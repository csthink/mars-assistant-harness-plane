#!/usr/bin/env python3
"""handoff_lint.py · 进度文件（HANDOFF/progress/<task>.md）的可选文法核对。

判断辅助工具，不是门：不接 pre-commit、不进 gates all、人工发起。行文法的规则正本 = handoff-protocol
设计 §3；本文件是其机械形态，也是 handoff_status.py 的解析器来源（status 只读不判）。

调用形态：
  python3 mechanisms/handoff-protocol/handoff_lint.py [--root <仓根>] [--json]
退出码由 handoff-protocol 设计 §6 定义：0 = PASS（无违规；warning 不判红）、1 = VIOLATION、
2 = NOT_CHECKED（progress 目录缺失、文件不可读、用法错误或未捕获异常）。

进度文件文法（一任务一文件、只追加）：
  第 1 行  `# task: <任务编号>`，任务编号 = 文件名 stem。
  第 2 行  类别行，三种之一：
           `- 类别: 里程碑任务 · 名单项 <id> · 分支意图 <branch>`   （<id> = stem）
           `- 类别: 台账任务 · 承载项 <ledger-id> · 分支意图 <branch>` （stem = <ledger-id> 小写、`:` 改 `-`）
           `- 类别: 仓级`                                            （只允许 repo.md）
  其后    每行一事件 `- <时间到分钟> · <行型> · …`，空行允许，行型：
           intent · <步骤名> · <文本>
           result · <步骤名> · <文本> [· commit:<40 位 SHA>]         （缺锚只 warning）
           note   · <文本>
           open   · <id> · <OD|KB> · <题名> · <现状 / 被什么挡住>     （<id> = `<stem>:OD-NN | KB-NN`）
           answer · <id> · Owner 原话… [· until <YYYY-MM-DD>]          （只对 OD）
           close  · <id> · <依据> [· commit:<40 位 SHA>]               （任意 id，含他任务与 legacy:）
           context · <JSON>：version/source_branch/target_branch/base_commit/authority_ref
           handoff · <JSON>：v1=version/mode/content_commit/summary/evidence/entries/next；v2 另必填 after_merge
  JSON 文法完整字段与类型见 RULES 的 context/handoff 项；JSON 内分隔符不再拆分。
  闭合 = 任一进度文件内存在该 id 的 answer 或 close 行（集合语义，与顺序无关）。
规则清单（每条可红可绿，见 RULES）。转录行 = 含「（转录自 HANDOFF/」的 open 行：切换点自只读历史层
转录而来，`legacy:` 前缀只允许出现在 repo.md 的转录行；含转录行的文件对铸造编号只核严格递增，
不含转录行的文件另核自 01 起连续。
"""
import argparse
import json
import os
import re
import sys
sys.dont_write_bytecode = True
import handoff_data as data

PASS, VIOLATION, NOT_CHECKED = "PASS", "VIOLATION", "NOT_CHECKED"
EXIT = {PASS: 0, VIOLATION: 1, NOT_CHECKED: 2}
PROGRESS_DIR = "HANDOFF/progress"
SEP = " · "
TYPES = ("intent", "result", "note", "open", "answer", "close", "context", "handoff")
KINDS = ("OD", "KB")
CATEGORY_MILESTONE, CATEGORY_LEDGER, CATEGORY_REPO = "里程碑任务", "台账任务", "仓级"
REPO_STEM = "repo"
TRANSCRIPTION_MARKER = "（转录自 HANDOFF/"
LEGACY_PREFIX = "legacy"

RE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?$")
RE_ID = re.compile(r"^([a-z0-9][a-z0-9-]*):(OD|KB)-(\d{2,})$")
RE_STEP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RE_COMMIT = re.compile(r"^commit:([0-9a-f]{40})$")
RE_UNTIL = re.compile(r"^until (\d{4}-\d{2}-\d{2})$")
RE_TITLE = re.compile(r"^# task: (\S+)$")
RE_CAT_MILESTONE = re.compile(r"^- 类别: 里程碑任务 · 名单项 (\S+) · 分支意图 (\S.*)$")
RE_CAT_LEDGER = re.compile(r"^- 类别: 台账任务 · 承载项 (\S+) · 分支意图 (\S.*)$")
RE_CAT_REPO = re.compile(r"^- 类别: 仓级$")

RULES = {
    "physical": "UTF-8 无 BOM、无 CR、末尾恰一个 LF",
    "header-title": "第 1 行 `# task: <stem>`，stem = 文件名 stem",
    "header-category": "第 2 行为三种类别行之一；里程碑任务的名单项 = stem；台账任务的 stem = 承载项小写且 `:` 改 `-`；仓级只允许 repo.md",
    "row-grammar": "事件行 `- <时间> · <行型> · …`，字段以「 · 」分隔且非空",
    "row-time": "时间为 ISO 8601 到分钟（可带 Z 或 ±HH:MM）",
    "row-type": "行型 ∈ intent · result · note · open · answer · close · context · handoff",
    "context": "version=1 整数；source/target 合法短分支且不同，target=main；base_commit 完整小写 SHA；authority_ref 非空仓内定位",
    "handoff": "version 为整数 1 或 2（布尔拒绝）；v1 只兼容读取，v2 新写；mode=pause/mr，content_commit 完整 SHA；summary={completed,remaining}字符串数组；evidence=[{commit,path,locator}]去重，mr 非空；entries=[{path,role}]，role=current/history/generated，generated 另含 sources 路径数组和 generator argv，源列为 current/history；next={kind,text,authority_ref}，kind=wait-owner/continue-authorized/none，none 后两字段 null，wait-owner 授权 null，continue-authorized 两字段非空；v2 after_merge 在 pause 必为 null，在 mr 必为 {next,basis_ref} 闭集，next 同文法，basis_ref 非空；basis_ref 及两个 continue-authorized 定位须在 C 中且路径列 current，本任务进度仅用 path:line 指向已存在合法事件；其他定位为 path#locator、path:line 或唯一台账 id，引用不生成授权",
    "json": "拒绝重复/未知键、未知版本、布尔冒充整数、空白串及控制字符；路径为仓内 POSIX 文件，禁止绝对/空组件/../反斜杠/Git 元数据/attempts/凭据；Git 存在与 C/H 关系由 status/workflow 核；未知版本 NOT_CHECKED",
    "row-fields": "各行型最低字段数：intent / result 步骤名 + 文本；note 文本；open id + 种类 + 题名 + 现状；answer / close id + 文本",
    "step-name": "intent / result 的步骤名为 [A-Za-z0-9._-] 串",
    "id-grammar": "id 形如 `<task>:OD-NN` 或 `<task>:KB-NN`（NN 两位起）",
    "id-prefix": "open 铸造的 id 前缀 = 文件名 stem；`legacy:` 前缀只允许出现在 repo.md 的转录行",
    "id-kind": "open 的种类字段与 id 内种类一致",
    "id-duplicate": "同一 id 在全部进度文件内只 open 一次",
    "id-sequence": "同一文件同一种类的铸造编号按文件顺序严格递增",
    "id-gap": "不含转录行的文件内，同一种类的铸造编号自 01 起连续",
    "answer-kind": "answer 只对 OD",
    "answer-until": "answer 的 until 字段形如 `until YYYY-MM-DD`",
    "commit-anchor": "commit 锚形如 `commit:<40 位小写十六进制>`",
    "ref-born": "answer / close 引用的 id 在任一进度文件内有 open 行",
    "result-anchor": "warning：result 行末尾建议带 commit 锚",
}


def finding(file, line, rule, message, severity="violation"):
    return {"file": file, "line": line, "rule": rule, "message": message, "severity": severity}


def stem_of_ledger_id(ledger_id):
    return ledger_id.lower().replace(":", "-")


# ---------------------------------------------------------------- 单文件解析

def parse_file(path, rel, raw=None):
    """解析一个进度文件。返回 (task 对象, findings)。task 在头两行不可解析时仍尽量返回。"""
    findings = []
    task = {"file": rel, "stem": os.path.basename(rel)[:-3], "category": None,
            "ref": None, "branch": None, "events": []}
    try:
        if raw is None:
            with open(path, "rb") as f:
                raw = f.read()
    except OSError as e:
        raise RuntimeError(f"无法读取 {rel}：{e}")
    if raw.startswith(b"\xef\xbb\xbf"):
        findings.append(finding(rel, 1, "physical", "含 UTF-8 BOM"))
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise RuntimeError(f"{rel} 不是合法 UTF-8：{e}")
    if "\r" in text:
        findings.append(finding(rel, 1, "physical", "含 CR 字节"))
        text = text.replace("\r", "")
    if not text.endswith("\n") or text.endswith("\n\n"):
        findings.append(finding(rel, max(1, text.count("\n")), "physical", "末尾须恰一个 LF"))
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    stem = task["stem"]

    m = RE_TITLE.match(lines[0]) if lines else None
    if not m:
        findings.append(finding(rel, 1, "header-title", "第 1 行须为 `# task: <stem>`"))
    elif m.group(1) != stem:
        findings.append(finding(rel, 1, "header-title", f"任务编号 {m.group(1)} ≠ 文件名 stem {stem}"))

    cat_line = lines[1] if len(lines) > 1 else ""
    mm, ml, mr = RE_CAT_MILESTONE.match(cat_line), RE_CAT_LEDGER.match(cat_line), RE_CAT_REPO.match(cat_line)
    if mm:
        task["category"], task["ref"], task["branch"] = CATEGORY_MILESTONE, mm.group(1), mm.group(2)
        if mm.group(1) != stem:
            findings.append(finding(rel, 2, "header-category", f"名单项 {mm.group(1)} ≠ stem {stem}"))
    elif ml:
        task["category"], task["ref"], task["branch"] = CATEGORY_LEDGER, ml.group(1), ml.group(2)
        if not RE_ID.match(ml.group(1)):
            findings.append(finding(rel, 2, "header-category", f"承载项 {ml.group(1)} 不是台账 id"))
        elif stem_of_ledger_id(ml.group(1)) != stem:
            findings.append(finding(rel, 2, "header-category",
                                    f"承载项 {ml.group(1)} 的小写形态 ≠ stem {stem}"))
    elif mr:
        task["category"] = CATEGORY_REPO
        if stem != REPO_STEM:
            findings.append(finding(rel, 2, "header-category", "仓级类别只允许 repo.md"))
    else:
        findings.append(finding(rel, 2, "header-category", "第 2 行须为三种类别行之一"))
    if stem == REPO_STEM and task["category"] not in (None, CATEGORY_REPO):
        findings.append(finding(rel, 2, "header-category", "repo.md 的类别须为 仓级"))

    for lineno, line in enumerate(lines[2:], 3):
        if line == "":
            continue
        ev, fs = parse_event(rel, lineno, line, stem, task["category"])
        findings.extend(fs)
        if ev is not None:
            if ev["type"] == "handoff" and not any(e["type"] == "context" for e in task["events"]):
                findings.append(finding(rel, lineno, "context", "handoff 前没有 context"))
            task["events"].append(ev)
    return task, findings


def parse_event(rel, lineno, line, stem, category):
    findings = []
    if not line.startswith("- "):
        return None, [finding(rel, lineno, "row-grammar", "事件行须以 `- ` 开头")]
    prefix = line[2:].split(SEP, 2)
    fields = prefix if len(prefix) == 3 and prefix[1] in ("context", "handoff") else line[2:].split(SEP)
    if len(fields) < 2 or any(f.strip() == "" or f != f.strip() for f in fields):
        return None, [finding(rel, lineno, "row-grammar", "字段以「 · 」分隔且每个字段非空、无首尾空白")]
    at, typ, rest = fields[0], fields[1], fields[2:]
    if not RE_TIME.match(at):
        findings.append(finding(rel, lineno, "row-time", f"时间 {at!r} 不是 ISO 8601 到分钟"))
    if typ not in TYPES:
        findings.append(finding(rel, lineno, "row-type", f"未知行型 {typ!r}"))
        return None, findings
    ev = {"line": lineno, "at": at, "type": typ, "fields": rest}

    if typ in ("context", "handoff"):
        try:
            data.require(len(rest) == 1, "JSON 事件需要一个对象")
            value = data.loads(rest[0])
            getattr(data, typ)(value)
            ev["data"] = value
            ev["raw"] = line
        except data.Invalid as e:
            severity = "not-checked" if isinstance(e, data.Unsupported) else "violation"
            return None, findings + [finding(rel, lineno, typ, str(e), severity)]
    elif typ in ("intent", "result"):
        if len(rest) < 2:
            findings.append(finding(rel, lineno, "row-fields", f"{typ} 须有步骤名与文本"))
            return None, findings
        ev["step"] = rest[0]
        if not RE_STEP.match(rest[0]):
            findings.append(finding(rel, lineno, "step-name", f"步骤名 {rest[0]!r} 不合文法"))
        text = rest[1:]
        ev["commit"] = None
        if typ == "result":
            if text[-1].startswith("commit:"):
                mc = RE_COMMIT.match(text[-1])
                if mc:
                    ev["commit"] = mc.group(1)
                    text = text[:-1]
                else:
                    findings.append(finding(rel, lineno, "commit-anchor", f"commit 锚 {text[-1]!r} 不合文法"))
            else:
                findings.append(finding(rel, lineno, "result-anchor", "result 行未带 commit 锚", "warning"))
            if not text:
                findings.append(finding(rel, lineno, "row-fields", "result 须有文本"))
                return None, findings
        ev["text"] = SEP.join(text)
    elif typ == "note":
        if len(rest) < 1:
            findings.append(finding(rel, lineno, "row-fields", "note 须有文本"))
            return None, findings
        ev["text"] = SEP.join(rest)
    elif typ == "open":
        if len(rest) < 4:
            findings.append(finding(rel, lineno, "row-fields", "open 须有 id、种类、题名、现状"))
            return None, findings
        ev["id"], ev["kind"], ev["title"], ev["status"] = rest[0], rest[1], rest[2], SEP.join(rest[3:])
        ev["transcribed"] = TRANSCRIPTION_MARKER in ev["status"]
        mi = RE_ID.match(rest[0])
        if not mi:
            findings.append(finding(rel, lineno, "id-grammar", f"id {rest[0]!r} 不合文法"))
            return None, findings
        prefix, kind, nn = mi.group(1), mi.group(2), int(mi.group(3))
        ev["prefix"], ev["nn"] = prefix, nn
        if rest[1] not in KINDS:
            findings.append(finding(rel, lineno, "id-kind", f"种类 {rest[1]!r} 须为 OD 或 KB"))
        elif rest[1] != kind:
            findings.append(finding(rel, lineno, "id-kind", f"种类字段 {rest[1]} 与 id 内种类 {kind} 不一致"))
        if prefix == LEGACY_PREFIX:
            if not (stem == REPO_STEM and ev["transcribed"]):
                findings.append(finding(rel, lineno, "id-prefix", "`legacy:` 前缀只允许出现在 repo.md 的转录行"))
        elif prefix != stem:
            findings.append(finding(rel, lineno, "id-prefix", f"铸造前缀 {prefix} ≠ 文件名 stem {stem}"))
    elif typ in ("answer", "close"):
        if len(rest) < 2:
            findings.append(finding(rel, lineno, "row-fields", f"{typ} 须有 id 与文本"))
            return None, findings
        ev["id"] = rest[0]
        text = rest[1:]
        mi = RE_ID.match(rest[0])
        if not mi:
            findings.append(finding(rel, lineno, "id-grammar", f"id {rest[0]!r} 不合文法"))
            return None, findings
        ev["kind"] = mi.group(2)
        if typ == "answer":
            ev["until"] = None
            if text[-1].startswith("until"):
                mu = RE_UNTIL.match(text[-1])
                if mu:
                    ev["until"] = mu.group(1)
                    text = text[:-1]
                else:
                    findings.append(finding(rel, lineno, "answer-until", f"until 字段 {text[-1]!r} 不合文法"))
            if mi.group(2) != "OD":
                findings.append(finding(rel, lineno, "answer-kind", "answer 只对 OD；KB 用 close"))
        else:
            ev["commit"] = None
            if text[-1].startswith("commit:"):
                mc = RE_COMMIT.match(text[-1])
                if mc:
                    ev["commit"] = mc.group(1)
                    text = text[:-1]
                else:
                    findings.append(finding(rel, lineno, "commit-anchor", f"commit 锚 {text[-1]!r} 不合文法"))
        if not text:
            findings.append(finding(rel, lineno, "row-fields", f"{typ} 须有文本"))
            return None, findings
        ev["text"] = SEP.join(text)
    return ev, findings


# ---------------------------------------------------------------- 目录级载入与跨文件规则

def load_progress(root):
    """读入 HANDOFF/progress/ 全部进度文件。返回 (tasks, findings)；目录缺失抛 RuntimeError。"""
    d = os.path.join(root, PROGRESS_DIR)
    if not os.path.isdir(d):
        raise RuntimeError(f"{PROGRESS_DIR}/ 不存在")
    tasks, findings = [], []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md") or name.startswith("."):
            continue
        rel = f"{PROGRESS_DIR}/{name}"
        full = os.path.join(d, name)
        if os.path.commonpath([os.path.realpath(root), os.path.realpath(full)]) != os.path.realpath(root):
            raise RuntimeError(f"{rel}: symlink 越出仓库")
        task, fs = parse_file(full, rel)
        tasks.append(task)
        findings.extend(fs)
    findings.extend(cross_checks(tasks))
    return tasks, findings


def cross_checks(tasks):
    findings = []
    born = {}
    for t in tasks:
        has_transcription = any(e["type"] == "open" and e.get("transcribed") for e in t["events"])
        last_nn = {}
        for e in t["events"]:
            if e["type"] != "open" or "nn" not in e:
                continue
            if e["id"] in born:
                findings.append(finding(t["file"], e["line"], "id-duplicate",
                                        f"{e['id']} 已在 {born[e['id']]} open 过"))
            else:
                born[e["id"]] = f"{t['file']}:{e['line']}"
            if e["prefix"] != t["stem"]:
                continue  # legacy 转录行不参与铸造编号序列
            prev = last_nn.get(e["kind"])
            if prev is not None and e["nn"] <= prev:
                findings.append(finding(t["file"], e["line"], "id-sequence",
                                        f"{e['id']} 的编号未严格递增（前一个 {prev:02d}）"))
            elif not has_transcription:
                expect = 1 if prev is None else prev + 1
                if e["nn"] != expect:
                    findings.append(finding(t["file"], e["line"], "id-gap",
                                            f"{e['id']} 的编号须为 {expect:02d}（自 01 起连续）"))
            last_nn[e["kind"]] = max(e["nn"], prev or 0)
    for t in tasks:
        for e in t["events"]:
            if e["type"] in ("answer", "close") and e.get("id") and e["id"] not in born:
                findings.append(finding(t["file"], e["line"], "ref-born",
                                        f"{e['type']} 引用的 {e['id']} 在任何进度文件内都没有 open 行"))
    return findings


def closure(tasks):
    """返回 {id: [闭合事件…]}：任一进度文件内的 answer / close 行。"""
    closed = {}
    for t in tasks:
        for e in t["events"]:
            if e["type"] in ("answer", "close"):
                closed.setdefault(e["id"], []).append({"task": t["stem"], "type": e["type"],
                                                       "at": e["at"], "line": e["line"]})
    return closed


def open_items(tasks):
    """返回 [open 事件…]（附 task 字段），按文件顺序。"""
    items = []
    for t in tasks:
        for e in t["events"]:
            if e["type"] == "open" and "nn" in e:
                items.append(dict(e, task=t["stem"]))
    return items


# ---------------------------------------------------------------- 命令行

def main(argv=None):
    parser = argparse.ArgumentParser(prog="handoff_lint.py", description=__doc__ + "\n" + "\n".join(k + ": " + v for k, v in RULES.items()),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="仓根（默认当前目录）")
    parser.add_argument("--json", action="store_true", help="结论以 JSON 打到 stdout")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        tasks, findings = load_progress(root)
    except RuntimeError as e:
        return emit(args.json, NOT_CHECKED, [], reason=str(e))
    conclusion = (NOT_CHECKED if any(f["severity"] == "not-checked" for f in findings) else
                  VIOLATION if any(f["severity"] == "violation" for f in findings) else PASS)
    return emit(args.json, conclusion, findings, files=[t["file"] for t in tasks])


def emit(as_json, conclusion, findings, reason=None, files=()):
    if as_json:
        print(json.dumps({"tool": "handoff_lint", "conclusion": conclusion, "reason": reason,
                          "files": list(files), "findings": findings}, ensure_ascii=False, indent=1))
    else:
        for f in findings:
            tag = "warning" if f["severity"] == "warning" else f["rule"]
            print(f"{f['file']}:{f['line']} [{tag}] {f['message']}")
        tail = f"（{reason}）" if reason else f"（{len(files)} 个进度文件）"
        print(f"handoff_lint: {conclusion}{tail}")
    return EXIT[conclusion]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # 未捕获异常映射 NOT_CHECKED / 2
        print(f"handoff_lint: NOT_CHECKED（未捕获异常：{exc!r}）", file=sys.stderr)
        sys.exit(2)
