"""自测声明：review_channel_secrets（第 3 类：密钥文件各状态与无回退、密钥目录、三种字面量正例、动态 / 重复 / 缺失负例、
不泄值、扫描集）。"""
import os

import review_channel_secrets as S


def literals(e):
    text = "\n".join([
        "export A=bare-value_1:/x~%",
        "export B='single quoted'",
        'export C="double quoted"',
        "export D=$(whoami)",
        "export E=${HOME}/x",
        "export F=`cmd`",
        "export G=a*b",
        "export H=x > /dev/null",
        "export I=x | y",
        'export J="has $dollar"',
        "export K='it''s'",
        "export L=1",
        "export L=2",
        "export M=x # comment",
        "export N=abc\\",
        "  export O='indented is fine'",
        "",
    ])
    names = list("ABCDEFGHIJKLMNOP")
    res = S.parse_zshrc_literals(text, names)
    e.check(res["A"] == {"state": "detected_literal", "value": "bare-value_1:/x~%"}, "bare literal")
    e.check(res["B"]["value"] == "single quoted" and res["C"]["value"] == "double quoted", "quoted literals")
    for n in "DEFGHIJKMN":
        e.check(res[n]["state"] == "dynamic_rejected" and res[n]["value"] is None, "%s must be dynamic_rejected: %s" % (n, res[n]))
    e.check(res["L"]["state"] == "duplicate" and res["L"]["value"] is None, "duplicate")
    e.check(res["O"]["state"] == "detected_literal", "leading whitespace tolerated")
    e.check(res["P"]["state"] == "missing", "missing")


def resolution_and_no_leak(e):
    z = e.fake_zshrc("export K1=sk-secret-one\nexport B1='https://x/v1'\nexport DUP=1\nexport DUP=2\nexport DYN=$(x)\n")
    values, report = S.resolve_env_names(["K1", "B1"], z)
    e.check(values == {"K1": "sk-secret-one", "B1": "https://x/v1"} and report == {"K1": "detected_literal", "B1": "detected_literal"}, "resolved")
    for names, code in ((["K1", "NOPE"], "secret-missing"), (["DUP"], "secret-duplicate"), (["DYN"], "secret-dynamic-rejected")):
        exc = e.expect_error(lambda n=names: S.resolve_env_names(n, z), code=code, message=code)
        e.check("sk-secret-one" not in exc.message and "https://x/v1" not in exc.message, "no value in the report")
    e.expect_error(lambda: S.resolve_env_names(["bad-name"], z), code="registry-invalid", message="variable name grammar")
    e.expect_error(lambda: S.resolve_env_names(["K1"], os.path.join(e.tmpdir("nz"), "absent")), code="zshrc-unreadable", message="unreadable")
    # provider 解析：key 只来自密钥文件（以 key_env 为名入句柄），base 来自 zshrc
    kd = e.tmpdir("kd")
    e.fake_key_file("sk-file-one", path_dir=kd, name="k1.key")
    h = S.SecretHandle()
    prov = {"kind": "official-direct", "key_env": "K1", "key_file": "k1.key", "base_env": "B1"}
    rep = S.resolve_for_provider(prov, h, z, kd)
    e.check(h.value_of("K1") == "sk-file-one" and h.value_of("B1") == "https://x/v1" and b"https://x/v1" in h.scan_set()
            and b"sk-secret-one" not in h.scan_set() and rep == {"K1": "key_file_present", "B1": "detected_literal"},
            "provider resolution takes the key from the key file only: %s" % rep)
    h.add_scan_values(["tok-abc", ""])
    e.check(b"tok-abc" in h.scan_set() and b"" not in h.scan_set(), "scan set extension drops empties")
    # Registry v6 之前的 provider（无 key_file）不能取得 key
    e.expect_error(lambda: S.resolve_for_provider({"kind": "aggregator", "key_env": "K1", "base_env": "B1"}, S.SecretHandle(), z, kd),
                   code="registry-invalid", message="provider without key_file")
    e.expect_error(lambda: S.resolve_for_provider(dict(prov, key_env="bad-name"), S.SecretHandle(), z, kd),
                   code="registry-invalid", message="key_env grammar still enforced")


def key_file_states(e):
    """密钥文件（§7.5）：各拒绝态与失败码、不泄值与目录路径、无环境变量与 zshrc 回退、O_NOFOLLOW、属主与权限。"""
    kd = e.tmpdir("kfs")
    held = "fake-key-file-value-777"
    z = e.fake_zshrc("export K9=sk-zshrc-must-not-be-used\nexport B9='https://b9/v1'\n")
    prov = {"kind": "official-direct", "key_env": "K9", "key_file": "k9.key", "base_env": "B9"}

    def rejected(state, code):
        exc = e.expect_error(lambda: S.read_key_file(kd, "k9.key"), code=code, message="%s → %s" % (state, code))
        e.check(state in exc.message and held not in exc.message and kd not in exc.message,
                "%s: message names the state only, never the value or directory: %s" % (state, exc.message))
        e.check(S.inspect_key_file(kd, "k9.key") == (state, None), "%s: inspect yields no value" % state)
        h = S.SecretHandle()
        e.expect_error(lambda: S.resolve_for_provider(prov, h, z, kd), code=code, message="%s fails the provider resolution" % state)
        e.check(h.value_of("K9") is None and h.scan_set() == [], "%s: nothing enters the handle" % state)

    # 缺失：同名环境变量与 zshrc 声明都不回退
    saved = os.environ.get("K9")
    os.environ["K9"] = "sk-env-must-not-be-used"
    try:
        rejected("missing", "secret-missing")
    finally:
        if saved is None:
            os.environ.pop("K9", None)
        else:
            os.environ["K9"] = saved
    e.check(S.inspect_key_file(os.path.join(kd, "absent-dir"), "k9.key") == ("missing", None), "absent key directory is missing")
    e.fake_key_file(b"", path_dir=kd, name="k9.key")
    rejected("empty", "secret-missing")
    e.fake_key_file(b"\n", path_dir=kd, name="k9.key")
    rejected("empty", "secret-missing")
    e.fake_key_file(held, path_dir=kd, name="k9.key", mode=0o644)
    rejected("permissions_too_open", "secret-file-rejected")
    e.fake_key_file(held, path_dir=kd, name="k9.key", mode=0o620)
    rejected("permissions_too_open", "secret-file-rejected")
    e.fake_key_file(held, path_dir=kd, name="k9.key", mode=0o604)
    rejected("permissions_too_open", "secret-file-rejected")
    for raw in (b"two\nlines\n", b"has space\n", b" lead\n", b"trail \n", b"tab\there\n", b"\xe2\x80\x8bzw\n", b"x" * (S.KEY_FILE_MAX_BYTES + 1),
                b"ctl\x07\n", b"double\n\n"):
        e.fake_key_file(raw, path_dir=kd, name="k9.key")
        rejected("malformed", "secret-file-rejected")
    # 属主：以替换 geteuid 模拟他人所有（非特权进程不能造出他人所有的文件）
    e.fake_key_file(held, path_dir=kd, name="k9.key")
    real_geteuid = os.geteuid
    os.geteuid = lambda: real_geteuid() + 1
    try:
        rejected("foreign_owner", "secret-file-rejected")
    finally:
        os.geteuid = real_geteuid
    # 符号链接（即使指向 0600 普通文件）、目录、FIFO 都不是普通文件
    os.remove(os.path.join(kd, "k9.key"))
    target = e.fake_key_file(held, path_dir=e.tmpdir("kfs-target"), name="target.key")
    os.symlink(target, os.path.join(kd, "k9.key"))
    rejected("not_regular_file", "secret-file-rejected")
    os.remove(os.path.join(kd, "k9.key"))
    os.mkdir(os.path.join(kd, "k9.key"), 0o700)
    rejected("not_regular_file", "secret-file-rejected")
    os.rmdir(os.path.join(kd, "k9.key"))
    os.mkfifo(os.path.join(kd, "k9.key"), 0o600)
    rejected("not_regular_file", "secret-file-rejected")
    os.remove(os.path.join(kd, "k9.key"))
    # 不可读（0000：属主也无读权限；以 root 运行时 open 仍成功，此断言只在非 root 下成立）
    if os.geteuid() != 0:
        e.fake_key_file(held, path_dir=kd, name="k9.key", mode=0o000)
        rejected("unreadable", "secret-file-rejected")
        os.chmod(os.path.join(kd, "k9.key"), 0o600)
    # 正例：0600 与 0400，单个结尾换行（LF 或 CRLF）或无换行
    for raw, mode in ((held + "\n", 0o600), (held, 0o400), (held + "\r\n", 0o600)):
        e.fake_key_file(raw.encode("ascii"), path_dir=kd, name="k9.key", mode=mode)
        e.check(S.read_key_file(kd, "k9.key") == held, "present: %r / %o" % (raw[-2:], mode))
        os.chmod(os.path.join(kd, "k9.key"), 0o600)
    # 文件名文法在读取端同样封闭（Registry 校验之外的第二道）
    for bad in ("../k9.key", "k9", ".k9.key", "sub/k9.key", "k9.key\n"):
        e.expect_error(lambda b=bad: S.inspect_key_file(kd, b), code="registry-invalid", message="key file name grammar %r" % bad)
    e.check(set(S.KEY_FILE_STATES) == {"present", "missing", "empty", "not_regular_file", "foreign_owner", "permissions_too_open",
                                        "malformed", "unreadable"}, "key file state closed set")


def key_directory(e):
    """密钥目录：XDG_CONFIG_HOME（绝对路径）优先，否则 HOME/.config；目录名固定。"""
    e.check(S.key_directory({"HOME": "/h", "XDG_CONFIG_HOME": "/x/cfg"}) == os.path.join("/x/cfg", "mars-assistant"), "absolute XDG_CONFIG_HOME wins")
    e.check(S.key_directory({"HOME": "/h", "XDG_CONFIG_HOME": "rel/cfg"}) == os.path.join("/h", ".config", "mars-assistant"),
            "a relative XDG_CONFIG_HOME is ignored (XDG base directory rule)")
    e.check(S.key_directory({"HOME": "/h", "XDG_CONFIG_HOME": ""}) == os.path.join("/h", ".config", "mars-assistant"), "empty XDG_CONFIG_HOME is ignored")
    e.check(S.key_directory({"HOME": "/h"}) == os.path.join("/h", ".config", "mars-assistant"), "default under HOME")
    e.check(S.key_directory({"HOME": e.tmp_root}) == e.home_key_dir(), "the engine's sanitized-start key directory equals the module's derivation")


def builtin_auth(e):
    d = e.tmpdir("auth")
    p = os.path.join(d, "auth.json")
    prov = {"kind": "builtin-native", "auth_source": p}
    h = S.SecretHandle()
    e.expect_error(lambda: S.resolve_for_provider(prov, h, None), code="auth-source-missing", message="missing")
    open(p, "w").write("{}")
    e.expect_error(lambda: S.resolve_for_provider(prov, h, None), code="auth-source-malformed", message="malformed")
    open(p, "w").write('{"tokens": {"access_token": "AT-1"}}')
    rep = S.resolve_for_provider(prov, h, None)
    e.check(rep == {"auth_source": "present"} and b"AT-1" in h.scan_set(), "present and scan set extended")
    e.check("AT-1" not in str(rep), "report never carries content")


def union_scan(e):
    reg = e.fake_registry()
    z = e.fake_zshrc()
    kd = e.tmpdir("ukd")
    e.fake_key_file(path_dir=kd)
    scan = S.union_scan_set(reg, z, kd)
    e.check(b"sk-fake-secret-value-123" in scan and b"https://fake.invalid/v1" in scan, "union scan set carries every registry-declared secret")
    e.check(S.union_scan_set(reg + ".missing", z, kd) == [], "an unreadable registry yields an empty pre-scan (no failure here)")
    e.check(S.union_scan_set(reg, z + ".missing", os.path.join(kd, "absent")) == [], "unresolvable sources yield an empty pre-scan (no failure here)")
    partial = e.fake_zshrc("export FAKE_API_BASE=$DYN\n", path_dir=e.tmpdir("zp"))
    scan = S.union_scan_set(reg, partial, kd)
    e.check(b"sk-fake-secret-value-123" in scan, "an unresolvable base does not drop the known key file value (R8-B1)")
    scan = S.union_scan_set(reg, z, os.path.join(kd, "absent"))
    e.check(b"https://fake.invalid/v1" in scan, "a missing key file does not drop the known base literal (R8-B1)")
    legacy = e.fake_zshrc("export FAKE_API_KEY=sk-zshrc-legacy\nexport FAKE_API_BASE='https://fake.invalid/v1'\n", path_dir=e.tmpdir("zl"))
    e.check(b"sk-zshrc-legacy" not in S.union_scan_set(reg, legacy, kd), "a key exported in ~/.zshrc is not a key source")


def cases():
    return [
        ("secrets.union-scan", union_scan),
        ("secrets.literals", literals),
        ("secrets.resolution-no-leak", resolution_and_no_leak),
        ("secrets.key-file", key_file_states),
        ("secrets.key-directory", key_directory),
        ("secrets.builtin-auth", builtin_auth),
    ]
