"""Publish settlement: the one mapping from an execution or query outcome to the attempt, the node and the record.

Execution (purpose `publish`), dispatch kind:
  published -> execution-result fact, attempt COMPLETED, reservation released naming that fact, and the
               lifecycle finalisation that consumes it: COMPLETED + RESULT_RECORDED with the published slot.
  not-happened, partial -> attempt EXECUTION_FAILED, reservation released naming the fact, RECOVERY_REQUIRED.
  uncontrolled-change -> attempt EXECUTION_FAILED, reservation kept, RECOVERY_REQUIRED; nothing forced or rolled back.
  unknown -> attempt INDETERMINATE, reservation kept, RECOVERY_REQUIRED; only the same operation may be queried.
Execution, reconcile kind (the node stays RECOVERY_REQUIRED; no Workflow attempt): the outcome forms a new
recovery assessment: published -> RESULT_CONFIRMED, RESTORE_PUBLISH_FINALIZATION and the finalisation in the
same transaction; not-happened / partial -> RECONCILIATION_REQUIRED; unknown -> INDETERMINATE; uncontrolled ->
no assessment.
Query (purpose `publish-query`): confirmed -> RESULT_CONFIRMED, restore and finalise without any new push,
create or attempt (D-05 §6.2, S11); absent / partial -> RECONCILIATION_REQUIRED; unknown -> INDETERMINATE;
uncontrolled -> no assessment, stop. A determinate query releases the reservations the operation still holds.
The assessment result is always derived here from the observed facts; no caller chooses it (D-05 §2).
"""
import copy
from datetime import datetime, timezone

from domain.publish import records
from domain.publish.results import (
    ABSENT, CONFIRMED, EXECUTION_OUTCOMES, EXECUTION_SETTLED, IDEMPOTENT_REPLAY, NOT_HAPPENED, PARTIAL, PUBLISH_OBSERVED,
    PUBLISHED, PUBLISHED_OUTCOME, QUERY_OUTCOMES, UNCONTROLLED, UNCONTROLLED_CHANGE, UNKNOWN,
)
from domain.workflow import progression, recovery, reservations, states

RESULT_PURPOSE = "publish"
OBSERVATION_PURPOSE = "publish-observation"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fact(state, topology, task_id, fact_id, purpose, authority, payload):
    return progression.record_fact(state, topology, task_id, dict(factId=fact_id, kind="execution-result", purpose=purpose,
                                                                  authorityRef=authority, payload=payload),
                                   revision=state["revision"])["fact"]


def _release_held(state, topology, task_id, fact_id):
    """Release every reservation of this operation still held, naming the fact that settled its external state."""
    released = []
    record = records.ledger(state, task_id)
    inst = progression.instance(state, task_id)
    for execution in record["executions"]:
        reservation = inst["reservations"].get(execution["reservationId"])
        if reservation is not None and reservation["status"] == reservations.HELD:
            reservations.settle(state, topology, task_id, dict(reservationId=execution["reservationId"], settlement=dict(
                executionFact=dict(factId=fact_id, kind="publish-operation-state"),
                attemptId=execution["attemptId"])), revision=state["revision"])
            released.append(execution["reservationId"])
    return released


def _finalize(state, topology, task_id, command_id, fact_id, purpose, authority):
    return progression.finalize_publish(state, topology, task_id, dict(commandId=command_id, triggers=[fact_id], purpose=purpose,
                                                                       authorityRef=authority), revision=state["revision"])


def _assess(state, topology, task_id, assessment_id, result, fact_id, checked):
    return recovery.assess(state, topology, task_id, dict(assessmentId=assessment_id, assessment=result, checked=checked,
                                                          evidence=[dict(factId=fact_id)]), revision=state["revision"])


def _restore_and_finalize(state, topology, task_id, base, fact_id, purpose, authority, checked):
    assessment = _assess(state, topology, task_id, base + ":assess", recovery.RESULT_CONFIRMED, fact_id, checked)
    recovery.recover(state, topology, task_id, dict(commandId=base + ":restore", action=recovery.RESTORE_PUBLISH_FINALIZATION,
                                                    assessmentId=assessment["assessment"]["assessmentId"],
                                                    authorityRef=authority), revision=state["revision"])
    _release_held(state, topology, task_id, fact_id)
    return _finalize(state, topology, task_id, base + ":finalize", fact_id, purpose, authority)


def settle_publish(state, topology, descriptor, outcome):
    task_id = descriptor["taskId"]
    record = records.ledger(state, task_id)
    done = next(e for e in record["executions"] if e["executionId"] == descriptor["executionId"])
    if done["status"] not in ("dispatched", "running"):
        return dict(result=IDEMPOTENT_REPLAY, execution=copy.deepcopy(done))
    inst = progression.instance(state, task_id)
    classification = outcome.get("classification")
    if classification not in EXECUTION_OUTCOMES:
        classification = UNKNOWN
    failure = outcome.get("failureCode")
    if done["kind"] == "dispatch" and classification == PUBLISHED_OUTCOME and inst["condition"] != states.EXECUTING:
        # The execution never started (no EXECUTING), yet the remote shows the published state: not this execution's
        # effect. Stop here; a later query of the same operation can still confirm it through the recovery contract.
        classification, failure = UNCONTROLLED, "published-without-this-execution"
    authority = done["authorityRef"]
    base = "settle:" + descriptor["executionId"]
    summary = dict(operation=record["operation"]["id"], executionId=done["executionId"], number=done["number"], kind=done["kind"],
                   classification=classification, failureCode=failure,
                   via=outcome.get("via", "execution"), evidence=copy.deepcopy(outcome.get("evidence")))
    done.update(outcome=summary, settledAt=now())
    if inst["lifecycle"] != states.ACTIVE:
        # Closed before the execution could start: nothing was released; the reservation is settled by that refusal.
        reservations.settle(state, topology, task_id, dict(reservationId=done["reservationId"], settlement=dict(
            executionFact=dict(kind="refused-before-release", executionId=done["executionId"]))), revision=state["revision"])
        done["status"] = "not-started"
        return dict(result=EXECUTION_SETTLED, classification=classification, lifecycle=inst["lifecycle"])
    fact = _fact(state, topology, task_id, base + ":result", RESULT_PURPOSE, authority, summary)
    fact_ref = dict(factId=fact["factId"], kind="execution-result")
    if done["kind"] == "reconcile":
        return _settle_reconcile(state, topology, task_id, done, record, classification, fact, authority, base)
    if classification == PUBLISHED_OUTCOME:
        progression.settle_attempt(state, topology, task_id, dict(attemptId=done["attemptId"], status="COMPLETED",
                                                                  evidence=fact_ref, commandId=base), revision=state["revision"])
        reservations.settle(state, topology, task_id, dict(reservationId=done["reservationId"], settlement=dict(
            executionFact=fact_ref, attemptId=done["attemptId"])), revision=state["revision"])
        _finalize(state, topology, task_id, base + ":finalize", fact["factId"], RESULT_PURPOSE, authority)
        done["status"] = "published"
        record["operation"]["status"] = "published"
        return dict(result=PUBLISHED, classification=classification, evidence=copy.deepcopy(summary["evidence"]),
                    lifecycle=inst["lifecycle"], runtimeVersion=inst["runtimeVersion"])
    status = "INDETERMINATE" if classification == UNKNOWN else "EXECUTION_FAILED"
    attempt = next((a for a in inst["attempts"] if a["attemptId"] == done["attemptId"]), None)
    if attempt is not None and attempt["status"] in ("CREATED", "RUNNING"):
        progression.settle_attempt(state, topology, task_id, dict(attemptId=done["attemptId"], status=status, evidence=fact_ref,
                                                                  commandId=base), revision=state["revision"])
    if classification in (NOT_HAPPENED, PARTIAL):
        reservations.settle(state, topology, task_id, dict(reservationId=done["reservationId"], settlement=dict(
            executionFact=fact_ref, attemptId=done["attemptId"])), revision=state["revision"])
    if inst["condition"] != states.RECOVERY_REQUIRED:
        progression.update_condition(state, topology, task_id, dict(commandId=base + ":recovery", condition=states.RECOVERY_REQUIRED,
                                                                    authorityRef=authority), revision=state["revision"])
    done["status"] = classification
    record["operation"]["status"] = classification
    result = UNCONTROLLED_CHANGE if classification == UNCONTROLLED else EXECUTION_SETTLED
    return dict(result=result, classification=classification, attempt=status, failureCode=failure,
                indeterminate=classification == UNKNOWN, position=inst["position"], condition=inst["condition"])


def _settle_reconcile(state, topology, task_id, done, record, classification, fact, authority, base):
    inst = progression.instance(state, task_id)
    checked = [dict(executionId=done["executionId"], kind="reconcile", classification=classification)]
    if classification == PUBLISHED_OUTCOME:
        _restore_and_finalize(state, topology, task_id, base, fact["factId"], RESULT_PURPOSE, authority, checked)
        done["status"] = "published"
        record["operation"]["status"] = "published"
        record["recoveries"].append(dict(executionId=done["executionId"], assessment=recovery.RESULT_CONFIRMED, at=now()))
        return dict(result=PUBLISHED, classification=classification, lifecycle=inst["lifecycle"], runtimeVersion=inst["runtimeVersion"])
    assessment = None
    if classification in (NOT_HAPPENED, PARTIAL):
        reservations.settle(state, topology, task_id, dict(reservationId=done["reservationId"], settlement=dict(
            executionFact=dict(factId=fact["factId"], kind="execution-result"))), revision=state["revision"])
        assessment = _assess(state, topology, task_id, base + ":assess", recovery.RECONCILIATION_REQUIRED, fact["factId"], checked)
    elif classification == UNKNOWN:
        assessment = _assess(state, topology, task_id, base + ":assess", recovery.INDETERMINATE, fact["factId"], checked)
    done["status"] = classification
    record["operation"]["status"] = classification
    record["recoveries"].append(dict(executionId=done["executionId"], assessment=(assessment or {}).get("assessment", {}).get("assessment"),
                                     at=now()))
    result = UNCONTROLLED_CHANGE if classification == UNCONTROLLED else EXECUTION_SETTLED
    return dict(result=result, classification=classification, indeterminate=classification == UNKNOWN,
                assessment=copy.deepcopy((assessment or {}).get("assessment")), position=inst["position"], condition=inst["condition"])


def settle_query(state, topology, descriptor, outcome):
    task_id = descriptor["taskId"]
    record = records.ledger(state, task_id)
    observation = next(o for o in record["observations"] if o["executionId"] == descriptor["executionId"])
    if observation["status"] != "dispatched":
        return dict(result=IDEMPOTENT_REPLAY, observation=copy.deepcopy(observation))
    inst = progression.instance(state, task_id)
    classification = outcome.get("classification")
    if classification not in QUERY_OUTCOMES:
        classification = UNKNOWN
    authority = observation["authorityRef"]
    base = "observe:" + descriptor["executionId"]
    summary = dict(operation=record["operation"]["id"], executionId=descriptor["executionId"], classification=classification,
                   failureCode=outcome.get("failureCode"), evidence=copy.deepcopy(outcome.get("evidence")))
    observation.update(outcome=summary, settledAt=now(), status=classification)
    if inst["lifecycle"] != states.ACTIVE or inst["condition"] != states.RECOVERY_REQUIRED:
        return dict(result=EXECUTION_SETTLED, classification=classification, note="the Publish node is no longer in recovery")
    fact = _fact(state, topology, task_id, base + ":observation", OBSERVATION_PURPOSE, authority, summary)
    checked = [dict(query=descriptor["executionId"], classification=classification)]
    if classification == CONFIRMED:
        _restore_and_finalize(state, topology, task_id, base, fact["factId"], OBSERVATION_PURPOSE, authority, checked)
        record["operation"]["status"] = "published"
        record["recoveries"].append(dict(query=descriptor["executionId"], assessment=recovery.RESULT_CONFIRMED, at=now()))
        return dict(result=PUBLISHED, classification=classification, lifecycle=inst["lifecycle"], runtimeVersion=inst["runtimeVersion"])
    if classification == UNCONTROLLED:
        record["recoveries"].append(dict(query=descriptor["executionId"], assessment=None, at=now()))
        return dict(result=UNCONTROLLED_CHANGE, classification=classification, failureCode=outcome.get("failureCode"),
                    position=inst["position"], condition=inst["condition"])
    released = []
    if classification in (ABSENT, PARTIAL):
        released = _release_held(state, topology, task_id, fact["factId"])
        result = recovery.RECONCILIATION_REQUIRED
    else:
        result = recovery.INDETERMINATE
    assessment = _assess(state, topology, task_id, base + ":assess", result, fact["factId"], checked)
    record["recoveries"].append(dict(query=descriptor["executionId"], assessment=result, at=now()))
    return dict(result=PUBLISH_OBSERVED, classification=classification, assessment=copy.deepcopy(assessment["assessment"]),
                released=released, indeterminate=classification == UNKNOWN, position=inst["position"],
                condition=inst["condition"])
