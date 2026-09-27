"""自测声明：review_channel_secrets（第 3 类：三种字面量正例、动态 / 重复 / 缺失负例、不泄值、扫描集）。"""
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
    h = S.SecretHandle()
    prov = {"kind": "official-direct", "key_env": "K1", "base_env": "B1"}
    rep = S.resolve_for_provider(prov, h, z)
    e.check(h.value_of("K1") == "sk-secret-one" and b"https://x/v1" in h.scan_set() and rep["K1"] == "detected_literal", "provider resolution")
    h.add_scan_values(["tok-abc", ""])
    e.check(b"tok-abc" in h.scan_set() and b"" not in h.scan_set(), "scan set extension drops empties")


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
    scan = S.union_scan_set(reg, z)
    e.check(b"sk-fake-secret-value-123" in scan and b"https://fake.invalid/v1" in scan, "union scan set carries every registry-declared literal")
    e.check(S.union_scan_set(reg + ".missing", z) == [] and S.union_scan_set(reg, z + ".missing") == [], "unresolvable sources yield an empty pre-scan (no failure here)")
    partial = e.fake_zshrc("export FAKE_API_KEY=sk-fake-secret-value-123\nexport FAKE_API_BASE=$DYN\n", path_dir=e.tmpdir("zp"))
    scan = S.union_scan_set(reg, partial)
    e.check(b"sk-fake-secret-value-123" in scan, "a sibling name that fails to resolve does not drop the known literal (R8-B1)")


def cases():
    return [
        ("secrets.union-scan", union_scan),
        ("secrets.literals", literals),
        ("secrets.resolution-no-leak", resolution_and_no_leak),
        ("secrets.builtin-auth", builtin_auth),
    ]
