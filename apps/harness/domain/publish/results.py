"""Closed set of Publish results (feature-t7 design, 结果码闭集; finalised in construction).

Kept apart from the acceptance, Workflow, Definition, Implement/Verify, budget, Validate Change and Policy
closed sets; none of them covers another. The generic-command and generic-decision narrowings reuse the
feature-t2 codes with a reasonCode, and Policy reasons and platform failure kinds stay sub-fields of the
reason object. Adding a result means changing the design and adding a positive and a negative test.
"""
PUBLISH_TARGET_CONFIGURED = "PUBLISH_TARGET_CONFIGURED"
PUBLISH_CONTEXT_READ = "PUBLISH_CONTEXT_READ"
PUBLISH_AUTHORIZED = "PUBLISH_AUTHORIZED"
PUBLISH_DISPATCHED = "PUBLISH_DISPATCHED"
PUBLISHED = "PUBLISHED"
QUERY_DISPATCHED = "QUERY_DISPATCHED"
PUBLISH_OBSERVED = "PUBLISH_OBSERVED"
RECONCILE_DISPATCHED = "RECONCILE_DISPATCHED"
EXECUTION_SETTLED = "EXECUTION_SETTLED"
PUBLISH_READ = "PUBLISH_READ"
IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"

POSITION_NOT_APPLICABLE = "POSITION_NOT_APPLICABLE"
INPUT_INVALID = "INPUT_INVALID"
PUBLISH_TARGET_NOT_CONFIGURED = "PUBLISH_TARGET_NOT_CONFIGURED"
PUBLISH_TARGET_REJECTED = "PUBLISH_TARGET_REJECTED"
BINDING_MISMATCH = "BINDING_MISMATCH"
CANDIDATE_NOT_VERIFIED = "CANDIDATE_NOT_VERIFIED"
CONTEXT_STALE = "CONTEXT_STALE"
UNCONTROLLED_CHANGE = "UNCONTROLLED_CHANGE"
PUSH_NOT_PERMITTED = "PUSH_NOT_PERMITTED"
EXECUTION_IN_FLIGHT = "EXECUTION_IN_FLIGHT"
ASSESSMENT_NOT_RECONCILABLE = "ASSESSMENT_NOT_RECONCILABLE"

PUSH_PERMIT_NOT_DETERMINABLE = "PUSH_PERMIT_NOT_DETERMINABLE"
PUBLISH_RESULT_UNKNOWN = "PUBLISH_RESULT_UNKNOWN"
INDETERMINATE = "INDETERMINATE"

# reasonCode values carried by feature-t2 rejections (not results of their own).
GENERIC_COMMAND_NARROWED = "GENERIC_COMMAND_NARROWED"
DECISION_REQUIRES_PUBLISH_ENTRY = "DECISION_REQUIRES_PUBLISH_ENTRY"

SUCCESS = (PUBLISH_TARGET_CONFIGURED, PUBLISH_CONTEXT_READ, PUBLISH_AUTHORIZED, PUBLISH_DISPATCHED, PUBLISHED,
           QUERY_DISPATCHED, PUBLISH_OBSERVED, RECONCILE_DISPATCHED, EXECUTION_SETTLED, PUBLISH_READ, IDEMPOTENT_REPLAY)
REJECTIONS = (POSITION_NOT_APPLICABLE, INPUT_INVALID, PUBLISH_TARGET_NOT_CONFIGURED, PUBLISH_TARGET_REJECTED,
              BINDING_MISMATCH, CANDIDATE_NOT_VERIFIED, CONTEXT_STALE, UNCONTROLLED_CHANGE, PUSH_NOT_PERMITTED,
              EXECUTION_IN_FLIGHT, ASSESSMENT_NOT_RECONCILABLE)
NOT_DETERMINABLE = (PUSH_PERMIT_NOT_DETERMINABLE, PUBLISH_RESULT_UNKNOWN, INDETERMINATE)
RESULTS = SUCCESS + REJECTIONS + NOT_DETERMINABLE
# Results that settle a Runtime Operation as succeeded.
OPERATION_SUCCEEDED = (PUBLISH_AUTHORIZED, PUBLISH_DISPATCHED, PUBLISHED, QUERY_DISPATCHED, PUBLISH_OBSERVED,
                       RECONCILE_DISPATCHED, IDEMPOTENT_REPLAY)

# Outcome classifications of one publish execution and of one same-operation query (design, 结果分类).
PUBLISHED_OUTCOME, NOT_HAPPENED, PARTIAL, UNCONTROLLED, UNKNOWN = (
    "published", "not-happened", "partial", "uncontrolled-change", "unknown")
EXECUTION_OUTCOMES = (PUBLISHED_OUTCOME, NOT_HAPPENED, PARTIAL, UNCONTROLLED, UNKNOWN)
CONFIRMED, ABSENT = "confirmed", "absent"
QUERY_OUTCOMES = (CONFIRMED, ABSENT, PARTIAL, UNCONTROLLED, UNKNOWN)


class PublishRejection(Exception):
    """A determinate or indeterminate refusal of a Publish command; nothing is recorded by the refused step."""

    def __init__(self, code, message, **detail):
        if code not in RESULTS or code in SUCCESS:
            raise ValueError("Unknown publish rejection code: " + str(code))
        self.code, self.detail = code, dict(detail)
        super().__init__(message)

    def reason(self):
        return dict(code=self.code, message=str(self), **self.detail)


def exit_code(code):
    """0 completed, 1 determinate refusal, 2 not determinable (repository tool convention)."""
    if code in SUCCESS:
        return 0
    if code in NOT_DETERMINABLE:
        return 2
    return 1
