"""Implement dispatch: FR-60 checks and the walk from a dispatch node to the Implementer node.

Dispatch is a Control Plane action on a CONTROL_PLANE_ORCHESTRATOR node (N-IMPL-DISPATCH, or one of the
two Verification remediation nodes). One domain transaction checks, in this order, and rejects with a
machine-distinguishable reason: the task exists (otherwise capacity or acceptance is required), the
Workflow is ACTIVE and at a dispatch position, the role and purpose belong to that position, the
requested worktree is the bound one, the authority maps to the Definition finalization recorded by
feature-t3, the product-side registration exists, the budget fits it, and no other execution writer
holds the same worktree. Continuing or recovering an existing task never counts as a new acceptance.

The transaction then records the dispatch fact, crosses exactly one registered edge per commit to
N-IMPL-EXECUTE, opens the attempt, holds the Workflow reservation and stores the execution descriptor.
Nothing external is released here; the executor starts the Agent later, after the port has reserved.
"""
import copy
import hashlib
import os
from pathlib import Path

from domain.acceptance import terminal as acceptance_terminal
from domain.workflow import states
from domain.workflow.progression import now
from domain.workflow.results import TASK_TERMINAL, WorkflowRejection
from domain.implement_verify import registration, seams, steps, worktree
from domain.implement_verify.results import (
    ACCEPTANCE_REQUIRED, AUTHORITY_NOT_DERIVABLE, BUDGET_EXCEEDS_PROFILE, CANDIDATE_MISMATCH, CAPACITY_EXHAUSTED,
    DISPATCHED, EXECUTION_WRITER_BUSY, IDEMPOTENT_REPLAY, POSITION_NOT_APPLICABLE, PROFILE_PURPOSE_MISMATCH,
    REGISTRY_ENTRY_MISSING, REQUEST_CONFLICT, ROLE_NOT_LEGAL_HERE, WORKTREE_BINDING_MISMATCH, ImplementVerifyRejection,
)

IMPLEMENT_NODE = "N-IMPL-EXECUTE"
DISPATCH_EDGES = {
    "N-IMPL-DISPATCH": "E-I01",
    "N-VERIFY-AUTONOMOUS-REMEDIATION": "E-I09",
    "N-VERIFY-HUMAN-REMEDIATION": "E-I14",
    # feature-t5: Validation remediation dispatch (Budget Remains E-V07 or Human Continue E-V10 then E-V13).
    "N-VALIDATE-REMEDIATION-DISPATCH": "E-V08",
}
# The Human continuation outcome is routed to the human remediation node first (E-I13).
CONTINUE_EDGE = ("N-VERIFY-CONTINUE", "E-I13", "N-VERIFY-HUMAN-REMEDIATION")
# Every Continue outcome this dispatch accepts: node -> (edge, remediation dispatch node). feature-t5 adds Validation.
CONTINUE_EDGES = {CONTINUE_EDGE[0]: CONTINUE_EDGE[1:], "N-VALIDATE-CONTINUE": ("E-V13", "N-VALIDATE-REMEDIATION-DISPATCH")}
VALIDATION_ORIGINS = ("N-VALIDATE-REMEDIATION-DISPATCH", "N-VALIDATE-CONTINUE")
ROLE = "implementer"
# The entry that runs an execution of each port mode (feature-t3 PORT_ENTRY, inverted).
ENTRY_OF_MODE = {"standalone": "cli", "embedded": "runtime"}
IN_FLIGHT = (states.CREATED, states.RUNNING)


def _identity(value):
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _capacity(state, repository):
    limit = acceptance_terminal.concurrency_limit(state)
    if repository is None:
        tasks = [t for t, r in state.get("tasks", {}).items() if not r.get("terminal")]
        claimed = [k for k, c in state.get("claims", {}).items() if c.get("state") == "claimed"]
        return dict(count=len(tasks) + len(claimed), limit=limit, basis="domain-terminal-slots")
    from domain.acceptance.gitrepo import Repository
    repo = Repository(repository)
    commit = repo.resolve("HEAD")
    flight = acceptance_terminal.in_flight(state, repo, commit)
    return dict(count=flight["count"], limit=limit, basis="feature-t0 in_flight")


def _busy(state, task_id, worktree_path):
    """Another in-flight attempt or held execution reservation on the same worktree."""
    for other_id, record in state.get("tasks", {}).items():
        try:
            same = os.path.realpath(record["worktree"]) == os.path.realpath(worktree_path)
        except (KeyError, TypeError):
            continue
        if not same:
            continue
        inst = record["workflowInstance"]
        running = [a["attemptId"] for a in inst["attempts"] if a["status"] in IN_FLIGHT]
        held = sorted(r for r, v in inst["reservations"].items() if v["status"] == "held")
        if running or held:
            return dict(taskId=other_id, attempts=running, reservations=held)
    return None


def check(state, task_id, payload, *, repository):
    """All dispatch preconditions; returns (task, entry, finalization, baseline) or raises."""
    task = state.get("tasks", {}).get(task_id)
    if task is None:
        capacity = _capacity(state, repository)
        if capacity["count"] >= capacity["limit"]:
            raise ImplementVerifyRejection(CAPACITY_EXHAUSTED, "this dispatch needs a new acceptance and the in-flight "
                                           "task count has reached the concurrency limit", **capacity)
        raise ImplementVerifyRejection(ACCEPTANCE_REQUIRED, "the task is not accepted; dispatch never accepts a task "
                                       "or reuses another task's worktree", taskId=task_id, **capacity)
    inst = task["workflowInstance"]
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection(TASK_TERMINAL, "a terminal Workflow takes no dispatch", lifecycle=inst["lifecycle"])
    position = inst["position"]
    restart = position == IMPLEMENT_NODE and inst["condition"] == states.ENTERED
    if position not in DISPATCH_EDGES and position not in CONTINUE_EDGES and not restart:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "implement dispatch runs only at a dispatch position",
                                       position=position,
                                       dispatchPositions=sorted(DISPATCH_EDGES) + sorted(CONTINUE_EDGES) + [IMPLEMENT_NODE + " (ENTERED)"])
    if payload.get("role") != ROLE or payload.get("purpose") != registration.PURPOSE:
        raise ImplementVerifyRejection(ROLE_NOT_LEGAL_HERE, "only the implementer role with the coding-implementer "
                                       "purpose is dispatched here", role=payload.get("role"), purpose=payload.get("purpose"))
    requested = payload.get("worktree")
    if not isinstance(requested, str) or os.path.realpath(requested) != os.path.realpath(task["worktree"]):
        raise ImplementVerifyRejection(WORKTREE_BINDING_MISMATCH, "the requested worktree is not the one bound to the "
                                       "task at acceptance", requested=requested, bound=task["worktree"])
    path = worktree.bound(task)
    final = seams.finalization(state, task_id)
    if final is None:
        raise ImplementVerifyRejection(AUTHORITY_NOT_DERIVABLE, "the Definition of this task has no written "
                                       "finalization; implement dispatch has nothing to authorise it")
    if payload.get("finalizationRef") != final["ruling"].get("ruling"):
        raise ImplementVerifyRejection(AUTHORITY_NOT_DERIVABLE, "the offered authority does not map to the recorded "
                                       "Definition finalization", offered=payload.get("finalizationRef"),
                                       recorded=final["ruling"].get("ruling"))
    entry = registration.resolve(state, payload.get("portId"))
    if entry is None:
        raise ImplementVerifyRejection(REGISTRY_ENTRY_MISSING, "no product-side implementer registration for this "
                                       "(portId, purpose)", portId=payload.get("portId"), purpose=registration.PURPOSE)
    if entry["profile"]["purpose"] != registration.PURPOSE:
        raise ImplementVerifyRejection(PROFILE_PURPOSE_MISMATCH, "registered profile purpose is not coding-implementer")
    budget = payload.get("budget")
    if not isinstance(budget, dict) or set(budget) != set(registration.BUDGET_FIELDS) or any(
            type(budget[f]) is not int or not 1 <= budget[f] <= entry["budget"][f] for f in registration.BUDGET_FIELDS):
        raise ImplementVerifyRejection(BUDGET_EXCEEDS_PROFILE, "the requested budget is missing a limit or exceeds the "
                                       "registered profile budget", requested=budget, registered=entry["budget"])
    busy = _busy(state, task_id, task["worktree"])
    if busy:
        raise ImplementVerifyRejection(EXECUTION_WRITER_BUSY, "another execution already writes this worktree", **busy)
    baseline = worktree.snapshot(path)
    if not baseline["clean"]:
        raise ImplementVerifyRejection(CANDIDATE_MISMATCH, "the task worktree has uncommitted changes; a dispatch needs "
                                       "a clean baseline", baseline=baseline)
    return task, entry, final, baseline


def _remediation(state, task_id, origin=None):
    """The last recorded Verification Result that sent this task to remediation, if any.

    feature-t5: a dispatch from a Validation remediation position carries the last Validation FAIL verdict and
    its findings instead (read only from the Validate Change record).
    """
    if origin in VALIDATION_ORIGINS:
        from domain.validation import records as validation_records
        return validation_records.remediation_input(state, task_id)
    ledger = steps.ledger(state, task_id)
    failed = [v for v in ledger["verifications"].values() if v["result"] == "FAIL"]
    if not failed:
        return None
    last = max(failed, key=lambda v: int(v["recordedRevision"]))
    return dict(verificationId=last["verificationId"], findings=copy.deepcopy(last["findings"]),
                candidateCommit=last["candidateCommit"])


def dispatch(state, topology, task_id, payload, *, revision, repository=None):
    command_id = payload.get("commandId")
    if not isinstance(command_id, str) or not command_id:
        raise ImplementVerifyRejection(REQUEST_CONFLICT, "commandId is required")
    ledger = steps.ledger(state, task_id) if task_id in state.get("tasks", {}) else None
    if ledger is not None:
        for record in ledger["executions"].values():
            if record["commandId"] == command_id:
                if record["request"] != _request(payload):
                    raise ImplementVerifyRejection(REQUEST_CONFLICT, "commandId already bound to another dispatch",
                                                   commandId=command_id)
                return dict(result=IDEMPOTENT_REPLAY, execution=copy.deepcopy(record))
    task, entry, final, baseline = check(state, task_id, payload, repository=repository)
    authority = payload.get("authorityRef")
    if not isinstance(authority, str) or not authority:
        raise ImplementVerifyRejection(AUTHORITY_NOT_DERIVABLE, "authorityRef is required")
    ledger = steps.ledger(state, task_id)
    inst = steps.inst(state, task_id)
    origin = inst["position"]
    if inst["position"] in CONTINUE_EDGES:
        steps.advance(state, topology, task_id, command_id + ":continue", CONTINUE_EDGES[inst["position"]][0], authority,
                      revision=revision)
    if inst["position"] in DISPATCH_EDGES:
        node, edge = inst["position"], DISPATCH_EDGES[inst["position"]]
        steps.walk_to(state, topology, task_id, states.EXECUTING, command_id + ":dispatch", authority, revision=revision)
        fact_id = command_id + ":dispatch-fact"
        steps.fact(state, topology, task_id, fact_id, "execution-result", "implement-dispatch", authority,
                   dict(portId=entry["id"], mode=entry["mode"], role=ROLE, finalization=final["ruling"].get("ruling")),
                   revision=revision)
        steps.walk_to(state, topology, task_id, states.RESULT_RECORDED, command_id + ":dispatched", authority,
                      revision=revision)
        steps.advance(state, topology, task_id, command_id + ":" + edge, edge, authority, revision=revision,
                      triggers=[fact_id], purpose="implement-dispatch")
    execution_id = "implement:" + _identity([task_id, command_id])[:40]
    attempt_id = "attempt:" + execution_id
    steps.open_attempt(state, topology, task_id, attempt_id, "implement", authority, revision=revision)
    steps.reserve(state, topology, task_id, execution_id, "external-execution", authority,
                  ["port-reservation:" + execution_id], revision=revision)
    inst = steps.inst(state, task_id)
    record = dict(executionRequestId=execution_id, commandId=command_id, request=_request(payload), taskId=task_id,
                  attemptId=attempt_id, reservationId=execution_id, portId=entry["id"], mode=entry["mode"],
                  purpose=registration.PURPOSE, agent=entry["agent"], profileDigest=entry["profile"]["digest"],
                  budget=copy.deepcopy(payload["budget"]), authorityRef=authority,
                  occurrence=dict(workflowInstance=task_id, node=inst["position"],
                                  positionEntryRuntimeVersion=inst["positionEntryRevision"]),
                  finalization=copy.deepcopy(final), baseline=baseline, remediation=_remediation(state, task_id, origin),
                  worktree=task["worktree"], branch=task["branch"], status="dispatched", dispatchedRevision=revision,
                  programIdentity=None, settlement=None)
    ledger["executions"][execution_id] = record
    # feature-t3 execution layer: a data-only descriptor the entry owning this port mode schedules
    # (standalone -> cli, embedded -> runtime); the executor is looked up by purpose.
    state.setdefault("executionDescriptors", {})[execution_id] = dict(
        executionId=execution_id, purpose=registration.PURPOSE, taskId=task_id, status="pending", attemptId=attempt_id,
        createdAt=now(), createdRevision=revision, authorityRef=authority, result=None, lastError=None,
        entry=ENTRY_OF_MODE[entry["mode"]], input=dict(kind="implement", portId=entry["id"], mode=entry["mode"],
                                                     runtime=copy.deepcopy(payload.get("runtimeContext"))))
    # The trust boundary is reported as the profile declares it; nothing here claims stronger isolation (NFR-05).
    trust = dict(trustModel=entry["profile"]["trustModel"], limitations=list(entry["profile"]["limitations"]),
                 note="declared by the registered profile; current-user trusted local execution, no strong isolation")
    return dict(result=DISPATCHED, execution=copy.deepcopy(record), trustBoundary=trust,
                runtimeVersion=inst["runtimeVersion"])


def _request(payload):
    return {k: copy.deepcopy(payload.get(k)) for k in ("portId", "role", "purpose", "worktree", "budget",
                                                        "finalizationRef", "authorityRef")}


def pending(state, task_id):
    """Execution descriptors not yet settled, for the executor and for a restarted entry (query only)."""
    task = state.get("tasks", {}).get(task_id)
    if task is None:
        return []
    return [copy.deepcopy(r) for r in task.get("implementVerify", {}).get("executions", {}).values()
            if r["status"] in ("dispatched", "running")]
