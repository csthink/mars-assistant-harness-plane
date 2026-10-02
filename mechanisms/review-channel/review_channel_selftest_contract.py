"""自测声明：review_channel_contract（状态转换表四行、三维聚合、归约、vendors 闭集、题号集合）。"""
import review_channel_contract as C


def transition_table(e):
    e.check(C.capability_transition("PROVEN", "SUFFICIENT", "VALID") == ("governed_verdict", "REVIEW_ENABLED"), "row 1")
    e.check(C.capability_transition("PROVEN", "SUFFICIENT", "INVALID") == ("receipt_only", "PROBED"), "row 2 INVALID")
    e.check(C.capability_transition("PROVEN", "SUFFICIENT", "NOT_REACHED") == ("receipt_only", "PROBED"), "row 2 NOT_REACHED")
    for cpp in ("NOT_PROVEN", "INDETERMINATE"):
        e.check(C.capability_transition(cpp, "SUFFICIENT", "VALID") == ("receipt_only", "no-higher-than-UNVERIFIED"), "row 3")
    for pb in ("MISMATCH", "INSUFFICIENT"):
        e.check(C.capability_transition("PROVEN", pb, "VALID") == ("receipt_only", "requested-profile-not-PROBED-or-ENABLED"), "row 4")
    e.expect_error(lambda: C.capability_transition("PROVEN", "SUFFICIENT", "WEIRD"), exc_type=ValueError, message="outside table")


def aggregation(e):
    e.check(C.aggregate_call_path(["PROVEN", "PROVEN"]) == "PROVEN", "all proven")
    e.check(C.aggregate_call_path(["PROVEN", "NOT_PROVEN"]) == "NOT_PROVEN", "any not proven")
    e.check(C.aggregate_call_path(["PROVEN", "INDETERMINATE"]) == "INDETERMINATE", "otherwise indeterminate")
    e.check(C.aggregate_call_path([]) == "INDETERMINATE", "empty is indeterminate")
    e.check(C.aggregate_profile_binding(["SUFFICIENT", "MISMATCH"]) == "MISMATCH", "mismatch dominates")
    e.check(C.aggregate_profile_binding(["INSUFFICIENT", "SUFFICIENT"]) == "INSUFFICIENT", "insufficient next")
    e.check(C.aggregate_profile_binding(["SUFFICIENT", "SUFFICIENT"]) == "SUFFICIENT", "all sufficient")
    e.check(C.reduce_single_valued([{"x": 1}, {"x": 1}], "x") == 1 and C.reduce_single_valued([{"x": 1}, {"x": 2}], "x") is None, "reduce")


def closed_sets(e):
    e.check(C.VENDORS == ("Anthropic", "OpenAI", "DeepSeek", "Zhipu"), "vendors closed set verbatim")
    e.check("anthropic" not in C.VENDORS and C.HUMAN not in C.VENDORS, "case variant and human outside")
    e.check(len(C.CLASSIFICATIONS) == 11 and "interrupted" in C.CLASSIFICATIONS, "classification closed set")
    # 五题闭集（§6.4，Amendment 4）：按 stage 两套、各恰五题、题号合文法、与旧 Q<n> / STD-<n> 不相交
    task_ids = C.required_question_ids("task")
    impl_ids = C.required_question_ids("impl")
    e.check(task_ids == ["Q-FIDELITY", "Q-GOAL", "Q-BOUNDARY", "Q-ACCEPT", "Q-EXEC"], "task round: FR-21 five dimensions verbatim: %s" % task_ids)
    e.check(impl_ids == ["Q-CHANGE", "Q-UPSTREAM", "Q-PREMISE", "Q-REFERENCE", "Q-BOUNDARY"], "impl round five questions: %s" % impl_ids)
    e.check(len(set(task_ids)) == 5 and len(set(impl_ids)) == 5 and set(C.QUESTIONS_BY_STAGE) == set(C.STAGES), "five distinct ids per stage; one set per stage")
    e.check(all(C.QUESTION_ID_RE.match(q) for q in task_ids + impl_ids) and not C.QUESTION_ID_RE.match("Q1") and not C.QUESTION_ID_RE.match("STD-1"),
            "question id grammar ^Q-[A-Z]+$ excludes the retired Q<n> / STD-<n> forms")
    e.check(all(text for _q, text in C.TASK_QUESTIONS + C.IMPL_QUESTIONS), "every question carries its text")
    e.expect_error(lambda: C.required_question_ids("design"), exc_type=KeyError, message="stage outside the closed set has no question set")
    e.check(C.ASSESSMENT_FIELDS == ("question_id", "assessment", "evidence_refs", "finding_ids"), "assessment members: four (the two assertion members retired)")
    e.check(C.NON_BLOCKING_ORIGINS == ("unchanged_region",) and set(C.NON_BLOCKING_ORIGINS) < set(C.ORIGINS), "rule 14 origins are a strict subset of ORIGINS")
    e.check(C.REQUEST_SCHEMA == "review-channel-request/v4" and C.VERDICT_SCHEMA == "review-channel-verdict/v4" and C.RECEIPT_SCHEMA == "review-channel-receipt/v4"
            and C.DECISIONS_SCHEMA == "review-channel-decisions/v1", "schema ids: request / verdict v4, receipt v4, decisions v1")
    e.check(C.DECISION_ACTIONS == ("approve", "fix", "skip") and C.WORK_ITEM_RE.match("repo-od-10:KB-08") and not C.WORK_ITEM_RE.match("KB-08")
            and {"decisions-missing", "decisions-invalid", "decisions-mismatch"} <= set(C.FAILURE_CODES), "decision constants and failure codes")
    e.check(C.NARRATIVE_QUESTION_LINE_RE.match("- Q-CHANGE: SATISFIED") and not C.NARRATIVE_QUESTION_LINE_RE.match("- Q-CHANGE: SATISFIED · extra: true"),
            "narrative question line carries the assessment only")
    e.check(all(code in C.STATIC_FAILURE_MESSAGES for code in C.FAILURE_CODES), "static message per failure code")
    m = C.FINDING_ID_RE.match("R12-H3")
    e.check(m and m.groups() == ("R12", "H", "3"), "finding id grammar")
    e.check(not C.FINDING_ID_RE.match("R1-X1") and not C.FINDING_ID_RE.match("r1-B1"), "finding id negatives")
    e.check(C.TASK_RECORD_RE.match("gov-t8") and C.TASK_RECORD_RE.match("feature-t12") and not C.TASK_RECORD_RE.match("gov-t08"), "task id grammar")
    # task.template.md 页首引导块：N 自 0 起、不补零；TASK_ID_RE 与 TASK_RECORD_RE 同一模式（hotfix 只属于后者）
    zero = ("feature-t0", "design-t0", "gov-t0")
    e.check(all(C.TASK_ID_RE.match(t) and C.TASK_RECORD_RE.match(t) for t in zero), "task id grammar starts at t0")
    e.check(not any(C.TASK_ID_RE.match(t) or C.TASK_RECORD_RE.match(t) for t in ("feature-t00", "gov-t01", "feature-t", "task-t1")),
            "task id grammar refuses padded, empty and unknown forms")
    hotfix = "hotfix-h" + "a" * 64
    e.check(C.TASK_RECORD_RE.match(hotfix) and not C.TASK_ID_RE.match(hotfix), "hotfix is a task record, not a milestones task id")


def cases():
    return [
        ("contract.transition-table", transition_table),
        ("contract.aggregation", aggregation),
        ("contract.closed-sets", closed_sets),
    ]
