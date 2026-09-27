"""Read-only Runtime projection of the Definition actions (NFR-04: the state derives the legal set).

Each action is enabled only where the current Workflow position allows it; the dispatcher re-reads
the action before durable acceptance, so a projected action that has become illegal is refused.
"""
import copy

from domain import capability_schema
from domain.definition import commands, gate
from domain.definition.schema import DECIDE_ID, DISPATCH_ID, FORMAL_ID, SCHEMAS, SUBMIT_ID
from domain.workflow import states

CAPABILITY_ID = "harness.definition"
CAPABILITY_VERSION = "2"
OBJECT = "definition:tasks"
ACTIONS = {"definition.submit": SUBMIT_ID, "definition.dispatch": DISPATCH_ID, "definition.decide": DECIDE_ID,
           "definition.formal-authorize": FORMAL_ID}
# OD-425: the capability's negotiated schema is its primary action's payload schema with every other action's
# payload schema as a root `definitions` entry named by the actionId (domain/capability_schema.py); the
# document changed, so the capability version did.
DOCUMENT = capability_schema.CapabilityDocument("definition.submit", ACTIONS, SCHEMAS)


def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DOCUMENT.digest, required=False)


def legal(state, task_id):
    """Action ids legal for one task now; derived from position, condition and recorded business facts."""
    task = state["tasks"][task_id]
    inst = task.get("workflowInstance") or {}
    if inst.get("lifecycle") != states.ACTIVE:
        return set()
    definition = task.get("taskDefinition") or {}
    position, condition = inst["position"], inst["condition"]
    rounds = definition.get("rounds", [])
    verdicts = [r for r in rounds if r.get("verdict")]
    out = set()
    if position == commands.HUMAN:
        out.add("definition.submit")
    if position in (commands.DISPATCH, commands.CONTINUE) and condition != states.RECOVERY_REQUIRED:
        out |= {"definition.dispatch", "definition.formal-authorize"}
        if verdicts and verdicts[-1]["verdict"]["verdict"] == "FAIL" and rounds[-1] is verdicts[-1]:
            out.add("definition.submit")
    if position in (gate.AUTH_GATE, gate.ESCALATION_GATE):
        out.add("definition.decide")
    if position == gate.VERDICT_DECISION and rounds and rounds[-1].get("status") == "awaiting-human-disposition":
        out.add("definition.decide")
    return out


def rows(state):
    return [dict(taskId=task_id, legal=sorted(legal(state, task_id)))
            for task_id, task in sorted(state.get("tasks", {}).items()) if "lifecycle" in (task.get("workflowInstance") or {})]


def action(scope, action_id, table, cap):
    enabled = any(action_id in row["legal"] for row in table)
    return dict(scopeRef=scope, actionId=action_id, objectRef=OBJECT, capability=copy.deepcopy(cap),
                label=action_id, expectedRevision=str(len(table)), candidateRef=None,
                payloadSchemaDigest=DOCUMENT.payload_digest(action_id), enabled=enabled,
                disabledReason="" if enabled else "No task is at a position where this Definition action is legal",
                disabledCode=None if enabled else "DEFINITION_ACTION_NOT_LEGAL_HERE", requiresHumanDecision=True)


def definition_object(scope, table, cap):
    view = [dict(id=r["taskId"], title=r["taskId"], detail=", ".join(r["legal"]) or "no Definition action") for r in table]
    return dict(scopeRef=scope, objectRef=OBJECT, revision=str(len(table)), title="Task Definition", stateLabel="ready",
                capability=copy.deepcopy(cap), view=dict(kind="list", rows=view[:100]), evidence=[])


def refresh(state):
    cap = capability()
    table = rows(state)
    for scope, view in state.get("scopes", {}).items():
        view["objects"] = [o for o in view["objects"] if o["objectRef"] != OBJECT] + [definition_object(scope, table, cap)]
        view["actions"] = [a for a in view["actions"] if a["actionId"] not in ACTIONS] + [
            action(scope, action_id, table, cap) for action_id in ACTIONS]
