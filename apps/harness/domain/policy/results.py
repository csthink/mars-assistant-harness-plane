"""Closed sets of the Policy Gate: item results, overall conclusions, reasons and exit codes.

Kept apart from the Workflow closed set (domain/workflow/results.py) and the acceptance closed set
(domain/acceptance/results.py); none of them covers another. Adding a reason means changing the
design and adding a positive and a negative test.
"""
PASS, FAIL, NOT_CHECKED, NOT_APPLICABLE = "PASS", "FAIL", "NOT_CHECKED", "NOT_APPLICABLE"
ITEM_RESULTS = (PASS, FAIL, NOT_CHECKED, NOT_APPLICABLE)

ALLOW, DENY, NOT_DETERMINABLE = "ALLOW", "DENY", "NOT_DETERMINABLE"
CONCLUSIONS = (ALLOW, DENY, NOT_DETERMINABLE)
INPUT_INVALID = "INPUT_INVALID"

REASONS = (
    "VENDOR_OVERLAP", "AUTHOR_SET_EMPTY", "AUTHOR_VENDOR_UNKNOWN", "VENDOR_NOT_REGISTERED", "HUMAN_EVIDENCE_MISSING",
    "AUTHOR_DECLARATION_MISMATCH", "CAPABILITY_NOT_CONFIGURED", "FORMAL_AUTHORIZATION_REQUIRED", "BINDING_MISMATCH",
    "ENTRY_MISMATCH", "REGISTRY_UNAVAILABLE", "EVIDENCE_MISSING", "EVIDENCE_AMBIGUOUS", "EVIDENCE_DIGEST_MISMATCH",
    "PURPOSE_MISMATCH", "PORT_MODE_MISMATCH", "PROFILE_NOT_REGISTERED", "AUTHORITY_MISSING", "AUTHORITY_STALE",
    "PUSH_AUTHORIZATION_MISSING", "PUSH_BINDING_MISMATCH", "BUDGET_MISSING", "BUDGET_EXCEEDS_LIMIT",
    "BUDGET_FIELD_NOT_ALLOWED", "CALL_LIMIT_EXHAUSTED", "ROUND_BUDGET_EXHAUSTED", "ROUND_FACTS_UNREADABLE",
    "SUBJECT_NOT_IN_CLOSED_SET", "INPUT_INVALID", "STORE_UNAVAILABLE", "TASK_BRANCH_MISMATCH", "INPUTS_UNAVAILABLE",
    "AUTHOR_EXECUTION_UNREADABLE", "AUTHOR_EVIDENCE_UNAVAILABLE", "PORT_REGISTRATION_UNAVAILABLE",
    "CALL_STABLE_CORE_MISMATCH",
    # feature-t5 autonomous budget subjects
    "BUDGET_NOT_CONFIGURED", "BUDGET_CONFIGURATION_INVALID", "BUDGET_ARRIVAL_UNBOUND", "BUDGET_HISTORY_UNBOUND",
    "BUDGET_POSITION_MISMATCH",
)


class PolicyInputInvalid(Exception):
    """The evaluation request itself is malformed; nothing is evaluated and nothing is recorded."""

    def __init__(self, message, **detail):
        self.detail = dict(detail)
        super().__init__(message)

    def reason(self):
        return dict(code=INPUT_INVALID, message=str(self), **self.detail)


def reason(code, message, **detail):
    if code not in REASONS:
        raise ValueError("unknown policy reason: " + str(code))
    return dict(code=code, message=message, **detail)


def conclude(item_results):
    """Any FAIL is DENY; otherwise any NOT_CHECKED is NOT_DETERMINABLE; only all PASS is ALLOW."""
    applicable = [r for r in item_results if r != NOT_APPLICABLE]
    if any(r not in ITEM_RESULTS for r in item_results):
        raise ValueError("item result outside the closed set")
    if any(r == FAIL for r in applicable):
        return DENY
    if any(r == NOT_CHECKED for r in applicable) or not applicable:
        return NOT_DETERMINABLE
    return ALLOW


def exit_code(conclusion):
    """0 ALLOW, 1 DENY, 2 NOT_DETERMINABLE or INPUT_INVALID (not checked; see output `result`)."""
    return {ALLOW: 0, DENY: 1, NOT_DETERMINABLE: 2, INPUT_INVALID: 2}[conclusion]
