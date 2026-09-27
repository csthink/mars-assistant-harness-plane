"""Read-only Runtime projection of the Validate Change actions (NFR-04: the state derives the legal set)."""
import copy

from domain import capability_schema
from domain.validation import config, dispatch, gate, verdict
from domain.validation.schema import (
    CONFIGURE_ID, DECIDE_ID, DISPATCH_ID, DISPOSE_ID, FORMAL_ID, RESUME_ID, SCHEMAS,
)
from domain.workflow import states

CAPABILITY_ID = "harness.validate-change"
CAPABILITY_VERSION = "2"
OBJECT = "validate-change:tasks"
CONFIGURE, DISPATCH, FORMAL, DISPOSE, DECIDE, RESUME = ("validate.configure", "validate.dispatch", "validate.formal-authorize",
                                                        "validate.dispose", "validate.decide", "validate.resume")
ACTIONS = {CONFIGURE: CONFIGURE_ID, DISPATCH: DISPATCH_ID, FORMAL: FORMAL_ID, DISPOSE: DISPOSE_ID, DECIDE: DECIDE_ID,
           RESUME: RESUME_ID}
# OD-425: the capability's negotiated schema is its primary action's payload schema with every other action's
# payload schema as a root `definitions` entry named by the actionId (domain/capability_schema.py); the
# document changed, so the capability version did.
DOCUMENT = capability_schema.CapabilityDocument(CONFIGURE, ACTIONS, SCHEMAS)
COMMAND_OF = {CONFIGURE: "validate-configure", DISPATCH: "validate-dispatch", FORMAL: "validate-formal-authorize",
              DISPOSE: "validate-dispose", DECIDE: "validate-decide", RESUME: "validate-resume"}


def capability():
    return dict(id=CAPABILITY_ID, version=CAPABILITY_VERSION, schemaDigest=DOCUMENT.digest, required=False)


def legal(state, task_id):
    task = state["tasks"][task_id]
    inst = task.get("workflowInstance") or {}
    if inst.get("lifecycle") != states.ACTIVE or inst.get("condition") == states.RECOVERY_REQUIRED:
        return set()
    record = task.get("validateChange") or {}
    rounds = record.get("rounds", [])
    in_flight = any(r["status"] in ("dispatched", "running") for r in rounds)
    position, condition = inst["position"], inst["condition"]
    out = set()
    if position == config.CONFIG:
        out.add(CONFIGURE)
    if position == dispatch.REVIEWER and condition == states.ENTERED and not in_flight:
        out |= {DISPATCH, FORMAL}
    if position == verdict.VERDICT_DECISION and rounds and rounds[-1].get("status") == "awaiting-human-disposition":
        out.add(DISPOSE)
    if position == gate.ESCALATION_GATE:
        out.add(DECIDE)
    if position == gate.CONTINUE_NODE:
        out.add(RESUME)
    return out


def rows(state):
    return [dict(taskId=task_id, legal=sorted(legal(state, task_id)))
            for task_id, task in sorted(state.get("tasks", {}).items()) if "lifecycle" in (task.get("workflowInstance") or {})]


def action(scope, action_id, table, cap):
    enabled = any(action_id in row["legal"] for row in table)
    return dict(scopeRef=scope, actionId=action_id, objectRef=OBJECT, capability=copy.deepcopy(cap), label=action_id,
                expectedRevision=str(len(table)), candidateRef=None, payloadSchemaDigest=DOCUMENT.payload_digest(action_id),
                enabled=enabled, disabledReason="" if enabled else "No task is at a position where this Validate Change action is legal",
                disabledCode=None if enabled else "VALIDATE_ACTION_NOT_LEGAL_HERE", requiresHumanDecision=True)


def loop_object(scope, table, cap):
    view = [dict(id=r["taskId"], title=r["taskId"], detail=", ".join(r["legal"]) or "no Validate Change action") for r in table]
    return dict(scopeRef=scope, objectRef=OBJECT, revision=str(len(table)), title="Validate Change", stateLabel="ready",
                capability=copy.deepcopy(cap), view=dict(kind="list", rows=view[:100]), evidence=[])


def refresh(state):
    cap = capability()
    table = rows(state)
    for scope, view in state.get("scopes", {}).items():
        view["objects"] = [o for o in view["objects"] if o["objectRef"] != OBJECT] + [loop_object(scope, table, cap)]
        view["actions"] = [a for a in view["actions"] if a["actionId"] not in ACTIONS] + [
            action(scope, action_id, table, cap) for action_id in ACTIONS]
