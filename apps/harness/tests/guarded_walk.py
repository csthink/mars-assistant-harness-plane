"""SYNTHETIC, test only: walk a node feature-t5 narrows without a feature-t5 entry.

feature-t5 refuses feature-t2's generic fact / condition / advance commands at the three budget nodes and the
Validate Change nodes for every task. Tests of feature-t2 and feature-t6 that only need to pass through those
nodes (to check occurrences, decision sets or Policy chains, not budgets) use these helpers, which apply the
feature-t2 progression functions directly inside one Domain Core transaction, exactly as the generic command
would have done before the narrowing. Product code never registers or calls this module.
"""
from domain.workflow import progression, states

LABEL = "SYNTHETIC guarded walk (test only)"


def _transact(domain, generation, task_id, function):
    def callback(state):
        inst = progression.instance(state, task_id)
        return function(state, domain.topology(inst))
    return domain.transaction(generation, callback)


def condition(domain, generation, task_id, command_id, value, authority):
    return _transact(domain, generation, task_id, lambda s, t: progression.update_condition(
        s, t, task_id, dict(commandId=command_id, condition=value, authorityRef=authority), revision=s["revision"]))


def advance(domain, generation, task_id, command_id, edge, authority, triggers=(), purpose=None):
    return _transact(domain, generation, task_id, lambda s, t: progression.advance(
        s, t, task_id, dict(commandId=command_id, edgeId=edge, authorityRef=authority, triggers=list(triggers),
                            purpose=purpose), revision=s["revision"]))


def settle_and_advance(domain, generation, task_id, command_id, edge, authority):
    """Walk the current node along its standard path to RESULT_RECORDED, then cross `edge`."""
    def run(state, topology):
        inst = progression.instance(state, task_id)
        node = inst["position"]
        step = 0
        while inst["condition"] != states.RESULT_RECORDED:
            nxt = states.next_condition(node, topology.semantic_type(node), inst["condition"])
            if nxt is None:
                break
            progression.update_condition(state, topology, task_id, dict(commandId="%s:c%d" % (command_id, step),
                                                                        condition=nxt, authorityRef=authority),
                                         revision=state["revision"])
            step += 1
        return progression.advance(state, topology, task_id, dict(commandId=command_id, edgeId=edge, authorityRef=authority),
                                   revision=state["revision"])
    return _transact(domain, generation, task_id, run)
