#!/usr/bin/env python3
"""CL-56 共用交接执行入口。prepare 保存本地；publish 内含 prepare；check-cleanup 只读。

--request 是 handoff-workflow-request/v2 的单次 JSON 输入，放仓外或已忽略的 attempts。
字段/安全边界正本：handoff-protocol §3、§5、§6、§7。--help 不提供授权。
调用前会话必须核对本次 Owner 授权、业务条件和精确 paths；程序不证明授权文本来源。
发布适配：HANDOFF_GITLAB_MR_SCRIPT 指向现有 gitlab-mr-api/scripts/gitlab_mr.py，
使用其配置、GET 客户端、preflight 与 create/readback。GitHub 使用 HANDOFF_PLATFORM_CONFIG
与 gh-axi；MIGRATION.md 说明私有免费部署、普通 PR 和独立首次导入。不会修改全局配置。
JSON: handoff-workflow-result/v1；0 completed、1 blocked、2 not-checked/external-unknown。
申报的人写字段：path/instruction/authority_ref/classification；对齐级另有
before_after=[{before,after}]、semantic_statement=语义零变化。身份/状态/复核命令从 Git 生成。
"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, quote

sys.dont_write_bytecode = True
import handoff_platform as platform
import handoff_data as data
import handoff_lint as grammar
import handoff_status as reader
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'repo-layout'))
try:
    import history_read as history
except ImportError:
    history = None



def redact_local(message):
    result = str(message)
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GL_CSTHINK_HARNESS_PLANE_TOKEN', 'GL_HOST', 'GL_CSTHINK_HARNESS_PLANE_PROJECT'):
        value = os.environ.get(name)
        if value:
            result = result.replace(value, '[REDACTED_CONFIG]').replace(quote(value, safe=''), '[REDACTED_CONFIG]')
    return result


class Stop(RuntimeError):
    def __init__(self, reason, message, status='blocked'):
        super().__init__(message)
        self.reason, self.status = reason, status


def ensure(ok, reason, message, status='blocked'):
    if not ok:
        raise Stop(reason, message, status)


def dirty_paths(repo, ignored=False):
    args = ['status', '--porcelain=v1', '-z', '--untracked-files=all']
    if ignored:
        args.append('--ignored')
    raw = repo.run(*args)
    ensure(raw is not None, 'tool-unavailable', 'git status 未查成', 'not-checked')
    chunks = raw.split('\0'); paths = set(); i = 0
    while i < len(chunks) and chunks[i]:
        row = chunks[i]; paths.add(row[3:]); i += 1
        if 'R' in row[:2] or 'C' in row[:2]:
            paths.add(chunks[i]); i += 1
    return paths


def run_git(repo, *args):
    # Capture output; do not expose arbitrary configured URL or credentials.
    p = subprocess.run(['git', '-C', repo.root, *args], capture_output=True)
    ensure(p.returncode == 0, 'scope-mismatch', 'Git 动作失败: ' + ' '.join(args[:1]) + '；现场已保留')
    return p.stdout.decode().strip()


def check_refs(repo, q, commit, working=False):
    # Pause/resume needs only Git syntax; MR preparation verifies private originals.
    if q['mode']=='mr':
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'review-channel'))
        import review_evidence as evidence
        refs=list(q['authority_refs'])+[c[k] for c in q['conditions'] for k in ('requirement_ref','evidence_ref')]
        try:
            evidence.configured(repo.root)
            evidence.formal_refs(repo.root,refs,working)
            for original in q['handoff']['evidence']:
                if original['locator'].lstrip('#')=='review-result':
                    raw=evidence.fixed_file(repo.root,original['commit'],original['path'])['content']
                    evidence.verify_result(repo.root,raw)
        except evidence.EvidenceError as exc:raise Stop('evidence-missing',str(exc)) from exc
    for ref in q['authority_refs']:
        repo.locate(commit, ref)
    for c in q['conditions']:
        repo.locate(commit, c['requirement_ref']); repo.locate(commit, c['evidence_ref'])
    for e in q['handoff']['evidence']:
        ensure(repo.ancestor(e['commit'], commit), 'evidence-missing', e['commit'] + ': 不是内容祖先')
        repo.file(e['commit'], e['path'])
    reader.suggestion_refs(repo, q['handoff'], commit, f"HANDOFF/progress/{q['task']}.md", working=working)


def check_conditions(repo, q, task):
    if q['mode'] != 'mr':
        return
    ensure(all(c['result'] == 'met' for c in q['conditions']), 'conditions-unmet', '本批存在 unmet/not-checked 条件')
    # Full-task acceptance is identifiable when the caller declares the Definition itself.
    # Partial deliveries still require the caller to check the §5.1 terminal gate honestly.
    if task['category'] == grammar.CATEGORY_MILESTONE:
        definitions = [p for p in repo.files('HEAD') if p.startswith(f"tasks/{task['stem']}/") and
                       ('definition' in p.lower() or p.endswith('/task.md') or p.endswith('/' + task['stem'] + '.md'))]
        full = any(c['requirement_ref'].split('#')[0] in definitions and '#' not in c['requirement_ref'] for c in q['conditions'])
        ensure(not full or any(v in reader.TERMINAL_TYPES for v in reader.ruling_types(repo.root, task['stem'])),
               'conditions-unmet', '全部任务验收声明在场但无 done/close，先请 Owner 判 done')


def validate_working_entries(repo, q):
    for entry in q['handoff']['entries']:
        target = repo.safe_path(entry['path'])
        ensure(target.is_file() and not target.is_symlink(), 'evidence-missing', entry['path'] + ': 入口不是普通文件')
        if entry['role'] == 'history':
            ensure(target.read_bytes() == repo.file('HEAD', entry['path']), 'scope-mismatch', entry['path'] + ': 不可改写历史')
        for p in entry.get('sources', []):
            ensure(repo.safe_path(p).is_file(), 'evidence-missing', p + ': 生成源缺失')


def generators(repo, q):
    expected = [e['generator'] for e in q['handoff']['entries'] if e['role'] == 'generated']
    ensure(all(command in q['generators'] for command in expected), 'conditions-unmet', 'generated 入口缺本次精确命令授权，未运行生成器')
    for command in q['generators']:
        ensure(command in expected, 'scope-mismatch', '命令不在本批已核入口声明内')
        # Require a repository script, never inline shell/Python code or arbitrary external command.
        candidates = []
        for arg in command:
            try:
                data.path(arg)
                if (Path(repo.root) / arg).is_file():
                    candidates.append(arg)
            except data.Invalid:
                pass
        ensure(candidates and command[0] not in ('sh', 'bash', 'zsh', 'env') and
               '-c' not in command and '-m' not in command, 'scope-mismatch', 'generator 必须是已核仓内脚本入口')
        script = candidates[0]; repo.file('HEAD', script)
        ensure(command[0] == script or (Path(command[0]).name.startswith('python') and script in command[1:]),
               'scope-mismatch', 'generator 仅支持仓内可执行脚本或 Python 文件入口')
        allowed = {e['path'] for e in q['handoff']['entries'] if e.get('generator') == command}
        ensure(allowed <= set(q['paths']), 'scope-mismatch', '生成产物未列入 paths')
        before = working_fingerprints(repo)
        git_before = repo.resolve('HEAD')
        p = subprocess.run(command, cwd=repo.root, capture_output=True)
        after = working_fingerprints(repo)
        ensure(repo.resolve('HEAD') == git_before, 'scope-mismatch', 'generator 改动 Git HEAD')
        changed = {x for x in set(before) | set(after) if before.get(x) != after.get(x)}
        ensure(changed <= allowed, 'scope-mismatch', 'generator 越界改动: ' + ', '.join(sorted(changed - allowed)))
        ensure(p.returncode == 0, 'conditions-unmet', 'generator 失败，退出码 ' + str(p.returncode))


def working_fingerprints(repo):
    result = {}
    # Include ignored files: a generator cannot hide writes by relying on .gitignore.
    for root, dirs, files in os.walk(repo.root, followlinks=False):
        dirs[:] = [d for d in dirs if d != '.git']
        for name in files:
            p = Path(root) / name; rel = p.relative_to(repo.root).as_posix()
            if rel == '.git':
                continue
            result[rel] = ('symlink:' + os.readlink(p)) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def prepare(repo, q):
    data.request(q)
    branch = repo.need('symbolic-ref', '--short', 'HEAD')
    ensure(branch != 'main', 'scope-mismatch', 'main 不承载交接写入')
    worktrees = repo.worktrees()
    ensure(worktrees.get(branch) == str(Path(repo.root).resolve()), 'scope-mismatch', '当前分支工作区归属不符')
    paths = set(q['paths'])
    for p in paths:
        repo.safe_path(p)
    unknown = dirty_paths(repo) - paths
    ensure(not unknown, 'scope-mismatch', '未声明改动: ' + ', '.join(sorted(unknown)))
    tasks, errors = grammar.load_progress(repo.root)
    task = next((t for t in tasks if t['stem'] == q['task']), None)
    ensure(task is not None, 'input-invalid', '任务进度文件不存在')
    bad = [e for e in errors if e['severity'] != 'warning' and e['file'] == task['file']]
    ensure(not bad, 'input-invalid', str(bad))
    ctx_event = reader.last_event(task, 'context')
    ensure(ctx_event is not None, 'ambiguous-context', '需要先按获授权意图追加 context')
    ctx = ctx_event['data']
    ensure(ctx['source_branch'] == branch, 'scope-mismatch', 'context.source_branch 不匹配当前分支')
    ensure(repo.ancestor(ctx['base_commit'], 'HEAD'), 'evidence-missing', 'base 不在 source 历史中')
    main = repo.resolve('main')
    ensure(repo.ancestor(main, 'HEAD') or repo.ancestor('HEAD', main), 'scope-mismatch', 'source 与 main 分叉')
    check_conditions(repo, q, task)
    check_refs(repo, q, 'HEAD', working=True); repo.locate('HEAD', ctx['authority_ref'])
    validate_working_entries(repo, q)
    generators(repo, q)
    ensure(not dirty_paths(repo) - paths, 'scope-mismatch', '生成后出现未声明改动')
    changed = dirty_paths(repo)
    if (not changed and reader.last_event(task, 'handoff') and
            ctx_event['line'] < reader.last_event(task, 'handoff')['line']):
        proof = reader.validate_handoff(repo, task)
        head = repo.resolve('HEAD')
        if q['mode'] == 'mr' and repo.ancestor(head, main):
            reader.check_later(repo, proof, task, head)
            return proof
        expected = dict(version=2, mode=q['mode'], content_commit=proof['content_commit'], **q['handoff'])
        if proof['handoff_commit'] == head and proof['handoff'] == expected:
            return proof
        # A new request is a new handoff. Never rewrite the previous line.
    if changed:
        run_git(repo, 'add', '--', *sorted(changed))
        run_git(repo, 'diff', '--cached', '--check')
        run_git(repo, 'commit', '-m', f"docs: prepare {q['task']} handoff content")
    c = repo.resolve('HEAD')
    committed = repo.task_at(c, q['task'])
    ensure(reader.last_event(committed, 'context')['data'] == ctx, 'ambiguous-context', 'context 未进入内容提交')
    check_refs(repo, q, c)
    for e in q['handoff']['entries']:
        repo.file(c, e['path'])
        for src in e.get('sources', []):
            repo.file(c, src)
    record = dict(version=2, mode=q['mode'], content_commit=c, **q['handoff']); data.handoff(record)
    at = datetime.now().astimezone().isoformat(timespec='minutes')
    line = f'- {at} · handoff · ' + json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n'
    ensure(not dirty_paths(repo), 'scope-mismatch', '内容提交后出现新改动')
    with repo.safe_path(task['file']).open('a', encoding='utf-8') as f:
        f.write(line)
    ensure(dirty_paths(repo) == {task['file']}, 'scope-mismatch', 'H 追加范围超出本任务进度')
    run_git(repo, 'add', '--', task['file'])
    run_git(repo, 'commit', '-m', f"docs: handoff {q['task']} ({q['mode']})")
    return reader.validate_handoff(repo, repo.task_at('HEAD', q['task']))


def frozen_state(repo, commit):
    objects, rows = {}, []
    for p in repo.files(commit):
        if re.fullmatch(r'records/governance/[^/]+/freeze-records\.jsonl', p):
            parsed = [data.loads(l) for l in repo.blob(commit, p).decode().splitlines()]
            for n, row in enumerate(parsed, 1):
                for o in row['objects']:
                    objects[o['path']] = {'state': '历史已退役' if row['event'] == 'retire' else 'freeze-record',
                                         'record': p, 'revision': row['revision'], 'object': o}
                rows.append((p, n, row))
    return objects, rows


def identity(repo, commit, path):
    try:
        b = repo.blob(commit, path)
    except reader.Unavailable:
        return None
    return dict(bytes=len(b), sha256=hashlib.sha256(b).hexdigest())


def describe(repo, q, proof, base):
    if history is None:
        raise Stop('history-unavailable', 'shared helper absent', 'not-checked')
    h = proof['handoff_commit']; changed = sorted(repo.changed(base, h))
    # Keep each command bound to the fixed commits while avoiding oversized MR responses.
    command_base = repo.need('rev-parse', '--short=12', base)
    command_h = repo.need('rev-parse', '--short=12', h)
    ensure(repo.resolve(command_base) == base and repo.resolve(command_h) == h,
           'evidence-missing', '复核命令的提交缩写未唯一解析到固定基线与交接提交')
    before, old_rows = frozen_state(repo, base); after, rows = frozen_state(repo, h)
    # Existing governance evidence cannot be rewritten while preparing a publication.
    for path in {p for p, _, _ in old_rows}:
        ensure(repo.blob(h, path).startswith(repo.blob(base, path)), 'conditions-unmet', path + ': 历史冻结行被改写')
    human = {v['path']: v for v in q['mr']['declarations']}
    legacy_locks = {}
    lock_path = 'records/lock-declarations.jsonl'
    lock_bytes = None
    if lock_path in repo.files(base):
        lock_bytes = repo.blob(base, lock_path)
    else:
        try:
            lock_bytes = history.read_history(repo.root, base, lock_path)['content']
        except history.HistoryReadError as exc:
            if exc.code != 'history-not-found':
                raise Stop('history-unavailable', exc.code + ': ' + exc.message, 'not-checked')
    if lock_bytes is not None:
        for line in lock_bytes.decode().splitlines():
            lock = data.loads(line)
            lock_file = lock.get('path') or lock.get('target')
            if isinstance(lock_file, str):
                if lock.get('kind', lock.get('event')) == 'lock':
                    legacy_locks[lock_file] = lock
                elif lock.get('kind', lock.get('event')) in ('unlock', 'retire'):
                    legacy_locks.pop(lock_file, None)
    old_set = {(p, n) for p, n, row in old_rows}
    new_rows = [(p, n, row) for p, n, row in rows if (p, n) not in old_set]
    trigger = lambda p: p in before or p in after or p in legacy_locks or p.startswith(('decisions/', 'reviews/', 'records/governance/')) or bool(re.match(r'tasks/[^/]+/(reviews|rulings)/', p)) or p in ('.gitlab-ci.yml', 'mechanisms/gates/hooks/pre-commit', 'records/evidence-locks.jsonl', 'records/lock-declarations.jsonl', 'records/authorizations.jsonl')
    required = {p for p in changed if trigger(p)}
    ensure(set(human) == required, 'input-invalid', '申报路径缺失或多余: ' + ', '.join(sorted(set(human) ^ required)))
    out = [q['mr']['summary'], '', f'交接提交: `{h}`；目标基线: `{base}`。', '', '## 申报二', '', '| 路径 | 构成 |', '|---|---|']
    for p in changed:
        category = '机械证据' if p.startswith(('records/governance/', 'reviews/')) or '/reviews/' in p else '实质改动'
        out.append(f'| `{p}` | {category} |')
    out.extend(['', '## 申报三'])
    renames = {}
    names = repo.need('diff', '--name-status', '-z', '--find-renames', base, h).split('\0')
    i = 0
    while i < len(names) and names[i]:
        code = names[i]; i += 1
        if code.startswith('R'):
            old_name, new_name = names[i:i+2]; i += 2
            renames[old_name] = renames[new_name] = f'改名：{old_name} → {new_name}'
        else:
            i += 1
    for p in sorted(required):
        d = human[p]; repo.locate(h, d['authority_ref'])
        old = identity(repo, base, p); new = identity(repo, h, p)
        kind = renames.get(p) or ('新增' if old is None else '删除' if new is None else '修改')
        state = after.get(p) or before.get(p) or ({'state': '历史活跃 lock', 'record': 'records/lock-declarations.jsonl', 'lock': legacy_locks[p]} if p in legacy_locks else {'state': '无冻结记录'})
        # A frozen object's submitted bytes must match the actual frozen record.
        if p in after and after[p]['state'] == 'freeze-record':
            ensure(new == {k: after[p]['object'][k] for k in ('bytes', 'sha256')}, 'conditions-unmet', p + ': 已审/冻结字节变化，需走治理程序')
        out.extend(['', f'### `{p}`', '', f'- 改动类别：{kind}', '- 冻结状态：' + json.dumps(state, ensure_ascii=False),
                    '- 旧身份：' + json.dumps(old, ensure_ascii=False), '- 新身份：' + json.dumps(new, ensure_ascii=False),
                    f"- 授权：{d['instruction']}；{d['authority_ref']}", f"- 分级：{d['classification']}"])
        if d['classification'] == '对齐级':
            out.append('- 语义零变化；逐处对照：' + json.dumps(d['before_after'], ensure_ascii=False))
        out.extend(['', '```bash', 'git diff --stat ' + command_base + ' ' + command_h + ' -- ' + shlex.quote(p),
                    'git show ' + shlex.quote(command_base + ':' + p) + ' | shasum -a 256',
                    'git show ' + shlex.quote(command_h + ':' + p) + ' | shasum -a 256',
                    'git diff ' + command_base + ' ' + command_h + ' -- ' + shlex.quote(p)])
        if state.get('record'):
            out.append('git show ' + shlex.quote(command_h + ':' + state['record']) + ' | tail -n 1')
        out.append('```')
    if new_rows:
        out.extend(['', '## 本次新增冻结记录'])
        for p, n, row in new_rows:
            # Verify at the commit that introduced the immutable row. Later revisions
            # in the same MR must not be compared to an earlier frozen identity.
            raw = repo.blob(h, p).splitlines()[n-1]
            origins = []
            for commit in repo.need('log', '--format=%H', h, '--', p).splitlines():
                try:
                    content = repo.blob(commit, p).splitlines()
                except reader.Unavailable:
                    continue
                if raw not in content:
                    continue
                parents = repo.need('rev-list', '--parents', '-n', '1', commit).split()[1:]
                found_before = False
                for parent in parents:
                    try:
                        found_before |= raw in repo.blob(parent, p).splitlines()
                    except reader.Unavailable:
                        pass
                if not found_before:
                    origins.append(commit)
            ensure(len(origins) == 1, 'conditions-unmet', p + ': 冻结行来源不唯一')
            if row['event'] != 'retire':
                for o in row['objects']:
                    ensure(identity(repo, origins[0], o['path']) == {k: o[k] for k in ('bytes', 'sha256')},
                           'conditions-unmet', p + ': 冻结提交对象身份不符')
            # Retirement records preserve the last frozen identity, not a deleted HEAD blob.
            else:
                prior = [x for fp, ln, x in rows if fp == p and ln < n and x['event'] != 'retire']
                if prior:
                    ensure(row['objects'] == prior[-1]['objects'], 'conditions-unmet', p + ': 退役身份不符')
            out.append(f'- `{p}:{n}`：' + json.dumps(row, ensure_ascii=False))
    return '\n'.join(out) + '\n'


class Adapter:
    """Reuse the existing platform script. No replacement HTTP client or retries."""
    def __init__(self, repo, expected_identity=None):
        script = os.environ.get('HANDOFF_GITLAB_MR_SCRIPT', '')
        ensure(script and Path(script).is_file(), 'tool-unavailable', 'HANDOFF_GITLAB_MR_SCRIPT 不可用', 'not-checked')
        spec = importlib.util.spec_from_file_location('_handoff_gitlab_adapter', script)
        ensure(spec is not None and spec.loader is not None, 'tool-unavailable', '适配脚本不可载入', 'not-checked')
        self.module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        m = self.module
        ensure(all(callable(getattr(m, n, None)) for n in ('load_config', 'GitLabClient', 'run_preflight', 'verify_created_merge_request', 'main')),
               'tool-unavailable', '适配脚本不满足现有契约', 'not-checked')
        self.script, self.repo = script, repo
        try:
            self.config = m.load_config(True)
            if expected_identity is not None:
                ensure(self.config.host == expected_identity['host'] and self.config.project == expected_identity['repository'],
                       'remote-mismatch', 'GitLab 配置与已批准源身份不一致')
            self.client = m.GitLabClient(self.config)
        except Stop:
            raise
        except Exception as e:
            raise Stop('tool-unavailable', self.clean(e), 'not-checked') from e
        origin = repo.need('remote', 'get-url', 'origin')
        if '://' in origin:
            u = urlsplit(origin); host, project = u.hostname, u.path.lstrip('/')
        else:
            match = re.fullmatch(r'(?:[^@]+@)?([^:]+):(.+)', origin)
            ensure(match is not None, 'remote-mismatch', 'origin 不是可核对的 GitLab URL')
            host, project = match.groups()
        ensure(host == urlsplit(self.config.host).hostname and project.removesuffix('.git') == self.config.project,
               'remote-mismatch', 'origin 与配置 project/host 不匹配')

    def clean(self, error):
        token = os.environ.get('GL_CSTHINK_HARNESS_PLANE_TOKEN', '')
        m = self.module
        return redact_local(m.redact(str(error), token)) if hasattr(m, 'redact') else 'adapter 错误（无安全脱敏接口）'

    provider = 'gitlab'
    display_name = 'MR'

    def inspect_repository(self):
        try:
            project = self.client.request('GET', '/projects/' + self.config.project_encoded)
        except Exception as exc:
            raise Stop('tool-unavailable', self.clean(exc), 'not-checked') from exc
        ensure(project.get('path_with_namespace') == self.config.project and type(project.get('id')) is int,
               'remote-mismatch', 'GitLab API project 身份不符')
        push_urls = self.repo.need('remote', 'get-url', '--push', '--all', 'origin').splitlines()
        ensure(len(push_urls) == 1 and platform.git_address(push_urls[0]) ==
               platform.git_address(self.repo.need('remote', 'get-url', 'origin')),
               'remote-mismatch', 'origin push 地址不一致')
        self.repository = project
        return dict(provider='gitlab', host=self.config.host, repository=self.config.project, repository_id=str(project['id']))

    def find_change_requests(self, source, target):
        m, c = self.module, self.config
        try:
            project = self.client.request('GET', '/projects/' + c.project_encoded)
            ensure(project.get('path_with_namespace') == c.project, 'remote-mismatch', 'API project 不匹配')
            result = []
            for page in range(1, 101):
                rows = self.client.request('GET', f'/projects/{c.project_encoded}/merge_requests', query={
                    'state': 'all', 'source_branch': source, 'target_branch': target, 'per_page': '100', 'page': str(page)})
                ensure(type(rows) is list, 'tool-unavailable', 'MR GET 返回值不是列表', 'not-checked')
                result.extend(rows)
                if len(rows) < 100:
                    return result
            raise Stop('tool-unavailable', 'MR GET 分页未穷尽', 'not-checked')
        except Stop:
            raise
        except Exception as e:
            raise Stop('tool-unavailable', self.clean(e), 'not-checked') from e

    def read_change_request(self, iid):
        try:
            return self.client.request('GET', f'/projects/{self.config.project_encoded}/merge_requests/{iid}')
        except Exception as e:
            raise Stop('tool-unavailable', self.clean(e), 'not-checked') from e

    def create_change_request(self, ctx, h, mr, description, target_sha):
        try:
            preflight = self.module.run_preflight(self.client, self.config, ctx['source_branch'], ctx['target_branch'], h)
            ensure(preflight['target_sha'] == target_sha and not preflight['duplicate_open_merge_request_count'],
                   'remote-mismatch', '发布前置后目标或已有 MR 改变')
        except Stop:
            raise
        except Exception as e:
            raise Stop('tool-unavailable', self.clean(e), 'not-checked') from e
        with tempfile.TemporaryDirectory(prefix='handoff-mr-') as temp:
            path = Path(temp) / 'description.md'; path.write_text(description)
            args = [sys.executable, '-B', self.script, 'create', '--source-branch', ctx['source_branch'],
                    '--target-branch', ctx['target_branch'], '--expected-source-sha', h,
                    '--title', mr['title'], '--description-file', str(path), '--execute']
            if self.config.host.startswith('http://'):
                args.append('--allow-insecure-http')
            p = subprocess.run(args, cwd=self.repo.root, capture_output=True, text=True)
            if p.returncode:
                raise Stop('external-unknown', self.clean(p.stderr), 'external-unknown')
            try:
                out = data.loads(p.stdout)
                return self.read_change_request(out['iid'])
            except Exception as e:
                raise Stop('external-unknown', self.clean(e), 'external-unknown') from e


def remote_refs(repo, ctx):
    try:
        p = subprocess.run(['git', '-C', repo.root, 'ls-remote', '--heads', 'origin',
                            'refs/heads/' + ctx['source_branch'], 'refs/heads/' + ctx['target_branch']], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop('tool-unavailable', '真实远端引用未查成', 'not-checked') from exc
    ensure(p.returncode == 0, 'tool-unavailable', '真实远端引用未查成', 'not-checked')
    refs = {}
    for line in p.stdout.splitlines():
        sha, ref = line.split('\t'); data.sha(sha); refs[ref.removeprefix('refs/heads/')] = sha
    ensure(ctx['target_branch'] in refs, 'remote-mismatch', '远端目标分支不存在；首次导入须使用独立 migration 入口')
    return refs


def verify_mr(value, ctx, h, states=('opened', 'merged')):
    actual = value.get('sha') or value.get('diff_refs', {}).get('head_sha')
    ensure(type(value.get('iid')) is int and value.get('web_url') and
           value.get('source_branch') == ctx['source_branch'] and value.get('target_branch') == ctx['target_branch'] and
           actual == h and value.get('state') in states, 'duplicate-mr', '既有/回读 MR 的状态或 source/target/SHA 不符')
    return dict(id=value['iid'], url=value['web_url'], source=ctx['source_branch'], target=ctx['target_branch'], sha=h, state=value['state'])


def select_adapter(repo):
    if os.environ.get('HANDOFF_PLATFORM_CONFIG'):
        return platform.GitHubAdapter(repo)
    if platform.git_address(repo.need('remote', 'get-url', 'origin'))[0] == 'github.com':
        raise Stop('input-invalid', 'GitHub origin 缺少显式平台配置', 'not-checked')
    return Adapter(repo)


def publish(repo, q, adapter_factory=None):
    data.request(q)
    ensure(q['mode'] == 'mr', 'input-invalid', 'publish 必须使用 mr 模式')
    ensure(all(c['result'] == 'met' for c in q['conditions']), 'conditions-unmet', '发布条件尚未满足')
    ensure(repo.need('symbolic-ref', '--short', 'HEAD') != 'main', 'conditions-unmet', '日常 publish 拒绝 main 直推')
    adapter = (adapter_factory or select_adapter)(repo)
    bound_identity = adapter.inspect_repository()
    # Before migrating a v1 MR handoff, resolve any original external result by
    # its original source/target/SHA. No local commit or remote write precedes GET.
    old_path = f"HANDOFF/progress/{q['task']}.md"
    old_task = repo.task_at('HEAD', q['task']) if old_path in repo.files('HEAD') else None
    old_event = reader.last_event(old_task, 'handoff') if old_task else None
    old_context = next((e for e in reversed(old_task['events'])
                        if e['type'] == 'context' and old_event and e['line'] < old_event['line']), None) if old_task else None
    if (old_event and old_event['data']['version'] == 1 and old_event['data']['mode'] == 'mr'
            and old_context and old_context['data']['source_branch'] == repo.need('symbolic-ref', '--short', 'HEAD')):
        check_conditions(repo, q, old_task)
        original_task = dict(old_task, events=[e for e in old_task['events'] if e['line'] <= old_event['line']])
        old = reader.validate_handoff(repo, original_task)
        ctx = old['context']; old_h = old['handoff_commit']
        ensure(repo.need('symbolic-ref', '--short', 'HEAD') == ctx['source_branch'],
               'scope-mismatch', '旧发布恢复须在原 source')
        refs = remote_refs(repo, ctx)
        existing = adapter.find_change_requests(ctx['source_branch'], ctx['target_branch'])
        ensure(len(existing) <= 1, 'duplicate-mr', '同 source/target 存在多个 MR')
        if existing:
            return old, verify_mr(adapter.read_change_request(existing[0]['iid']), ctx, old_h), 'none'
        ensure(refs.get(ctx['source_branch']) in (None, old_h), 'remote-mismatch', '旧发布 source SHA 不一致')
        target = refs[ctx['target_branch']]
        ensure(repo.ref_exists(target), 'remote-mismatch', '远端 target 不在本地历史')
        if not dirty_paths(repo) and repo.ancestor(repo.resolve('HEAD'), target):
            return old, None, 'already-landed'
    proof = prepare(repo, q); ctx = proof['context']; h = proof['handoff_commit']
    refs = remote_refs(repo, ctx); target = refs[ctx['target_branch']]
    ensure(repo.ref_exists(target), 'remote-mismatch', '远端 target 不在本地历史，请按授权同步后重新准备')
    ensure(repo.ancestor(target, h) or repo.ancestor(h, target), 'remote-mismatch', 'source 与真实远端 target 分叉')
    existing = adapter.find_change_requests(ctx['source_branch'], ctx['target_branch'])
    ensure(len(existing) <= 1, 'duplicate-mr', '同 source/target 存在多个 MR')
    if existing:
        return proof, verify_mr(adapter.read_change_request(existing[0]['iid']), ctx, h), 'none'
    if repo.ancestor(h, target):
        return proof, None, 'already-landed'
    description = describe(repo, q, proof, target)
    source = refs.get(ctx['source_branch'])
    ensure(source is None or source == h or repo.ancestor(source, h), 'remote-mismatch', '远端 source 不是 H 或其已知祖先；不改写远端分叉')
    ensure(repo.resolve('HEAD') == h and not dirty_paths(repo), 'stale-handoff', 'prepare 后现场改变')
    # Freeze input and all generated-source bytes in H; recheck target just before external writes.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'review-channel'))
    import review_evidence as evidence
    try:
        if evidence.storage_mode(repo.root)=='archive-v1':
            evidence.verify_new_commits(repo.root,target,h,source)
    except evidence.EvidenceError as exc:raise Stop('evidence-missing',str(exc)) from exc
    ensure(adapter.inspect_repository() == bound_identity, 'remote-mismatch', '平台仓库身份在准备后改变')
    ensure(remote_refs(repo, ctx) == refs, 'remote-mismatch', '远端在准备后改变')
    if source != h:
        try:
            p = subprocess.run(['git', '-C', repo.root, 'push', 'origin', f'{h}:refs/heads/{ctx["source_branch"]}'], capture_output=True, timeout=60)
            pushed = p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pushed = False
        if not pushed:
            try:
                observed = remote_refs(repo, ctx)
                matches = adapter.find_change_requests(ctx['source_branch'], ctx['target_branch'])
                detail = 'source 已为 H' if observed.get(ctx['source_branch']) == h else 'source 尚未核成 H'
                if len(matches) == 1:
                    verify_mr(adapter.read_change_request(matches[0]['iid']), ctx, h)
            except (Stop, platform.PlatformError):
                detail = '读回未完成'
            raise Stop('external-unknown', 'push 结果不确定；已停止写入并对账：' + detail, 'external-unknown')
    ensure(repo.resolve('HEAD') == h and not dirty_paths(repo), 'stale-handoff', 'push 前后现场改变')
    after = remote_refs(repo, ctx)
    ensure(after.get(ctx['source_branch']) == h and after.get(ctx['target_branch']) == target, 'remote-mismatch', 'push 回读 source/target 改变')
    try:
        raw = adapter.create_change_request(ctx, h, q['mr'], description, target)
    except (Stop, platform.PlatformError) as exc:
        if exc.status != 'external-unknown':
            raise
        try:
            observed = remote_refs(repo, ctx)
            matches = adapter.find_change_requests(ctx['source_branch'], ctx['target_branch'])
            ensure(observed.get(ctx['source_branch']) == h and observed.get(ctx['target_branch']) == target and len(matches) == 1,
                   'external-unknown', '创建失联后未取得唯一对应对象', 'external-unknown')
            raw = adapter.read_change_request(matches[0]['iid'])
            ensure(raw.get('title') == q['mr']['title'] and raw.get('description') == description,
                   'external-unknown', '创建失联后完整申报未核成', 'external-unknown')
        except (Stop, platform.PlatformError) as read_error:
            raise Stop('external-unknown', '创建结果不确定；GET/refs 对账未完成，未重试写入', 'external-unknown') from read_error
    try:
        final_refs = remote_refs(repo, ctx)
        ensure(final_refs.get(ctx['source_branch']) == h and final_refs.get(ctx['target_branch']) == target,
               'remote-mismatch', '创建回读期间 source/target 改变')
        ensure(repo.resolve('HEAD') == h and not dirty_paths(repo), 'stale-handoff', '创建回读期间本地现场改变')
        result = verify_mr(raw, ctx, h, ('opened',))
    except Stop as e:
        raise Stop('external-unknown', str(e), 'external-unknown') from e
    return proof, result, 'none'


def check_cleanup(repo, task, h):
    data.sha(h); t = repo.task_at(h, task); proof = reader.validate_handoff(repo, t, h)
    ensure(proof['handoff_commit'] == h, 'stale-handoff', 'source SHA 不是所给交接 H')
    ensure(repo.ancestor(h, 'main'), 'evidence-missing', '本地 main 未含实际 source SHA')
    current = repo.task_at('main', task); reader.check_later(repo, proof, current, 'main')
    worktrees = repo.worktrees()
    source_path = worktrees.get(proof['context']['source_branch'])
    for path in set(filter(None, (repo.root, source_path, worktrees.get('main')))):
        scoped = reader.Repository(path)
        # Only the source worktree will be removed. Preserve ignored material in
        # retained checkouts; tracked/untracked changes still block the check.
        removing = path == source_path
        leftovers = dirty_paths(scoped, ignored=removing)
        kinds = 'tracked/untracked/ignored' if removing else 'tracked/untracked'
        ensure(not leftovers, 'scope-mismatch', path + ': 仍有 ' + kinds + ' 材料: ' + ', '.join(sorted(leftovers)))
    # Only local proof. Platform merged state/source SHA and outside-worktree materials remain caller checks.
    return proof


def main(argv=None, *, required_provider=None, description=None):
    parser = argparse.ArgumentParser(description=description or __doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('publish',) if required_provider == 'github' else ('prepare', 'publish', 'check-cleanup'))
    parser.add_argument('--root', default='.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--request', required=required_provider == 'github')
    parser.set_defaults(task=None, source_sha=None)
    if required_provider != 'github':
        parser.add_argument('--task')
        parser.add_argument('--source-sha')
    a = parser.parse_args(argv)
    out = dict(schema='handoff-workflow-result/v1', action=a.action, status='not-checked', reason='none', task=a.task,
               content_commit=None, handoff_commit=None, mr=None, details=[])
    try:
        repo = reader.Repository(str(Path(a.root).resolve()))
        if required_provider == 'github':
            platform.load_config(repo)
        if a.action == 'check-cleanup':
            data.require(a.task is not None and a.source_sha is not None and a.request is None, 'check-cleanup 需要 task/source-sha')
            proof = check_cleanup(repo, a.task, a.source_sha)
            out['details'].append('仅核本地 main、source SHA、交接与工作区材料；平台合并事实和仓外唯一材料由整理会话核实；未删除任何内容')
        else:
            data.require(a.request is not None and a.task is None and a.source_sha is None, 'prepare/publish 仅接受 --request')
            path = Path(a.request).resolve()
            if path.is_relative_to(Path(repo.root)):
                rel = path.relative_to(repo.root).as_posix()
                data.require(('attempts' in path.parts or 'review-attempts' in path.parts) and
                             repo.run('check-ignore', '--', rel) is not None, '请求须在仓外或已忽略的本地暂存')
            q = data.loads(path.read_text()); data.request(q); out['task'] = q['task']
            if a.action == 'publish':
                proof, out['mr'], out['reason'] = publish(repo, q)
                if out['mr']:
                    label = 'GitHub PR' if out['mr']['url'].startswith('https://github.com/') else 'GitLab MR'
                    out['details'].append(label + ' 已回读；仅发布，不含合并和清理')
            else:
                proof = prepare(repo, q)
        out.update(status='completed', content_commit=proof['content_commit'], handoff_commit=proof['handoff_commit'])
    except (Stop, platform.PlatformError) as e:
        out.update(status=e.status, reason=e.reason); out['details'].append(str(e))
    except reader.Unavailable as e:
        out.update(status='not-checked', reason=e.reason); out['details'].append(str(e))
    except data.Invalid as e:
        out.update(status='not-checked' if isinstance(e, data.Unsupported) else 'blocked', reason='input-invalid'); out['details'].append(str(e))
    except Exception as e:
        out.update(status='not-checked', reason='tool-unavailable'); out['details'].append(type(e).__name__ + ': 执行未查成，原始异常未输出')
    out['details'] = [redact_local(x) for x in out['details']]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out['status'] == 'completed' else 1 if out['status'] == 'blocked' else 2


if __name__ == '__main__':
    sys.exit(main())
