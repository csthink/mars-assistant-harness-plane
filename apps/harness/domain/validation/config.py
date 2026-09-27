"""`Validate Change · Enabled?`: read the switch recorded at acceptance, record it, take Enabled or Disabled.

The switch value and its source (`default` or `configuration`) come from the Workflow Instance record
feature-t0 wrote at acceptance; this module never reads the live configuration and never changes the
default (delivery-method r18 §8, Assistant OD-388). The recorded configuration-decision fact is the
configuration snapshot FR-43 asks for; the Disabled path creates no Reviewer attempt.
"""
import copy

from domain.validation import records
from domain.validation.results import IDEMPOTENT_REPLAY, POSITION_NOT_APPLICABLE, VALIDATION_CONFIGURED, ValidationRejection
from domain.workflow import progression, states
from domain.workflow.results import RECOVERY_REQUIRED_BLOCKS_PROGRESSION, WorkflowRejection

CONFIG = "N-VALIDATE-CONFIG"
PUBLISH_GATE = "N-PUBLISH-AUTH-GATE"
PURPOSE = "change-validation-config"


def walk(state, topology, task_id, target, command_id, authority):
    inst = progression.instance(state, task_id)
    node = inst["position"]
    semantic = topology.semantic_type(node)
    step = 0
    while inst["condition"] != target:
        nxt = states.next_condition(node, semantic, inst["condition"])
        if nxt is None:
            break
        progression.update_condition(state, topology, task_id, dict(commandId="%s:c%d" % (command_id, step),
                                                                    condition=nxt, authorityRef=authority),
                                     revision=state["revision"])
        step += 1


def advance(state, topology, task_id, command_id, edge, authority, triggers=(), purpose=None):
    return progression.advance(state, topology, task_id, dict(commandId=command_id, edgeId=edge, triggers=list(triggers),
                                                              purpose=purpose, authorityRef=authority),
                               revision=state["revision"])


def await_human(state, topology, task_id, command_id, authority):
    inst = progression.instance(state, task_id)
    if inst["condition"] == states.ENTERED:
        progression.update_condition(state, topology, task_id, dict(commandId=command_id + ":await",
                                                                    condition=states.AWAITING_HUMAN_ACTION,
                                                                    authorityRef=authority), revision=state["revision"])


def configure(state, topology, task_id, payload, command_id, authority):
    record = records.ledger(state, task_id)
    for done in record["configurations"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, configuration=copy.deepcopy(done))
    inst = progression.instance(state, task_id)
    if inst["position"] != CONFIG:
        raise ValidationRejection(POSITION_NOT_APPLICABLE, "the switch is read only at Validate Change · Enabled?",
                                  position=inst["position"])
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection(RECOVERY_REQUIRED_BLOCKS_PROGRESSION, "the configuration node needs recovery first")
    snapshot = copy.deepcopy(inst["reviewConfiguration"])
    enabled = bool(snapshot.get("changeValidation"))
    walk(state, topology, task_id, states.RESULT_RECORDED, command_id + ":config", authority)
    fact_id = command_id + ":validate-switch"
    progression.record_fact(state, topology, task_id, dict(
        factId=fact_id, kind="configuration-decision", purpose=PURPOSE, authorityRef=authority,
        payload=dict(changeValidation=enabled, source=snapshot.get("source"), reviewConfiguration=snapshot,
                     readRevision=str(state["revision"]))), revision=state["revision"])
    edge = "E-V01" if enabled else "E-V02"
    advance(state, topology, task_id, command_id + ":" + edge, edge, authority, [fact_id], PURPOSE)
    if not enabled:
        await_human(state, topology, task_id, command_id, authority)
    done = dict(commandId=command_id, factId=fact_id, changeValidation=enabled, source=snapshot.get("source"),
                edge=edge, occurrence=progression.occurrence(inst, task_id), authorityRef=authority,
                recordedRevision=str(state["revision"]))
    record["configurations"].append(done)
    return dict(result=VALIDATION_CONFIGURED, configuration=copy.deepcopy(done), position=inst["position"],
                condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])
