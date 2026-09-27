"""自测声明：review_channel_base（canonical JSON 第 24 类、秘密扫描、原子原语、符号链接安全、允许集合解析）。"""
import json
import os

import review_channel_base as base


def canonical_equivalence(e):
    a = base.canonical_json({"b": [1, {"z": "é", "a": None}], "a": "x"})
    b = base.canonical_json(json.loads('{"a":"x","b":[1,{"a":null,"z":"\\u00e9"}]}'))
    e.check(a == b, "equivalent objects must serialize identically")
    e.check(base.sha256_bytes(a) == base.sha256_bytes(b), "same hash")
    e.check(b"\\u00e9" not in a and "é".encode("utf-8") in a, "non-ASCII must not be escaped")
    e.check(a == b'{"a":"x","b":[1,{"a":null,"z":"\xc3\xa9"}]}', "key order and separators: %r" % a)
    e.check(not a.endswith(b"\n"), "no trailing newline")


def strict_json(e):
    e.expect_error(lambda: base.strict_json_load(b'{"a":1,"a":2}'), exc_type=ValueError, message="duplicate member")
    e.expect_error(lambda: base.strict_json_load(b'{"a":NaN}'), exc_type=ValueError, message="NaN")
    e.expect_error(lambda: base.strict_json_load(b'\xef\xbb\xbf{}'), exc_type=ValueError, message="BOM")
    e.check(base.strict_json_load(b'{"a":[1,2]}') == {"a": [1, 2]}, "valid JSON parses")
    # r18 自查整改（R18-B2 线索）：孤立代理项转义在值与成员名两处均拒绝；合法代理对放行
    e.expect_error(lambda: base.strict_json_load(b'{"a":"x\\ud800y"}'), exc_type=ValueError, message="lone surrogate in a value is rejected")
    e.expect_error(lambda: base.strict_json_load(b'{"\\udfff":1}'), exc_type=ValueError, message="lone surrogate in a member name is rejected")
    e.check(base.strict_json_load(b'{"a":["\\ud83d\\ude00"]}') == {"a": ["\U0001F600"]}, "valid surrogate pair decodes")
    e.check(base.is_strict_int(3) and not base.is_strict_int(True), "bool is not a strict int")


def secret_scrub(e):
    data, hit = base.scrub_secrets(b"token sk-abc end", [b"sk-abc"])
    e.check(hit and data == b"token " + base.REDACTED + b" end", "scrub replaces the secret")
    data, hit = base.scrub_secrets(b"clean", [b"sk-abc", b""])
    e.check(not hit and data == b"clean", "no hit leaves bytes unchanged")
    e.check(base.contains_secret(b"xx sk-abc", [b"sk-abc"]) and not base.contains_secret(b"xx", [b"sk-abc"]), "contains")
    # R18-B1 / R19-B1：治理 JSON 工件的结构感知脱敏——字符串值与动态成员名替换，容器形状不动，同名成员以 #n 区分
    obj, hit = base.scrub_json({"usage": {"sk-abc": 1, "x sk-abc": 2, "[REDACTED-SECRET]": 3}, "n": ["sk-abc", 1, None, True], "d": {"k": "clean"}}, [b"sk-abc", b""])
    e.check(hit and obj == {"usage": {"[REDACTED-SECRET]": 1, "x [REDACTED-SECRET]": 2, "[REDACTED-SECRET]#2": 3}, "n": ["[REDACTED-SECRET]", 1, None, True], "d": {"k": "clean"}},
            "structure-aware scrub: string values and dynamic member names replaced, shape intact, duplicates suffixed: %s" % obj)
    obj, hit = base.scrub_json({"a": "x"}, [b"\xff\xfe"])
    e.check(not hit and obj == {"a": "x"}, "non-UTF-8 secret cannot occur in a JSON string value")
    # R20-B1 闭包：替换与相邻字节可拼出另一秘密（"T] b" 跨哨兵边界）——字节级脱敏迭代到不动点
    data, hit = base.scrub_secrets(b"a sk-abc b", [b"T] b", b"sk-abc"])   # 顺序使第二趟成为必需
    e.check(hit and not base.contains_secret(data, [b"sk-abc", b"T] b"]), "byte-level scrub reaches a fixed point across the sentinel boundary: %r" % data)
    # R21-B1：哨兵 + 相邻字节逐字节再生秘密的链条（每趟消耗一个 Z）——趟数界 = len(data) + 1，不再被固定上限截断
    chain = [b"[REDACTED-SECRET]Z", b"sk-abc"]
    data, hit = base.scrub_secrets(b"sk-abc" + b"Z" * 40, chain)
    e.check(hit and not base.contains_secret(data, chain) and data == base.REDACTED, "a 40-step regeneration chain still reaches the fixed point: %r" % data[:60])


def auth_three_state(e):
    d = e.tmpdir("auth")
    p = os.path.join(d, "auth.json")
    e.check(base.inspect_auth_source(p)[0] == "missing", "missing")
    open(p, "w").write("{not json")
    e.check(base.inspect_auth_source(p)[0] == "malformed", "malformed json")
    open(p, "w").write('{"a": "short"}')
    e.check(base.inspect_auth_source(p)[0] == "malformed", "no collectable material is malformed")
    open(p, "w").write('{"tokens": {"access_token": "abc"}, "x": "%s"}' % ("L" * 20))
    state, values = base.inspect_auth_source(p)
    e.check(state == "present" and set(values) == {"abc", "L" * 20}, "present with marker keys and long leaves: %s" % values)
    target = os.path.join(d, "copy.json")
    vals = base.stage_auth_copy(p, target)
    e.check(oct(os.stat(target).st_mode)[-3:] == "600" and set(vals) == set(values), "staged copy 0600")
    open(p, "w").write("{}")
    e.expect_error(lambda: base.stage_auth_copy(p, target + "2"), code="auth-source-malformed-at-staging",
                   message="re-validation before staging")
    e.check(not os.path.exists(target + "2"), "no copy placed on staging failure")
    os.unlink(p)
    e.expect_error(lambda: base.stage_auth_copy(p, target + "3"), code="auth-source-missing-at-staging", message="missing at staging")


def remove_tree_never_follows_symlinks(e):
    d = e.tmpdir("rt")
    outside = os.path.join(d, "outside.bin")
    open(outside, "wb").write(b"x")
    os.chmod(outside, 0o755)
    tree = os.path.join(d, "tree")
    os.makedirs(os.path.join(tree, "sub"))
    os.symlink(outside, os.path.join(tree, "sub", "link"))
    outdir = os.path.join(d, "outdir")
    os.makedirs(outdir)
    open(os.path.join(outdir, "keep"), "w").write("k")
    os.symlink(outdir, os.path.join(tree, "dirlink"))
    base.remove_tree(tree)
    e.check(not os.path.exists(tree), "tree removed")
    e.check(oct(os.stat(outside).st_mode)[-3:] == "755", "symlink target permission untouched")
    e.check(os.path.exists(os.path.join(outdir, "keep")), "symlinked directory content untouched")
    base.remove_tree(os.path.join(d, "never-existed"))
    e.check(True, "absent tree is a no-op (R5-B3)")


def link_primitives(e):
    d = e.tmpdir("link")
    target = os.path.join(d, "receipt.json")
    e.check(base.write_then_link(target, b"one", "tmp-a") is True, "first link wins")
    e.check(base.write_then_link(target, b"two", "tmp-b") is False, "second link EEXIST")
    e.check(open(target, "rb").read() == b"one", "bytes of the winner")
    e.check(not os.path.exists(os.path.join(d, "tmp-a")) and not os.path.exists(os.path.join(d, "tmp-b")), "temp files cleaned")
    e.expect_error(lambda: base.write_new(target, b"x"), exc_type=FileExistsError, message="write_new never overwrites")
    base.write_atomic_replace(target, b"three")
    e.check(open(target, "rb").read() == b"three", "atomic replace")


def process_liveness(e):
    me = os.getpid()
    tok = base.process_start_token(me)
    e.check(tok is not None and base.owner_alive(me, tok) is True, "own process alive with matching token")
    e.check(base.owner_alive(me, "different-token") is False, "token mismatch = pid reused = not alive")
    e.check(base.owner_alive(me, None) is None, "null recorded token is undeterminable, never dead (R2-B9)")
    e.check(base.owner_alive(2 ** 22 - 1, "x") is False, "absent pid not alive")


def mutation_verdict(e):
    """§12 第 17 类：变异被捕获 ⇔ 声明的每个 must_fail 用例都变红（r18 自查整改，R18-B3 线索）。"""
    import review_channel_selftest as ST
    e.check(ST.mutation_outcome(["a", "b"], ["a", "b"], ["a", "b"])[0] == "CAUGHT", "all declared cases red → caught")
    e.check(ST.mutation_outcome(["a", "b"], ["b", "a"], ["a"])[0] == "ESCAPED", "one declared case green → escaped")
    e.check(ST.mutation_outcome(["a"], ["a"], [])[0] == "ESCAPED", "no red → escaped")
    e.check(ST.mutation_outcome(["a", "b"], ["a"], ["a"])[0] == "ENGINE_ERROR", "declared case did not run → engine error")


def cases():
    return [
        ("selftest.mutation-verdict", mutation_verdict),
        ("base.canonical-json", canonical_equivalence),
        ("base.strict-json", strict_json),
        ("base.secret-scrub", secret_scrub),
        ("base.auth-three-state", auth_three_state),
        ("base.remove-tree-symlink-safe", remove_tree_never_follows_symlinks),
        ("base.link-primitives", link_primitives),
        ("base.process-liveness", process_liveness),
    ]
