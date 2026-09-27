"""`Publish`: the push permit, the attempt, the reservation and the execution descriptor; the execution start.

The dispatch transaction builds the push request from the authorized binding and lets feature-t6's Policy Gate
evaluate and record it. Anything but ALLOW keeps that record, changes no condition, opens no attempt and
calls nothing external. On ALLOW the attempt (purpose `publish`) is opened, a Workflow reservation is held
for the execution and a data-only descriptor is registered for this entry's execution layer. The start runs in
its own transaction: attempt CREATED -> RUNNING and the Publish node ENTERED -> EXECUTING, triggered by that
ALLOW decision, so the external work is mechanically bound to one permit. A Human-authorised reconcile under
the same publish operation reuses this module for its descriptor; it opens no Workflow attempt and changes no
condition (D-05 §6.2 and §6.4).
"""
import copy
from datetime import datetime, timezone

from domain.policy import evaluate as policy_evaluate, rules as policy_rules
from domain.publish import records
from domain.publish.results import (
    EXECUTION_IN_FLIGHT, IDEMPOTENT_REPLAY, POSITION_NOT_APPLICABLE, PUBLISH_DISPATCHED, PUSH_NOT_PERMITTED,
    PUSH_PERMIT_NOT_DETERMINABLE, PublishRejection,
)
from domain.workflow import progression, reservations, states
from domain.workflow.results import RECOVERY_REQUIRED_BLOCKS_PROGRESSION, REQUEST_CONFLICT, TASK_TERMINAL, WorkflowRejection

PUBLISH_NODE = "N-PUBLISH"
PURPOSE = "publish"
QUERY_PURPOSE = "publish-query"
PERMIT = policy_rules.PUSH_PERMIT


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def authorization(state, task_id):
    record = records.ledger(state, task_id)
    if record["authorization"] is None:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "no Publish authorization with a binding was recorded for this task")
    return record["authorization"]


def permit(state, topology, task_id, authority, inputs):
    """feature-t6 push permit for the authorized binding; the decision is recorded whatever it concludes.

    The Policy Decision identity is the digest of the decision content, which does not include who asked; a
    re-evaluation at the same occurrence with identical content under another authority (a reconcile issued by a
    different Human decision) meets the recorded identical decision, which feature-t2 reports as a conflict of the
    fact envelope. That recorded decision is the same Policy Gate conclusion for the same content and is used as is.
    """
    task = state["tasks"][task_id]
    bound = authorization(state, task_id)["binding"]
    push = dict(candidateCommit=bound["candidateCommit"], sourceBranch=bound["sourceBranch"], remote=bound["remote"],
                targetBranch=bound["targetBranch"], repositoryIdentity=task.get("repositoryIdentity"))
    request = dict(schema=policy_rules.REQUEST_SCHEMA, subject=PERMIT, taskId=task_id, push=push)
    try:
        return policy_evaluate.evaluate(state, topology, task_id, dict(request=request, authorityRef=authority),
                                        revision=state["revision"], inputs=inputs)
    except WorkflowRejection as exc:
        existing = progression.instance(state, task_id)["facts"].get(exc.detail.get("factId") or "")
        if exc.code != REQUEST_CONFLICT or existing is None or existing.get("kind") != "policy-decision" \
                or existing.get("purpose") != PERMIT or existing.get("producer") != "policy-gate":
            raise
        payload = existing.get("payload") or {}
        return dict(result="POLICY_RECORDED_EARLIER", conclusion=payload.get("conclusion"), factId=existing["factId"],
                    decision=copy.deepcopy(payload), recordedUnder=existing.get("authorityRef"))


def refused(evaluation):
    code = PUSH_NOT_PERMITTED if evaluation["conclusion"] == "DENY" else PUSH_PERMIT_NOT_DETERMINABLE
    return dict(result=code, conclusion=evaluation["conclusion"], factId=evaluation.get("factId"),
                decision=copy.deepcopy(evaluation.get("decision")), reason=copy.deepcopy(evaluation.get("reason")))


def register(state, topology, context, task_id, *, command_id, authority, kind, permit_fact, runtime=None):
    """Execution record, reservation and descriptor of one execution under the task's publish operation."""
    record = records.ledger(state, task_id)
    task = state["tasks"][task_id]
    operation = record["operation"]["id"]
    number = len(record["executions"]) + 1
    execution_id = "%s:%d" % (operation, number)
    attempt_id = operation + ":attempt" if kind == "dispatch" else None
    bound = record["authorization"]["binding"]
    if attempt_id:
        progression.open_attempt(state, topology, task_id, dict(attemptId=attempt_id, purpose=PURPOSE, authorityRef=authority),
                                 revision=state["revision"])
    reservations.reserve(state, topology, task_id, dict(
        reservationId=execution_id, purpose="publish-execution", authorityRef=authority, executionRef=execution_id,
        protects=["%s refs/heads/%s" % (bound["remoteAddress"], bound["sourceBranch"]),
                  "%s pull request %s -> %s" % (bound["platform"]["repository"], bound["sourceBranch"], bound["targetBranch"])]),
        revision=state["revision"])
    done = dict(commandId=command_id, executionId=execution_id, number=number, kind=kind, attemptId=attempt_id,
                reservationId=execution_id, permitFact=permit_fact, status="dispatched", dispatchedAt=now(),
                dispatchedRevision=str(state["revision"]), authorityRef=authority, outcome=None)
    record["executions"].append(done)
    record["operation"]["status"] = "dispatched" if kind == "dispatch" else "reconciling"
    state.setdefault("executionDescriptors", {})[execution_id] = dict(
        executionId=execution_id, purpose=PURPOSE, taskId=task_id, status="pending", attemptId=attempt_id, createdAt=now(),
        createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None, entry=context.entry,
        input=dict(operation=operation, number=number, kind=kind, repository=str(context.repository_root),
                   worktree=task["worktree"], runtime=copy.deepcopy(runtime)))
    return done


def dispatch(state, topology, context, payload, command_id, authority, inputs):
    task_id = payload["taskId"]
    record = records.ledger(state, task_id)
    for done in record["executions"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, execution=copy.deepcopy(done), executionId=done["executionId"])
    inst = progression.instance(state, task_id)
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection(TASK_TERMINAL, "the Workflow reached a terminal lifecycle", lifecycle=inst["lifecycle"])
    if inst["position"] != PUBLISH_NODE:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "the publish runs only at the Publish node", position=inst["position"])
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection(RECOVERY_REQUIRED_BLOCKS_PROGRESSION,
                                "the Publish node needs recovery first; query the same publish operation")
    if inst["condition"] != states.ENTERED or records.in_flight(state, task_id):
        raise PublishRejection(EXECUTION_IN_FLIGHT, "this task's publish operation is already executing",
                               condition=inst["condition"], executions=records.in_flight(state, task_id))
    authorization(state, task_id)
    evaluation = permit(state, topology, task_id, authority, inputs)
    if evaluation["conclusion"] != "ALLOW":
        return refused(evaluation)
    done = register(state, topology, context, task_id, command_id=command_id, authority=authority, kind="dispatch",
                    permit_fact=evaluation["factId"], runtime=payload.get("runtimeContext"))
    return dict(result=PUBLISH_DISPATCHED, execution=copy.deepcopy(done), executionId=done["executionId"],
                permit=dict(factId=evaluation["factId"], conclusion=evaluation["conclusion"]),
                operation=record["operation"]["id"], position=inst["position"], runtimeVersion=inst["runtimeVersion"])


def start(state, topology, task_id, execution_id):
    """Own transaction before any external effect: attempt RUNNING and, for the dispatch, the node EXECUTING."""
    record = records.ledger(state, task_id)
    done = next(e for e in record["executions"] if e["executionId"] == execution_id)
    if done["status"] != "dispatched":
        return copy.deepcopy(done)
    inst = progression.instance(state, task_id)
    if inst["lifecycle"] != states.ACTIVE or inst["position"] != PUBLISH_NODE:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "the task left the Publish node before the execution started",
                               lifecycle=inst["lifecycle"], position=inst["position"])
    if done["kind"] == "dispatch":
        if inst["condition"] != states.ENTERED:
            raise PublishRejection(EXECUTION_IN_FLIGHT, "the Publish node is not ENTERED", condition=inst["condition"])
        progression.start_attempt(state, topology, task_id, dict(attemptId=done["attemptId"], commandId="start:" + execution_id,
                                                                 executionRef=execution_id, authorityRef=done["authorityRef"]),
                                  revision=state["revision"])
        progression.update_condition(state, topology, task_id, dict(
            commandId="start:" + execution_id + ":executing", condition=states.EXECUTING, triggers=[done["permitFact"]],
            purpose=PERMIT, authorityRef=done["authorityRef"]), revision=state["revision"])
    elif inst["condition"] != states.RECOVERY_REQUIRED:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "a reconcile runs only while the Publish node is in recovery",
                               condition=inst["condition"])
    done.update(status="running", startedAt=now())
    return copy.deepcopy(done)
