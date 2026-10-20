"""review_channel_secrets — 秘密来源（评审通道设计 §7.5）。

official-direct / aggregator 的 key 只从密钥目录内、Registry `key_file` 声明的密钥文件读取（O_NOFOLLOW 打开；须为当前用户
所有、无组与其他用户权限的普通文件；内容为一行可打印 ASCII），不读父进程环境变量、不读 `~/.zshrc`，不设回退。
base URL 仍由 `~/.zshrc` 非执行解析（只接受 `export NAME=<literal>` 整行、三种字面量；一切 substitution / glob /
重定向 / 管道 / 控制运算符 / 行接续 / 行尾注释 / 重复声明 fail closed）。另有认证文件三态（经基座），
以及本次 attempt 扫描集的构造。解析结果只进入进程内的 SecretHandle，绝不进入任何报告；报告与失败消息只含文件名、
变量名与状态词，不含值、长度、目录路径或前后缀。
"""
import errno
import os
import re
import stat

import review_channel_base as base
import review_channel_contract as C

ZSHRC_PATH = os.path.join(os.path.expanduser("~"), ".zshrc")
_BARE_LITERAL_RE = re.compile(r"^[A-Za-z0-9._:/~%-]+$")
_SINGLE_QUOTED_RE = re.compile(r"^'[^']*'$")
_DOUBLE_QUOTED_RE = re.compile(r'^"[^"$`\\]*"$')
_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
STATES = ("detected_literal", "missing", "duplicate", "dynamic_rejected")
# 密钥文件状态：present 之外都不交出值；missing / empty 与「变量未声明」同为 secret-missing，其余为 secret-file-rejected
KEY_FILE_STATES = ("present", "missing", "empty", "not_regular_file", "foreign_owner", "permissions_too_open", "malformed",
                   "unreadable")
KEY_FILE_REPORT_STATE = "key_file_present"
KEY_FILE_MAX_BYTES = 4096
_KEY_VALUE_RE = re.compile(rb"[\x21-\x7e]+")
_KEY_FILE_HINTS = {
    "missing": "missing",
    "empty": "empty",
    "not_regular_file": "not_regular_file (symbolic links, directories and special files are refused)",
    "foreign_owner": "foreign_owner (the file must be owned by the current user)",
    "permissions_too_open": "permissions_too_open (group or other permission bits are set; owner-only access such as 0600 is required)",
    "malformed": "malformed (one line of printable ASCII without spaces, at most %d bytes, is required)" % KEY_FILE_MAX_BYTES,
    "unreadable": "unreadable",
}


def key_directory(environ=None):
    """密钥目录（§7.5）：XDG_CONFIG_HOME 已设置且为绝对路径时取 $XDG_CONFIG_HOME/mars-assistant，否则 $HOME/.config/mars-assistant。
    与 ZSHRC_PATH 同属派生路径，命令行无注入口；覆盖只经进程环境的 XDG_CONFIG_HOME 或 HOME（非秘密设置）。"""
    env = os.environ if environ is None else environ
    xdg = env.get("XDG_CONFIG_HOME")
    if isinstance(xdg, str) and xdg and os.path.isabs(xdg):
        root = xdg
    else:
        home = env.get("HOME") or os.path.expanduser("~")
        root = os.path.join(home, ".config")
    return os.path.join(root, C.KEY_DIRECTORY_NAME)


class SecretHandle:
    """进程内秘密句柄：值只经 `value_of` 取出给适配器执行上下文；`scan_set` 供落盘前终检。"""

    def __init__(self):
        self._values = {}
        self._extra = []

    def put(self, name, value):
        self._values[name] = value

    def add_scan_values(self, values):
        for v in values:
            if v:
                self._extra.append(v)

    def value_of(self, name):
        return self._values.get(name)

    def drop_values(self, values):
        """移除与治理工件结构字节重叠、不可受值级脱敏保护的秘密值（preflight 已以 secret-structural-collision 拒绝）。"""
        drop = set(values)
        self._values = {n: v for n, v in self._values.items() if (v.encode("utf-8") if isinstance(v, str) else v) not in drop}
        self._extra = [v for v in self._extra if (v.encode("utf-8") if isinstance(v, str) else v) not in drop]

    def names(self):
        return sorted(self._values)

    def scan_set(self):
        out = []
        for v in list(self._values.values()) + self._extra:
            if isinstance(v, str):
                v = v.encode("utf-8")
            if v and v not in out:
                out.append(v)
        return out


def parse_zshrc_literals(text, names):
    """返回 {name: {"state": ..., "value": str|None}}。整行匹配：行须恰为 `export NAME=<rhs>`（允许首尾空白）。"""
    results = {n: {"state": "missing", "value": None} for n in names}
    occurrences = {n: [] for n in names}
    for raw in text.split("\n"):
        line = raw.strip()
        if not line.startswith("export "):
            continue
        rest = line[len("export "):]
        if "=" not in rest:
            continue
        name, rhs = rest.split("=", 1)
        name = name.strip()
        if name in occurrences:
            occurrences[name].append(rhs)
    for n in names:
        found = occurrences[n]
        if not found:
            continue
        if len(found) > 1:
            results[n] = {"state": "duplicate", "value": None}
            continue
        rhs = found[0]
        if _BARE_LITERAL_RE.match(rhs):
            value = rhs
        elif _SINGLE_QUOTED_RE.match(rhs) or _DOUBLE_QUOTED_RE.match(rhs):
            value = rhs[1:-1]
        else:
            results[n] = {"state": "dynamic_rejected", "value": None}
            continue
        results[n] = {"state": "detected_literal", "value": value}
    return results


def resolve_env_names(names, zshrc_path=ZSHRC_PATH):
    """解析变量名集合；返回 (handle_updates: {name: value}, report: {name: state})。
    任一非 detected_literal 即抛 PreflightError（状态只进失败码，不带值）。"""
    for n in names:
        if not _NAME_RE.match(n):
            raise base.PreflightError("registry-invalid", "environment variable name grammar: %s" % n)
    try:
        with open(zshrc_path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        raise base.PreflightError("zshrc-unreadable", "configuration source ~/.zshrc unreadable")
    parsed = parse_zshrc_literals(text, list(names))
    report = {n: parsed[n]["state"] for n in names}
    for n in names:
        st = parsed[n]["state"]
        if st == "missing":
            raise base.PreflightError("secret-missing", "variable %s: missing" % n)
        if st == "duplicate":
            raise base.PreflightError("secret-duplicate", "variable %s: duplicate" % n)
        if st == "dynamic_rejected":
            raise base.PreflightError("secret-dynamic-rejected", "variable %s: dynamic_rejected" % n)
    return {n: parsed[n]["value"] for n in names}, report


def inspect_key_file(directory, file_name):
    """密钥文件状态（§7.5）。返回 (state, value|None)，state 属 KEY_FILE_STATES；只有 present 交出值。
    以 O_NOFOLLOW | O_NONBLOCK 打开后对同一描述符 fstat，判定与读取之间不再按路径重开（无检查后使用竞态）。"""
    if not isinstance(file_name, str) or not C.KEY_FILE_NAME_RE.fullmatch(file_name):
        raise base.PreflightError("registry-invalid", "key file name grammar")
    path = os.path.join(directory, file_name)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return "missing", None
        if exc.errno == errno.ELOOP:
            return "not_regular_file", None
        return "unreadable", None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return "not_regular_file", None
        if st.st_uid != os.geteuid():
            return "foreign_owner", None
        if st.st_mode & 0o077:
            return "permissions_too_open", None
        data = b""
        while len(data) <= KEY_FILE_MAX_BYTES:
            chunk = os.read(fd, KEY_FILE_MAX_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
    except OSError:
        return "unreadable", None
    finally:
        os.close(fd)
    if len(data) > KEY_FILE_MAX_BYTES:
        return "malformed", None
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if not data:
        return "empty", None
    if not _KEY_VALUE_RE.fullmatch(data):
        return "malformed", None
    return "present", data.decode("ascii")


def read_key_file(directory, file_name):
    """读取一个密钥文件；非 present 即抛 PreflightError：missing / empty → secret-missing（与变量未声明同级），
    其余 → secret-file-rejected。消息只含文件名与状态词。"""
    state, value = inspect_key_file(directory, file_name)
    if state == "present":
        return value
    code = "secret-missing" if state in ("missing", "empty") else "secret-file-rejected"
    raise base.PreflightError(code, "key file %s: %s" % (file_name, _KEY_FILE_HINTS[state]))


def resolve_for_provider(provider, handle, zshrc_path=ZSHRC_PATH, key_dir=None):
    """按 provider kind 解析秘密：official-direct / aggregator 从密钥文件 key_file 取 key（以 key_env 为名放入句柄），
    从 ~/.zshrc 解析 base_env；builtin-native 核认证文件三态并扩展扫描集。返回环境状态报告（只含状态词）。"""
    kind = provider["kind"]
    if kind == "builtin-native":
        state, values = base.inspect_auth_source(provider["auth_source"])
        if state == "missing":
            raise base.PreflightError("auth-source-missing", "authentication source: missing")
        if state == "malformed":
            raise base.PreflightError("auth-source-malformed", "authentication source: malformed")
        handle.add_scan_values(values)
        return {"auth_source": state}
    key_env, key_file = provider["key_env"], provider.get("key_file")
    if not isinstance(key_env, str) or not _NAME_RE.match(key_env):
        raise base.PreflightError("registry-invalid", "environment variable name grammar: %s" % key_env)
    if key_file is None:
        raise base.PreflightError("registry-invalid", "provider declares no key_file (key files need registry schema %s)"
                                  % C.REGISTRY_SCHEMA)
    key = read_key_file(key_dir if key_dir is not None else key_directory(), key_file)
    values, report = resolve_env_names([provider["base_env"]], zshrc_path)
    handle.put(key_env, key)
    for n, v in values.items():
        handle.put(n, v)
    return {key_env: KEY_FILE_REPORT_STATE, **report}


def union_scan_set(registry_path, zshrc_path=ZSHRC_PATH, key_dir=None):
    """分配 attempt 之前的预扫描集（R7-B1 整改）：Registry 全部 provider 声明的秘密（key 文件值、base 字面量、builtin 认证载荷）
    的并集；任一 provider 解析失败只跳过（此处不判失败，失败仍由 preflight 清单按选中 Profile 判定）。返回 bytes 列表。"""
    key_dir = key_dir if key_dir is not None else key_directory()
    try:
        reg = base.strict_json_load(base.read_bytes(registry_path))
        providers = reg["providers"]
    except (OSError, ValueError, UnicodeDecodeError, KeyError, TypeError):
        return []
    out = []
    for prov in (providers.values() if isinstance(providers, dict) else []):
        if not isinstance(prov, dict):
            continue
        try:
            if prov.get("kind") == "builtin-native":
                state, values = base.inspect_auth_source(prov["auth_source"])
                if state == "present":
                    out.extend(values)
            else:
                # R8-B1 整改：key 文件与 base 变量逐个解析——一个来源不可解析不丢弃另一个已知值
                key_file = prov.get("key_file")
                if isinstance(key_file, str):
                    try:
                        out.append(read_key_file(key_dir, key_file))
                    except base.PreflightError:
                        pass
                name = prov.get("base_env")
                if isinstance(name, str):
                    try:
                        values, _report = resolve_env_names([name], zshrc_path)
                        out.extend(values.values())
                    except base.PreflightError:
                        pass
        except (base.PreflightError, KeyError, TypeError, OSError):
            continue
    handle = SecretHandle()
    handle.add_scan_values(out)
    return handle.scan_set()
