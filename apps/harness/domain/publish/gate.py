"""`Human Gate · Publish Authorization`: the exact Publish authorization, and the narrowing of the generic decide.

`Publish authorization` must carry the exact binding and the digest of the context the Human saw (FR-29,
FR-26). The generic `workflow decide` path can carry neither, so it refuses exactly this decision and the
workflow.decide projection stops listing it (an intentional narrowing of feature-t2, Definition Scope In,
same form as feature-t3's and feature-t5's). The recorded human-decision fact is a superset of the shape
progression.decide writes, so feature-t6's Human Gate chain check and push permit read it unchanged.
"""
import copy
from datetime import datetime, timezone

from domain.publish import binding as publish_binding, records
from domain.publish.results import IDEMPOTENT_REPLAY, INPUT_INVALID, POSITION_NOT_APPLICABLE, PUBLISH_AUTHORIZED, PublishRejection
from domain.workflow import progression, states
from domain.workflow.results import DECISION_NOT_LEGAL_HERE, RECOVERY_REQUIRED_BLOCKS_PROGRESSION, WorkflowRejection

GATE = "N-PUBLISH-AUTH-GATE"
PUBLISH_NODE = "N-PUBLISH"
DECISION = "Publish authorization"
EDGE = "E-V06"
PUBLISH_ENTRY_DECISIONS = frozenset({(GATE, DECISION)})


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def requires_publish_entry(position, decision):
    return (position, decision) in PUBLISH_ENTRY_DECISIONS


def generic_filter(position, decisions):
    """Drop the decision the generic entry may not submit; used by the workflow projection and status."""
    return [d for d in decisions
            if (position, d["decision"] if isinstance(d, dict) else d) not in PUBLISH_ENTRY_DECISIONS]


def decision_text(payload):
    text = payload.get("decisionText")
    if not isinstance(text, str) or not text.strip() or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise PublishRejection(INPUT_INVALID, "decisionText carries the Human's exact words on one line", field="decisionText")
    return text


def authorize(state, topology, context, payload, command_id, authority):
    task_id = payload["taskId"]
    record = records.ledger(state, task_id)
    done = record.get("authorization")
    if done is not None and done["commandId"] == command_id:
        return dict(result=IDEMPOTENT_REPLAY, authorization=copy.deepcopy(done))
    inst = progression.instance(state, task_id)
    if inst["lifecycle"] != states.ACTIVE or inst["position"] != GATE:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "Publish authorization is decided at the Publish Authorization Gate",
                               position=inst["position"], lifecycle=inst["lifecycle"])
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection(RECOVERY_REQUIRED_BLOCKS_PROGRESSION, "the Publish Authorization Gate needs recovery first")
    if inst["condition"] != states.AWAITING_HUMAN_ACTION:
        raise PublishRejection(POSITION_NOT_APPLICABLE, "the Publish Authorization Gate is not waiting for a Human decision",
                               condition=inst["condition"])
    legal = [d["decision"] for d in progression.decisions(inst, topology)]
    if DECISION not in legal:
        raise WorkflowRejection(DECISION_NOT_LEGAL_HERE, "this decision is not in the legal set here", legal=legal)
    text = decision_text(payload)
    bound, digest = publish_binding.require(state, context.repository_root, task_id, payload.get("publishBinding"),
                                            payload.get("contextDigest"))
    progression.update_condition(state, topology, task_id, dict(commandId=command_id + ":record", condition=states.RESULT_RECORDED,
                                                                authorityRef=authority), revision=state["revision"])
    fact_id = command_id + ":decision"
    operation = records.operation_id(task_id, fact_id)
    progression.record_fact(state, topology, task_id, dict(
        factId=fact_id, kind="human-decision", purpose="gate-decision", authorityRef=authority,
        payload=dict(decision=DECISION, edgeId=EDGE, reservation=None, publishBinding=copy.deepcopy(bound), decisionText=text,
                     publishContextDigest=digest, operation=operation)), revision=state["revision"])
    progression.advance(state, topology, task_id, dict(commandId=command_id, edgeId=EDGE, triggers=[fact_id],
                                                       purpose="gate-decision", authorityRef=authority), revision=state["revision"])
    records.register_authorization(state, task_id, command_id=command_id, fact_id=fact_id, edge=EDGE, binding=bound,
                                   context_digest=digest, decision_text=text, authority=authority, at=now())
    return dict(result=PUBLISH_AUTHORIZED, authorization=copy.deepcopy(record["authorization"]), operation=operation,
                position=inst["position"], condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])
