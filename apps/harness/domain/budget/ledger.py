"""Pure derivation of an autonomous budget window from immutable records (feature-t5 design, 额度配置与计算).

Nothing here writes. The Policy Gate's budget judgement items call derive() and arrival() inside the
Domain Core unit of work that records the decision; the status view calls them read only. This module
does not import domain.policy, so the Policy Gate can depend on it without an import cycle.

Window rule, per loop L (FAIL edge F, Budget Remains edge R, Continue edge C at L's escalation gate):
- the window starts at the latest commit that selected C (grant basis `continue`, the Human Continue is
  the re-authorisation), otherwise at the first commit that selected F (grant basis `initial`);
- the granted amount is L's integer in the autonomous-budget history row in force at the window start
  revision; when nothing was configured at that revision, the first row written after it is used, so a
  task stopped for a missing configuration proceeds once the Human configures it, and that choice never
  moves again;
- the consumed count is the number of commits after the window start that selected R; each of them must
  have consumed an ALLOW Policy Gate decision of this subject whose outcome is `Budget Remains`,
  otherwise the history is not bound to budget decisions and the judgement fails;
- consumed < amount is `Budget Remains`, anything else `Budget Exhausted`.
The three loops never share a count and no event of another loop resets a window.
"""
from domain.budget import configuration

POLICY_DECISION, POLICY_PRODUCER = "policy-decision", "policy-gate"
REMAINS, EXHAUSTED = "Budget Remains", "Budget Exhausted"
OUTCOMES = (REMAINS, EXHAUSTED)
DEFINITION, VERIFICATION, VALIDATION = "definition-review-budget", "verification-budget", "validation-review-budget"
LOOPS = {
    DEFINITION: dict(loop="definitionReview", node="N-DEF-BUDGET-DECISION", failEdge="E-D08", remainsEdge="E-D11",
                     exhaustedEdge="E-D10", continueEdge="E-D12", gate="N-DEF-ESCALATION-GATE"),
    VERIFICATION: dict(loop="verification", node="N-VERIFY-BUDGET-DECISION", failEdge="E-I07", remainsEdge="E-I08",
                       exhaustedEdge="E-I10", continueEdge="E-I11", gate="N-VERIFY-ESCALATION-GATE"),
    VALIDATION: dict(loop="validationReview", node="N-VALIDATE-BUDGET-DECISION", failEdge="E-V05",
                     remainsEdge="E-V07", exhaustedEdge="E-V09", continueEdge="E-V10", gate="N-VALIDATE-ESCALATION-GATE"),
}
SUBJECTS = tuple(LOOPS)
SUBJECT_AT = {spec["node"]: subject for subject, spec in LOOPS.items()}


class BudgetUnavailable(Exception):
    """The budget cannot be determined from what is recorded (NOT_CHECKED)."""

    def __init__(self, code, message, **detail):
        self.code, self.detail = code, dict(detail)
        super().__init__(message)


class BudgetBroken(Exception):
    """What is recorded contradicts the budget rules (FAIL)."""

    def __init__(self, code, message, **detail):
        self.code, self.detail = code, dict(detail)
        super().__init__(message)


def edge(subject, outcome):
    spec = LOOPS[subject]
    return spec["remainsEdge"] if outcome == REMAINS else spec["exhaustedEdge"]


def _entry_commit(inst):
    for commit in reversed(inst["commits"]):
        nxt = commit["nextSnapshot"]
        if commit["transitionKind"] == "POSITION_ADVANCE" and nxt["position"] == inst["position"] and \
                str(nxt["positionEntryRuntimeVersion"]) == str(inst["positionEntryRevision"]):
            return commit
    return None


def _last_verdict_round(rounds):
    verdicts = [r for r in rounds or [] if r.get("verdict")]
    return verdicts[-1] if verdicts else None


def arrival(state, task_id, subject):
    """The business FAIL that brought the current occurrence to this budget node, or BudgetBroken."""
    spec = LOOPS[subject]
    task = state["tasks"][task_id]
    inst = task["workflowInstance"]
    if inst["position"] != spec["node"]:
        raise BudgetBroken("BUDGET_POSITION_MISMATCH", "the task is not at this subject's budget node",
                           position=inst["position"], node=spec["node"])
    entry = _entry_commit(inst)
    if entry is None or entry["selectedEdge"] != spec["failEdge"]:
        raise BudgetBroken("BUDGET_ARRIVAL_UNBOUND", "the current occurrence was not entered through the loop's FAIL edge",
                           expected=spec["failEdge"], enteredBy=(entry or {}).get("selectedEdge"))
    if subject == VERIFICATION:
        facts = [inst["facts"].get(f) or {} for f in entry.get("triggers", [])]
        hits = [f for f in facts if f.get("kind") == "verify-result" and (f.get("payload") or {}).get("result") == "FAIL"]
        if not hits:
            raise BudgetBroken("BUDGET_ARRIVAL_UNBOUND", "the FAIL edge consumed no FAIL Verification Result",
                               commit=entry["commandId"])
        return dict(kind="verify-result", ref=hits[0]["factId"], commit=entry["commandId"])
    rounds = (task.get("taskDefinition") or {}).get("rounds") if subject == DEFINITION else \
        (task.get("validateChange") or {}).get("rounds")
    last = _last_verdict_round(rounds)
    if last is None or last["verdict"].get("verdict") != "FAIL":
        raise BudgetBroken("BUDGET_ARRIVAL_UNBOUND", "the loop's latest Reviewer verdict is not a FAIL",
                           round=(last or {}).get("round"))
    return dict(kind="reviewer-verdict", ref=last.get("verdictFact"), round=last.get("round"), commit=entry["commandId"])


def grant_for(state, revision, loop):
    """(amount, history index, row revision, basis) of the configuration in force at `revision`."""
    rows = configuration.history(state)
    parsed = []
    for index, row in rows:
        try:
            written = int(row["revision"])
            value = configuration.validate(row["value"])
        except Exception:  # an unreadable history row is never a pass
            raise BudgetUnavailable("BUDGET_CONFIGURATION_INVALID", "an autonomous-budget history row cannot be interpreted",
                                    historyIndex=index) from None
        parsed.append((index, written, value))
    at = int(revision)
    before = [p for p in parsed if p[1] <= at]
    if before:
        index, written, value = before[-1]
        return value[loop], index, str(written), "in-force-at-window-start"
    after = [p for p in parsed if p[1] > at]
    if after:
        index, written, value = after[0]
        return value[loop], index, str(written), "first-configured-after-window-start"
    raise BudgetUnavailable("BUDGET_NOT_CONFIGURED", "no autonomous-budget configuration exists; the budget cannot be "
                            "decided (no default applies)", key=configuration.KEY)


def _bound_remains(inst, commit, subject):
    for fact_id in commit.get("triggers", []):
        fact = inst["facts"].get(fact_id) or {}
        payload = fact.get("payload") or {}
        if (fact.get("kind") == POLICY_DECISION and fact.get("producer") == POLICY_PRODUCER
                and fact.get("purpose") == subject and payload.get("conclusion") == "ALLOW"
                and payload.get("outcome") == REMAINS and fact.get("consumedBy") == commit["commandId"]):
            return True
    return False


def derive(state, task_id, subject):
    """Window, grant, consumption and outcome for this subject on this task (see the module rule)."""
    spec = LOOPS[subject]
    inst = state["tasks"][task_id]["workflowInstance"]
    commits = list(enumerate(inst["commits"]))
    advances = [(i, c) for i, c in commits if c["transitionKind"] == "POSITION_ADVANCE"]
    continues = [(i, c) for i, c in advances if c["selectedEdge"] == spec["continueEdge"]]
    if continues:
        start_index, start = continues[-1]
        basis, decision = "continue", (start.get("triggers") or [None])[0]
    else:
        firsts = [(i, c) for i, c in advances if c["selectedEdge"] == spec["failEdge"]]
        if not firsts:
            raise BudgetBroken("BUDGET_ARRIVAL_UNBOUND", "this loop has never reached its budget node through its FAIL edge")
        start_index, start = firsts[0]
        basis, decision = "initial", None
    amount, index, written, how = grant_for(state, start["domainRevision"], spec["loop"])
    consumed_by = []
    for i, commit in advances:
        if i <= start_index or commit["selectedEdge"] != spec["remainsEdge"]:
            continue
        if not _bound_remains(inst, commit, subject):
            raise BudgetBroken("BUDGET_HISTORY_UNBOUND", "a Budget Remains progression consumed no Policy Gate budget decision",
                               commit=commit["commandId"], edge=commit["selectedEdge"])
        consumed_by.append(commit["commandId"])
    consumed = len(consumed_by)
    outcome = REMAINS if consumed < amount else EXHAUSTED
    return dict(subject=subject, loop=spec["loop"], node=spec["node"],
                window=dict(startCommand=start["commandId"], startRevision=str(start["domainRevision"]), basis=basis,
                            continueDecisionFact=decision),
                grant=dict(amount=amount, configurationRevision=written, historyIndex=index, selection=how),
                consumed=consumed, consumedBy=consumed_by, remaining=max(amount - consumed, 0), outcome=outcome,
                edge=edge(subject, outcome))


def decisions(state, task_id):
    """Recorded budget decisions of one task (read only), oldest first."""
    inst = state["tasks"][task_id]["workflowInstance"]
    rows = [f for f in inst["facts"].values() if f.get("kind") == POLICY_DECISION and f.get("purpose") in LOOPS]
    return sorted(rows, key=lambda f: (int(f["domainRevision"]), f["factId"]))
