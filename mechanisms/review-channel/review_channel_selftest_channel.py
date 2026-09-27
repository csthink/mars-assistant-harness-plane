"""自测声明：review_channel（入口端到端；第 8 / 14 / 15 / 16 / 19 类的子进程实撞：假适配器注入下契约层全程）。"""
import json
import os
import signal
import subprocess
import sys
import time

import review_channel_base as base
import review_channel_contract as C
import review_channel_receipt as RC
import review_channel_verdict as V


class Env:
    def __init__(self, e, control=None, names=("fake", "fakeinline")):
        self.e = e
        self.repo = e.iso_repo()
        self.adapters = e.install_unit(self.repo, e.fake_adapters(control or {"behavior": "valid"}, names=names))
        self.registry = self.repo.path("mechanisms/review-channel/review_channel_registry.json")

    def run(self, sub, req, *more):
        return self.e.channel(self.repo, sub, req, *more)

    def control(self, **kw):
        self.e.set_control(self.adapters, **kw)

    def receipts(self, rnd, task=True):
        d = self.repo.path(self.repo.attempts_dir(rnd, task))
        out = []
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            p = os.path.join(d, name, "receipt.json")
            if os.path.isfile(p):
                out.append((name, json.loads(base.read_bytes(p))))
        return out

    def tracked(self, rnd, task=True):
        d = self.repo.path(self.repo.tracked_dir(rnd, task))
        return sorted(os.listdir(d)) if os.path.isdir(d) else None

    def respond(self, rnd, decisions, task=True, **extra):
        """`respond`（§6.12）：写决定文件；返回 (exit, stdout_json, stderr)。"""
        code, out, err, j = self.run("respond", self.repo.decisions_input(rnd, decisions, task=task, **extra))
        return code, j, err

    def next_round_brief(self, rnd, decisions, task=True, narrative="fixed", extra_residuals=()):
        """对 r<N> 判词 respond 后，按其 stdout 派生 r<N+1> 请求件的 remediation / residuals 两个夹具参数（§6.12 其三、其四）。"""
        code, j, err = self.respond(rnd, decisions, task=task)
        self.e.check(code == 0 and j["state"] == "WRITTEN", "respond for %s: %s" % (rnd, err[-300:]))
        nr = j["next_round"]
        residuals = list(nr["accepted_residuals"])
        residuals.extend({"id": "RES-%d" % (len(residuals) + 1 + i), "text": t} for i, t in enumerate(extra_residuals))
        return {"remediation": nr["remediation_statement"] + "\n\n" + narrative, "residuals": residuals}

    def approve_all(self, rnd, task=True):
        """对 r<N> 已发布判词的每条 finding 取 approve（无 finding 时决定列表为空）。"""
        obj, _jb, _n = V.parse_published(base.read_bytes(self.repo.path(self.repo.tracked_dir(rnd, task) + "/HarnessPlane_Demo_Review_R%s.md" % rnd[1:])))
        return [{"finding_id": f["id"], "action": "approve", "owner_verbatim": "ok"} for f in obj["findings"]]


def _four(names):
    return names is not None and len(names) == 4 and any(n.startswith("receipt-r") for n in names)


def probe_and_preflight(e):
    env = Env(e)
    code, out, err, j = env.run("preflight", env.repo.request("r1"))
    e.check(code == 0 and j["state"] == "PASS" and j["delivery"] == "tool" and j["profile"]["provider"] == "fake-official", "standalone preflight PASS: %s" % err[-300:])
    e.check(not os.path.isdir(env.repo.path(env.repo.attempts_dir("r1"))), "standalone preflight allocates no attempt")
    code, out, err, j = env.run("probe", env.repo.request("r1"))
    e.check(code == 0 and j["classification"] == "probe_completed" and j["call_path_proof"] == "PROVEN", "probe completed: %s" % err[-300:])
    recs = env.receipts("r1")
    e.check(len(recs) == 1 and recs[0][1]["receipt_phase"] == "completed" and recs[0][1]["attempt_outcome"] == "receipt_only"
            and recs[0][1]["verdict_published"] is False and recs[0][1]["capability_suggestion"] == "PROBED", "probe receipt")
    env.control(behavior="probe-bad")
    code, out, err, j = env.run("probe", env.repo.request("r1"))
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid" and j["call_path_proof"] == "INDETERMINATE", "probe payload mismatch")
    bad = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(bad["receipt_phase"] == "called" and bad["extraction"]["tier"] == "invalid" and bad["failure_code"] == "probe-payload-mismatch"
            and bad["failure_call_index"] == 1 and j["failure_code"] == "probe-payload-mismatch", "probe failure receipt satisfies the called-phase schema; closed-set code (R2-B5 / R3-B5)")
    # 死 .alloc 名内令牌为 unknown 时恒不可判、不清理（R2-B9）
    ard = env.repo.path(env.repo.attempts_dir("r1"))
    unknown = os.path.join(ard, ".alloc-Z-999999-unknown")
    os.makedirs(unknown)
    env.run("preflight", env.repo.request("r1"))
    e.check(os.path.isdir(unknown), "unknown-token alloc never cleaned")
    os.rmdir(unknown)
    e.check(env.tracked("r1") is None, "probe never touches the tracked dir")
    # R3-B2：应答侧标识含秘密 → Receipt 终检降级；对外报告、退出码与 called 阶段 schema 一致
    env.control(behavior="valid", version="fake sk-fake-secret-value-123")   # 秘密进入 runtime_version / 运行时组，三维仍 PROVEN + SUFFICIENT
    code, out, err, j = env.run("probe", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid" and j["failure_code"] == "secret-leak"
            and rec["classification"] == "reviewer_output_invalid" and rec["failure_code"] == "secret-leak" and rec["receipt_phase"] == "called"
            and rec["extraction"]["tier"] == "invalid" and rec["failure_call_index"] == 1 and rec["diagnostics"]["secret_leak_in_evidence"] is True
            and rec["capability_suggestion"] != "REVIEW_ENABLED" and b"sk-fake-secret-value-123" not in base.pretty_json(rec),
            "probe downgraded by the receipt secret check reports and exits as a failure (R3-B2): %s / %s" % (j, rec["failure_code"]))
    # R4-B2：载荷正确但绑定不足 → 不是 probe_completed
    env.control(behavior="valid", identity="some-other-model")
    code, out, err, j = env.run("probe", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid" and j["failure_code"] == "profile-binding" and rec["receipt_phase"] == "called"
            and rec["call_path_proof"] == "PROVEN" and rec["profile_binding"] == "MISMATCH" and rec["extraction"]["tier"] == "invalid"
            and rec["capability_suggestion"] not in ("PROBED", "REVIEW_ENABLED"), "probe success requires PROVEN + SUFFICIENT (R4-B2): %s" % j)
    env.control(behavior="valid")
    # R3-B10：取锁的非竞争异常（锁路径是目录）→ preflight_failed + internal-error Receipt，不是无 Receipt 退出 2
    lock = os.path.join(ard, ".in-progress")
    os.unlink(lock)
    os.makedirs(lock)
    code, out, err, j = env.run("probe", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and j["classification"] == "preflight_failed" and j["failure_code"] == "internal-error"
            and rec["receipt_phase"] == "routed" and rec["failure_code"] == "internal-error", "lock acquisition exception still yields a Receipt (R3-B10): %s" % err[-200:])
    os.rmdir(lock)
    # R3-B1：候选本身是符号链接 → 引用解析之前即拒绝，报告不含任何引用解析结果
    outside = os.path.join(e.tmpdir("outside"), "cand.md")
    open(outside, "w").write("# outside\n\nSee `mechanisms/ghost.md`.\n")
    os.symlink(outside, env.repo.path("mechanisms/demo/linked.md"))
    code, out, err, j = env.run("review", env.repo.request("r1", inputs={"candidates": ["mechanisms/demo/linked.md"], "references": []}))
    e.check(code == 1 and j["failure_code"] == "candidate-unreadable" and "ghost" not in err, "symlinked candidate refused before any reference resolution (R3-B1)")
    os.unlink(env.repo.path("mechanisms/demo/linked.md"))


def review_paths(e):
    env = Env(e, {"behavior": "valid", "verdict": "FAIL"})
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 0 and j["classification"] == "completed_with_valid_verdict" and j["verdict"] == "FAIL" and j["extraction_tier"] == "strict",
            "r1 strict: %s" % err[-400:])
    e.check(_four(env.tracked("r1")), "four members published: %s" % env.tracked("r1"))
    tracked = env.repo.path(env.repo.tracked_dir("r1"))
    receipt = json.loads(base.read_bytes(os.path.join(tracked, "receipt-r1.json")))
    e.check(receipt["receipt_phase"] == "completed" and receipt["verdict_published"] is True and receipt["attempt_outcome"] == "governed_verdict"
            and receipt["effective_profile"]["verdict_sha256"] == base.sha256_bytes(base.read_bytes(os.path.join(tracked, "HarnessPlane_Demo_Review_R1.md")))
            and "bundle_manifest" not in receipt and receipt["input_manifest_sha256"] == json.loads(base.read_bytes(os.path.join(tracked, "bundle_manifest.json")))["manifest_sha256"],
            "receipt facts; manifest not embedded")
    attempt_dir = os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"])
    e.check(os.stat(os.path.join(attempt_dir, "receipt.json")).st_ino == os.stat(os.path.join(tracked, "receipt-r1.json")).st_ino, "backlink same inode")
    e.check(not any(n.startswith("publish.tmp-") for n in os.listdir(attempt_dir)), "staging gone after rename")
    e.check(env.repo.git("status", "--short").stdout.strip() != "" and "attempts" not in env.repo.git("status", "--short", "--ignored").stdout.split("!!")[0], "attempts ignored")
    # r2：二级修复 + 继承（须先跟踪 r1；r2+ 请求件由上一轮决定文件派生，§6.12）
    env.repo.commit("r1 evidence")
    env.control(behavior="repaired", verdict="PASS")
    brief = env.next_round_brief("r1", [{"finding_id": "R1-B1", "action": "fix", "instructions": "rewrite it", "owner_verbatim": "改掉"}])
    code, out, err, j = env.run("review", env.repo.request("r2", previous=env.repo.previous_round("r1"), **brief))
    e.check(code == 0 and j["extraction_tier"] == "repaired" and _four(env.tracked("r2")), "r2 repaired: %s" % err[-400:])
    r2 = json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r2") + "/receipt-r2.json")))
    e.check(r2["effective_profile"]["selection_source"] == "inherited-snapshot" and r2["extraction"]["repairs"] == ["block-relocated", ] or
            set(r2["extraction"]["repairs"]) >= {"missing-closing-fence", "trailing-content", "block-relocated"}, "repairs recorded: %s" % r2["extraction"])
    e.check(r2["runtime"]["changed_across_rounds"] is False and r2["round_budget"]["submitted_rounds"] == 1, "runtime unchanged; budget counts r1")
    e.check(base.hex64(r2["decisions_sha256"]) and "standard_questions_effective" not in r2 and r2["options"] == {"reemit_enabled": True},
            "r2 receipt records the decisions file identity; retired members absent: %s" % r2.get("decisions_sha256"))
    names = [i["bundle_name"] for i in json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r2") + "/bundle_manifest.json")))["inputs"]]
    e.check({"previous--candidate-baseline--HarnessPlane_Demo_Design_v1.md", "previous--verdict.md", "previous--bundle_manifest.json", "previous--receipt.json"} <= set(names), "previous-- four members in r2")
    task = base.read_bytes(env.repo.path(env.repo.tracked_dir("r2") + "/HarnessPlane_Demo_Review_Task_R2.md")).decode()
    e.check("R1-B1" in task and "整改声明" in task and "Dispositions (decisions.json sha256 %s)" % r2["decisions_sha256"][:12] in task
            and "- `R1-B1` · blocking · problem one → fix · rewrite it" in task, "r2 task book lists previous findings, the dispositions segment and the decision summary")
    # r3：显式改选 + 版本变化 + 无提示（Registry 缺省额度 2 已由 r1 / r2 用尽：请求件级 max_rounds 覆盖，§6.10）
    env.repo.commit("r2 evidence")
    env.control(behavior="valid", verdict="PASS", version="fake 2.0")
    code, out, err, j = env.run("review", env.repo.request("r3", previous=env.repo.previous_round("r2"), max_rounds=5,
                                                            **env.next_round_brief("r2", env.approve_all("r2")),
                                                            profile={"provider": "fake-official", "model": "fake-openai"}))
    e.check(code == 0, "r3 explicit change: %s" % err[-300:])
    r3 = json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r3") + "/receipt-r3.json")))
    e.check(r3["effective_profile"]["selection_source"] == "explicit-request" and r3["runtime"]["changed_across_rounds"] is True
            and r3["runtime"]["tool_version"] == "fake 2.0", "explicit change and version fact")
    e.check("version" not in err.lower() or "changed" not in err.lower(), "no version reminder on stderr")
    # budget: max_rounds 2 → r4 exhausted; extension lifts
    env.repo.commit("r3 evidence")
    brief4 = env.next_round_brief("r3", env.approve_all("r3"))
    code, out, err, j = env.run("review", env.repo.request("r4", previous=env.repo.previous_round("r3"), max_rounds=2, **brief4))
    e.check(code == 1 and j["failure_code"] == "round_budget_exhausted" and "blocking" in err, "budget exhausted with human hint: %s" % err[-300:])
    code, out, err, j = env.run("review", env.repo.request("r4", previous=env.repo.previous_round("r3"), max_rounds=2, **brief4,
                                                            round_extensions=[{"authorized_by": "owner", "at": "2026-09-02", "added_rounds": 2, "note": "go"}]))
    e.check(code == 0 and _four(env.tracked("r4")), "extension lifts the budget: %s" % err[-300:])


def reemission(e):
    env = Env(e, {"behavior": "truncated", "verdict": "FAIL"})
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 0 and j["extraction_tier"] == "reemitted", "truncated → reemitted VALID: %s" % err[-300:])
    r = json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/receipt-r1.json")))
    e.check(r["extraction"]["invariance_check"] == {"status": "passed", "mismatched_fields": []} and len(r["effective_profile"]["calls"]) == 2
            and r["extraction"]["reemit_raw_message_sha256"] is not None and r["round_budget"]["submitted_rounds"] == 0, "receipt: two calls, one attempt, no budget consumed")
    attempt_dir = os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"])
    e.check(os.path.isfile(os.path.join(attempt_dir, "reemit-reviewer_last_message.md")), "reemit- diagnostics")
    e.check(len(env.receipts("r1")) == 1, "one receipt per attempt")
    env2 = Env(e, {"behavior": "truncated", "verdict": "FAIL", "reemit": "mismatch"})
    code, out, err, j = env2.run("review", env2.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "reemit-invariance-mismatch" and any("reemit-invariance-mismatch:verdict" in p for p in j["verdict_problems"]),
            "invariance mismatch → INVALID with per-field codes: %s" % j)
    e.check(env2.tracked("r1") is None, "tracked dir untouched on failure")
    env3 = Env(e, {"behavior": "truncated", "reemit": "garbage"})
    code, out, err, j = env3.run("review", env3.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "reemit-unparseable", "reemit unparseable")
    env4 = Env(e, {"behavior": "truncated", "reemit": "infra-fail"})
    code, out, err, j = env4.run("review", env4.repo.request("r1"))
    rec = env4.receipts("r1")[0][1]
    e.check(code == 1 and j["classification"] == "provider_unavailable" and rec["failure_code"] == "provider_unavailable"
            and rec["failure_call_index"] == 2 and rec["extraction"]["invariance_check"]["status"] == "not_reached",
            "reemit infra failure classified by the last call; call index is a separate fact (R1-B5): %s" % rec["failure_code"])
    env5 = Env(e, {"behavior": "truncated"})
    code, out, err, j = env5.run("review", env5.repo.request("r1"), "--no-reemit")
    rec = env5.receipts("r1")[0][1]
    e.check(code == 1 and rec["options"]["reemit_enabled"] is False and rec["extraction"]["tier"] == "invalid", "--no-reemit recorded")
    att5 = json.loads(base.read_bytes(os.path.join(env5.repo.path(env5.repo.attempts_dir("r1")), j["attempt_id"], "attempt.json")))
    e.check(att5["phase"] == "validated" and att5["verdict_validation"] == "INVALID" and att5["extraction"]["tier"] == "invalid",
            "INVALID decided before the Receipt is recorded in the validated state (R16-B1): %s" % att5["phase"])
    env6 = Env(e, {"behavior": "truncated", "version": "v1", "reemit_version": "v2"})
    code, out, err, j = env6.run("review", env6.repo.request("r1"))
    r = json.loads(base.read_bytes(env6.repo.path(env6.repo.tracked_dir("r1") + "/receipt-r1.json")))
    e.check(code == 0 and r["runtime"]["tool_version"] == "v1" and r["runtime"]["changed_within_attempt"] is True
            and [c["runtime_version"] for c in r["effective_profile"]["calls"]] == ["v1", "v2"], "version change within attempt: fact only")


def _tracked_receipt(env, rnd):
    return json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir(rnd) + "/receipt-%s.json" % rnd)))


def validation_reemit(e):
    """S4 校验类补发（Amendment 2）：已知值缺陷 / 叙述缺陷 / 两者并存各一正例；判断字段改动负例；判断字段缺陷不补发；补发后仍失败；
    --no-reemit；信封类补发后不再第二次补发。"""
    for behavior, hint in (("known-defect", "verdict_schema"), ("narrative-defect", "narrative"), ("both-defect", "verdict_schema")):
        env = Env(e, {"behavior": behavior, "verdict": "FAIL"})
        code, out, err, j = env.run("review", env.repo.request("r1"))
        e.check(code == 0 and j["extraction_tier"] == "reemitted" and j["reemit_trigger"] == "validation", "%s → validation re-emission VALID: %s" % (behavior, err[-400:]))
        r = _tracked_receipt(env, "r1")
        ex = r["extraction"]
        e.check(ex["reemit_trigger"] == "validation" and ex["reemit_reasons"] and any(hint in x for x in ex["reemit_reasons"])
                and ex["reemit_unverifiable_fields"] == [] and ex["invariance_check"] == {"status": "passed", "mismatched_fields": []}
                and ex["reemit_raw_message_sha256"] is not None and len(r["effective_profile"]["calls"]) == 2 and r["round_budget"]["submitted_rounds"] == 0,
                "%s receipt: trigger, reasons, no unverifiable fields, two calls, no budget consumed: %s" % (behavior, ex))
        obj, _jb, narr = V.parse_published(base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/HarnessPlane_Demo_Review_R1.md")))
        e.check(obj["verdict_schema"] == C.VERDICT_SCHEMA and obj["authorization_disclaimer"] is True and "## Question assessments" in narr,
                "%s published verdict is the re-emitted, contract-satisfying document" % behavior)
        e.check(os.path.isfile(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "reemit-reviewer_last_message.md")), "reemit- diagnostics")
    env2 = Env(e, {"behavior": "known-defect", "verdict": "FAIL", "reemit": "mismatch"})
    code, out, err, j = env2.run("review", env2.repo.request("r1"))
    rec = env2.receipts("r1")[0][1]
    e.check(code == 1 and j["failure_code"] == "reemit-invariance-mismatch" and any("reemit-invariance-mismatch:verdict" in p for p in j["verdict_problems"])
            and rec["extraction"]["reemit_trigger"] == "validation" and rec["extraction"]["invariance_check"] == {"status": "mismatch", "mismatched_fields": ["verdict"]}
            and env2.tracked("r1") is None, "judgment field changed in the re-emission → INVALID, field named: %s" % j)
    env3 = Env(e, {"behavior": "judgment-defect"})
    code, out, err, j = env3.run("review", env3.repo.request("r1"))
    rec = env3.receipts("r1")[0][1]
    e.check(code == 1 and j["failure_code"] == "verdict-invalid" and rec["extraction"]["reemit_trigger"] is None and rec["extraction"]["tier"] == "strict"
            and len(rec["effective_profile"]["calls"]) == 1, "judgment-field defect: no re-emission, one call: %s" % rec["extraction"])
    env4 = Env(e, {"behavior": "narrative-defect", "reemit": "still-bad"})
    code, out, err, j = env4.run("review", env4.repo.request("r1"))
    rec = env4.receipts("r1")[0][1]
    e.check(code == 1 and j["failure_code"] == "verdict-invalid" and rec["extraction"]["reemit_trigger"] == "validation"
            and len(rec["effective_profile"]["calls"]) == 2, "still failing after the re-emission → verdict-invalid with the trigger recorded, no third call: %s" % rec["extraction"])
    env5 = Env(e, {"behavior": "known-defect"})
    code, out, err, j = env5.run("review", env5.repo.request("r1"), "--no-reemit")
    rec = env5.receipts("r1")[0][1]
    e.check(code == 1 and j["failure_code"] == "reemit-disabled" and rec["options"]["reemit_enabled"] is False and len(rec["effective_profile"]["calls"]) == 1,
            "--no-reemit disables the validation class too")
    env6 = Env(e, {"behavior": "truncated-known-defect", "reemit": "keep-known-defect"})
    code, out, err, j = env6.run("review", env6.repo.request("r1"))
    rec = env6.receipts("r1")[0][1]
    e.check(code == 1 and j["failure_code"] == "verdict-invalid" and rec["extraction"]["reemit_trigger"] == "envelope"
            and rec["extraction"]["invariance_check"]["status"] == "passed" and len(rec["effective_profile"]["calls"]) == 2,
            "envelope re-emission then a known-value defect: at most one re-emission, no validation-class second call: %s" % rec["extraction"])


def multi_candidate(e):
    """S20 多候选（Amendment 2；subject 轴）：两候选一轮一份判词；候选互引记候选之一；r2 逐候选基线；候选集合变化 → inherit-unanchored；任务轴两候选 → 请求文法失败（R33-B1）。"""
    env = Env(e, {"behavior": "valid", "verdict": "FAIL"})
    design = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    second = "mechanisms/demo/second.md"
    env.repo.write(second, "# Second\n\nCites `%s`.\n" % design)
    env.repo.commit("second candidate")
    refs = ["AGENTS.md", "mechanisms/gates/rules_catalog.json", "records/fixture-reference.md"]
    code, out, err, j = env.run("preflight", env.repo.request("r1", inputs={"candidates": [design, second], "references": refs}))
    e.check(code == 1 and j["failure_code"] == "request-schema", "task axis with two candidates is refused (task-artifact-schema §10.2): %s" % j.get("failure_code"))
    code, out, err, j = env.run("review", env.repo.request("r1", task=False, inputs={"candidates": [design, second], "references": refs}))
    e.check(code == 0 and _four(env.tracked("r1", task=False)), "two candidates, one verdict: %s" % err[-400:])
    man = json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r1", task=False) + "/bundle_manifest.json")))
    e.check([i["source"] for i in man["inputs"] if i["role"] == "candidate"] == [design, second], "manifest candidate order = request order")
    obj, _jb, _n = V.parse_published(base.read_bytes(env.repo.path(env.repo.tracked_dir("r1", task=False) + "/HarnessPlane_Demo_Review_R1.md")))
    e.check(len(obj["candidates"]) == 2 and obj["candidate"] == obj["candidates"][0] and obj["candidates"][0]["bundle_name"] == "HarnessPlane_Demo_Design_v1.md",
            "verdict names both candidates, candidate = first: %s" % obj["candidates"])
    task = base.read_bytes(env.repo.path(env.repo.tracked_dir("r1", task=False) + "/HarnessPlane_Demo_Review_Task_R1.md")).decode()
    e.check("被审对象 1（首候选）" in task and "被审对象 2" in task and "候选之一" in task, "task book lists both candidates and the co-candidate reference")
    env.repo.commit("r1 evidence")
    brief2 = env.next_round_brief("r1", [{"finding_id": "R1-B1", "action": "approve", "owner_verbatim": "按 summary 改"}], task=False)
    code, out, err, j = env.run("review", env.repo.request("r2", task=False, previous=env.repo.previous_round("r1", task=False), inputs={"candidates": [design, second], "references": refs}, **brief2))
    e.check(code == 0, "r2 with the same candidate set: %s" % err[-400:])
    e.check(os.path.isfile(env.repo.path("review-attempts/demo/r1/decisions.json")), "subject-axis decisions file sits in review-attempts/<subject>/r1/")
    names = [i["bundle_name"] for i in json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r2", task=False) + "/bundle_manifest.json")))["inputs"]]
    e.check({"previous--candidate-baseline--HarnessPlane_Demo_Design_v1.md", "previous--candidate-baseline--second.md", "previous--verdict.md"} <= set(names),
            "one baseline per candidate: %s" % names)
    task2 = base.read_bytes(env.repo.path(env.repo.tracked_dir("r2", task=False) + "/HarnessPlane_Demo_Review_Task_R2.md")).decode()
    e.check("#### 候选 `second.md`" in task2 and "#### 候选 `HarnessPlane_Demo_Design_v1.md`" in task2, "diff section per candidate")
    env.repo.commit("r2 evidence")
    brief3 = env.next_round_brief("r2", env.approve_all("r2", task=False), task=False)
    code, out, err, j = env.run("review", env.repo.request("r3", task=False, previous=env.repo.previous_round("r2", task=False), inputs={"candidates": [design], "references": refs}, max_rounds=5, **brief3))
    e.check(code == 1 and j["failure_code"] == "inherit-unanchored", "candidate set shrank → inherit-unanchored: %s" % j)


def failures_and_classification(e):
    env = Env(e, {"behavior": "infra-fail", "failure": "authentication_failed", "diag_secret": True})
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = env.receipts("r1")[0][1]
    e.check(code == 1 and rec["classification"] == "authentication_failed" and rec["verdict_validation"] == "INVALID"
            and rec["diagnostics"]["secret_leak_redacted"] is True, "infrastructure failure with a diagnostic secret hit is INVALID (R6-B5): %s" % rec["verdict_validation"])
    env.control(behavior="infra-fail", failure="authentication_failed")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and rec["classification"] == "authentication_failed" and rec["call_path_proof"] == "NOT_PROVEN"
            and rec["receipt_phase"] == "called" and rec["verdict_validation"] == "NOT_REACHED"
            and rec["extraction"] == {"tier": "invalid", "repairs": [], "reemit_trigger": None, "reemit_reasons": [], "reemit_raw_message_sha256": None, "reemit_unverifiable_fields": [], "invariance_check": None}
            and rec["failure_call_index"] == 1, "infrastructure failure receipt carries extraction and call index (R1-B5)")
    env.control(behavior="empty")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(rec["classification"] == "reviewer_output_invalid" and rec["call_path_proof"] == "INDETERMINATE", "empty output indeterminate")
    env.control(behavior="two-blocks", verdict="PASS")
    code, out, err, j = env.run("review", env.repo.request("r1"), "--no-reemit")
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid", "two blocks invalid")
    # R5-B4：秘密只出现在诊断层（事件流）→ 仍 INVALID、不发布
    env.control(behavior="diag-secret", verdict="PASS")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and j["failure_code"] == "verdict-invalid" and rec["diagnostics"]["secret_leak_redacted"] is True and env.tracked("r1") is None
            and any("secret material" in x for x in rec["verdict_problems"]), "diagnostic-layer secret hit blocks publication (R5-B4): %s" % j)
    # R5-B9：被审输入含已解析秘密 → preflight 拒（secret-in-input），束不投递
    env.repo.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "# Demo\n\nkey = sk-fake-secret-value-123\n")
    code, out, err, j = env.run("review", env.repo.request("r1", inputs={"candidates": ["mechanisms/demo/HarnessPlane_Demo_Design_v1.md"], "references": []}))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and j["failure_code"] == "secret-in-input" and rec["receipt_phase"] == "routed"
            and not os.path.isdir(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "inputs")),
            "secret in the candidate refused before sealing (R5-B9): %s" % j)
    env.repo.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "# Demo\n\n> Depends on:\n> `AGENTS.md`\n>\n\nBody references `mechanisms/gates/rules_catalog.json` and `records/fixture-reference.md`.\n")
    # R6-B3：参考件含秘密 → 写入封存目录之前即拒，inputs 目录不留任何件
    env.repo.write("mechanisms/demo/leaky.md", "base sk-fake-secret-value-123\n")
    env.repo.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "# Demo\n\nSee `mechanisms/demo/leaky.md`.\n")
    code, out, err, j = env.run("review", env.repo.request("r1", inputs={"candidates": ["mechanisms/demo/HarnessPlane_Demo_Design_v1.md"], "references": ["mechanisms/demo/leaky.md"]}))
    e.check(code == 1 and j["failure_code"] == "secret-in-input"
            and not os.path.exists(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "inputs")),
            "secret in a reference refused before sealing; bundle withdrawn (R6-B3): %s" % j)
    os.unlink(env.repo.path("mechanisms/demo/leaky.md"))
    env.repo.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "# Demo\n\n> Depends on:\n> `AGENTS.md`\n>\n\nBody references `mechanisms/gates/rules_catalog.json` and `records/fixture-reference.md`.\n")
    # R6-B4：Request 自身（runtime_overrides 值）携带秘密 → secret-in-input，attempt 内 request.json 脱敏
    req_ov = env.repo.request("r1", runtime_overrides={"x": "sk-fake-secret-value-123"})
    code, out, err, j = env.run("review", req_ov)
    att = os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"])
    e.check(code == 1 and j["failure_code"] == "secret-in-input" and base.read_bytes(os.path.join(att, "request.json")) == base.read_bytes(req_ov)
            and b"sk-fake-secret-value-123" not in base.read_bytes(os.path.join(att, "receipt.json")), "request-side secret refused; exact copy kept, Receipt clean (R6-B4 / OD-09 乙): %s" % j)
    # R7-B1：秘密在校验失败字段旁（caller 非法 + background 含密）→ 预扫描先于分配落盘，request.json 脱敏、失败码 secret-in-input
    req = env.repo.request("r1", caller=5)
    raw = json.loads(base.read_bytes(req)); raw["review_brief"]["background"] = "note sk-fake-secret-value-123"
    open(req, "w", encoding="utf-8").write(json.dumps(raw, ensure_ascii=False))
    code, out, err, j = env.run("review", req)
    att = os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"])
    rec = json.loads(base.read_bytes(os.path.join(att, "receipt.json")))
    e.check(code == 1 and j["failure_code"] == "secret-in-input" and rec["diagnostics"]["request_secret_hit_at_allocation"] is True
            and base.read_bytes(os.path.join(att, "request.json")) == base.read_bytes(req)
            and rec["request_sha256"] == base.sha256_bytes(base.read_bytes(req)) and rec["receipt_phase"] == "routed"
            and b"sk-fake-secret-value-123" not in base.pretty_json(rec),
            "pre-allocation hit ends the attempt before validation; request.json stays the exact copy (§8.1, OD-09 乙, RES-4): %s" % j)
    # R7-B2：基础设施失败 + 秘密只在 Receipt 证据字段（runtime_version）→ INVALID
    env.control(behavior="infra-fail", failure="provider_unavailable", version="fake sk-fake-secret-value-123")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and rec["classification"] == "provider_unavailable" and rec["verdict_validation"] == "INVALID"
            and rec["diagnostics"]["secret_leak_in_evidence"] is True and rec["extraction"]["tier"] == "invalid"
            and b"sk-fake-secret-value-123" not in base.pretty_json(rec), "receipt evidence hit invalidates a failed review (R7-B2): %s" % rec["verdict_validation"])
    att_ev = json.loads(base.read_bytes(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "attempt.json")))
    e.check(att_ev["phase"] == "validated" and att_ev["verdict_validation"] == "INVALID" and b"sk-fake-secret-value-123" not in base.pretty_json(att_ev),
            "receipt-evidence INVALID reaches the validated record before the Receipt (R17-B1): %s" % att_ev["phase"])
    # 自查整改（r18 前）：判词 VALID + 秘密只在 Receipt / Profile 证据字段（runtime_version）→ 发布前终检拒绝；失败 Receipt 取 called 而非 completed
    env.control(behavior="valid", version="fake sk-fake-secret-value-123")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    att_ev = json.loads(base.read_bytes(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "attempt.json")))
    e.check(code == 1 and rec["classification"] == "reviewer_output_invalid" and rec["failure_code"] == "secret-leak"
            and rec["receipt_phase"] == "called" and rec["verdict_published"] is False and rec["attempt_outcome"] == "receipt_only"
            and rec["verdict_path"] is None and rec["effective_profile"]["verdict_path"] is None and rec["runtime"] is not None
            and rec["extraction"]["tier"] == "strict" and rec["verdict_validation"] == "INVALID" and rec["capability_suggestion"] == "PROBED"
            and rec["diagnostics"]["secret_leak_in_evidence"] is True and b"sk-fake-secret-value-123" not in base.pretty_json(rec)
            and att_ev["phase"] == "validated" and att_ev["verdict_validation"] == "INVALID" and env.tracked("r1") is None,
            "receipt / profile evidence secret on the VALID path: failure Receipt is called, never completed: %s / %s" % (rec["receipt_phase"], rec["failure_code"]))
    env.control(behavior="secret-leak")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and rec["verdict_validation"] == "INVALID" and rec["diagnostics"]["secret_leak_redacted"] is True, "secret in output → INVALID, redacted")
    att_leak = json.loads(base.read_bytes(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "attempt.json")))
    e.check(att_leak["phase"] == "validated" and att_leak["verdict_validation"] == "INVALID", "secret-hit INVALID also reaches the validated record (R16-B1)")
    attempt_dir = os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"])
    e.check(b"sk-fake-secret-value-123" not in base.read_bytes(os.path.join(attempt_dir, "reviewer_last_message.md")), "diagnostic redacted")
    # r18 自查整改（R18-B1 线索）：秘密字面与治理工件结构字节重叠（此处 = Receipt 成员名 receipt_schema）→ preflight 拒绝
    # secret-structural-collision，Receipt 成员名完整在场、无 Traceback；随后恢复默认 zshrc
    e.fake_zshrc("export FAKE_API_KEY=receipt_schema\nexport FAKE_API_BASE='https://fake.invalid/v1'\n", path_dir=e.tmp_root, name=".zshrc")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and j["failure_code"] == "secret-structural-collision" and rec["receipt_phase"] == "routed"
            and rec["classification"] == "preflight_failed" and rec["receipt_schema"] is not None and "Traceback" not in err
            and set(rec) == set(RC.RECEIPT_KEYS), "secret overlapping structural bytes is refused at preflight; Receipt schema intact: %s" % j)
    # r18 R18-B1 整改：带引号字面量（单引号 zshrc 值内的 "receipt_schema"）、替换哨兵子串、纯结构流字符值三族同样在 preflight 拒绝
    for literal, why in (("'\"receipt_schema\"'", "quoted member-name literal"), ("'REDACTED-SECRET'", "substring of the redaction sentinel"),
                        ("'null, 123'", "quote-free structural-stream characters only"),
                        ("'q\"q'", "raw quote inside the value (a raw quote can only ever match structural bytes)"),
                        # R19-B1：preflight 可预知的动态成员名——环境变量名键、适配器事实键（fake preflight 返回 recognition）、诊断文件名
                        ("FAKE_API_BASE", "environment-report member name (Registry variable name)"),
                        ("recognition", "adapter preflight fact member name"),
                        ("reviewer_last_message.md", "diagnostics artifact name"),
                        # R20-B1：脱敏算法自身可生成的字节（哨兵#n 的子串）——去重后缀会把秘密写回，preflight 拒绝
                        ("'#2'", "dedupe suffix literal"), ("'T]#7'", "substring spanning the sentinel tail and a dedupe suffix"),
                        # R21-B1：连续哨兵的跨界子串与输出层替代文本的子串同属生成字节语言
                        ("'T][RED'", "substring spanning two adjacent sentinels"), ("REDACTED-OUTPUT", "substring of the output fallback text")):
        e.fake_zshrc("export FAKE_API_KEY=%s\nexport FAKE_API_BASE='https://fake.invalid/v1'\n" % literal, path_dir=e.tmp_root, name=".zshrc")
        code, out, err, j = env.run("review", env.repo.request("r1"))
        rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
        e.check(code == 1 and j["failure_code"] == "secret-structural-collision" and rec["receipt_phase"] == "routed" and "Traceback" not in err
                and set(rec) == set(RC.RECEIPT_KEYS), "%s is refused at preflight as a structural collision: %s" % (why, j))
    # R19-B1：调用后才出现的动态成员名（提供方应答 usage 键 input_tokens）不可在 preflight 预知——成员名级脱敏兜底：
    # 判词 VALID 路径的发布前终检命中 → secret-leak、INVALID、Receipt 内成员名已脱敏、tracked 未建
    e.fake_zshrc("export FAKE_API_KEY=input_tokens\nexport FAKE_API_BASE='https://fake.invalid/v1'\n", path_dir=e.tmp_root, name=".zshrc")
    env.control(behavior="valid", usage={"input_tokens": 1, "output_tokens": 2})
    code, out, err, j = env.run("review", env.repo.request("r1"))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    att_dyn = json.loads(base.read_bytes(os.path.join(env.repo.path(env.repo.attempts_dir("r1")), j["attempt_id"], "attempt.json")))
    # （假适配器的事件流也含 input_tokens：诊断层先命中 → verdict-invalid；无论哪个终检先命中，Receipt 与记录都不含该字节）
    e.check(code == 1 and j["failure_code"] in ("secret-leak", "verdict-invalid") and rec["receipt_phase"] == "called" and rec["verdict_validation"] == "INVALID"
            and rec["classification"] == "reviewer_output_invalid" and b"input_tokens" not in base.pretty_json(rec)
            and b"input_tokens" not in base.pretty_json(att_dyn)
            and rec["effective_profile"]["calls"][0]["usage"] == {"[REDACTED-SECRET]": 1, "output_tokens": 2}
            and att_dyn["effective_profile"]["calls"][0]["usage"] == {"[REDACTED-SECRET]": 1, "output_tokens": 2}
            and "Traceback" not in err and env.tracked("r1") is None,
            "post-call dynamic member name colliding with a secret is scrubbed deterministically, never an internal error: %s" % j)
    # 结构字面若同时出现在 Request 原始字节里（如 `": "`），分配前预扫描先以 secret-in-input 结束 attempt（更早的关口，R7-B1）
    e.fake_zshrc("export FAKE_API_KEY='\": \"'\nexport FAKE_API_BASE='https://fake.invalid/v1'\n", path_dir=e.tmp_root, name=".zshrc")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "secret-in-input" and "Traceback" not in err, "delimiter-shaped literal is caught by the pre-allocation request scan first: %s" % j)
    e.fake_zshrc(None, path_dir=e.tmp_root, name=".zshrc")
    # 资格拒绝：作者含评审方厂商
    code, out, err, j = env.run("review", env.repo.request("r1", artifact_author={"human_only": False, "authors": [{"tool": "codex-cli", "model": "m", "vendor": "DeepSeek"}]}))
    rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
    e.check(code == 1 and rec["failure_code"] == "eligibility" and rec["receipt_phase"] == "routed" and rec["effective_profile"] is None, "eligibility rejection receipt (routed)")
    # formal 授权缺失
    code, out, err, j = env.run("review", env.repo.request("r1", formal_review_authorized_by_owner=None))
    e.check(code == 1 and j["failure_code"] == "formal-authorization-required", "CONFIGURED needs formal authorization")
    # 引用缺件
    env.repo.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "# Demo\n\nSee `mechanisms/ghost.md`.\n")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "reference-unresolved", "reference unresolved")
    # 人裁决点
    env.repo.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "# Demo\n")
    env.control(behavior="valid", verdict="PASS", human=True)
    code, out, err, j = env.run("review", env.repo.request("r1", inputs={"candidates": ["mechanisms/demo/HarnessPlane_Demo_Design_v1.md"], "references": []}))
    e.check(code == 0 and j["human_decision_required"] is True and j["verdict"] == "PASS", "human finding surfaces the stop signal: %s" % err[-300:])
    # inline 投递与 wrapper
    env7 = Env(e, {"behavior": "wrapper", "verdict": "FAIL"})
    code, out, err, j = env7.run("review", env7.repo.request("r1", profile={"provider": "fake-inline", "model": "inline-model"}))
    e.check(code == 0 and j["extraction_tier"] == "strict", "inline wrapper published: %s" % err[-300:])
    r = json.loads(base.read_bytes(env7.repo.path(env7.repo.tracked_dir("r1") + "/receipt-r1.json")))
    e.check(r["delivery"] == "inline" and r["runtime"]["api_endpoint_id"] is None and r["runtime"]["tool_version"] is None
            or r["delivery"] == "inline", "inline delivery recorded")
    # R11-B1：适配器 preflight 抛含秘密异常（清洗器须已启用）→ 两流均无秘密
    env11 = Env(e, {"behavior": "valid", "preflight_raise_secret": True})
    code, out, err, j = env11.run("review", env11.repo.request("r1"))
    e.check(code == 1 and "sk-fake-secret-value-123" not in err and "sk-fake-secret-value-123" not in out and j["failure_code"] == "internal-error",
            "adapter preflight exception is scrubbed: scrubber armed at secret resolution (R11-B1): %s" % err[-200:])
    # R11-B2：适配器异常文本含秘密 → stderr / stdout 报告均脱敏
    env10 = Env(e, {"behavior": "raise-secret"})
    code, out, err, j = env10.run("review", env10.repo.request("r1"))
    e.check(code == 1 and "sk-fake-secret-value-123" not in err and "sk-fake-secret-value-123" not in out and j["failure_code"] == "internal-error",
            "adapter exception text is scrubbed on both streams (R11-B2)")
    # R3-B5：调用后内部异常同经 _conclude_failure（called 阶段 extraction 补齐、闭集失败码、调用序号）
    env9 = Env(e, {"behavior": "post-call-crash"})
    code, out, err, j = env9.run("review", env9.repo.request("r1"))
    rec = env9.receipts("r1")[0][1]
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid" and j["failure_code"] == "internal-error"
            and rec["receipt_phase"] == "called" and rec["extraction"]["tier"] == "invalid" and rec["failure_call_index"] == 1
            and rec["verdict_validation"] == "INVALID" and rec["capability_suggestion"] != "REVIEW_ENABLED",
            "post-call internal error receipt satisfies the called-phase schema (R3-B5): %s" % err[-300:])
    env8 = Env(e, {"behavior": "wrapper-bad"})
    code, out, err, j = env8.run("review", env8.repo.request("r1", profile={"provider": "fake-inline", "model": "inline-model"}))
    rec = env8.receipts("r1")[0][1]
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid" and rec["extraction"]["tier"] == "invalid"
            and len(rec["effective_profile"]["calls"]) == 1, "wrapper invalid, no re-emission on the inline path: %s" % j)


def unrouteable_and_startup(e):
    env = Env(e)
    p = os.path.join(e.tmpdir("bad"), "req.json")
    open(p, "w").write("{")
    code, out, err, j = env.run("review", p)
    e.check(code == 1 and "request-unrouteable" in err and not os.path.isdir(env.repo.path("tasks/gov-t1/attempts")), "unrouteable: no attempt dir")
    open(p, "w").write(json.dumps({"subject": "demo", "stage": "impl", "round": "x1"}))
    code, out, err, j = env.run("review", p)
    e.check(code == 1 and "request-unrouteable" in err, "round grammar unrouteable")
    # r18 自查整改（R18-B2 线索）：合法 JSON 内的孤立代理项转义 = 不可解析 → request-unrouteable、零目录、无 Traceback
    open(p, "w").write('{"subject": "demo", "stage": "impl", "round": "r1", "invocation_authorization": "auth \\ud800"}')
    code, out, err, j = env.run("review", p)
    e.check(code == 1 and "request-unrouteable" in err and "Traceback" not in err and not os.path.isdir(env.repo.path("tasks/gov-t1/attempts")),
            "lone surrogate in a legal JSON request is unrouteable, never an uncaught exception: %s" % err[-200:])
    # 非净化启动的负例恒不带 -B / -E / -s / -S（启动形态检查看的正是这四个标志）；另给 pycache_prefix 只把该次启动
    # 写出的字节码引到临时目录，不改变被检查的标志，故不弱化本断言，也不在单元目录留副产物（§14 S13 零工作树副产物）
    proc = subprocess.run([sys.executable, "-X", "pycache_prefix=" + e.tmpdir("pycache"),
                           os.path.join(e.unit_dir, "review_channel.py"), "review", "--request", p], capture_output=True, text=True,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": e.tmp_root})
    e.check(proc.returncode == 2 and "startup form" in proc.stderr, "non-sanitized launch refused with exit 2")
    # 减重第 3 步（F9 甲）：通道不再作运行时身份资格检查——不读只读历史档案内的运行时身份允许集合、无 runtime-identity 退出路径
    src_entry = open(os.path.join(e.unit_dir, "review_channel.py"), encoding="utf-8").read()
    e.check("runtime_qualification" not in src_entry and not hasattr(base, "runtime_qualification") and not hasattr(base, "RUNTIME_ENV_PATH")
            and "runtime-identity-not-allowed" not in C.FAILURE_CODES, "static: no runtime identity qualification remains in the entry or the base")
    # R9-B1 / R10-B1：入口不存在任何注入口——Registry / 适配器恒取自被审仓根，配置正本恒取自 HOME；旧注入旗标即未知参数
    for flag in (("--request",), ("--repo-root",)):
        code, out, err, j = env.run("preflight", env.repo.request("r1"), *flag)
        e.check(code == 2 and "requires an operand" in err and "Traceback" not in err, "%s without an operand is a controlled usage failure (R11-B3)" % flag[0])
    for flag in (("--registry", "x"), ("--adapters-dir", "x"), ("--zshrc", "x"), ("--no-recognition-probe",), ("--no-register",)):
        code, out, err, j = env.run("preflight", env.repo.request("r1"), *flag)
        e.check(code == 2 and "unknown argument" in err, "injection flag / retired switch %s refused as an unknown argument (R10-B1; register retired)" % flag[0])
    # respond 的调用形态：--decisions 必填绝对路径、不收 --request；其余子命令不收 --decisions
    code, out, err, j = env.run("preflight", env.repo.request("r1"), "--decisions", "/x.json")
    e.check(code == 2 and "only accepted by respond" in err, "--decisions refused outside respond")
    code, out, err, j = env.run("respond", env.repo.decisions_input("r1", []), "--request", "/x.json")
    e.check(code == 2 and "not --request" in err, "respond refuses --request")
    code, out, err, j = env.run("respond", "relative/decisions.json")
    e.check(code == 2 and "absolute path" in err, "respond requires an absolute --decisions path")
    src = open(os.path.join(e.unit_dir, "review_channel.py"), encoding="utf-8").read()
    e.check(all(t not in src for t in ("--registry", "--adapters-dir", "--zshrc", "--no-recognition-probe", "SELFTEST"))
            and 'REGISTRY_REL = "mechanisms/review-channel/review_channel_registry.json"' in src and "os.path.join(self.repo_root, REGISTRY_REL)" in src
            and "os.path.join(self.repo_root, ADAPTERS_REL)" in src, "static: registry and adapters derive from the repo root only; no injection surface")
    # 被审仓根缺少 Registry → registry-invalid（取自仓根的证据）
    os.unlink(env.registry)
    code, out, err, j = env.run("preflight", env.repo.request("r1"))
    e.check(code == 1 and j.get("failure_code") == "registry-invalid", "registry is read from the repo root under review: %s" % (j or err[-200:]))


def concurrency_and_occupied(e):
    env = Env(e)
    ard = env.repo.path(env.repo.attempts_dir("r1"))
    os.makedirs(ard, exist_ok=True)
    holder = subprocess.Popen([sys.executable, "-c",
                               "import fcntl,os,sys,time\nfd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT)\nfcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)\nprint('held',flush=True)\ntime.sleep(60)",
                               os.path.join(ard, ".in-progress")], stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    inode = os.stat(os.path.join(ard, ".in-progress")).st_ino
    try:
        code, out, err, j = env.run("review", env.repo.request("r1"))
        e.check(code == 1 and j["failure_code"] == "round-in-progress", "held lock → round-in-progress")
        rec = env.receipts("r1")[0][1]
        e.check(rec["classification"] == "preflight_failed" and rec["receipt_phase"] == "routed", "round-in-progress receipt")
    finally:
        holder.kill()
        holder.wait()
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 0 and os.stat(os.path.join(ard, ".in-progress")).st_ino == inode, "after SIGKILL the lock is free without cleanup; inode constant")
    e.check(not any(n.startswith(".in-progress.") for n in os.listdir(ard)), "no lock side files")
    # 目标已存在（四件齐备）：第二次投同轮
    env.repo.commit("r1")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "round-not-increasing", "published round refuses a new attempt at preflight")
    # 预先存在的目录：preflight 序号判定即拒（存在即计入最大轮序号）
    env2 = Env(e)
    os.makedirs(env2.repo.path(env2.repo.tracked_dir("r1")))
    code, out, err, j = env2.run("review", env2.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "round-not-increasing" and os.listdir(env2.repo.path(env2.repo.tracked_dir("r1"))) == [],
            "pre-existing dir refused at preflight and untouched: %s" % j)
    # 提交协议本体：目标在核对时刻存在（空 / 非空 / 四件齐备）一律拒绝、暂存删除、tracked 未触碰
    import review_channel as RCH

    class _A:
        pass
    for content in ("empty", "unknown", "four"):
        att_dir = e.tmpdir("att")
        a = _A()
        a.repo_root = env2.repo.root
        a.routing = {"tracked_round_dir": "tasks/gov-t1/reviews/impl-r9"}
        a.attempt_id = "A-" + content
        a.dir = att_dir
        pf = _A()
        pf.task_file, pf.verdict_file, pf.request = "T.md", "V.md", {"round": "r9"}
        os.makedirs(os.path.join(att_dir, "inputs"))
        for rel in ("inputs/T.md", "bundle_manifest.json", "V.md"):
            open(os.path.join(att_dir, rel), "w").write("x")
        target = env2.repo.path("tasks/gov-t1/reviews/impl-r9")
        os.makedirs(target)
        if content == "unknown":
            open(os.path.join(target, "stray.txt"), "w").write("s")
        elif content == "four":
            for n in ("T.md", "V.md", "bundle_manifest.json", "receipt-r9.json"):
                open(os.path.join(target, n), "w").write("p")
        before = sorted(os.listdir(target))
        code = RCH.publish(a, pf, b"{}")
        e.check(code == "tracked-round-dir-occupied" and sorted(os.listdir(target)) == before, "occupied (%s) refused and untouched" % content)
        e.check(not any(n.startswith("publish.tmp-") for n in os.listdir(att_dir)), "staging removed (%s)" % content)
        base.remove_tree(target)
    a.attempt_id = "A-ok"
    code = RCH.publish(a, pf, b"{}")
    e.check(code is None and _four(sorted(os.listdir(target))), "absent target → one rename publishes four members")
    # R3-B8：rename 之后父目录描述符 close 抛错不得反转发布结局
    base.remove_tree(target)
    a.attempt_id = "A-close"
    real_os = RCH.os

    class _OsProxy:
        def __init__(self):
            self.target_fd = None

        def __getattr__(self, name):
            return getattr(real_os, name)

        def open(self, path, flags, *rest, **kw):
            fd = real_os.open(path, flags, *rest, **kw)
            if flags & real_os.O_DIRECTORY:
                self.target_fd = fd
            return fd

        def close(self, fd):
            if fd == self.target_fd:
                self.target_fd = None
                real_os.close(fd)
                raise OSError(5, "injected close failure")
            return real_os.close(fd)
    RCH.os = _OsProxy()
    try:
        code = RCH.publish(a, pf, b"{}")
    finally:
        RCH.os = real_os
    e.check(code is None and _four(sorted(os.listdir(target))), "close failure after rename: publication stands (R3-B8): %r" % code)
    # subject 轴端到端
    env3 = Env(e)
    code, out, err, j = env3.run("review", env3.repo.request("r1", task=False))
    e.check(code == 0 and _four(env3.tracked("r1", task=False)) and os.path.isdir(env3.repo.path("review-attempts/demo/r1")), "subject axis two-dir derivation")


def crash_recovery(e):
    env = Env(e, {"behavior": "valid"})
    # 死所有者的 .alloc 与 attempt.json（sealed 态）→ 补产 interrupted；活所有者不动
    ard = env.repo.path(env.repo.attempts_dir("r1"))
    os.makedirs(ard)
    dead = os.path.join(ard, ".alloc-X-999999-token")
    os.makedirs(dead)
    alive_token = base.process_start_token(os.getpid())
    alive = os.path.join(ard, ".alloc-Y-%d-%s" % (os.getpid(), "".join(c if c.isalnum() else "_" for c in alive_token)[:48]))
    os.makedirs(alive)
    att = os.path.join(ard, "20260101T000000Z-deadbeef")
    os.makedirs(att)
    record = {"attempt_id": "20260101T000000Z-deadbeef", "mode": "review", "pid": 999999, "pid_start": "gone", "at": "t", "phase": "sealed",
              "routing": {"subject": "demo", "stage": "impl", "round": "r1", "task_record": "gov-t1"}, "request_sha256": "q",
              "invocation_authorization_sha256": "i", "formal_review_authorized_by_owner": True,
              "effective_profile": __import__("review_channel_selftest_receipt").valid_profile(),
              "input_manifest_sha256": "m", "round_budget": {}, "decisions_sha256": None, "delivery": "tool"}
    open(os.path.join(att, "attempt.json"), "w").write(json.dumps(record))
    os.makedirs(os.path.join(att, "publish.tmp-20260101T000000Z-deadbeef"))
    open(os.path.join(att, "receipt.json.tmp-999999-gone"), "w").write("partial")
    # respond 不是恢复起点（§6.12：零提供方接触、不是 attempt、不取锁）——不删遗留、不补产
    env.run("respond", env.repo.decisions_input("r1", []))
    e.check(os.path.isdir(dead) and not os.path.exists(os.path.join(att, "receipt.json")) and os.path.isdir(os.path.join(att, "publish.tmp-20260101T000000Z-deadbeef")),
            "respond neither removes leftovers nor synthesizes receipts")
    code, out, err, j = env.run("preflight", env.repo.request("r1"))
    e.check(code == 0, "preflight runs cleanup: %s" % err[-300:])
    e.check(not os.path.exists(dead) and os.path.isdir(alive), "dead alloc removed, live alloc kept")
    rec = json.loads(base.read_bytes(os.path.join(att, "receipt.json")))
    e.check(rec["classification"] == "interrupted" and rec["receipt_phase"] == "sealed" and rec["effective_profile"]["calls"] is None
            and rec["input_manifest_sha256"] == "m" and rec["synthesized_by"]["role"] == "preflight" and isinstance(rec["synthesized_by"]["pid"], int)
            and rec["synthesized_by"]["attempt_id"] is None, "interrupted receipt synthesized from attempt.json; recoverer identity object (R1-B4)")
    e.check(not os.path.exists(os.path.join(att, "publish.tmp-20260101T000000Z-deadbeef")) and not os.path.exists(os.path.join(att, "receipt.json.tmp-999999-gone")),
            "stale staging and temp receipt removed")
    first = base.read_bytes(os.path.join(att, "receipt.json"))
    env.run("preflight", env.repo.request("r1"))
    e.check(base.read_bytes(os.path.join(att, "receipt.json")) == first, "not synthesized twice")
    os.rmdir(alive)
    # R5-B3：并发恢复者先删（remove_tree 中途对象消失）→ 只记事实，不逃逸
    import review_channel as RCH
    race = os.path.join(ard, ".alloc-R-999999-token")
    os.makedirs(os.path.join(race, "sub"))
    real_remove = RCH.base.remove_tree
    RCH.base.remove_tree = lambda p: (real_remove(p), (_ for _ in ()).throw(FileNotFoundError(2, "gone", p)))[1]
    try:
        rep = RCH.preflight_cleanup(env.repo.root, RCH.derive_routing({"subject": "demo", "stage": "impl", "round": "r1", "task_record": "gov-t1"}), RCH._recoverer_identity())
    finally:
        RCH.base.remove_tree = real_remove
    e.check(any(x.get("action") == "alloc-removed-by-concurrent-recoverer" for x in rep) and not os.path.exists(race), "concurrent deletion recorded as a fact (R5-B3): %s" % rep)
    # 真实崩溃：假适配器在 calling 态 SIGKILL 自身 → 下一 preflight 补产 calling 态 Receipt
    env.control(behavior="valid", crash_after="calling")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code != 0, "process killed")
    crashed = [n for n in os.listdir(ard) if not n.startswith(".") and n != "20260101T000000Z-deadbeef"]
    e.check(len(crashed) == 1 and not os.path.exists(os.path.join(ard, crashed[0], "receipt.json")), "crashed attempt has no receipt yet")
    env.control(behavior="valid")
    code, out, err, j = env.run("preflight", env.repo.request("r1"))
    rec = json.loads(base.read_bytes(os.path.join(ard, crashed[0], "receipt.json")))
    e.check(rec["classification"] == "interrupted" and rec["receipt_phase"] == "calling"
            and (rec["call_path_proof"], rec["profile_binding"], rec["verdict_validation"]) == ("INDETERMINATE", "INSUFFICIENT", "NOT_REACHED"),
            "calling-phase interrupted receipt: %s" % {k: rec[k] for k in ("receipt_phase", "call_path_proof", "profile_binding")})
    # 发布后回链前崩溃的等价：删除回链后 preflight 重新回链
    env.control(behavior="valid")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 0, "publish for backlink test: %s" % err[-200:])
    att_ok = os.path.join(ard, j["attempt_id"])
    os.unlink(os.path.join(att_ok, "receipt.json"))
    env.run("preflight", env.repo.request("r1"))  # 前置清理先于任何检查执行；本轮已发布故检查本身判 round-not-increasing
    e.check(os.path.exists(os.path.join(att_ok, "receipt.json")), "backlink restored for the published attempt (owner dead after exit)")
    e.check(os.stat(os.path.join(att_ok, "receipt.json")).st_ino == os.stat(env.repo.path(env.repo.tracked_dir("r1") + "/receipt-r1.json")).st_ino,
            "restored backlink shares the tracked inode")
    e.check(len([n for n in os.listdir(ard) if n.startswith(".in-progress")]) == 1, "lock file constant")


def derivation_static(e):
    import review_channel as RCH
    routing = RCH.derive_routing({"subject": "demo", "stage": "impl", "round": "r1", "task_record": "gov-t1"})
    e.check(routing["tracked_round_dir"] == "tasks/gov-t1/reviews/impl-r1" and routing["attempt_round_dir"] == "tasks/gov-t1/attempts/impl-r1"
            and routing["tracked_parent"] == "tasks/gov-t1/reviews", "task axis derivation")
    s = RCH.derive_routing({"subject": "demo", "stage": "impl", "round": "r2", "task_record": None})
    e.check(s["tracked_round_dir"] == "reviews/demo/r2" and s["attempt_round_dir"] == "review-attempts/demo/r2" and s["tracked_parent"] == "reviews/demo", "subject axis derivation")
    # Amendment 4（§8.4）：register 整体退役——子命令闭集无 register、入口无 run_register / --no-register / register_enabled，
    # 发布之后通道不执行任何 Git 动作（入口内零处 git_run；决定文件模块亦不触 Git）
    src = open(os.path.join(e.unit_dir, "review_channel.py"), encoding="utf-8").read()
    src_d = open(os.path.join(e.unit_dir, "review_channel_decisions.py"), encoding="utf-8").read()
    e.check(RCH.SUBCOMMANDS == ("preflight", "probe", "review", "respond", "selftest", "archive") and not hasattr(RCH, "run_register") and not hasattr(RCH, "register_round")
            and "--no-register" not in src and "register_enabled" not in src and "git_run(" not in src and "git_run(" not in src_d
            and "standard_questions" not in src, "static: register retired entirely; no Git action after publication; no standard-questions flag")
    e.check(src.count("fcntl.flock(") == 1 and src.count("acquire_round_lock(") == 2, "static: the lock is taken at exactly one site, called once")
    e.check("os.unlink(" not in src.split("def acquire_round_lock")[1].split("def note_lock_holder")[0], "static: lock file never unlinked by the lock code")
    pub = src.split("def publish(")[1].split("def _describe_dir")[0]
    e.check("os.makedirs(parent_abs" in pub and pub.count("os.rename(") == 1 and "os.makedirs(os.path.join(repo_root, tracked" not in pub,
            "static: publish never creates the target path; exactly one rename")
    e.check(pub.index("published = True") < pub.index("os.close(parent_fd)") and "if published:" in pub, "static: the irreversible success point precedes the descriptor close (R3-B8)")
    e.check("os.stat(name, dir_fd=parent_fd, follow_symlinks=False)" in pub and 'if exists or H.items(repo_root, tracked+"/"):' in pub
            and pub.index('if exists or H.items(repo_root, tracked+"/"):') < pub.index("os.rename(staging, name, dst_dir_fd=parent_fd)"),
            "static: target-existence check gates the rename (§8.2 step 2; mutation M11 must turn this red)")
    locked = src.split("def _run_locked(")[1].split("def _finish_probe(")[0]
    e.check("attempt.advance(\"sealed\"" in locked.split("    except base.PreflightError")[0], "static: sealed-state writes sit inside the pre-call internal-error envelope (R3-B10)")
    e.check("_write_failure_receipt(" not in locked.split("# ---- 调用")[1], "static: post-call fallback goes through _conclude_failure only (R3-B5)")
    eng = open(os.path.join(e.unit_dir, "review_channel_selftest.py"), encoding="utf-8").read()
    mut = eng.split("def run_mutations(")[1].split("def main(")[0]
    verdict = eng.split("def mutation_outcome(")[1].split("def run_mutations(")[0]
    e.check('"--repo-root", engine.repo_root' in mut and "mutation_outcome(mut[\"must_fail\"]" in mut
            and "set(ran_cases) != set(must_fail)" in verdict,
            "static: mutants run against the caller's repo root and every must_fail case must run (R9-B2); verdict via mutation_outcome (§12 第 17 类)")
    e.check(e.repo_root == os.path.realpath(os.path.join(e.unit_dir, os.pardir, os.pardir)) or os.path.isfile(os.path.join(e.repo_root, "mechanisms/gates/rules_catalog.json")),
            "engine repo root is a real repository (mutant copies inherit it)")


def two_round_cap(e):
    """S25 / V6（Amendment 4，F8 甲）：Registry 缺省额度 2——同轴 r1、r2 各已发布后 r3 preflight 到额 `round_budget_exhausted`，
    stderr 含已投递轮数与允许轮数 2；出口其一 = 请求件追加一条 Human 加轮授权记录 → r3 放行；无效 attempt 不计入额度。"""
    env = Env(e, {"behavior": "valid", "verdict": "FAIL"})
    reg = json.loads(base.read_bytes(env.registry))
    e.check(reg["defaults"]["max_rounds"] == 2, "fixture registry default max_rounds = 2")
    live = json.loads(base.read_bytes(os.path.join(e.repo_root, "mechanisms/review-channel/review_channel_registry.json")))
    e.check(live["defaults"]["max_rounds"] == 2 and live["registry_revision"] == 7, "live Registry: defaults.max_rounds 2, registry_revision 7")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 0 and j["verdict"] == "FAIL", "r1 FAIL published: %s" % err[-300:])
    env.repo.commit("r1")
    brief2 = env.next_round_brief("r1", [{"finding_id": "R1-B1", "action": "fix", "instructions": "x", "owner_verbatim": "v"}])
    code, out, err, j = env.run("review", env.repo.request("r2", previous=env.repo.previous_round("r1"), **brief2))
    e.check(code == 0 and j["verdict"] == "FAIL", "r2 FAIL published: %s" % err[-300:])
    env.repo.commit("r2")
    brief3 = env.next_round_brief("r2", [{"finding_id": "R2-B1", "action": "fix", "instructions": "y", "owner_verbatim": "w"}])
    code, out, err, j = env.run("preflight", env.repo.request("r3", previous=env.repo.previous_round("r2"), **brief3))
    e.check(code == 1 and j["failure_code"] == "round_budget_exhausted" and "submitted rounds 2 >= allowed rounds 2" in err and "max_rounds 2 from default" in err
            and "blocking findings: 1" in err and "round_extensions" in err, "third round refused at the default cap of two with the human hint: %s" % err[-400:])
    e.check(env.tracked("r3") is None and not os.path.isdir(env.repo.path(env.repo.attempts_dir("r3"))), "preflight refusal leaves no r3 artifacts")
    code, out, err, j = env.run("preflight", env.repo.request("r3", previous=env.repo.previous_round("r2"), **brief3,
                                                              round_extensions=[{"authorized_by": "owner: 加 1 轮", "at": "2026-09-06", "added_rounds": 1, "note": "2/2 used"}]))
    e.check(code == 0 and j["state"] == "PASS" and j["budget"]["allowed_rounds"] == 3 and j["budget"]["extensions_added"] == 1,
            "exit one: a Human extension record lifts the cap: %s" % err[-300:])


def unchanged_region(e):
    """S24 / V5（Amendment 4，F4 甲）：`origin = unchanged_region` 且 `blocking` 的判词 → INVALID（`rule-14:<id>`）、`verdict-invalid`、
    无补发、tracked 无成员；请求件一字不改原样重投 → 放行且额度未增；改判 non_blocking / human 或取 changed_region → 通过。"""
    env = Env(e, {"behavior": "valid", "verdict": "FAIL", "first_origin": "unchanged_region"})
    req = env.repo.request("r1")
    code, out, err, j = env.run("review", req)
    rec = env.receipts("r1")[0][1]
    e.check(code == 1 and j["classification"] == "reviewer_output_invalid" and j["failure_code"] == "verdict-invalid"
            and any(p.startswith("rule-14:R1-B1") for p in j["verdict_problems"]) and rec["verdict_validation"] == "INVALID"
            and rec["extraction"]["reemit_trigger"] is None and len(rec["effective_profile"]["calls"]) == 1 and env.tracked("r1") is None,
            "unchanged-region blocking → INVALID with rule-14:<id>, no re-emission, nothing published: %s" % j)
    env.control(behavior="valid", verdict="FAIL", first_origin="changed_region")
    code, out, err, j = env.run("review", req)
    r = json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/receipt-r1.json")))
    e.check(code == 0 and j["verdict"] == "FAIL" and r["round_budget"]["submitted_rounds"] == 0, "same request re-submitted unchanged: published; the invalid attempt consumed no budget")
    env2 = Env(e, {"behavior": "valid", "verdict": "PASS", "extra_findings": [{"severity": "non_blocking", "origin": "unchanged_region"}], "human": True})
    code, out, err, j = env2.run("review", env2.repo.request("r1"))
    obj, _jb, _n = V.parse_published(base.read_bytes(env2.repo.path(env2.repo.tracked_dir("r1") + "/HarnessPlane_Demo_Review_R1.md")))
    e.check(code == 0 and sorted(f["origin"] for f in obj["findings"] if f["severity"] != "blocking") == ["unchanged_region", "unchanged_region"],
            "unchanged-region non_blocking and human findings pass: %s" % err[-300:])


def five_questions(e):
    """S23 / V4（Amendment 4，F1 甲）：判词题号集合 ≠ 该 stage 五题闭集（缺题、多出旧题 Q1、重复、取另一 stage 的套）→ INVALID、不补发、
    `calls[]` 恰一项；task 轮与 impl 轮各自以五题闭集通过；旧判词（v3）经 parse_published 仍可读出 verdict。"""
    impl = C.required_question_ids("impl")
    env = Env(e, {"behavior": "valid", "verdict": "PASS"})
    for label, ids in (("missing Q-REFERENCE", [q for q in impl if q != "Q-REFERENCE"]), ("extra Q1", impl + ["Q1"]),
                       ("duplicate Q-CHANGE", impl + ["Q-CHANGE"]), ("task set on impl", C.required_question_ids("task"))):
        env.control(behavior="valid", verdict="PASS", question_ids=ids)
        code, out, err, j = env.run("review", env.repo.request("r1"))
        rec = [r for _n, r in env.receipts("r1") if r["attempt_id"] == j["attempt_id"]][0]
        e.check(code == 1 and j["failure_code"] == "verdict-invalid" and any("five-question" in p for p in j["verdict_problems"])
                and rec["extraction"]["reemit_trigger"] is None and len(rec["effective_profile"]["calls"]) == 1 and env.tracked("r1") is None,
                "%s → INVALID as a judgment defect, one call: %s" % (label, j.get("verdict_problems")))
    env.control(behavior="valid", verdict="PASS")
    code, out, err, j = env.run("review", env.repo.request("r1"))
    obj, _jb, _n = V.parse_published(base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/HarnessPlane_Demo_Review_R1.md")))
    e.check(code == 0 and [q["question_id"] for q in obj["question_assessments"]] == impl and obj["verdict_schema"] == "review-channel-verdict/v4"
            and all(set(q) == set(C.ASSESSMENT_FIELDS) for q in obj["question_assessments"]), "impl round: five impl questions, v4 block")
    task = base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/HarnessPlane_Demo_Review_Task_R1.md")).decode()
    e.check(all(("**%s**" % q) in task for q in impl) and "Q1" not in task.split("## 8.")[1].split("## 9.")[0], "task book section 8 = the five impl questions")
    env3 = Env(e, {"behavior": "valid", "verdict": "PASS"})
    definition = '# gov-t1 · Synthetic task\n\n> Depends on:\n> `milestones.md@r1 gov-t1`\n>\n> 权威状态: subject `gov-t1-task`（治理记录目录按所在仓的布局规则解析；唯一状态正本）\n\n## Identity\n\n- Task record ID: `gov-t1`\n- Task kind: `governance`\n- Definition subject: `gov-t1-task`\n- Product line: `synthetic`\n\n## 通俗说明（给人读）\n\n本节只帮助人建立心智模型，不是任务契约的权威取值；冲突时以其余正式章节为准。\n\n此测试验证任务评审问题。\n\n## Goal\n\nValidate synthetic review.\n\n## Goal Conditions\n\n- Review is valid.\n\n## Scope In\n\n- Synthetic task.\n\n## Scope Out\n\n- Real models.\n\n## Constraints\n\nSynthetic only.\n\n## Acceptance Criteria\n\n- Five questions are validated.\n\n## Source References\n\n- Primary source: `milestones.md@r1 gov-t1`\n'
    env3.repo.write("spec/milestones.md", "# Synthetic milestones\n")
    env3.repo.write("tasks/gov-t1/gov-t1.md", definition)
    env3.repo.write("mechanisms/artifact-templates/artifact_lint.py", base.read_bytes(os.path.join(e.repo_root, "mechanisms/artifact-templates/artifact_lint.py")).decode())
    env3.repo.commit("definition")
    code, out, err, j = env3.run("review", env3.repo.request("r1", stage="task", inputs={"candidates": ["tasks/gov-t1/gov-t1.md"], "references": ["spec/milestones.md"]}))
    e.check(code == 0, "valid task structure fixture: %s" % err[-600:])
    obj, _jb, _n = V.parse_published(base.read_bytes(env3.repo.path("tasks/gov-t1/reviews/task-r1/HarnessPlane_Demo_Review_R1.md")))
    e.check(code == 0 and [q["question_id"] for q in obj["question_assessments"]] == C.required_question_ids("task"), "task round: FR-21 five questions: %s" % err[-300:])
    old = b"```review-channel-verdict\n" + json.dumps({"verdict_schema": "review-channel-verdict/v3", "verdict": "FAIL",
                                                        "question_assessments": [{"question_id": "STD-1", "assessment": "SATISFIED"}]}).encode() + b"\n```\n\n**Verdict: FAIL**\n"
    e.check(V.parse_published(old)[0]["verdict"] == "FAIL", "a v3 verdict still yields its verdict field to read-only consumers")


def respond_decisions(e):
    """S26 / V8（Amendment 4，F6 / F7 甲）：r1 三条 finding → respond（fix / skip 带 work_item / approve）→ 决定文件、stdout 处置段与派生残留项
    → r2 请求件按其填写后 preflight 通过、任务书含决定摘要、Receipt decisions_sha256 在场；五条规则与派生核对的各负例。"""
    env = Env(e, {"behavior": "valid", "verdict": "FAIL", "human": True, "extra_findings": [{"severity": "non_blocking"}]})
    code, out, err, j = env.run("review", env.repo.request("r1"))
    e.check(code == 0 and j["verdict"] == "FAIL", "r1 with B1 / N1 / H1 published: %s" % err[-300:])
    verdict_bytes = base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/HarnessPlane_Demo_Review_R1.md"))
    env.repo.commit("r1")
    good = [{"finding_id": "R1-B1", "action": "fix", "instructions": "rewrite section 2", "owner_verbatim": "改第二节"},
            {"finding_id": "R1-N1", "action": "skip", "work_item": "repo:KB-09", "owner_verbatim": "下次再说"},
            {"finding_id": "R1-H1", "action": "approve", "owner_verbatim": "同意"}]
    code, j, err = env.respond("r1", good)
    path = env.repo.path("tasks/gov-t1/attempts/impl-r1/decisions.json")
    doc = json.loads(base.read_bytes(path))
    dsha = base.sha256_bytes(base.read_bytes(path))
    e.check(code == 0 and j["state"] == "WRITTEN" and j["decisions_sha256"] == dsha and doc["decisions_schema"] == "review-channel-decisions/v1"
            and doc["verdict_sha256"] == base.sha256_bytes(verdict_bytes) == j["verdict_sha256"] and doc["task_record"] == "gov-t1" and doc["round"] == "r1"
            and doc["decisions"] == good and doc["decided_at"] and set(doc) == set(C.DECISIONS_FIELDS), "decisions file written with the channel-filled members: %s" % (j or err[-300:]))
    seg = j["next_round"]["remediation_statement"]
    e.check(seg.split("\n") == ["Dispositions (decisions.json sha256 %s)" % dsha[:12], "- R1-B1: fix · rewrite section 2", "- R1-H1: approve", "- R1-N1: skip · repo:KB-09"]
            and j["next_round"]["accepted_residuals"] == [{"id": "RES-1", "text": "extra 1 · repo:KB-09"}],
            "dispositions segment (verdict finding order B1, H1, N1) and derived residual: %s" % j["next_round"])
    e.check(not any(n.startswith(".tmp-") for n in os.listdir(os.path.dirname(path))), "atomic write leaves no temp file")
    # 覆盖语义：再次 respond 整体覆盖
    code2, j2, err2 = env.respond("r1", [dict(good[0], instructions="rewrite section 3")] + good[1:])
    e.check(code2 == 0 and json.loads(base.read_bytes(path))["decisions"][0]["instructions"] == "rewrite section 3" and j2["decisions_sha256"] != dsha, "second respond overwrites the file")
    code, j, err = env.respond("r1", good)
    dsha = j["decisions_sha256"]
    seg = j["next_round"]["remediation_statement"]
    derived = j["next_round"]["accepted_residuals"]
    # 负例（decisions-invalid）：blocking 的 skip 缺 work_item、缺一条、owner_verbatim 为空、输入内在场的 verdict_sha256、动作表外、fix 缺 instructions、
    # work_item 挂在 approve、work_item 文法、未知成员、判词不可定位（r2 尚未发布）
    for label, decisions, extra in (("blocking skip without work_item", [dict(good[0], action="skip", instructions=None), good[1], good[2]], {}),
                                    ("missing R1-H1", good[:2], {}), ("empty owner_verbatim", [dict(good[2], owner_verbatim="")] + good[:2], {}),
                                    ("verdict_sha256 in the input", good, {"verdict_sha256": "0" * 64}), ("decided_at in the input", good, {"decided_at": "now"}),
                                    ("action outside the closed set", [dict(good[2], action="defer")] + good[:2], {}),
                                    ("fix without instructions", [dict(good[0], instructions="")] + good[1:], {}),
                                    ("work_item on approve", [dict(good[2], work_item="repo:KB-01")] + good[:2], {}),
                                    ("work_item grammar", [dict(good[1], work_item="KB-09")] + [good[0], good[2]], {}),
                                    ("unknown member", [dict(good[2], note="x")] + good[:2], {}), ("duplicate finding_id", good + [good[2]], {}),
                                    ("unpublished round", good, {"round": "r2"})):
        decisions = [{k: v for k, v in d.items() if v is not None} for d in decisions]
        code, jj, err = env.respond("r1", decisions, **extra)
        e.check(code == 1 and jj["failure_code"] == "decisions-invalid" and "Traceback" not in err, "%s → decisions-invalid: %s" % (label, jj))
    e.check(base.sha256_bytes(base.read_bytes(path)) == dsha, "rejected inputs never touch the decisions file")
    # r2 派生核对：以处置段起始 + 派生残留在前 → preflight 通过
    residuals = derived + [{"id": "RES-2", "text": "caller residual"}]
    req2 = env.repo.request("r2", previous=env.repo.previous_round("r1"), remediation=seg + "\n\nfixed as instructed", residuals=residuals)
    code, out, err, j = env.run("preflight", req2)
    e.check(code == 0 and j["decisions_sha256"] == dsha, "r2 preflight passes on the derived brief: %s" % err[-300:])
    # 负例（decisions-mismatch）：删去处置段、残留缺派生项、text 不等、决定文件的 verdict_sha256 与上一轮判词不等
    for label, kw in (("segment removed", dict(remediation="fixed as instructed", residuals=residuals)),
                      ("derived residual missing", dict(remediation=seg + "\n\nfixed", residuals=[{"id": "RES-1", "text": "caller residual"}])),
                      ("derived residual text differs", dict(remediation=seg + "\n\nfixed", residuals=[{"id": "RES-1", "text": "extra 1"}]))):
        code, out, err, j = env.run("preflight", env.repo.request("r2", previous=env.repo.previous_round("r1"), **kw))
        e.check(code == 1 and j["failure_code"] == "decisions-mismatch", "%s → decisions-mismatch: %s" % (label, j))
    # 规则其五单独可判：决定文件的 verdict_sha256 被改而请求件按改后的文件字节重新派生（处置段前缀与残留均一致）→ 仍 decisions-mismatch
    import review_channel_decisions as D
    tampered = dict(doc, verdict_sha256="1" * 64)
    open(path, "w", encoding="utf-8").write(json.dumps(tampered))
    obj1, _jb, _n = V.parse_published(verdict_bytes)
    findings1 = [{"id": f["id"], "severity": f["severity"], "title": f["title"]} for f in obj1["findings"]]
    tseg = D.dispositions_segment(doc["decisions"], findings1, base.sha256_bytes(base.read_bytes(path)))
    code, out, err, j = env.run("preflight", env.repo.request("r2", previous=env.repo.previous_round("r1"), remediation=tseg + "\n\nfixed", residuals=residuals))
    e.check(code == 1 and j["failure_code"] == "decisions-mismatch" and "rule 5" in err, "verdict_sha256 not equal to the previous verdict → decisions-mismatch (rule 5): %s" % j)
    open(path, "w", encoding="utf-8").write(json.dumps(dict(doc, decisions=doc["decisions"][:2])))
    code, out, err, j = env.run("preflight", req2)
    e.check(code == 1 and j["failure_code"] == "decisions-invalid", "decisions file with a missing finding → decisions-invalid at preflight: %s" % j)
    open(path, "w", encoding="utf-8").write("{not json")
    code, out, err, j = env.run("preflight", req2)
    e.check(code == 1 and j["failure_code"] == "decisions-invalid", "unparseable decisions file → decisions-invalid: %s" % j)
    os.unlink(path)
    code, out, err, j = env.run("preflight", req2)
    e.check(code == 1 and j["failure_code"] == "decisions-missing" and "respond" in err, "absent decisions file → decisions-missing: %s" % j)
    # 重新 respond 恢复决定文件（其丢失只使 r2 无法送审，不影响已发布证据）→ r2 review：任务书含决定摘要、Receipt 记 decisions_sha256
    code, j, err = env.respond("r1", good)
    e.check(code == 0 and j["next_round"]["remediation_statement"] != seg and j["next_round"]["remediation_statement"].split("\n")[1:] == seg.split("\n")[1:],
            "respond again: same dispositions, new decided_at hence a new sha prefix in the heading")
    dsha = j["decisions_sha256"]
    seg = j["next_round"]["remediation_statement"]
    req2 = env.repo.request("r2", previous=env.repo.previous_round("r1"), remediation=seg + "\n\nfixed as instructed", residuals=residuals)
    env.control(behavior="valid", verdict="PASS")
    code, out, err, j = env.run("review", req2)
    e.check(code == 0, "r2 review: %s" % err[-300:])
    r2 = json.loads(base.read_bytes(env.repo.path(env.repo.tracked_dir("r2") + "/receipt-r2.json")))
    task2 = base.read_bytes(env.repo.path(env.repo.tracked_dir("r2") + "/HarnessPlane_Demo_Review_Task_R2.md")).decode()
    obj2, _jb, _n = V.parse_published(base.read_bytes(env.repo.path(env.repo.tracked_dir("r2") + "/HarnessPlane_Demo_Review_R2.md")))
    e.check(r2["decisions_sha256"] == dsha and "### 上一轮决定摘要" in task2 and "- `R1-N1` · non_blocking · extra 1 → skip · repo:KB-09" in task2
            and "- `R1-B1` · blocking · problem one → fix · rewrite section 2" in task2 and "改第二节" not in task2 and seg in task2
            and obj2["accepted_residuals_acknowledged"] == ["RES-1", "RES-2"], "r2 evidence: decisions_sha256, decision summary (owner_verbatim stays out), residual set")
    e.check(env.run("preflight", env.repo.request("r1", name="again.json"))[0] == 1, "r1 is unaffected by decision files (refused only by round-not-increasing)")


def r1_changed_region(e):
    """S28 / V7（Amendment 4，F5 甲）：r1 任务书第 3 节「改动区（通道算）」——现行冻结事实在案时基线 SHA-256 等于其 objects[].sha256、差异块 ≥ 1；
    首冻（无冻结事实）声明整件为改动区；`.md` 记录取 frozen_objects[].sha256；雏形记录身份不可得；在案而字节不可恢复 → baseline-unrecoverable。"""
    env = Env(e, {"behavior": "valid", "verdict": "PASS"})
    design = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    frozen = env.repo.read(design)
    fsha = base.sha256_bytes(frozen)
    env.repo.write(design, frozen.decode() + "\nAmended line.\n")
    code, out, err, j = env.run("preflight", env.repo.request("r1"))
    e.check(code == 0 and j["changed_region"] == [{"bundle_name": "HarnessPlane_Demo_Design_v1.md", "baseline": None, "hunks": None, "note": None}],
            "no freeze fact anywhere → first freeze, whole file is the changed region: %s" % j.get("changed_region"))
    env.repo.write("records/governance/demo/freeze-records.jsonl",
                   json.dumps({"revision": 3, "event": "re-freeze", "objects": [{"path": design, "bytes": len(frozen), "sha256": fsha}]}) + "\n")
    code, out, err, j = env.run("preflight", env.repo.request("r1"))
    e.check(code == 0 and j["changed_region"][0]["baseline"] == {"revision": 3, "sha256": fsha} and j["changed_region"][0]["hunks"] == 1,
            "jsonl freeze fact: baseline identity and one hunk: %s" % j.get("changed_region"))
    code, out, err, j = env.run("review", env.repo.request("r1"))
    task = base.read_bytes(env.repo.path(env.repo.tracked_dir("r1") + "/HarnessPlane_Demo_Review_Task_R1.md")).decode()
    sec3 = task.split("## 3. 改动区、整改声明与决定摘要")[1].split("## 4.")[0]
    e.check(code == 0 and "### 改动区（通道算）" in sec3 and ("现行冻结事实 r3 · SHA-256 `%s`" % fsha) in sec3 and "insert: baseline lines" in sec3
            and "previous--" not in task and "整改声明" not in sec3, "r1 task book: changed region with the frozen baseline, no previous-- family: %s" % sec3)
    # .md 记录（fenced JSON frozen_objects[]）与雏形记录
    env2 = Env(e, {"behavior": "valid", "verdict": "PASS"})
    env2.repo.write("records/governance/demo/HarnessPlane_Demo_Freeze_Record_r2.md",
                    "# r2\n\n```freeze-record\n%s\n```\n" % json.dumps({"revision": 2, "frozen_objects": [{"path": design, "sha256": fsha}]}))
    env2.repo.write(design, frozen.decode() + "\nAnother line.\n")
    code, out, err, j = env2.run("preflight", env2.repo.request("r1"))
    e.check(code == 0 and j["changed_region"][0]["baseline"] == {"revision": 2, "sha256": fsha} and j["changed_region"][0]["hunks"] == 1,
            ".md record with a machine master: baseline from frozen_objects[]: %s" % j.get("changed_region"))
    env2.repo.write("records/governance/demo/HarnessPlane_Demo_Freeze_Record_r3.md", "# r3 prototype record without a fenced block\n")
    code, out, err, j = env2.run("preflight", env2.repo.request("r1"))
    e.check(code == 0 and j["changed_region"][0]["baseline"] is None and "r3" in j["changed_region"][0]["note"],
            "prototype record: identity unobtainable, whole file is the changed region, no failure code: %s" % j.get("changed_region"))
    # 在案而字节不可恢复
    env2.repo.write("records/governance/demo/freeze-records.jsonl",
                    json.dumps({"revision": 9, "event": "freeze", "objects": [{"path": design, "bytes": 1, "sha256": "c" * 64}]}) + "\n")
    code, out, err, j = env2.run("preflight", env2.repo.request("r1"))
    e.check(code == 1 and j["failure_code"] == "baseline-unrecoverable", "identity on record but bytes unrecoverable → baseline-unrecoverable: %s" % j)


def cases():
    return [
        ("channel.validation-reemit", validation_reemit),
        ("channel.multi-candidate", multi_candidate),
        ("channel.probe-preflight", probe_and_preflight),
        ("channel.review-paths", review_paths),
        ("channel.reemission", reemission),
        ("channel.failures-classification", failures_and_classification),
        ("channel.unrouteable-startup", unrouteable_and_startup),
        ("channel.concurrency-occupied", concurrency_and_occupied),
        ("channel.crash-recovery", crash_recovery),
        ("channel.derivation-static", derivation_static),
        ("channel.two-round-cap", two_round_cap),
        ("channel.unchanged-region", unchanged_region),
        ("channel.five-questions", five_questions),
        ("channel.respond-decisions", respond_decisions),
        ("channel.r1-changed-region", r1_changed_region),
    ]
