"""The Publish authorization context: one read-only composite view and its canonical digest (FR-26, SC-6).

What a Publish authorization must be able to show, read from the one domain state and the product-line
repository: the frozen Definition, the Definition review rounds with their verdicts, findings, rulings and
Definition-side reservations (feature-t3), the routed candidate and its Verification Result (feature-t4),
feature-t5's Publish authorization view (Validate Change switch, rounds, verdicts, findings, reservations and
decision context, budget decisions), every recorded Policy Decision (ordered by the integer domain revision,
not through policy/evaluate.decisions), the two Review switches recorded at acceptance with their source, the
Publish target configuration and the task branch head. The Human's authorization carries the digest of the
view they saw; the authorizing transaction recomputes it and refuses a stale one.
"""
import copy
import hashlib
import subprocess

import rfc8785

from domain.acceptance.gitrepo import environment
from domain.definition import commands as definition_commands
from domain.publish import configuration
from domain.validation import dispatch as validation_dispatch, records as validation_records
from domain.validation.results import ValidationRejection


def branch_head(repository, branch):
    """The task branch head in the product-line repository, or None when the branch does not resolve."""
    try:
        result = subprocess.run(["git", "-C", str(repository), "rev-parse", "--verify", "--quiet",
                                 "refs/heads/%s^{commit}" % branch], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=environment(repository), timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode().strip() or None


def _definition(state, task_id):
    view = definition_commands.view(state, task_id)
    return dict(frozen=copy.deepcopy(view["frozen"]), rounds=copy.deepcopy(view["rounds"]),
                reservations=copy.deepcopy(view["reservations"]),
                rulings=[{k: r.get(k) for k in ("number", "type", "path", "sha256", "status", "commit")}
                         for r in view["rulings"]])


def _candidate(state, task_id):
    try:
        found = validation_dispatch.candidate(state, task_id)
    except ValidationRejection as exc:
        return dict(problem=exc.code)
    verification = found["verification"]
    return dict(commit=found["commit"], baseCommit=found["baseCommit"], lastExecution=found["lastExecution"],
                verification={k: verification.get(k) for k in ("verificationId", "result", "candidateCommit",
                                                                "recordedRevision")})


def _policy(inst):
    rows = [dict(factId=f["factId"], subject=f["purpose"], node=f["node"], conclusion=(f.get("payload") or {}).get("conclusion"),
                 outcome=(f.get("payload") or {}).get("outcome"), domainRevision=str(f.get("domainRevision")))
            for f in inst["facts"].values() if f.get("kind") == "policy-decision"]
    return sorted(rows, key=lambda r: (int(r["domainRevision"]) if r["domainRevision"].isdigit() else -1, r["factId"]))


def view(state, repository, task_id):
    task = state["tasks"][task_id]
    inst = task["workflowInstance"]
    return dict(taskId=task_id, repositoryIdentity=task.get("repositoryIdentity"),
                taskBranch=dict(name=task["branch"], head=branch_head(repository, task["branch"])),
                reviewConfiguration=copy.deepcopy(inst.get("reviewConfiguration")),
                definition=_definition(state, task_id), candidate=_candidate(state, task_id),
                validateChange=validation_records.publish_context(state, task_id), policyDecisions=_policy(inst),
                publishTarget=configuration.current(state))


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()
