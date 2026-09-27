#!/usr/bin/env python3
"""交接状态唯一读取器，handoff-protocol r7 §4/§6。
--resume 按当前 worktree 或 main first-parent 最近交接选择；--task 显式限定。
只读、不联网、不要求已清理分支存在；以 Git 提交树证明 C/H 与后继材料。
普通调用输出四段和 handoff-status/v3；next 只来自有效 handoff，旧记录标 legacy。
退出码 0=所请求范围已查成；2=未查成。可选调用，不接 hook/CI。
"""
import argparse
import json
import os
import subprocess
import sys
sys.dont_write_bytecode = True
import re
from pathlib import Path
import handoff_data as data

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import handoff_lint as grammar  # noqa: E402

SCHEMA = "handoff-status/v3"
TERMINAL_TYPES = ("done", "close")
LANDED_LIMIT = 5


class Git:
    def __init__(self, root):
        self.root = root
        self.failures = []

    def run(self, *args):
        try:
            env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
            env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0',
                       GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            r = subprocess.run(["git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false", "-C", self.root] + list(args), capture_output=True, env=env)
        except OSError as e:
            self.failures.append(f"git 不可用：{e}")
            return None
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", "replace")

    def ref_exists(self, ref):
        return self.run("rev-parse", "--verify", "--quiet", ref) is not None

    def worktrees(self):
        """{branch: path}，取自 git worktree list --porcelain。"""
        out = self.run("worktree", "list", "--porcelain")
        if out is None:
            self.failures.append("git worktree list 失败")
            return {}
        result, path = {}, None
        for line in out.split("\n"):
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line.startswith("branch refs/heads/") and path:
                result[line[len("branch refs/heads/"):]] = path
        return result

    def ahead_behind(self, branch):
        """相对 origin/main 的 (领先, 落后)；分支本地与 origin 均无时返回 None。"""
        ref = None
        for cand in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
            if self.ref_exists(cand):
                ref = cand
                break
        if ref is None:
            return None
        out = self.run("rev-list", "--left-right", "--count", f"origin/main...{ref}")
        if out is None:
            self.failures.append(f"rev-list origin/main...{branch} 失败")
            return None
        behind, ahead = out.split()
        return int(ahead), int(behind)

    def is_ancestor_of_main(self, sha):
        try:
            r = subprocess.run(["git", "-C", self.root, "merge-base", "--is-ancestor", sha, "origin/main"],
                               capture_output=True)
        except OSError as e:
            self.failures.append(f"git 不可用：{e}")
            return False
        return r.returncode == 0


def ruling_types(root, task_id):
    d = os.path.join(root, "tasks", task_id, "rulings")
    types = []
    if not os.path.isdir(d):
        return types
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                head = [next(f, "") for _ in range(8)]
        except OSError:
            continue
        for line in head:
            if line.startswith("> Type:"):
                types.append(line[len("> Type:"):].strip())
    return types


def terminal_state(root, task, closed):
    """返回 (是否终态, 说明)。"""
    if task["category"] == grammar.CATEGORY_MILESTONE:
        types = ruling_types(root, task["ref"])
        hit = [t for t in types if t in TERMINAL_TYPES]
        return (True, f"ruling Type: {hit[0]}") if hit else (False, "无 done / close ruling")
    if task["category"] == grammar.CATEGORY_LEDGER:
        if task["ref"] in closed:
            c = closed[task["ref"]][0]
            return True, f"承载项 {task['ref']} 已由 {c['task']} 的 {c['type']} 行闭合"
        if task["ref"] not in task["_born"]:
            return True, f"承载项 {task['ref']} 不在进度层（切换点前已闭合）"
        return False, f"承载项 {task['ref']} 仍 open"
    return True, "仓级文件不是任务"


def compute_legacy(root):
    tasks, findings = grammar.load_progress(root)
    violations = [f for f in findings if f["severity"] == "violation"]
    git = Git(root)
    notes = []
    if violations:
        notes.append(f"进度文件文法有 {len(violations)} 处违规，先跑 handoff_lint.py；本快照按可解析部分算出")
    if not git.ref_exists("origin/main"):
        notes.append("origin/main 不存在：第 2 段领先 / 落后与第 3 段无法判定")
        have_main = False
    else:
        have_main = True

    closed = grammar.closure(tasks)
    items = grammar.open_items(tasks)
    born = {e["id"] for e in items}
    for t in tasks:
        t["_born"] = born

    pending = []
    for e in items:
        if e["kind"] == "OD" and e["id"] not in closed:
            pending.append({"id": e["id"], "task": e["task"], "title": e["title"],
                            "blocked_by": e["status"], "opened_at": e["at"]})

    worktrees = git.worktrees()
    in_progress = []
    for t in tasks:
        terminal, why = terminal_state(root, t, closed)
        if terminal:
            continue
        latest = None
        for e in t["events"]:
            if e["type"] in ("intent", "result"):
                latest = {"at": e["at"], "type": e["type"], "step": e["step"], "text": e["text"],
                          "commit": e.get("commit")}
        entry = {"task": t["stem"], "category": t["category"], "ref": t["ref"], "branch": t["branch"],
                 "state": why, "latest": latest, "worktree": None, "ahead": None, "behind": None,
                 "branch_note": None}
        if t["branch"].startswith("无"):
            entry["branch_note"] = "分支意图为「无」，不查 Git"
        else:
            entry["worktree"] = worktrees.get(t["branch"])
            if have_main:
                ab = git.ahead_behind(t["branch"])
                if ab is None:
                    entry["branch_note"] = "分支在本地与 origin 均不存在"
                else:
                    entry["ahead"], entry["behind"] = ab
            else:
                entry["branch_note"] = "origin/main 不存在，未查领先 / 落后"
        in_progress.append(entry)

    landed = []
    if have_main:
        for t in tasks:
            for e in t["events"]:
                if e["type"] == "result" and e.get("commit") and git.is_ancestor_of_main(e["commit"]):
                    landed.append({"task": t["stem"], "at": e["at"], "step": e["step"],
                                   "text": e["text"], "commit": e["commit"]})
        landed.sort(key=lambda x: (x["at"], x["commit"]), reverse=True)
        landed = landed[:LANDED_LIMIT]

    nxt = []
    for entry in in_progress:
        task = next(t for t in tasks if t["stem"] == entry["task"])
        intents = [e for e in task["events"] if e["type"] == "intent"]
        nxt.append({"task": entry["task"], "step": None,
                    "text": "未提供结构化交接，待核对"})

    notes.extend(git.failures)
    conclusion = grammar.NOT_CHECKED if (violations or not have_main or git.failures) else grammar.PASS
    return {"schema": SCHEMA, "conclusion": conclusion, "notes": notes,
            "pending_owner": pending, "in_progress": in_progress, "landed": landed,
            "next": nxt, "next_text": None if nxt else "无在办"}


def summary_presentations(snapshot, selected_handoff=None):
    """Pair only same-proof presentation sources; never resolve state or read Git."""
    records = {}
    for i, entry in enumerate(snapshot['in_progress']):
        if entry.get('handoff'):
            records['in_progress', i] = dict(summary=entry['handoff']['summary'], at=None,
                                            task=entry['task'], commit=None)
    for i, entry in enumerate(snapshot['landed']):
        if entry.get('summary') is not None:
            records['landed', i] = dict(summary=entry['summary'], at=entry['at'],
                                       task=entry['task'], commit=entry['commit'])
    groups = {place: place for place in records}
    # compute emits at most one proved main handoff per task from resolutions.
    # Require unique rows and equal payloads before joining their C and H.
    for i, entry in enumerate(snapshot['in_progress']):
        place = ('in_progress', i)
        matches = [j for j, row in enumerate(snapshot['landed'])
                   if row['task'] == entry['task'] and row.get('summary') is not None]
        peers = [e for e in snapshot['in_progress'] if e['task'] == entry['task']]
        if place not in records or entry.get('location') != 'main' or len(matches) != 1 or len(peers) != 1:
            continue
        landed = ('landed', matches[0])
        if records[place]['summary'] == records[landed]['summary'] and entry['handoff'].get('content_commit'):
            groups[landed] = place
            records[place] = dict(records[landed])

    selected = snapshot.get('resume')
    if selected and selected['status'] == 'ready':
        task, c, h = selected['task'], selected['content_commit'], selected['handoff_commit']
        entries = [i for i, e in enumerate(snapshot['in_progress'])
                   if e['task'] == task and e.get('location') == selected['location']
                   and (e.get('handoff') or {}).get('content_commit') == c]
        landed = [i for i, e in enumerate(snapshot['landed'])
                  if e['task'] == task and e['commit'] == h and e.get('summary') is not None]
        # Re-pair the selected task by explicit C/H, not by a transitive group.
        # An inconsistent landed H must remain visible as a separate source.
        for place, record in records.items():
            if record['task'] == task:
                groups[place] = place
                if place[0] == 'in_progress':
                    record.update(at=None, commit=None)
        chosen = None
        if selected_handoff is not None:
            event = selected_handoff['event']
            if (selected_handoff['task'] != task or selected_handoff['commit'] != h
                    or event['data']['content_commit'] != c):
                raise ValueError('selected summary identity differs from resume C/H')
            chosen = dict(task=task, commit=h, at=event['at'], summary=event['data']['summary'])
        elif len(landed) == 1:
            chosen = dict(records['landed', landed[0]])
        elif len(entries) == 1:
            chosen = dict(records['in_progress', entries[0]], commit=h)
        if chosen is not None:
            records['resume', 0] = chosen
            groups['resume', 0] = ('resume', 0)
            for kind, matches in (('in_progress', entries), ('landed', landed)):
                if len(matches) != 1:
                    continue
                place = (kind, matches[0])
                if records[place]['summary'] != chosen['summary']:
                    continue
                if (kind == 'in_progress' and selected_handoff is not None
                        and snapshot[kind][matches[0]]['handoff'] != selected_handoff['event']['data']):
                    continue
                groups[place] = ('resume', 0)
    return records, groups


def render(snapshot, selected_handoff=None):
    records, groups = summary_presentations(snapshot, selected_handoff)
    out = []

    def summary(place):
        if place not in records:
            return
        record = records[place]
        owner = groups[place]
        # A group may have been promoted from in_progress to the selected resume.
        owner = groups[owner]
        indent = '' if place[0] == 'resume' else '  '
        if owner != place:
            target = records[owner]
            section = {'resume': '接手', 'in_progress': '2 在办', 'landed': '3 刚落地'}[owner[0]]
            anchor = f" / H:{target['commit']}" if target['commit'] else ''
            out.append(f"{indent}- 交接声明见“{section} / {target['task']}{anchor}”")
            return
        when = f"{record['at']} " if record['at'] else ''
        anchor = f" · H:{record['commit']}" if record['commit'] else ''
        out.append(f"{indent}- {when}交接写入时的声明{anchor}")
        for field, label in (('completed', '成果'), ('remaining', '残留')):
            values = record['summary'][field]
            if values:
                out.extend(f"{indent}  - {label}：{value}" for value in values)
            else:
                out.append(f"{indent}  - {label}声明：无")

    def action(nxt, missing):
        if nxt is None:
            return missing
        if nxt['kind'] == 'none':
            return '本批无后续动作'
        text = f"{nxt['kind']} · {nxt['text']}"
        if nxt['authority_ref'] is not None:
            text += ' · 授权依据：' + nxt['authority_ref']
        return text

    if snapshot['notes']:
        out.append('## 未查成原因')
        out.extend(f'- {n}' for n in snapshot['notes'])
        out.append('')
    out.append('## 1 等 Owner 拍板')
    for p in snapshot['pending_owner']:
        row = (f"- {p['id']} · {p['task']} · {p['title']} · 未闭合 · 登记于 {p['opened_at']}"
               f" · 原登记说明：{p['blocked_by']}")
        for e in snapshot['in_progress']:
            if e['ref'] == p['id']:
                row += f" · 最近记录见“2 在办 / {e['task']}”"
                if any(n['task'] == e['task'] for n in snapshot['next']):
                    row += f"；建议见“4 下一步 / {e['task']}”"
        out.append(row)
    if not snapshot['pending_owner']:
        out.append('- 无')
    out.extend(['', '## 2 在办'])
    for i, e in enumerate(snapshot['in_progress']):
        ref = f" · {e['ref']}" if e['ref'] else ''
        out.append(f"- {e['task']} · {e['category']}{ref} · 分支意图 {e['branch']} · {e['state']}")
        if e['latest']:
            anchor = f" · commit:{e['latest']['commit']}" if e['latest']['commit'] else ''
            out.append(f"  - 最近 {e['latest']['type']} · {e['latest']['at']} · {e['latest']['step']} · "
                       f"{e['latest']['text']}{anchor}")
        else:
            out.append('  - 最近 intent / result：无')
        if e['branch_note']:
            out.append(f"  - {e['branch_note']}")
        else:
            wt = e['worktree'] or '无 worktree 命中'
            out.append(f"  - worktree：{wt}；相对 origin/main 领先 {e['ahead']} / 落后 {e['behind']}")
        summary(('in_progress', i))
    if not snapshot['in_progress']:
        out.append('- 无')
    out.extend(['', '## 3 刚落地'])
    for i, l in enumerate(snapshot['landed']):
        text = '' if l.get('summary') is not None else f" · {l['text']}"
        out.append(f"- {l['at']} · {l['task']} · {l['step']}{text} · commit:{l['commit']}")
        summary(('landed', i))
    if not snapshot['landed']:
        out.append('- 无')
    out.extend(['', '## 4 下一步'])
    main_advice_note = ('本地 main 祖先证明不代表交付收尾完成；建议的执行状态未核验，'
                        '不能直接列为当前待办。已核实完成的动作不再提醒或重复执行；'
                        '未核验项说明限制，不推断已完成。')
    for n in snapshot['next']:
        entry = next((e for e in snapshot['in_progress'] if e['task'] == n['task']), None)
        main_advice = bool(entry and entry.get('location') == 'main' and n.get('handoff_next')
                           and entry.get('handoff', {}).get('after_merge'))
        label = '交接中的合并后建议：' if main_advice else ''
        out.append(f"- {n['task']} · {label}{action(n.get('handoff_next'), n.get('text') or '未提供当前建议')}")
        if main_advice:
            out.append('  - 合并后建议依据：' + entry['handoff']['after_merge']['basis_ref'])
            out.append('  - ' + main_advice_note)
    if not snapshot['next']:
        out.append(f"- {snapshot['next_text']}")
    selected = snapshot.get('resume')
    if selected is not None:
        out.extend(['', '## 接手'])
        out.append(f"- 状态：{selected['status']}；任务：{selected['task'] or '未选定'}；"
                   f"候选：{', '.join(selected['candidates']) or '无'}；位置：{selected['location'] or '未确定'}")
        out.append(f"- 内容提交 C：{selected['content_commit'] or '未提供'}")
        out.append(f"- 交接提交 H：{selected['handoff_commit'] or '未提供'}")
        matching = [n for n in snapshot['next'] if n['task'] == selected['task']
                    and n.get('handoff_next') == selected['next']]
        if selected['candidates']:
            out.append('- 候选仅用于选择恢复来源，不是在办任务或待办清单。')
        if selected['status'] == 'ready' and not any(e['task'] == selected['task'] for e in snapshot['in_progress']):
            out.append('- 所选恢复来源未列入本次在办清单；交接记录不重开已闭合任务，仓级记录也不据此变成待办。')
        main_advice = selected['location'] == 'main' and selected['next'] is not None
        label = '交接中的合并后建议' if main_advice else '当前下一步'
        if len(matching) == 1:
            out.append(f"- {label}：见“4 下一步 / {selected['task']}”")
        else:
            out.append(f'- {label}：' + action(selected['next'], '未提供当前建议，见原因'))
            if main_advice:
                out.append('- ' + main_advice_note)
        out.extend(f'- 原因：{reason}' for reason in selected['reasons'])
        if not selected['reasons']:
            out.append('- 原因：无')
        summary(('resume', 0))
        if selected['status'] == 'ready' and ('resume', 0) not in records:
            out.append('- summary 未随本次呈现输入提供')
    return "\n".join(out) + "\n"


class Unavailable(RuntimeError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class Repository(Git):
    """Read-only Git operations shared by the reader and workflow."""
    def need(self, *args):
        value = self.run(*args)
        if value is None:
            raise Unavailable('evidence-missing', 'git 查询失败: ' + ' '.join(args))
        return value.strip()

    def resolve(self, ref):
        return self.need('rev-parse', '--verify', ref + '^{commit}')

    def ancestor(self, a, b):
        return self.run('merge-base', '--is-ancestor', a, b) is not None

    def blob(self, commit, path):
        data.path(path)
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
            commit = self.resolve(commit)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'repo-layout'))
        try:
            import history_read as history
        except ImportError as exc:
            raise Unavailable('evidence-missing', 'history-unavailable: shared helper absent') from exc
        try:
            return history.read_history(self.root, commit, path, commit)['content']
        except history.HistoryReadError as exc:
            raise Unavailable('evidence-missing', exc.code+': '+exc.message)

    def files(self, commit):
        return self.need('ls-tree', '-r', '--name-only', '-z', commit).split('\0')

    def file(self, commit, path):
        data.path(path)
        row = self.run('ls-tree', commit, '--', path)
        if not row or row.split()[0] not in ('100644', '100755'):
            raise Unavailable('evidence-missing', f'{commit}:{path} 不是可核对的普通 Git 文件')
        return self.blob(commit, path)

    def safe_path(self, path):
        data.path(path)
        target = Path(self.root) / path
        if not target.resolve().is_relative_to(Path(self.root).resolve()):
            raise Unavailable('scope-mismatch', f'{path}: symlink 越出仓库')
        return target

    def changed(self, a, b):
        result = self.need('diff', '--name-only', '--no-renames', '-z', a, b)
        return set(filter(None, result.split('\0')))

    def dirty(self, ignored=False):
        args = ['status', '--porcelain=v1', '-z', '--untracked-files=all']
        if ignored:
            args.append('--ignored')
        return self.need(*args)

    def tree_tasks(self, commit):
        tasks, errors = [], []
        for path in self.files(commit):
            if re.fullmatch(r'HANDOFF/progress/[^/]+\.md', path):
                task, fs = grammar.parse_file(None, path, self.file(commit, path))
                tasks.append(task); errors.extend(fs)
        errors.extend(grammar.cross_checks(tasks))
        return tasks, errors

    def task_at(self, commit, task):
        path = f'HANDOFF/progress/{task}.md'
        result, fs = grammar.parse_file(None, path, self.file(commit, path))
        errors = [f for f in fs if f['severity'] != 'warning']
        if errors:
            raise Unavailable('input-invalid', f'{commit}:{path}: {errors}')
        return result

    def locate(self, commit, ref, strict=False, own_path=None, working=False):
        """Resolve a location; v2 requires a unique event or an explicit locator."""
        data.text(ref)
        if grammar.RE_ID.fullmatch(ref):
            tasks, fs = grammar.load_progress(self.root) if working else self.tree_tasks(commit)
            matches = [(t['file'], e) for t in tasks for e in t['events']
                       if e.get('id') == ref and (not strict or e['type'] == 'open')]
            if not matches or (strict and len(matches) != 1):
                raise Unavailable('evidence-missing', f'{commit}: 事件来源不唯一或缺失 {ref}')
            path = matches[0][0]
            if strict and path == own_path:
                raise Unavailable('evidence-missing', '本任务进度引用必须使用 path:line')
            return path
        match = re.fullmatch(r'(.+):(\d+)', ref)
        path = match[1] if match else ref.split('#', 1)[0]
        if not strict:
            path = re.sub(r':\d+(?:-\d+)?$', '', path)
        data.path(path)
        if working:
            target = self.safe_path(path)
            if not target.is_file() or target.is_symlink():
                raise Unavailable('evidence-missing', path + ': 不是普通工作文件')
            raw = target.read_bytes()
        else:
            raw = self.file(commit, path)
        if ref.endswith('#review-result'):
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'review-channel'))
            import review_evidence as evidence
            try:evidence.result_block(raw)
            except evidence.EvidenceError as exc:raise Unavailable('evidence-missing',str(exc)) from exc
        if strict:
            if match:
                line = int(match[2])
                if not 1 <= line <= len(raw.splitlines()):
                    raise Unavailable('evidence-missing', ref + ': 行号不存在')
                if path == own_path:
                    task, errors = grammar.parse_file(None, path, raw)
                    if any(f['severity'] != 'warning' for f in errors) or not any(e['line'] == line for e in task['events']):
                        raise Unavailable('evidence-missing', ref + ': 不是具体合法进度事件')
            elif path == own_path or '#' not in ref or not ref.split('#', 1)[1].strip():
                raise Unavailable('evidence-missing', ref + ': 需要明确定位，本任务进度须用 path:line')
        return path


def suggestion_refs(repo, record, commit, own_path, working=False):
    """Validate both stages' C-local references without granting authority."""
    if record.get('version', 2) == 1:
        if record['next']['kind'] == 'continue-authorized':
            repo.locate(commit, record['next']['authority_ref'])
        return
    refs = []
    steps = [record['next']]
    if record['after_merge'] is not None:
        refs.append(record['after_merge']['basis_ref'])
        steps.append(record['after_merge']['next'])
    refs.extend(n['authority_ref'] for n in steps if n['kind'] == 'continue-authorized')
    current = {e['path'] for e in record['entries'] if e['role'] == 'current'}
    for ref in refs:
        path = repo.locate(commit, ref, strict=True, own_path=own_path, working=working)
        if path not in current:
            raise Unavailable('evidence-missing', ref + ': 引用路径必须列为 current entry')


def last_event(task, kind):
    return next((e for e in reversed(task['events']) if e['type'] == kind), None)


def validate_handoff(repo, task, tip='HEAD'):
    event = last_event(task, 'handoff')
    ctx = last_event(task, 'context')
    if not event:
        raise Unavailable('stale-handoff', f"{task['file']}: 尚无 handoff")
    if not ctx or ctx['line'] > event['line']:
        raise Unavailable('stale-handoff', f"{task['file']}: 新 context 后尚无交接")
    record, context = event['data'], ctx['data']
    c = record['content_commit']; repo.resolve(c)
    # Search exact introduction in reachable history; never map squash/tree similarity.
    raw = event['raw'].encode() + b'\n'; path = task['file']
    if repo.blob(tip, path).splitlines().count(raw.rstrip(b'\n')) != 1:
        raise Unavailable('ambiguous-context', f'{path}:{event["line"]}: 重复交接行')
    sources = []
    for h in repo.need('log', '--format=%H', tip, '--', path).splitlines():
        parents = repo.need('rev-list', '--parents', '-n', '1', h).split()[1:]
        if parents != [c]:
            continue
        before = repo.blob(c, path); after = repo.blob(h, path)
        if after == before + raw and repo.changed(c, h) == {path}:
            sources.append(h)
    if len(sources) != 1:
        raise Unavailable('evidence-missing', f'{path}:{event["line"]}: 不能唯一证明 H 的单父 C 与单行追加')
    h = sources[0]; prior = repo.task_at(c, task['stem']); prior_context = last_event(prior, 'context')
    if not prior_context or prior_context['data'] != context:
        raise Unavailable('ambiguous-context', f'{c}:{path}: context 未在 C 中成立')
    if not repo.ancestor(context['base_commit'], c):
        raise Unavailable('evidence-missing', f'{c}: base_commit 不是祖先')
    repo.locate(c, context['authority_ref'])
    for e in record['evidence']:
        if not repo.ancestor(e['commit'], c):
            raise Unavailable('evidence-missing', f"{e['commit']}: 不是 C 祖先")
        repo.file(e['commit'], e['path'])
    for e in record['entries']:
        repo.file(c, e['path'])
        for path2 in e.get('sources', []):
            repo.file(c, path2)
    suggestion_refs(repo, record, c, task['file'])
    return {'context': context, 'handoff': record, 'content_commit': c, 'handoff_commit': h}


def check_later(repo, proof, task, tip):
    h = proof['handoff_commit']; record = proof['handoff']
    sensitive = {e['path'] for e in record['entries'] if e['role'] != 'history'}
    sensitive.update(e['path'] for e in record['evidence'])
    changed = repo.changed(h, tip)
    hits = sorted((changed & sensitive) - {task['file']})
    if hits:
        raise Unavailable('stale-handoff', f'{h}..{tip}: 未交接的材料变化: ' + ', '.join(hits))
    if task['file'] in changed:
        before = repo.blob(h, task['file']); after = repo.blob(tip, task['file'])
        if not after.startswith(before):
            raise Unavailable('stale-handoff', f'{task["file"]}: 旧进度被修改')
        for n, line in enumerate(after[len(before):].decode().splitlines(), len(before.splitlines()) + 1):
            event, fs = grammar.parse_event(task['file'], n, line, task['stem'], task['category'])
            if fs or not event or event['type'] not in ('answer', 'close'):
                raise Unavailable('stale-handoff', f'{task["file"]}:{n}: 后继内容尚未交接')


def resolve_task(repo, tasks, errors, selected=None):
    proof = None
    out = dict(status='unavailable', task=selected, candidates=[], location=None,
               content_commit=None, handoff_commit=None, next=None, reasons=[])
    try:
        head = repo.resolve('HEAD'); branch = repo.need('symbolic-ref', '--short', 'HEAD')
        if repo.need('rev-parse', '--is-shallow-repository') == 'true':
            raise Unavailable('evidence-missing', '浅历史不足以证明交接来源')
        if selected is None:
            if branch != 'main':
                candidates = [t['stem'] for t in tasks if last_event(t, 'context') and
                              last_event(t, 'context')['data']['source_branch'] == branch]
            else:
                candidates = []
                for boundary in repo.need('log', '--first-parent', '--diff-merges=first-parent', '--format=%H', '-G', ' · handoff · ', head, '--', grammar.PROGRESS_DIR).splitlines():
                    parents = repo.need('rev-list', '--parents', '-n', '1', boundary).split()[1:]
                    now, fs = repo.tree_tasks(boundary)
                    for t in now:
                        try:
                            before = repo.blob(parents[0], t['file']).decode().splitlines() if parents else []
                        except Unavailable:
                            before = []
                        introduced = [line for line in repo.blob(boundary, t['file']).decode().splitlines() if ' · handoff · ' in line and line not in before]
                        if introduced:
                            invalid = [e for e in fs if e['file'] == t['file'] and e['severity'] != 'warning']
                            if invalid:
                                raise Unavailable('input-invalid', f'{boundary}: {invalid}')
                            validate_handoff(repo, t, boundary)
                            candidates.append(t['stem'])
                    if candidates:
                        break
            candidates = sorted(set(candidates)); out['candidates'] = candidates
            if len(candidates) > 1:
                out['status'] = 'ambiguous'; out['reasons'] = ['多个交接候选，请指定 --task']; return out, None
            if not candidates:
                # Legacy auto-selection is deliberately not inferred from prose or dates.
                out['candidates'] = [t['stem'] for t in tasks if t['category'] != grammar.CATEGORY_REPO]
                out['status'] = 'ambiguous' if len(out['candidates']) > 1 else 'unavailable'
                out['reasons'] = ['无可选新版交接，请指定旧任务以核对 result 锚']; return out, None
            selected = candidates[0]; out['task'] = selected
        task = next((t for t in tasks if t['stem'] == selected), None)
        if task is None:
            raise Unavailable('input-invalid', f'任务 {selected} 不存在')
        bad = [e for e in errors if e['file'] == task['file'] and e['severity'] != 'warning']
        if bad:
            raise Unavailable('input-invalid', str(bad))
        if repo.dirty():
            raise Unavailable('scope-mismatch', '所选工作区有未提交内容，不能视为已交接')
        main = repo.resolve('refs/heads/main')
        if branch != 'main' and not (repo.ancestor(main, head) or repo.ancestor(head, main)):
            raise Unavailable('scope-mismatch', 'HEAD 与本地 main 分叉')
        if not last_event(task, 'handoff'):
            if last_event(task, 'context'):
                source = last_event(task, 'context')['data']['source_branch']
                other = repo.worktrees().get(source)
                if other and str(Path(other).resolve()) != str(Path(repo.root).resolve()):
                    out['location'] = 'other-worktree'
                    raise Unavailable('scope-mismatch', '本批尚未交接；source 在其他 worktree: ' + other)
                raise Unavailable('stale-handoff', f'{task["file"]}: 本批尚未交接')
            ev = next((e for e in reversed(task['events']) if e['type'] == 'result' and e.get('commit')), None)
            if not ev or not repo.ancestor(ev['commit'], head):
                raise Unavailable('evidence-missing', f'{task["file"]}: legacy result 锚不可达')
            out.update(status='legacy', content_commit=ev['commit'], location='main' if branch == 'main' else 'source',
                       reasons=['未提供结构化交接，待核对；历史 intent 不是下一步'])
            return out, proof if out['status'] == 'ready' else None
        proof = validate_handoff(repo, task, head)
        out.update({k: proof[k] for k in ('content_commit', 'handoff_commit')})
        check_later(repo, proof, task, head)
        if repo.ancestor(proof['handoff_commit'], main):
            # If this worktree has newer task context, validation above already refused it.
            latest = repo.task_at(main, selected)
            if last_event(latest, 'handoff')['data'] != proof['handoff']:
                proof = validate_handoff(repo, latest, main)
                out.update({k: proof[k] for k in ('content_commit', 'handoff_commit')})
            check_later(repo, proof, latest, main); out['location'] = 'main'
        elif branch == proof['context']['source_branch']:
            check_later(repo, proof, task, head); out['location'] = 'source'
        else:
            other = repo.worktrees().get(proof['context']['source_branch'])
            if other:
                out['location'] = 'other-worktree'
                raise Unavailable('scope-mismatch', 'source 由其他 worktree 承载: ' + other)
            raise Unavailable('evidence-missing', 'H/C 未进入 main，source 现场不匹配')
        nxt, reason = current_next(proof, out['location'])
        out.update(status='ready', next=nxt)
        if reason:
            out['reasons'].append(reason)
    except (Unavailable, data.Invalid, RuntimeError) as e:
        out['reasons'].append(str(e))
    return out, proof if out['status'] == 'ready' else None


MISSING_AFTER_MERGE = '交接已进入本地 main；未提供合并后下一步，待核对'


def current_next(proof, location):
    record = proof['handoff']
    if location == 'source':
        return record['next'], None
    if record['version'] == 2 and record['mode'] == 'mr':
        return record['after_merge']['next'], '合并后建议依据: ' + record['after_merge']['basis_ref']
    return None, MISSING_AFTER_MERGE


def resume_result(repo, tasks, errors, selected=None):
    return resolve_task(repo, tasks, errors, selected)[0]


def compute(root, task_id=None, resume=False):
    snapshot = compute_legacy(root)
    tasks, errors = grammar.load_progress(root)
    repo = Repository(root)
    by_id = {t['stem']: t for t in tasks}
    resolutions = {}
    for t in tasks:
        if last_event(t, 'context') or last_event(t, 'handoff'):
            resolutions[t['stem']] = resolve_task(repo, tasks, errors, t['stem'])
    next_rows = []
    for entry in snapshot['in_progress']:
        t = by_id[entry['task']]
        ctx, hand = last_event(t, 'context'), last_event(t, 'handoff')
        result, proof = resolutions.get(t['stem'], (None, None))
        entry.update(context=ctx['data'] if ctx else None, handoff=hand['data'] if hand else None,
                     location=result['location'] if result else None)
        if proof:
            entry.update(context=proof['context'], handoff=proof['handoff'])
        if entry['context']:
            entry['branch'] = entry['context']['source_branch']
            entry['worktree'] = repo.worktrees().get(entry['branch'])
            ab = repo.ahead_behind(entry['branch'])
            entry['ahead'], entry['behind'] = ab if ab else (None, None)
            entry['branch_note'] = None if ab else 'source 不存在；以交接祖先证明判定位置'
        nxt = result['next'] if result else None
        message = MISSING_AFTER_MERGE if result and MISSING_AFTER_MERGE in result['reasons'] else '未提供有效结构化交接，待核对'
        next_rows.append(dict(task=t['stem'], step=None, text=nxt['text'] if nxt else message, handoff_next=nxt))
    snapshot['next'] = next_rows
    for stem, (result, proof) in resolutions.items():
        if result['status'] != 'ready':
            snapshot['notes'].extend(f"{by_id[stem]['file']}: {e}" for e in result['reasons'])
            snapshot['conclusion'] = grammar.NOT_CHECKED
        if proof and result['location'] == 'main':
            t = repo.task_at(proof['handoff_commit'], stem)
            snapshot['landed'].append(dict(task=stem, at=last_event(t, 'handoff')['at'], step='handoff',
                text='交接写入时的成果声明：' + '；'.join(proof['handoff']['summary']['completed']),
                summary=proof['handoff']['summary'], commit=proof['handoff_commit']))
    snapshot['landed'] = sorted(snapshot['landed'], key=lambda x: x['at'], reverse=True)[:LANDED_LIMIT]
    snapshot['resume'] = None
    if task_id or resume:
        if task_id in resolutions:
            result = resolutions[task_id][0]
        else:
            result, proof = resolve_task(repo, tasks, errors, task_id)
        snapshot['resume'] = result
        if resume and result['status'] in ('ambiguous', 'unavailable') and result['task'] is None:
            for row in snapshot['next']:
                if row['task'] in result['candidates']:
                    row.update(handoff_next=None, text='；'.join(result['reasons']))
        snapshot['conclusion'] = grammar.PASS if result['status'] in ('ready', 'legacy') else grammar.NOT_CHECKED
        if task_id:
            for key in ('pending_owner', 'in_progress', 'landed', 'next'):
                snapshot[key] = [v for v in snapshot[key] if v['task'] == task_id]
    if any(e['severity'] == 'not-checked' for e in errors) and not (task_id or resume):
        snapshot['conclusion'] = grammar.NOT_CHECKED
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(prog="handoff_status.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="仓根（默认当前目录）")
    parser.add_argument("--resume", action="store_true", help="按专用规则只读选择并核验交接")
    parser.add_argument("--task", help="指定任务，不改变跨文件闭合集合")
    parser.add_argument("--json", action="store_true", help="输出 JSON（schema handoff-status/v3）")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        snapshot = compute(root, args.task, args.resume)
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"schema": SCHEMA, "conclusion": grammar.NOT_CHECKED, "notes": [str(e)]},
                             ensure_ascii=False))
        else:
            print(f"handoff_status: NOT_CHECKED（{e}）")
        return 2
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=1))
    else:
        selected_handoff = None
        selected = snapshot.get('resume')
        if selected and selected['status'] == 'ready':
            task = Repository(root).task_at(selected['handoff_commit'], selected['task'])
            selected_handoff = dict(task=selected['task'], commit=selected['handoff_commit'],
                                    event=last_event(task, 'handoff'))
        sys.stdout.write(render(snapshot, selected_handoff))
    return 0 if snapshot["conclusion"] == grammar.PASS else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # 未捕获异常映射 NOT_CHECKED / 2
        print(f"handoff_status: NOT_CHECKED（未捕获异常：{exc!r}）", file=sys.stderr)
        sys.exit(2)
