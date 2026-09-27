"""The only call points from feature-t4 into feature-t3 and feature-t6 (seam ruling S-02, S-03, S-11, S-13).

Both tasks are merged (main 631bd3ea). Every function here reaches an interface another task owns:

- feature-t3: `progression.start_attempt(state, topology, task_id, command, *, revision)` moves a named
  CREATED attempt of the current occurrence to RUNNING; `domain.definition.commands.frozen_definition(
  state, task_id)` returns the frozen Definition identity {candidateId, path, bytes, sha256, commit,
  rulings: [{number, type, path, sha256, commit}], ...} or None. Its execution layer and production port
  factory (`runtime/executions.py`) run this task's executor and build its ports.
- feature-t6: `domain.policy.authorize.execution_authorizer(domain, task_id, subject, entry, generation,
  *, context=None, authority_ref=...)` returns the async `authorize(intent)` callback (reached through
  feature-t3's `build_port`); the author vendor mapping is feature-t6's product-side configuration
  `configuration.authorVendors[agent][model]`, written by `config set author-vendor` and read here only.
"""
import copy

from domain.definition import commands as definition_commands
from domain.workflow import progression

# feature-t6 evaluation subject and per-request call limit for the implementer purpose.
IMPLEMENT_RELEASE = "implement-release"
MAX_CALLS = 1


def start_attempt(state, topology, task_id, command, *, revision):
    return progression.start_attempt(state, topology, task_id, command, revision=revision)


def vendor_of(state, agent, model):
    """Model vendor from feature-t6's product-side mapping keyed by (agent, model); None means no entry."""
    table = state.get("configuration", {}).get("authorVendors") or {}
    return (table.get(agent) or {}).get(model)


def finalization(state, task_id):
    """The written finalization of the task's Definition, normalised from feature-t3's frozen record.

    Returns dict(ruling={ruling: "RU-NN", number, type, path, sha256, commit},
    candidate={candidateId, commit, path, bytes, sha256}) or None when the Definition is not frozen by
    exactly one written finalization ruling.
    """
    if state.get("tasks", {}).get(task_id) is None:
        return None
    frozen = definition_commands.frozen_definition(state, task_id)
    if not frozen:
        return None
    rulings = [r for r in frozen.get("rulings") or [] if r.get("type") == "finalization"]
    if len(rulings) != 1 or not rulings[0].get("commit"):
        return None
    ruling = rulings[0]
    return dict(ruling=dict(ruling="RU-%02d" % ruling["number"], number=ruling["number"], type=ruling["type"],
                            path=ruling["path"], sha256=ruling["sha256"], commit=ruling["commit"]),
                candidate={k: copy.deepcopy(frozen[k]) for k in ("candidateId", "commit", "path", "bytes", "sha256")})


def policy_context(final):
    """feature-t6 implement-release request keys besides the intent, from the normalised finalization."""
    candidate, ruling = final["candidate"], final["ruling"]
    return dict(definition=dict(path=candidate["path"], commit=candidate["commit"], bytes=candidate["bytes"],
                                sha256=candidate["sha256"]),
                finalization=dict(path=ruling["path"], commit=ruling["commit"]), maxCalls=MAX_CALLS)
