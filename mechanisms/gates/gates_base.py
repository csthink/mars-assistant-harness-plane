"""工作树读取、规则执行与结果序列化。规则来源见各检查模块。"""
import collections
import json
import os
import shutil
import stat
import subprocess

PASS = "PASS"
VIOLATION = "VIOLATION"
NOT_CHECKED = "NOT_CHECKED"
NOT_APPLICABLE = "NOT_APPLICABLE"
EXIT_CODES = {PASS: 0, VIOLATION: 1, NOT_CHECKED: 2}
Rule = collections.namedtuple("Rule", "id upstream object_class applies precondition check")
Gate = collections.namedtuple("Gate", "name rules")
Finding = collections.namedtuple("Finding", "subject rule detail")
CheckResult = collections.namedtuple("CheckResult", "check state findings reason")
RepoProfile = collections.namedtuple("RepoProfile", "kind top_level_members root_tracked_members on_demand_dirs_common on_demand_dirs_local")
Entry = collections.namedtuple("Entry", "path type mode target")

class GateError(Exception):
    """必要输入不可得，调用者返回 NOT_CHECKED。"""


def find_repo_root(start):
    root = os.path.realpath(start)
    while not os.path.lexists(os.path.join(root, ".git")):
        parent = os.path.dirname(root)
        if parent == root:
            raise GateError("自工具位置向上未找到 .git")
        root = parent
    return explicit_repo_root(root)


def explicit_repo_root(value):
    if not os.path.isabs(value):
        raise GateError("--repo-root 须为绝对路径")
    root = os.path.realpath(value)
    if not os.path.isdir(root) or not os.path.lexists(os.path.join(root, ".git")):
        raise GateError("判定仓根不存在或缺 .git：%s" % root)
    return root


def git_environment():
    # 不继承调用者的其他仓库、索引或全局配置；保留系统寻找 Git 所需 PATH。
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(LC_ALL="C", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_OPTIONAL_LOCKS="0")
    return env


class Context:
    """只读工作树。每次命令建立新实例，不跨运行缓存磁盘状态。"""
    def __init__(self, repo_root, profile, catalog):
        self.repo_root = explicit_repo_root(repo_root)
        self.profile = profile
        self.catalog = catalog
        self.cache = {}
        self.git_path = shutil.which("git")
        if self.git_path is None:
            raise GateError("Git 不可用")

    def git(self, *args):
        # 保留真实大小写与 Unicode 路径字节；-z 已保证路径不经 quotePath 转义。
        proc = subprocess.run([self.git_path, "-C", self.repo_root,
                               "-c", "core.ignoreCase=false", "-c", "core.precomposeUnicode=false",
                               "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                               *args], env=git_environment(), capture_output=True)
        if proc.returncode:
            raise GateError("git %s 失败 (%d)：%s" %
                            (" ".join(args), proc.returncode, proc.stderr.decode("utf-8", "replace").strip()))
        return proc.stdout

    def tracked_paths(self):
        if "tracked" not in self.cache:
            self.cache["tracked"] = {os.fsdecode(p) for p in self.git("ls-files", "--cached", "-z").split(b"\0") if p}
        return self.cache["tracked"]

    def entries(self):
        if "entries" not in self.cache:
            paths = self.tracked_paths() | {os.fsdecode(p) for p in self.git(
                "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p}
            entries = []
            for path in sorted(paths):
                fs = os.path.join(self.repo_root, path)
                try:
                    mode = os.lstat(fs).st_mode
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(mode):
                    entries.append(Entry(path, "symlink", "120000", os.readlink(fs)))
                elif stat.S_ISREG(mode):
                    entries.append(Entry(path, "file", "100755" if mode & 0o100 else "100644", None))
                elif stat.S_ISDIR(mode):
                    entries.append(Entry(path, "dir", "040000", None))
                else:
                    raise GateError("无法读取非常规条目：%s" % path)
            self.cache["entries"] = entries
        return self.cache["entries"]

    def read(self, path):
        # 不跟随文件或父目录符号链接越出本仓读取。
        parts = path.split("/")
        if not path or os.path.isabs(path) or any(p in ("", ".", "..") for p in parts):
            raise GateError("非法仓内路径：%s" % path)
        fs = self.repo_root
        for part in parts:
            fs = os.path.join(fs, part)
            if os.path.islink(fs):
                raise GateError("输入为符号链接：%s" % path)
        with open(fs, "rb") as stream:
            return stream.read()


def scan(ctx):
    """由文件与符号链接条目的路径派生目录结构；绝不使用目录类型条目。"""
    if "scan" in ctx.cache:
        return ctx.cache["scan"]
    dirs = set()
    files_in = {}   # 父目录 -> [（名字, Entry）]（"" = 仓根）
    for e in ctx.entries():
        if e.type == "dir":
            continue
        parts = e.path.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
        parent = "/".join(parts[:-1])
        files_in.setdefault(parent, []).append((parts[-1], e))
    dirs_in = {}    # 父目录 -> {直接子目录名}
    for d in dirs:
        parent, _, name = d.rpartition("/")
        dirs_in.setdefault(parent, set()).add(name)
    result = {"dirs": dirs, "files_in": files_in, "dirs_in": dirs_in}
    ctx.cache["scan"] = result
    return result


def top_level_dirs(ctx):
    return scan(ctx)["dirs_in"].get("", set())


def root_entries(ctx):
    return scan(ctx)["files_in"].get("", [])


def dir_files(ctx, d):
    return scan(ctx)["files_in"].get(d, [])


def dir_subdirs(ctx, d):
    return scan(ctx)["dirs_in"].get(d, set())


def strict_json_load(data_bytes):
    """严格 JSON：UTF-8、拒 BOM、拒非标准数值常量与重复成员名。"""
    if data_bytes.startswith(b"\xef\xbb\xbf"):
        raise GateError("JSON 文件起始存在 BOM")
    try:
        text = data_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise GateError("JSON 文件不是合法 UTF-8：%s" % exc) from exc

    def _reject(token):
        raise GateError("非标准数值常量：%s" % token)

    def _pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GateError("JSON 成员名重复：%s" % key)
            result[key] = value
        return result

    try:
        return json.loads(text, parse_constant=_reject, object_pairs_hook=_pairs)
    except json.JSONDecodeError as exc:
        raise GateError("JSON 解析失败：%s" % exc) from exc


def load_catalog(unit_path=None):
    p = os.path.join(unit_path or unit_dir(), "rules_catalog.json")
    with open(p, "rb") as f:
        return strict_json_load(f.read())


def unit_dir():
    return os.path.dirname(os.path.realpath(__file__))


def profile_from_catalog(catalog, kind="bootstrap"):
    if kind != "bootstrap":
        raise GateError("仅支持 bootstrap 仓型")
    boot = catalog["profiles"][kind]
    values = []
    for key in RepoProfile._fields[1:]:
        entries = boot[key]["values"]
        if (not isinstance(entries, list) or not entries
                or any(not isinstance(v, str) or not v or "/" in v for v in entries)
                or len(entries) != len(set(entries))):
            raise GateError("仓型集合非法：%s" % key)
        values.append(frozenset(entries))
    return RepoProfile(kind, *values)


def run_rule(rule, ctx):
    try:
        a = rule.applies(ctx)
    except Exception as exc:
        return CheckResult(rule.id, NOT_CHECKED, [], "适用性判定失败：%s: %s" % (type(exc).__name__, exc))
    if not isinstance(a, bool):
        return CheckResult(rule.id, NOT_CHECKED, [], "适用性返回值非法")
    if a is False:
        return CheckResult(rule.id, NOT_APPLICABLE, [], None)
    try:
        p = rule.precondition(ctx)
    except Exception as exc:
        return CheckResult(rule.id, NOT_CHECKED, [], "前置判定失败：%s: %s" % (type(exc).__name__, exc))
    if p is not None and not isinstance(p, str):
        return CheckResult(rule.id, NOT_CHECKED, [], "前置返回值非法")
    if p == "":
        return CheckResult(rule.id, NOT_CHECKED, [], "前置返回值非法（理由为空）")
    if isinstance(p, str):
        return CheckResult(rule.id, NOT_CHECKED, [], p)
    try:
        findings = rule.check(ctx)
    except Exception as exc:
        return CheckResult(rule.id, NOT_CHECKED, [], "检查执行异常：%s: %s" % (type(exc).__name__, exc))
    # Finding 序列：list 与 tuple 均合法（impl-r17 R17-N1）
    if (not isinstance(findings, (list, tuple))
            or any(not isinstance(f, Finding) for f in findings)):
        return CheckResult(rule.id, NOT_CHECKED, [], "返回值非法")
    if findings:
        return CheckResult(rule.id, VIOLATION, list(findings), None)
    return CheckResult(rule.id, PASS, [], None)


def aggregate_states(states):
    states = list(states)
    if NOT_CHECKED in states:
        return NOT_CHECKED
    if VIOLATION in states:
        return VIOLATION
    return PASS


def run_gate(gate, ctx):
    if not gate.rules:
        return [CheckResult(gate.name, NOT_CHECKED, [], "检查集合为空")]
    return [run_rule(rule, ctx) for rule in gate.rules]


def finding_json(f):
    return {"subject": f.subject, "rule": f.rule, "detail": f.detail}


def check_json(c):
    obj = {"check": c.check, "state": c.state,
           "findings": [finding_json(f) for f in c.findings]}
    if c.reason is not None:
        obj["reason"] = c.reason
    return obj
