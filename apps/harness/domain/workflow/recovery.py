"""Recovery of a current node in RECOVERY_REQUIRED (spec FR-30; D-05 logical contract).

Assessment is read-only and produces exactly one of four mutually exclusive results. Each result maps
to exactly one legal action, and an assessment is consumed once: a change of Current Position,
occurrence or Runtime Version invalidates it, and so does any action that consumes it. Recovery stays
inside the same occurrence, adds no Node, Edge or Gate, never fabricates a business result and never
crosses a business edge in the same commit. INDETERMINATE can never be rewritten into one of the
other three by any path, Human included.

Authority boundary: read-only assessment and non-mutating reconciliation probes run automatically;
restarting the node, any reconciliation that changes the repository or an external system, and any
evidence collection that widens credentials, network, filesystem or tool permissions each require a
single-use Human Recovery Action Authorization bound to the instance, occurrence, expected Runtime
Version, assessment, exact action and allowed effect scope.
"""
import copy

from domain.workflow import progression, states
from domain.workflow.progression import instance, now, occurrence
from domain.workflow.results import (
    ASSESSMENT_ALREADY_CONSUMED, ASSESSMENT_STALE, AUTHORITY_MISSING, IDEMPOTENT_REPLAY,
    ILLEGAL_TRANSITION, RECOVERY_AUTHORIZATION_MISSING, REQUEST_CONFLICT, TASK_TERMINAL,
    TRIGGER_NOT_APPLICABLE, WorkflowRejection,
)

RESULT_CONFIRMED = "RESULT_CONFIRMED"
RESTART_SAFE = "RESTART_SAFE"
RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
INDETERMINATE = "INDETERMINATE"
ASSESSMENT_RESULTS = (RESULT_CONFIRMED, RESTART_SAFE, RECONCILIATION_REQUIRED, INDETERMINATE)

RECORD_CONFIRMED_RESULT = "RECORD_CONFIRMED_RESULT"
RESTORE_PUBLISH_FINALIZATION = "RESTORE_PUBLISH_FINALIZATION"
RESTART_CURRENT_NODE = "RESTART_CURRENT_NODE"
RECONCILE_CURRENT_NODE = "RECONCILE_CURRENT_NODE"
ACTIONS = (RECORD_CONFIRMED_RESULT, RESTORE_PUBLISH_FINALIZATION, RESTART_CURRENT_NODE, RECONCILE_CURRENT_NODE)

# Assessment result to the one legal action. INDETERMINATE maps to no action at all.
LEGAL_ACTION = {
    RESULT_CONFIRMED: (RECORD_CONFIRMED_RESULT, RESTORE_PUBLISH_FINALIZATION),
    RESTART_SAFE: (RESTART_CURRENT_NODE,),
    RECONCILIATION_REQUIRED: (RECONCILE_CURRENT_NODE,),
    INDETERMINATE: (),
}
AUTHORIZATION_BINDING = ("workflowInstance", "occurrence", "expectedRuntimeVersion", "assessmentId", "action", "effectScope")


def assess(state, topology, task_id, command, *, revision):
    """Read-only recovery assessment; it changes no lifecycle, position or condition."""
    inst = instance(state, task_id)
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection(TASK_TERMINAL, "recovery applies only to an ACTIVE Workflow", lifecycle=inst["lifecycle"])
    if inst["condition"] != states.RECOVERY_REQUIRED:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "the current node is not in RECOVERY_REQUIRED",
                                condition=inst["condition"])
    result = command.get("assessment")
    if result not in ASSESSMENT_RESULTS:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "assessment must be one of the four mutually exclusive results",
                                assessment=result, results=list(ASSESSMENT_RESULTS))
    assessment_id = command.get("assessmentId")
    if not isinstance(assessment_id, str) or not assessment_id:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "assessmentId is required")
    semantic = topology.semantic_type(inst["position"])
    if result == RESTART_SAFE and not states.restartable(inst["position"], semantic):
        raise WorkflowRejection(ILLEGAL_TRANSITION, "this node semantic type cannot produce RESTART_SAFE",
                                node=inst["position"], semanticType=semantic)
    body = dict(assessmentId=assessment_id, assessment=result, workflowInstance=task_id,
                occurrence=occurrence(inst, task_id), expectedRuntimeVersion=inst["runtimeVersion"],
                checked=copy.deepcopy(command.get("checked", [])), evidence=copy.deepcopy(command.get("evidence", [])),
                producedAt=now(), domainRevision=revision, consumedBy=None, invalidatedBy=None)
    existing = inst["recovery"]["assessments"].get(assessment_id)
    if existing is not None:
        comparable = {k: v for k, v in body.items() if k not in ("producedAt", "domainRevision", "consumedBy", "invalidatedBy")}
        recorded = {k: v for k, v in existing.items() if k not in ("producedAt", "domainRevision", "consumedBy", "invalidatedBy")}
        if comparable != recorded:
            raise WorkflowRejection(REQUEST_CONFLICT, "assessmentId already bound to a different assessment",
                                    assessmentId=assessment_id)
        return dict(result=IDEMPOTENT_REPLAY, assessment=copy.deepcopy(existing))
    inst["recovery"]["assessments"][assessment_id] = body
    inst["recovery"]["current"] = assessment_id
    return dict(result="ASSESSED", assessment=copy.deepcopy(body),
                legalActions=list(LEGAL_ACTION[result]) if result != RESULT_CONFIRMED else
                [RESTORE_PUBLISH_FINALIZATION if inst["position"] == states.PUBLISH_NODE else RECORD_CONFIRMED_RESULT])


def _fresh(inst, task_id, assessment):
    if assessment["consumedBy"] is not None:
        raise WorkflowRejection(ASSESSMENT_ALREADY_CONSUMED, "this assessment was already consumed by a recovery action",
                                assessmentId=assessment["assessmentId"], consumedBy=assessment["consumedBy"])
    if assessment["invalidatedBy"] is not None:
        raise WorkflowRejection(ASSESSMENT_STALE, "this assessment was invalidated and a new one is required",
                                assessmentId=assessment["assessmentId"], invalidatedBy=assessment["invalidatedBy"])
    current = occurrence(inst, task_id)
    if assessment["occurrence"] != current:
        raise WorkflowRejection(ASSESSMENT_STALE, "the Current Position occurrence changed since the assessment",
                                recorded=assessment["occurrence"], current=current)
    if assessment["expectedRuntimeVersion"] != inst["runtimeVersion"]:
        raise WorkflowRejection(ASSESSMENT_STALE, "the Runtime Version changed since the assessment",
                                recorded=assessment["expectedRuntimeVersion"], current=inst["runtimeVersion"])


def _authorization(inst, task_id, assessment, action, command):
    """Consume the single-use Human Recovery Action Authorization required by this action."""
    offered = command.get("humanAuthorization")
    if not isinstance(offered, dict):
        raise WorkflowRejection(RECOVERY_AUTHORIZATION_MISSING,
                                "this recovery action produces new external effect and needs a Human authorization",
                                action=action, binding=list(AUTHORIZATION_BINDING))
    expected = dict(workflowInstance=task_id, occurrence=occurrence(inst, task_id),
                    expectedRuntimeVersion=inst["runtimeVersion"], assessmentId=assessment["assessmentId"],
                    action=action, effectScope=offered.get("effectScope"))
    if any(offered.get(field) != expected[field] for field in AUTHORIZATION_BINDING):
        raise WorkflowRejection(RECOVERY_AUTHORIZATION_MISSING, "the Human authorization is not bound to this exact action",
                                offered={k: offered.get(k) for k in AUTHORIZATION_BINDING}, expected=expected)
    if not offered.get("effectScope"):
        raise WorkflowRejection(RECOVERY_AUTHORIZATION_MISSING, "the Human authorization must name an allowed effect scope")
    reference = offered.get("authorizationRef")
    if not isinstance(reference, str) or not reference:
        raise WorkflowRejection(AUTHORITY_MISSING, "the Human authorization must carry a locatable reference")
    if reference in inst["recovery"]["authorizations"]:
        raise WorkflowRejection(RECOVERY_AUTHORIZATION_MISSING, "this Human authorization was already consumed",
                                authorizationRef=reference)
    inst["recovery"]["authorizations"][reference] = dict(expected, authorizationRef=reference, consumedAt=now())
    return reference


def recover(state, topology, task_id, command, *, revision):
    """Run the one legal action for the latest valid assessment."""
    inst = instance(state, task_id)
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection(TASK_TERMINAL, "recovery applies only to an ACTIVE Workflow", lifecycle=inst["lifecycle"])
    action = command.get("action")
    if action not in ACTIONS:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "unknown recovery action", action=action, actions=list(ACTIONS))
    assessment_id = command.get("assessmentId") or inst["recovery"]["current"]
    assessment = inst["recovery"]["assessments"].get(assessment_id)
    if assessment is None:
        raise WorkflowRejection(ASSESSMENT_STALE, "no recovery assessment to consume", assessmentId=assessment_id)
    _fresh(inst, task_id, assessment)
    legal = LEGAL_ACTION[assessment["assessment"]]
    if not legal:
        raise WorkflowRejection(ILLEGAL_TRANSITION,
                                "an INDETERMINATE assessment authorises no state change; collect new trustworthy "
                                "facts and assess again",
                                assessment=assessment["assessment"], action=action)
    at_publish = inst["position"] == states.PUBLISH_NODE
    if assessment["assessment"] == RESULT_CONFIRMED:
        expected_action = RESTORE_PUBLISH_FINALIZATION if at_publish else RECORD_CONFIRMED_RESULT
        legal = (expected_action,)
    if action not in legal:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "this action is not the legal action for the current assessment",
                                assessment=assessment["assessment"], action=action, legal=list(legal))
    authorization = None
    if action == RESTART_CURRENT_NODE or (action == RECONCILE_CURRENT_NODE and command.get("mutatesExternalState")):
        authorization = _authorization(inst, task_id, assessment, action, command)

    if action == RECONCILE_CURRENT_NODE:
        # Lifecycle, position, occurrence and condition all stay; a new assessment is then required.
        assessment["consumedBy"] = command["commandId"]
        entry = dict(commandId=command["commandId"], action=action, assessmentId=assessment_id, at=now(),
                     authorizationRef=authorization, scope=copy.deepcopy(command.get("scope")),
                     evidence=copy.deepcopy(command.get("evidence", [])),
                     mutatesExternalState=bool(command.get("mutatesExternalState")))
        inst["recovery"].setdefault("actions", []).append(entry)
        inst["recovery"]["current"] = None
        return dict(result="RECONCILED", action=action, reassessmentRequired=True, record=copy.deepcopy(entry),
                    runtimeVersion=inst["runtimeVersion"])

    condition = {RECORD_CONFIRMED_RESULT: states.RESULT_RECORDED,
                 RESTORE_PUBLISH_FINALIZATION: states.EXECUTING,
                 RESTART_CURRENT_NODE: states.ENTERED}[action]
    outcome = progression.recovery_condition_update(
        state, topology, task_id,
        dict(commandId=command["commandId"], condition=condition, authorityRef=command["authorityRef"],
             expectedRuntimeVersion=inst["runtimeVersion"]), revision=revision)
    assessment["consumedBy"] = command["commandId"]
    inst["recovery"]["current"] = None
    entry = dict(commandId=command["commandId"], action=action, assessmentId=assessment_id, at=now(),
                 authorizationRef=authorization, condition=condition)
    inst["recovery"].setdefault("actions", []).append(entry)
    if action == RESTART_CURRENT_NODE:
        # The occurrence does not change: a restart is not a new position entry. Old attempts and
        # their evidence stay and are excluded from any further consumption at this node.
        for attempt in inst["attempts"]:
            if attempt["occurrence"] == assessment["occurrence"] and attempt["status"] in states.ATTEMPT_RECOVERY:
                attempt["excludedFromConsumption"] = True
        inst["attempt"] = None
        for fact_id, fact in inst["facts"].items():
            if fact["occurrence"] == assessment["occurrence"] and fact["consumedBy"] is None:
                fact["consumedBy"] = "restart:" + command["commandId"]
    return dict(result=outcome["result"], action=action, commit=outcome["commit"],
                runtimeVersion=outcome["runtimeVersion"], authorizationRef=authorization)
