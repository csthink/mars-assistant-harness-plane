"""Read-only Runtime projection of Workflow state (spec FR-53 semantics, NFR-04).

The projection derives everything from the domain state and holds no state of its own. The set of
legal actions is computed from the Workflow position, so an interface cannot widen authority by
displaying something: an action the state does not allow is projected disabled, and the domain
refuses it again at commit time with the same rule.
"""
import copy

from domain import capability_schema
from domain.workflow import progression, states
from domain.workflow.schema import CLOSE_ID, DECIDE_ID, SCHEMAS

CAPABILITY_ID = "harness.workflow"
CAPABILITY_VERSION = "2"
WORKFLOW_OBJECT = "workflow:tasks"
ACTION_DECIDE = "workflow.decide"
ACTION_CLOSE = "workflow.close"
ACTIONS = {ACTION_DECIDE: DECIDE_ID, ACTION_CLOSE: CLOSE_ID}
# OD-425: the capability's negotiated schema is its primary action's payload schema with every other action's
# payload schema as a root `definitions` entry named by the actionId (domain/capability_schema.py); the
# document changed, so the capability version did.
DOCUMENT = capability_schema.CapabilityDocument(ACTION_DECIDE, ACTIONS, SCHEMAS)
NO_GATE = "NO_LEGAL_DECISION_AT_CURRENT_POSITION"
NO_ACTIVE = "NO_NON_TERMINAL_TASK"


def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DOCUMENT.digest, required=False)


def instance_rows(state, resolve, exclude=None):
    """One row per accepted Task carrying the layered facts and the legal decision set.

    exclude(position, decisions) removes decisions the generic entry may not submit (feature-t3 keeps
    the two Definition-freezing decisions on its own entry); None keeps the feature-t2 behaviour.
    """
    rows = []
    for task_id, task in sorted(state.get("tasks", {}).items()):
        inst = task.get("workflowInstance") or {}
        if "lifecycle" not in inst:
            continue
        topology = resolve(inst)
        if topology is None:
            rows.append(dict(taskId=task_id, lifecycle=inst["lifecycle"], position=inst["position"],
                             condition=inst["condition"], runtimeVersion=inst["runtimeVersion"],
                             decisions=[], topology="unreadable"))
            continue
        rows.append(dict(taskId=task_id, **{k: inst[k] for k in ("lifecycle", "position", "condition", "runtimeVersion")},
                         positionLabel=topology.label(inst["position"]),
                         semanticType=topology.semantic_type(inst["position"]),
                         decisions=[d["decision"] for d in (exclude or (lambda _p, ds: ds))(inst["position"], progression.decisions(inst, topology))],
                         topology="bound"))
    return rows


def workflow_object(scope, rows, cap):
    view = [dict(id=r["taskId"], title=r["taskId"],
                 detail="{lifecycle} · {position} · {condition} · v{runtimeVersion}".format(**r)) for r in rows]
    return dict(scopeRef=scope, objectRef=WORKFLOW_OBJECT, revision=str(len(rows)), title="Workflow state",
                stateLabel="ready", capability=copy.deepcopy(cap), view=dict(kind="list", rows=view[:100]), evidence=[])


def decide_action(scope, rows, cap):
    gated = [r for r in rows if r["decisions"]]
    return dict(scopeRef=scope, actionId=ACTION_DECIDE, objectRef=WORKFLOW_OBJECT, capability=copy.deepcopy(cap),
                label="Record a Human Gate decision", expectedRevision=str(len(rows)), candidateRef=None,
                payloadSchemaDigest=DOCUMENT.payload_digest(ACTION_DECIDE), enabled=bool(gated),
                disabledReason="" if gated else "No task is waiting at a Human Gate",
                disabledCode=None if gated else NO_GATE, requiresHumanDecision=True)


def close_action(scope, rows, cap):
    open_tasks = [r for r in rows if r["lifecycle"] == states.ACTIVE]
    return dict(scopeRef=scope, actionId=ACTION_CLOSE, objectRef=WORKFLOW_OBJECT, capability=copy.deepcopy(cap),
                label="Close a non-terminal task", expectedRevision=str(len(rows)), candidateRef=None,
                payloadSchemaDigest=DOCUMENT.payload_digest(ACTION_CLOSE), enabled=bool(open_tasks),
                disabledReason="" if open_tasks else "Every task reached a terminal lifecycle",
                disabledCode=None if open_tasks else NO_ACTIVE, requiresHumanDecision=True)


def actions(scope, rows, cap):
    return [decide_action(scope, rows, cap), close_action(scope, rows, cap)]


def refresh(state, resolve, exclude=None):
    """Rebuild the Workflow object and the two Workflow actions in every open scope."""
    cap = capability()
    rows = instance_rows(state, resolve, exclude)
    ours = {ACTION_DECIDE, ACTION_CLOSE}
    for scope, view in state.get("scopes", {}).items():
        view["objects"] = [o for o in view["objects"] if o["objectRef"] != WORKFLOW_OBJECT] + [workflow_object(scope, rows, cap)]
        view["actions"] = [a for a in view["actions"] if a["actionId"] not in ours] + actions(scope, rows, cap)
