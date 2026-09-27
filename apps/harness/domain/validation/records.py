"""The Validate Change business record of a task and its read-only views.

`validateChange` lives in the task record of the one domain state (no second Workflow state): switch
decisions, impl rounds (candidate, materials, verdict, failure), Owner formal authorizations, Human
decisions, rulings and reservations. The views below are what feature-t4's remediation dispatch and
feature-t7's Publish authorization read; neither writes here.
"""
import copy

from domain.budget import ledger as budget_ledger


def ledger(state, task_id):
    task = state["tasks"][task_id]
    return task.setdefault("validateChange", dict(configurations=[], rounds=[], formal=[], decisions=[], rulings=[],
                                                  reservations=[]))


def view_of(state, task_id):
    return copy.deepcopy(state["tasks"][task_id].get("validateChange") or dict(configurations=[], rounds=[], formal=[],
                                                                                 decisions=[], rulings=[], reservations=[]))


def last_verdict_round(record):
    verdicts = [r for r in record.get("rounds", []) if r.get("verdict")]
    return verdicts[-1] if verdicts else None


def remediation_input(state, task_id):
    """For feature-t4's remediation dispatch from a Validation position: the last FAIL verdict and its findings."""
    record = state["tasks"][task_id].get("validateChange") or {}
    last = last_verdict_round(record)
    if last is None or last["verdict"]["verdict"] != "FAIL":
        return None
    verdict = last["verdict"]
    return dict(kind="validation", round=last["round"], verdictFact=last.get("verdictFact"),
                evidenceRef=copy.deepcopy(verdict.get("evidenceRef")), receiptRef=copy.deepcopy(verdict.get("receiptRef")),
                verdict=verdict["verdict"], findings=copy.deepcopy(verdict.get("findings")),
                candidateCommit=last["candidateCommit"])


def publish_context(state, task_id):
    """Read only, for feature-t7: everything a Publish authorization must be able to show (FR-26, SC-6)."""
    record = view_of(state, task_id)
    decisions = []
    for fact in budget_ledger.decisions(state, task_id):
        payload = fact.get("payload") or {}
        decisions.append(dict(factId=fact["factId"], subject=fact["purpose"], conclusion=payload.get("conclusion"),
                              outcome=payload.get("outcome"), consumedBy=fact.get("consumedBy"),
                              budget=copy.deepcopy((payload.get("derived") or {}).get("budget"))))
    rounds = [dict(round=r["round"], status=r["status"], candidateCommit=r["candidateCommit"], baseCommit=r["baseCommit"],
                   document=copy.deepcopy(r["document"]), verdict=copy.deepcopy(r.get("verdict")),
                   semantics=copy.deepcopy(r.get("semantics")), failure=copy.deepcopy(r.get("failure")),
                   disposed=copy.deepcopy(r.get("disposed", [])))
              for r in record["rounds"]]
    return dict(taskId=task_id, switch=copy.deepcopy(record["configurations"]), rounds=rounds,
                rulings=copy.deepcopy(record["rulings"]), reservations=copy.deepcopy(record["reservations"]),
                decisions=copy.deepcopy(record["decisions"]), budgetDecisions=decisions)
