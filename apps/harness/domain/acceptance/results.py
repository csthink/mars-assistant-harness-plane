"""Closed set of acceptance results and rejection reasons (design §拒绝分类闭集)."""

ACCEPTED = "ACCEPTED"
IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
REQUEST_CONFLICT = "REQUEST_CONFLICT"
UNRESOLVED = "UNRESOLVED"
INDETERMINATE = "INDETERMINATE"
SOURCE_LANE_UNAVAILABLE = "SOURCE_LANE_UNAVAILABLE"
DEPENDENCY_UNMET = "DEPENDENCY_UNMET"
AUTHORITY_MISSING = "AUTHORITY_MISSING"
DUPLICATE_ACCEPTED_TASK = "DUPLICATE_ACCEPTED_TASK"
DUPLICATE_ACCEPTANCE_IN_PROGRESS = "DUPLICATE_ACCEPTANCE_IN_PROGRESS"
CONCURRENCY_LIMIT_REACHED = "CONCURRENCY_LIMIT_REACHED"
PARTIAL_EFFECT_UNRESOLVED = "PARTIAL_EFFECT_UNRESOLVED"
WORKSPACE_ERROR = "WORKSPACE_ERROR"

RESULTS = (ACCEPTED, IDEMPOTENT_REPLAY, REQUEST_CONFLICT, UNRESOLVED, INDETERMINATE, SOURCE_LANE_UNAVAILABLE,
           DEPENDENCY_UNMET, AUTHORITY_MISSING, DUPLICATE_ACCEPTED_TASK, DUPLICATE_ACCEPTANCE_IN_PROGRESS,
           CONCURRENCY_LIMIT_REACHED, PARTIAL_EFFECT_UNRESOLVED, WORKSPACE_ERROR)

# Exit codes follow the repository tool convention: 0 completed, 1 determinate rejection, 2 not determinable.
SUCCESS = (ACCEPTED, IDEMPOTENT_REPLAY)
NOT_DETERMINABLE = (INDETERMINATE, PARTIAL_EFFECT_UNRESOLVED)

# Dedup outcomes (D-06 logical contract as mapped by spec FR-16); only CLAIM_ACQUIRED continues.
CLAIM_ACQUIRED = "CLAIM_ACQUIRED"

class Rejection(Exception):
    """A determinate or indeterminate non-acceptance carrying a machine-readable reason object."""
    def __init__(self, code, message, **detail):
        if code not in RESULTS or code in SUCCESS:
            raise ValueError("Unknown rejection code: " + str(code))
        self.code, self.detail = code, dict(detail)
        super().__init__(message)

    def reason(self):
        return dict(code=self.code, message=str(self), **self.detail)

def exit_code(code):
    if code in SUCCESS:
        return 0
    if code in NOT_DETERMINABLE:
        return 2
    return 1
