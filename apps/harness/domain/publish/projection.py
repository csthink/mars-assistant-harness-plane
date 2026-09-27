"""Read-only Runtime projection of the Publish actions (NFR-04: the state derives the legal set).

The loop object lists, per task, the legal Publish actions and, while a task waits at the Publish
Authorization Gate, the digest of its Publish authorization context: the value the trusted Human decision must
carry in `contextDigest` (the full view is read with `harness publish context`).
"""
import copy

from domain import capability_schema
from domain.publish import context as publish_context, gate, records
from domain.publish.schema import AUTHORIZE_ID, DISPATCH_ID, QUERY_ID, RECONCILE_ID, SCHEMAS
from domain.workflow import recovery, states

CAPABILITY_ID = "harness.publish"
CAPABILITY_VERSION = "2"
OBJECT = "publish:tasks"
AUTHORIZE, DISPATCH, QUERY, RECONCILE = "publish.authorize", "publish.dispatch", "publish.query", "publish.reconcile"
ACTIONS = {AUTHORIZE: AUTHORIZE_ID, DISPATCH: DISPATCH_ID, QUERY: QUERY_ID, RECONCILE: RECONCILE_ID}
# OD-425: the capability's negotiated schema is its primary action's payload schema with every other action's
# payload schema as a root `definitions` entry named by the actionId (domain/capability_schema.py); the
# document changed, so the capability version did.
DOCUMENT = capability_schema.CapabilityDocument(DISPATCH, ACTIONS, SCHEMAS)
COMMAND_OF = {AUTHORIZE: "publish-authorize", DISPATCH: "publish-dispatch", QUERY: "publish-query", RECONCILE: "publish-reconcile"}


def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DOCUMENT.digest, required=False)


def legal(state, task_id):
    task = state["tasks"][task_id]
    inst = task.get("workflowInstance") or {}
    if inst.get("lifecycle") != states.ACTIVE:
        return set()
    position, condition = inst["position"], inst["condition"]
    flight = records.in_flight(state, task_id)
    out = set()
    if position == gate.GATE and condition == states.AWAITING_HUMAN_ACTION:
        out.add(AUTHORIZE)
    if position == gate.PUBLISH_NODE and not flight and (task.get("publish") or {}).get("operation"):
        if condition == states.ENTERED:
            out.add(DISPATCH)
        if condition == states.RECOVERY_REQUIRED:
            out.add(QUERY)
            current = inst["recovery"]["current"]
            assessment = inst["recovery"]["assessments"].get(current) if current else None
            if assessment and assessment["assessment"] == recovery.RECONCILIATION_REQUIRED and assessment["consumedBy"] is None:
                out.add(RECONCILE)
    return out


def rows(state, repository=None):
    out = []
    for task_id, task in sorted(state.get("tasks", {}).items()):
        inst = task.get("workflowInstance") or {}
        if "lifecycle" not in inst:
            continue
        row = dict(taskId=task_id, legal=sorted(legal(state, task_id)))
        if repository is not None and AUTHORIZE in row["legal"]:
            row["contextDigest"] = publish_context.digest(publish_context.view(state, repository, task_id))
        out.append(row)
    return out


def action(scope, action_id, table, cap):
    enabled = any(action_id in row["legal"] for row in table)
    return dict(scopeRef=scope, actionId=action_id, objectRef=OBJECT, capability=copy.deepcopy(cap), label=action_id,
                expectedRevision=str(len(table)), candidateRef=None, payloadSchemaDigest=DOCUMENT.payload_digest(action_id),
                enabled=enabled, disabledReason="" if enabled else "No task is at a position where this Publish action is legal",
                disabledCode=None if enabled else "PUBLISH_ACTION_NOT_LEGAL_HERE", requiresHumanDecision=True)


def loop_object(scope, table, cap):
    view = [dict(id=r["taskId"], title=r["taskId"],
                 detail=(", ".join(r["legal"]) or "no Publish action") + (
                     "; contextDigest " + r["contextDigest"] if r.get("contextDigest") else "")) for r in table]
    return dict(scopeRef=scope, objectRef=OBJECT, revision=str(len(table)), title="Publish", stateLabel="ready",
                capability=copy.deepcopy(cap), view=dict(kind="list", rows=view[:100]), evidence=[])


def refresh(state, repository=None):
    if not state.get("scopes"):
        return
    cap = capability()
    table = rows(state, repository)
    for scope, view in state.get("scopes", {}).items():
        view["objects"] = [o for o in view["objects"] if o["objectRef"] != OBJECT] + [loop_object(scope, table, cap)]
        view["actions"] = [a for a in view["actions"] if a["actionId"] not in ACTIONS] + [
            action(scope, action_id, table, cap) for action_id in ACTIONS]
