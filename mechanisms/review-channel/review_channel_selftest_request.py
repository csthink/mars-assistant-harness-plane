"""自测声明：review_channel_request（第 1 类全封闭校验；第 10 类 vendors 闭集与 Human 项；最小可路由解析第 19 类）。"""
import copy
import json

import review_channel_base as base
import review_channel_contract as C
import review_channel_request as R


def good():
    return {"request_schema": C.REQUEST_SCHEMA, "subject": "demo", "stage": "impl", "round": "r1", "caller": "t",
            "task_record": "gov-t1",
            "artifact_author": {"human_only": False, "authors": [{"tool": "claude-code", "model": "m", "vendor": "Anthropic"}]},
            "inputs": {"candidates": ["a.md"], "references": ["b.md"]},
            "review_brief": {"background": "b", "check_surfaces": "c", "evidence_limits": [], "accepted_residuals": []},
            "invocation_authorization": "x:OD-01"}


def _rej(e, mutate, code="request-schema", message=""):
    obj = copy.deepcopy(good())
    mutate(obj)
    e.expect_error(lambda: R.validate_request(obj, "review"), code=code, message=message or code)


def total_closure(e):
    e.check(R.validate_request(good(), "review")["model_vendors"] == ["Anthropic"], "good request validates")
    e.expect_error(lambda: R.validate_request([], "review"), code="request-schema", message="top level non-object")
    _rej(e, lambda o: o.update(max_rounds=True), message="bool masquerading as integer")
    _rej(e, lambda o: o.update(max_rounds="3"), message="string as integer")
    _rej(e, lambda o: o.update(formal_review_authorized_by_owner="true"), message="string as authorization boolean")
    _rej(e, lambda o: o.update(round="impl-r1"), message="round grammar")
    _rej(e, lambda o: o.update(stage="design"), message="stage closed set")
    _rej(e, lambda o: o.update(profile={"provider": "p"}), message="profile half pair")
    _rej(e, lambda o: o.update(effort="ultra"), message="effort closed set")
    _rej(e, lambda o: o.update(unknown_member=1), message="unknown top-level member")
    _rej(e, lambda o: o.update(request_schema="review-channel-request/v1"), message="schema id")
    # Amendment 4（F2 甲）：caller 自由题与 standard_questions 开关退出请求件（v4），在场即请求文法失败
    _rej(e, lambda o: o["review_brief"].update(questions=[{"id": "Q1", "text": "t"}]), message="review_brief.questions retired (v4)")
    _rej(e, lambda o: o.update(standard_questions=True), message="standard_questions retired (v4)")
    _rej(e, lambda o: o.update(request_schema="review-channel-request/v3"), message="v3 schema id refused")
    _rej(e, lambda o: o["review_brief"]["accepted_residuals"].extend([{"id": "RES-1", "text": "t"}, {"id": "RES-1", "text": "u"}]), message="duplicate residual id")
    _rej(e, lambda o: o["review_brief"]["accepted_residuals"].append({"id": "Q-1", "text": "t"}), message="residual id grammar")
    e.check("question_ids" not in R.validate_request(good(), "review") and "standard_questions" not in R.validate_request(good(), "review"),
            "normalized request carries no question ids and no standard-questions flag")
    _rej(e, lambda o: o["review_brief"].update(remediation_statement="x"), message="remediation forbidden in r1")
    _rej(e, lambda o: o["inputs"]["references"].append("a.md"), message="candidate repeated as reference")
    _rej(e, lambda o: o["inputs"]["candidates"].append("a.md"), message="candidate repeated in candidates")
    _rej(e, lambda o: o["inputs"].update(candidates=[]), message="empty candidates")
    # R33-B1：任务轴恰一件候选（task-artifact-schema §10.2）；subject 轴允许多件
    _rej(e, lambda o: (o.update(task_record="gov-t1"), o["inputs"].update(candidates=["a.md", "c.md"])), message="task axis with two candidates")
    ok = good(); ok["inputs"]["candidates"] = ["a.md", "c.md"]; ok.pop("task_record", None)
    e.check(R.validate_request(ok, "preflight")["inputs"]["candidates"] == ["a.md", "c.md"], "subject axis accepts two candidates")
    for bad in ("/etc/passwd", "../x.md", "a//b.md", "./a.md", "a/../b.md", "a\\b.md"):
        _rej(e, lambda o, b=bad: o["inputs"].update(candidates=[b]), message="path escape rejected: %s" % bad)
    _rej(e, lambda o: o["inputs"]["references"].append("../../secret"), message="reference path escape rejected")
    _rej(e, lambda o: o.update(previous_round={"verdict_path": "v", "receipt_path": "r"}), code="request-field-not-allowed",
         message="previous_round forbidden in r1 (S15 round constraint)")
    # Amendment 1：evidence_limits[].kind 闭集与缺省、reference 数组内唯一
    obj = good(); obj["review_brief"]["evidence_limits"] = [{"reference": "x.md", "reason": "r"}, {"reference": "apps/y.md", "reason": "p", "kind": "planned-location"}]
    lims = R.validate_request(obj, "review")["review_brief"]["evidence_limits"]
    e.check(lims[0]["kind"] == "exemption" and lims[1]["kind"] == "planned-location" and C.EVIDENCE_LIMIT_KINDS == ("exemption", "planned-location"),
            "kind defaults to exemption; declared values kept; the closed set is the two values")
    _rej(e, lambda o: o["review_brief"]["evidence_limits"].append({"reference": "apps/y.md", "reason": "", "kind": "planned-location"}),
         message="declaration with an empty reason")
    _rej(e, lambda o: o["review_brief"]["evidence_limits"].append({"reference": "x.md", "reason": "r", "kind": "planned"}), message="kind outside the closed set")
    _rej(e, lambda o: o["review_brief"]["evidence_limits"].append({"reference": "x.md", "reason": "r", "extra": 1}), message="unknown evidence_limits member")
    _rej(e, lambda o: o["review_brief"]["evidence_limits"].extend([{"reference": "x.md", "reason": "r", "kind": "planned-location"}, {"reference": "x.md", "reason": "s"}]),
         message="same reference declared twice (different kinds) is refused")
    _rej(e, lambda o: o["review_brief"]["evidence_limits"].extend([{"reference": "x.md", "reason": "r"}, {"reference": "x.md", "reason": "s"}]),
         message="same reference declared twice (same kind) is refused")
    _rej(e, lambda o: o.update(round_extensions=[{"authorized_by": "h", "at": "t", "added_rounds": 0, "note": ""}]),
         message="added_rounds positive")
    obj = good(); obj["round"] = "r2"
    e.expect_error(lambda: R.validate_request(obj, "review"), code="request-schema", message="r2 needs remediation + previous_round")
    obj["review_brief"]["remediation_statement"] = "fixed"
    obj["previous_round"] = {"verdict_path": "v.md", "receipt_path": "receipt-r1.json"}
    e.check(R.validate_request(obj, "review")["previous_round"]["verdict_path"] == "v.md", "r2 valid")
    obj = good(); del obj["invocation_authorization"]
    e.expect_error(lambda: R.validate_request(obj, "review"), code="invocation-authorization-required", message="review needs authorization")
    e.check(R.validate_request(obj, "preflight")["invocation_authorization"] is None, "preflight tolerates absent authorization")
    obj = good(); obj["formal_review_authorized_by_owner"] = True
    e.check(R.validate_request(obj, "review")["formal_review_authorized_by_owner"] is True, "literal true accepted")


def vendors(e):
    _rej(e, lambda o: o["artifact_author"]["authors"][0].update(vendor="anthropic"), code="vendor-not-registered",
         message="case variant rejected")
    _rej(e, lambda o: o["artifact_author"]["authors"][0].update(vendor="Mistral"), code="vendor-not-registered", message="outside table")
    obj = good()
    obj["artifact_author"] = {"human_only": True, "authors": [{"tool": "human", "model": "human", "vendor": "human"}]}
    e.check(R.validate_request(obj, "review")["model_vendors"] == [], "Human entry keeps the derived set empty")
    _rej(e, lambda o: o["artifact_author"].update(human_only=True), message="human_only with a model author")
    _rej(e, lambda o: o["artifact_author"]["authors"].append({"tool": "human", "model": "gpt", "vendor": "OpenAI"}),
         message="tool=human with model vendor")
    _rej(e, lambda o: o["artifact_author"]["authors"].append({"tool": "codex-cli", "model": "m", "vendor": "human"}),
         message="model tool with vendor=human")
    obj = good()
    obj["artifact_author"]["authors"].append({"tool": "human", "model": "human", "vendor": "human"})
    obj["artifact_author"]["authors"].append({"tool": "codex-cli", "model": "m", "vendor": "OpenAI"})
    e.check(R.validate_request(obj, "review")["model_vendors"] == ["Anthropic", "OpenAI"], "mixed authors derive model vendors only")
    _rej(e, lambda o: o["artifact_author"].update(authors=[]), message="empty authors")


def minimal_route(e):
    raw = json.dumps(good()).encode()
    r = R.minimal_route(raw)
    e.check(r["subject"] == "demo" and r["task_record"] == "gov-t1" and r["round"] == "r1", "route fields")
    for bad, why in ((b"{", "unparseable"), (b"[]", "non-object"), (json.dumps(dict(good(), round="r01")).encode(), "round"),
                     (json.dumps(dict(good(), stage="x")).encode(), "stage"),
                     (json.dumps(dict(good(), task_record="gov-t01")).encode(), "task_record grammar"),
                     (json.dumps({k: v for k, v in good().items() if k != "subject"}).encode(), "subject missing")):
        e.expect_error(lambda b=bad: R.minimal_route(b), exc_type=base.UnrouteableError, message="unrouteable: " + why)
    for record in ("feature-t0", "design-t0", "gov-t0"):
        e.check(R.minimal_route(json.dumps(dict(good(), task_record=record)).encode())["task_record"] == record,
                "task_record %s routes on the task axis" % record)
    e.expect_error(lambda: R.minimal_route(json.dumps(dict(good(), task_record="feature-t00")).encode()),
                   exc_type=base.UnrouteableError, message="unrouteable: padded t00")
    obj = good(); del obj["task_record"]
    e.check(R.minimal_route(json.dumps(obj).encode())["task_record"] is None, "subject axis when task_record absent")
    obj = good(); obj["caller"] = 5  # 完整校验失败但仍可路由
    e.check(R.minimal_route(json.dumps(obj).encode())["subject"] == "demo", "routable despite full-validation failure")


def cases():
    return [
        ("request.total-closure", total_closure),
        ("request.vendors", vendors),
        ("request.minimal-route", minimal_route),
    ]
