"""Closed set of autonomous budget results (feature-t5 design, 结果码闭集).

Separate from the Workflow, acceptance, Definition, Implement/Verify and Policy closed sets; a Workflow
or Policy result raised while this package drives them passes through unchanged.
"""
BUDGET_ROUTED = "BUDGET_ROUTED"
BUDGET_CONFIGURED = "BUDGET_CONFIGURED"
IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
BUDGET_READ = "BUDGET_READ"

BUDGET_DENIED = "BUDGET_DENIED"
POSITION_NOT_APPLICABLE = "POSITION_NOT_APPLICABLE"
BUDGET_CONFIGURATION_REJECTED = "BUDGET_CONFIGURATION_REJECTED"
GENERIC_COMMAND_NARROWED = "GENERIC_COMMAND_NARROWED"

BUDGET_NOT_DETERMINABLE = "BUDGET_NOT_DETERMINABLE"

SUCCESS = (BUDGET_ROUTED, BUDGET_CONFIGURED, IDEMPOTENT_REPLAY, BUDGET_READ)
REJECTIONS = (BUDGET_DENIED, POSITION_NOT_APPLICABLE, BUDGET_CONFIGURATION_REJECTED, GENERIC_COMMAND_NARROWED)
NOT_DETERMINABLE = (BUDGET_NOT_DETERMINABLE,)
RESULTS = SUCCESS + REJECTIONS + NOT_DETERMINABLE


class BudgetRejection(Exception):
    """A determinate refusal of a budget command; nothing is recorded."""

    def __init__(self, code, message, **detail):
        if code not in RESULTS or code in SUCCESS:
            raise ValueError("Unknown budget rejection code: " + str(code))
        self.code, self.detail = code, dict(detail)
        super().__init__(message)

    def reason(self):
        return dict(code=self.code, message=str(self), **self.detail)


def exit_code(code):
    """0 completed, 1 determinate refusal (DENY included), 2 not determinable."""
    if code in SUCCESS:
        return 0
    if code in NOT_DETERMINABLE:
        return 2
    return 1
