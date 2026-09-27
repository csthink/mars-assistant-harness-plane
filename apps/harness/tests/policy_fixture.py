"""Fixture for the feature-t6 Policy Gate tests. Everything here is synthetic and marked as such.

- Product-line repositories are the synthetic ones from product_line.py (.synthetic-hp-domain marker).
- The Registry used by most cases is the LIVE Registry loaded read-only by the production loader, then
  deep-copied and marked `synthetic: True` before a case changes a capability state or adds a
  standalone port. The live Registry file is never written.
- feature-t3's fixed author identity (taskDefinition.candidates), its Owner formal authorization fact,
  feature-t17 execution records, feature-t4's Implementer registration and feature-t7's publishBinding
  are written here in the shapes fixed by the feature-t6 design, each marked synthetic, because their
  producers are other tasks that have not merged yet.
"""
import copy
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance.accept import accept_task, set_configuration
from domain.core import HarnessDomain
from domain.policy import inputs as policy_inputs
from domain.policy import rules
from domain.workflow import states
from product_line import create_product_line, git, write

OWNER = "owner:synthetic"
TASK = "feature-t0"
DEFINITION_PATH = "tasks/feature-t0/feature-t0.md"
FINALIZATION_PATH = "tasks/feature-t0/rulings/RU-02-definition-finalization.md"
CLAUDE = ("agent:claude-code", "claude-opus-5[1m]")
CODEX = ("agent:codex", "gpt-6-sol")
_LIVE = None


def live_registry():
    global _LIVE
    if _LIVE is None:
        _LIVE = policy_inputs.load_live_registry()
    return copy.deepcopy(_LIVE)


def synthetic_registry(status=None, standalone=False, port_changes=None):
    loaded = live_registry()
    loaded["synthetic"] = True
    ports = loaded["registry"]["execution_ports"]
    embedded = next(p for p in ports if p["id"] == "embedded")
    if status is not None:
        embedded["capability"]["status"] = status
    if port_changes:
        embedded.update(copy.deepcopy(port_changes))
    if standalone:
        other = copy.deepcopy(embedded)
        other.update(id="standalone", mode="standalone")
        other["applicability"]["executionPort"] = "standalone"
        ports.append(other)
    loaded["sha256"] = hashlib.sha256(rules.canonical(loaded["registry"])).hexdigest()
    return loaded


def implementer_registration(port_id="implementer", mode="embedded", digest="2" * 64):
    """Synthetic stand-in for feature-t4's product-side Implementer registration."""
    profile = dict(id="coding-implementer/claude-print-restricted", version="1", digest=digest, trustModel="current-user",
                   purpose="coding-implementer", operations=["implement"], maxToolCalls=20, maxRunSeconds=600,
                   limitations=["no-shell", "no-network-tools", "no-mcp", "no-prompts", "cwd-confined"],
                   programIdentity=dict(launcher="/synthetic/claude", binaryDigest="a" * 64, version="synthetic-1"))
    return dict(id=port_id, mode=mode, profile=profile, synthetic=True)


class World:
    """One synthetic product line with an accepted task and a Domain Core using injectable sources."""

    def __init__(self, directory, *, entry="cli"):
        self.directory = Path(directory)
        self.repo, self.head = create_product_line(self.directory / "repo")
        self.domain = HarnessDomain(self.repo, entry=entry)
        self.generation = self.domain.bind_entry()
        outcome = accept_task(self.domain.store, dict(requestId="req-1", repository=str(self.repo), taskType="feature",
                                                      taskId=TASK, baseRef="main",
                                                      worktreeRoot=str(self.directory / "worktrees"), authorityRef=OWNER))
        assert outcome["result"] == "ACCEPTED", outcome
        self.registry = synthetic_registry()
        self.rounds = dict(submitted=0, allowed=2, exhausted=False, source="synthetic")
        self.registration = None
        self.use_synthetic_sources()

    # -- sources -----------------------------------------------------------------------------------
    def use_synthetic_sources(self):
        def registry_loader():
            if isinstance(self.registry, Exception):
                raise self.registry
            return copy.deepcopy(self.registry)

        def round_reader(task_id, stage, review, defaults):
            if isinstance(self.rounds, Exception):
                raise self.rounds
            return dict(self.rounds)

        def registrations(state, port_id):
            return self.registration if self.registration and self.registration["id"] == port_id else None
        self.domain.policy_sources = dict(registry_loader=registry_loader, round_reader=round_reader,
                                          implementer_registrations=registrations)

    def use_production_sources(self):
        """Production readers. feature-t3 integration: the production Registry reader reads the bound product line's
        review-channel Registry, so the synthetic line carries a copy of the hp live Registry (provider capabilities
        CONFIGURED, since their Receipt evidence lives only in hp) unless the test installed its own."""
        bound = policy_inputs.bound_registry_path(self.repo)
        if not bound.exists():
            import json as _json
            live = _json.loads(policy_inputs.REGISTRY_FILE.read_text())
            for provider in live["providers"].values():
                for model in provider["models"].values():
                    model["capability"] = dict(status="CONFIGURED", note="synthetic copy; evidence stays in hp")
            write(self.repo, str(bound.relative_to(self.repo)), _json.dumps(live, ensure_ascii=False, indent=2) + "\n")
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-q", "-m", "synthetic bound registry")
        self.domain.policy_sources = {}

    # -- state helpers -----------------------------------------------------------------------------
    def state(self):
        return self.domain.store.read()

    def inst(self):
        return self.state()["tasks"][TASK]["workflowInstance"]

    def mutate(self, change):
        return self.domain.transaction(self.generation, change)

    def run(self, name, **payload):
        payload.setdefault("taskId", TASK)
        payload.setdefault("authorityRef", OWNER)
        return self.domain.run(name, payload, generation=self.generation)

    def map_author(self, agent, model, vendor):
        return set_configuration(self.domain.store, "author-vendor", dict(agent=agent, model=model, vendor=vendor), OWNER)

    # -- repository content ------------------------------------------------------------------------
    def commit_definition(self, text="# feature-t0 · synthetic Definition\n\nSynthetic body.\n"):
        write(self.repo, DEFINITION_PATH, text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "synthetic definition")
        raw = text.encode()
        return dict(kind="definition", path=DEFINITION_PATH, commit=git(self.repo, "rev-parse", "HEAD"), bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest())

    def commit_finalization(self, obj, pin=None):
        pin = pin or "%s · %d bytes · SHA-256 %s" % (obj["path"], obj["bytes"], obj["sha256"])
        text = ("> Ruling: RU-02\n> Date: 2026-09-23\n> Type: finalization\n> Object: %s\n> Basis: synthetic\n"
                "> Decision: synthetic finalization\n\n# synthetic\n" % pin)
        write(self.repo, FINALIZATION_PATH, text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "synthetic finalization")
        return dict(path=FINALIZATION_PATH, commit=git(self.repo, "rev-parse", "HEAD"))

    # -- synthetic facts of other tasks ------------------------------------------------------------
    def candidate(self, obj, identity):
        """feature-t3's fixed author identity (taskDefinition.candidates), synthetic."""
        def change(s):
            rows = s["tasks"][TASK].setdefault("taskDefinition", {}).setdefault("candidates", [])
            rows.append(dict(candidateId="cand-%d" % (len(rows) + 1), path=obj["path"], bytes=obj["bytes"],
                             sha256=obj["sha256"], authorIdentity=copy.deepcopy(identity), synthetic=True))
        self.mutate(change)

    def execution(self, ref, agent, model, completed=True, observed=None):
        """A feature-t17 execution record (executionReservations), synthetic."""
        def change(s):
            s.setdefault("executionReservations", {})[ref] = dict(
                request_id=ref, synthetic=True, phase="completed" if completed else "observing",
                intent=dict(executionBinding=dict(agent=agent, model=model),
                            profile=dict(programIdentity=dict(launcher="/synthetic/agent", binaryDigest="d" * 64,
                                                              version="synthetic"))),
                observations=[dict(physical_execution=dict(actualBinding=dict(
                    model=model, observedModels=list(observed or [model]), source="protocol-result")))],
                result="c3ludGhldGlj" if completed else None)
        self.mutate(change)

    def formal(self, obj, fact_id="formal-1", port="embedded", digest=None, **extra):
        """feature-t3's Owner formal authorization fact, written through the generic fact entry (synthetic)."""
        port_entry = next(p for p in self.registry["registry"]["execution_ports"] if p["id"] == port)
        body = dict(taskId=TASK, object={k: obj[k] for k in ("path", "bytes", "sha256", "commit") if k in obj}, portId=port,
                    profileDigest=digest or port_entry["profile"]["digest"], decisionRef="decision:synthetic",
                    synthetic=True, **extra)
        return self.run("fact", fact=dict(factId=fact_id, kind="human-decision", purpose=rules.FORMAL_PURPOSE,
                                          authorityRef=OWNER, payload=body))

    # -- requests ----------------------------------------------------------------------------------
    def review_intent(self, port="embedded", request_id="review-request:1", **changes):
        entry = next(p for p in self.registry["registry"]["execution_ports"] if p["id"] == port)
        profile = copy.deepcopy(entry["profile"])
        binding = dict(profileDigest=profile["digest"], agent="agent:codex", model=entry["model_ref"],
                       modelVendor="OpenAI", routeVendor=None, credentialRef="credential:codex",
                       configurationRevision=entry["applicability"]["configurationRevision"])
        intent = dict(portId=port, executionRequestId=request_id, resourceHandle="resource:one", scopeRef="scope:one",
                      domainOperationId="domain:one", domainNodeRef="node:one", controlGeneration=self.generation,
                      executionBinding=binding, profile=profile, connectionRef="connection:one",
                      credentialRevision=entry["applicability"]["credentialRevision"], transport=entry["transport"],
                      effort=entry["effort"], constraints=[], grantRefs=[dict(id="grant:one", revision="1")],
                      decisionRef="decision:one",
                      budget=dict(maxToolCalls=20, maxRunSeconds=600, maxOutputBytes=1048576, cleanupSeconds=30),
                      caller="hp-review", invocation_authorization="decision:one / synthetic scope",
                      formal_review_authorized_by_owner=True)
        intent.update(changes)
        return intent

    def review_request(self, obj, intent=None, entry="embedded", refs=(), **extra):
        intent = intent or self.review_intent()
        request = dict(schema=rules.REQUEST_SCHEMA, subject=rules.REVIEW_RELEASE, taskId=TASK, entry=entry,
                       portId=intent["portId"], intent=intent, object=obj, authorExecutionRefs=list(refs),
                       review=dict(stage="task", maxRounds=None, roundExtensions=[]), maxCalls=1)
        request.update(extra)
        return request

    def implement_intent(self, port="implementer", digest="2" * 64, **changes):
        profile = copy.deepcopy(implementer_registration(port, digest=digest)["profile"])
        intent = dict(portId=port, executionRequestId="implement-request:1", scopeRef="scope:one",
                      profile=profile, executionBinding=dict(profileDigest=profile["digest"], agent=CLAUDE[0],
                                                             model=CLAUDE[1], modelVendor="Anthropic"),
                      caller="hp-implement", invocation_authorization="decision:implement",
                      budget=dict(maxToolCalls=20, maxRunSeconds=600, maxOutputBytes=1048576, cleanupSeconds=30))
        intent.update(changes)
        return intent

    def implement_request(self, definition, finalization, intent=None, entry="embedded"):
        intent = intent or self.implement_intent()
        return dict(schema=rules.REQUEST_SCHEMA, subject=rules.IMPLEMENT_RELEASE, taskId=TASK, entry=entry,
                    portId=intent["portId"], intent=intent,
                    definition={k: definition[k] for k in ("path", "commit", "bytes", "sha256")},
                    finalization=finalization, maxCalls=1)

    def push_request(self, **changes):
        task = self.state()["tasks"][TASK]
        push = dict(candidateCommit=self.head_commit(), sourceBranch=task["branch"], remote="origin",
                    targetBranch="main", repositoryIdentity=task["repositoryIdentity"])
        push.update(changes)
        return dict(schema=rules.REQUEST_SCHEMA, subject=rules.PUSH_PERMIT, taskId=TASK, push=push)

    def head_commit(self):
        return git(self.repo, "rev-parse", "HEAD")

    def evaluate(self, request, **payload):
        return self.run("policy-evaluate", request=request, **payload)

    # -- Workflow driving (same commands both entries use) ------------------------------------------
    def narrowed(self):
        """feature-t5 narrows the generic commands at the budget and Validate Change nodes for every task; feature-t7 at the
        Publish Authorization Gate and the Publish node."""
        from domain.budget import commands as budget_commands
        from domain.publish import commands as publish_commands
        from domain.validation import commands as validation_commands
        position = self.inst()["position"]
        return position in budget_commands.GUARDED_NODES or position in validation_commands.GUARDED_NODES \
            or position in publish_commands.GUARDED_NODES

    def settle(self, tag):
        """Move the current node along its standard condition path up to RESULT_RECORDED."""
        if self.narrowed():
            return  # advance() walks a narrowed node through the SYNTHETIC direct helper instead
        n = 0
        while True:
            inst = self.inst()
            node, condition = inst["position"], inst["condition"]
            if condition == states.RESULT_RECORDED:
                return
            semantic = self.domain.topology(inst).semantic_type(node)
            nxt = states.next_condition(node, semantic, condition)
            if nxt is None:
                return
            n += 1
            self.run("condition", commandId="%s-c%d" % (tag, n), condition=nxt)

    def advance(self, edge, tag, **extra):
        if self.narrowed() and not extra:
            import guarded_walk  # SYNTHETIC, test only: the same progression functions applied directly
            return guarded_walk.settle_and_advance(self.domain, self.generation, TASK, "%s-%s" % (tag, edge), edge, OWNER)
        self.settle(tag)
        return self.run("advance", commandId="%s-%s" % (tag, edge), edgeId=edge, **extra)

    def await_human(self, tag):
        inst = self.inst()
        if inst["condition"] == states.ENTERED:
            self.run("condition", commandId=tag + "-await", condition=states.AWAITING_HUMAN_ACTION)

    def decide(self, decision, tag):
        from domain.definition import gate as definition_gate
        from domain.publish import gate as publish_gate
        from domain.workflow import progression as workflow_progression
        publish = publish_gate.requires_publish_entry(self.inst()["position"], decision)
        if not publish:
            self.await_human(tag)
        if definition_gate.requires_definition_entry(self.inst()["position"], decision) or publish:
            # feature-t7: Publish authorization goes through the Publish entry with a binding, and the gate's generic
            # condition update is narrowed; applying the same progression functions directly records the unbound
            # decision shape the push-permit tests need.
            # feature-t3 integration: Authorize & Freeze / Accept With reservation at the Definition gates go through
            # the Definition entry, which writes the finalization ruling and then applies progression.decide. The
            # policy tests reach the same recorded state by applying that function directly (same fact shape).
            def apply(s):
                inst = s["tasks"][TASK]["workflowInstance"]
                if inst["condition"] == states.ENTERED:
                    workflow_progression.update_condition(s, self.domain.topology(inst), TASK,
                                                          dict(commandId=tag + "-await", condition=states.AWAITING_HUMAN_ACTION,
                                                               authorityRef=OWNER), revision=s["revision"])
                return workflow_progression.decide(s, self.domain.topology(inst), TASK,
                                                   dict(commandId=tag + "-decide", decision=decision, authorityRef=OWNER),
                                                   revision=s["revision"])
            return self.mutate(apply)
        return self.run("decide", commandId=tag + "-decide", decision=decision)

    def gate_decision_with_binding(self, edge, decision, tag, binding):
        """The exact shape decide() writes, plus feature-t7's publishBinding (synthetic)."""
        fact_id = tag + "-decide:decision"
        fact = dict(factId=fact_id, kind="human-decision", purpose=rules.GATE_DECISION_PURPOSE, authorityRef=OWNER,
                    payload=dict(decision=decision, edgeId=edge, reservation=None, publishBinding=binding, synthetic=True))
        if self.narrowed():
            # feature-t5 narrows the generic commands at the Validation escalation gate: the same writes, applied directly.
            from domain.workflow import progression as workflow_progression

            def apply(s):
                inst = s["tasks"][TASK]["workflowInstance"]
                topology = self.domain.topology(inst)
                for command, condition in ((tag + "-await", states.AWAITING_HUMAN_ACTION), (tag + "-record", states.RESULT_RECORDED)):
                    if inst["condition"] != states.RESULT_RECORDED:
                        workflow_progression.update_condition(s, topology, TASK, dict(commandId=command, condition=condition,
                                                                                      authorityRef=OWNER), revision=s["revision"])
                workflow_progression.record_fact(s, topology, TASK, fact, revision=s["revision"])
                return workflow_progression.advance(s, topology, TASK, dict(commandId=tag + "-decide", edgeId=edge, triggers=[fact_id],
                                                                          purpose="gate-decision", authorityRef=OWNER),
                                                    revision=s["revision"])
            return self.mutate(apply)
        self.await_human(tag)
        self.run("condition", commandId=tag + "-record", condition=states.RESULT_RECORDED)
        self.run("fact", fact=fact)
        return self.run("advance", commandId=tag + "-decide", edgeId=edge, triggers=[fact_id], purpose="gate-decision")

    def to_definition_gate(self, tag="d"):
        self.advance("E-D01", tag)
        self.advance("E-D02", tag)
        self.advance("E-D04", tag)

    def to_implement(self, tag="i"):
        """Definition lane with Authorize & Freeze, then to N-IMPL-DISPATCH."""
        self.to_definition_gate(tag)
        self.decide("Authorize & Freeze", tag)
        self.advance("E-D17", tag)

    def to_publish_gate(self, tag="p"):
        self.to_implement(tag)
        self.advance("E-I01", tag)
        self.advance("E-I02", tag)
        self.advance("E-I03", tag)
        self.advance("E-I05", tag)
        self.advance("E-V02", tag)
