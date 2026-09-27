"""Read-only Runtime projection of the Implement and Verify actions (NFR-04: the state derives the legal set).

Each action is enabled only where the current Workflow position and condition allow it and no execution
of this loop is in flight on the task; the dispatcher re-reads the action before durable acceptance, so
a projected action that has become illegal is refused. The Host gains no authority here: an accepted
action runs the same domain command the standalone CLI runs, under the Human decision the Runtime
verified, and the execution authorization still comes only from feature-t6's Policy Gate.
"""
import copy

from domain import capability_schema
from domain.implement_verify import dispatch, verify
from domain.implement_verify.schema import DISPATCH_ID, SCHEMAS, VERIFY_ID
from domain.workflow import states

CAPABILITY_ID = "harness.implement-verify"
CAPABILITY_VERSION = "2"
OBJECT = "implement-verify:tasks"
DISPATCH = "implement.dispatch"
VERIFY = "verify.run"
ACTIONS = {DISPATCH: DISPATCH_ID, VERIFY: VERIFY_ID}
# OD-425: the capability's negotiated schema is its primary action's payload schema with every other action's
# payload schema as a root `definitions` entry named by the actionId (domain/capability_schema.py); the
# document changed, so the capability version did.
DOCUMENT = capability_schema.CapabilityDocument(DISPATCH, ACTIONS, SCHEMAS)


def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DOCUMENT.digest, required=False)


def _in_flight(task):
    records = (task.get("implementVerify") or {}).get("executions", {}).values()
    return any(r["status"] in ("dispatched", "running") for r in records)


def legal(state, task_id):
    """Action ids legal for one task now; derived from position, condition and this loop's own records."""
    task = state["tasks"][task_id]
    inst = task.get("workflowInstance") or {}
    if inst.get("lifecycle") != states.ACTIVE or inst.get("condition") == states.RECOVERY_REQUIRED or _in_flight(task):
        return set()
    position, condition = inst["position"], inst["condition"]
    out = set()
    if position in dispatch.DISPATCH_EDGES or position == dispatch.CONTINUE_EDGE[0] or \
            (position == dispatch.IMPLEMENT_NODE and condition == states.ENTERED):
        out.add(DISPATCH)
    if position == verify.APPLICABILITY_NODE or (position == verify.VERIFY_NODE and condition == states.ENTERED):
        out.add(VERIFY)
    return out


def rows(state):
    return [dict(taskId=task_id, legal=sorted(legal(state, task_id)))
            for task_id, task in sorted(state.get("tasks", {}).items()) if "lifecycle" in (task.get("workflowInstance") or {})]


def action(scope, action_id, table, cap):
    enabled = any(action_id in row["legal"] for row in table)
    return dict(scopeRef=scope, actionId=action_id, objectRef=OBJECT, capability=copy.deepcopy(cap),
                label=action_id, expectedRevision=str(len(table)), candidateRef=None,
                payloadSchemaDigest=DOCUMENT.payload_digest(action_id), enabled=enabled,
                disabledReason="" if enabled else "No task is at a position where this Implement/Verify action is legal",
                disabledCode=None if enabled else "IMPLEMENT_VERIFY_ACTION_NOT_LEGAL_HERE", requiresHumanDecision=True)


def loop_object(scope, table, cap):
    view = [dict(id=r["taskId"], title=r["taskId"], detail=", ".join(r["legal"]) or "no Implement/Verify action")
            for r in table]
    return dict(scopeRef=scope, objectRef=OBJECT, revision=str(len(table)), title="Implement and Verify",
                stateLabel="ready", capability=copy.deepcopy(cap), view=dict(kind="list", rows=view[:100]), evidence=[])


def refresh(state):
    cap = capability()
    table = rows(state)
    for scope, view in state.get("scopes", {}).items():
        view["objects"] = [o for o in view["objects"] if o["objectRef"] != OBJECT] + [loop_object(scope, table, cap)]
        view["actions"] = [a for a in view["actions"] if a["actionId"] not in ACTIONS] + [
            action(scope, action_id, table, cap) for action_id in ACTIONS]
