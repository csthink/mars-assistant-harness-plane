"""The Define Task / Review Definition commands both entries run (standalone CLI and serve-stdio).

Every state change goes through the feature-t2 progression functions (Progression Commit); this
module only decides which fact, edge and condition the business rule selects. External effects
(review execution, ruling write) are registered as execution descriptors in the same transaction and
performed by the execution layer outside it; their results come back through `settle_execution`.
"""
import copy
from datetime import datetime, timezone

from domain.definition import gate, review, rulings
from domain.definition.candidate import load_candidate, sha256
from domain.definition.results import (
    BASIS_MISSING, CANDIDATE_BYTES_CHANGED, CANDIDATE_RECORDED, DEFINITION_FROZEN, EXECUTION_SETTLED,
    FINDING_DISPOSED, FORMAL_AUTHORIZATION_NOT_APPLICABLE, FORMAL_AUTHORIZATION_RECORDED, HUMAN_FINDINGS_PENDING,
    IDEMPOTENT_REPLAY, INPUT_INVALID, POSITION_NOT_APPLICABLE, REQUEST_CONFLICT, REVIEW_DISPATCHED,
    REVISION_NOT_ALLOWED_HERE, RULING_REGISTERED, RULING_WRITE_INDETERMINATE, RULING_WRITE_PRECONDITION_FAILED,
    VERDICT_RECORDED, DefinitionRejection,
)
from domain.workflow import progression, reservations, states
from domain.workflow.results import VERSION_CONFLICT, WorkflowRejection

HUMAN = "N-DEF-HUMAN"
CONFIG = "N-DEF-REVIEW-CONFIG"
DISPATCH = "N-DEF-REVIEW-DISPATCH"
REVIEWER = "N-DEF-REVIEWER"
BUDGET = "N-DEF-BUDGET-DECISION"
CONTINUE = "N-DEF-CONTINUE"
ACCEPT_RESERVATION_NODE = "N-DEF-ACCEPT-RESERVATION"
FROZEN = "N-DEF-FROZEN"
COMMANDS = ("submit", "formal-authorize", "dispatch", "decide", "status")
PENDING, RUNNING, SETTLED, BLOCKED, INDETERMINATE = "pending", "running", "settled", "blocked", "indeterminate"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today():
    return datetime.now(timezone.utc).date().isoformat()


def task_record(state, task_id):
    progression.instance(state, task_id)
    return state["tasks"][task_id]


def definition_of(task):
    return task.setdefault("taskDefinition", dict(candidates=[], rounds=[], rulings=[], reservations=[], formal=[],
                                                  decisions=[], frozen=None))


def descriptors(state):
    return state.setdefault("executionDescriptors", {})


def _authority(payload):
    ref = payload.get("authorityRef")
    if not isinstance(ref, str) or not ref:
        raise WorkflowRejection("AUTHORITY_MISSING", "authorityRef is required: every progression binds to an authorising fact")
    return ref


def _version(inst, payload):
    expected = payload.get("expectedRuntimeVersion")
    if expected is not None and str(expected) != inst["runtimeVersion"]:
        raise WorkflowRejection(VERSION_CONFLICT, "expected Runtime Version does not match the current one",
                                expected=str(expected), current=inst["runtimeVersion"])


def _cid(payload):
    cid = payload.get("commandId")
    if not isinstance(cid, str) or not cid:
        raise DefinitionRejection(INPUT_INVALID, "commandId is required")
    return cid


def _at(inst, *nodes):
    if inst["lifecycle"] != states.ACTIVE:
        raise WorkflowRejection("TASK_TERMINAL", "the Workflow reached a terminal lifecycle and cannot progress",
                                lifecycle=inst["lifecycle"])
    if inst["position"] not in nodes:
        raise DefinitionRejection(POSITION_NOT_APPLICABLE, "this Definition command is not legal at the current position",
                                  position=inst["position"], legal=list(nodes))


def _condition(state, topology, task_id, cid, condition, authority):
    return progression.update_condition(state, topology, task_id, dict(commandId=cid, condition=condition,
                                                                       authorityRef=authority), revision=state["revision"])


def _advance(state, topology, task_id, cid, edge, authority, triggers=(), purpose=None):
    return progression.advance(state, topology, task_id, dict(commandId=cid, edgeId=edge, triggers=list(triggers),
                                                              purpose=purpose, authorityRef=authority),
                               revision=state["revision"])


def _fact(state, topology, task_id, fact_id, kind, purpose, authority, payload):
    return progression.record_fact(state, topology, task_id, dict(factId=fact_id, kind=kind, purpose=purpose,
                                                                  authorityRef=authority, payload=payload),
                                   revision=state["revision"])


def _record_result(state, topology, task_id, cid, authority):
    """Walk the standard condition path of the current node up to RESULT_RECORDED."""
    inst = progression.instance(state, task_id)
    node = inst["position"]
    semantic = topology.semantic_type(node)
    step = 0
    while inst["condition"] != states.RESULT_RECORDED:
        nxt = states.next_condition(node, semantic, inst["condition"])
        if nxt is None:
            break
        _condition(state, topology, task_id, f"{cid}:cond:{node}:{step}", nxt, authority)
        step += 1


def _await_human(state, topology, task_id, cid, authority):
    inst = progression.instance(state, task_id)
    if inst["condition"] == states.ENTERED:
        _condition(state, topology, task_id, cid + ":await", states.AWAITING_HUMAN_ACTION, authority)


def _to_dispatch(state, topology, task_id, cid, authority):
    """After Continue the Human decision outcome node is left along Resume definition review (E-D15)."""
    inst = progression.instance(state, task_id)
    if inst["position"] == CONTINUE:
        _advance(state, topology, task_id, cid + ":e-d15", "E-D15", authority)


# -- Define Task ---------------------------------------------------------------------------------
def _route(state, topology, task, cid, authority):
    """Review Definition Enabled?: read the recorded switch, record it, take Enabled or Disabled."""
    task_id = task["taskId"]
    inst = task["workflowInstance"]
    configuration = copy.deepcopy(inst["reviewConfiguration"])
    enabled = bool(configuration.get("definitionReview"))
    _record_result(state, topology, task_id, cid + ":config", authority)
    fact_id = cid + ":review-switch"
    _fact(state, topology, task_id, fact_id, "configuration-decision", "review-definition-switch", authority,
          dict(definitionReview=enabled, source=configuration.get("source")))
    edge = "E-D03" if enabled else "E-D04"
    _advance(state, topology, task_id, cid + ":" + edge.lower(), edge, authority, [fact_id], "review-definition-switch")
    if not enabled:
        _await_human(state, topology, task_id, cid, authority)
    return dict(edge=edge, definitionReview=enabled, source=configuration.get("source"), switchFact=fact_id)


def submit(state, topology, context, payload):
    task_id = payload.get("taskId")
    task = task_record(state, task_id)
    inst = task["workflowInstance"]
    definition = definition_of(task)
    cid = _cid(payload)
    for candidate in definition["candidates"]:
        if candidate["commandId"] == cid:
            if candidate["commit"] != payload.get("commit"):
                raise DefinitionRejection(REQUEST_CONFLICT, "commandId already bound to another candidate", commandId=cid)
            return dict(result=IDEMPOTENT_REPLAY, candidate=copy.deepcopy(candidate))
    authority = _authority(payload)
    if inst["position"] == DISPATCH or inst["position"] == CONTINUE:
        return revise(state, topology, context, payload, task, cid, authority)
    _at(inst, HUMAN)
    _version(inst, payload)
    loaded = load_candidate(context.repo, context.repository_root, task, payload.get("commit"), payload.get("author"))
    candidate = dict(candidateId="C%d" % (len(definition["candidates"]) + 1), commandId=cid, **loaded,
                     authorityRef=authority, recordedAt=now(), occurrence=progression.occurrence(inst, task_id),
                     kind="define-task")
    fact_id = cid + ":candidate"
    _record_result(state, topology, task_id, cid + ":human", authority)
    _fact(state, topology, task_id, fact_id, "human-decision", "define-task", authority,
          dict(candidateId=candidate["candidateId"], commit=candidate["commit"], path=candidate["path"],
               bytes=candidate["bytes"], sha256=candidate["sha256"], author=copy.deepcopy(candidate["author"])))
    definition["candidates"].append(candidate)
    _advance(state, topology, task_id, cid + ":e-d01", "E-D01", authority, [fact_id], "define-task")
    _advance(state, topology, task_id, cid + ":e-d02", "E-D02", authority)
    route = _route(state, topology, task, cid, authority)
    return dict(result=CANDIDATE_RECORDED, candidate=copy.deepcopy(candidate), route=route,
                position=inst["position"], condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])


def revise(state, topology, context, payload, task, cid, authority):
    """A revised candidate between rounds: only at the dispatch position after a FAIL verdict."""
    task_id = task["taskId"]
    inst = task["workflowInstance"]
    definition = definition_of(task)
    _version(inst, payload)
    verdicts = [r for r in definition["rounds"] if r.get("verdict")]
    last_round = definition["rounds"][-1] if definition["rounds"] else None
    current = definition["candidates"][-1]
    if (not verdicts or verdicts[-1]["verdict"]["verdict"] != "FAIL" or last_round is not verdicts[-1]
            or current["candidateId"] != verdicts[-1]["candidateId"]):
        raise DefinitionRejection(REVISION_NOT_ALLOWED_HERE,
                                  "a revised candidate is accepted only at the dispatch position after a FAIL verdict",
                                  position=inst["position"])
    _to_dispatch(state, topology, task_id, cid, authority)
    loaded = load_candidate(context.repo, context.repository_root, task, payload.get("commit"), payload.get("author"))
    candidate = dict(candidateId="C%d" % (len(definition["candidates"]) + 1), commandId=cid, **loaded,
                     authorityRef=authority, recordedAt=now(), occurrence=progression.occurrence(inst, task_id),
                     kind="revision", revises=current["candidateId"])
    _fact(state, topology, task_id, cid + ":candidate", "human-decision", "define-task-revision", authority,
          dict(candidateId=candidate["candidateId"], commit=candidate["commit"], sha256=candidate["sha256"],
               author=copy.deepcopy(candidate["author"])))
    definition["candidates"].append(candidate)
    return dict(result=CANDIDATE_RECORDED, candidate=copy.deepcopy(candidate), position=inst["position"],
                condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])


# -- Owner formal authorization entry (Assistant OD-390, way B) -----------------------------------
def _next_round(definition):
    return "r%d" % (len(definition["rounds"]) + 1)


def formal_authorize(state, topology, context, payload):
    task_id = payload.get("taskId")
    task = task_record(state, task_id)
    inst = task["workflowInstance"]
    definition = definition_of(task)
    cid = _cid(payload)
    for record in definition["formal"]:
        if record["commandId"] == cid:
            return dict(result=IDEMPOTENT_REPLAY, formal=copy.deepcopy(record))
    authority = _authority(payload)
    _at(inst, DISPATCH, CONTINUE)
    _version(inst, payload)
    port, _mapping, registry_revision = review.select_port(context.repository_root, context.entry, payload.get("portId"))
    if port["capability"]["status"] == "REVIEW_ENABLED":
        raise DefinitionRejection(FORMAL_AUTHORIZATION_NOT_APPLICABLE,
                                  "the port is REVIEW_ENABLED; no Owner formal authorization is recorded for it", portId=port["id"])
    max_calls = payload.get("maxCalls")
    if type(max_calls) is not int or max_calls < 1:
        raise DefinitionRejection(INPUT_INVALID, "maxCalls must be a positive integer")
    _to_dispatch(state, topology, task_id, cid, authority)
    candidate = definition["candidates"][-1]
    rnd = _next_round(definition)
    fact_id = f"formal:{task_id}:{rnd}:{cid}"
    body = dict(taskId=task_id, workflowInstance=task_id, occurrence=progression.occurrence(inst, task_id),
                object=dict(path=candidate["path"], bytes=candidate["bytes"], sha256=candidate["sha256"]),
                reviewObject=dict(candidateId=candidate["candidateId"], path=candidate["path"], bytes=candidate["bytes"],
                                  sha256=candidate["sha256"]),
                round=int(rnd[1:]), roundLabel=rnd, attemptId=f"{task_id}:review:{rnd}", portId=port["id"], entry=context.entry,
                profileDigest=port["profile"]["digest"], capability=port["capability"]["status"],
                registryRevision=registry_revision, maxCalls=max_calls, decisionRef=authority)
    _fact(state, topology, task_id, fact_id, "human-decision", "owner-formal-review-authorization", authority, body)
    record = dict(commandId=cid, factId=fact_id, recordedAt=now(), **body)
    definition["formal"].append(record)
    return dict(result=FORMAL_AUTHORIZATION_RECORDED, formal=copy.deepcopy(record), runtimeVersion=inst["runtimeVersion"])


# -- dispatch and review settlement ----------------------------------------------------------------
def dispatch(state, topology, context, payload):
    task_id = payload.get("taskId")
    task = task_record(state, task_id)
    inst = task["workflowInstance"]
    definition = definition_of(task)
    cid = _cid(payload)
    for record in definition["rounds"]:
        if record["commandId"] == cid:
            return dict(result=IDEMPOTENT_REPLAY, round=copy.deepcopy(record), executionId=record["executionId"])
    authority = _authority(payload)
    _at(inst, DISPATCH, CONTINUE)
    _version(inst, payload)
    port, mapping, registry_revision = review.select_port(context.repository_root, context.entry)
    context.authorizer_check()
    _to_dispatch(state, topology, task_id, cid, authority)
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection("RECOVERY_REQUIRED_BLOCKS_PROGRESSION", "the dispatch node needs recovery first")
    candidate = definition["candidates"][-1]
    rnd = _next_round(definition)
    attempt_id = f"{task_id}:review:{rnd}"
    execution_id = f"review:{task_id}:{rnd}"
    formal = [f for f in definition["formal"] if f["roundLabel"] == rnd and f["portId"] == port["id"]]
    previous = next((r for r in reversed(definition["rounds"]) if r.get("verdict")), None)
    _record_result(state, topology, task_id, cid + ":dispatch", authority)
    fact_id = cid + ":dispatch"
    _fact(state, topology, task_id, fact_id, "human-decision", "review-dispatch", authority,
          dict(round=rnd, candidateId=candidate["candidateId"], portId=port["id"]))
    _advance(state, topology, task_id, cid + ":e-d05", "E-D05", authority, [fact_id], "review-dispatch")
    progression.open_attempt(state, topology, task_id, dict(attemptId=attempt_id, purpose="review", authorityRef=authority),
                             revision=state["revision"])
    reservations.reserve(state, topology, task_id, dict(reservationId=execution_id, purpose="review-execution",
                                                        authorityRef=authority, executionRef=execution_id,
                                                        protects=[candidate["path"]]), revision=state["revision"])
    record = dict(commandId=cid, round=rnd, candidateId=candidate["candidateId"], attemptId=attempt_id,
                  reservationId=execution_id, executionId=execution_id, portId=port["id"], entry=context.entry,
                  registryRevision=registry_revision, formalFactId=formal[-1]["factId"] if formal else None,
                  previousRound=copy.deepcopy(previous.get("published")) if previous else None,
                  status="dispatched", dispatchedAt=now(), authorityRef=authority, verdict=None, failure=None)
    definition["rounds"].append(record)
    descriptors(state)[execution_id] = dict(
        executionId=execution_id, purpose="review", taskId=task_id, status=PENDING, attemptId=attempt_id,
        createdAt=now(), createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None,
        input=dict(round=rnd, subject=f"{task_id}-task", candidate={k: candidate[k] for k in ("candidateId", "commit", "path", "bytes", "sha256")},
                   author=copy.deepcopy(candidate["author"]), authorIdentity=copy.deepcopy(candidate["authorIdentity"]),
                   anchor=copy.deepcopy(task["anchor"]),
                   maxCalls=formal[-1]["maxCalls"] if formal else 1,
                   worktree=task["worktree"], branch=task["branch"], portId=port["id"], mappingId=mapping["id"],
                   formalFactId=record["formalFactId"], previousRound=record["previousRound"],
                   runtime=copy.deepcopy(payload.get("runtimeContext"))))
    return dict(result=REVIEW_DISPATCHED, round=copy.deepcopy(record), executionId=execution_id,
                position=inst["position"], runtimeVersion=inst["runtimeVersion"])


def start_review(state, topology, descriptor, generation_ref):
    task_id = descriptor["taskId"]
    inst = progression.instance(state, task_id)
    progression.start_attempt(state, topology, task_id, dict(attemptId=descriptor["attemptId"], commandId="start:" + descriptor["executionId"],
                                                             executionRef=descriptor["executionId"], authorityRef=descriptor["authorityRef"]),
                              revision=state["revision"])
    if inst["position"] == REVIEWER and inst["condition"] == states.ENTERED:
        _condition(state, topology, task_id, "start:" + descriptor["executionId"] + ":executing", states.EXECUTING,
                   descriptor["authorityRef"])


def _route_verdict(state, topology, task, round_record, authority):
    """At Definition Review · Verdict = PASS?: stop for human findings, else take PASS or FAIL."""
    task_id = task["taskId"]
    inst = task["workflowInstance"]
    verdict = round_record["verdict"]
    pending = [f for f in verdict["humanFindings"] if f not in round_record.get("disposed", [])]
    if pending:
        round_record["status"] = "awaiting-human-disposition"
        return dict(stopped=HUMAN_FINDINGS_PENDING, pending=pending)
    edge = "E-D07" if verdict["verdict"] == "PASS" else "E-D08"
    _advance(state, topology, task_id, f"route:{round_record['executionId']}:{edge.lower()}", edge, authority)
    if edge == "E-D07":
        _await_human(state, topology, task_id, f"route:{round_record['executionId']}", authority)
    round_record["status"] = "routed"
    return dict(edge=edge)


def settle_review(state, topology, descriptor, outcome):
    task = task_record(state, descriptor["taskId"])
    task_id = task["taskId"]
    inst = task["workflowInstance"]
    definition = definition_of(task)
    round_record = next(r for r in definition["rounds"] if r["executionId"] == descriptor["executionId"])
    if round_record["status"] not in ("dispatched",):
        return dict(result=IDEMPOTENT_REPLAY, round=copy.deepcopy(round_record))
    authority = descriptor["authorityRef"]
    candidate = next(c for c in definition["candidates"] if c["candidateId"] == round_record["candidateId"])
    base = "settle:" + descriptor["executionId"]
    evidence = dict(executionId=descriptor["executionId"], receiptRef=copy.deepcopy(outcome.get("receiptRef")),
                    classification=outcome.get("classification"), failureCode=outcome.get("failureCode"))
    try:
        accepted = review.accept_verdict(outcome, round_record, candidate)
    except DefinitionRejection as exc:
        accepted = None
        mismatch = exc if outcome.get("classification") == review.VALID else None
    if accepted is None:
        status, reason = review.failure_of(outcome)
        if mismatch is not None:
            status, reason = "EXECUTION_FAILED", dict(classification="verdict-not-acceptable", problems=mismatch.detail.get("problems"))
        progression.settle_attempt(state, topology, task_id, dict(attemptId=round_record["attemptId"], status=status,
                                                                  evidence=dict(evidence, reason=reason), commandId=base),
                                   revision=state["revision"])
        if status == "EXECUTION_FAILED" and (outcome.get("receiptRef") or outcome.get("classification") == "preflight_failed"):
            # The execution fact that settles the reservation: the Receipt, or the refusal before any release
            # (the same rule as Validate Change; a preflight failure without a Receipt never reached the port).
            fact = outcome.get("receiptRef") or dict(kind="refused-before-release", executionId=descriptor["executionId"],
                                                     failureCode=outcome.get("failureCode"))
            reservations.settle(state, topology, task_id, dict(reservationId=round_record["reservationId"], settlement=dict(
                executionFact=fact, attemptId=round_record["attemptId"])), revision=state["revision"])
        if inst["condition"] != states.RECOVERY_REQUIRED:
            _condition(state, topology, task_id, base + ":recovery", states.RECOVERY_REQUIRED, authority)
        round_record.update(status="execution-failed" if status == "EXECUTION_FAILED" else "indeterminate",
                            failure=dict(status=status, **reason), settledAt=now())
        return dict(result=EXECUTION_SETTLED, attempt=status, reason=reason, position=inst["position"],
                    condition=inst["condition"])
    progression.settle_attempt(state, topology, task_id, dict(attemptId=round_record["attemptId"], status="COMPLETED",
                                                              evidence=evidence, commandId=base), revision=state["revision"])
    reservations.settle(state, topology, task_id, dict(reservationId=round_record["reservationId"], settlement=dict(
        executionFact=outcome.get("receiptRef") or accepted["evidenceRef"], attemptId=round_record["attemptId"])),
                        revision=state["revision"])
    _record_result(state, topology, task_id, base, authority)
    fact_id = base + ":verdict"
    _fact(state, topology, task_id, fact_id, "reviewer-verdict", "definition-review", authority,
          dict(round=round_record["round"], **copy.deepcopy(accepted)))
    _advance(state, topology, task_id, base + ":e-d06", "E-D06", authority, [fact_id], "definition-review")
    _record_result(state, topology, task_id, base + ":decision", authority)
    round_record.update(verdict=accepted, published=copy.deepcopy(outcome.get("published")), settledAt=now(),
                        verdictFact=fact_id, disposed=[])
    routed = _route_verdict(state, topology, task, round_record, authority)
    return dict(result=VERDICT_RECORDED, verdict=accepted["verdict"], routed=routed, position=inst["position"],
                condition=inst["condition"], runtimeVersion=inst["runtimeVersion"])


# -- Human Gate decisions with rulings ---------------------------------------------------------------
def _branch_bytes(context, task, path):
    try:
        return context.repo.read("refs/heads/" + task["branch"], path)
    except Exception:
        return None


def _ruling_items(context, task, definition, specs):
    """Fix numbers, bytes and digests of the rulings to write in one commit."""
    base = context.repo.resolve("refs/heads/" + task["branch"])
    taken = set(rulings.existing_numbers(task["worktree"], task["taskId"], base))
    taken |= {r["number"] for r in definition["rulings"]}
    number = max(taken) if taken else 0
    items = []
    for spec in specs:
        number += 1
        path = f"tasks/{task['taskId']}/rulings/" + rulings.filename(number, spec["type"])
        raw = rulings.render(number, today(), spec["type"], spec["object"], spec["basis"], spec["decision"], spec["body"])
        rulings.lint(context.repository_root, path, raw)
        items.append(dict(number=number, type=spec["type"], path=path, bytes=len(raw), sha256=sha256(raw),
                          content=raw.decode("utf-8"), status="registered"))
    return base, items


def _decision_text(payload):
    text = payload.get("decisionText")
    if not isinstance(text, str) or not text.strip() or "\n" in text:
        raise DefinitionRejection(INPUT_INVALID, "decisionText carries the Human's exact words on one line")
    return text


def decide(state, topology, context, payload):
    task_id = payload.get("taskId")
    task = task_record(state, task_id)
    inst = task["workflowInstance"]
    definition = definition_of(task)
    cid = _cid(payload)
    for record in definition["decisions"]:
        if record["commandId"] == cid:
            descriptor = descriptors(state).get(record["executionId"])
            if descriptor and descriptor["status"] == BLOCKED:
                descriptor.update(status=PENDING, lastError=None)
            return dict(result=IDEMPOTENT_REPLAY, decision=copy.deepcopy(record), executionId=record["executionId"])
    authority = _authority(payload)
    decision = payload.get("decision")
    text = _decision_text(payload)
    if decision == gate.DISPOSE:
        return dispose(state, topology, context, payload, task, cid, authority, text)
    if not gate.requires_definition_entry(inst["position"], decision):
        raise DefinitionRejection(POSITION_NOT_APPLICABLE, "only the two Definition-freezing decisions use this entry here",
                                  position=inst["position"], decision=decision,
                                  legal=[d for n, d in sorted(gate.DEFINITION_ENTRY_DECISIONS) if n == inst["position"]])
    _at(inst, gate.AUTH_GATE, gate.ESCALATION_GATE)
    _version(inst, payload)
    legal = [d["decision"] for d in progression.decisions(inst, topology)]
    if decision not in legal:
        raise WorkflowRejection("DECISION_NOT_LEGAL_HERE", "this decision is not in the legal set at the current position",
                                decision=decision, legal=legal)
    if any(a["status"] in ("CREATED", "RUNNING") for a in inst["attempts"]):
        raise DefinitionRejection(RULING_WRITE_PRECONDITION_FAILED, "an attempt is still in progress")
    if decision == gate.AUTHORIZE:
        basis = gate.authorize_basis(inst, definition)
    else:
        basis = gate.reservation_basis(definition, payload.get("reservation"))
    candidate = basis["candidate"]
    current = _branch_bytes(context, task, candidate["path"])
    if current is None or sha256(current) != candidate["sha256"]:
        raise DefinitionRejection(CANDIDATE_BYTES_CHANGED, "the task branch no longer carries the bound candidate bytes",
                                  path=candidate["path"], bound=candidate["sha256"],
                                  current=sha256(current) if current is not None else None)
    obj = rulings.object_line(candidate)
    boundary = "本裁定只定稿该精确 Definition，不授权施工以外的后续阶段、真实模型调用、发布、合并或清理，也不承载 done。"
    specs = []
    if basis["kind"] == "review-skip":
        switch = next((f for f in inst["facts"].values() if f["purpose"] == "review-definition-switch"
                       and f["payload"].get("definitionReview") is False), None)
        if switch is None:
            raise DefinitionRejection(BASIS_MISSING, "no recorded review-switch fact for the Disabled path")
        specs.append(dict(type="review-skip", object=obj,
                          basis=f"领域事实 {switch['factId']}（Review Definition 开关 {switch['payload'].get('source')} 关闭）；授权 {authority}",
                          decision=f"Human 原话「{text}」。对该精确候选关闭定义评审；未发起评审，不产生 Verdict 或 Receipt。",
                          body="# 定义评审关闭\n\n由 HarnessPlane 领域在 Human 定稿时按记录的评审开关生成。"))
        finalization_basis = f"tasks/{task_id}/rulings/RU-%02d-definition-review-skip.md"
    elif basis["kind"] == "verdict":
        finalization_basis = "终轮判词 " + str(basis["round"]["verdict"].get("evidenceRef") or basis["round"]["verdictFact"])
    else:
        finalization_basis = "FAIL 判词 " + str(basis["round"]["verdict"].get("evidenceRef") or basis["round"]["verdictFact"])
    reservation = payload.get("reservation") if basis["kind"] == "reservation" else None
    final_decision = f"Human 原话「{text}」。定稿页首精确 Definition，定稿时 Definition 零字节变化。" + (
        f"带保留接受：{reservation.strip()}；原 FAIL 判词与 Findings 保留。" if reservation else "") + boundary
    specs.append(dict(type="finalization", object=obj, basis=finalization_basis, decision=final_decision,
                      body="# Definition 定稿\n\n由 HarnessPlane 领域在 Human Gate 决定时生成；决定在裁定件写入任务分支后推进。"))
    base, items = _ruling_items(context, task, definition, specs)
    if basis["kind"] == "review-skip":
        final = items[-1]
        spec = specs[-1]
        spec["basis"] = finalization_basis % items[0]["number"]
        raw = rulings.render(final["number"], today(), "finalization", spec["object"], spec["basis"], spec["decision"], spec["body"])
        rulings.lint(context.repository_root, final["path"], raw)
        final.update(bytes=len(raw), sha256=sha256(raw), content=raw.decode("utf-8"))
    execution_id = f"ruling:{task_id}:{cid}"
    record = dict(commandId=cid, decision=decision, decisionText=text, reservation=reservation, basis=dict(
        kind=basis["kind"], candidateId=candidate["candidateId"], round=basis.get("round", {}).get("round")),
        rulings=[i["number"] for i in items], executionId=execution_id, status="registered", authorityRef=authority,
        expectedRuntimeVersion=inst["runtimeVersion"], registeredAt=now())
    definition["decisions"].append(record)
    for item in items:
        definition["rulings"].append(dict({k: v for k, v in item.items() if k != "content"}, commandId=cid))
    if reservation:
        definition["reservations"].append(dict(commandId=cid, reservation=reservation, round=basis["round"]["round"],
                                               verdict=copy.deepcopy(basis["round"]["verdict"])))
    descriptors(state)[execution_id] = dict(
        executionId=execution_id, purpose="ruling-write", taskId=task_id, status=PENDING, attemptId=None,
        createdAt=now(), createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None,
        input=dict(kind="decision", commandId=cid, worktree=task["worktree"], branch=task["branch"], base=base,
                   items=items, message=f"docs({task_id}): record {decision} rulings"))
    return dict(result=RULING_REGISTERED, decision=copy.deepcopy(record), executionId=execution_id,
                rulings=[{k: v for k, v in i.items() if k != "content"} for i in items])


def dispose(state, topology, context, payload, task, cid, authority, text):
    """Human disposition of `human` findings at the verdict decision node (finding-disposition ruling)."""
    task_id = task["taskId"]
    inst = task["workflowInstance"]
    definition = definition_of(task)
    _at(inst, gate.VERDICT_DECISION)
    _version(inst, payload)
    round_record = definition["rounds"][-1] if definition["rounds"] else None
    if not round_record or round_record.get("status") != "awaiting-human-disposition":
        raise DefinitionRejection(POSITION_NOT_APPLICABLE, "no human findings are waiting for disposition")
    findings = payload.get("findings")
    pending = [f for f in round_record["verdict"]["humanFindings"] if f not in round_record.get("disposed", [])]
    if not isinstance(findings, dict) or sorted(findings) != sorted(pending) or not all(
            isinstance(v, str) and v.strip() for v in findings.values()):
        raise DefinitionRejection(INPUT_INVALID, "findings must dispose exactly the pending human findings", pending=pending)
    candidate = next(c for c in definition["candidates"] if c["candidateId"] == round_record["candidateId"])
    ids = "、".join(sorted(findings))
    spec = dict(type="finding-disposition", object=f"{ids} · {rulings.object_line(candidate)}",
                basis="判词 " + str(round_record["verdict"].get("evidenceRef") or round_record["verdictFact"]),
                decision=f"Human 原话「{text}」。" + "；".join(f"{k}：{v.strip()}" for k, v in sorted(findings.items())),
                body="# human finding 处置\n\n由 HarnessPlane 领域生成；处置写入后按原判词结论推进。")
    base, items = _ruling_items(context, task, definition, [spec])
    execution_id = f"ruling:{task_id}:{cid}"
    record = dict(commandId=cid, decision=gate.DISPOSE, decisionText=text, findings=copy.deepcopy(findings),
                  round=round_record["round"], rulings=[i["number"] for i in items], executionId=execution_id,
                  status="registered", authorityRef=authority, registeredAt=now())
    definition["decisions"].append(record)
    for item in items:
        definition["rulings"].append(dict({k: v for k, v in item.items() if k != "content"}, commandId=cid))
    descriptors(state)[execution_id] = dict(
        executionId=execution_id, purpose="ruling-write", taskId=task_id, status=PENDING, attemptId=None,
        createdAt=now(), createdRevision=state["revision"], authorityRef=authority, result=None, lastError=None,
        input=dict(kind="disposition", commandId=cid, worktree=task["worktree"], branch=task["branch"], base=base,
                   items=items, message=f"docs({task_id}): record human finding disposition"))
    return dict(result=RULING_REGISTERED, decision=copy.deepcopy(record), executionId=execution_id)


def settle_rulings(state, topology, descriptor, outcome):
    task = task_record(state, descriptor["taskId"])
    task_id = task["taskId"]
    inst = task["workflowInstance"]
    definition = definition_of(task)
    record = next(d for d in definition["decisions"] if d["executionId"] == descriptor["executionId"])
    if record["status"] in ("completed",):
        return dict(result=IDEMPOTENT_REPLAY, decision=copy.deepcopy(record))
    mine = [r for r in definition["rulings"] if r["commandId"] == record["commandId"]]
    if outcome.get("state") != "written":
        code = outcome.get("code")
        if code == RULING_WRITE_PRECONDITION_FAILED:
            record["status"] = "blocked"
            return dict(result=EXECUTION_SETTLED, blocked=True, reason=copy.deepcopy(outcome))
        for r in mine:
            r["status"] = "indeterminate"
        record["status"] = "indeterminate"
        return dict(result=EXECUTION_SETTLED, indeterminate=True, code=RULING_WRITE_INDETERMINATE, reason=copy.deepcopy(outcome))
    for r in mine:
        r.update(status="written", commit=outcome["commit"])
    authority = record["authorityRef"]
    if record["decision"] == gate.DISPOSE:
        round_record = next(r for r in definition["rounds"] if r["round"] == record["round"])
        round_record.setdefault("disposed", []).extend(sorted(record["findings"]))
        record["status"] = "completed"
        routed = _route_verdict(state, topology, task, round_record, authority)
        return dict(result=FINDING_DISPOSED, routed=routed, position=inst["position"], runtimeVersion=inst["runtimeVersion"])
    progression.decide(state, topology, task_id, dict(commandId="decide:" + record["commandId"], decision=record["decision"],
                                                      authorityRef=authority, reservation=record.get("reservation")),
                       revision=state["revision"])
    if inst["position"] == ACCEPT_RESERVATION_NODE:
        _advance(state, topology, task_id, "decide:" + record["commandId"] + ":e-d16", "E-D16", authority)
    candidate = next(c for c in definition["candidates"] if c["candidateId"] == record["basis"]["candidateId"])
    definition["frozen"] = dict(candidateId=candidate["candidateId"], path=candidate["path"], bytes=candidate["bytes"],
                                sha256=candidate["sha256"], commit=candidate["commit"],
                                rulings=[dict(number=r["number"], type=r["type"], path=r["path"], sha256=r["sha256"],
                                              commit=r["commit"]) for r in mine],
                                reservation=record.get("reservation"), frozenAt=now())
    record["status"] = "completed"
    return dict(result=DEFINITION_FROZEN, frozen=copy.deepcopy(definition["frozen"]), position=inst["position"],
                runtimeVersion=inst["runtimeVersion"])


# -- read side ----------------------------------------------------------------------------------------
def view(state, task_id):
    task = task_record(state, task_id)
    definition = copy.deepcopy(definition_of(task)) if "taskDefinition" in task else definition_of(copy.deepcopy(task))
    for candidate in definition["candidates"]:
        candidate.pop("content", None)
    return dict(taskId=task_id, frozen=definition["frozen"], candidates=definition["candidates"],
                rounds=definition["rounds"], rulings=definition["rulings"], reservations=definition["reservations"],
                formal=definition["formal"], decisions=definition["decisions"],
                executions={k: {x: v[x] for x in ("executionId", "purpose", "status", "lastError")}
                            for k, v in state.get("executionDescriptors", {}).items() if v["taskId"] == task_id})


def frozen_definition(state, task_id):
    """Read-only for downstream (feature-t4): the frozen Definition identity and its rulings, or None."""
    task = task_record(state, task_id)
    return copy.deepcopy((task.get("taskDefinition") or {}).get("frozen"))


HANDLERS = {"submit": submit, "formal-authorize": formal_authorize, "dispatch": dispatch, "decide": decide}
EXECUTION_START = {"review": start_review}
EXECUTION_SETTLE = {"review": settle_review, "ruling-write": settle_rulings}


def apply(state, topology, context, name, payload):
    handler = HANDLERS.get(name)
    if handler is None:
        raise DefinitionRejection(INPUT_INVALID, "unknown definition command: " + str(name), commands=list(HANDLERS))
    return handler(state, topology, context, payload)
