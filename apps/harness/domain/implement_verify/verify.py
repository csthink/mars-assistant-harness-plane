"""Verify: applicability, prescribed deterministic checks and the immutable Verification Result (FR-23).

prepare() runs in one transaction at N-VERIFY-APPLICABILITY (or at N-VERIFY-EXECUTE after a recovery
restart). It binds the candidate the implement settlement routed, reads the finalized Definition bytes,
computes the applicable checks against the bound declaration revision and records the decision as a
`configuration-decision` fact (purpose verify-applicability; never `policy-decision`, which only the
Policy Gate produces under seam ruling S-05). None applicable follows E-I05 and is recorded apart from
PASS and FAIL. Otherwise the Verify attempt opens and runs; a Definition-required check that is not
registered is a check-execution failure that enters recovery (KB-259 option A), never "not applicable".

The checks run outside any transaction (runner in executors.py). settle() then re-reads the worktree:
the candidate must still be HEAD and clean, every check must map to PASS or FAIL, otherwise the attempt
is an execution failure and the node enters RECOVERY_REQUIRED without a business result. A recorded
Verification Result is immutable: no command rewrites it, a later declaration change does not touch it,
and the Verification escalation gate offers only Continue and Close Task (feature-t2 decision set).
"""
import copy
import hashlib

from domain.workflow import states
from domain.implement_verify import checks, seams, steps, worktree
from domain.implement_verify.results import (
    CANDIDATE_MISMATCH, CHECK_EXECUTION_FAILED, IDEMPOTENT_REPLAY, PENDING, POSITION_NOT_APPLICABLE,
    PRESCRIBED_CHECK_UNREGISTERED, VERIFY_FAIL, VERIFY_NOT_APPLICABLE, VERIFY_PASS, ImplementVerifyRejection,
)

APPLICABILITY_NODE = "N-VERIFY-APPLICABILITY"
VERIFY_NODE = "N-VERIFY-EXECUTE"


def _id(task_id, command_id):
    return "verify:" + hashlib.sha256(repr([task_id, command_id]).encode()).hexdigest()[:40]


def routed_candidate(state, task_id):
    """The candidate commit of the last completed implement settlement (its routing fact)."""
    executions = [e for e in steps.ledger(state, task_id)["executions"].values()
                  if e["status"] == "settled" and (e.get("settlement") or {}).get("kind") == "completed"]
    if not executions:
        raise ImplementVerifyRejection(CANDIDATE_MISMATCH, "no routed implementation candidate on this task")
    last = max(executions, key=lambda e: int(e["dispatchedRevision"]))
    return last


def prepare(state, topology, task_id, payload, *, revision):
    command_id = payload.get("commandId")
    authority = payload.get("authorityRef")
    ledger = steps.ledger(state, task_id)
    verification_id = _id(task_id, command_id)
    if verification_id in ledger["verifications"]:
        return dict(result=IDEMPOTENT_REPLAY, verification=copy.deepcopy(ledger["verifications"][verification_id]))
    inst = steps.inst(state, task_id)
    restart = inst["position"] == VERIFY_NODE and inst["condition"] == states.ENTERED
    if inst["position"] != APPLICABILITY_NODE and not restart:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "Verify runs only at the applicability decision or after "
                                       "a restart of the Verify node", position=inst["position"],
                                       condition=inst["condition"])
    execution = routed_candidate(state, task_id)
    candidate = execution["settlement"]["candidateCommit"]
    path = worktree.bound(state["tasks"][task_id])
    current = worktree.snapshot(path)
    if current["head"] != candidate or not current["clean"]:
        raise ImplementVerifyRejection(CANDIDATE_MISMATCH, "the task worktree is not the routed candidate; Verify binds "
                                       "exactly the candidate commit", candidate=candidate, current=current)
    final = execution["finalization"]["candidate"]
    raw = worktree.blob(path, final["commit"], final["path"])
    if hashlib.sha256(raw).hexdigest() != final["sha256"]:
        raise ImplementVerifyRejection(CANDIDATE_MISMATCH, "the finalized Definition bytes no longer match their identity",
                                       definition=final)
    required = checks.prescribed(raw)
    declared = checks.declared(state)
    registered = {c["id"]: c for c in declared["checks"]}
    missing = [c for c in required if c not in registered]
    changed = worktree.changed_files(path, execution["baseline"]["head"], candidate)
    selected = [c for c in declared["checks"] if c["id"] in required or checks.applicable(c, changed)]
    verification = dict(verificationId=verification_id, commandId=command_id, candidateCommit=candidate,
                        definition=copy.deepcopy(final), checksRevision=declared["revision"],
                        prescribed=required, missing=missing, applicable=[c["id"] for c in selected],
                        changedFiles=changed, result=None, findings=[], checkResults=[], attemptId=None,
                        recordedRevision=revision, status="prepared", authorityRef=authority)
    if not restart:
        steps.walk_to(state, topology, task_id, states.EXECUTING, verification_id + ":applicability", authority,
                      revision=revision)
        fact_id = verification_id + ":applicability"
        applicable = bool(selected) or bool(missing)
        steps.fact(state, topology, task_id, fact_id, "configuration-decision", "verify-applicability", authority,
                   dict(candidateCommit=candidate, checksRevision=declared["revision"], prescribed=required,
                        missing=missing, applicable=verification["applicable"],
                        conclusion="Applicable" if applicable else "None Applicable"), revision=revision)
        steps.walk_to(state, topology, task_id, states.RESULT_RECORDED, verification_id + ":decided", authority,
                      revision=revision)
        edge = "E-I04" if applicable else "E-I05"
        steps.advance(state, topology, task_id, verification_id + ":" + edge, edge, authority, revision=revision,
                      triggers=[fact_id], purpose="verify-applicability")
        if not applicable:
            verification.update(result="NOT_APPLICABLE", status="recorded", edge=edge)
            ledger["verifications"][verification_id] = verification
            return dict(result=VERIFY_NOT_APPLICABLE, verification=copy.deepcopy(verification))
    attempt_id = "attempt:" + verification_id
    steps.open_attempt(state, topology, task_id, attempt_id, "verify", authority, revision=revision)
    seams.start_attempt(state, topology, task_id, dict(attemptId=attempt_id, commandId=verification_id + ":start",
                                                       executionRef=verification_id, authorityRef=authority),
                        revision=revision)
    steps.condition(state, topology, task_id, verification_id + ":executing", states.EXECUTING, authority,
                    revision=revision)
    verification["attemptId"] = attempt_id
    verification["occurrence"] = dict(node=VERIFY_NODE, positionEntryRuntimeVersion=steps.inst(state, task_id)["positionEntryRevision"])
    verification["checks"] = copy.deepcopy(selected)
    ledger["verifications"][verification_id] = verification
    if missing:
        return _failure(state, topology, task_id, verification, PRESCRIBED_CHECK_UNREGISTERED,
                        dict(missing=missing, checksRevision=declared["revision"]), revision=revision)
    return dict(result=PENDING, verification=copy.deepcopy(verification))


def settle(state, topology, task_id, verification_id, results, *, revision):
    """Record the Verification Result from the runner's in-process results, or enter recovery."""
    ledger = steps.ledger(state, task_id)
    verification = ledger["verifications"].get(verification_id)
    if verification is None:
        raise ImplementVerifyRejection(POSITION_NOT_APPLICABLE, "no such verification", verificationId=verification_id)
    if verification["status"] != "prepared":
        return dict(result=IDEMPOTENT_REPLAY, verification=copy.deepcopy(verification))
    inst = steps.inst(state, task_id)
    if inst["position"] != VERIFY_NODE or inst["positionEntryRevision"] != verification["occurrence"]["positionEntryRuntimeVersion"]:
        verification.update(status="late-result-not-consumed")
        return dict(result=IDEMPOTENT_REPLAY, verification=copy.deepcopy(verification))
    authority = verification["authorityRef"]
    path = worktree.bound(state["tasks"][task_id])
    current = worktree.snapshot(path)
    verification["checkResults"] = copy.deepcopy(results)
    if current["head"] != verification["candidateCommit"] or not current["clean"]:
        return _failure(state, topology, task_id, verification, CHECK_EXECUTION_FAILED,
                        dict(reason="candidate-moved-during-checks", current=current), revision=revision)
    failed_to_run = [r for r in results if r.get("outcome") not in ("PASS", "FAIL")]
    if failed_to_run or [r["id"] for r in results] != [c["id"] for c in verification["checks"]]:
        return _failure(state, topology, task_id, verification, CHECK_EXECUTION_FAILED,
                        dict(reason="check-not-executed", failures=[dict(id=r.get("id"), failure=r.get("failure"))
                                                                    for r in failed_to_run]), revision=revision)
    outcome = "FAIL" if any(r["outcome"] == "FAIL" for r in results) else "PASS"
    findings = [dict(check=r["id"], exitCode=r["exitCode"], stdoutSha256=r["stdout"]["sha256"],
                     stderrSha256=r["stderr"]["sha256"], excerpt=r["stdout"]["excerpt"][-2048:] + r["stderr"]["excerpt"][-2048:])
                for r in results if r["outcome"] == "FAIL"]
    steps.settle_attempt(state, topology, task_id, verification["attemptId"], states.ATTEMPT_COMPLETED,
                         verification_id + ":settle", dict(result=outcome, checks=len(results)), revision=revision)
    fact_id = verification_id + ":result"
    steps.fact(state, topology, task_id, fact_id, "verify-result", "verification-result", authority,
               dict(verificationId=verification_id, result=outcome, candidateCommit=verification["candidateCommit"],
                    checksRevision=verification["checksRevision"], findings=findings), revision=revision)
    steps.walk_to(state, topology, task_id, states.RESULT_RECORDED, verification_id + ":recorded", authority,
                  revision=revision)
    edge = "E-I06" if outcome == "PASS" else "E-I07"
    steps.advance(state, topology, task_id, verification_id + ":" + edge, edge, authority, revision=revision,
                  triggers=[fact_id], purpose="verification-result")
    verification.update(result=outcome, findings=findings, status="recorded", edge=edge, fact=fact_id,
                        recordedRevision=revision)
    return dict(result=VERIFY_PASS if outcome == "PASS" else VERIFY_FAIL, verification=copy.deepcopy(verification),
                runtimeVersion=steps.inst(state, task_id)["runtimeVersion"])


def _failure(state, topology, task_id, verification, code, detail, *, revision):
    """No business result: the Verify attempt failed to execute and the node enters RECOVERY_REQUIRED."""
    verification_id = verification["verificationId"]
    steps.settle_attempt(state, topology, task_id, verification["attemptId"], states.EXECUTION_FAILED,
                         verification_id + ":settle", dict(code=code, **detail), revision=revision)
    steps.condition(state, topology, task_id, verification_id + ":recovery", states.RECOVERY_REQUIRED,
                    verification["authorityRef"], revision=revision)
    verification.update(status="execution-failed", failure=dict(code=code, **copy.deepcopy(detail)))
    return dict(result=code, verification=copy.deepcopy(verification),
                runtimeVersion=steps.inst(state, task_id)["runtimeVersion"])
