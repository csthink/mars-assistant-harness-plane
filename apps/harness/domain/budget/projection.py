"""Read-only Runtime projection of the `budget.decide` action (NFR-04: the state derives the legal set).

The action is enabled only for a task at one of the three budget nodes outside recovery. Accepting it
runs the same Domain Core command the standalone CLI runs; the outcome is always the Policy Gate's.
"""
import copy

from domain.budget import ledger
from domain.budget.schema import DECIDE_ID, DIGEST_OF
from domain.workflow import states

CAPABILITY_ID = "harness.autonomous-budget"
CAPABILITY_VERSION = "1"
OBJECT = "autonomous-budget:tasks"
DECIDE = "budget.decide"
ACTIONS = {DECIDE: DECIDE_ID}


def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DIGEST_OF[DECIDE_ID], required=False)


def legal(state, task_id):
    inst = state["tasks"][task_id].get("workflowInstance") or {}
    if inst.get("lifecycle") != states.ACTIVE or inst.get("condition") == states.RECOVERY_REQUIRED:
        return set()
    return {DECIDE} if inst.get("position") in ledger.SUBJECT_AT else set()


def rows(state):
    return [dict(taskId=task_id, legal=sorted(legal(state, task_id)))
            for task_id, task in sorted(state.get("tasks", {}).items()) if "lifecycle" in (task.get("workflowInstance") or {})]


def action(scope, action_id, table, cap):
    enabled = any(action_id in row["legal"] for row in table)
    return dict(scopeRef=scope, actionId=action_id, objectRef=OBJECT, capability=copy.deepcopy(cap), label=action_id,
                expectedRevision=str(len(table)), candidateRef=None, payloadSchemaDigest=DIGEST_OF[ACTIONS[action_id]],
                enabled=enabled, disabledReason="" if enabled else "No task is at an autonomous budget decision node",
                disabledCode=None if enabled else "BUDGET_ACTION_NOT_LEGAL_HERE", requiresHumanDecision=True)


def budget_object(scope, table, cap):
    view = [dict(id=r["taskId"], title=r["taskId"], detail=", ".join(r["legal"]) or "no budget decision pending")
            for r in table]
    return dict(scopeRef=scope, objectRef=OBJECT, revision=str(len(table)), title="Autonomous budget",
                stateLabel="ready", capability=copy.deepcopy(cap), view=dict(kind="list", rows=view[:100]), evidence=[])


def refresh(state):
    cap = capability()
    table = rows(state)
    for scope, view in state.get("scopes", {}).items():
        view["objects"] = [o for o in view["objects"] if o["objectRef"] != OBJECT] + [budget_object(scope, table, cap)]
        view["actions"] = [a for a in view["actions"] if a["actionId"] not in ACTIONS] + [
            action(scope, action_id, table, cap) for action_id in ACTIONS]
