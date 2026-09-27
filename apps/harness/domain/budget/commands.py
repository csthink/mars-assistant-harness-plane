"""The budget decision command and the narrowing of feature-t2's generic commands at the budget nodes.

`budget-decide` runs in one Domain Core transaction: the Policy Gate evaluates the subject of the current
budget node and records its policy-decision fact; an ALLOW decision is then consumed as the trigger of
exactly one registered edge (Budget Remains or Budget Exhausted). At the Verification budget node the
routing is feature-t4's `remediate`, which consumes the same fact; this package keeps no second router.
A DENY or NOT_DETERMINABLE decision is committed as a record and moves nothing (Assistant KB-264: an
exhausted budget is an ALLOW record, never a DENY).

guard() refuses the generic fact / condition / advance / attempt / reservation commands at the three
budget nodes for every task, whoever drives it: a generic advance without a budget decision would make the
budget bypassable (spec FR-25). Close Task (FR-27) and the Human-authorised recovery commands stay open.
"""
import copy

from domain.budget import ledger
from domain.budget.results import (
    BUDGET_DENIED, BUDGET_NOT_DETERMINABLE, BUDGET_ROUTED, GENERIC_COMMAND_NARROWED, IDEMPOTENT_REPLAY,
    POSITION_NOT_APPLICABLE, BudgetRejection,
)
from domain.workflow import progression, states
from domain.workflow.results import (
    ILLEGAL_TRANSITION, RECOVERY_REQUIRED_BLOCKS_PROGRESSION, TASK_TERMINAL, WorkflowRejection,
)

COMMANDS = ("budget-decide",)
GUARDED_NODES = tuple(spec["node"] for spec in ledger.LOOPS.values())
GUARDED_GENERIC = ("fact", "advance", "condition", "attempt-open", "attempt-settle", "attempt-start", "reserve",
                   "reservation-settle")


def guard(state, task_id, name):
    if name not in GUARDED_GENERIC:
        return
    task = state.get("tasks", {}).get(task_id)
    if task is None:
        return
    position = task["workflowInstance"]["position"]
    if position in GUARDED_NODES:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "a budget decision node moves only on a Policy Gate budget decision; "
                                "the generic command cannot record its facts or move it", command=name, position=position,
                                reasonCode=GENERIC_COMMAND_NARROWED, entry="harness budget decide")


def _walk(state, topology, task_id, target, command_id, authority, revision):
    inst = progression.instance(state, task_id)
    node = inst["position"]
    semantic = topology.semantic_type(node)
    step = 0
    while inst["condition"] != target:
        nxt = states.next_condition(node, semantic, inst["condition"])
        if nxt is None:
            break
        progression.update_condition(state, topology, task_id, dict(commandId="%s:c%d" % (command_id, step), condition=nxt,
                                                                    authorityRef=authority), revision=revision)
        step += 1


def decide(state, topology, task_id, payload, *, revision, inputs):
    from domain.policy import evaluate as policy_evaluate, rules
    from domain.policy.results import ALLOW, DENY
    command_id, authority = payload.get("commandId"), payload.get("authorityRef")
    if not isinstance(command_id, str) or not command_id:
        raise BudgetRejection(POSITION_NOT_APPLICABLE, "commandId is required")
    if not isinstance(authority, str) or not authority:
        raise WorkflowRejection("AUTHORITY_MISSING", "authorityRef is required: every progression binds to an authorising fact")
    inst = progression.instance(state, task_id)
    for commit in inst["commits"]:
        if commit["commandId"].startswith(command_id + ":E-") and commit["transitionKind"] == states.POSITION_ADVANCE:
            return dict(result=IDEMPOTENT_REPLAY, commit=copy.deepcopy(commit), position=inst["position"],
                        runtimeVersion=inst["runtimeVersion"])
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection(TASK_TERMINAL, "a terminal Workflow takes no budget decision", lifecycle=inst["lifecycle"])
    subject = ledger.SUBJECT_AT.get(inst["position"])
    if subject is None:
        raise BudgetRejection(POSITION_NOT_APPLICABLE, "a budget decision runs only at one of the three budget nodes",
                              position=inst["position"], nodes=list(ledger.SUBJECT_AT))
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection(RECOVERY_REQUIRED_BLOCKS_PROGRESSION, "the budget node needs recovery first",
                                node=inst["position"])
    request = dict(schema=rules.REQUEST_SCHEMA, subject=subject, taskId=task_id)
    outcome = policy_evaluate.evaluate(state, topology, task_id, dict(taskId=task_id, authorityRef=authority, request=request),
                                       revision=revision, inputs=inputs)
    base = dict(subject=subject, factId=outcome.get("factId"), conclusion=outcome["conclusion"],
                decision=copy.deepcopy(outcome.get("decision")))
    if outcome["conclusion"] != ALLOW:
        code = BUDGET_DENIED if outcome["conclusion"] == DENY else BUDGET_NOT_DETERMINABLE
        return dict(result=code, position=inst["position"], condition=inst["condition"],
                    runtimeVersion=inst["runtimeVersion"], **base)
    result = outcome["decision"]["outcome"]
    edge = ledger.edge(subject, result)
    if subject == ledger.VERIFICATION:
        from domain.implement_verify import commands as implement_verify
        implement_verify.remediate(state, topology, task_id, dict(budgetFact=outcome["factId"], commandId=command_id,
                                                                  authorityRef=authority), revision=revision)
    else:
        _walk(state, topology, task_id, states.RESULT_RECORDED, command_id + ":budget", authority, revision)
        progression.advance(state, topology, task_id, dict(commandId=command_id + ":" + edge, edgeId=edge,
                                                           triggers=[outcome["factId"]], purpose=subject,
                                                           authorityRef=authority), revision=revision)
        if result == ledger.EXHAUSTED:
            _walk(state, topology, task_id, states.AWAITING_HUMAN_ACTION, command_id + ":gate", authority, revision)
    inst = progression.instance(state, task_id)
    return dict(result=BUDGET_ROUTED, outcome=result, edge=edge, position=inst["position"], condition=inst["condition"],
                runtimeVersion=inst["runtimeVersion"], budget=copy.deepcopy(outcome["decision"]["derived"]["budget"]),
                **{k: v for k, v in base.items() if k != "decision"})


def status(state, task_id):
    """Read only: configuration, the current window of each loop and every recorded budget decision."""
    from domain.budget import configuration
    task = state["tasks"][task_id]
    inst = task["workflowInstance"]
    windows = {}
    for subject in ledger.SUBJECTS:
        try:
            windows[subject] = ledger.derive(state, task_id, subject)
        except (ledger.BudgetUnavailable, ledger.BudgetBroken) as exc:
            windows[subject] = dict(unavailable=exc.code, message=str(exc))
    return dict(configuration=configuration.current(state),
                history=[dict(index=i, **copy.deepcopy(row)) for i, row in configuration.history(state)],
                position=inst["position"], windows=windows,
                decisions=[dict(factId=f["factId"], purpose=f["purpose"], conclusion=f["payload"].get("conclusion"),
                                outcome=f["payload"].get("outcome"), consumedBy=f.get("consumedBy"),
                                budget=copy.deepcopy((f["payload"].get("derived") or {}).get("budget")))
                           for f in ledger.decisions(state, task_id)])


def apply(state, resolve, name, payload, *, revision, inputs=None):
    task_id = payload.get("taskId")
    inst = progression.instance(state, task_id)
    topology = resolve(inst)
    if topology is None:
        raise WorkflowRejection("TOPOLOGY_UNREADABLE", "the bound Workflow topology could not be read")
    if name == "budget-decide":
        return decide(state, topology, task_id, payload, revision=revision, inputs=inputs)
    raise BudgetRejection(POSITION_NOT_APPLICABLE, "unknown budget command", command=name, commands=list(COMMANDS))
