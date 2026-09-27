"""Command table feature-t5 adds for the Validate Change loop, and the narrowing of generic commands there.

Both entries reach these through core.apply_command with feature-t3's Definition context (repository,
repository root, calling entry, authorization availability check), so neither holds a second rule set.
guard() refuses feature-t2's generic fact / condition / advance / attempt / reservation commands at every
Validate Change node for every task (not only for tasks this loop has driven): a generic walk there could
record a PASS no reviewer produced or cross the Validation budget. Close Task (FR-27) and the
Human-authorised recovery commands stay open; Continue and Close Task at the escalation gate keep the
generic decide (progression.decide moves the gate internally, not through a generic command).
"""
from domain.validation import config, dispatch, gate, verdict
from domain.validation.results import INPUT_INVALID, POSITION_NOT_APPLICABLE, ValidationRejection
from domain.workflow import progression
from domain.workflow.results import ILLEGAL_TRANSITION, WorkflowRejection

COMMANDS = ("validate-configure", "validate-formal-authorize", "validate-dispatch", "validate-dispose", "validate-decide",
            "validate-resume")
GUARDED_NODES = (config.CONFIG, dispatch.REVIEWER, verdict.VERDICT_DECISION, gate.ESCALATION_GATE, gate.REMEDIATION_NODE,
                 gate.CONTINUE_NODE, gate.ACCEPT_NODE)
GUARDED_GENERIC = ("fact", "advance", "condition", "attempt-open", "attempt-settle", "attempt-start", "reserve",
                   "reservation-settle")
EXECUTION_SETTLE = {dispatch.PURPOSE: verdict.settle, gate.RULING_PURPOSE: gate.settle_disposition}


def guard(state, task_id, name):
    if name not in GUARDED_GENERIC:
        return
    task = state.get("tasks", {}).get(task_id)
    if task is None:
        return
    position = task["workflowInstance"]["position"]
    if position in GUARDED_NODES:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "this Validate Change node is driven only through the validate entry; "
                                "the generic command cannot record its facts or move it", command=name, position=position,
                                reasonCode="GENERIC_COMMAND_NARROWED", entry="harness validate")


def _required(payload):
    command_id, authority = payload.get("commandId"), payload.get("authorityRef")
    if not isinstance(command_id, str) or not command_id:
        raise ValidationRejection(INPUT_INVALID, "commandId is required")
    if not isinstance(authority, str) or not authority:
        raise WorkflowRejection("AUTHORITY_MISSING", "authorityRef is required: every progression binds to an authorising fact")
    return command_id, authority


def _version(inst, payload):
    expected = payload.get("expectedRuntimeVersion")
    if expected is not None and str(expected) != inst["runtimeVersion"]:
        raise WorkflowRejection("VERSION_CONFLICT", "expected Runtime Version does not match the current one",
                                expected=str(expected), current=inst["runtimeVersion"])


def apply(state, resolve, name, payload, *, revision, context):
    task_id = payload.get("taskId")
    inst = progression.instance(state, task_id)
    topology = resolve(inst)
    if topology is None:
        raise WorkflowRejection("TOPOLOGY_UNREADABLE", "the bound Workflow topology could not be read")
    command_id, authority = _required(payload)
    _version(inst, payload)
    if name == "validate-configure":
        return config.configure(state, topology, task_id, payload, command_id, authority)
    if name == "validate-formal-authorize":
        return dispatch.formal_authorize(state, topology, context, payload, command_id, authority)
    if name == "validate-dispatch":
        return dispatch.dispatch(state, topology, context, payload, command_id, authority)
    if name == "validate-dispose":
        return gate.dispose(state, topology, context, payload, command_id, authority)
    if name == "validate-decide":
        if payload.get("decision") != gate.ACCEPT_RESERVATION:
            raise ValidationRejection(POSITION_NOT_APPLICABLE, "only Accept With reservation uses the validate entry; "
                                      "Continue and Close Task use the generic decide", decision=payload.get("decision"))
        return gate.accept_with_reservation(state, topology, task_id, payload, command_id, authority, context=context)
    if name == "validate-resume":
        return gate.resume(state, topology, task_id, payload, command_id, authority)
    raise ValidationRejection(POSITION_NOT_APPLICABLE, "unknown validate command", command=name, commands=list(COMMANDS))
