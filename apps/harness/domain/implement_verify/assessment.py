"""Recovery assessments for the Implementer and Verify nodes (D-05 §4, §5; spec FR-30, FR-60).

feature-t2 owns the assessment record, its freshness and single consumption, the assessment-to-action
mapping and the Human single-use authorization (recovery.assess / recovery.recover). This module is
only the producer of the evidence-based result for the two nodes feature-t4 drives:

- RESULT_CONFIRMED: the Implementer port holds a completed result, the bound worktree carries a valid
  candidate (new commit, descends from the baseline, clean) and the vendor mapping is known. The
  formal result fact is recorded from the port's persisted result, not fabricated.
- RESTART_SAFE: the execution is proven terminal (failed, stopped, rejected before release, or never
  released) and the worktree equals the dispatch baseline (implement) or the candidate (verify). The
  Workflow reservation is released against that same terminal execution fact.
- RECONCILIATION_REQUIRED: the worktree moved away from the baseline or candidate (uncommitted work or
  a commit that is not a valid candidate): restarting could lose or duplicate that partial effect.
- INDETERMINATE: stop unconfirmed, physical state unknown, or an execution that was released but has
  no terminal fact. Nothing can override it; a session that disappeared is never counted complete.

Restart and effectful reconciliation still need the exact Human authorization that recovery.recover
checks; this module never performs a recovery action.
"""
import copy

from domain.workflow import recovery, states
from domain.implement_verify import seams, settlement, steps, worktree
from domain.implement_verify.implement import IMPLEMENT_NODE, candidate, port_record
from domain.implement_verify.results import ASSESSED, POSITION_NOT_APPLICABLE, ImplementVerifyRejection
from domain.implement_verify.verify import VERIFY_NODE

TERMINAL_KINDS = ("failed", "stopped")


def _current_execution(state, task_id, inst):
    records = [r for r in steps.ledger(state, task_id)["executions"].values()
               if r["occurrence"]["node"] == inst["position"]
               and r["occurrence"]["positionEntryRuntimeVersion"] == inst["positionEntryRevision"]]
    return max(records, key=lambda r: int(r["dispatchedRevision"])) if records else None


def _implement(state, task_id, inst):
    record = _current_execution(state, task_id, inst)
    if record is None:
        return "INDETERMINATE", dict(reason="no execution descriptor for this occurrence"), None
    port = port_record(state, record["executionRequestId"])
    verdict = settlement.classify(port, None)
    if record.get("settlement") and record["settlement"].get("kind") == "recovery":
        reason = record["settlement"]["reason"]
    else:
        reason = verdict["reason"]
    found = candidate(record)
    evidence = dict(executionRequestId=record["executionRequestId"], physical=verdict, settlementReason=reason,
                    worktree=found, baseline=record["baseline"])
    released = bool(port and port.get("start_dispatched"))
    if verdict["kind"] == "stop-unconfirmed":
        return "INDETERMINATE", evidence, record
    if verdict["kind"] == "completed":
        model = settlement.latest(port) or {}
        binding = (model.get("actualBinding") or {}).get("model")
        agent = (((port or {}).get("intent") or {}).get("executionBinding") or {}).get("agent")
        vendor = seams.vendor_of(state, agent, binding) if binding and agent else None
        evidence["modelVendor"] = vendor
        if found["kind"] == "candidate" and vendor is not None:
            return "RESULT_CONFIRMED", evidence, record
        if found["kind"] == "candidate":
            # A candidate exists but its vendor cannot be established: the result is not yet consumable.
            return "INDETERMINATE", evidence, record
        if found["kind"] in ("no-commit",) and found["current"]["statusDigest"] == record["baseline"]["statusDigest"]:
            return "RESTART_SAFE", evidence, record
        return "RECONCILIATION_REQUIRED", evidence, record
    physical_state = (settlement.latest(port) or {}).get("state")
    # Terminal: a failed or stopped execution, a completed execution whose result the port rejected, or an
    # execution that was never released. A released execution without a terminal fact stays unknown.
    terminal = (verdict["kind"] in TERMINAL_KINDS or physical_state in ("failed", "stopped", "completed")
                or (not released and record["status"] == "settled"))
    if not terminal:
        return "INDETERMINATE", evidence, record
    if worktree.compare(record["baseline"], found["current"]) == "unchanged":
        return "RESTART_SAFE", evidence, record
    return "RECONCILIATION_REQUIRED", evidence, record


def _verify(state, task_id, inst):
    records = [v for v in steps.ledger(state, task_id)["verifications"].values()
               if (v.get("occurrence") or {}).get("positionEntryRuntimeVersion") == inst["positionEntryRevision"]]
    if not records:
        return "INDETERMINATE", dict(reason="no verification for this occurrence"), None
    last = max(records, key=lambda v: int(v["recordedRevision"]))
    current = worktree.snapshot(worktree.bound(state["tasks"][task_id]))
    evidence = dict(verificationId=last["verificationId"], failure=copy.deepcopy(last.get("failure")), worktree=current)
    if last["status"] != "execution-failed":
        return "INDETERMINATE", evidence, None
    if current["head"] == last["candidateCommit"] and current["clean"]:
        return "RESTART_SAFE", evidence, None
    return "RECONCILIATION_REQUIRED", evidence, None


def assess(state, topology, task_id, payload, *, revision):
    inst = steps.inst(state, task_id)
    if inst["condition"] != states.RECOVERY_REQUIRED or inst["position"] not in (IMPLEMENT_NODE, VERIFY_NODE):
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "feature-t4 assesses only the Implementer and Verify "
                                       "nodes in RECOVERY_REQUIRED", position=inst["position"], condition=inst["condition"])
    authority = payload.get("authorityRef")
    assessment_id = payload.get("assessmentId")
    if inst["position"] == IMPLEMENT_NODE:
        result, evidence, record = _implement(state, task_id, inst)
    else:
        result, evidence, record = _verify(state, task_id, inst)
    extra = {}
    if record is not None and result == "RESULT_CONFIRMED":
        extra = _confirm(state, topology, task_id, record, evidence, authority, revision=revision)
    if record is not None and result == "RESTART_SAFE":
        extra = _release(state, topology, task_id, record, evidence, authority, revision=revision)
    outcome = recovery.assess(state, topology, task_id,
                              dict(assessmentId=assessment_id, assessment=result,
                                   checked=[dict(kind="implement-verify-evidence", node=inst["position"])],
                                   evidence=[copy.deepcopy(evidence)]), revision=revision)
    steps.ledger(state, task_id)["assessments"][assessment_id] = dict(assessmentId=assessment_id, result=result,
                                                                      node=inst["position"], evidence=evidence,
                                                                      revision=revision, **extra)
    return dict(result=ASSESSED, assessment=result, recovery=outcome, **extra)


def _confirm(state, topology, task_id, record, evidence, authority, *, revision):
    """Record the formal result from the port's persisted completion, so RECORD_CONFIRMED_RESULT can use it."""
    fact_id = record["executionRequestId"] + ":confirmed-result"
    if fact_id not in steps.inst(state, task_id)["facts"]:
        steps.fact(state, topology, task_id, fact_id, "execution-result", "implement-result", authority,
                   dict(candidateCommit=evidence["worktree"]["commit"], changedFiles=evidence["worktree"]["changed"],
                        baseline=record["baseline"]["head"], executionRequestId=record["executionRequestId"],
                        modelVendor=evidence["modelVendor"], confirmedBy="recovery-assessment"), revision=revision)
    held = steps.inst(state, task_id)["reservations"].get(record["reservationId"], {})
    if held.get("status") == "held":
        steps.settle_reservation(state, topology, task_id, record["reservationId"],
                                 dict(executionFact=fact_id, attemptId=record["attemptId"], outcome="confirmed"),
                                 revision=revision)
    record["settlement"] = dict(record.get("settlement") or {}, confirmedResult=fact_id,
                                candidateCommit=evidence["worktree"]["commit"])
    return dict(confirmedFact=fact_id)


def _release(state, topology, task_id, record, evidence, authority, *, revision):
    """A proven-terminal execution: release its Workflow reservation against that same execution fact."""
    held = steps.inst(state, task_id)["reservations"].get(record["reservationId"], {})
    if held.get("status") != "held":
        return {}
    fact_id = record["executionRequestId"] + ":terminal"
    if fact_id not in steps.inst(state, task_id)["facts"]:
        steps.fact(state, topology, task_id, fact_id, "host-observation", "execution-terminal", authority,
                   dict(physical=evidence["physical"], reason=evidence["settlementReason"]), revision=revision)
    steps.settle_reservation(state, topology, task_id, record["reservationId"],
                             dict(executionFact=fact_id, attemptId=record["attemptId"], outcome="terminal"),
                             revision=revision)
    return dict(releasedReservation=record["reservationId"], terminalFact=fact_id)
