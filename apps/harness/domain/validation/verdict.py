"""Change review settlement: the one mapping from a channel outcome to the attempt, the node and the verdict.

Only a published valid impl-round verdict (verdict schema v4, stage impl, the five impl questions, the
round's candidate change document as the exact candidate, a Receipt that binds the verdict bytes) enters
the domain. It is recorded by EvidenceRef as a reviewer-verdict fact bound to the reviewed candidate commit
(D-03 §5), mapped to the seven minimal semantic classes of FR-24, and routed: PASS to the Publish
Authorization Gate, FAIL to the Validation budget node, after any `human` findings are disposed.

Everything else never becomes a Reviewer FAIL (milestones feature-t5, review channel r10 §6.7): Host cancel,
port failure, provider or authentication failure, timeout or transport failure, runtime refusal, invalid
output, preflight refusal (the channel's own round budget and the Policy refusals included), interruption,
material mismatch and a verdict that does not fit the round settle the attempt EXECUTION_FAILED; an
unknown result and the J-06 stop-unconfirmed projection settle it INDETERMINATE and keep the reservation.
Either way the node enters RECOVERY_REQUIRED and no budget is consumed (consumption exists only on a
Budget Remains progression, which only follows a business FAIL).
"""
import copy
from datetime import datetime, timezone

from domain.definition import review as definition_review
from domain.implement_verify import settlement as physical
from domain.validation import config, records
from domain.validation.results import EXECUTION_SETTLED, HUMAN_FINDINGS_PENDING, IDEMPOTENT_REPLAY, VERDICT_RECORDED
from domain.validation.review import QUESTIONS, STAGE
from domain.workflow import progression, reservations, states

VERDICT_DECISION = "N-VALIDATE-VERDICT-DECISION"
BUDGET_NODE = "N-VALIDATE-BUDGET-DECISION"
PURPOSE = "change-validation"
VALID = "completed_with_valid_verdict"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotAcceptable(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def accept(outcome, round_record):
    problems = []
    receipt = outcome.get("receipt") or {}
    block = outcome.get("verdict") or {}
    if outcome.get("classification") != VALID or receipt.get("classification") != VALID:
        problems.append("classification is not completed_with_valid_verdict")
    if receipt.get("verdict_validation") != "VALID" or receipt.get("verdict_published") is not True:
        problems.append("receipt does not record a published valid verdict")
    if block.get("verdict_schema") != definition_review.VERDICT_SCHEMA:
        problems.append("verdict schema is not " + definition_review.VERDICT_SCHEMA)
    if block.get("stage") != STAGE or block.get("round") != round_record["round"]:
        problems.append("verdict stage or round differs from the dispatched impl round")
    ids = [q.get("question_id") for q in block.get("question_assessments", []) if isinstance(q, dict)]
    if sorted(ids) != sorted(QUESTIONS) or len(ids) != len(set(ids)):
        problems.append("question set is not exactly the impl-round five questions")
    expected = round_record["document"]["sha256"]
    if (block.get("candidate") or {}).get("sha256") != expected or \
            [c.get("sha256") for c in block.get("candidates") or [] if isinstance(c, dict)] != [expected]:
        problems.append("verdict candidate identity differs from the round's candidate change document")
    if block.get("verdict") not in ("PASS", "FAIL"):
        problems.append("verdict value outside PASS / FAIL")
    if outcome.get("verdictSha256") is None or receipt.get("verdict_sha256") != outcome.get("verdictSha256"):
        problems.append("receipt verdict_sha256 does not bind the verdict bytes")
    if problems:
        raise NotAcceptable(problems)
    findings = [dict(id=f["id"], severity=f["severity"], title=f.get("title"), origin=f.get("origin"),
                     location=copy.deepcopy(f.get("location"))) for f in block.get("findings", []) if isinstance(f, dict)]
    return dict(verdict=block["verdict"], humanDecisionRequired=bool(block.get("human_decision_required")),
                findings=findings, humanFindings=[f["id"] for f in findings if f["severity"] == "human"],
                questionAssessments=copy.deepcopy(block.get("question_assessments")),
                scopeFilesRead=copy.deepcopy(block.get("scope_files_read")), verdictSha256=outcome["verdictSha256"],
                evidenceRef=copy.deepcopy(outcome.get("evidenceRef")), receiptRef=copy.deepcopy(outcome.get("receiptRef")),
                reviewer=copy.deepcopy({k: receipt.get(k) for k in ("reviewer", "effective_profile", "cross_vendor",
                                                                   "profile_binding") if k in receipt}))


def semantics(accepted, round_record, policy_refs):
    """FR-24's seven minimal semantic classes, each pointing at where it is actually recorded."""
    return {
        "Verdict": dict(value=accepted["verdict"], source="verdict.verdict"),
        "Review Scope & Basis": dict(stage=STAGE, round=round_record["round"], candidateCommit=round_record["candidateCommit"],
                                     baseCommit=round_record["baseCommit"], document=copy.deepcopy(round_record["document"]),
                                     references=copy.deepcopy(round_record["references"]),
                                     scopeFilesRead=copy.deepcopy(accepted["scopeFilesRead"]), source="round record, verdict"),
        "Goal Conditions Assessment": dict(questionAssessments=copy.deepcopy(accepted["questionAssessments"]),
                                           source="verdict.question_assessments (Q-CHANGE against the Goal Conditions)"),
        "Findings": dict(items=[f for f in accepted["findings"] if f["severity"] in ("blocking", "human")],
                         source="verdict.findings (blocking, human)"),
        "Non-blocking Recommendations": dict(items=[f for f in accepted["findings"] if f["severity"] == "non_blocking"],
                                             source="verdict.findings (non_blocking)"),
        "Validation Evidence": dict(verification=copy.deepcopy(round_record["verification"]),
                                    evidenceRef=copy.deepcopy(accepted["evidenceRef"]),
                                    receiptRef=copy.deepcopy(accepted["receiptRef"]),
                                    source="question evidence_refs, Verification Result, verdict and Receipt originals"),
        "Provenance": dict(reviewer=copy.deepcopy(accepted["reviewer"]), portId=round_record["portId"],
                           executionId=round_record["executionId"], policyDecisions=list(policy_refs),
                           authorExecutionRefs=list(round_record["authorExecutionRefs"]),
                           source="Receipt, execution request, review-release Policy Decision"),
    }


def _policy_refs(inst, round_record):
    return sorted(f["factId"] for f in inst["facts"].values()
                  if f.get("kind") == "policy-decision" and f.get("purpose") == "review-release"
                  and (f.get("payload") or {}).get("conclusion") == "ALLOW"
                  and (f.get("occurrence") or {}).get("node") == "N-VALIDATE-REVIEWER")


def _stop_unconfirmed(state, descriptor, outcome):
    projection = outcome.get("physicalExecution")
    if projection is None:
        projection = physical.latest(state.get("executionReservations", {}).get(descriptor["executionId"]))
    return physical.stop_unconfirmed(projection)


def route(state, topology, task_id, round_record, authority):
    """At Validation Review · Verdict = PASS?: stop for human findings, else take PASS (E-V04) or FAIL (E-V05)."""
    pending = [f for f in round_record["verdict"]["humanFindings"] if f not in round_record.get("disposed", [])]
    if pending:
        round_record["status"] = "awaiting-human-disposition"
        return dict(stopped=HUMAN_FINDINGS_PENDING, pending=pending)
    edge = "E-V04" if round_record["verdict"]["verdict"] == "PASS" else "E-V05"
    base = "route:%s" % round_record["executionId"]
    config.advance(state, topology, task_id, base + ":" + edge.lower(), edge, authority)
    if edge == "E-V04":
        config.await_human(state, topology, task_id, base, authority)
    round_record["status"] = "routed"
    return dict(edge=edge)


def settle(state, topology, descriptor, outcome):
    task_id = descriptor["taskId"]
    inst = progression.instance(state, task_id)
    record = records.ledger(state, task_id)
    round_record = next(r for r in record["rounds"] if r["executionId"] == descriptor["executionId"])
    if round_record["status"] not in ("dispatched", "running"):
        return dict(result=IDEMPOTENT_REPLAY, round=copy.deepcopy(round_record))
    authority = round_record["authorityRef"]
    base = "settle:" + descriptor["executionId"]
    evidence = dict(executionId=descriptor["executionId"], receiptRef=copy.deepcopy(outcome.get("receiptRef")),
                    classification=outcome.get("classification"), failureCode=outcome.get("failureCode"))
    accepted, reason = None, None
    if _stop_unconfirmed(state, descriptor, outcome):
        status, reason = "INDETERMINATE", dict(classification="unknown", failureCode="stop-unconfirmed")
    else:
        try:
            accepted = accept(outcome, round_record)
        except NotAcceptable as exc:
            status, reason = definition_review.failure_of(outcome)
            if outcome.get("classification") == VALID:
                status, reason = "EXECUTION_FAILED", dict(classification="verdict-not-acceptable", problems=exc.problems)
    if accepted is None:
        progression.settle_attempt(state, topology, task_id, dict(attemptId=round_record["attemptId"], status=status,
                                                                  evidence=dict(evidence, reason=reason), commandId=base),
                                   revision=state["revision"])
        if status == "EXECUTION_FAILED" and (outcome.get("receiptRef") or outcome.get("classification") == "preflight_failed"):
            # The execution fact that settles the reservation: the Receipt, or the refusal before any release.
            fact = outcome.get("receiptRef") or dict(kind="refused-before-release", executionId=descriptor["executionId"],
                                                     failureCode=outcome.get("failureCode"))
            reservations.settle(state, topology, task_id, dict(reservationId=round_record["reservationId"], settlement=dict(
                executionFact=fact, attemptId=round_record["attemptId"])), revision=state["revision"])
        if inst["condition"] != states.RECOVERY_REQUIRED:
            progression.update_condition(state, topology, task_id, dict(commandId=base + ":recovery",
                                                                        condition=states.RECOVERY_REQUIRED,
                                                                        authorityRef=authority), revision=state["revision"])
        round_record.update(status="execution-failed" if status == "EXECUTION_FAILED" else "indeterminate",
                            failure=dict(status=status, **reason), settledAt=now())
        return dict(result=EXECUTION_SETTLED, attempt=status, reason=reason, indeterminate=status == "INDETERMINATE",
                    position=inst["position"], condition=inst["condition"])
    progression.settle_attempt(state, topology, task_id, dict(attemptId=round_record["attemptId"], status="COMPLETED",
                                                              evidence=evidence, commandId=base), revision=state["revision"])
    reservations.settle(state, topology, task_id, dict(reservationId=round_record["reservationId"], settlement=dict(
        executionFact=outcome.get("receiptRef") or accepted["evidenceRef"], attemptId=round_record["attemptId"])),
                        revision=state["revision"])
    config.walk(state, topology, task_id, states.RESULT_RECORDED, base, authority)
    fact_id = base + ":verdict"
    seven = semantics(accepted, round_record, _policy_refs(inst, round_record))
    progression.record_fact(state, topology, task_id, dict(
        factId=fact_id, kind="reviewer-verdict", purpose=PURPOSE, authorityRef=authority,
        payload=dict(round=round_record["round"], candidateCommit=round_record["candidateCommit"],
                     document=copy.deepcopy(round_record["document"]), verdict=accepted["verdict"],
                     findings=copy.deepcopy(accepted["findings"]), evidenceRef=copy.deepcopy(accepted["evidenceRef"]),
                     receiptRef=copy.deepcopy(accepted["receiptRef"]), verdictSha256=accepted["verdictSha256"])),
        revision=state["revision"])
    config.advance(state, topology, task_id, base + ":e-v03", "E-V03", authority, [fact_id], PURPOSE)
    config.walk(state, topology, task_id, states.RESULT_RECORDED, base + ":decision", authority)
    round_record.update(verdict=accepted, verdictFact=fact_id, semantics=seven, published=copy.deepcopy(outcome.get("published")),
                        settledAt=now(), disposed=[])
    routed = route(state, topology, task_id, round_record, authority)
    return dict(result=VERDICT_RECORDED, verdict=accepted["verdict"], routed=routed, position=inst["position"],
                condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])
