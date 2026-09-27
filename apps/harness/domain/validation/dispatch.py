"""`Validate Change · Reviewer`: candidate and baseline selection, round, Owner formal authorization, dispatch.

The dispatch transaction fixes everything the review needs: the candidate commit feature-t4 routed and
Verify passed (or found no applicable check), the baseline of the task's first implement dispatch, the
impl round, the previous valid round for the channel's inheritance, the author executions for feature-t6's
author vendor derivation, and the byte identities of the reviewed materials. It opens the attempt, holds
the Workflow reservation for the execution and registers a data-only execution descriptor (purpose
`change-review`) that this entry's execution layer runs later. Nothing external happens here.

A round whose attempt failed or stayed unknown was never delivered to the channel (no tracked Receipt,
review-channel r10 §6.10), so its retry keeps the same round label under a new attempt; only a round with
a recorded verdict advances the label.
"""
import copy
from datetime import datetime, timezone

from domain.definition import review as definition_review
from domain.implement_verify import steps as implement_steps, worktree
from domain.validation import materials, records
from domain.validation.results import (
    CANDIDATE_NOT_VERIFIED, EXECUTION_IN_FLIGHT, FORMAL_AUTHORIZATION_NOT_APPLICABLE, FORMAL_AUTHORIZATION_RECORDED,
    IDEMPOTENT_REPLAY, INPUT_INVALID, POSITION_NOT_APPLICABLE, REVIEW_DISPATCHED, ValidationRejection,
)
from domain.workflow import progression, reservations, states
from domain.workflow.results import RECOVERY_REQUIRED_BLOCKS_PROGRESSION, WorkflowRejection

REVIEWER = "N-VALIDATE-REVIEWER"
PURPOSE = "change-review"
FORMAL_PURPOSE = "owner-formal-review-authorization"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def candidate(state, task_id):
    """The routed candidate, its passing (or not applicable) Verify, the first dispatch baseline and the authors."""
    ledger = implement_steps.ledger(state, task_id)
    executions = sorted(ledger["executions"].values(), key=lambda e: int(e["dispatchedRevision"]))
    completed = [e for e in executions if e["status"] == "settled" and (e.get("settlement") or {}).get("kind") == "completed"]
    if not completed:
        raise ValidationRejection(CANDIDATE_NOT_VERIFIED, "no completed implementation candidate on this task")
    last = completed[-1]
    commit = last["settlement"]["candidateCommit"]
    verified = [v for v in ledger["verifications"].values() if v.get("candidateCommit") == commit and v.get("status") == "recorded"
                and v.get("result") in ("PASS", "NOT_APPLICABLE")]
    if not verified:
        raise ValidationRejection(CANDIDATE_NOT_VERIFIED, "the routed candidate has no PASS or None Applicable Verify outcome",
                                  candidateCommit=commit)
    verification = max(verified, key=lambda v: int(v["recordedRevision"]))
    return dict(commit=commit, baseCommit=executions[0]["baseline"]["head"], verification=copy.deepcopy(verification),
                authors=[e["executionRequestId"] for e in completed], finalization=copy.deepcopy(last["finalization"]),
                lastExecution=last["executionRequestId"])


def _round_label(record):
    delivered = [r for r in record["rounds"] if r.get("verdict")]
    return "r%d" % (len(delivered) + 1)


def _attempt_number(record, label):
    return len([r for r in record["rounds"] if r["round"] == label]) + 1


def _ids(task_id, label, number):
    return ("%s:change-review:%s:%d" % (task_id, label, number), "change-review:%s:%s:%d" % (task_id, label, number))


def _check(inst):
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection("TASK_TERMINAL", "the Workflow reached a terminal lifecycle", lifecycle=inst["lifecycle"])
    if inst["position"] != REVIEWER:
        raise ValidationRejection(POSITION_NOT_APPLICABLE, "the change review runs only at Validate Change · Reviewer",
                                  position=inst["position"])
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection(RECOVERY_REQUIRED_BLOCKS_PROGRESSION, "the Reviewer node needs recovery first")
    if inst["condition"] != states.ENTERED:
        raise ValidationRejection(EXECUTION_IN_FLIGHT, "a change review attempt is already in progress at this node",
                                  condition=inst["condition"])


def _review_object(task_id, label, found):
    return dict(path=materials.directory(task_id, label) + "/" + materials.DOCUMENT, commit=found["commit"])


def formal_authorize(state, topology, context, payload, command_id, authority):
    task_id = payload["taskId"]
    record = records.ledger(state, task_id)
    for done in record["formal"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, formal=copy.deepcopy(done))
    inst = progression.instance(state, task_id)
    _check(inst)
    port, _mapping, registry_revision = definition_review.select_port(context.repository_root, context.entry,
                                                                       payload.get("portId"))
    if port["capability"]["status"] == "REVIEW_ENABLED":
        raise ValidationRejection(FORMAL_AUTHORIZATION_NOT_APPLICABLE,
                                  "the port is REVIEW_ENABLED; no Owner formal authorization is recorded for it", portId=port["id"])
    max_calls = payload.get("maxCalls")
    if type(max_calls) is not int or max_calls < 1:
        raise ValidationRejection(INPUT_INVALID, "maxCalls must be a positive integer")
    found = candidate(state, task_id)
    label = _round_label(record)
    attempt_id, _execution = _ids(task_id, label, _attempt_number(record, label))
    fact_id = "formal:%s:impl:%s:%s" % (task_id, label, command_id)
    body = dict(taskId=task_id, workflowInstance=task_id, occurrence=progression.occurrence(inst, task_id),
                object=_review_object(task_id, label, found), round=int(label[1:]), roundLabel=label, stage="impl",
                attemptId=attempt_id, portId=port["id"], entry=context.entry, profileDigest=port["profile"]["digest"],
                capability=port["capability"]["status"], registryRevision=registry_revision, maxCalls=max_calls,
                decisionRef=authority)
    progression.record_fact(state, topology, task_id, dict(factId=fact_id, kind="human-decision", purpose=FORMAL_PURPOSE,
                                                           authorityRef=authority, payload=body), revision=state["revision"])
    done = dict(commandId=command_id, factId=fact_id, recordedAt=now(), **body)
    record["formal"].append(done)
    return dict(result=FORMAL_AUTHORIZATION_RECORDED, formal=copy.deepcopy(done), runtimeVersion=inst["runtimeVersion"])


def _extensions(payload):
    value = payload.get("roundExtensions") or []
    if not isinstance(value, list) or any(not isinstance(e, dict) or set(e) != {"authorized_by", "at", "added_rounds", "note"}
                                          or type(e["added_rounds"]) is not int or e["added_rounds"] < 1 for e in value):
        raise ValidationRejection(INPUT_INVALID, "roundExtensions must be Human authorization records "
                                  "{authorized_by, at, added_rounds, note}")
    return copy.deepcopy(value)


def _remediation_statement(state, task_id, found):
    record = implement_steps.ledger(state, task_id)["executions"].get(found["lastExecution"]) or {}
    fact = progression.instance(state, task_id)["facts"].get((record.get("settlement") or {}).get("fact")) or {}
    declaration = (fact.get("payload") or {}).get("declaration") or {}
    text = declaration.get("text") if isinstance(declaration, dict) else None
    return (text or "Implementer remediation; see the candidate change document")[:4000]


def dispatch(state, topology, context, payload, command_id, authority):
    task_id = payload["taskId"]
    task = state["tasks"][task_id]
    record = records.ledger(state, task_id)
    for done in record["rounds"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, round=copy.deepcopy(done), executionId=done["executionId"])
    inst = task["workflowInstance"]
    _check(inst)
    if any(r["status"] in ("dispatched", "running") for r in record["rounds"]):
        raise ValidationRejection(EXECUTION_IN_FLIGHT, "a change review of this task is already dispatched and not settled")
    port, mapping, registry_revision = definition_review.select_port(context.repository_root, context.entry,
                                                                     payload.get("portId"))
    context.authorizer_check()
    extensions = _extensions(payload)
    found = candidate(state, task_id)
    label = _round_label(record)
    number = _attempt_number(record, label)
    attempt_id, execution_id = _ids(task_id, label, number)
    path = worktree.bound(task)
    built = materials.build(path, dict(task, taskId=task_id), label, found["baseCommit"], found["commit"],
                            found["verification"], found["finalization"]["candidate"])
    fixed = materials.identity(built)
    previous = records.last_verdict_round(record)
    formal = [f for f in record["formal"] if f["roundLabel"] == label and f["attemptId"] == attempt_id and f["portId"] == port["id"]]
    progression.open_attempt(state, topology, task_id, dict(attemptId=attempt_id, purpose=PURPOSE, authorityRef=authority),
                             revision=state["revision"])
    document_path = materials.directory(task_id, label) + "/" + materials.DOCUMENT
    reservations.reserve(state, topology, task_id, dict(reservationId=execution_id, purpose="review-execution",
                                                        authorityRef=authority, executionRef=execution_id,
                                                        protects=[document_path]), revision=state["revision"])
    done = dict(commandId=command_id, round=label, attempt=number, attemptId=attempt_id, executionId=execution_id,
                reservationId=execution_id, candidateCommit=found["commit"], baseCommit=found["baseCommit"],
                verification=dict(verificationId=found["verification"]["verificationId"],
                                  result=found["verification"]["result"]),
                authorExecutionRefs=list(found["authors"]), finalization=copy.deepcopy(found["finalization"]),
                document=dict(fixed["document"], path=document_path), references=fixed["references"], portId=port["id"],
                entry=context.entry, registryRevision=registry_revision, mappingId=mapping["id"],
                formalFactId=formal[-1]["factId"] if formal else None, maxCalls=formal[-1]["maxCalls"] if formal else 1,
                previousRound=copy.deepcopy(previous.get("published")) if previous else None,
                previousFindings=[f["id"] for f in (previous["verdict"].get("findings") or [])] if previous else [],
                remediationStatement=_remediation_statement(state, task_id, found) if previous else None,
                roundExtensions=extensions, status="dispatched", dispatchedAt=now(), dispatchedRevision=str(state["revision"]),
                authorityRef=authority, verdict=None, failure=None, disposed=[])
    record["rounds"].append(done)
    state.setdefault("executionDescriptors", {})[execution_id] = dict(
        executionId=execution_id, purpose=PURPOSE, taskId=task_id, status="pending", attemptId=attempt_id,
        createdAt=now(), createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None,
        entry=context.entry, input=dict(round=label, subject="%s-task" % task_id, worktree=task["worktree"],
                                        branch=task["branch"], portId=port["id"], mappingId=mapping["id"],
                                        runtime=copy.deepcopy(payload.get("runtimeContext"))))
    return dict(result=REVIEW_DISPATCHED, round=copy.deepcopy(done), executionId=execution_id, position=inst["position"],
                runtimeVersion=inst["runtimeVersion"])


def start(state, topology, task_id, execution_id):
    """CREATED -> RUNNING for the round's attempt and ENTERED -> EXECUTING for the Reviewer node (own transaction)."""
    record = records.ledger(state, task_id)
    done = next(r for r in record["rounds"] if r["executionId"] == execution_id)
    if done["status"] != "dispatched":
        return copy.deepcopy(done)
    progression.start_attempt(state, topology, task_id, dict(attemptId=done["attemptId"], commandId="start:" + execution_id,
                                                             executionRef=execution_id, authorityRef=done["authorityRef"]),
                              revision=state["revision"])
    inst = progression.instance(state, task_id)
    if inst["position"] == REVIEWER and inst["condition"] == states.ENTERED:
        progression.update_condition(state, topology, task_id, dict(commandId="start:" + execution_id + ":executing",
                                                                    condition=states.EXECUTING,
                                                                    authorityRef=done["authorityRef"]), revision=state["revision"])
    done["status"] = "running"
    return copy.deepcopy(done)
