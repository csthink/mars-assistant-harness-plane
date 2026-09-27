"""自测声明：review_channel_decisions（§6.12 决定文件：五条校验规则各一负例、输入形状、处置段与派生残留项的固定文法、r<N+1> 请求件核对）。"""
import copy

import review_channel_contract as C
import review_channel_decisions as D

FINDINGS = [{"id": "R1-B1", "severity": "blocking", "title": "problem one"},
            {"id": "R1-H1", "severity": "human", "title": "needs a ruling"},
            {"id": "R1-N1", "severity": "non_blocking", "title": "note"}]
GOOD = [{"finding_id": "R1-B1", "action": "fix", "instructions": "rewrite", "owner_verbatim": "改"},
        {"finding_id": "R1-N1", "action": "skip", "work_item": "repo:KB-09", "owner_verbatim": "下次"},
        {"finding_id": "R1-H1", "action": "approve", "owner_verbatim": "同意"}]
ROUTING = {"subject": "demo", "stage": "impl", "round": "r1", "task_record": "gov-t1"}


def _neg(e, label, mutate, needle):
    d = copy.deepcopy(GOOD)
    mutate(d)
    p = D.decision_problems(d, FINDINGS)
    e.check(p and any(needle in x for x in p), "%s → problem containing %r: %s" % (label, needle, p))


def rules(e):
    e.check(D.decision_problems(GOOD, FINDINGS) == [], "valid decisions: %s" % D.decision_problems(GOOD, FINDINGS))
    e.check(D.decision_problems([], []) == [], "a verdict without findings takes an empty decision list")
    e.check(D.decision_problems("x", FINDINGS) == ["decisions must be an array"] and D.decision_problems([5], FINDINGS), "total closure on shape")
    _neg(e, "rule 1 missing finding", lambda d: d.pop(), "rule 1")
    _neg(e, "rule 1 unknown finding", lambda d: d.append({"finding_id": "R1-B9", "action": "approve", "owner_verbatim": "x"}), "rule 1")
    _neg(e, "rule 1 duplicate", lambda d: d.append(dict(d[2])), "rule 1: duplicate")
    _neg(e, "rule 2 action closed set", lambda d: d[2].update(action="defer"), "rule 2")
    _neg(e, "rule 2 fix needs instructions", lambda d: d[0].pop("instructions"), "rule 2")
    _neg(e, "rule 3 blocking skip needs work_item", lambda d: d[0].update(action="skip"), "rule 3")
    _neg(e, "rule 3 work_item grammar", lambda d: d[1].update(work_item="KB-09"), "rule 3")
    _neg(e, "work_item only on skip", lambda d: d[2].update(work_item="repo:KB-01"), "only meaningful for action skip")
    _neg(e, "rule 4 owner_verbatim", lambda d: d[2].update(owner_verbatim=""), "rule 4")
    _neg(e, "unknown member", lambda d: d[2].update(note="x"), "unknown member")
    _neg(e, "missing member", lambda d: d[2].pop("owner_verbatim"), "missing")
    ok = copy.deepcopy(GOOD)
    ok[1].pop("work_item")
    e.check(D.decision_problems(ok, FINDINGS) == [], "non-blocking skip may omit work_item")
    ok = copy.deepcopy(GOOD)
    ok[2]["instructions"] = ""
    e.check(D.decision_problems(ok, FINDINGS) == [], "approve may carry empty instructions")
    # 输入形状：verdict_sha256 / decided_at 由通道填写、在场即拒；decisions_schema 在场须等于常量
    base_in = {"subject": "demo", "stage": "impl", "round": "r1", "task_record": "gov-t1", "decisions": GOOD}
    e.check(D.input_problems(base_in) == [] and D.input_problems(dict(base_in, decisions_schema=C.DECISIONS_SCHEMA)) == [], "valid input")
    for label, obj in (("verdict_sha256 present", dict(base_in, verdict_sha256="0" * 64)), ("decided_at present", dict(base_in, decided_at="t")),
                       ("unknown member", dict(base_in, extra=1)), ("bad subject", dict(base_in, subject="Demo")), ("bad stage", dict(base_in, stage="design")),
                       ("bad round", dict(base_in, round="1")), ("bad task_record", dict(base_in, task_record="t1")), ("decisions not a list", dict(base_in, decisions={})),
                       ("wrong schema id", dict(base_in, decisions_schema="review-channel-decisions/v0")), ("not an object", [])):
        e.check(D.input_problems(obj), "input negative: %s" % label)
    # 决定文件（已写入形态）：封闭对象、身份、规则其五
    doc = D.build_document(ROUTING, "a" * 64, GOOD)
    e.check(set(doc) == set(C.DECISIONS_FIELDS) and doc["decisions_schema"] == C.DECISIONS_SCHEMA and doc["decided_at"], "document members closed")
    e.check(D.document_problems(doc, FINDINGS, "a" * 64, ROUTING) == [] and D.document_problems(doc, FINDINGS, None, ROUTING) == [], "valid document (rule 5 checked or skipped)")
    e.check(any("rule 5" in x for x in D.document_problems(doc, FINDINGS, "b" * 64, ROUTING)), "rule 5 verdict_sha256 binding")
    e.check(D.document_problems(dict(doc, round="r2"), FINDINGS, "a" * 64, ROUTING) and D.document_problems(dict(doc, extra=1), FINDINGS, "a" * 64, ROUTING)
            and D.document_problems({k: v for k, v in doc.items() if k != "decided_at"}, FINDINGS, "a" * 64, ROUTING)
            and D.document_problems(dict(doc, verdict_sha256="zz"), FINDINGS, None, ROUTING) and D.document_problems("x", FINDINGS, None, ROUTING),
            "document negatives: identity, unknown / missing member, sha grammar, shape")


def derivation(e):
    sha = "f" * 64
    seg = D.dispositions_segment(GOOD, FINDINGS, sha)
    e.check(seg == "Dispositions (decisions.json sha256 ffffffffffff)\n- R1-B1: fix · rewrite\n- R1-H1: approve\n- R1-N1: skip · repo:KB-09",
            "dispositions segment: heading with the 12-char prefix, verdict finding order, fix instructions and skip work_item: %r" % seg)
    ns = copy.deepcopy(GOOD)
    ns[1].pop("work_item")
    e.check(D.dispositions_segment(ns, FINDINGS, sha).split("\n")[3] == "- R1-N1: skip", "skip without work_item renders the action only")
    e.check(D.derived_residuals(GOOD, FINDINGS) == [{"id": "RES-1", "text": "note · repo:KB-09"}] and D.derived_residuals(ns, FINDINGS) == [{"id": "RES-1", "text": "note"}],
            "derived residuals: RES-<n> from 1, text = title · work_item (or title)")
    two = copy.deepcopy(GOOD)
    two[0].update(action="skip", work_item="repo:OD-10")
    two[0].pop("instructions")
    e.check(D.derived_residuals(two, FINDINGS) == [{"id": "RES-1", "text": "problem one · repo:OD-10"}, {"id": "RES-2", "text": "note · repo:KB-09"}],
            "two skips numbered consecutively in verdict order")
    brief = {"remediation_statement": seg + "\n\nfixed", "accepted_residuals": [{"id": "RES-1", "text": "note · repo:KB-09"}, {"id": "RES-2", "text": "own"}]}
    e.check(D.request_mismatches(brief, GOOD, FINDINGS, sha) == [], "brief starting with the segment and carrying the derived residual matches")
    e.check(D.request_mismatches(dict(brief, remediation_statement="fixed\n" + seg), GOOD, FINDINGS, sha), "segment not at the start → mismatch")
    e.check(D.request_mismatches(dict(brief, remediation_statement=seg.replace("ffffffffffff", "000000000000") + "\n\nfixed"), GOOD, FINDINGS, sha), "stale sha prefix → mismatch")
    e.check(D.request_mismatches(dict(brief, accepted_residuals=[{"id": "RES-1", "text": "note"}]), GOOD, FINDINGS, sha), "derived residual text differs → mismatch")
    e.check(D.request_mismatches(dict(brief, accepted_residuals=[{"id": "RES-2", "text": "own"}, {"id": "RES-1", "text": "note · repo:KB-09"}]), GOOD, FINDINGS, sha),
            "derived residuals must come first → mismatch")
    e.check(D.request_mismatches({"remediation_statement": None, "accepted_residuals": []}, GOOD, FINDINGS, sha), "empty brief → mismatch")
    rows = D.summary_rows(GOOD, FINDINGS)
    e.check(rows == [("R1-B1", "blocking", "problem one", "fix", "rewrite", ""), ("R1-H1", "human", "needs a ruling", "approve", "", ""),
                     ("R1-N1", "non_blocking", "note", "skip", "", "repo:KB-09")], "task book summary rows in verdict order: %s" % rows)


def cases():
    return [
        ("decisions.rules", rules),
        ("decisions.derivation", derivation),
    ]
