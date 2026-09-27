"""自测假适配器夹具：由引擎复制为 adapters/<name>.py；行为由同目录 fake_control.json 控制。

control 字段：
  behavior   valid | repaired | truncated | garbage | two-blocks | infra-fail | timeout | empty | probe-bad | wrapper |
             wrapper-bad | secret-leak | post-call-crash | diag-secret | adapter-exception（无秘密的适配器意外异常，R35-B1）|
             known-defect（缺 verdict_schema、authorization_disclaimer 为 false；Amendment 2 已知值缺陷）|
             narrative-defect（叙述排版漂移；Amendment 2 叙述缺陷）| both-defect | judgment-defect（缺 question_assessments）
  verdict    PASS | FAIL（默认 PASS）· human 布尔 · version 字符串 · identity 应答侧模型标识（默认无）
  first_origin  FAIL 时 R<N>-B1 的 origin（默认 changed_region；取 unchanged_region 即触发规则 14 的负例，Amendment 4）
  extra_findings  追加 finding 列表 [{severity, origin}]（各类自 B1 / N1 / H1 之后续编；non_blocking 挂在第二题、blocking 挂在首题、human 挂在末题）
  question_ids  覆盖判词题号集合（默认取 ctx.required_question_ids；用于五题闭集缺题 / 多题 / 重复的负例）
  reemit     valid | mismatch | garbage | infra-fail | still-bad | raise（补发调用的行为，默认 valid；校验类补发下 valid = 完整正确判词、
             mismatch = 改动判断字段、still-bad = 块正确但叙述仍漂移；raise = 补发调用中适配器抛出异常，R35-B1）
  truncated-known-defect  behavior：块截断（信封类补发）且块缺 verdict_schema；配 reemit = keep-known-defect 时补发块仍缺 →
             信封类补发后校验仍失败（verdict-invalid）、不得再补发（M105 变异的捕获用例）
  usage  应答 usage 对象（默认 unknown）· reemit_version  补发调用的版本（默认同 version）· crash_after  calling | called（在该态记录写出后模拟进程终止）
"""
import json
import os
import signal

import review_channel_runtime as RT

RUNTIME_ID = "fake"
SUPPORTED_KINDS = ("official-direct", "aggregator", "builtin-native")
SUPPORTED_TRANSPORTS = ("responses", "chat", "messages", "builtin")
INLINE_DELIVERY = False
CONTROL = os.path.join(os.path.dirname(os.path.realpath(__file__)), "fake_control.json")


def _control():
    try:
        with open(CONTROL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def preflight(ctx):
    c = _control()
    if c.get("preflight_reject"):
        import review_channel_base as base
        raise base.PreflightError(c["preflight_reject"], "fake adapter preflight rejection")
    if c.get("preflight_raise_secret"):
        raise RuntimeError("preflight exploded with sk-fake-secret-value-123")
    return {"tool_version": c.get("version", "fake 1.0"), "recognition": "checked"}


def build_block(ctx, verdict="PASS", human=False, control=None):
    c = control or {}
    cand = [i for i in ctx["inputs"] if i["role"] == "candidate"][0]
    qids = c.get("question_ids") if c.get("question_ids") is not None else ctx["required_question_ids"]
    qa = [{"question_id": q, "assessment": "SATISFIED", "evidence_refs": [], "finding_ids": []} for q in qids]
    findings = []
    rt = ctx["round"].upper()
    letter = {"blocking": "B", "non_blocking": "N", "human": "H"}
    slot = {"blocking": 0, "non_blocking": 1 if len(qa) > 1 else 0, "human": len(qa) - 1}
    counts = {"B": 0, "N": 0, "H": 0}

    def add(severity, origin, title, anchor):
        counts[letter[severity]] += 1
        fid = "%s-%s%d" % (rt, letter[severity], counts[letter[severity]])
        findings.append({"id": fid, "severity": severity, "title": title,
                         "location": {"file": cand["bundle_name"], "anchor": anchor}, "origin": origin, "summary": "x"})
        q = qa[slot[severity]]
        q["finding_ids"].append(fid)
        if severity == "blocking":
            q["assessment"] = "NOT_SATISFIED"
        elif severity == "human":
            q["assessment"] = "INDETERMINATE"
    if verdict == "FAIL":
        add("blocking", c.get("first_origin", "changed_region"), "problem one", "line 1")
    if human:
        add("human", "unchanged_region", "needs a ruling", "line 2")
    for i, spec in enumerate(c.get("extra_findings") or []):
        add(spec["severity"], spec.get("origin", "changed_region"), "extra %d" % (i + 1), "line %d" % (i + 3))
    human = any(f["severity"] == "human" for f in findings)
    prev = [] if ctx["previous_finding_ids"] is None else [
        {"id": p, "disposition": "RESOLVED", "evidence_refs": []} for p in ctx["previous_finding_ids"]]
    cands = [i for i in ctx["inputs"] if i["role"] == "candidate"]
    block = {"verdict_schema": "review-channel-verdict/v4", "verdict": verdict, "human_decision_required": human,
             "subject": ctx["subject"], "stage": ctx["stage"], "round": ctx["round"],
             "candidate": {"bundle_name": cand["bundle_name"], "sha256": cand["sha256"]},
             "candidates": [{"bundle_name": c["bundle_name"], "sha256": c["sha256"]} for c in cands],
             "question_assessments": qa, "findings": findings, "previous_findings_disposition": prev,
             "accepted_residuals_acknowledged": list(ctx["residual_ids"]),
             "scope_files_read": [ctx["task_file"]] + [c["bundle_name"] for c in cands],
             "tools_used": [] if INLINE_DELIVERY else ["read"],
             "authorization_disclaimer": True}
    narr = ["**Verdict: %s**" % verdict, "**Human decision required: %s**" % ("yes" if human else "no"), ""]
    for f in findings:
        narr += ["### %s · %s · %s" % (f["id"], f["severity"], f["title"]), "details", ""]
    narr += ["## Question assessments"] + ["- %s: %s" % (q["question_id"], q["assessment"]) for q in qa]
    if ctx["previous_finding_ids"] is not None:
        narr += ["", "## Previous findings"] + ["- %s: RESOLVED" % p for p in ctx["previous_finding_ids"]]
    return block, "\n".join(narr) + "\n"


def _crash_if(ctx, when):
    c = _control()
    if c.get("crash_after") == when and ctx["call_index"] == c.get("crash_call_index", 1):
        os.kill(os.getpid(), signal.SIGKILL)


def run(ctx):
    r = RT.empty_result()
    c = _control()
    behavior = c.get("behavior", "valid")
    r["tool_version"] = c.get("version", "fake 1.0") if ctx["call_index"] == 1 else c.get("reemit_version", c.get("version", "fake 1.0"))
    if c.get("usage") is not None:
        r["runtime_evidence"]["usage"] = c["usage"]   # 提供方应答的 usage 对象（动态成员名来源，R19-B1 自测用）
    if c.get("identity"):
        r["identity_claim"] = c["identity"]
    r["process"] = {"exit_code": 0, "timed_out": False, "stderr_summary": ""}
    r["raw"] = {"events": b'{"usage": {"input_tokens": 1}, "request_id": "req-1"}\n', "stderr": b""}
    _crash_if(ctx, "calling")
    if c.get("diag_secret"):
        r["raw"]["events"] += b'{"debug": "key sk-fake-secret-value-123"}\n'
    if behavior == "diag-secret":
        r["raw"] = {"events": b'{"usage": {"input_tokens": 1}, "request_id": "req-1", "debug": "key sk-fake-secret-value-123"}\n', "stderr": b""}
        behavior = "valid"
    if behavior == "raise-secret":
        raise RuntimeError("adapter blew up with sk-fake-secret-value-123 in the message")
    if behavior == "adapter-exception":
        raise RuntimeError("adapter blew up after the call")   # 无秘密的适配器意外异常（调用后内部异常收口的自测）
    if behavior == "post-call-crash":
        r["raw"] = {"events": 12345, "stderr": b""}   # 非字节事件流：契约层落盘诊断时抛出（调用后内部异常）
    if ctx["mode"] == "probe":
        r["final_message"] = b"PROBE-OK\n" if behavior != "probe-bad" else b"nope"
        return r
    block, narr = build_block(ctx, c.get("verdict", "PASS"), c.get("human", False), c)
    jb = json.dumps(block, ensure_ascii=False, indent=1)
    bad_block = dict(block, authorization_disclaimer=False)
    del bad_block["verdict_schema"]
    bad_jb = json.dumps(bad_block, ensure_ascii=False, indent=1)
    bad_narr = (narr.replace("**Human decision required", "\n**Human decision required")
                    .replace("## Question assessments", "## Question Assessments")
                    .replace(" · blocking · ", " - blocking - ").replace(" · human · ", " - human - "))
    if ctx["call_index"] == 2:
        rb = c.get("reemit", "valid")
        if rb == "raise":
            raise RuntimeError("adapter blew up during the re-emission call")
        validation = "叙述骨架如下" in (ctx.get("instruction") or "")
        if rb == "mismatch":
            block2 = dict(block, verdict="PASS" if block["verdict"] == "FAIL" else "FAIL")
            body = json.dumps(block2, indent=1)
            r["final_message"] = ("```review-channel-verdict\n%s\n```\n%s" % (body, ("\n" + narr) if validation else "")).encode()
        elif rb == "garbage":
            r["final_message"] = b"still garbage"
        elif rb == "infra-fail":
            r["failure"] = "provider_unavailable"
            r["process"]["exit_code"] = 1
        elif rb == "still-bad":
            r["final_message"] = ("```review-channel-verdict\n%s\n```\n\n%s" % (jb, bad_narr)).encode()
        elif rb == "keep-known-defect":
            r["final_message"] = ("```review-channel-verdict\n%s\n```\n%s" % (bad_jb, ("\n" + narr) if validation else "")).encode()
        else:
            r["final_message"] = ("```review-channel-verdict\n%s\n```\n%s" % (jb, ("\n" + narr) if validation else "")).encode()
        return r
    if behavior == "valid":
        msg = "```review-channel-verdict\n%s\n```\n\n%s" % (jb, narr)
    elif behavior in ("known-defect", "both-defect"):
        msg = "```review-channel-verdict\n%s\n```\n\n%s" % (bad_jb, bad_narr if behavior == "both-defect" else narr)
    elif behavior == "truncated-known-defect":
        msg = "```review-channel-verdict\n%s\n```\n\n%s" % (bad_jb[:-40], narr)
    elif behavior == "narrative-defect":
        msg = "```review-channel-verdict\n%s\n```\n\n%s" % (jb, bad_narr)
    elif behavior == "judgment-defect":
        bad = dict(block)
        del bad["question_assessments"]
        msg = "```review-channel-verdict\n%s\n```\n\n%s" % (json.dumps(bad, ensure_ascii=False, indent=1), narr)
    elif behavior == "repaired":
        msg = "%s\n```review-channel-verdict\n%s\nthanks\n" % (narr, jb)
    elif behavior == "truncated":
        msg = "```review-channel-verdict\n%s\n```\n\n%s" % (jb[:-40], narr)
    elif behavior == "two-blocks":
        msg = "```review-channel-verdict\n%s\n```\n```review-channel-verdict\n%s\n```\n%s" % (jb, jb, narr)
    elif behavior == "wrapper":
        msg = json.dumps({"machine": block, "narrative": narr}, ensure_ascii=False)
    elif behavior == "wrapper-bad":
        msg = json.dumps({"narrative": narr})
    elif behavior == "secret-leak":
        msg = "```review-channel-verdict\n%s\n```\n\n%s\nkey was sk-fake-secret-value-123\n" % (jb, narr)
    elif behavior == "infra-fail":
        r["failure"] = c.get("failure", "provider_unavailable")
        r["process"]["exit_code"] = 1
        r["raw"]["stderr"] = b"connection refused"
        return r
    elif behavior == "timeout":
        r["failure"] = "timeout_or_transport_failure"
        r["process"] = {"exit_code": None, "timed_out": True, "stderr_summary": ""}
        return r
    elif behavior == "empty":
        msg = ""
    else:
        msg = "garbage"
    r["final_message"] = msg.encode()
    return r
