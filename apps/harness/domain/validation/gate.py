"""Validation Human decisions: finding disposition, escalation Accept With reservation, resume after Continue.

Accept With reservation at `Human Gate · Validation Escalation` is, by FR-26, the Publish authorization of
that path; it must carry the reservation and keep the original FAIL verdict and its findings as its decision
context. The generic `workflow decide` path cannot carry either, so it refuses exactly this decision and the
workflow.decide projection stops listing it (an intentional narrowing of feature-t2, Definition Scope In,
same form as feature-t3's). Continue and Close Task keep the generic decide. After a generic Continue the
task sits at the Continue outcome node; `validate resume` (or feature-t4's implement dispatch) takes E-V13.

`human` findings of a verdict are disposed by the Human before the verdict routes; the disposition is a
finding-disposition ruling written on the task branch by feature-t3's two-phase ruling writer.
"""
import copy
from datetime import datetime, timezone

from domain.definition import rulings
from domain.validation import config, dispatch, records
from domain.validation.results import (
    BASIS_NOT_FINAL, EXECUTION_SETTLED, FINDING_DISPOSED, IDEMPOTENT_REPLAY, INPUT_INVALID, POSITION_NOT_APPLICABLE,
    REMEDIATION_RESUMED, RESERVATION_ACCEPTED, RESERVATION_REQUIRED, RULING_REGISTERED, ValidationRejection,
)
from domain.validation.verdict import VERDICT_DECISION, route
from domain.workflow import progression, states
from domain.workflow.results import DECISION_NOT_LEGAL_HERE, WorkflowRejection

ESCALATION_GATE = "N-VALIDATE-ESCALATION-GATE"
ACCEPT_RESERVATION = "Accept With reservation"
ACCEPT_NODE = "N-VALIDATE-ACCEPT-RESERVATION"
CONTINUE_NODE = "N-VALIDATE-CONTINUE"
REMEDIATION_NODE = "N-VALIDATE-REMEDIATION-DISPATCH"
VALIDATION_ENTRY_DECISIONS = frozenset({(ESCALATION_GATE, ACCEPT_RESERVATION)})
RULING_PURPOSE = "validation-ruling-write"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def requires_validation_entry(position, decision):
    return (position, decision) in VALIDATION_ENTRY_DECISIONS


def generic_filter(position, decisions):
    """Drop the decision the generic entry may not submit; used by the workflow projection and status."""
    return [d for d in decisions
            if (position, d["decision"] if isinstance(d, dict) else d) not in VALIDATION_ENTRY_DECISIONS]


def _text(payload):
    text = payload.get("decisionText")
    if not isinstance(text, str) or not text.strip() or "\n" in text:
        raise ValidationRejection(INPUT_INVALID, "decisionText carries the Human's exact words on one line")
    return text


def accept_with_reservation(state, topology, task_id, payload, command_id, authority, context=None):
    record = records.ledger(state, task_id)
    for done in record["decisions"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, decision=copy.deepcopy(done))
    inst = progression.instance(state, task_id)
    if inst["position"] != ESCALATION_GATE or inst["lifecycle"] != states.ACTIVE:
        raise ValidationRejection(POSITION_NOT_APPLICABLE, "Accept With reservation is decided at the Validation escalation gate",
                                  position=inst["position"])
    text = _text(payload)
    reservation = payload.get("reservation")
    if not isinstance(reservation, str) or not reservation.strip():
        raise ValidationRejection(RESERVATION_REQUIRED, "Accept With reservation needs the reservation text")
    legal = [d["decision"] for d in progression.decisions(inst, topology)]
    if ACCEPT_RESERVATION not in legal:
        raise WorkflowRejection(DECISION_NOT_LEGAL_HERE, "this decision is not in the legal set here", legal=legal)
    last = records.last_verdict_round(record)
    current = dispatch.candidate(state, task_id)["commit"]
    if last is None or last["verdict"]["verdict"] != "FAIL" or last["candidateCommit"] != current:
        raise ValidationRejection(BASIS_NOT_FINAL, "Accept With reservation keeps the final FAIL verdict of the current candidate",
                                  round=(last or {}).get("round"), candidateCommit=current)
    # feature-t7 (Assistant KB-265, FR-26): this decision is the path's Publish authorization, so it carries the exact
    # binding and the digest of the Publish authorization context in the same decision fact. A binding refusal keeps
    # its Publish reason (code and field path) inside this entry's INPUT_INVALID.
    from domain.publish import binding as publish_binding, records as publish_records
    from domain.publish.results import PublishRejection
    try:
        bound, context_digest = publish_binding.require(state, getattr(context, "repository_root", None), task_id,
                                                        payload.get("publishBinding"), payload.get("contextDigest"))
    except PublishRejection as exc:
        raise ValidationRejection(INPUT_INVALID, "the Publish authorization binding was refused: " + str(exc),
                                  publishReason=exc.reason()) from exc
    if inst["condition"] == states.AWAITING_HUMAN_ACTION:
        progression.update_condition(state, topology, task_id, dict(commandId=command_id + ":record",
                                                                    condition=states.RESULT_RECORDED, authorityRef=authority),
                                     revision=state["revision"])
    context = dict(round=last["round"], candidateCommit=last["candidateCommit"], verdictFact=last["verdictFact"],
                   verdict=last["verdict"]["verdict"], evidenceRef=copy.deepcopy(last["verdict"].get("evidenceRef")),
                   receiptRef=copy.deepcopy(last["verdict"].get("receiptRef")),
                   findings=copy.deepcopy(last["verdict"]["findings"]))
    fact_id = command_id + ":decision"
    progression.record_fact(state, topology, task_id, dict(
        factId=fact_id, kind="human-decision", purpose="gate-decision", authorityRef=authority,
        payload=dict(decision=ACCEPT_RESERVATION, edgeId="E-V12", reservation=reservation.strip(), decisionText=text,
                     decisionContext=context, publishBinding=copy.deepcopy(bound), publishContextDigest=context_digest,
                     operation=publish_records.operation_id(task_id, fact_id))), revision=state["revision"])
    config.advance(state, topology, task_id, command_id, "E-V12", authority, [fact_id], "gate-decision")
    config.advance(state, topology, task_id, command_id + ":e-v14", "E-V14", authority)
    done = dict(commandId=command_id, decision=ACCEPT_RESERVATION, decisionText=text, reservation=reservation.strip(),
                factId=fact_id, decisionContext=context, authorityRef=authority, decidedAt=now(),
                publishBinding=copy.deepcopy(bound), publishContextDigest=context_digest)
    publish_records.register_authorization(state, task_id, command_id=command_id, fact_id=fact_id, edge="E-V12", binding=bound,
                                           context_digest=context_digest, decision_text=text, authority=authority,
                                           at=done["decidedAt"])
    record["decisions"].append(done)
    record["reservations"].append(dict(commandId=command_id, reservation=reservation.strip(), round=last["round"],
                                       factId=fact_id, verdict=copy.deepcopy(last["verdict"])))
    return dict(result=RESERVATION_ACCEPTED, decision=copy.deepcopy(done), position=inst["position"],
                condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])


def resume(state, topology, task_id, payload, command_id, authority):
    """After a generic Continue at the Validation escalation gate: Continue outcome -> remediation dispatch (E-V13)."""
    inst = progression.instance(state, task_id)
    for commit in inst["commits"]:
        if commit["commandId"] == command_id + ":e-v13":
            return dict(result=IDEMPOTENT_REPLAY, commit=copy.deepcopy(commit))
    if inst["position"] != CONTINUE_NODE:
        raise ValidationRejection(POSITION_NOT_APPLICABLE, "resume runs at the Validation Continue outcome", position=inst["position"])
    config.advance(state, topology, task_id, command_id + ":e-v13", "E-V13", authority)
    return dict(result=REMEDIATION_RESUMED, position=inst["position"], condition=inst["condition"],
                runtimeVersion=inst["runtimeVersion"])


def _ruling_number(context, task, record):
    base = context.repo.resolve("refs/heads/" + task["branch"])
    taken = set(rulings.existing_numbers(task["worktree"], task["taskId"], base))
    taken |= {r["number"] for r in (task.get("taskDefinition") or {}).get("rulings", [])}
    taken |= {r["number"] for r in record["rulings"]}
    return base, (max(taken) if taken else 0) + 1


def dispose(state, topology, context, payload, command_id, authority):
    task_id = payload["taskId"]
    task = dict(state["tasks"][task_id], taskId=task_id)
    record = records.ledger(state, task_id)
    for done in record["decisions"]:
        if done["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, decision=copy.deepcopy(done), executionId=done.get("executionId"))
    inst = progression.instance(state, task_id)
    if inst["position"] != VERDICT_DECISION:
        raise ValidationRejection(POSITION_NOT_APPLICABLE, "human findings are disposed at the Validation verdict decision",
                                  position=inst["position"])
    text = _text(payload)
    last = record["rounds"][-1] if record["rounds"] else None
    if not last or last.get("status") != "awaiting-human-disposition":
        raise ValidationRejection(POSITION_NOT_APPLICABLE, "no human findings are waiting for disposition")
    findings = payload.get("findings")
    pending = [f for f in last["verdict"]["humanFindings"] if f not in last.get("disposed", [])]
    if not isinstance(findings, dict) or sorted(findings) != sorted(pending) or not all(
            isinstance(v, str) and v.strip() for v in findings.values()):
        raise ValidationRejection(INPUT_INVALID, "findings must dispose exactly the pending human findings", pending=pending)
    base, number = _ruling_number(context, task, record)
    path = "tasks/%s/rulings/RU-%02d-validation-finding-disposition.md" % (task_id, number)
    document = last["document"]
    obj = "%s · %s · %d bytes · SHA-256 %s" % ("、".join(sorted(findings)), document["path"], document["bytes"], document["sha256"])
    basis = "判词 %s（impl %s，候选提交 %s）" % ((last["verdict"].get("evidenceRef") or {}).get("path") or last["verdictFact"],
                                           last["round"], last["candidateCommit"])
    decision = "Human 原话「%s」。" % text + "；".join("%s：%s" % (k, v.strip()) for k, v in sorted(findings.items()))
    raw = rulings.render(number, now()[:10], "finding-disposition", obj, basis, decision,
                         "# Validate Change human finding 处置\n\n由 HarnessPlane 领域生成；处置写入后按原判词结论推进。")
    rulings.lint(context.repository_root, path, raw)
    item = dict(number=number, type="finding-disposition", path=path, bytes=len(raw), sha256=rulings.sha256(raw),
                content=raw.decode("utf-8"), status="registered")
    execution_id = "ruling:%s:%s" % (task_id, command_id)
    done = dict(commandId=command_id, decision="Dispose findings", decisionText=text, findings=copy.deepcopy(findings),
                round=last["round"], executionId=execution_id, rulings=[number], status="registered",
                authorityRef=authority, registeredAt=now())
    record["decisions"].append(done)
    record["rulings"].append(dict({k: v for k, v in item.items() if k != "content"}, commandId=command_id))
    state.setdefault("executionDescriptors", {})[execution_id] = dict(
        executionId=execution_id, purpose=RULING_PURPOSE, taskId=task_id, status="pending", attemptId=None,
        createdAt=now(), createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None,
        input=dict(kind="validation-disposition", commandId=command_id, worktree=task["worktree"], branch=task["branch"],
                   base=base, items=[item], message="docs(%s): record Validate Change human finding disposition" % task_id))
    return dict(result=RULING_REGISTERED, decision=copy.deepcopy(done), executionId=execution_id)


def settle_disposition(state, topology, descriptor, outcome):
    task_id = descriptor["taskId"]
    record = records.ledger(state, task_id)
    done = next(d for d in record["decisions"] if d.get("executionId") == descriptor["executionId"])
    if done["status"] == "completed":
        return dict(result=IDEMPOTENT_REPLAY, decision=copy.deepcopy(done))
    mine = [r for r in record["rulings"] if r["commandId"] == done["commandId"]]
    if outcome.get("state") != "written":
        if outcome.get("code") == "RULING_WRITE_PRECONDITION_FAILED":
            done["status"] = "blocked"
            return dict(result=EXECUTION_SETTLED, blocked=True, reason=copy.deepcopy(outcome))
        for r in mine:
            r["status"] = "indeterminate"
        done["status"] = "indeterminate"
        return dict(result=EXECUTION_SETTLED, indeterminate=True, reason=copy.deepcopy(outcome))
    for r in mine:
        r.update(status="written", commit=outcome["commit"])
    last = next(r for r in record["rounds"] if r["round"] == done["round"] and r.get("verdict"))
    last.setdefault("disposed", []).extend(sorted(done["findings"]))
    done["status"] = "completed"
    inst = progression.instance(state, task_id)
    routed = route(state, topology, task_id, last, done["authorityRef"])
    return dict(result=FINDING_DISPOSED, routed=routed, position=inst["position"], runtimeVersion=inst["runtimeVersion"])
