"""Controlled recovery at the Publish node (spec FR-29, FR-30; D-05 §4, §6, §8).

`publish-query` registers a read-only query of the same publish operation; its settlement records the
observation and derives the recovery assessment (settle.py). `publish-reconcile` consumes only a fresh
RECONCILIATION_REQUIRED assessment and a single Human recovery authorization bound to the instance, the
occurrence, the expected Runtime Version, the assessment, the exact action RECONCILE_CURRENT_NODE and the
effect scope `publish-operation:<operation id>`; it re-evaluates the push permit and registers an execution
of the same operation. feature-t2 produces no RESTART_SAFE at the Publish node (states.restartable), so a
publish proven not to have happened is remedied this way rather than by re-dispatching (feature-t7:KB-01).
"""
import copy
from datetime import datetime, timezone

from domain.publish import dispatch, records
from domain.publish.results import (
    ASSESSMENT_NOT_RECONCILABLE, BINDING_MISMATCH, EXECUTION_IN_FLIGHT, IDEMPOTENT_REPLAY, POSITION_NOT_APPLICABLE,
    QUERY_DISPATCHED, RECONCILE_DISPATCHED, PublishRejection,
)
from domain.workflow import progression, recovery, states
from domain.workflow.results import TASK_TERMINAL, WorkflowRejection


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scope_of(state, task_id):
    return "publish-operation:" + records.ledger(state, task_id)["operation"]["id"]


def _in_recovery(state, task_id):
    inst = progression.instance(state, task_id)
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection(TASK_TERMINAL, "the Workflow reached a terminal lifecycle", lifecycle=inst["lifecycle"])
    if inst["position"] != dispatch.PUBLISH_NODE or inst["condition"] != states.RECOVERY_REQUIRED:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "publish recovery runs only while the Publish node is in RECOVERY_REQUIRED",
                               position=inst["position"], condition=inst["condition"])
    if records.ledger(state, task_id)["operation"] is None:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "no publish operation was recorded for this task")
    flight = records.in_flight(state, task_id)
    if flight:
        raise PublishRejection(EXECUTION_IN_FLIGHT, "an execution of this publish operation is still pending or running",
                               executions=flight)
    return inst


def query(state, topology, context, payload, command_id, authority):
    task_id = payload["taskId"]
    record = records.ledger(state, task_id)
    for done in record["observations"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, observation=copy.deepcopy(done), executionId=done["executionId"])
    _in_recovery(state, task_id)
    execution_id = "publish-query:%s:%s" % (task_id, command_id)
    done = dict(commandId=command_id, executionId=execution_id, status="dispatched", dispatchedAt=now(),
                dispatchedRevision=str(state["revision"]), authorityRef=authority, outcome=None)
    record["observations"].append(done)
    state.setdefault("executionDescriptors", {})[execution_id] = dict(
        executionId=execution_id, purpose=dispatch.QUERY_PURPOSE, taskId=task_id, status="pending", attemptId=None,
        createdAt=now(), createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None,
        entry=context.entry, input=dict(operation=record["operation"]["id"], repository=str(context.repository_root),
                                        runtime=copy.deepcopy(payload.get("runtimeContext"))))
    return dict(result=QUERY_DISPATCHED, observation=copy.deepcopy(done), executionId=execution_id,
                operation=record["operation"]["id"])


def reconcile(state, topology, context, payload, command_id, authority, inputs):
    task_id = payload["taskId"]
    record = records.ledger(state, task_id)
    for done in record["executions"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, execution=copy.deepcopy(done), executionId=done["executionId"])
    inst = _in_recovery(state, task_id)
    assessment_id = payload.get("assessmentId") or inst["recovery"]["current"]
    assessment = inst["recovery"]["assessments"].get(assessment_id) if assessment_id else None
    if assessment is None or assessment["assessment"] != recovery.RECONCILIATION_REQUIRED:
        raise PublishRejection(ASSESSMENT_NOT_RECONCILABLE, "a reconcile consumes only a RECONCILIATION_REQUIRED assessment "
                               "formed from a query of this publish operation", assessmentId=assessment_id,
                               assessment=(assessment or {}).get("assessment"))
    offered = payload.get("humanAuthorization")
    scope = scope_of(state, task_id)
    if isinstance(offered, dict) and offered.get("effectScope") != scope:
        raise PublishRejection(BINDING_MISMATCH, "the Human recovery authorization must name this publish operation as its "
                               "effect scope", field="humanAuthorization.effectScope", expected=scope,
                               offered=offered.get("effectScope"))
    evaluation = dispatch.permit(state, topology, task_id, authority, inputs)
    if evaluation["conclusion"] != "ALLOW":
        return dispatch.refused(evaluation)
    recovered = recovery.recover(state, topology, task_id, dict(commandId=command_id + ":reconcile", action=recovery.RECONCILE_CURRENT_NODE,
                                                                assessmentId=assessment_id, mutatesExternalState=True,
                                                                humanAuthorization=copy.deepcopy(offered), scope=scope,
                                                                evidence=[dict(assessmentId=assessment_id)],
                                                                authorityRef=authority), revision=state["revision"])
    done = dispatch.register(state, topology, context, task_id, command_id=command_id, authority=authority, kind="reconcile",
                             permit_fact=evaluation["factId"], runtime=payload.get("runtimeContext"))
    record["recoveries"].append(dict(commandId=command_id, action=recovery.RECONCILE_CURRENT_NODE, assessmentId=assessment_id,
                                     authorizationRef=recovered.get("record", {}).get("authorizationRef"), at=now()))
    return dict(result=RECONCILE_DISPATCHED, execution=copy.deepcopy(done), executionId=done["executionId"],
                operation=record["operation"]["id"], recovery=copy.deepcopy(recovered.get("record")),
                position=inst["position"], condition=inst["condition"])
