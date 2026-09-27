#!/usr/bin/env python3
"""CL-57 独立首次导入：check/import/verify --request <仓外 JSON>。

不执行切换、业务提交、合并、补推或删除。import 需要当前会话对精确计划的写入授权。
计划与批准 JSON 块见同机制的 MIGRATION.md；调用者核 Owner 授权真实性与资产处置。
结果 handoff-migration-result/v2：0 completed，1 blocked，2 not-checked/external-unknown。
"""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
import handoff_data as data
import handoff_platform as platform
import handoff_status as reader
import handoff_workflow as flow


REQUEST_SCHEMA = 'handoff-migration-request/v2'
PLAN_SCHEMA = 'handoff-migration-plan/v2'
RESULT_SCHEMA = 'handoff-migration-result/v2'
# Per-command options only: no config/known_hosts/agent mutation or prompt.
SSH_COMMAND = ('ssh -oBatchMode=yes -oStrictHostKeyChecking=yes -oUpdateHostKeys=no '
               '-oCanonicalizeHostname=no -oVerifyHostKeyDNS=no -oControlMaster=no -oControlPath=none')


class Stop(RuntimeError):
    def __init__(self, reason, message, status='blocked'):
        super().__init__(message)
        self.reason, self.status = reason, status


def require(ok, reason, message, status='blocked'):
    if not ok:
        raise Stop(reason, message, status)


def identity(value, provider):
    data.obj(value, 'provider host repository repository_id')
    require(value['provider'] == provider and isinstance(value['repository_id'], str) and
            re.fullmatch(r'[1-9][0-9]*', value['repository_id']), 'input-invalid', '迁移仓库身份错误')
    require(isinstance(value['repository'], str) and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+', value['repository']),
            'input-invalid', '迁移项目路径错误')
    require(isinstance(value['host'], str) and
            re.fullmatch(r'https?://[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*', value['host']),
            'input-invalid', 'API host 必须是无凭据、无路径和端口的 HTTP/HTTPS 根地址')
    if provider == 'github':
        require(value['host'] == 'https://github.com' and value['repository'].count('/') == 1, 'input-invalid', '不支持的目标 host')


def git_url(value, identity):
    require(isinstance(value, str), 'input-invalid', 'Git 地址须为字符串')
    # Accept only the frozen forms, with the scheme-specific default port implicit.
    require(re.fullmatch(r'(?:https://|ssh://git@|git@)[A-Za-z0-9.-]+[/:][A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.git', value),
            'input-invalid', 'Git 地址格式不支持或含凭据/端口')
    try:
        actual = platform.git_address(value)
        if '://' in value:
            u = urlsplit(value)
            require(u.port in (None, 443 if u.scheme == 'https' else 22),
                    'input-invalid', 'Git 地址使用非默认端口')
    except (platform.PlatformError, ValueError):
        raise Stop('input-invalid', 'Git 地址格式不支持') from None
    require(actual == (urlsplit(identity['host']).hostname, identity['repository']),
            'identity-mismatch', 'Git 地址与 API 身份不一致')


def api_git_urls(metadata, identity, selected):
    keys = ('http_url_to_repo', 'ssh_url_to_repo') if identity['provider'] == 'gitlab' else ('clone_url', 'ssh_url')
    for key in keys:
        value = metadata.get(key)
        require(isinstance(value, str), 'identity-mismatch', 'API 缺少 Git 地址')
        # GitLab advertises HTTP even when the approved Git transport is SSH.
        if key == 'http_url_to_repo' and value.startswith('http://'):
            value = 'https://' + value[len('http://'):]
        git_url(value, identity)
    advertised = metadata[keys[0] if selected.startswith('https://') else keys[1]]
    if advertised.startswith('http://'):
        advertised = 'https://' + advertised[len('http://'):]
    require(platform.git_address(advertised) == platform.git_address(selected),
            'identity-mismatch', 'API Git 地址与批准地址不一致')


def ref_rows(rows):
    data.array(rows, lambda r: data.obj(r, 'ref oid'), nonempty=True)
    for row in rows:
        ref, oid = row['ref'], row['oid']
        data.text(ref); data.sha(oid)
        require(oid != '0' * 40 and ref.startswith(('refs/heads/', 'refs/tags/')) and
                subprocess.run(['git', 'check-ref-format', ref], capture_output=True).returncode == 0,
                'input-invalid', '仅接受合法完整 heads/tags 和非零 SHA-1')
    require(len({r['ref'] for r in rows}) == len(rows), 'input-invalid', '重复 ref')
    require(any(r['ref'] == 'refs/heads/main' for r in rows), 'input-invalid', '清单缺 main')


def request(q):
    data.obj(q, 'schema plan_ref approval_ref source target source_git_url target_git_url refs')
    require(q['schema'] == REQUEST_SCHEMA, 'input-invalid', '未知迁移请求版本')
    for key in ('plan_ref', 'approval_ref'):
        data.obj(q[key], 'commit path' + (' locator' if key == 'approval_ref' else ''))
        data.sha(q[key]['commit']); data.path(q[key]['path'])
    data.text(q['approval_ref']['locator'])
    require(q['plan_ref']['path'].startswith('records/diagnostics/'), 'input-invalid', '计划须在诊断规划落点')
    require(q['approval_ref']['path'].startswith(('records/governance/', 'HANDOFF/progress/')),
            'input-invalid', '批准须在正式决定或进度落点')
    identity(q['source'], 'gitlab'); identity(q['target'], 'github'); ref_rows(q['refs'])
    for side in ('source', 'target'):
        git_url(q[side + '_git_url'], q[side])


def block(repo, ref, label):
    raw = repo.file(ref['commit'], ref['path'])
    require(raw is not None, 'object-missing', label + ' 引用不存在')
    matches = re.findall(r'^```' + label + r'\n(.*?)\n```[ \t]*$', raw.decode(), re.M | re.S)
    require(len(matches) == 1, 'input-invalid', label + ' 需要唯一 JSON 块')
    return data.loads(matches[0])


def git_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    return env


def run(root, args, reason='transport-unavailable'):
    try:
        p = subprocess.run(['git', '-c', 'core.sshCommand=' + SSH_COMMAND, '-c', 'ssh.variant=ssh',
                            '-c', 'http.followRedirects=false', '-C', str(root), *args], capture_output=True, timeout=60, env=git_environment())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop(reason, 'Git 操作未查成；未输出原始连接信息', 'not-checked') from exc
    require(p.returncode == 0, reason, 'Git ' + args[0] + ' 未查成；保留现场', 'not-checked')
    return p.stdout


class Transport:
    """Use the approved Git addresses; never derive them from API hosts or origin."""
    def __init__(self, repo, q, target_only=False):
        self.repo, self.q = repo, q
        self.urls = {side: q[side + '_git_url'] for side in
                     (('target',) if target_only else ('source', 'target'))}
        for address in self.urls.values():
            self.check_address(repo.root, address)

    @staticmethod
    def check_address(root, address):
        require(run(root, ['ls-remote', '--get-url', address]).decode().strip() == address,
                'identity-mismatch', 'Git URL 重写不等于已批准地址')
        if address.startswith(('git@', 'ssh://')):
            host, _ = platform.git_address(address)
            try:
                result = subprocess.run([*SSH_COMMAND.split(), '-G', 'git@' + host],
                                        capture_output=True, text=True, timeout=15, env=git_environment())
            except (OSError, subprocess.TimeoutExpired):
                raise Stop('transport-unavailable', 'SSH 配置未查成', 'not-checked') from None
            config = dict(line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line)
            require(result.returncode == 0 and config.get('hostname') == host and
                    config.get('user') == 'git' and config.get('port') == '22' and
                    config.get('hostkeyalias', 'none') == 'none',
                    'identity-mismatch', 'SSH 实际主机/用户/端口或主机密钥别名不等于批准身份')

    def refs(self, side):
        self.check_address(self.repo.root, self.urls[side])
        raw = run(self.repo.root, ['ls-remote', '--symref', self.urls[side], 'refs/heads/*', 'refs/tags/*']).decode()
        refs = {}
        for line in raw.splitlines():
            oid, ref = line.split('\t')
            require(not oid.startswith('ref:'), 'conditions-unmet', '不支持符号 ref')
            if ref.endswith('^{}'):
                continue
            data.sha(oid)
            require(ref not in refs, 'conditions-unmet', '远端 ref 重复')
            refs[ref] = oid
        return refs

    def push(self, rows):
        self.check_address(self.repo.root, self.urls['target'])
        args = ['git', '-c', 'core.sshCommand=' + SSH_COMMAND, '-c', 'ssh.variant=ssh',
                '-c', 'http.followRedirects=false', '-C', self.repo.root, 'push', '--porcelain', '--atomic',
                *['--force-with-lease=' + r['ref'] + ':' for r in rows], self.urls['target'],
                *[r['oid'] + ':' + r['ref'] for r in rows]]
        try:
            p = subprocess.run(args, capture_output=True, timeout=60, env=git_environment())
        except (OSError, subprocess.TimeoutExpired):
            return 'unknown'
        if p.returncode:
            if b'does not support --atomic push' in p.stderr:
                return 'atomic-unavailable'
            return 'unknown'
        # '*' means new ref; '=' does not identify this invocation as creator.
        flags = [line.split(b'\t', 1)[0] for line in p.stdout.splitlines() if b'\t' in line]
        return 'created' if len(flags) == len(rows) and all(f == b'*' for f in flags) else 'reconciled'

    def fetch_target(self, root, rows):
        self.check_address(root, self.urls['target'])
        run(root, ['fetch', '--no-tags', self.urls['target'], *[r['ref'] + ':' + r['ref'] for r in rows]])


class Platforms:
    def __init__(self, repo, q):
        self.repo, self.q = repo, q
        self.source = None
        # Migration explicitly uses both providers; the ordinary publisher rejects dual config.
        c = platform.load_config(repo, allow_gitlab=True)
        require({k: c[k] for k in ('provider', 'host', 'repository', 'repository_id')} == q['target'],
                'identity-mismatch', '迁移目标与显式平台配置不一致')
        self.target = platform.GitHubAdapter(repo, config=c, bind_origin=False)

    def inspect_source(self):
        if self.source is None:
            self.source = flow.Adapter(self.repo, expected_identity=self.q['source'])
        require(self.source.inspect_repository() == self.q['source'], 'identity-mismatch', '源 API 身份不一致')
        api_git_urls(self.source.repository, self.q['source'], self.q['source_git_url'])

    def inspect_target(self):
        require(self.target.inspect_repository() == self.q['target'], 'identity-mismatch', '目标 API 身份不一致')
        require(self.target.repository.get('private') is True, 'conditions-unmet', '首次迁移目标须私有')
        api_git_urls(self.target.repository, self.q['target'], self.q['target_git_url'])

    def branches(self):
        return platform.paged(self.target.api, self.target.endpoint + '/branches')


def validate_plan(repo, q):
    require(repo.need('rev-parse', '--is-shallow-repository') == 'false' and
            repo.need('rev-parse', '--show-object-format') == 'sha1', 'conditions-unmet', '浅仓或非 SHA-1 仓不支持')
    p, a = q['plan_ref'], q['approval_ref']
    for commit in (p['commit'], a['commit'], *[r['oid'] for r in q['refs']]):
        require(repo.run('cat-file', '-e', commit) is not None, 'object-missing', '批准/计划或选定 Git 对象本地缺失')
    require(p['commit'] != a['commit'] and repo.ancestor(p['commit'], a['commit']), 'input-invalid', '批准必须晚于已提交计划')
    plan = block(repo, p, 'migration-plan')
    data.obj(plan, 'schema source target source_git_url target_git_url refs retained_branch retained_base inventory verification source_window writer_exclusion')
    require(plan['schema'] == PLAN_SCHEMA, 'input-invalid', '未知计划块')
    require(all(plan[k] == q[k] for k in ('source', 'target', 'source_git_url', 'target_git_url', 'refs')), 'input-invalid', '请求身份或清单不等于已批准计划')
    data.sha(plan['retained_base']); data.branch(plan['retained_branch'])
    for commit in (plan['retained_base'], p['commit'], a['commit']):
        require(repo.run('cat-file', '-e', commit) is not None, 'object-missing', '计划/批准/保留基线本地对象缺失')
    require(plan['retained_branch'] != 'main' and 'refs/heads/' + plan['retained_branch'] not in {r['ref'] for r in q['refs']},
            'input-invalid', '计划/批准保留分支不能在导入清单内')
    require(repo.ancestor(plan['retained_base'], p['commit']), 'source-changed', '计划分支不继承保留基线')
    approval = block(repo, a, 'migration-approval')
    data.obj(approval, 'schema plan_ref action')
    require(approval == dict(schema='handoff-migration-approval/v1', plan_ref=p, action='import'),
            'input-invalid', '批准没有绑定本计划身份与 import')
    approval_text = repo.file(a['commit'], a['path']).decode()
    require(a['locator'] in approval_text, 'input-invalid', '批准 locator 不存在')
    for key in ('source_window', 'writer_exclusion'):
        data.text(plan[key])
    if q['source']['host'].startswith('http://'):
        disclosure = plan['source_window'] + '\n' + repo.file(p['commit'], p['path']).decode()
        require(q['source']['host'] in disclosure and 'HTTP 本身不加密 API 凭据' in disclosure,
                'conditions-unmet', 'HTTP 计划缺精确源地址或未加密凭据说明；须重新核差计划及当次批准')
    data.obj(plan['inventory'], 'git_history large_objects lfs submodules archive_repository review_archives collaboration_assets external_callers in_flight')
    for item in plan['inventory'].values():
        data.obj(item, 'disposition evidence')
        require(item['disposition'] in ('migrate', 'retain', 'not-applicable'), 'conditions-unmet', '盘点仍有未处置资料')
        data.text(item['evidence'])
    data.obj(plan['verification'], 'implementation history recovery first_pr')
    for item in plan['verification'].values():
        data.text(item)
    main = next(r['oid'] for r in q['refs'] if r['ref'] == 'refs/heads/main')
    # Rule and implementation birth must precede the fixed main. The caller separately checks test evidence semantics.
    required = ('handoff_platform.py', 'handoff_migration.py', 'github_pr_api.py',
                'HarnessPlane_Handoff_Protocol_Design_v1.md')
    files = {name: repo.file(main, 'mechanisms/handoff-protocol/' + name) for name in required}
    require(all(files.values()), 'conditions-unmet', '固定 main 未包含 CL-57 迁移适配及规则')
    try:
        tree = ast.parse(files['handoff_migration.py'])
        constants = {node.targets[0].id: node.value.value for node in tree.body
                     if isinstance(node, ast.Assign) and len(node.targets) == 1 and
                     isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    except (SyntaxError, ValueError):
        raise Stop('conditions-unmet', '固定 main 迁移实现不可解析') from None
    require(all(constants.get(key) == value for key, value in
                dict(REQUEST_SCHEMA=REQUEST_SCHEMA, PLAN_SCHEMA=PLAN_SCHEMA, RESULT_SCHEMA=RESULT_SCHEMA).items()) and
            REQUEST_SCHEMA.encode() in files[required[-1]],
            'conditions-unmet', '固定 main 缺 v2 实现版本或规则；文件在场不足以证明能力')
    repo.locate(main, plan['verification']['implementation'], strict=True)
    return plan


def check_source(repo, q, plan, observed):
    expected = {r['ref']: r['oid'] for r in q['refs']}
    retained = 'refs/heads/' + plan['retained_branch']
    require(set(observed) == set(expected) | {retained}, 'source-changed', '源存在未申报或缺失的 heads/tags')
    require(all(observed[r] == oid for r, oid in expected.items()), 'source-changed', '选定源 ref 已漂移')
    require(observed[retained] == q['approval_ref']['commit'], 'source-changed', '保留分支有批准后未申报变化')


def validate_local_proof(repo, q, plan):
    """Validate the fixed approval chain, independent of live refs and latest HEAD."""
    allowed = {q['plan_ref']['path'], q['approval_ref']['path']}
    changed = set(repo.need('diff', '--name-only', plan['retained_base'], q['approval_ref']['commit']).splitlines())
    require(changed <= allowed, 'source-changed', '保留分支新增内容超出计划/批准路径')
    for commit in repo.need('rev-list', plan['retained_base'] + '..' + q['approval_ref']['commit']).splitlines():
        parents = repo.need('rev-list', '--parents', '-n', '1', commit).split()[1:]
        require(len(parents) == 1, 'source-changed', '计划/批准新增历史不允许未申报 merge')
        paths = set(repo.need('diff', '--name-only', parents[0], commit).splitlines())
        require(paths <= allowed, 'source-changed', '计划/批准之间包含未申报提交路径')
    for row in q['refs']:
        require(repo.run('cat-file', '-e', row['oid']) is not None, 'object-missing', '选定 Git 对象本地缺失')
        kind = repo.need('cat-file', '-t', row['oid'])
        require(kind in ('commit', 'tag') and (not row['ref'].startswith('refs/heads/') or kind == 'commit'),
                'conditions-unmet', '不支持的 ref 对象类型')
        if row['ref'].startswith('refs/heads/'):
            require(repo.run('symbolic-ref', '-q', row['ref']) is None, 'conditions-unmet', '不支持符号分支')
    run(repo.root, ['rev-list', '--objects', '--missing=error', *[r['oid'] for r in q['refs']]], 'object-missing')
    verify_history(repo, q['refs'])


def verify_history(repo, rows):
    """Check the imported closure, not unrelated objects left in the original clone."""
    commits = {repo.need('rev-parse', r['oid'] + '^{commit}') for r in rows}
    closure = set(repo.need('rev-list', *[r['oid'] for r in rows]).splitlines())
    for commit in commits:
        files = repo.files(commit)
        if 'records/history-locations.jsonl' in files:
            for raw in repo.file(commit, 'records/history-locations.jsonl').decode().splitlines():
                location = data.loads(raw)
                source = location.get('source_commit')
                require(source in closure, 'object-missing', '历史定位源不在导入祖先闭包')
            hist = flow.history.GitHistory(repo.root, commit)
            hist.items()
        objects, _ = flow.frozen_state(repo, commit)
        for path, record in objects.items():
            if record['state'] != '历史已退役':
                actual = flow.identity(repo, commit, path)
                want = record['object']
                require(actual is not None and all(actual[k] == want[k] for k in ('bytes', 'sha256')),
                        'object-missing', '当前冻结对象不可读或身份不符: ' + path)
        for path in files:
            if path.startswith('HANDOFF/progress/') and path.endswith('.md'):
                task = repo.task_at(commit, Path(path).stem)
                event = reader.last_event(task, 'handoff')
                if event:
                    proof = reader.validate_handoff(repo, task, commit)
                    require(proof['content_commit'] in closure and proof['handoff_commit'] in closure,
                            'object-missing', 'C/H 不在导入历史闭包')


def ref_results(q, observed):
    expected = {r['ref']: r['oid'] for r in q['refs']}
    return [dict(ref=r, expected_oid=expected.get(r), observed_oid=observed.get(r),
                 state='absent' if r not in observed else 'matched' if observed[r] == expected.get(r) else 'mismatch')
            for r in sorted(expected)]


def verify_target(repo, q, transport, out):
    observed = transport.refs('target')
    out['ref_results'] = ref_results(q, observed)
    extra = set(observed) - {r['ref'] for r in q['refs']}
    if extra:
        out['details'].append('目标额外 refs: ' + ', '.join(sorted(extra)))
    require(observed == {r['ref']: r['oid'] for r in q['refs']}, 'conditions-unmet', '目标 refs 未全等或有额外 refs；不补推/删除')
    # This is an isolated bare verification repository, not a task worktree.
    with tempfile.TemporaryDirectory(prefix='handoff-migration-verify-') as folder:
        run(folder, ['init', '--bare'])
        transport.fetch_target(folder, q['refs'])
        target = reader.Repository(folder)
        for row in q['refs']:
            require(target.need('rev-parse', '--verify', row['ref']) == row['oid'], 'conditions-unmet', '取得目标对象时 ref 漂移')
        run(folder, ['fsck', '--full', '--no-reflogs'], 'object-missing')
        verify_history(target, q['refs'])
        source_objects = run(repo.root, ['rev-list', '--objects', '--no-object-names', *[r['oid'] for r in q['refs']]], 'object-missing')
        target_objects = run(folder, ['rev-list', '--objects', '--no-object-names', *[r['oid'] for r in q['refs']]], 'object-missing')
        require(set(source_objects.splitlines()) == set(target_objects.splitlines()), 'object-missing', '目标对象闭包不等于源')
    require(transport.refs('target') == observed, 'conditions-unmet', '对象核查期间目标 refs 改变')
    out['details'].append('Git refs、对象闭包、历史定位、冻结字节和 C/H 已核；不证明 LFS/归档/协作资产或切换完成')


def execute(repo, q, action, out, platforms=None, transport=None):
    request(q)
    out.update(plan_ref=q['plan_ref'], source=q['source'], target=q['target'],
               source_git_url=q['source_git_url'], target_git_url=q['target_git_url'])
    plan = validate_plan(repo, q)
    validate_local_proof(repo, q, plan)
    platforms = platforms or Platforms(repo, q)
    transport = transport or Transport(repo, q, target_only=action == 'verify')
    platforms.inspect_target()
    if action == 'verify':
        verify_target(repo, q, transport, out)
        platforms.inspect_target()
        return
    platforms.inspect_source()
    check_source(repo, q, plan, transport.refs('source'))
    observed = transport.refs('target')
    out['ref_results'] = ref_results(q, observed)
    require(not observed and platforms.branches() == [], 'target-not-empty', '目标已有 refs 或 API 分支；拒绝初始化')
    if action == 'check':
        out['details'].append('只读 check 完成；调用方仍须核授权语义、停写窗口与外部资产证据')
        return
    # Re-read identities and all refs immediately before the sole write attempt.
    platforms.inspect_target()
    platforms.inspect_source()
    check_source(repo, q, plan, transport.refs('source'))
    require(not transport.refs('target') and platforms.branches() == [], 'target-not-empty', '写入前目标改变')
    result = transport.push(q['refs'])
    if result == 'atomic-unavailable':
        raise Stop('transport-unavailable', '目标不支持 atomic，未回退顺序推送', 'not-checked')
    try:
        verify_target(repo, q, transport, out)
        platforms.inspect_target()
    except Exception as exc:
        # A malformed readback is also unknown after a write, never an input-only failure.
        raise Stop('external-unknown', '写入后对账未完成；停止写入并保留两端，使用 verify 继续核对', 'external-unknown') from exc
    out['details'].append('服务端报告本次精确 refs 创建成功' if result == 'created' else
                          '回读全等；本调用创建归属未核，不重试 import')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('check', 'import', 'verify'))
    p.add_argument('--request', required=True)
    p.add_argument('--root', default='.')
    p.add_argument('--json', action='store_true')
    a = p.parse_args(argv)
    out = dict(schema=RESULT_SCHEMA, action=a.action, status='not-checked', reason='none',
               plan_ref=None, source=None, target=None, source_git_url=None, target_git_url=None, ref_results=[], details=[])
    try:
        repo = reader.Repository(str(Path(a.root).resolve()))
        path = Path(a.request).resolve()
        require(not path.is_relative_to(Path(repo.root)), 'input-invalid', '迁移请求须位于仓外')
        q = data.loads(path.read_text())
        execute(repo, q, a.action, out)
        out['status'] = 'completed'
    except Stop as exc:
        out.update(status=exc.status, reason=exc.reason); out['details'].append(str(exc))
    except (platform.PlatformError, flow.Stop) as exc:
        reason = 'identity-mismatch' if exc.reason == 'remote-mismatch' else 'conditions-unmet' if exc.reason == 'conditions-unmet' else 'input-invalid' if exc.reason == 'input-invalid' else 'transport-unavailable'
        out.update(status=exc.status, reason=reason); out['details'].append(str(exc))
    except data.Invalid:
        out.update(status='blocked', reason='input-invalid'); out['details'].append('请求或引用块文法错误')
    except reader.Unavailable:
        out.update(status='not-checked', reason='object-missing'); out['details'].append('Git 引用或交接证据不可读')
    except Exception:
        out.update(status='not-checked', reason='transport-unavailable'); out['details'].append('执行未查成；原始异常未输出')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out['status'] == 'completed' else 1 if out['status'] == 'blocked' else 2


if __name__ == '__main__':
    sys.exit(main())
