"""Synthetic fixture for the Implement and Verify loop. Never a real repository, Agent or model.

Fixture builds a synthetic product line (feature-t0 acceptance), commits a strict v1 Definition on the task
branch and freezes it through feature-t3's real Definition path (submit, Authorize & Freeze with the
Definition review switched off, the review-skip and finalization rulings written by feature-t3's ruling
executor on its execution layer), then advances E-D17 to N-IMPL-DISPATCH. The product-side author
vendor mapping is written through feature-t6's `author-vendor` configuration. feature-t5's Verification
budget decision is the one remaining stand-in (budget_fact), explicitly labelled synthetic.

SyntheticAgent is a local executable standing in for the Implementer Agent: it reads a behaviour file,
edits and commits in its working directory, prints stream-json style lines and a final
{"type": "result"} line with the model it claims. Its program identity is its own file digest.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance.accept import accept_task, set_configuration
from domain.definition import dispatch as definition_dispatch, gate as definition_gate
from domain.definition.commands import frozen_definition
from domain.core import HarnessDomain
from domain.implement_verify import checks, registration
from domain.workflow import progression, states
from product_line import create_product_line, git, write
from runtime.executions import Environment, run_pending
import definition_fixture as DF

OWNER = "owner:synthetic"
IMPLEMENTER_DIGEST = "2c9583da0f4101cc04e86251d85ba15c3a2bc9d6fda024f8d79081566744f16c"
AGENT_ID = "agent:claude-code"
# Product-side author vendor mapping written through feature-t6's `config set author-vendor` path.
VENDORS = {"claude-synthetic": "Anthropic", "claude-opus-5:1m": "Anthropic", "claude-opus-5[1m]": "Anthropic"}

AGENT = r'''#!{python}
"""SYNTHETIC Implementer Agent for feature-t4 tests. Behaviour comes from a fixed JSON file."""
import json, os, subprocess, sys, time
BEHAVIOUR = {behaviour!r}
VERSION = {version!r}
if "--version" in sys.argv:
    print(VERSION); sys.exit(0)
b = json.load(open(BEHAVIOUR))
mode = b.get("mode", "commit")
def say(value):
    sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
def commit(content, name="feature.txt"):
    open(name, "w").write(content + "\n")
    subprocess.run(["git", "add", name], check=True)
    subprocess.run(["git", "-c", "user.name=Synthetic Agent", "-c", "user.email=agent@invalid", "commit", "-q",
                    "-m", "synthetic candidate"], check=True)
for i in range(b.get("tools", 1)):
    say(dict(type="tool_use", name="Edit", id="t%d" % i))
time.sleep(b.get("linger", 0))
if mode == "fail":
    sys.exit(3)
if mode == "slow":
    time.sleep(b.get("seconds", 30))
if mode == "loud":
    sys.stdout.write("x" * b.get("bytes", 100000)); sys.stdout.flush(); time.sleep(5)
if mode == "escape":
    subprocess.Popen([sys.executable, "-c", "import os,time; os.setsid(); time.sleep(%f)" % b.get("seconds", 2.0)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    time.sleep(0.8)
if mode in ("commit", "escape", "slow"):
    commit(b.get("content", "good"))
if mode == "dirty":
    open("feature.txt", "w").write("partial\n")
say(dict(type="result", result=b.get("declaration", "Implemented the Definition."), model=b.get("model", "claude-synthetic")))
'''


class SyntheticAgent:
    def __init__(self, directory, version="synthetic-agent 1.0"):
        self.directory = Path(directory)
        (self.directory / "bin").mkdir(parents=True, exist_ok=True)
        self.behaviour_path = self.directory / "agent-behaviour.json"
        self.path = self.directory / "bin" / "synthetic-agent"
        self.write(version)
        self.set(mode="commit")

    def write(self, version):
        self.path.write_text(AGENT.format(python=sys.executable, behaviour=str(self.behaviour_path), version=version))
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)

    def set(self, **behaviour):
        self.behaviour_path.write_text(json.dumps(behaviour))

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def profile(**overrides):
    value = dict(id="coding-implementer/claude-print-restricted", version="1", digest=IMPLEMENTER_DIGEST,
                 trustModel="current-user", purpose="coding-implementer", nativeApprovalPolicy="auto-deny",
                 configurationDigest=IMPLEMENTER_DIGEST, capabilities=["tool:Read", "tool:Edit", "tool:Write", "effort"],
                 limitations=["no-shell", "no-network-tools", "no-mcp", "no-prompts", "cwd-confined"],
                 operations=["implement"], maxContextBytes=4194304, maxToolCalls=20, maxRunSeconds=600)
    value.update(overrides)
    return value


def entry(port_id="local-implementer", mode="standalone", agent_path=None, **overrides):
    value = dict(id=port_id, purpose="coding-implementer", mode=mode, agent="agent:claude-code", profile=profile(),
                 approval_policy="auto-deny", provider="claude", model_ref="claude-synthetic",
                 actual_models=["claude-synthetic"], allowed_sources=["protocol-init", "protocol-result"],
                 transport="builtin", effort="high", configurationRevision="3", credentialRevision="1",
                 budget=dict(maxToolCalls=10, maxRunSeconds=60, maxOutputBytes=65536, cleanupSeconds=2))
    if mode == "standalone":
        value["standalone"] = dict(command=str(agent_path), argv=["--instruction", "{instruction}", "--inputs", "{inputs}"])
    value.update(overrides)
    return value


def budget(**overrides):
    value = dict(maxToolCalls=10, maxRunSeconds=30, maxOutputBytes=65536, cleanupSeconds=2)
    value.update(overrides)
    return value


def check(check_id, expected="good", **overrides):
    code = ("import pathlib,sys; p=pathlib.Path('feature.txt'); "
            "sys.exit(0 if p.exists() and p.read_text().strip()==%r else 1)" % expected)
    value = dict(id=check_id, argv=[sys.executable, "-c", code], timeoutSeconds=30)
    value.update(overrides)
    return value


def definition_text(task_id, prescribed=()):
    """feature-t3's strict v1 synthetic Definition, plus the Prescribed Checks extension section when asked."""
    body = DF.definition_text(task_id)
    if prescribed:
        body += "\n## Extension: Prescribed Checks\n\nMaps to: Acceptance Criteria\n\n"
        body += "".join("- `%s`\n" % c for c in prescribed)
    return body


class Fixture:
    def __init__(self, root, *, task_id="feature-t0", prescribed=(), registrations=None, declared=None, agent=None,
                 vendors=None):
        self.root = Path(root)
        self.task_id = task_id
        self.repo, self.head = create_product_line(self.root / "repo")
        git(self.repo, "config", "user.name", "Synthetic")
        git(self.repo, "config", "user.email", "synthetic@invalid")
        # feature-t3 reads the structure validator and the author evidence from the product line.
        write(self.repo, DF.VALIDATOR, (DF.HP / DF.VALIDATOR).read_bytes())
        write(self.repo, DF.EVIDENCE, "Synthetic author evidence: human declaration fixture.\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "synthetic validator and author evidence")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.domain = HarnessDomain(self.repo, entry="cli")
        self.generation = self.domain.bind_entry()
        outcome = accept_task(self.domain.store, dict(requestId="req-1", repository=str(self.repo), taskType="feature",
                                                      taskId=task_id, baseRef="main",
                                                      worktreeRoot=str(self.root / "worktrees"), authorityRef=OWNER))
        assert outcome["result"] == "ACCEPTED", outcome
        self.task = self.domain.read()["tasks"][task_id]
        self.worktree = Path(self.task["worktree"])
        self.agent = agent or SyntheticAgent(self.root / "agent")
        self.definition_path = "tasks/%s/%s.md" % (task_id, task_id)
        self.definition_commit = DF.commit_candidate(self.worktree, definition_text(task_id, prescribed), task_id=task_id)
        self.freeze()
        self.set_registration(registrations if registrations is not None else [entry(agent_path=self.agent.path)])
        self.set_checks(declared if declared is not None else [check("unit")])
        for model, vendor in (VENDORS if vendors is None else vendors).items():
            self.set_vendor(model, vendor)

    def run(self, name, **payload):
        payload.setdefault("taskId", self.task_id)
        payload.setdefault("authorityRef", OWNER)
        return self.domain.run(name, payload, generation=self.generation)

    def freeze(self):
        """feature-t3's Definition path: submit, Authorize & Freeze (review off), ruling write, then E-D17."""
        task_id = self.task_id

        def definition(name, **payload):
            payload.update(taskId=task_id, authorityRef=OWNER)
            return self.domain.run_definition(name, payload, generation=self.generation)
        definition("submit", commandId="def-submit", commit=self.definition_commit, author=DF.author(self.head))
        definition("decide", commandId="def-decide", decision=definition_gate.AUTHORIZE,
                   decisionText="定稿 " + task_id)
        env = Environment("cli", self.domain, self.generation, repository_root=str(self.repo))
        failures = run_pending(self.domain, env, {"ruling-write": definition_dispatch.ruling_executor})
        assert not failures, failures
        assert self.inst()["position"] == "N-DEF-FROZEN", self.inst()["position"]
        self.run("advance", commandId="def-e-d17", edgeId="E-D17")
        self.frozen = frozen_definition(self.domain.read(), task_id)
        assert self.frozen["commit"] == self.definition_commit, self.frozen

    def set_registration(self, entries):
        return self.domain.transaction(self.generation, lambda s: registration.set_registration(s, entries, OWNER))

    def set_vendor(self, model, vendor, agent=AGENT_ID):
        """feature-t6 product-side author vendor mapping (entries can be added or overwritten, not deleted)."""
        return set_configuration(self.domain.store, "author-vendor", dict(agent=agent, model=model, vendor=vendor), OWNER)

    def budget_fact(self, fact_id, outcome):
        """SYNTHETIC feature-t5 Verification budget decision.

        feature-t6 lets only the Policy Gate produce policy-decision facts and progression consume only its
        ALLOW; feature-t5's producer is not merged, so this stand-in records the decision with that producer
        binding and an explicit synthetic label. It is never available to product code.
        """
        task_id = self.task_id
        fact = dict(factId=fact_id, kind=progression.POLICY_DECISION, purpose="verification-budget", authorityRef=OWNER,
                    payload=dict(outcome=outcome, conclusion="ALLOW", label="SYNTHETIC feature-t5 budget decision"))

        def write(state):
            bound = self.domain.topology(progression.instance(state, task_id))
            return progression.record_fact(state, bound, task_id, fact, revision=state["revision"],
                                           producer=progression.POLICY_PRODUCER)
        return self.domain.transaction(self.generation, write)

    def set_checks(self, declared):
        return self.domain.transaction(self.generation, lambda s: checks.set_checks(s, declared, OWNER))

    def dispatch(self, command_id="d1", port_id="local-implementer", **overrides):
        payload = dict(commandId=command_id, portId=port_id, worktree=str(self.worktree), finalizationRef=self.finalization_ref(),
                       budget=budget(), role="implementer", purpose="coding-implementer")
        payload.update(overrides)
        return self.run("implement-dispatch", **payload)

    def finalization_ref(self):
        return "RU-%02d" % next(r["number"] for r in self.frozen["rulings"] if r["type"] == "finalization")

    def state(self):
        return self.domain.read()

    def inst(self):
        return self.state()["tasks"][self.task_id]["workflowInstance"]
