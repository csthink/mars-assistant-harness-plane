"""Command table feature-t7 adds for Publish, and the narrowing of generic commands at the two Publish nodes.

Both entries reach these through core.apply_command with feature-t3's Definition context (repository root,
calling entry) and the Policy inputs, so neither holds a second rule set. guard() refuses feature-t2's generic
fact / advance / condition / attempt / reservation commands and also `publish-finalize`, `recover-assess` and
`recover` at the Publish Authorization Gate and the Publish node for every task: a generic walk there could
cross the gate without a binding, record a publish result no remote produced, or self-report a recovery
assessment. Close Task (FR-27) stays open everywhere.
"""
from domain.publish import dispatch, gate, recovery, settle
from domain.publish.results import GENERIC_COMMAND_NARROWED, INPUT_INVALID, PublishRejection
from domain.workflow import progression
from domain.workflow.results import ILLEGAL_TRANSITION, WorkflowRejection

COMMANDS = ("publish-authorize", "publish-dispatch", "publish-query", "publish-reconcile")
GUARDED_NODES = (gate.GATE, gate.PUBLISH_NODE)
GUARDED_GENERIC = ("fact", "advance", "condition", "attempt-open", "attempt-settle", "attempt-start", "reserve",
                   "reservation-settle", "publish-finalize", "recover-assess", "recover")
EXECUTION_SETTLE = {dispatch.PURPOSE: settle.settle_publish, dispatch.QUERY_PURPOSE: settle.settle_query}


def guard(state, task_id, name):
    if name not in GUARDED_GENERIC:
        return
    task = state.get("tasks", {}).get(task_id)
    if task is None:
        return
    position = task["workflowInstance"]["position"]
    if position in GUARDED_NODES:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "this Publish node is driven only through the publish entry; the generic "
                                "command cannot record its facts, move it, finalise it or assess its recovery",
                                command=name, position=position, reasonCode=GENERIC_COMMAND_NARROWED, entry="harness publish")


def _required(payload):
    command_id, authority = payload.get("commandId"), payload.get("authorityRef")
    if not isinstance(command_id, str) or not command_id:
        raise PublishRejection(INPUT_INVALID, "commandId is required", field="commandId")
    if not isinstance(authority, str) or not authority:
        raise WorkflowRejection("AUTHORITY_MISSING", "authorityRef is required: every progression binds to an authorising fact")
    return command_id, authority


def _version(inst, payload):
    expected = payload.get("expectedRuntimeVersion")
    if expected is not None and str(expected) != inst["runtimeVersion"]:
        raise WorkflowRejection("VERSION_CONFLICT", "expected Runtime Version does not match the current one",
                                expected=str(expected), current=inst["runtimeVersion"])


def apply(state, resolve, name, payload, *, revision, context, inputs):
    task_id = payload.get("taskId")
    inst = progression.instance(state, task_id)
    topology = resolve(inst)
    if topology is None:
        raise WorkflowRejection("TOPOLOGY_UNREADABLE", "the bound Workflow topology could not be read")
    command_id, authority = _required(payload)
    _version(inst, payload)
    if name == "publish-authorize":
        return gate.authorize(state, topology, context, payload, command_id, authority)
    if name == "publish-dispatch":
        return dispatch.dispatch(state, topology, context, payload, command_id, authority, inputs)
    if name == "publish-query":
        return recovery.query(state, topology, context, payload, command_id, authority)
    if name == "publish-reconcile":
        return recovery.reconcile(state, topology, context, payload, command_id, authority, inputs)
    raise PublishRejection(INPUT_INVALID, "unknown publish command", command=name, commands=list(COMMANDS))
