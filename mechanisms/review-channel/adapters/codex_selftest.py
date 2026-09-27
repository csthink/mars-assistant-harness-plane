"""自测声明：adapters/codex（第 14 类：配置生成、环境构造、受保护前缀、事件流提取、识别探针以假 codex 脚本离线实撞）。

假 codex 是一段 shell 脚本：不读取任何环境变量（适配器从空构造环境，这本身就是被验证的义务），
行为由脚本同目录的 `control` 与 `message` 两个文件控制。
"""
import os
import stat

import review_channel_base as base
import review_channel_runtime as RT
import review_channel_secrets as S

FAKE_CODEX = """#!/bin/sh
here=$(dirname "$0")
if [ "$1" = "--version" ]; then echo "codex-cli 9.9.9"; exit 0; fi
mode=$(cat "$here/control" 2>/dev/null)
case "$mode" in
  reject) echo "Error loading config: unknown configuration field zzz" 1>&2; exit 1;;
  auth) echo "401 Unauthorized" 1>&2; exit 1;;
esac
if [ "$mode" = "residue" ]; then echo raw-secret-echo > "$CODEX_HOME/keep"; chflags uchg "$CODEX_HOME/keep"; fi
if [ "$mode" = "residue-dir" ]; then mkdir "$CODEX_HOME/dark"; echo raw-secret-echo > "$CODEX_HOME/dark/f"; chflags uchg "$CODEX_HOME/dark/f"; chmod 000 "$CODEX_HOME/dark"; fi
url=$(sed -n 's/^base_url = "\\(.*\\)"$/\\1/p' "$CODEX_HOME/config.toml")
if [ -n "$url" ]; then /usr/bin/curl -s -o /dev/null "$url/responses" >/dev/null 2>&1 || true; fi
out=""
for a in "$@"; do if [ "$prev" = "-o" ]; then out="$a"; fi; prev="$a"; done
if [ -n "$out" ]; then cat "$here/message" > "$out" 2>/dev/null || printf '' > "$out"; fi
echo '{"usage": {"input_tokens": 3}, "request_id": "req-9"}'
exit 0
"""


def _adapter():
    return RT.load_adapter("codex")


def config_and_argv(e):
    A = _adapter()
    prov = {"kind": "official-direct", "key_env": "K", "base_env": "B", "transport": "responses", "display_name": "D"}
    cfg = A.render_config("p", prov, "m", "high", "https://x/v1")
    for line in ('model = "m"', 'model_reasoning_effort = "high"', 'model_provider = "p"', "[model_providers.p]", 'base_url = "https://x/v1"',
                 'env_key = "K"', 'wire_api = "responses"', 'inherit = "none"', "web_search = false"):
        e.check(line in cfg, "config line: %s" % line)
    e.check("request_max_retries" not in cfg and "request_max_retries = 0" in A.render_config("p", prov, "m", "high", "u", retry_zero=True), "retry only in the probe config")
    bcfg = A.render_config("b", {"kind": "builtin-native", "auth_source": "~/x"}, "m", "low", None)
    e.check("[model_providers" not in bcfg and "base_url" not in bcfg and 'model = "m"' in bcfg, "builtin-native config has no provider block")
    argv = A.exec_argv("/bin/codex", "/seal", "/out.md", {"b.c": 1, "a": "x", "flag": True}, "GO")
    e.check(argv[:12] == ["/bin/codex", "exec", "--strict-config", "--skip-git-repo-check", "--ephemeral", "--ignore-rules", "--sandbox", "read-only",
                          "--color", "never", "-C", "/seal"] and "--json" in argv and argv[-1] == "GO"
            and argv[argv.index("-o") + 1] == "/out.md" and 'a="x"' in argv and "b.c=1" in argv and "flag=true" in argv, "exec argv form: %s" % argv)
    for ov in ({"model": "x"}, {"model_providers.p.base_url": "y"}, {"tools.web_search": True}, {"mcp_servers.a.cmd": "c"}, {"sandbox": "full"},
               {"profile": "p"}, {"notify": ["x"]}):
        e.expect_error(lambda o=ov: A.check_overrides(prov, o), code="runtime-key-protected", message="protected %s" % ov)
    A.check_overrides(prov, {"request_max_retries": 0})
    e.expect_error(lambda: A.check_overrides({"kind": "builtin-native"}, {"request_max_retries": 0}), code="runtime-key-protected", message="builtin-native zero override")
    env = A.process_env("/opt/x/bin/codex", e.tmpdir("home"), "/ch", {"K": "v"})
    e.check(env["PATH"].startswith("/opt/x/bin:") and env["CODEX_HOME"] == "/ch" and env["K"] == "v" and "HOME" in env and "TMPDIR" in env
            and not any(k in env for k in ("PYTHONPATH", "SSH_AUTH_SOCK")), "environment constructed from empty")
    ev = A.extract_events('{"usage": {"a": 1}, "request_id": "r1"}\n{"nested": {"response_id": "r2"}}\nnot json\n')
    e.check(ev == {"jsonl_event_count": 2, "usage": {"a": 1}, "request_ids": ["r1", "r2"], "request_count": 2}, "event extraction: %s" % ev)
    e.check(A.extract_events("")["usage"] == "unknown", "unknown when absent")
    e.check(A.classify_recognition("Error loading config: unknown field `x`") == "unrecognized" and A.classify_recognition("connection refused") == "recognized", "recognition classification")
    e.check(A.classify_failure("401 unauthorized", False) == "authentication_failed" and A.classify_failure("", True) == "timeout_or_transport_failure"
            and A.classify_failure("connection refused", False) == "provider_unavailable" and A.classify_failure("unknown field", False) == "runtime_rejected_config",
            "stderr classification")


class _FakeCodex:
    def __init__(self, e):
        self.dir = e.tmpdir("bin")
        p = os.path.join(self.dir, "codex")
        with open(p, "w") as f:
            f.write(FAKE_CODEX)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.dir + os.pathsep + self.old_path

    def control(self, mode):
        with open(os.path.join(self.dir, "control"), "w") as f:
            f.write(mode)

    def message(self, text):
        with open(os.path.join(self.dir, "message"), "w") as f:
            f.write(text)

    def close(self):
        os.environ["PATH"] = self.old_path


def recognition_and_run_offline(e):
    A = _adapter()
    if not os.path.exists("/usr/bin/curl"):
        e.fail("/usr/bin/curl required for the offline recognition probe fixture")
    fc = _FakeCodex(e)
    try:
        prov = {"kind": "official-direct", "key_env": "FAKE_API_KEY", "base_env": "FAKE_API_BASE", "transport": "responses", "display_name": "D"}
        h = S.SecretHandle()
        h.put("FAKE_API_KEY", "sk-fake-1")
        h.put("FAKE_API_BASE", "https://fake.invalid/v1")
        att = e.tmpdir("att")
        seal = os.path.join(att, "inputs")
        os.makedirs(seal)
        ctx = {"mode": "review", "provider_id": "p", "provider": prov, "model_slug": "m", "model": {}, "effort": "high", "overrides": {},
               "secrets": h, "attempt_dir": att, "seal_dir": seal, "instruction": "review", "timeout_seconds": 30, "call_index": 1, "inputs": []}
        fc.control("ok")
        facts = A.preflight(ctx)
        e.check(facts["tool_version"] == "codex-cli 9.9.9" and facts["recognition"] == "checked", "fake codex recognized via loopback request: %s" % facts)
        e.check(not os.path.exists(os.path.join(att, "recognition")), "probe workspace removed")
        fc.control("reject")
        e.expect_error(lambda: A.preflight(ctx), code="runtime-key-unrecognized", message="config load rejection")
        fc.control("ok")
        fc.message("hello")
        r = A.run(ctx)
        e.check(r["final_message"] == b"hello" and r["process"]["exit_code"] == 0 and r["runtime_evidence"]["request_ids"] == ["req-9"]
                and r["tool_version"] == "codex-cli 9.9.9" and r["failure"] is None, "run captured the final message and events: %s" % r["process"])
        call_dir = os.path.join(att, "call-1")
        e.check(not os.path.exists(os.path.join(call_dir, "codex-home", "config.toml")), "temporary config deleted after use")
        e.check(not os.path.exists(call_dir), "R3-B3: the call workspace (raw last_message.md, CODEX_HOME state and caches) is removed after the read")
        e.check(RT.assess_call_path("review", r) == "PROVEN" and RT.assess_profile_binding("official-direct", "unreported", "m", None) == ("SUFFICIENT", "unreported"),
                "three-dimension observation points")
        fc.control("auth")
        r = A.run(dict(ctx, call_index=2))
        e.check(r["failure"] == "authentication_failed" and RT.assess_call_path("review", r) == "NOT_PROVEN", "stderr-classified failure")
        # R4-B5 / R5-B1：不可变（chflags uchg）且含秘密的残留文件 → 解锁、截断、删除，工作区整体消失
        fc.control("residue")
        fc.message("raw-secret-echo")
        keep = os.path.join(att, "call-3", "codex-home", "keep")
        try:
            r = A.run(dict(ctx, call_index=3))
            e.check(r["final_message"] == b"raw-secret-echo" and not os.path.exists(os.path.join(att, "call-3")), "immutable secret-bearing residue fully destroyed")
        finally:
            if os.path.exists(keep):
                os.chflags(keep, 0)
                base.remove_tree(os.path.join(att, "call-3"))
        # R5-B7：不可遍历（chmod 000）子目录内的不可变秘密文件 → 先解锁目录再遍历，整体销毁
        fc.control("residue-dir")
        dark = os.path.join(att, "call-5", "codex-home", "dark")
        try:
            r = A.run(dict(ctx, call_index=5))
            e.check(not os.path.exists(os.path.join(att, "call-5")), "unsearchable subdirectory unlocked and destroyed (R5-B7)")
        finally:
            if os.path.exists(dark):
                os.chmod(dark, 0o700)
                for f in os.listdir(dark):
                    os.chflags(os.path.join(dark, f), 0)
                base.remove_tree(os.path.join(att, "call-5"))
        # 删除本身失败（注入）→ 字节先截断为零，再以内部异常收口
        fc.control("residue")
        real_os = A.os

        class _OsProxy:
            def __getattr__(self, name):
                return getattr(real_os, name)

            def unlink(self, path, *a, **kw):
                if os.path.basename(path) == "keep":
                    raise OSError(1, "injected unlink failure")
                return real_os.unlink(path, *a, **kw)
        A.os = _OsProxy()
        try:
            e.expect_error(lambda: A.run(dict(ctx, call_index=4)), exc_type=RuntimeError, message="residue is an internal error, never silent")
        finally:
            A.os = real_os
        keep4 = os.path.join(att, "call-4", "codex-home", "keep")
        e.check(os.path.exists(keep4) and os.path.getsize(keep4) == 0 and not os.path.exists(os.path.join(att, "call-4", "last_message.md")),
                "unremovable residue is truncated to zero bytes; raw final message gone")
        e.check(not any(b"raw-secret-echo" in open(os.path.join(rt, f), "rb").read() for rt, _d, fs in os.walk(os.path.join(att, "call-4")) for f in fs),
                "no residue file carries the raw output")
        os.chflags(keep4, 0)
        base.remove_tree(os.path.join(att, "call-4"))
    finally:
        fc.close()


def builtin_auth_staging(e):
    A = _adapter()
    fc = _FakeCodex(e)
    try:
        auth = os.path.join(e.tmpdir("auth"), "auth.json")
        with open(auth, "w") as f:
            f.write('{"tokens": {"access_token": "AT-secret-1"}}')
        prov = {"kind": "builtin-native", "auth_source": auth, "transport": "builtin", "display_name": "B"}
        h = S.SecretHandle()
        att = e.tmpdir("att")
        seal = os.path.join(att, "inputs")
        os.makedirs(seal)
        ctx = {"mode": "probe", "provider_id": "b", "provider": prov, "model_slug": "m", "model": {}, "effort": "high", "overrides": {},
               "secrets": h, "attempt_dir": att, "seal_dir": seal, "instruction": "probe", "timeout_seconds": 30, "call_index": 1, "inputs": []}
        fc.control("ok")
        facts = A.preflight(ctx)
        e.check(facts["recognition"] == "not-applicable-builtin-native", "builtin-native: no loopback form")
        fc.message("PROBE-OK")
        r = A.run(ctx)
        e.check(b"AT-secret-1" in h.scan_set(), "auth payload joined the scan set")
        e.check(not os.path.exists(os.path.join(att, "call-1")), "auth copy and the whole call workspace destroyed after the call")
        e.check(open(auth).read().startswith('{"tokens"'), "user auth file never written back")
        e.check(RT.assess_call_path("probe", r) == "PROVEN", "probe payload exact: %r" % r["final_message"])
        with open(auth, "w") as f:
            f.write("{}")
        e.expect_error(lambda: A.run(dict(ctx, call_index=2)), code="auth-source-malformed-at-staging", message="staging re-validation")
    finally:
        fc.close()


def cases():
    return [
        ("adapter.codex.config-argv-overrides", config_and_argv),
        ("adapter.codex.recognition-run-offline", recognition_and_run_offline),
        ("adapter.codex.builtin-auth-staging", builtin_auth_staging),
    ]
