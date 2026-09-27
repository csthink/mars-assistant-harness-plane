"""Configuration key `autonomous-budget`: the three count budgets granted per window (spec FR-25).

The value is exactly {definitionReview, verification, validationReview}, each a non-negative integer
(a boolean is not an integer). There is no default: an unconfigured product line cannot decide a budget
and its tasks stop at the budget node (NOT_DETERMINABLE), which is the explicit-configuration rule of
FR-25 and NFR-06. Writes happen in one Domain Core transaction with an authority reference and append a
history row that carries the domain revision of the write, so the amount in force at any window start
is reconstructible from the history alone.
"""
import copy
from datetime import datetime, timezone

from domain.budget.results import BUDGET_CONFIGURATION_REJECTED, BUDGET_CONFIGURED, BudgetRejection

KEY = "autonomous-budget"
FIELD = "autonomousBudget"
LOOPS = ("definitionReview", "verification", "validationReview")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate(value):
    if not isinstance(value, dict) or set(value) != set(LOOPS):
        raise BudgetRejection(BUDGET_CONFIGURATION_REJECTED, "autonomous-budget takes exactly the three loop keys",
                              keys=list(LOOPS), offered=sorted(value) if isinstance(value, dict) else None)
    bad = [k for k in LOOPS if type(value[k]) is not int or value[k] < 0]
    if bad:
        raise BudgetRejection(BUDGET_CONFIGURATION_REJECTED, "each budget must be a non-negative integer", invalid=bad)
    return {k: value[k] for k in LOOPS}


def set_budget(state, value, authority_ref):
    """Write the value and append the history row (field, previous, value, authority, domain revision)."""
    if not isinstance(authority_ref, str) or not authority_ref:
        raise BudgetRejection(BUDGET_CONFIGURATION_REJECTED, "authorityRef is required to change the autonomous budget")
    normalised = validate(value)
    configuration = state.setdefault("configuration", {})
    previous = copy.deepcopy(configuration.get(FIELD))
    configuration[FIELD] = normalised
    configuration.setdefault("history", []).append(dict(at=now(), field=FIELD, previous=previous,
                                                        value=copy.deepcopy(normalised), authorityRef=authority_ref,
                                                        revision=str(state["revision"])))
    return dict(result=BUDGET_CONFIGURED, key=KEY, value=copy.deepcopy(normalised), previous=previous,
                revision=str(state["revision"]))


def history(state):
    """(index in configuration.history, row) for every autonomous-budget write, in write order."""
    rows = (state.get("configuration") or {}).get("history") or []
    return [(i, row) for i, row in enumerate(rows) if isinstance(row, dict) and row.get("field") == FIELD]


def current(state):
    return copy.deepcopy((state.get("configuration") or {}).get(FIELD))
