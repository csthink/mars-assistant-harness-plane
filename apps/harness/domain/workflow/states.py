"""The five orthogonal layers of Workflow Runtime State and their legal combination matrix.

Layers (never collapsed into one enumeration): Workflow Lifecycle, Current Position, Execution
Condition, Attempt and Progression Commit. This module owns the first three plus Attempt; the
Progression Commit record lives in progression.py.

Consumed through sdd/spec.md §8 (D-04 -> FR-31 / NFR-01, "any non-terminal -> Closed" extension per
FR-27) and the founding-archive fixed original text. A business FAIL is a consumable formal result
(RESULT_RECORDED) and is not a recovery condition; only execution failure, result-integrity damage or
an unconfirmable completion state enters RECOVERY_REQUIRED (FR-30).
"""
ACTIVE, COMPLETED, CLOSED = "ACTIVE", "COMPLETED", "CLOSED"
LIFECYCLES = (ACTIVE, COMPLETED, CLOSED)

ENTERED, EXECUTING, AWAITING_HUMAN_ACTION, RESULT_RECORDED, RECOVERY_REQUIRED = (
    "ENTERED", "EXECUTING", "AWAITING_HUMAN_ACTION", "RESULT_RECORDED", "RECOVERY_REQUIRED")
CONDITIONS = (ENTERED, EXECUTING, AWAITING_HUMAN_ACTION, RESULT_RECORDED, RECOVERY_REQUIRED)

CREATED, RUNNING, ATTEMPT_COMPLETED, EXECUTION_FAILED, ATTEMPT_INDETERMINATE = (
    "CREATED", "RUNNING", "COMPLETED", "EXECUTION_FAILED", "INDETERMINATE")
ATTEMPT_STATES = (CREATED, RUNNING, ATTEMPT_COMPLETED, EXECUTION_FAILED, ATTEMPT_INDETERMINATE)
ATTEMPT_TERMINAL = (ATTEMPT_COMPLETED, EXECUTION_FAILED, ATTEMPT_INDETERMINATE)
# Both failure kinds stop progression, and they keep separate evidence; they are never merged.
ATTEMPT_RECOVERY = (EXECUTION_FAILED, ATTEMPT_INDETERMINATE)

POSITION_ADVANCE, CONDITION_UPDATE, LIFECYCLE_FINALIZATION = (
    "POSITION_ADVANCE", "CONDITION_UPDATE", "LIFECYCLE_FINALIZATION")
TRANSITION_KINDS = (POSITION_ADVANCE, CONDITION_UPDATE, LIFECYCLE_FINALIZATION)

PUBLISH_NODE = "N-PUBLISH"
TERMINAL_DECISION = "TERMINAL_HUMAN_DECISION_OUTCOME"

_DECIDING = (ENTERED, EXECUTING, RESULT_RECORDED, RECOVERY_REQUIRED)
_HUMAN = (ENTERED, AWAITING_HUMAN_ACTION, RESULT_RECORDED, RECOVERY_REQUIRED)
_RECORDED_ONLY = (RESULT_RECORDED, RECOVERY_REQUIRED)

# Legal Execution Conditions per node semantic type while the Workflow Lifecycle is ACTIVE.
ACTIVE_MATRIX = {
    "HUMAN_ACTION": _HUMAN,
    "ARTIFACT": _RECORDED_ONLY,
    "CONFIGURATION_DECISION": _DECIDING,
    "APPLICABILITY_DECISION": _DECIDING,
    "POLICY_DECISION": _DECIDING,
    "RESULT_DECISION": _DECIDING,
    "CONTROL_PLANE_ORCHESTRATOR": _DECIDING,
    "ENGINEERING_MODULE": _DECIDING,
    "REVIEW_MODULE": _DECIDING,
    "HUMAN_GATE": _HUMAN,
    "HUMAN_DECISION_OUTCOME": _RECORDED_ONLY,
    TERMINAL_DECISION: (),
}
# Publish narrows the ACTIVE row further: RESULT_RECORDED there would claim a completed publication.
PUBLISH_ACTIVE = (ENTERED, EXECUTING, RECOVERY_REQUIRED)


def legal(lifecycle, node_id, semantic_type, condition, *, closure=None):
    """Whether one (lifecycle, position, condition) combination may be persisted.

    closure distinguishes the two shapes CLOSED is reached in: "topology-edge" lands on a registered
    Close Task node through an escalation gate (D-04 §9), and "power-action" is FR-27 exercised at
    any other position, which spec §8 OD-69 admits into the matrix as "any non-terminal -> Closed"
    without moving the position or adding a Node, Edge or Gate.
    """
    if lifecycle not in LIFECYCLES or condition not in CONDITIONS:
        return False
    if lifecycle == ACTIVE:
        if node_id == PUBLISH_NODE:
            return condition in PUBLISH_ACTIVE
        return condition in ACTIVE_MATRIX.get(semantic_type, ())
    if lifecycle == COMPLETED:
        return node_id == PUBLISH_NODE and condition == RESULT_RECORDED
    if condition != RESULT_RECORDED:
        return False
    if semantic_type == TERMINAL_DECISION:
        return closure in (None, "topology-edge")
    return closure == "power-action"


def entry_condition(node_id, semantic_type):
    """The condition a node carries at the moment it becomes the Current Position."""
    if semantic_type in ("ARTIFACT", "HUMAN_DECISION_OUTCOME"):
        return RESULT_RECORDED
    if semantic_type == TERMINAL_DECISION:
        return RESULT_RECORDED
    if node_id == PUBLISH_NODE:
        return ENTERED
    return ENTERED


def standard_path(node_id, semantic_type):
    """Allowed condition updates inside one occurrence, in order, excluding recovery transitions."""
    if semantic_type in ("HUMAN_ACTION", "HUMAN_GATE"):
        return (ENTERED, AWAITING_HUMAN_ACTION, RESULT_RECORDED)
    if semantic_type in ("ARTIFACT", "HUMAN_DECISION_OUTCOME", TERMINAL_DECISION):
        return (RESULT_RECORDED,)
    if node_id == PUBLISH_NODE:
        return (ENTERED, EXECUTING)
    return (ENTERED, EXECUTING, RESULT_RECORDED)


def next_condition(node_id, semantic_type, condition):
    """The single next condition on the standard path, or None when the node has no further step."""
    path = standard_path(node_id, semantic_type)
    if condition not in path:
        return None
    index = path.index(condition) + 1
    return path[index] if index < len(path) else None


def restartable(node_id, semantic_type):
    """Whether RESTART_CURRENT_NODE may put this node back to ENTERED (recovery contract §4.2)."""
    return ENTERED in ACTIVE_MATRIX.get(semantic_type, ()) and node_id != PUBLISH_NODE


def requires_attempt(semantic_type):
    """Node kinds whose work is a concrete external call and therefore carries an Attempt."""
    return semantic_type in ("ENGINEERING_MODULE", "REVIEW_MODULE")
