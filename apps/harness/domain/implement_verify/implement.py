"""Implement attempt lifecycle, settlement and candidate routing (spec FR-22, FR-48, FR-62; D-03 §5).

Two transactions bracket one Agent execution:

- start(): the descriptor becomes running, the attempt moves CREATED -> RUNNING through feature-t3's
  RUNNING function (seams.start_attempt) and the Implementer node moves ENTERED -> EXECUTING.
- settle(): reads what the execution port persisted in the same domain state (its reservation
  record, observations, result envelope and rediscovered program identity) plus the actual task
  worktree, maps them through settlement.classify(), and commits the one consistent outcome.

Neither function takes execution results from a caller: the executor runs in-process and passes only
the port error it caught, and everything else is re-read here. A completion declaration is an
implementation claim, never a Verification Result (FR-22). A candidate is a new commit on the bound
Task Branch that descends from the dispatch baseline with a clean worktree; anything else is not
consumable and the node enters RECOVERY_REQUIRED instead of following a business edge.
"""
import base64
import copy
import json

from domain.workflow import states
from domain.implement_verify import seams, settlement, steps, worktree
from domain.implement_verify.results import (
    CANDIDATE_ROUTED, IDEMPOTENT_REPLAY, IMPLEMENT_COMPLETED, PENDING, POSITION_NOT_APPLICABLE, RESULT_UNKNOWN,
    SETTLED, STOP_UNCONFIRMED, VENDOR_MAPPING_UNKNOWN, ImplementVerifyRejection,
)

IMPLEMENT_NODE = "N-IMPL-EXECUTE"
ROUTE_NODE = "N-IMPL-ROUTE"


def descriptor(state, task_id, execution_id):
    record = steps.ledger(state, task_id)["executions"].get(execution_id)
    if record is None:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "no such execution descriptor on this task",
                                       executionRequestId=execution_id)
    return record


def start(state, topology, task_id, execution_id, *, revision):
    """Mark the execution running just before the port releases it; replays are harmless."""
    record = descriptor(state, task_id, execution_id)
    if record["status"] != "dispatched":
        return dict(result=IDEMPOTENT_REPLAY, execution=copy.deepcopy(record))
    inst = steps.inst(state, task_id)
    if inst["position"] != record["occurrence"]["node"] or inst["positionEntryRevision"] != \
            record["occurrence"]["positionEntryRuntimeVersion"]:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "the execution belongs to an earlier occurrence",
                                       occurrence=record["occurrence"])
    seams.start_attempt(state, topology, task_id,
                        dict(attemptId=record["attemptId"], commandId=execution_id + ":start",
                             executionRef=execution_id, authorityRef=record["authorityRef"]), revision=revision)
    if inst["condition"] == states.ENTERED:
        steps.condition(state, topology, task_id, execution_id + ":executing", states.EXECUTING,
                        record["authorityRef"], revision=revision)
    record["status"] = "running"
    return dict(result=PENDING, execution=copy.deepcopy(record))


def port_record(state, execution_id):
    return copy.deepcopy(state.get("executionReservations", {}).get(execution_id))


def candidate(record):
    """Candidate facts from the bound worktree against the dispatch baseline (read-only)."""
    try:
        path = worktree.bound(dict(worktree=record["worktree"], branch=record["branch"]))
    except ImplementVerifyRejection as exc:
        # The Agent left the bound branch or worktree: nothing there is a candidate of this task.
        return dict(kind="binding-mismatch", commit=None, current=dict(head=None, clean=False, statusDigest=None,
                                                                    trackedChanges=[], untracked=[]),
                    changed=[], reason=exc.reason())
    current = worktree.snapshot(path)
    base = record["baseline"]["head"]
    head = current["head"]
    if head == base:
        kind = "no-commit" if current["clean"] else "uncommitted"
    elif not worktree.is_ancestor(path, base, head):
        kind = "not-descendant"
    elif not current["clean"]:
        kind = "uncommitted"
    else:
        kind = "candidate"
    changed = worktree.changed_files(path, base, head) if kind in ("candidate", "uncommitted") and head != base else []
    return dict(kind=kind, commit=head if kind == "candidate" else None, current=current, changed=changed)


def _declaration(port):
    """The Agent's own completion text, kept as an implementation claim with its digest."""
    if not port or port.get("result") is None:
        return None
    raw = base64.b64decode(port["result"], validate=True)
    envelope = json.loads(base64.b64decode(port["result_envelope"], validate=True))
    return dict(kind="implementation-claim", bytes=len(raw), sha256=settlement.sha(raw),
                text=raw.decode("utf-8", "replace")[:4096], actualBinding=copy.deepcopy(envelope.get("actualBinding")),
                envelopeSha256=settlement.sha(base64.b64decode(port["result_envelope"], validate=True)))


def settle(state, topology, task_id, execution_id, *, revision, port_error=None):
    """Commit the outcome the persisted facts support; pending facts change nothing."""
    record = descriptor(state, task_id, execution_id)
    if record["status"] == "settled":
        return dict(result=IDEMPOTENT_REPLAY, execution=copy.deepcopy(record))
    port = port_record(state, execution_id)
    verdict = settlement.classify(port, port_error)
    if verdict["kind"] == "pending":
        return dict(result=PENDING, execution=copy.deepcopy(record), physical=verdict)
    authority = record["authorityRef"]
    inst = steps.inst(state, task_id)
    if inst["lifecycle"] != states.ACTIVE or inst["position"] != IMPLEMENT_NODE or \
            inst["positionEntryRevision"] != record["occurrence"]["positionEntryRuntimeVersion"]:
        # The task was closed or the occurrence moved: the late result is never consumed. A terminal
        # physical fact still settles the reservation it protected (FR-27: held until the same
        # execution fact is settled); stop unconfirmed or unknown keeps it held.
        released = False
        reservation = inst["reservations"].get(record["reservationId"], {})
        if verdict["kind"] in ("completed", "failed", "stopped") and reservation.get("status") == "held":
            steps.settle_reservation(state, topology, task_id, record["reservationId"],
                                     dict(executionFact="port-execution:%s:%s" % (execution_id, verdict["kind"]),
                                          attemptId=record["attemptId"], outcome="late-" + verdict["kind"]),
                                     revision=revision)
            released = True
        record.update(status="settled", settlement=dict(kind="late-result-not-consumed", physical=verdict,
                                                        reservationReleased=released))
        return dict(result=SETTLED, execution=copy.deepcopy(record))
    program = (port or {}).get("program_identity")
    record["programIdentity"] = copy.deepcopy(program)
    evidence = dict(executionRequestId=execution_id, physical=verdict, programIdentity=program,
                    portRecordPhase=(port or {}).get("phase"))
    if verdict["kind"] == "completed":
        found = candidate(record)
        claim = _declaration(port)
        model = (claim or {}).get("actualBinding", {}) or {}
        agent = (((port or {}).get("intent") or {}).get("executionBinding") or {}).get("agent")
        vendor = seams.vendor_of(state, agent, model.get("model")) if model.get("model") and agent else None
        evidence.update(candidate=found, declaration=claim, modelVendor=vendor)
        if found["kind"] == "candidate" and vendor is not None:
            return _completed(state, topology, task_id, record, evidence, revision=revision)
        failure = VENDOR_MAPPING_UNKNOWN if vendor is None and found["kind"] == "candidate" else "candidate-" + found["kind"]
        return _recovery(state, topology, task_id, record, states.EXECUTION_FAILED, failure, evidence, revision=revision)
    if verdict["kind"] == "stop-unconfirmed":
        return _recovery(state, topology, task_id, record, states.ATTEMPT_INDETERMINATE, STOP_UNCONFIRMED, evidence,
                         revision=revision)
    if verdict["kind"] == "unknown":
        return _recovery(state, topology, task_id, record, states.ATTEMPT_INDETERMINATE, RESULT_UNKNOWN, evidence,
                         revision=revision)
    return _recovery(state, topology, task_id, record, states.EXECUTION_FAILED, verdict.get("reason", "failed"),
                     evidence, revision=revision, release=verdict["kind"] == "stopped")


def _completed(state, topology, task_id, record, evidence, *, revision):
    execution_id, authority = record["executionRequestId"], record["authorityRef"]
    steps.settle_attempt(state, topology, task_id, record["attemptId"], states.ATTEMPT_COMPLETED,
                         execution_id + ":settle", evidence, revision=revision)
    fact_id = execution_id + ":result"
    payload = dict(candidateCommit=evidence["candidate"]["commit"], changedFiles=evidence["candidate"]["changed"],
                   baseline=record["baseline"]["head"], declaration=evidence["declaration"],
                   programIdentity=evidence["programIdentity"], modelVendor=evidence["modelVendor"],
                   executionRequestId=execution_id, portId=record["portId"], mode=record["mode"])
    steps.fact(state, topology, task_id, fact_id, "execution-result", "implement-result", authority, payload,
               revision=revision)
    steps.walk_to(state, topology, task_id, states.RESULT_RECORDED, execution_id + ":recorded", authority,
                  revision=revision)
    steps.settle_reservation(state, topology, task_id, record["reservationId"],
                             dict(executionFact=fact_id, attemptId=record["attemptId"], outcome="completed"),
                             revision=revision)
    record.update(status="settled", settlement=dict(kind="completed", fact=fact_id,
                                                    candidateCommit=payload["candidateCommit"]))
    routed = route(state, topology, task_id, fact_id, authority, revision=revision)
    return dict(result=IMPLEMENT_COMPLETED, execution=copy.deepcopy(record), routed=routed,
                runtimeVersion=steps.inst(state, task_id)["runtimeVersion"])


def route(state, topology, task_id, fact_id, authority, *, revision):
    """E-I02 then E-I03: the Control Plane routes the recorded candidate to the applicability decision."""
    steps.advance(state, topology, task_id, fact_id + ":E-I02", "E-I02", authority, revision=revision,
                  triggers=[fact_id], purpose="implement-result")
    candidate_commit = steps.inst(state, task_id)["facts"][fact_id]["payload"]["candidateCommit"]
    steps.walk_to(state, topology, task_id, states.EXECUTING, fact_id + ":route", authority, revision=revision)
    route_fact = fact_id + ":routed"
    steps.fact(state, topology, task_id, route_fact, "execution-result", "candidate-route", authority,
               dict(candidateCommit=candidate_commit), revision=revision)
    steps.walk_to(state, topology, task_id, states.RESULT_RECORDED, fact_id + ":route-recorded", authority,
                  revision=revision)
    steps.advance(state, topology, task_id, fact_id + ":E-I03", "E-I03", authority, revision=revision,
                  triggers=[route_fact], purpose="candidate-route")
    return dict(result=CANDIDATE_ROUTED, candidateCommit=candidate_commit)


def _recovery(state, topology, task_id, record, status, reason, evidence, *, revision, release=False):
    """No consumable result: settle the attempt with its own evidence and stop in RECOVERY_REQUIRED."""
    execution_id = record["executionRequestId"]
    evidence = dict(evidence, reason=reason)
    steps.settle_attempt(state, topology, task_id, record["attemptId"], status, execution_id + ":settle", evidence,
                         revision=revision)
    steps.condition(state, topology, task_id, execution_id + ":recovery", states.RECOVERY_REQUIRED,
                    record["authorityRef"], revision=revision)
    if release:
        # A stopped execution whose escaped processes all exited is a settled execution fact (J-06 §7).
        fact_id = execution_id + ":stopped"
        steps.fact(state, topology, task_id, fact_id, "host-observation", "execution-stopped", record["authorityRef"],
                   dict(physical=evidence["physical"]), revision=revision)
        steps.settle_reservation(state, topology, task_id, record["reservationId"],
                                 dict(executionFact=fact_id, attemptId=record["attemptId"], outcome="stopped"),
                                 revision=revision)
    record.update(status="settled", settlement=dict(kind="recovery", reason=reason, attemptStatus=status,
                                                    reservationReleased=release))
    return dict(result=SETTLED, recovery=True, reason=reason, execution=copy.deepcopy(record),
                runtimeVersion=steps.inst(state, task_id)["runtimeVersion"])
