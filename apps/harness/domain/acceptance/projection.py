"""Runtime-facing projection of accepted tasks. Derived from domain records; never a second state."""
import copy

from domain.acceptance.schema import DIGEST

CAPABILITY_ID = "harness.task-acceptance"
CAPABILITY_VERSION = "1"
SOURCES_OBJECT = "sources:milestones"
SOURCES_REVISION = "1"
ACTION_ID = "task.accept"

def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DIGEST, required=False)

def task_object(scope, task, cap):
    rows = [dict(id="branch", title="Task Branch", detail=task["branch"]),
            dict(id="worktree", title="worktree", detail=task["worktree"]),
            dict(id="anchor", title="Canonical Source Anchor", detail=task["anchor"]["digest"]),
            dict(id="revision", title="source revision", detail=task["anchor"]["sourceRevision"]),
            dict(id="position", title="Workflow position", detail=task["workflowInstance"]["position"])]
    state = task["terminal"]["kind"] if task.get("terminal") else "accepted"
    return dict(scopeRef=scope, objectRef=task["taskRef"], revision=task["acceptedRevision"], title=task["taskId"],
                stateLabel=state, capability=copy.deepcopy(cap), view=dict(kind="list", rows=rows), evidence=[])

def sources_object(scope, state, cap):
    rows = [dict(id=t["taskRef"], title=t["taskId"], detail=t["branch"]) for t in state["tasks"].values()]
    return dict(scopeRef=scope, objectRef=SOURCES_OBJECT, revision=SOURCES_REVISION, title="Task acceptance",
                stateLabel="ready", capability=copy.deepcopy(cap), view=dict(kind="list", rows=rows[:100]), evidence=[])

def accept_action(scope, cap):
    return dict(scopeRef=scope, actionId=ACTION_ID, objectRef=SOURCES_OBJECT, capability=copy.deepcopy(cap),
                label="Accept a milestones task", expectedRevision=SOURCES_REVISION, candidateRef=None,
                payloadSchemaDigest=DIGEST, enabled=True, disabledReason="", disabledCode=None,
                requiresHumanDecision=True)

def refresh(state):
    """Rebuild acceptance objects and the single legal action in every open scope."""
    cap = capability()
    for scope, view in state.get("scopes", {}).items():
        others = [o for o in view["objects"] if not (o["objectRef"] == SOURCES_OBJECT or o["objectRef"].startswith("task:"))]
        view["objects"] = others + [sources_object(scope, state, cap)] + [task_object(scope, t, cap) for t in state["tasks"].values()]
        view["actions"] = [a for a in view["actions"] if a["actionId"] != ACTION_ID] + [accept_action(scope, cap)]
