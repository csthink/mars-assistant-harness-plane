"""自测声明：review_channel_selection（第 10 类资格、第 11 类选择与继承、第 12 类轮次额度、review-skip 缺口）。"""
import os

import review_channel_base as base
import review_channel_contract as C
import review_channel_receipt as RC
import review_channel_registry as G
import review_channel_runtime as RT
import review_channel_selection as SL


def eligibility(e):
    SL.check_eligibility(["Anthropic"], False, "DeepSeek")
    SL.check_eligibility([], True, "DeepSeek")
    for vendors, human, reviewer, why in ((["DeepSeek"], False, "DeepSeek", "same vendor"), ([], False, "DeepSeek", "empty set"),
                                           (["unknown"], False, "DeepSeek", "unknown"), ([""], False, "DeepSeek", "empty string"),
                                           (["Anthropic"], True, "DeepSeek", "human_only with vendors"),
                                           (["Anthropic", "OpenAI"], False, "OpenAI", "mixed authors contain reviewer")):
        e.expect_error(lambda v=vendors, h=human, r=reviewer: SL.check_eligibility(v, h, r), code="eligibility", message=why)
    e.expect_error(lambda: SL.check_eligibility(["Anthropic"], False, "deepseek"), code="vendor-not-registered", message="reviewer vendor case")
    SL.check_eligibility(["Anthropic", "OpenAI"], False, "DeepSeek")


def _reg(e):
    d = e.fake_adapters(names=("fake", "fakeinline"))
    return G.load_registry(e.fake_registry(), adapter_loader=lambda rid: RT.load_adapter(rid, d), verify_evidence=False)


def _req(**kw):
    r = {"profile": None, "effort": None, "runtime_overrides": None, "max_rounds": None, "round_extensions": [], "round_index": 1}
    r.update(kw)
    return r


def selection_levels(e):
    reg = _reg(e)
    s = SL.select(_req(), reg, None, RC.profile_shape_problems)
    e.check((s["provider_id"], s["model_slug"], s["effort"], s["selection_source"], s["effort_source"]) ==
            ("fake-official", "fake-model", "high", "system-default", "registry-default"), "r1 system default")
    s = SL.select(_req(profile={"provider": "fake-official", "model": "fake-openai"}, effort="high"), reg, None, RC.profile_shape_problems)
    e.check(s["selection_source"] == "explicit-request" and s["effort_source"] == "explicit-request", "explicit request")
    e.expect_error(lambda: SL.select(_req(profile={"provider": "fake-official", "model": "ghost"}), reg, None, RC.profile_shape_problems),
                   code="profile-unknown", message="explicit unknown: no fallback to default")
    e.expect_error(lambda: SL.select(_req(effort="medium"), reg, None, RC.profile_shape_problems), code="effort-unsupported", message="effort unsupported")
    from review_channel_selftest_receipt import valid_profile, call_record
    prof = valid_profile([call_record(1, effort="low", effort_source="explicit-request")],
                         {"verdict_path": "v", "verdict_sha256": "0" * 64}, overrides={"request_max_retries": 0}, overrides_source="explicit-request")
    previous = {"receipt": {"effective_profile": prof, "runtime": {"adapter": "fake"}}}
    s = SL.select(_req(round_index=2), reg, previous, RC.profile_shape_problems)
    e.check(s["selection_source"] == "inherited-snapshot" and s["effort"] == "low" and s["effort_source"] == "inherited-snapshot"
            and s["overrides"] == {"request_max_retries": 0} and s["overrides_source"] == "inherited-snapshot" and s["changed_from_previous"] is False,
            "inherit full snapshot")
    empty_prev = {"receipt": {"effective_profile": dict(prof, runtime_overrides={}, overrides_source="none"), "runtime": {"adapter": "fake"}}}
    s = SL.select(_req(round_index=2), reg, empty_prev, RC.profile_shape_problems)
    e.check(s["overrides"] == {} and s["overrides_source"] == "inherited-snapshot", "silent inheritance of an empty snapshot keeps its provenance (R5-B8)")
    s = SL.select(_req(round_index=2, runtime_overrides={}), reg, previous, RC.profile_shape_problems)
    e.check(s["overrides"] == {} and s["overrides_source"] == "explicit-request", "explicit empty object clears inherited overrides (R5-B2)")
    s = SL.select(_req(round_index=2, profile={"provider": "fake-aggregator", "model": "agg-model"}, runtime_overrides={"a": 1}), reg, previous, RC.profile_shape_problems)
    e.check(s["changed_from_previous"] is True and s["previous_pair"] == {"provider": "fake-official", "model": "fake-model"}
            and s["overrides"] == {"a": 1} and s["overrides_source"] == "explicit-request", "explicit change records the difference")
    drift = dict(prof, transport="chat")
    e.expect_error(lambda: SL.select(_req(round_index=2), reg, {"receipt": {"effective_profile": drift}}, RC.profile_shape_problems),
                   code="inherit-unmaterializable", message="registry drift: transport")
    drift = dict(prof, provider_key_env="OTHER_KEY")
    e.expect_error(lambda: SL.select(_req(round_index=2), reg, {"receipt": {"effective_profile": drift}}, RC.profile_shape_problems),
                   code="inherit-unmaterializable", message="registry drift: key env rotation")
    nulleff = dict(prof, effective_effort=None)
    e.expect_error(lambda: SL.select(_req(round_index=2), reg, {"receipt": {"effective_profile": nulleff}}, RC.profile_shape_problems),
                   code="inherit-unanchored", message="null attempt-level effort is unanchored")
    e.expect_error(lambda: SL.select(_req(round_index=2), reg, {"receipt": {"effective_profile": {"profile_schema": "v2"}}}, RC.profile_shape_problems),
                   code="inherit-unanchored", message="profile schema mismatch")
    e.expect_error(lambda: SL.select(_req(round_index=2), reg, {"receipt": {"effective_profile": dict(prof, transport="smoke")}}, RC.profile_shape_problems),
                   code="inherit-unanchored", message="value-domain failure in the snapshot (R1-B7)")
    # 契约哈希不参与继承：设计哈希变化后旧快照仍可继承
    old_hash = dict(prof, contract_design_sha256="0" * 64, contract_version="older")
    s = SL.select(_req(round_index=2), reg, {"receipt": {"effective_profile": old_hash}}, RC.profile_shape_problems)
    e.check(s["selection_source"] == "inherited-snapshot", "contract hash does not gate inheritance")


def rounds_and_budget(e):
    repo = e.iso_repo()
    routing = {"axis": "task", "subject": "demo", "stage": "impl", "round": "r3", "round_index": 3, "task_record": "gov-t1",
               "tracked_parent": "tasks/gov-t1/reviews"}
    for k in (1, 2):
        repo.write("tasks/gov-t1/reviews/impl-r%d/receipt-r%d.json" % (k, k), "{}")
    repo.write("tasks/gov-t1/reviews/task-r1/receipt-r1.json", "{}")
    rounds = SL.scan_rounds(repo.root, routing["tracked_parent"], "task", "impl")
    e.check(sorted(rounds) == [1, 2] and rounds[2]["receipt"], "same stage rounds only")
    e.check(SL.check_round_sequence(repo.root, routing, rounds) == 2, "previous valid round")
    e.expect_error(lambda: SL.check_round_sequence(repo.root, dict(routing, round_index=2), rounds), code="round-not-increasing", message="not increasing")
    e.expect_error(lambda: SL.check_round_sequence(repo.root, dict(routing, round_index=4), rounds), code="round-gap-unexplained", message="gap")
    repo.write("tasks/gov-t1/rulings/RU-02-skip-r3.md", "> Ruling: RU-02\n> Date: 2026-09-02\n> Type: review-skip\n> Object: impl-r3 candidate x\n> Basis: b\n> Decision: skip\n")
    e.check(SL.check_round_sequence(repo.root, dict(routing, round_index=4), rounds) == 2, "gap covered by review-skip ruling")
    repo.write("tasks/gov-t1/rulings/RU-03-skip-r10.md", "> Ruling: RU-03\n> Date: 2026-09-02\n> Type: review-skip\n> Object: impl-r10 candidate x\n> Basis: b\n> Decision: skip\n")
    e.check(SL.review_skip_covers(repo.root, routing, 10) and not SL.review_skip_covers(repo.root, routing, 1), "whole-token match: r10 does not cover r1 (R2-B11)")
    # R3-B9：Type 精确相等、Object 右边界排除字母与短横线
    repo.write("tasks/gov-t1/rulings/RU-04-not-skip.md", "> Ruling: RU-04\n> Date: 2026-09-02\n> Type: not-review-skip\n> Object: impl-r5 candidate x\n> Basis: b\n> Decision: d\n")
    repo.write("tasks/gov-t1/rulings/RU-05-skip-r6x.md", "> Ruling: RU-05\n> Date: 2026-09-02\n> Type: review-skip\n> Object: impl-r6x candidate x\n> Basis: b\n> Decision: skip\n")
    repo.write("tasks/gov-t1/rulings/RU-06-skip-r7.md", "> Ruling: RU-06\n> Date: 2026-09-02\n> Type: review-skip \n> Object: r7-candidate x\n> Basis: b\n> Decision: skip\n")
    e.check(not SL.review_skip_covers(repo.root, routing, 5) and not SL.review_skip_covers(repo.root, routing, 6)
            and not SL.review_skip_covers(repo.root, routing, 7), "Type substring / Object suffix / hyphen suffix never claim a round (R3-B9)")
    defaults = {"max_rounds": 7}
    b = SL.round_budget({"max_rounds": None, "round_extensions": [], "round_index": 3}, defaults, rounds)
    e.check(b["max_rounds"] == 7 and b["source"] == "default" and b["submitted_rounds"] == 2 and not b["exhausted"], "default from registry")
    b = SL.round_budget({"max_rounds": 2, "round_extensions": [], "round_index": 3}, defaults, rounds)
    e.check(b["source"] == "request" and b["exhausted"], "request override exhausted")
    b = SL.round_budget({"max_rounds": 2, "round_extensions": [{"added_rounds": 1}], "round_index": 3}, defaults, rounds)
    e.check(b["allowed_rounds"] == 3 and not b["exhausted"], "extension lifts the budget")
    b = SL.round_budget({"max_rounds": 2, "round_extensions": [{"added_rounds": 1}], "round_index": 4}, defaults,
                        {**rounds, 3: {"dir": "x", "receipt": True}})
    e.check(b["exhausted"], "exhausted again after another submitted round")
    b = SL.round_budget({"max_rounds": 2, "round_extensions": [{"added_rounds": 1}, {"added_rounds": 1}], "round_index": 4}, defaults,
                        {**rounds, 3: {"dir": "x", "receipt": True}})
    e.check(not b["exhausted"] and b["extensions_added"] == 2, "second extension lifts again")
    # subject 轴
    os.makedirs(repo.path("reviews/demo/r1"))
    repo.write("reviews/demo/r1/receipt-r1.json", "{}")
    rounds_s = SL.scan_rounds(repo.root, "reviews/demo", "subject", "impl")
    e.check(sorted(rounds_s) == [1], "subject axis rounds")


def previous_anchoring(e):
    repo = e.iso_repo()
    routing = {"axis": "task", "subject": "demo", "stage": "impl", "round": "r2", "round_index": 2, "task_record": "gov-t1",
               "tracked_parent": "tasks/gov-t1/reviews"}
    d = "tasks/gov-t1/reviews/impl-r1"
    verdict = b"```review-channel-verdict\n{\"verdict\": \"PASS\"}\n```\n\nbody\n"
    msha = base.sha256_bytes(base.canonical_json([]))
    manifest = {"inputs": [], "manifest_sha256": msha}
    from review_channel_selftest_receipt import valid_profile
    receipt = {**RC.empty_receipt(), "receipt_schema": C.RECEIPT_SCHEMA, "attempt_id": "A", "classification": "completed_with_valid_verdict", "verdict_published": True,
               "attempt_outcome": "governed_verdict", "mode": "review", "receipt_phase": "completed", "subject": "demo", "stage": "impl", "round": "r1",
               "call_path_proof": "PROVEN", "profile_binding": "SUFFICIENT", "verdict_validation": "VALID",
               "verdict_sha256": base.sha256_bytes(verdict), "verdict_path": d + "/HarnessPlane_Demo_Review_R1.md",
               "input_manifest_sha256": msha, "effective_profile": valid_profile()}
    repo.write(d + "/HarnessPlane_Demo_Review_R1.md", verdict.decode())
    repo.write(d + "/bundle_manifest.json", base.pretty_json(manifest).decode())
    repo.write(d + "/receipt-r1.json", base.pretty_json(receipt).decode())
    req = {"previous_round": {"verdict_path": d + "/HarnessPlane_Demo_Review_R1.md", "receipt_path": d + "/receipt-r1.json"}}
    e.expect_error(lambda: SL.load_previous(repo.root, req, routing), code="inherit-unanchored", message="untracked previous round")
    repo.commit("r1")
    prev = SL.load_previous(repo.root, req, routing)
    e.check(prev["k"] == 1 and prev["manifest"] == manifest and prev["verdict_bytes"] == verdict, "anchored previous round")
    # R11-B1：清单自报摘要与 Receipt 相等但与 inputs 的 canonical 摘要不等 → 不得继承
    tampered = dict(manifest, inputs=[{"source": "x", "bundle_name": "x.md", "bytes": 1, "sha256": "0" * 64, "role": "candidate"}])
    repo.write(d + "/bundle_manifest.json", base.pretty_json(tampered).decode())
    e.expect_error(lambda: SL.load_previous(repo.root, req, routing), code="inherit-unanchored", message="manifest inputs tampered under a matching self-reported hash (R11-B1)")
    repo.write(d + "/bundle_manifest.json", base.pretty_json(manifest).decode())
    bad = dict(receipt, verdict_sha256="0" * 64)
    repo.write(d + "/receipt-r1.json", base.pretty_json(bad).decode())
    repo.commit("tamper")
    e.expect_error(lambda: SL.load_previous(repo.root, req, routing), code="inherit-unanchored", message="verdict hash mismatch")
    repo.write(d + "/receipt-r1.json", base.pretty_json(dict(receipt, classification="reviewer_output_invalid")).decode())
    repo.commit("invalid")
    e.expect_error(lambda: SL.load_previous(repo.root, req, routing), code="inherit-unanchored", message="not a governed verdict")
    repo.write(d + "/receipt-r1.json", base.pretty_json(dict(receipt, receipt_phase="called")).decode())
    repo.commit("phase")
    e.expect_error(lambda: SL.load_previous(repo.root, req, routing), code="inherit-unanchored", message="receipt_phase must be completed (R2-B7)")
    repo.write(d + "/receipt-r1.json", base.pretty_json(dict(receipt, profile_binding="INSUFFICIENT")).decode())
    repo.commit("dims")
    e.expect_error(lambda: SL.load_previous(repo.root, req, routing), code="inherit-unanchored", message="three dimensions must be the frozen success form (R2-B7)")
    e.expect_error(lambda: SL.load_previous(repo.root, {"previous_round": {"verdict_path": "x/v.md", "receipt_path": "x/receipt-r1.json"}}, routing),
                   code="inherit-unanchored", message="outside the tracked round dir")
    e.expect_error(lambda: SL.load_previous(repo.root, req, dict(routing, round_index=1)), code="inherit-unanchored", message="previous must precede")
    repo.write(d + "/receipt-r1.json", base.pretty_json(receipt).decode())
    repo.commit("restore")
    e.expect_error(lambda: SL.load_previous(repo.root, req, dict(routing, round_index=3), latest_submitted=2), code="inherit-unanchored",
                   message="previous_round must be the latest submitted round (R1-B7)")
    e.check(SL.load_previous(repo.root, req, routing, latest_submitted=1)["k"] == 1, "latest submitted round accepted")


def cases():
    return [
        ("selection.eligibility", eligibility),
        ("selection.levels-inheritance-drift", selection_levels),
        ("selection.rounds-budget", rounds_and_budget),
        ("selection.previous-anchoring", previous_anchoring),
    ]
