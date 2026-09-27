"""整文件生成实现。只读 freshness 核对与 manifest --write 共用本模块。

输入映射取 rules_catalog.json 的 generated 字段，经 Context 读取；
支持 frontmatter、叙述与表格。非法输入不自动规范化。
"""

import fnmatch
import os
import re
import tempfile

import gates_base as base
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'repo-layout'))
try:
    import history_read as history
except ImportError:
    history = None



class GenerationFailure(Exception):
    """生成失败（fail closed）：携带输入路径与情形名，供 precondition 落 NOT_CHECKED 理由。"""

    def __init__(self, path, reason):
        super().__init__("%s：%s" % (path, reason))
        self.path = path
        self.reason = reason


PLACEHOLDER_RE = re.compile(r"^<!--table:(.+)-->$")

# 单元格取值的合法性前置：控制字节闭集
_ILLEGAL_CELL_BYTES = frozenset(
    list(range(0x00, 0x09)) + [0x0B, 0x0C] + list(range(0x0E, 0x20)))


# ---------------------------------------------------------------- 输入侧前置

def _check_file_level(path, data):
    """文件级前置。fail closed，一律不做规范化。"""
    if data.startswith(b"\xef\xbb\xbf"):
        raise GenerationFailure(path, "文件起始存在 BOM")
    if b"\r" in data:
        raise GenerationFailure(path, "文件内出现 CR")
    try:
        data.decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise GenerationFailure(path, "文件字节不是合法 UTF-8")
    if not data.endswith(b"\n") or data.endswith(b"\n\n") or data == b"\n":
        raise GenerationFailure(path, "文件末尾不是恰一个 LF")


def load_readme_data(ctx, data_path):
    """严格 JSON 读入 readme_data.json（文件级前置 + 严格解码）。"""
    try:
        raw = ctx.read(data_path)
    except Exception as exc:
        raise GenerationFailure(data_path, "数据文件不可读（%s）" % type(exc).__name__)
    _check_file_level(data_path, raw)
    try:
        return base.strict_json_load(raw)
    except base.GateError as exc:
        raise GenerationFailure(data_path, str(exc))


# ---------------------------------------------------------------- 单元格与表

def _cell(value):
    """单元格取值规范化：合法性前置 + 先反斜杠后竖线的转义。"""
    b = value.encode("utf-8")
    if b"\n" in b or b"\r" in b:
        raise GenerationFailure(value, "单元格取值含换行字节")
    if any(byte in _ILLEGAL_CELL_BYTES for byte in b):
        raise GenerationFailure(value, "单元格取值含控制字节")
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _multi(values):
    """多值：各值分别规范化后按 LC_ALL=C 字节序升序、以 、 连接；空集恒写 无。"""
    if not values:
        return "无"
    processed = sorted((_cell(v) for v in values),
                       key=lambda s: s.encode("utf-8"))
    return "、".join(processed)


def _table_bytes(headers, rows, sort_col=0):
    """table 块文法：单元格两侧各恰一空格；分隔行恰 N 个 ---；数据行按排序键字节序升序。"""
    out = []
    out.append("| " + " | ".join(_cell(h) for h in headers) + " |")
    out.append("|" + "---|" * len(headers))
    for row in sorted(rows, key=lambda r: r[sort_col].encode("utf-8")):
        out.append("| " + " | ".join(row) + " |")
    return ("\n".join(out) + "\n").encode("utf-8")


# ---------------------------------------------------------------- 三张表的派生

def _units_rows(ctx):
    rows = []
    for unit in sorted(base.dir_subdirs(ctx, "mechanisms")):
        unit_path = "mechanisms/" + unit
        names = sorted(n for (n, _e) in base.dir_files(ctx, unit_path))
        designs = [n for n in names
                   if fnmatch.fnmatch(n, "HarnessPlane_*_Design_v*.md")]
        pyfiles = [n for n in names if n.endswith(".py")]
        selftests = [n for n in pyfiles
                     if fnmatch.fnmatch(n, "*_selftest.py")
                     or fnmatch.fnmatch(n, "selftest*.py")]
        paired = {}  # 主文件 -> [selftest...]；配不上的 selftest 不入本表、按普通可执行物单列
        for s in selftests:
            target = None
            # 同族判定：按固定顺序逐条尝试，模式匹配且目标主文件实存者即定
            if s.endswith("_selftest.py"):
                cand = s[:-len("_selftest.py")] + ".py"
                if cand in pyfiles and cand != s:
                    target = cand
            if target is None and s.startswith("selftest_"):
                cand = "gates_" + s[len("selftest_"):]
                if cand in pyfiles:
                    target = cand
            if target is None and s == "selftest.py" and "gates.py" in pyfiles:
                target = "gates.py"
            if target is not None:
                paired.setdefault(target, []).append(s)
        paired_children = {s for kids in paired.values() for s in kids}

        # 配对链嵌套渲染（impl-r17 R17-B5）：一个 selftest 文件自身又是别件的配对目标时
        # （如 selftest.py 挂着 selftest_selftest.py），其括注随链嵌套，使每个直下 .py
        # 恰好出现一次、不静默消失。链按命名规则严格缩短，不可能成环。
        def render(n):
            v = "`%s`" % n
            kids = paired.get(n)
            if kids:
                v += "（selftest：%s）" % "、".join(
                    render(s) for s in sorted(kids, key=lambda x: x.encode("utf-8")))
            return v

        exec_values = [render(n) for n in pyfiles if n not in paired_children]
        rows.append((
            _cell("`%s`" % unit),
            _cell("`%s/`" % unit_path),
            _multi(["`%s`" % d for d in designs]),
            _multi(exec_values) if exec_values else "无",
        ))
    return rows


def _top_level_map_rows(ctx, data, data_path):
    top = data.get("top_level")
    if not isinstance(top, dict):
        raise GenerationFailure(data_path, "缺 top_level 对象")
    rows = []
    for name in sorted(base.top_level_dirs(ctx)):
        entry = top.get(name)
        if not isinstance(entry, dict) or "zone" not in entry or "gloss" not in entry:
            raise GenerationFailure(
                data_path, "顶层条目 %s 缺 zone / gloss（生成器不填占位值）" % name)
        rows.append((_cell("`%s/`" % name), _cell(str(entry["zone"])),
                     _cell(str(entry["gloss"]))))
    return rows


def _subject_roster_rows(ctx):
    if history is None:
        raise GenerationFailure("mechanisms/repo-layout/history_read.py", "history-unavailable: shared helper absent")
    mech = set(base.dir_subdirs(ctx, "mechanisms"))
    gov = set(base.dir_subdirs(ctx, "records/governance"))
    rev = set(base.dir_subdirs(ctx, "reviews"))
    historical = {}
    if history.LOCATIONS in {e.path for e in ctx.entries()}:
        try:
            declarations = history.validate_locations_syntax(ctx.read(history.LOCATIONS))
        except history.HistoryReadError as exc:
            raise GenerationFailure(history.LOCATIONS, exc.code + ': ' + exc.message)
        for row in declarations:
            for path in row['selection']['roots'] + row['selection']['paths']:
                match = re.match(r'^(reviews|records/governance)/([a-z0-9][a-z0-9-]*)/', path)
                if match:
                    historical.setdefault(match[2], set()).add(match[1]+'/'+match[2]+'/')
    rows = []
    for subject in sorted(mech | gov | rev | set(historical)):
        sources = []
        if subject in mech:
            sources.append("机制单元")
        if subject in gov:
            sources.append("治理记录")
        if subject in rev:
            sources.append("评审证据")
        evidence = []
        if subject in gov:
            evidence.append("`records/governance/%s/`" % subject)
        if subject in rev:
            evidence.append("`reviews/%s/`" % subject)
        declared = [_cell('`'+p+'` (仅声明，未验证对象)') for p in sorted(historical.get(subject, []))]
        rows.append((_cell("`%s`" % subject), _multi(sources), _multi(evidence), _multi(declared)))
    return rows


def _build_table(ctx, name, data, data_path):
    if name == "units":
        return _table_bytes(("单元", "目录", "设计正本", "可执行物"), _units_rows(ctx))
    if name == "top_level_map":
        return _table_bytes(("顶层条目", "区", "一句话语义"),
                            _top_level_map_rows(ctx, data, data_path))
    if name == "subject_roster":
        return _table_bytes(("subject", "现存派生来源", "现存证据落点", "历史来源声明"), _subject_roster_rows(ctx))
    raise GenerationFailure(name, "未知表名（生成映射与实现不一致）")


# ---------------------------------------------------------------- frontmatter 与合成

def _frontmatter(entry):
    lines = ["---",
             "auto-generated: true",
             "generator: manifest --write",
             "source: %s" % entry["source"]]
    if entry.get("data"):
        lines.append("data: %s" % entry["data"])
    lines.append("---")
    return ("\n".join(lines) + "\n").encode("utf-8")


def generated_entry(catalog, path):
    entries = catalog.get("generated")
    if not isinstance(entries, list) or len(entries) != 2:
        raise GenerationFailure("rules_catalog.json", "generated 须声明 README.md 与 mechanisms/MECHANISMS.md")
    mapping = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("path") in mapping:
            raise GenerationFailure("rules_catalog.json", "生成映射非法或目标重复")
        target = entry.get("path")
        expected = {"README.md": ["top_level_map", "subject_roster"],
                    "mechanisms/MECHANISMS.md": ["units"]}.get(target)
        if (expected is None or entry.get("table_names") != expected
                or not isinstance(entry.get("source"), str)
                or (target == "README.md" and not isinstance(entry.get("data"), str))):
            raise GenerationFailure("rules_catalog.json", "生成目标、来源或表名无效")
        mapping[target] = entry
    if path not in mapping:
        raise GenerationFailure(path, "生成映射中无此路径")
    return mapping[path]


def generate(ctx, path):
    """生成一个受管文件的全部字节。失败一律 GenerationFailure（fail closed，不改写任何输入字节）。"""
    cache = ctx.cache.setdefault("generated", {})
    if path in cache:
        result = cache[path]
        if isinstance(result, GenerationFailure):
            raise result
        return result
    try:
        result = _generate_uncached(ctx, path)
    except GenerationFailure as exc:
        cache[path] = exc
        raise
    cache[path] = result
    return result


def _generate_uncached(ctx, path):
    entry = generated_entry(ctx.catalog, path)
    source_path = entry["source"]
    try:
        narrative = ctx.read(source_path)
    except Exception as exc:
        raise GenerationFailure(source_path, "叙述源不可读（%s）" % type(exc).__name__)
    _check_file_level(source_path, narrative)
    data = None
    if entry.get("data"):
        data = load_readme_data(ctx, entry["data"])
    table_names = list(entry.get("table_names", []))

    lines = narrative.decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # 末尾恰一个 LF 已核；行表不含结尾空元素
    if lines and lines[0] == "":
        raise GenerationFailure(
            source_path, "叙述源首行为空行，与 frontmatter 块间「恰一个空行」文法冲突")

    seen = {}
    placeholder_at = {}
    for i, line in enumerate(lines):
        m = PLACEHOLDER_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name not in table_names:
            raise GenerationFailure(
                source_path, "第 %d 行占位表名未登记：%s" % (i + 1, name))
        seen[name] = seen.get(name, 0) + 1
        placeholder_at[i] = name
        # 占位行两侧文法：每个现存侧恰一空行
        if i > 0:
            if lines[i - 1] != "":
                raise GenerationFailure(
                    source_path, "第 %d 行占位表 %s 上方非恰一空行" % (i + 1, name))
            if i > 1 and lines[i - 2] == "":
                raise GenerationFailure(
                    source_path, "第 %d 行占位表 %s 上方出现连续空行" % (i + 1, name))
        if i < len(lines) - 1:
            if lines[i + 1] != "":
                raise GenerationFailure(
                    source_path, "第 %d 行占位表 %s 下方非恰一空行" % (i + 1, name))
            if i < len(lines) - 2 and lines[i + 2] == "":
                raise GenerationFailure(
                    source_path, "第 %d 行占位表 %s 下方出现连续空行" % (i + 1, name))
    for name in table_names:
        if seen.get(name, 0) != 1:
            raise GenerationFailure(
                source_path, "表 %s 的占位行出现 %d 次（须恰一次）" % (name, seen.get(name, 0)))

    tables = {name: _build_table(ctx, name, data, entry.get("data"))
              for name in table_names}
    out = bytearray()
    out += _frontmatter(entry)
    out += b"\n"
    for i, line in enumerate(lines):
        if i in placeholder_at:
            out += tables[placeholder_at[i]]
        else:
            out += line.encode("utf-8") + b"\n"
    return bytes(out)


# ---------------------------------------------------------------- 门侧接口（precondition / check 消费）

def generation_precondition(ctx, path):
    try:
        generate(ctx, path)
        return None
    except GenerationFailure as exc:
        return "生成失败：%s" % exc


def compare(ctx, path):
    expected = generate(ctx, path)
    try:
        actual = ctx.read(path)
    except FileNotFoundError:
        return [base.Finding(path, _rule_for(path), "受管文件缺失")]
    if actual == expected:
        return []
    offset = next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b),
                  min(len(actual), len(expected)))
    return [base.Finding(path, _rule_for(path),
                         "与重新生成的字节不等（首个不等字节偏移 %d）" % offset)]


def _rule_for(path):
    return "mechanisms-generated" if path == "mechanisms/MECHANISMS.md" else "readme-generated"


# 维护动作：先算完所有输出，逐文件原子替换，不承诺跨文件回滚。

def write_all(ctx):
    targets = ["mechanisms/MECHANISMS.md", "README.md"]
    outputs = {}
    try:
        for path in targets:
            outputs[path] = generate(ctx, path)
        for path in targets:
            fs = ctx.repo_root
            for part in path.split("/"):
                fs = os.path.join(fs, part)
                if os.path.islink(fs):
                    raise GenerationFailure(path, "目标或父目录是符号链接")
    except Exception as exc:
        return 2, ["未写入任何文件：%s" % exc, "未完成：" + "、".join(targets)]
    messages = []
    for index, path in enumerate(targets):
        fs = os.path.join(ctx.repo_root, path)
        tmp = None
        failure = None
        try:
            if os.path.islink(fs) or os.path.realpath(os.path.dirname(fs)) != os.path.dirname(fs):
                raise GenerationFailure(path, "目标或父目录变为符号链接")
            fd, tmp = tempfile.mkstemp(prefix=".hp-write-", dir=os.path.dirname(fs))
            with os.fdopen(fd, "wb") as stream:
                stream.write(outputs[path])
            os.replace(tmp, fs)
            tmp = None
        except Exception as exc:
            failure = "写入失败：%s（%s）" % (path, exc)
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    messages.append("临时文件未清理：%s" % tmp)
        if failure:
            return 2, messages + [failure, "未完成：" + "、".join(targets[index:])]
        messages.append("已写入 %s（%d 字节）" % (path, len(outputs[path])))
    return 0, messages
