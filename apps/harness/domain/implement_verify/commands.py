"""Command table feature-t4 adds to the shared Domain Core command point (core.apply_command).

Both entries reach these through the same apply_command, so neither holds a second rule set. Commands
that release an external effect (the Agent execution, the Verify checks) are not command names here:
they run in executors.py around two transactions and read every fact they commit from the persisted
state, never from a caller-supplied result.

guard() narrows feature-t2's generic commands on the nodes this loop owns. Without it, the generic
`workflow fact` + `workflow condition` + `workflow advance` surface could record a Verify PASS that no
check produced, or move an Implementer attempt around the execution port, which FR-23 and FR-62
forbid. Close Task (FR-27) and the Human-authorised recovery actions stay available everywhere.
"""
from domain.workflow import states
from domain.workflow.results import ILLEGAL_TRANSITION, WorkflowRejection
from domain.implement_verify import assessment, dispatch, implement, steps
from domain.implement_verify.results import (
    BUDGET_DECISION_MISSING, POSITION_NOT_APPLICABLE, REMEDIATION_ROUTED, ImplementVerifyRejection,
)

COMMANDS = ("implement-dispatch", "implement-remediate", "implement-assess", "implement-route")
OWNED_NODES = ("N-IMPL-DISPATCH", "N-IMPL-EXECUTE", "N-IMPL-ROUTE", "N-VERIFY-APPLICABILITY", "N-VERIFY-EXECUTE",
               "N-VERIFY-AUTONOMOUS-REMEDIATION", "N-VERIFY-HUMAN-REMEDIATION")
GUARDED_GENERIC = ("fact", "advance", "condition", "attempt-open", "attempt-settle", "attempt-start", "reserve",
                   "reservation-settle", "recover-assess")
BUDGET_NODE = "N-VERIFY-BUDGET-DECISION"
BUDGET_EDGES = {"Budget Remains": "E-I08", "Budget Exhausted": "E-I10"}


def guard(state, task_id, name):
    """Reject generic feature-t2 commands at the nodes of a task this loop drives.

    The guard is scoped to tasks with at least one execution dispatched through `implement-dispatch`:
    from then on only this loop records the facts of, and moves, its nodes. A task never dispatched here
    keeps feature-t2's generic surface unchanged (the feature-t6 Policy Gate tests walk the lane that way).
    """
    if name not in GUARDED_GENERIC:
        return
    task = state.get("tasks", {}).get(task_id)
    if task is None or not (task.get("implementVerify") or {}).get("executions"):
        return
    position = task["workflowInstance"]["position"]
    if position in OWNED_NODES:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "this node is driven only through the implement/verify entry; the "
                                "generic command cannot record its facts or move it", command=name, position=position,
                                entry="harness implement | harness verify")


def apply(state, resolve, name, payload, *, revision, repository=None):
    task_id = payload.get("taskId")
    if name == "implement-dispatch":
        topology = resolve(steps.inst(state, task_id)) if task_id in state.get("tasks", {}) else None
        return dispatch.dispatch(state, topology, task_id, payload, revision=revision, repository=repository)
    topology = resolve(steps.inst(state, task_id))
    if name == "implement-remediate":
        return remediate(state, topology, task_id, payload, revision=revision)
    if name == "implement-assess":
        return assessment.assess(state, topology, task_id, payload, revision=revision)
    if name == "implement-route":
        return route_confirmed(state, topology, task_id, payload, revision=revision)
    raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "unknown implement/verify command", command=name,
                                   commands=list(COMMANDS))


def remediate(state, topology, task_id, payload, *, revision):
    """Consume the Verification budget decision (produced by feature-t5) and follow E-I08 or E-I10."""
    inst = steps.inst(state, task_id)
    if inst["position"] != BUDGET_NODE:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "remediation routing runs at the Verification budget "
                                       "decision", position=inst["position"])
    fact_id = payload.get("budgetFact")
    fact = inst["facts"].get(fact_id) if isinstance(fact_id, str) else None
    outcome = ((fact or {}).get("payload") or {}).get("outcome")
    # feature-t6: only an ALLOW policy-decision produced by the Policy Gate may trigger a progression.
    if fact is None or fact["kind"] != "policy-decision" or fact["purpose"] != "verification-budget" or \
            fact.get("producer") != "policy-gate" or (fact.get("payload") or {}).get("conclusion") != "ALLOW" or \
            outcome not in BUDGET_EDGES:
        raise ImplementVerifyRejection(BUDGET_DECISION_MISSING, "no Verification budget decision fact to consume; this "
                                       "loop never decides the budget itself", budgetFact=fact_id,
                                       outcomes=sorted(BUDGET_EDGES))
    command_id, authority = payload["commandId"], payload.get("authorityRef")
    steps.walk_to(state, topology, task_id, states.RESULT_RECORDED, command_id + ":budget", authority, revision=revision)
    edge = BUDGET_EDGES[outcome]
    steps.advance(state, topology, task_id, command_id + ":" + edge, edge, authority, revision=revision,
                  triggers=[fact_id], purpose="verification-budget")
    if edge == "E-I10":
        steps.walk_to(state, topology, task_id, states.AWAITING_HUMAN_ACTION, command_id + ":gate", authority,
                      revision=revision)
    return dict(result=REMEDIATION_ROUTED, edge=edge, position=steps.inst(state, task_id)["position"],
                runtimeVersion=steps.inst(state, task_id)["runtimeVersion"])


def route_confirmed(state, topology, task_id, payload, *, revision):
    """After RECORD_CONFIRMED_RESULT, route the confirmed candidate on (E-I02, E-I03)."""
    inst = steps.inst(state, task_id)
    if inst["position"] != implement.IMPLEMENT_NODE or inst["condition"] != states.RESULT_RECORDED:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "only a recorded Implementer result is routed",
                                       position=inst["position"], condition=inst["condition"])
    confirmed = [f for f in inst["facts"].values() if f["purpose"] == "implement-result" and f["consumedBy"] is None
                 and f["occurrence"]["positionEntryRuntimeVersion"] == inst["positionEntryRevision"]]
    if len(confirmed) != 1:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "no single unconsumed Implementer result to route",
                                       candidates=[f["factId"] for f in confirmed])
    fact = confirmed[0]
    ledger = steps.ledger(state, task_id)
    record = ledger["executions"].get(fact["payload"]["executionRequestId"])
    if record is not None:
        record.update(status="settled", settlement=dict(record.get("settlement") or {}, kind="completed",
                                                       fact=fact["factId"],
                                                       candidateCommit=fact["payload"]["candidateCommit"]))
    return implement.route(state, topology, task_id, fact["factId"], payload.get("authorityRef"), revision=revision)
