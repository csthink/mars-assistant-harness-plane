"""The Publish business record of a task and its read-only view.

`publish` lives in the task record of the one domain state: the authorization (binding, context digest,
decision fact), the publish operation, every execution under that operation (dispatch and Human-authorised
reconcile), every same-operation observation and the recovery steps taken here. No second Workflow state.
"""
import copy


def ledger(state, task_id):
    task = state["tasks"][task_id]
    return task.setdefault("publish", dict(authorization=None, operation=None, executions=[], observations=[],
                                           recoveries=[]))


def view_of(state, task_id):
    return copy.deepcopy(state["tasks"][task_id].get("publish") or dict(authorization=None, operation=None, executions=[],
                                                                        observations=[], recoveries=[]))


def operation_id(task_id, fact_id):
    return "publish:%s:%s" % (task_id, fact_id)


def trailer(operation):
    """The deterministic last line of the published pull request body (identification of the operation)."""
    return "<!-- harness-publish-operation: %s -->" % operation


def register_authorization(state, task_id, *, command_id, fact_id, edge, binding, context_digest, decision_text,
                           authority, at):
    """Called in the authorizing transaction by both entries into Publish (E-V06 here, E-V12 by feature-t5)."""
    record = ledger(state, task_id)
    operation = operation_id(task_id, fact_id)
    record["authorization"] = dict(commandId=command_id, factId=fact_id, edge=edge, binding=copy.deepcopy(binding),
                                   contextDigest=context_digest, decisionText=decision_text, authorityRef=authority,
                                   decidedAt=at, operation=operation)
    record["operation"] = dict(id=operation, factId=fact_id, status="authorized", trailer=trailer(operation))
    return operation


def in_flight(state, task_id):
    """Publish or publish-query descriptors of this task that are pending or running on any entry."""
    return sorted(k for k, d in state.get("executionDescriptors", {}).items()
                  if d.get("taskId") == task_id and d.get("purpose") in ("publish", "publish-query")
                  and d.get("status") in ("pending", "running"))
