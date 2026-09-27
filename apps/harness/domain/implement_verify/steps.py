"""Thin wrappers over feature-t2's progression functions; every step is still one Progression Commit.

This package never writes position, condition or lifecycle itself. It records participant facts and
asks feature-t2's advance / update_condition / attempt / reservation functions to commit, so the same
six-step unit, the legal matrix and trigger consumption apply (D-04 §7, §8).
"""
from domain.workflow import progression, reservations, states


def ledger(state, task_id):
    """The feature-t4 business record of a task: execution descriptors, verifications and assessments."""
    task = state["tasks"][task_id]
    return task.setdefault("implementVerify", dict(executions={}, verifications={}, assessments={}))


def inst(state, task_id):
    return progression.instance(state, task_id)


def condition(state, topology, task_id, command_id, value, authority, *, revision, triggers=(), purpose=None):
    return progression.update_condition(state, topology, task_id,
                                        dict(commandId=command_id, condition=value, authorityRef=authority,
                                             triggers=list(triggers), purpose=purpose), revision=revision)


def walk_to(state, topology, task_id, target, command_id, authority, *, revision):
    """Condition updates along the node's standard path until `target` (inclusive), one commit each."""
    node = inst(state, task_id)["position"]
    semantic = topology.semantic_type(node)
    step = 0
    while inst(state, task_id)["condition"] != target:
        nxt = states.next_condition(node, semantic, inst(state, task_id)["condition"])
        if nxt is None:
            break
        condition(state, topology, task_id, "%s:c%d" % (command_id, step), nxt, authority, revision=revision)
        step += 1
    return inst(state, task_id)["condition"]


def fact(state, topology, task_id, fact_id, kind, purpose, authority, payload, *, revision):
    return progression.record_fact(state, topology, task_id,
                                   dict(factId=fact_id, kind=kind, purpose=purpose, authorityRef=authority,
                                        payload=payload), revision=revision)


def advance(state, topology, task_id, command_id, edge, authority, *, revision, triggers=(), purpose=None):
    return progression.advance(state, topology, task_id,
                               dict(commandId=command_id, edgeId=edge, authorityRef=authority,
                                    triggers=list(triggers), purpose=purpose), revision=revision)


def open_attempt(state, topology, task_id, attempt_id, purpose, authority, *, revision):
    return progression.open_attempt(state, topology, task_id,
                                    dict(attemptId=attempt_id, purpose=purpose, authorityRef=authority),
                                    revision=revision)


def settle_attempt(state, topology, task_id, attempt_id, status, command_id, evidence, *, revision):
    return progression.settle_attempt(state, topology, task_id,
                                      dict(attemptId=attempt_id, status=status, commandId=command_id,
                                           evidence=evidence), revision=revision)


def reserve(state, topology, task_id, reservation_id, purpose, authority, protects, *, revision, execution_ref=None):
    return reservations.reserve(state, topology, task_id,
                                dict(reservationId=reservation_id, purpose=purpose, authorityRef=authority,
                                     protects=list(protects), executionRef=execution_ref), revision=revision)


def settle_reservation(state, topology, task_id, reservation_id, settlement, *, revision):
    return reservations.settle(state, topology, task_id,
                               dict(reservationId=reservation_id, settlement=settlement), revision=revision)
