"""Progression Commit: the only way Workflow Runtime State changes (feature-t2).

Every change runs the same six steps inside one unit of work, and any failed step abandons the whole
transaction without a half-written state:

1. the offered expected Runtime Version equals the current one;
2. each offered trigger fact belongs to the current position, the current occurrence and the stated
   purpose, and has not been consumed;
3. the selected topology edge leaves the current node and the next snapshot is inside the legal
   combination matrix;
4. the immutable Progression Commit is written;
5. trigger consumption is bound to that commit;
6. the snapshot and the Runtime Version are updated.

Participants write only what they may produce: Human decisions, execution results, reviewer verdicts,
verification results and policy decisions arrive here as trigger facts. Choosing the edge, moving the
position and finalising the lifecycle stay with this module, which the Domain Core alone calls.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json

from domain.workflow import states
from domain.workflow.results import (
    ADVANCED, AUTHORITY_MISSING, CONDITION_UPDATED, DECISION_NOT_LEGAL_HERE, FINALIZED,
    IDEMPOTENT_REPLAY, ILLEGAL_STATE_COMBINATION, ILLEGAL_TRANSITION, PUBLISHED_NOT_CLOSEABLE,
    RECOVERY_REQUIRED_BLOCKS_PROGRESSION, REQUEST_CONFLICT, RESERVATION_HELD, TASK_NOT_FOUND,
    TASK_TERMINAL, TRIGGER_ALREADY_CONSUMED, TRIGGER_NOT_APPLICABLE, VERSION_CONFLICT,
    WorkflowRejection,
)

INITIAL_POSITION = "N-DEF-HUMAN"
CLOSE_TASK_DECISION = "Close Task"
FACT_KINDS = ("human-decision", "execution-result", "reviewer-verdict", "verify-result",
              "policy-decision", "configuration-decision", "host-observation")
CLOSURE_REASONS = ("human-initiated", "blocked-escalation")
# feature-t6: a policy-decision fact has exactly one producer, the Policy Gate (domain/policy/evaluate.py).
# The generic fact entry cannot write one, and progression consumes only an ALLOW produced by it.
POLICY_DECISION = "policy-decision"
POLICY_PRODUCER = "policy-gate"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def initial_instance(definition, review_configuration, revision):
    """The Workflow Instance record an accepted Task starts with (D-04 §14 scenario 1)."""
    return dict(definition=copy.deepcopy(definition), reviewConfiguration=copy.deepcopy(review_configuration),
                lifecycle=states.ACTIVE, position=INITIAL_POSITION, positionEntryRevision=revision,
                condition=states.AWAITING_HUMAN_ACTION, runtimeVersion="1", attempt=None, attempts=[],
                commits=[], facts={}, reservations={}, recovery=dict(assessments={}, current=None, authorizations={}),
                closure=None)


def instance(state, task_id):
    task = state.get("tasks", {}).get(task_id)
    if task is None:
        raise WorkflowRejection(TASK_NOT_FOUND, "no accepted Task with this identity: " + str(task_id), taskId=task_id)
    return task["workflowInstance"]


def occurrence(inst, task_id):
    """Current Position Occurrence Reference: instance identity + node + position entry version."""
    return dict(workflowInstance=task_id, node=inst["position"], positionEntryRuntimeVersion=inst["positionEntryRevision"])


def snapshot(inst):
    return dict(lifecycle=inst["lifecycle"], position=inst["position"], condition=inst["condition"],
                positionEntryRuntimeVersion=inst["positionEntryRevision"])


def terminal(inst):
    return inst["lifecycle"] in (states.COMPLETED, states.CLOSED)


def view(inst, topology, task_id):
    """Read-only layered view; the legal action set is derived here, never supplied by a caller."""
    node = inst["position"]
    semantic = topology.semantic_type(node)
    return dict(lifecycle=inst["lifecycle"], position=node, positionLabel=topology.label(node),
                semanticType=semantic, condition=inst["condition"], runtimeVersion=inst["runtimeVersion"],
                occurrence=occurrence(inst, task_id), occurrenceDigest=digest(occurrence(inst, task_id)),
                attempt=copy.deepcopy(inst["attempt"]), attempts=len(inst["attempts"]),
                commits=len(inst["commits"]), definition=copy.deepcopy(inst["definition"]),
                reviewConfiguration=copy.deepcopy(inst["reviewConfiguration"]),
                closure=copy.deepcopy(inst["closure"]), reservations=copy.deepcopy(inst["reservations"]),
                recovery=dict(current=copy.deepcopy(inst["recovery"]["current"]),
                              assessments=len(inst["recovery"]["assessments"])))


def _require_authority(authority_ref):
    if not isinstance(authority_ref, str) or not authority_ref:
        raise WorkflowRejection(AUTHORITY_MISSING, "authorityRef is required: every progression binds to an authorising fact")


def _check_version(inst, expected):
    if expected is not None and str(expected) != inst["runtimeVersion"]:
        raise WorkflowRejection(VERSION_CONFLICT, "expected Runtime Version does not match the current one",
                                expected=str(expected), current=inst["runtimeVersion"])


def _check_active(inst):
    if terminal(inst):
        raise WorkflowRejection(TASK_TERMINAL, "the Workflow reached a terminal lifecycle and cannot progress",
                                lifecycle=inst["lifecycle"])


def _consume(inst, task_id, fact_ids, node, purpose):
    """Step 2: triggers must belong to this position, occurrence and purpose, and be unconsumed."""
    consumed = []
    current = occurrence(inst, task_id)
    for fact_id in fact_ids:
        fact = inst["facts"].get(fact_id)
        if fact is None:
            raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "trigger fact is not recorded on this instance", factId=fact_id)
        if fact["node"] != node or fact["occurrence"] != current:
            raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "trigger fact belongs to another position occurrence",
                                    factId=fact_id, recorded=fact["occurrence"], current=current)
        if purpose is not None and fact["purpose"] != purpose:
            raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "trigger fact was produced for another purpose",
                                    factId=fact_id, recorded=fact["purpose"], requested=purpose)
        if fact["kind"] == POLICY_DECISION and (fact.get("producer") != POLICY_PRODUCER
                                                or (fact.get("payload") or {}).get("conclusion") != "ALLOW"):
            raise WorkflowRejection(TRIGGER_NOT_APPLICABLE,
                                    "only an ALLOW policy-decision produced by the Policy Gate can trigger a progression",
                                    factId=fact_id, producer=fact.get("producer"),
                                    conclusion=(fact.get("payload") or {}).get("conclusion"))
        if fact["consumedBy"] is not None:
            raise WorkflowRejection(TRIGGER_ALREADY_CONSUMED, "trigger fact was already consumed by a progression",
                                    factId=fact_id, consumedBy=fact["consumedBy"])
        consumed.append(fact_id)
    return consumed


def _write_commit(inst, command_id, kind, previous, nxt, edge_id, triggers, authority_ref, revision):
    """Steps 4 to 6 in one move: immutable record, trigger binding, snapshot and version update."""
    version = str(int(inst["runtimeVersion"]) + 1)
    record = dict(commandId=command_id, transitionKind=kind, expectedRuntimeVersion=inst["runtimeVersion"],
                  previousSnapshot=previous, nextSnapshot=nxt, selectedEdge=edge_id, triggers=list(triggers),
                  nextRuntimeVersion=version, at=now(), authorityRef=authority_ref, domainRevision=revision)
    inst["commits"].append(record)
    for fact_id in triggers:
        inst["facts"][fact_id]["consumedBy"] = command_id
    inst["lifecycle"] = nxt["lifecycle"]
    if nxt["position"] != inst["position"] or nxt["positionEntryRuntimeVersion"] != inst["positionEntryRevision"]:
        inst["position"] = nxt["position"]
        inst["positionEntryRevision"] = nxt["positionEntryRuntimeVersion"]
    inst["condition"] = nxt["condition"]
    inst["runtimeVersion"] = version
    return record


def _replay(inst, command_id, result):
    for record in inst["commits"]:
        if record["commandId"] == command_id:
            return dict(result=IDEMPOTENT_REPLAY, replayedAs=result, commit=copy.deepcopy(record),
                        runtimeVersion=inst["runtimeVersion"])
    return None


def record_fact(state, topology, task_id, fact, *, revision, producer=None):
    """Persist one participant-produced fact. It authorises nothing on its own.

    producer is supplied only by an internal producer; a policy-decision without the Policy Gate as its
    producer is refused, so the generic `fact` command cannot write one (feature-t6).
    """
    inst = instance(state, task_id)
    _check_active(inst)
    kind = fact.get("kind")
    if kind not in FACT_KINDS:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "unknown trigger fact kind: " + str(kind), kinds=list(FACT_KINDS))
    if kind == POLICY_DECISION and producer != POLICY_PRODUCER:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "policy-decision facts are produced only by the Policy Gate",
                                kind=kind, producer=producer)
    fact_id = fact.get("factId")
    if not isinstance(fact_id, str) or not fact_id:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "factId is required")
    purpose = fact.get("purpose")
    if not isinstance(purpose, str) or not purpose:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "purpose is required")
    _require_authority(fact.get("authorityRef"))
    existing = inst["facts"].get(fact_id)
    body = dict(factId=fact_id, kind=kind, purpose=purpose, node=inst["position"],
                occurrence=occurrence(inst, task_id), authorityRef=fact["authorityRef"],
                payload=copy.deepcopy(fact.get("payload")), recordedAt=now(), domainRevision=revision,
                consumedBy=None)
    if kind == POLICY_DECISION:
        body["producer"] = producer
    if existing is not None:
        comparable = {k: v for k, v in body.items() if k not in ("recordedAt", "domainRevision", "consumedBy")}
        recorded = {k: v for k, v in existing.items() if k not in ("recordedAt", "domainRevision", "consumedBy")}
        if comparable != recorded:
            raise WorkflowRejection(REQUEST_CONFLICT, "factId already bound to a different fact", factId=fact_id)
        return dict(result=IDEMPOTENT_REPLAY, fact=copy.deepcopy(existing))
    inst["facts"][fact_id] = body
    return dict(result="RECORDED", fact=copy.deepcopy(body))


def advance(state, topology, task_id, command, *, revision):
    """POSITION_ADVANCE across exactly one registered edge leaving the current node."""
    inst = instance(state, task_id)
    command_id = command["commandId"]
    replay = _replay(inst, command_id, ADVANCED)
    if replay:
        return replay
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    _check_version(inst, command.get("expectedRuntimeVersion"))
    if inst["condition"] == states.RECOVERY_REQUIRED:
        raise WorkflowRejection(RECOVERY_REQUIRED_BLOCKS_PROGRESSION,
                                "the current node has no consumable formal result; recovery must resolve it first",
                                node=inst["position"])
    edge_id = command.get("edgeId")
    edge = topology.edge(edge_id) if edge_id else None
    if edge is None or edge["source"] != inst["position"]:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "selected edge does not leave the current position",
                                edgeId=edge_id, position=inst["position"],
                                legal=[e["id"] for e in topology.outgoing(inst["position"])])
    if inst["condition"] != states.RESULT_RECORDED:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "a position advance needs a consumable formal result first",
                                condition=inst["condition"], node=inst["position"])
    if inst["reservations"]:
        held = sorted(r for r, v in inst["reservations"].items() if v["status"] == "held")
        if held:
            raise WorkflowRejection(RESERVATION_HELD, "reservations are still held at this position", reservations=held)
    target = edge["target"]
    semantic = topology.semantic_type(target)
    if semantic == states.TERMINAL_DECISION:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "a Close Task node is reached only by closing the task",
                                edgeId=edge_id, target=target)
    condition = states.entry_condition(target, semantic)
    nxt = dict(lifecycle=states.ACTIVE, position=target, condition=condition, positionEntryRuntimeVersion=revision)
    if not states.legal(states.ACTIVE, target, semantic, condition):
        raise WorkflowRejection(ILLEGAL_STATE_COMBINATION, "the next snapshot is outside the legal matrix", next=nxt)
    triggers = _consume(inst, task_id, command.get("triggers", []), inst["position"], command.get("purpose"))
    previous = snapshot(inst)
    record = _write_commit(inst, command_id, states.POSITION_ADVANCE, previous, nxt, edge_id, triggers,
                           command["authorityRef"], revision)
    inst["attempt"] = None
    return dict(result=ADVANCED, commit=copy.deepcopy(record), runtimeVersion=inst["runtimeVersion"])


def update_condition(state, topology, task_id, command, *, revision):
    """CONDITION_UPDATE inside one occurrence, along the standard path of the node semantic type."""
    inst = instance(state, task_id)
    command_id = command["commandId"]
    replay = _replay(inst, command_id, CONDITION_UPDATED)
    if replay:
        return replay
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    _check_version(inst, command.get("expectedRuntimeVersion"))
    node, requested = inst["position"], command.get("condition")
    semantic = topology.semantic_type(node)
    if requested == states.RECOVERY_REQUIRED:
        allowed = inst["condition"] != states.RECOVERY_REQUIRED
    else:
        allowed = states.next_condition(node, semantic, inst["condition"]) == requested
    if not allowed:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "condition update is not the next step on the standard path",
                                current=inst["condition"], requested=requested,
                                path=list(states.standard_path(node, semantic)))
    if not states.legal(states.ACTIVE, node, semantic, requested):
        raise WorkflowRejection(ILLEGAL_STATE_COMBINATION, "the requested condition is outside the legal matrix",
                                node=node, semanticType=semantic, condition=requested)
    triggers = _consume(inst, task_id, command.get("triggers", []), node, command.get("purpose"))
    previous = snapshot(inst)
    nxt = dict(previous, condition=requested)
    record = _write_commit(inst, command_id, states.CONDITION_UPDATE, previous, nxt, None, triggers,
                           command["authorityRef"], revision)
    return dict(result=CONDITION_UPDATED, commit=copy.deepcopy(record), runtimeVersion=inst["runtimeVersion"])


def recovery_condition_update(state, topology, task_id, command, *, revision):
    """CONDITION_UPDATE out of RECOVERY_REQUIRED, used only by the recovery contract.

    The standard condition path does not leave RECOVERY_REQUIRED, so recovery has its own writer; it
    still goes through the same Progression Commit and the same legal matrix, stays inside the same
    Current Position occurrence and never selects a topology edge (D-05 §6, §7).
    """
    inst = instance(state, task_id)
    command_id = command["commandId"]
    replay = _replay(inst, command_id, CONDITION_UPDATED)
    if replay:
        return replay
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    _check_version(inst, command.get("expectedRuntimeVersion"))
    if inst["condition"] != states.RECOVERY_REQUIRED:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "recovery updates apply only to a node in RECOVERY_REQUIRED",
                                condition=inst["condition"])
    node, requested = inst["position"], command["condition"]
    semantic = topology.semantic_type(node)
    if not states.legal(states.ACTIVE, node, semantic, requested):
        raise WorkflowRejection(ILLEGAL_STATE_COMBINATION, "the requested condition is outside the legal matrix",
                                node=node, semanticType=semantic, condition=requested)
    previous = snapshot(inst)
    nxt = dict(previous, condition=requested)
    record = _write_commit(inst, command_id, states.CONDITION_UPDATE, previous, nxt, None, [],
                           command["authorityRef"], revision)
    return dict(result=CONDITION_UPDATED, commit=copy.deepcopy(record), runtimeVersion=inst["runtimeVersion"])


def decisions(inst, topology):
    """Legal Human decisions at the current position; [] anywhere that is not a Human Gate."""
    from domain.workflow.topology import decision_set
    if terminal(inst):
        return []
    return decision_set(topology, inst["position"])


def decide(state, topology, task_id, command, *, revision):
    """Record a Human decision at a Human Gate and advance along the edge that decision selects."""
    inst = instance(state, task_id)
    _check_active(inst)
    legal = {d["decision"]: d for d in decisions(inst, topology)}
    requested = command.get("decision")
    if requested not in legal:
        raise WorkflowRejection(DECISION_NOT_LEGAL_HERE, "this decision is not in the legal set at the current position",
                                decision=requested, position=inst["position"], legal=sorted(legal))
    chosen = legal[requested]
    if requested == CLOSE_TASK_DECISION:
        return close_task(state, topology, task_id, dict(command, edgeId=chosen["edgeId"],
                                                         reasonCategory=command.get("reasonCategory", "blocked-escalation")),
                          revision=revision)
    fact_id = command["commandId"] + ":decision"
    if inst["condition"] == states.AWAITING_HUMAN_ACTION:
        update_condition(state, topology, task_id,
                         dict(commandId=command["commandId"] + ":record", condition=states.RESULT_RECORDED,
                              authorityRef=command["authorityRef"],
                              expectedRuntimeVersion=command.get("expectedRuntimeVersion")), revision=revision)
    record_fact(state, topology, task_id,
                dict(factId=fact_id, kind="human-decision", purpose="gate-decision", authorityRef=command["authorityRef"],
                     payload=dict(decision=requested, edgeId=chosen["edgeId"],
                                  reservation=copy.deepcopy(command.get("reservation")))), revision=revision)
    return advance(state, topology, task_id,
                   dict(commandId=command["commandId"], edgeId=chosen["edgeId"], triggers=[fact_id],
                        purpose="gate-decision", authorityRef=command["authorityRef"],
                        expectedRuntimeVersion=inst["runtimeVersion"]), revision=revision)


def close_task(state, topology, task_id, command, *, revision):
    """FR-27: Human may close any non-terminal task at any time, in one atomic commit.

    Through an escalation gate the commit selects that gate's Close Task edge and lands on the
    registered Close node (D-04 §9: no intermediate ACTIVE + Close Task state). Exercised anywhere
    else it is the task-lifecycle power action: the position does not move and no Node, Edge or Gate
    is added (spec §8 OD-69 extends the matrix with "any non-terminal -> Closed"). The direction is
    one-way; closing never records a business result, accepts a candidate or authorises a publish.
    """
    inst = instance(state, task_id)
    command_id = command["commandId"]
    replay = _replay(inst, command_id, FINALIZED)
    if replay:
        return replay
    if inst["lifecycle"] == states.COMPLETED:
        raise WorkflowRejection(PUBLISHED_NOT_CLOSEABLE, "a Published task cannot be closed", lifecycle=inst["lifecycle"])
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    _check_version(inst, command.get("expectedRuntimeVersion"))
    reason = command.get("reasonCategory", "human-initiated")
    if reason not in CLOSURE_REASONS:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "closure reason category must be machine-distinguishable",
                                reasonCategory=reason, categories=list(CLOSURE_REASONS))
    edge_id = command.get("edgeId")
    if edge_id:
        edge = topology.edge(edge_id)
        if edge["source"] != inst["position"] or topology.semantic_type(edge["target"]) != states.TERMINAL_DECISION:
            raise WorkflowRejection(ILLEGAL_TRANSITION, "the selected edge is not a Close Task edge of this gate",
                                    edgeId=edge_id, position=inst["position"])
        position, closure_kind = edge["target"], "topology-edge"
    else:
        position, closure_kind = inst["position"], "power-action"
    semantic = topology.semantic_type(position)
    if not states.legal(states.CLOSED, position, semantic, states.RESULT_RECORDED, closure=closure_kind):
        raise WorkflowRejection(ILLEGAL_STATE_COMBINATION, "the closed snapshot is outside the legal matrix",
                                position=position, semanticType=semantic)
    triggers = _consume(inst, task_id, command.get("triggers", []), inst["position"], command.get("purpose"))
    previous = snapshot(inst)
    entry = revision if position != inst["position"] else inst["positionEntryRevision"]
    nxt = dict(lifecycle=states.CLOSED, position=position, condition=states.RESULT_RECORDED,
               positionEntryRuntimeVersion=entry)
    record = _write_commit(inst, command_id, states.LIFECYCLE_FINALIZATION, previous, nxt, edge_id, triggers,
                           command["authorityRef"], revision)
    inst["closure"] = dict(reasonCategory=reason, kind=closure_kind, at=now(), authorityRef=command["authorityRef"],
                           commandId=command_id, closedFrom=previous)
    # The terminal slot feature-t0 reads for dependency satisfaction and in-flight counting is
    # written here; nothing else in the product writes it.
    state["tasks"][task_id]["terminal"] = dict(kind="closed", at=now(), commandId=command_id,
                                               reasonCategory=reason, authorityRef=command["authorityRef"])
    for attempt in inst["attempts"]:
        if attempt["status"] in (states.CREATED, states.RUNNING):
            # In-flight work stops being dispatched and is recorded as terminated, never as a
            # completed or failed result (FR-27 item 2).
            attempt.update(status="TERMINATED_BY_CLOSE", settledAt=now(), settledBy=command_id)
    inst["attempt"] = None
    for reservation in inst["reservations"].values():
        if reservation["status"] == "held":
            reservation["note"] = "task closed; the reservation stays held until the same execution fact is settled"
    return dict(result=FINALIZED, commit=copy.deepcopy(record), closure=copy.deepcopy(inst["closure"]),
                runtimeVersion=inst["runtimeVersion"])


def finalize_publish(state, topology, task_id, command, *, revision):
    """LIFECYCLE_FINALIZATION at N-PUBLISH: ACTIVE + EXECUTING becomes COMPLETED + RESULT_RECORDED.

    Nothing here pushes a branch or creates a pull request. feature-t7 owns the external publication;
    this is the atomic domain finalisation that a confirmed publish result authorises, and a partial
    or unconfirmable external effect must instead leave the node in RECOVERY_REQUIRED (FR-29 / FR-30).
    """
    inst = instance(state, task_id)
    command_id = command["commandId"]
    replay = _replay(inst, command_id, FINALIZED)
    if replay:
        return replay
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    _check_version(inst, command.get("expectedRuntimeVersion"))
    if inst["position"] != states.PUBLISH_NODE or inst["condition"] != states.EXECUTING:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "publish finalisation runs only at the Publish node while executing",
                                position=inst["position"], condition=inst["condition"])
    triggers = _consume(inst, task_id, command.get("triggers", []), inst["position"], command.get("purpose"))
    if not triggers:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "a confirmed publish result must authorise the finalisation")
    previous = snapshot(inst)
    nxt = dict(previous, lifecycle=states.COMPLETED, condition=states.RESULT_RECORDED)
    if not states.legal(states.COMPLETED, inst["position"], topology.semantic_type(inst["position"]), states.RESULT_RECORDED):
        raise WorkflowRejection(ILLEGAL_STATE_COMBINATION, "the completed snapshot is outside the legal matrix", next=nxt)
    record = _write_commit(inst, command_id, states.LIFECYCLE_FINALIZATION, previous, nxt, None, triggers,
                           command["authorityRef"], revision)
    state["tasks"][task_id]["terminal"] = dict(kind="published", at=now(), commandId=command_id,
                                               authorityRef=command["authorityRef"])
    return dict(result=FINALIZED, commit=copy.deepcopy(record), runtimeVersion=inst["runtimeVersion"])


def open_attempt(state, topology, task_id, command, *, revision):
    """Start one concrete external call at the current node. Node and Attempt stay distinct objects."""
    inst = instance(state, task_id)
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    attempt_id = command["attemptId"]
    for attempt in inst["attempts"]:
        if attempt["attemptId"] == attempt_id:
            return dict(result=IDEMPOTENT_REPLAY, attempt=copy.deepcopy(attempt))
    record = dict(attemptId=attempt_id, node=inst["position"], occurrence=occurrence(inst, task_id),
                  purpose=command.get("purpose", "node-work"), status=states.CREATED, createdAt=now(),
                  authorityRef=command["authorityRef"], settledAt=None, settledBy=None, evidence=None,
                  domainRevision=revision)
    inst["attempts"].append(record)
    inst["attempt"] = copy.deepcopy(record)
    return dict(result="ATTEMPT_CREATED", attempt=copy.deepcopy(record))


def start_attempt(state, topology, task_id, command, *, revision):
    """CREATED -> RUNNING for one named attempt of the current occurrence (feature-t3, purpose-agnostic).

    The execution layer calls this in its own transaction before any physical effect is released.
    It records when the work started, the execution reference and the authorising fact; it has no
    purpose-specific branch, so every executor (review, implementer, ruling write) uses the same rule.
    Replaying the same start is idempotent; a different start for the same attempt is a conflict.
    """
    inst = instance(state, task_id)
    _check_active(inst)
    _require_authority(command.get("authorityRef"))
    attempt_id = command.get("attemptId")
    for attempt in inst["attempts"]:
        if attempt["attemptId"] != attempt_id:
            continue
        started = dict(executionRef=command.get("executionRef"), startedBy=command.get("commandId"))
        if attempt["status"] == states.RUNNING:
            recorded = dict(executionRef=attempt.get("executionRef"), startedBy=attempt.get("startedBy"))
            if recorded != started:
                raise WorkflowRejection(REQUEST_CONFLICT, "attempt already started under another start",
                                        attemptId=attempt_id, recorded=recorded)
            return dict(result=IDEMPOTENT_REPLAY, attempt=copy.deepcopy(attempt))
        if attempt["status"] != states.CREATED:
            raise WorkflowRejection(ILLEGAL_TRANSITION, "only a CREATED attempt can start running",
                                    attemptId=attempt_id, status=attempt["status"])
        if attempt["occurrence"] != occurrence(inst, task_id):
            raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "the attempt belongs to another position occurrence",
                                    attemptId=attempt_id)
        attempt.update(status=states.RUNNING, startedAt=now(), authorityRef=attempt["authorityRef"],
                       startAuthorityRef=command["authorityRef"], domainRevisionStarted=revision, **started)
        inst["attempt"] = copy.deepcopy(attempt)
        return dict(result="ATTEMPT_RUNNING", attempt=copy.deepcopy(attempt))
    raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "no such attempt on this instance", attemptId=attempt_id)


def settle_attempt(state, topology, task_id, command, *, revision):
    """Settle an attempt. COMPLETED does not mean a business PASS; the two failure kinds stay apart."""
    inst = instance(state, task_id)
    _check_active(inst)
    status = command.get("status")
    if status not in states.ATTEMPT_TERMINAL:
        raise WorkflowRejection(ILLEGAL_TRANSITION, "attempt settlement must use a terminal attempt state",
                                status=status, states=list(states.ATTEMPT_TERMINAL))
    for attempt in inst["attempts"]:
        if attempt["attemptId"] == command["attemptId"]:
            if attempt["status"] in states.ATTEMPT_TERMINAL:
                if attempt["status"] != status:
                    raise WorkflowRejection(REQUEST_CONFLICT, "attempt already settled with another state",
                                            attemptId=attempt["attemptId"], recorded=attempt["status"])
                return dict(result=IDEMPOTENT_REPLAY, attempt=copy.deepcopy(attempt))
            attempt.update(status=status, settledAt=now(), evidence=copy.deepcopy(command.get("evidence")),
                           settledBy=command.get("commandId"))
            inst["attempt"] = copy.deepcopy(attempt)
            return dict(result="ATTEMPT_SETTLED", attempt=copy.deepcopy(attempt),
                        entersRecovery=status in states.ATTEMPT_RECOVERY)
    raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "no such attempt on this instance", attemptId=command.get("attemptId"))
