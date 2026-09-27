"""feature-t4 Implement and Verify loop on synthetic product lines. Docstrings carry the AC tags.

Every case uses a synthetic product-line repository, a synthetic Agent program or a synthetic embedded
Host, feature-t3's real Definition path, execution layer, port factory and RUNNING function, the real
feature-t6 Policy Gate callback and author vendor mapping, and one labelled SYNTHETIC stand-in for
feature-t5's Verification budget decision (Fixture.budget_fact). No real model, no remote operation, no
write outside the temporary directory.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from implement_verify_fixture import OWNER, Fixture, SyntheticAgent, budget, check, entry
from implement_verify_host import SAMPLE, STOPPED, STOPPING, ImplementerHost, make_discovery, sample_context
import instance_area
from domain.core import HarnessDomain
from domain.implement_verify import commands, executors, registration, results, seams, settlement
from domain.implement_verify.results import ImplementVerifyRejection
from domain.workflow import results as workflow_results, states
from domain.workflow.results import WorkflowRejection
from execution.host import HostExecutionPort
from execution.port import ExecutionError
from product_line import TOPOLOGY, git
from runtime.executions import Environment, build_port
from runtime.protocol import Fault

EMBEDDED = "host-implementer"


def embedded_entry(**overrides):
    value = entry(port_id=EMBEDDED, mode="embedded", model_ref=SAMPLE["model"],
                  actual_models=[SAMPLE["actualBinding"]["model"]], configurationRevision=SAMPLE["configurationRevision"])
    value.update(overrides)
    return value


class LoopCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t4-tests-")
            self.directory = Path(self.temp.name)

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    # -- helpers ---------------------------------------------------------------------------------
    def fixture(self, name="fx", **kw):
        return Fixture(self.directory / name, **kw)

    def build(self, fx, env, port_id):
        """feature-t3's production port factory with feature-t6's real callback (what the executor uses)."""
        found = registration.resolve(fx.state(), port_id)

        def context():
            return seams.policy_context(seams.finalization(fx.domain.read(), fx.task_id))
        port, binding = build_port(env, fx.task_id, registration.PURPOSE, registration=found,
                                   mapping=registration.mapping(found), context=context, authority_ref=OWNER,
                                   worktree=str(fx.worktree))
        port.bind_result_scanner(port, lambda: self.secrets)
        return port, dict(binding, portId=port_id)

    def local_env(self, fx):
        return Environment("cli", fx.domain, fx.generation, repository_root=str(fx.repo))

    def embedded_env(self, fx, host, port_id=EMBEDDED):
        host.domain = fx.domain
        binding = dict(connectionRef=SAMPLE["connectionRef"], credentialRef="credential:claude-native", credentialRevision="1",
                       configurationRevision=SAMPLE["configurationRevision"], agent="agent:claude-code",
                       protocolProvider="anthropic", launcher=str(fx.agent.path), scopeRef=SAMPLE["scopeRef"],
                       resourceHandle="resource:synthetic")
        return Environment("runtime", fx.domain, fx.generation, host=host, config=dict(executionBindings={port_id: binding}),
                           repository_root=str(fx.repo))

    def local_port(self, fx, port_id="local-implementer"):
        return self.build(fx, self.local_env(fx), port_id)[0]

    def embedded_port(self, fx, host, port_id=EMBEDDED):
        return self.build(fx, self.embedded_env(fx, host, port_id), port_id)[0]

    secrets = ["synthetic-secret-token-7f3a"]

    def local_context(self, fx, port_id="local-implementer"):
        return executors.execution_context(self.local_env(fx), fx.task_id, self.build(fx, self.local_env(fx), port_id)[1])

    def run_local(self, fx, execution_id, port=None):
        port = port or self.local_port(fx)
        return asyncio.run(executors.run_implement(fx.domain, fx.generation, fx.task_id, execution_id, port=port,
                                                   context=self.local_context(fx), seal_root=str(self.directory)))

    def run_embedded(self, fx, execution_id, host):
        port = self.embedded_port(fx, host)
        return asyncio.run(executors.run_implement(fx.domain, fx.generation, fx.task_id, execution_id, port=port,
                                                   context=sample_context(fx.generation), seal_root=str(self.directory)))

    def commit_effect(self, fx, content="good"):
        def effect(scenario):
            if scenario in ("completed", "start-unknown", "stopping", "stopped"):
                (fx.worktree / "feature.txt").write_text(content + "\n")
                git(fx.worktree, "add", "feature.txt")
                git(fx.worktree, "commit", "-q", "-m", "synthetic embedded candidate")
        return effect

    def implement(self, fx, content="good", command_id="d1", port_id="local-implementer"):
        fx.agent.set(mode="commit", content=content)
        out = fx.dispatch(command_id=command_id, port_id=port_id)
        return out, self.run_local(fx, out["execution"]["executionRequestId"])

    def verify(self, fx, command_id="v1"):
        return executors.run_verify(fx.domain, fx.generation, fx.task_id, dict(commandId=command_id, authorityRef=OWNER))

    def rejects(self, code, function, *args, **kw):
        with self.assertRaises((ImplementVerifyRejection, WorkflowRejection)) as ctx:
            function(*args, **kw)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception

    def unpin(self, fx):
        """Point the finalization ruling at a commit where the ruling file is absent (feature-t6 then denies)."""
        task_id, commit = fx.task_id, fx.definition_commit

        def tamper(state):
            for ruling in state["tasks"][task_id]["taskDefinition"]["frozen"]["rulings"]:
                if ruling["type"] == "finalization":
                    ruling["commit"] = commit
        fx.domain.transaction(fx.generation, tamper)

    def policy_decisions(self, fx):
        return [f for f in fx.inst()["facts"].values()
                if f["kind"] == "policy-decision" and f.get("producer") == "policy-gate" and f["purpose"] == "implement-release"]

    def edges(self, fx):
        return [c["selectedEdge"] for c in fx.inst()["commits"] if c["transitionKind"] == states.POSITION_ADVANCE]


@instance_area.needed  # ImplementerHost answers with the J-06 samples of a product-line instance area
class ImplementVerifyLoop(LoopCase):
    # -- AC-01 -----------------------------------------------------------------------------------
    def test_pass_path_crosses_registered_edges_one_at_a_time(self):
        """AC-01 AC-02: dispatch, implement, route, applicability and Verify PASS walk E-I01..E-I06 one edge per commit."""
        before = hashlib.sha256(TOPOLOGY.read_bytes()).hexdigest()
        fx = self.fixture()
        start = len(self.edges(fx))
        out, done = self.implement(fx)
        self.assertEqual(done["result"], results.IMPLEMENT_COMPLETED)
        verified = self.verify(fx)
        self.assertEqual(verified["result"], results.VERIFY_PASS)
        self.assertEqual(self.edges(fx)[start:], ["E-I01", "E-I02", "E-I03", "E-I04", "E-I06"])
        inst = fx.inst()
        self.assertEqual((inst["position"], inst["condition"]), ("N-VALIDATE-CONFIG", states.ENTERED))
        master = TOPOLOGY.read_text()
        for edge in self.edges(fx)[start:]:
            self.assertIn('topologyEdgeId="%s"' % edge, master)
        for commit in inst["commits"]:
            if commit["transitionKind"] == states.POSITION_ADVANCE and commit["selectedEdge"].startswith("E-I"):
                self.assertEqual(len(commit["triggers"]), 1, commit)
        self.assertEqual(hashlib.sha256(TOPOLOGY.read_bytes()).hexdigest(), before)

    def test_none_applicable_is_recorded_apart_from_pass(self):
        """AC-01 AC-03: with no applicable check Verify records None Applicable and follows E-I05, distinct from PASS."""
        fx = self.fixture(declared=[check("docs-only", paths=["docs/"])])
        self.implement(fx)
        verified = self.verify(fx)
        self.assertEqual(verified["result"], results.VERIFY_NOT_APPLICABLE)
        self.assertEqual(verified["verification"]["result"], "NOT_APPLICABLE")
        self.assertEqual(self.edges(fx)[-1], "E-I05")
        facts = [f for f in fx.inst()["facts"].values() if f["purpose"] == "verify-applicability"]
        self.assertEqual(facts[-1]["kind"], "configuration-decision")
        self.assertEqual(facts[-1]["payload"]["conclusion"], "None Applicable")
        self.assertFalse([f for f in fx.inst()["facts"].values() if f["kind"] == "verify-result"])

    # -- AC-02 -----------------------------------------------------------------------------------
    def test_candidate_evidence_and_claim_are_stable_references(self):
        """AC-02: candidate commit, execution evidence and the completion claim are recorded; HEAD moving later changes nothing."""
        fx = self.fixture()
        out, done = self.implement(fx)
        record = fx.state()["tasks"][fx.task_id]["implementVerify"]["executions"][out["execution"]["executionRequestId"]]
        candidate = record["settlement"]["candidateCommit"]
        self.assertEqual(candidate, git(fx.worktree, "rev-parse", "HEAD"))
        fact = fx.inst()["facts"][record["settlement"]["fact"]]
        self.assertEqual(fact["payload"]["declaration"]["kind"], "implementation-claim")
        self.assertEqual(fact["payload"]["changedFiles"], ["feature.txt"])
        self.assertTrue(fact["payload"]["programIdentity"]["binaryDigest"])
        self.assertFalse([f for f in fx.inst()["facts"].values() if f["kind"] == "verify-result"])
        port = fx.state()["executionReservations"][record["executionRequestId"]]
        self.assertTrue(port["result_envelope"] and port["observations"])
        verified = self.verify(fx)
        (fx.worktree / "later.txt").write_text("later\n")
        git(fx.worktree, "add", "later.txt")
        git(fx.worktree, "commit", "-q", "-m", "later commit")
        stored = fx.state()["tasks"][fx.task_id]["implementVerify"]["verifications"][verified["verification"]["verificationId"]]
        self.assertEqual(stored["candidateCommit"], candidate)
        self.assertNotEqual(git(fx.worktree, "rev-parse", "HEAD"), candidate)

    def test_leaving_the_bound_branch_is_not_a_candidate(self):
        """AC-02 AC-08: an Agent that commits on another branch produces no consumable candidate; the node enters recovery."""
        fx = self.fixture()
        self.rejects(results.WORKTREE_BINDING_MISMATCH, fx.dispatch, command_id="d0",
                     worktree=str(self.directory / "fx" / "repo"))
        out = fx.dispatch()
        agent_effect = fx.agent
        agent_effect.set(mode="no-commit")
        git(fx.worktree, "checkout", "-q", "-b", "elsewhere")
        (fx.worktree / "feature.txt").write_text("good\n")
        git(fx.worktree, "add", "feature.txt")
        git(fx.worktree, "commit", "-q", "-m", "other branch")
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertTrue(done["recovery"])
        self.assertEqual(done["reason"], "candidate-binding-mismatch")
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)

    # -- AC-03 -----------------------------------------------------------------------------------
    def test_verify_fail_cannot_become_pass(self):
        """AC-03: FAIL is recorded and no path rewrites it: reservation, Human decision, check change, replay, generic commands."""
        fx = self.fixture()
        self.implement(fx, content="bad")
        verified = self.verify(fx)
        self.assertEqual(verified["result"], results.VERIFY_FAIL)
        verification_id = verified["verification"]["verificationId"]
        raw = json.dumps(fx.state()["tasks"][fx.task_id]["implementVerify"]["verifications"][verification_id], sort_keys=True)
        self.assertEqual(fx.inst()["position"], "N-VERIFY-BUDGET-DECISION")
        # replay of the same Verify command returns the same FAIL
        self.assertEqual(self.verify(fx)["result"], results.IDEMPOTENT_REPLAY)
        # re-running Verify elsewhere is refused
        self.rejects(results.POSITION_NOT_APPLICABLE, self.verify, fx, "v2")
        # changing the declared checks after the fact does not touch the recorded result
        fx.set_checks([check("unit", expected="bad")])
        # a generic PASS fact or edge on the Verify node: drive back is impossible, and at the budget node E-I06 is illegal
        self.rejects(workflow_results.ILLEGAL_TRANSITION, fx.run, "advance", commandId="x1", edgeId="E-I06")
        # exhausted budget -> escalation gate: Accept With Reservation is not in the legal set
        fx.budget_fact("budget-1", "Budget Exhausted")
        fx.run("implement-remediate", commandId="r1", budgetFact="budget-1")
        self.rejects(workflow_results.DECISION_NOT_LEGAL_HERE, fx.run, "decide", commandId="x2",
                     decision="Accept With Reservation")
        after = json.dumps(fx.state()["tasks"][fx.task_id]["implementVerify"]["verifications"][verification_id], sort_keys=True)
        self.assertEqual(after, raw)

    def test_generic_commands_cannot_forge_a_verify_result(self):
        """AC-03: at the Verify nodes the generic fact / condition / advance / recover-assess surface is refused."""
        fx = self.fixture()
        self.implement(fx, content="bad")
        self.assertEqual(fx.inst()["position"], "N-VERIFY-APPLICABILITY")
        for name, payload in (("fact", dict(fact=dict(factId="forged", kind="verify-result", purpose="verification-result",
                                                      authorityRef=OWNER, payload=dict(result="PASS")))),
                              ("condition", dict(commandId="c1", condition=states.EXECUTING)),
                              ("advance", dict(commandId="a1", edgeId="E-I05")),
                              ("recover-assess", dict(assessmentId="s1", assessment="RESULT_CONFIRMED"))):
            with self.subTest(command=name):
                self.rejects(workflow_results.ILLEGAL_TRANSITION, fx.run, name, **payload)
        self.assertEqual(self.verify(fx)["result"], results.VERIFY_FAIL)

    def test_check_execution_failures_enter_recovery_not_fail(self):
        """AC-03 AC-08: an unstartable, timed-out or unmapped check is an execution failure in recovery, never a business FAIL."""
        cases = {
            "not-startable": dict(id="unit", argv=["/nonexistent/synthetic-check"], timeoutSeconds=5),
            "timeout": dict(id="unit", argv=[sys.executable, "-c", "import time; time.sleep(5)"], timeoutSeconds=1),
            "unmapped": dict(id="unit", argv=[sys.executable, "-c", "raise SystemExit(7)"], timeoutSeconds=5),
        }
        for name, declared in cases.items():
            with self.subTest(case=name):
                fx = self.fixture(name, declared=[declared])
                self.implement(fx)
                verified = self.verify(fx)
                self.assertEqual(verified["result"], results.CHECK_EXECUTION_FAILED)
                self.assertEqual((fx.inst()["position"], fx.inst()["condition"]),
                                 ("N-VERIFY-EXECUTE", states.RECOVERY_REQUIRED))
                self.assertFalse([f for f in fx.inst()["facts"].values() if f["kind"] == "verify-result"])
                attempt = fx.inst()["attempts"][-1]
                self.assertEqual(attempt["status"], states.EXECUTION_FAILED)

    def test_prescribed_check_not_registered_is_not_not_applicable(self):
        """AC-03 AC-08: a Definition-required check absent from the declarations enters recovery (KB-259 option A)."""
        fx = self.fixture(prescribed=("unit", "lint"), declared=[check("unit")])
        self.implement(fx)
        verified = self.verify(fx)
        self.assertEqual(verified["result"], results.PRESCRIBED_CHECK_UNREGISTERED)
        self.assertEqual(verified["verification"]["missing"], ["lint"])
        self.assertEqual(self.edges(fx)[-1], "E-I04")
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
        # after an authorised declaration and a Human-authorised restart the same node runs the checks
        fx.set_checks([check("unit"), check("lint")])
        assessed = fx.run("implement-assess", assessmentId="as-1")
        self.assertEqual(assessed["assessment"], "RESTART_SAFE")
        occurrence = dict(workflowInstance=fx.task_id, node="N-VERIFY-EXECUTE",
                          positionEntryRuntimeVersion=fx.inst()["positionEntryRevision"])
        fx.run("recover", commandId="rs-1", action="RESTART_CURRENT_NODE", assessmentId="as-1",
               humanAuthorization=dict(workflowInstance=fx.task_id, occurrence=occurrence,
                                       expectedRuntimeVersion=fx.inst()["runtimeVersion"], assessmentId="as-1",
                                       action="RESTART_CURRENT_NODE", effectScope="rerun declared checks",
                                       authorizationRef="human:synthetic:restart-1"))
        self.assertEqual(self.verify(fx, "v2")["result"], results.VERIFY_PASS)

    # -- AC-04 -----------------------------------------------------------------------------------
    def test_remediation_budget_remains_returns_to_implementer_in_new_occurrence(self):
        """AC-04: Budget Remains follows E-I08/E-I09 into a new occurrence carrying the last Verification Result."""
        fx = self.fixture()
        self.implement(fx, content="bad")
        failed = self.verify(fx)
        first_entry = [c for c in fx.inst()["commits"] if c["selectedEdge"] == "E-I01"][-1]["nextSnapshot"]
        self.rejects(results.BUDGET_DECISION_MISSING, fx.run, "implement-remediate", commandId="r0", budgetFact="none")
        fx.budget_fact("budget-1", "Budget Remains")
        routed = fx.run("implement-remediate", commandId="r1", budgetFact="budget-1")
        self.assertEqual(routed["position"], "N-VERIFY-AUTONOMOUS-REMEDIATION")
        definition = (fx.worktree / fx.definition_path).read_bytes()
        out, done = self.implement(fx, content="good", command_id="d2")
        self.assertEqual(self.edges(fx)[-4:-2], ["E-I08", "E-I09"])
        self.assertEqual(out["execution"]["remediation"]["verificationId"], failed["verification"]["verificationId"])
        self.assertNotEqual(out["execution"]["occurrence"]["positionEntryRuntimeVersion"],
                            first_entry["positionEntryRuntimeVersion"])
        self.assertEqual((fx.worktree / fx.definition_path).read_bytes(), definition)
        self.assertEqual(self.verify(fx, "v2")["result"], results.VERIFY_PASS)

    def test_budget_exhausted_escalation_continue_and_close(self):
        """AC-04: Budget Exhausted reaches the escalation gate; Continue returns via E-I13/E-I14; Close Task terminates."""
        fx = self.fixture()
        self.implement(fx, content="bad")
        self.verify(fx)
        fx.budget_fact("budget-1", "Budget Exhausted")
        fx.run("implement-remediate", commandId="r1", budgetFact="budget-1")
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]),
                         ("N-VERIFY-ESCALATION-GATE", states.AWAITING_HUMAN_ACTION))
        fx.run("decide", commandId="g1", decision="Continue")
        self.implement(fx, content="good", command_id="d2")
        self.assertEqual([e for e in self.edges(fx) if e in ("E-I10", "E-I11", "E-I13", "E-I14")],
                         ["E-I10", "E-I11", "E-I13", "E-I14"])
        self.assertEqual(self.verify(fx, "v2")["result"], results.VERIFY_PASS)
        other = self.fixture("close")
        self.implement(other, content="bad")
        self.verify(other)
        other.budget_fact("b", "Budget Exhausted")
        other.run("implement-remediate", commandId="r1", budgetFact="b")
        other.run("decide", commandId="g1", decision="Close Task")
        self.assertEqual((other.inst()["lifecycle"], other.inst()["position"]), (states.CLOSED, "N-VERIFY-CLOSE"))

    def test_late_result_of_old_occurrence_is_not_consumed(self):
        """AC-04 AC-08: a result arriving after the task moved (closed) is recorded as not consumed."""
        fx = self.fixture()
        out = fx.dispatch()
        execution = out["execution"]["executionRequestId"]
        fx.run("close", commandId="close-1", reasonCategory="human-initiated")
        late = fx.domain.transaction(fx.generation, lambda s: __import__("domain.implement_verify.implement", fromlist=["x"])
                                     .settle(s, fx.domain.topology(s["tasks"][fx.task_id]["workflowInstance"]),
                                             fx.task_id, execution, revision=s["revision"],
                                             port_error=dict(code="execution_port_failure")))
        self.assertEqual(late["execution"]["settlement"]["kind"], "late-result-not-consumed")
        self.assertTrue(late["execution"]["settlement"]["reservationReleased"])
        self.assertEqual(fx.inst()["lifecycle"], states.CLOSED)
        self.assertFalse([f for f in fx.inst()["facts"].values() if f["purpose"] == "implement-result"])

    # -- AC-05 -----------------------------------------------------------------------------------
    def test_embedded_reservation_precedes_release_and_one_request_one_execution(self):
        """AC-05: the port reservation is persisted before host.execution.start; a lost start answer queries the original."""
        fx = self.fixture(registrations=None)
        fx.set_registration([entry(agent_path=fx.agent.path), embedded_entry()])
        host = ImplementerHost(fx.generation)
        host.effect = self.commit_effect(fx)
        host.scenario = "start-unknown"
        out = fx.dispatch(port_id=EMBEDDED)
        done = self.run_embedded(fx, out["execution"]["executionRequestId"], host)
        self.assertEqual(done["result"], results.IMPLEMENT_COMPLETED)
        self.assertEqual(host.methods.count("host.execution.start"), 1)
        self.assertIn("host.operation.get", host.methods)
        self.assertTrue(host.observed_reservation["start_dispatched"])
        self.assertEqual(host.observed_reservation["phase"], "starting")
        self.assertEqual(host.start["roleIntent"], "implement")
        again = self.run_embedded(fx, out["execution"]["executionRequestId"], host)
        self.assertEqual(again["result"], results.IDEMPOTENT_REPLAY)
        self.assertEqual(host.methods.count("host.execution.start"), 1)
        executions = fx.domain.store.coordination / "executions"
        self.assertFalse(executions.exists() and any(executions.iterdir()), "embedded mode must not spawn locally")

    def test_budget_limits_and_no_dollar_cap(self):
        """AC-05: a budget above the registration is refused before release; a budget stop is an execution fact; no dollar field."""
        fx = self.fixture()
        self.rejects(results.BUDGET_EXCEEDS_PROFILE, fx.dispatch, budget=budget(maxRunSeconds=61))
        self.rejects(results.BUDGET_EXCEEDS_PROFILE, fx.dispatch, budget=dict(maxToolCalls=1, maxRunSeconds=1))
        fx.agent.set(mode="slow", seconds=20)
        out = fx.dispatch(budget=budget(maxRunSeconds=2, cleanupSeconds=1))
        self.assertEqual(out["trustBoundary"]["trustModel"], "current-user")
        self.assertIn("cwd-confined", out["trustBoundary"]["limitations"])
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertTrue(done["recovery"])
        self.assertEqual(done["reason"], "stopped-timeout")
        self.assertEqual(fx.inst()["attempts"][-1]["status"], states.EXECUTION_FAILED)
        self.assertFalse([f for f in fx.inst()["facts"].values() if f["kind"] == "verify-result"])
        def keys(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield k
                    yield from keys(v)
            elif isinstance(value, list):
                for v in value:
                    yield from keys(v)
        import re
        words = lambda k: {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", k)}
        forbidden = [k for k in keys(fx.state()) if words(k) & {"usd", "cost", "dollar", "dollars"}]
        self.assertEqual(forbidden, [])
        self.assertIn("maxOutputBytes", fx.state()["executionReservations"][out["execution"]["executionRequestId"]]["intent"]["budget"])
        job = json.loads((fx.domain.store.coordination / "executions" / out["execution"]["executionRequestId"] / "job.json").read_text())
        self.assertFalse([a for a in job["argv"] if "budget-usd" in a or "cost" in a.lower()])

    def test_output_and_tool_call_limits_stop_the_execution(self):
        """AC-05: exceeding the output bytes or tool-call count stops the target and is recorded as the stop reason."""
        for name, behaviour, reason in (("loud", dict(mode="loud", bytes=200000), "stopped-output-limit"),
                                        ("tools", dict(mode="commit", tools=15, linger=3), "stopped-tool-call-budget")):
            with self.subTest(case=name):
                fx = self.fixture(name)
                fx.agent.set(**behaviour)
                out = fx.dispatch(budget=budget(maxOutputBytes=4096, maxToolCalls=3))
                done = self.run_local(fx, out["execution"]["executionRequestId"])
                self.assertEqual(done.get("reason"), reason, done)

    def test_authorization_callback_and_registration_gate_release(self):
        """AC-05: a refused authorization or a withdrawn product-side registration stops the release with no start."""
        fx = self.fixture()
        fx.set_registration([entry(agent_path=fx.agent.path), embedded_entry()])
        self.unpin(fx)  # the real feature-t6 callback then denies the implement-release
        host = ImplementerHost(fx.generation)
        out = fx.dispatch(port_id=EMBEDDED)
        done = self.run_embedded(fx, out["execution"]["executionRequestId"], host)
        self.assertEqual(done["reason"], "rejected-before-release:policy-denied")
        self.assertNotIn("host.execution.start", host.methods)
        other = self.fixture("withdrawn")
        other.set_registration([entry(agent_path=other.agent.path), embedded_entry()])
        out = other.dispatch(port_id=EMBEDDED)
        host = ImplementerHost(other.generation)
        port = self.embedded_port(other, host)  # built while registered, as a factory would have
        found = registration.resolve(other.state(), EMBEDDED)
        record = other.state()["tasks"][other.task_id]["implementVerify"]["executions"][out["execution"]["executionRequestId"]]
        intent = executors.intent_for(other.state(), record, found, sample_context(other.generation))
        other.set_registration([entry(agent_path=other.agent.path)])
        with self.assertRaises(ExecutionError) as exc:  # host.py:99 re-resolves (portId, purpose) on every preflight
            asyncio.run(port.preflight(intent))
        self.assertEqual(exc.exception.code, "execution-port-unregistered")
        done = asyncio.run(executors.run_implement(other.domain, other.generation, other.task_id,
                                                   out["execution"]["executionRequestId"], port=port,
                                                   context=sample_context(other.generation), seal_root=str(self.directory)))
        self.assertEqual(done["reason"], "rejected-before-release:REGISTRY_ENTRY_MISSING")
        self.assertNotIn("host.execution.start", host.methods)

    def test_policy_gate_request_shape_and_registration_reader(self):
        """AC-05: the real feature-t6 callback evaluates implement-release with the finalized Definition, its ruling,
        maxCalls 1, a four-field budget and the injected product-side registration; an unpinned ruling is DENY."""
        reader = HarnessDomain.policy_sources["implementer_registrations"]
        self.assertIs(reader, registration.resolve)
        fx = self.fixture()
        self.assertEqual(reader(fx.state(), "local-implementer")["id"], "local-implementer")
        self.assertIsNone(reader(fx.state(), "no-such-port"))
        out, done = self.implement(fx)
        self.assertEqual(done["result"], results.IMPLEMENT_COMPLETED)
        decisions = self.policy_decisions(fx)
        self.assertTrue(decisions)
        ruling = next(r for r in fx.frozen["rulings"] if r["type"] == "finalization")
        for fact in decisions:
            decision = fact["payload"]
            self.assertEqual((fact["authorityRef"], decision["subject"], decision["conclusion"], decision["derived"]["maxCalls"]),
                             (OWNER, "implement-release", "ALLOW", 1))
            read = {row["role"]: row for row in decision["inputs"]}
            self.assertEqual(read["definition"]["ref"], fx.definition_commit + ":" + fx.definition_path)
            self.assertEqual(read["finalization"]["ref"], ruling["commit"] + ":" + ruling["path"])
            self.assertIn("implementer-registration", read)
            self.assertTrue(all(row["result"] in ("PASS", "NOT_APPLICABLE") for row in decision["items"]), decision["items"])
        # A finalization reference that does not pin this Definition is denied before any release.
        other = self.fixture("unpinned")
        self.unpin(other)
        head = git(other.worktree, "rev-parse", "HEAD")
        out = other.dispatch()
        done = self.run_local(other, out["execution"]["executionRequestId"])
        self.assertEqual(done["reason"], "rejected-before-release:policy-denied", done)
        denied = self.policy_decisions(other)
        self.assertEqual([f["payload"]["conclusion"] for f in denied], ["DENY"])
        self.assertIn(("input-evidence", "FAIL"), [(r["item"], r["result"]) for r in denied[0]["payload"]["items"]])
        self.assertEqual(git(other.worktree, "rev-parse", "HEAD"), head)

    # -- AC-06 -----------------------------------------------------------------------------------
    def test_program_identity_rediscovered_and_version_change_not_rejected(self):
        """AC-06: each execution records the rediscovered program identity; a new Agent version is not a rejection."""
        fx = self.fixture()
        out, done = self.implement(fx, content="bad")
        first = fx.state()["executionReservations"][out["execution"]["executionRequestId"]]["program_identity"]
        self.verify(fx)
        fx.budget_fact("b1", "Budget Remains")
        fx.run("implement-remediate", commandId="r1", budgetFact="b1")
        fx.agent.write("synthetic-agent 2.0")
        out2, done2 = self.implement(fx, content="good", command_id="d2")
        self.assertEqual(done2["result"], results.IMPLEMENT_COMPLETED)
        second = fx.state()["executionReservations"][out2["execution"]["executionRequestId"]]["program_identity"]
        self.assertEqual(first["version"], "synthetic-agent 1.0")
        self.assertEqual(second["version"], "synthetic-agent 2.0")
        self.assertNotEqual(first["binaryDigest"], second["binaryDigest"])
        self.assertNotIn("programIdentity", registration.entries(fx.state())[0]["profile"])

    def test_identity_readback_vendor_and_approval_rejections(self):
        """AC-06: model readback, unknown vendor mapping, profile digest, agent and approval mismatches are not consumed."""
        fx = self.fixture()
        fx.agent.set(mode="commit", model="claude-unregistered")
        out = fx.dispatch()
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertEqual(done["reason"], "result-rejected:execution-port-identity-unverified")
        vendorless = self.fixture("vendor")
        vendorless.set_registration([entry(agent_path=vendorless.agent.path, model_ref="claude-no-vendor",
                                           actual_models=["claude-no-vendor"])])
        out = vendorless.dispatch()
        done = self.run_local(vendorless, out["execution"]["executionRequestId"])
        self.assertEqual(done["reason"], "rejected-before-release:VENDOR_MAPPING_UNKNOWN")
        approval = self.fixture("approval")
        approval.set_registration([entry(agent_path=approval.agent.path), embedded_entry()])
        host = ImplementerHost(approval.generation)
        host.effect = self.commit_effect(approval)
        host.approvals = ["approval:unexpected"]
        out = approval.dispatch(port_id=EMBEDDED)
        done = self.run_embedded(approval, out["execution"]["executionRequestId"], host)
        self.assertEqual(done["reason"], "result-rejected:execution-port-approval-out-of-policy")
        # profile digest and agent mismatches at preflight, one field at a time
        found = registration.resolve(approval.state(), EMBEDDED)
        for field, value in (("digest", "d" * 64), ("agent", "agent:other")):
            with self.subTest(field=field):
                port = self.embedded_port(approval, ImplementerHost(approval.generation))
                intent = executors.intent_for(approval.state(), approval.state()["tasks"][approval.task_id]
                                              ["implementVerify"]["executions"][out["execution"]["executionRequestId"]],
                                              found, sample_context(approval.generation))
                if field == "digest":
                    intent["profile"] = dict(intent["profile"], digest=value)
                else:
                    intent["executionBinding"]["agent"] = value
                with self.assertRaises(ExecutionError):
                    asyncio.run(port.preflight(intent))
        review = HostExecutionPort(ImplementerHost(approval.generation), approval.domain, found, registration.mapping(found),
                                   make_discovery(found), None)
        review.bind_result_scanner(review, lambda: [])
        with self.assertRaises(ExecutionError) as exc:
            asyncio.run(review.discovery(intent))
        self.assertEqual(exc.exception.code, "execution-port-profile-mismatch")

    def test_known_secret_never_reaches_the_domain(self):
        """AC-06: a completion claim carrying a known login secret is refused before it is persisted."""
        fx = self.fixture()
        fx.agent.set(mode="commit", declaration="done " + self.secrets[0])
        out = fx.dispatch()
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertEqual(done["reason"], "result-rejected:secret-leak")
        self.assertNotIn(self.secrets[0], json.dumps(fx.state()))

    # -- AC-07 -----------------------------------------------------------------------------------
    def test_j06_samples_classify_as_stop_unconfirmed_and_stopped(self):
        """AC-07: the fixed J-06 r2 samples, unmodified, classify as stop unconfirmed and stopped by the literal prefix."""
        stopping = json.loads(STOPPING.read_text())
        stopped = json.loads(STOPPED.read_text())
        self.assertTrue(stopping["reason"].startswith(settlement.STOP_UNCONFIRMED_PREFIX))
        self.assertEqual(settlement.STOP_UNCONFIRMED_PREFIX, "stop unconfirmed after")
        port = dict(observations=[dict(physical_execution=stopping)], result=None, start_dispatched=True)
        self.assertEqual(settlement.classify(port)["kind"], "stop-unconfirmed")
        port = dict(observations=[dict(physical_execution=stopped)], result=None, start_dispatched=True)
        self.assertEqual(settlement.classify(port)["kind"], "stopped")
        for variant in (dict(exit=None), dict(reason="stop confirmed: every process exited"), dict(state="running")):
            with self.subTest(variant=variant):
                port = dict(observations=[dict(physical_execution=dict(stopping, **variant))], result=None)
                self.assertNotEqual(settlement.classify(port)["kind"], "stop-unconfirmed")

    def test_embedded_stop_unconfirmed_keeps_reservation_until_host_resolves(self):
        """AC-07 AC-08: stopping + exit + prefix keeps the reservation; the Host's stopped releases it against that fact."""
        fx = self.fixture()
        fx.set_registration([entry(agent_path=fx.agent.path), embedded_entry()])
        host = ImplementerHost(fx.generation)
        host.scenario = "stopping"
        out = fx.dispatch(port_id=EMBEDDED)
        execution = out["execution"]["executionRequestId"]
        done = self.run_embedded(fx, execution, host)
        self.assertEqual(done["reason"], results.STOP_UNCONFIRMED)
        reservation = fx.inst()["reservations"][execution]
        self.assertEqual(reservation["status"], "held")
        self.assertEqual(fx.inst()["attempts"][-1]["status"], states.ATTEMPT_INDETERMINATE)
        self.assertEqual(host.methods.count("host.execution.start"), 1)
        self.assertFalse([m for m in host.methods if "quiesce" in m or "shutdown" in m or "handoff" in m])
        assessed = fx.run("implement-assess", assessmentId="a1")
        self.assertEqual(assessed["assessment"], "INDETERMINATE")
        self.rejects(workflow_results.ILLEGAL_TRANSITION, fx.run, "recover", commandId="rc1",
                     action="RECORD_CONFIRMED_RESULT", assessmentId="a1")
        # no second dispatch while the node is in recovery: the execution is never repeated
        self.rejects(results.POSITION_NOT_APPLICABLE, fx.dispatch, command_id="d2", port_id=EMBEDDED)
        host.scenario = "stopped"
        refreshed = self.run_embedded(fx, execution, host)
        self.assertEqual(refreshed["physical"]["kind"], "stopped")
        self.assertEqual(host.methods.count("host.execution.start"), 1)
        self.assertNotIn("host.resource.read", host.methods)
        assessed = fx.run("implement-assess", assessmentId="a2")
        self.assertEqual(assessed["assessment"], "RECONCILIATION_REQUIRED" if fx.worktree.joinpath("feature.txt").exists()
                         else "RESTART_SAFE")
        self.assertEqual(fx.inst()["reservations"][execution]["status"],
                         "settled" if assessed["assessment"] == "RESTART_SAFE" else "held")

    def test_standalone_escaped_descendant_is_stop_unconfirmed(self):
        """AC-07: a descendant that leaves the target session keeps the standalone execution stop unconfirmed until it exits."""
        fx = self.fixture()
        fx.agent.set(mode="escape", seconds=4.0)
        out = fx.dispatch()
        execution = out["execution"]["executionRequestId"]
        done = self.run_local(fx, execution)
        self.assertEqual(done["reason"], results.STOP_UNCONFIRMED, done)
        physical = settlement.latest(fx.state()["executionReservations"][execution])
        self.assertTrue(physical["reason"].startswith("stop unconfirmed after exit"))
        self.assertEqual(fx.inst()["reservations"][execution]["status"], "held")
        time.sleep(6)
        port = self.local_port(fx)
        refreshed = asyncio.run(executors.run_implement(fx.domain, fx.generation, fx.task_id, execution, port=port,
                                                        context=self.local_context(fx), seal_root=str(self.directory)))
        self.assertTrue(refreshed.get("refreshed"))
        self.assertNotEqual(refreshed["physical"]["kind"], "stop-unconfirmed")
        assessed = fx.run("implement-assess", assessmentId="a1")
        self.assertEqual(assessed["assessment"], "RECONCILIATION_REQUIRED")

    # -- AC-08 -----------------------------------------------------------------------------------
    def test_recovery_result_confirmed_routes_after_record(self):
        """AC-08: a complete candidate whose vendor was unknown at settlement is confirmed later and routed on."""
        vendors = {"claude-synthetic-request-only": "Anthropic"}
        fx = self.fixture(vendors=vendors)
        fx.agent.set(mode="commit", content="good")
        fx.set_registration([entry(agent_path=fx.agent.path, model_ref="claude-synthetic-request-only",
                                   actual_models=["claude-synthetic"])])
        out = fx.dispatch()
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertEqual(done["reason"], results.VENDOR_MAPPING_UNKNOWN)
        fx.set_vendor("claude-synthetic", "Anthropic")  # the Human adds the missing mapping entry
        assessed = fx.run("implement-assess", assessmentId="a1")
        self.assertEqual(assessed["assessment"], "RESULT_CONFIRMED")
        fx.run("recover", commandId="rc1", action="RECORD_CONFIRMED_RESULT", assessmentId="a1")
        self.assertEqual(fx.inst()["condition"], states.RESULT_RECORDED)
        routed = fx.run("implement-route", commandId="rt1")
        self.assertEqual(routed["result"], results.CANDIDATE_ROUTED)
        self.assertEqual(self.verify(fx)["result"], results.VERIFY_PASS)

    def test_recovery_restart_safe_requires_human_authorization(self):
        """AC-08: a failed execution with an unchanged worktree is RESTART_SAFE; restart needs the exact Human authorization."""
        fx = self.fixture()
        fx.agent.set(mode="fail")
        out = fx.dispatch()
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertTrue(done["recovery"])
        assessed = fx.run("implement-assess", assessmentId="a1")
        self.assertEqual(assessed["assessment"], "RESTART_SAFE")
        self.assertEqual(fx.inst()["reservations"][out["execution"]["executionRequestId"]]["status"], "settled")
        self.rejects(workflow_results.RECOVERY_AUTHORIZATION_MISSING, fx.run, "recover", commandId="rs0",
                     action="RESTART_CURRENT_NODE", assessmentId="a1")
        occurrence = dict(workflowInstance=fx.task_id, node="N-IMPL-EXECUTE",
                          positionEntryRuntimeVersion=fx.inst()["positionEntryRevision"])
        fx.run("recover", commandId="rs1", action="RESTART_CURRENT_NODE", assessmentId="a1",
               humanAuthorization=dict(workflowInstance=fx.task_id, occurrence=occurrence,
                                       expectedRuntimeVersion=fx.inst()["runtimeVersion"], assessmentId="a1",
                                       action="RESTART_CURRENT_NODE", effectScope="rerun the Implementer",
                                       authorizationRef="human:synthetic:1"))
        self.assertEqual(fx.inst()["condition"], states.ENTERED)
        out2, done2 = self.implement(fx, command_id="d2")
        self.assertEqual(done2["result"], results.IMPLEMENT_COMPLETED)

    def test_recovery_reconciliation_and_indeterminate_are_not_overridable(self):
        """AC-08: uncommitted partial work needs reconciliation; a vanished session is INDETERMINATE and never completion."""
        fx = self.fixture()
        fx.agent.set(mode="dirty")
        out = fx.dispatch()
        done = self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertEqual(done["reason"], "candidate-uncommitted")
        assessed = fx.run("implement-assess", assessmentId="a1")
        self.assertEqual(assessed["assessment"], "RECONCILIATION_REQUIRED")
        self.rejects(workflow_results.RECOVERY_AUTHORIZATION_MISSING, fx.run, "recover", commandId="rc1",
                     action="RECONCILE_CURRENT_NODE", assessmentId="a1", mutatesExternalState=True)
        self.rejects(workflow_results.ILLEGAL_TRANSITION, fx.run, "recover", commandId="rc2",
                     action="RESTART_CURRENT_NODE", assessmentId="a1")
        vanished = self.fixture("vanished")
        vanished.agent.set(mode="slow", seconds=30)
        out = vanished.dispatch()
        execution = out["execution"]["executionRequestId"]

        async def run_and_kill():
            port = self.local_port(vanished)
            task = asyncio.create_task(executors.run_implement(vanished.domain, vanished.generation, vanished.task_id,
                                                               execution, port=port, context=self.local_context(vanished),
                                                               seal_root=str(self.directory)))
            directory = vanished.domain.store.coordination / "executions" / execution
            for _ in range(400):
                if (directory / "record-000001.json").exists():
                    break
                await asyncio.sleep(0.05)
            ready = json.loads((directory / "ready.json").read_text())
            target = json.loads((directory / "record-000001.json").read_text())["target"]["pid"]
            os.kill(ready["pid"], signal.SIGKILL)
            os.killpg(target, signal.SIGKILL)
            return await task
        done = asyncio.run(run_and_kill())
        self.assertEqual(done["reason"], results.RESULT_UNKNOWN)
        self.assertEqual(vanished.inst()["attempts"][-1]["status"], states.ATTEMPT_INDETERMINATE)
        assessed = vanished.run("implement-assess", assessmentId="a1")
        self.assertEqual(assessed["assessment"], "INDETERMINATE")
        for action in ("RECORD_CONFIRMED_RESULT", "RESTART_CURRENT_NODE"):
            with self.subTest(action=action):
                self.rejects(workflow_results.ILLEGAL_TRANSITION, vanished.run, "recover", commandId="x-" + action,
                             action=action, assessmentId="a1")

    # -- AC-09 -----------------------------------------------------------------------------------
    def test_two_executors_and_distinguishable_rejections(self):
        """AC-09: standalone and embedded executors both dispatch legally; every refusal reason is distinguishable."""
        fx = self.fixture()
        fx.set_registration([entry(agent_path=fx.agent.path), embedded_entry()])
        self.rejects(results.ROLE_NOT_LEGAL_HERE, fx.dispatch, role="reviewer")
        self.rejects(results.ROLE_NOT_LEGAL_HERE, fx.dispatch, purpose="review")
        self.rejects(results.AUTHORITY_NOT_DERIVABLE, fx.dispatch, finalizationRef="RU-99")
        self.rejects(results.REGISTRY_ENTRY_MISSING, fx.dispatch, port_id="unregistered")
        self.rejects(results.WORKTREE_BINDING_MISMATCH, fx.dispatch, worktree=str(self.directory))
        self.rejects(results.CAPACITY_EXHAUSTED, fx.run, "implement-dispatch", taskId="feature-t1", commandId="n1")
        fx.domain.transaction(fx.generation, lambda s: s["configuration"].update(concurrencyLimit=2))
        self.rejects(results.ACCEPTANCE_REQUIRED, fx.run, "implement-dispatch", taskId="feature-t1", commandId="n2")
        fx.domain.transaction(fx.generation, lambda s: s["configuration"].update(concurrencyLimit=1))
        fx.agent.set(mode="commit", content="bad")
        out = fx.dispatch()
        self.rejects(results.EXECUTION_WRITER_BUSY, fx.dispatch, command_id="d-busy")
        self.run_local(fx, out["execution"]["executionRequestId"])
        self.verify(fx)
        fx.budget_fact("b1", "Budget Remains")
        fx.run("implement-remediate", commandId="r1", budgetFact="b1")
        # continuing an existing task at full capacity is not a new acceptance
        host = ImplementerHost(fx.generation)
        host.effect = self.commit_effect(fx)
        out2 = fx.dispatch(command_id="d2", port_id=EMBEDDED)
        done = self.run_embedded(fx, out2["execution"]["executionRequestId"], host)
        self.assertEqual(done["result"], results.IMPLEMENT_COMPLETED)
        records = fx.state()["tasks"][fx.task_id]["implementVerify"]["executions"]
        shapes = {tuple(sorted(r)) for r in records.values()}
        self.assertEqual(len(shapes), 1)
        self.assertEqual({r["mode"] for r in records.values()}, {"standalone", "embedded"})
        self.assertEqual(self.verify(fx, "v2")["result"], results.VERIFY_PASS)

    # -- AC-10 -----------------------------------------------------------------------------------
    def test_two_entries_share_reservations_and_generation_fence(self):
        """AC-10: the Runtime entry sees the CLI entry's held execution; the older generation cannot settle a result."""
        fx = self.fixture()
        out = fx.dispatch()
        runtime = HarnessDomain(fx.repo, entry="runtime")
        generation = runtime.acquire_generation()
        with self.assertRaises(ImplementVerifyRejection) as ctx:
            runtime.run("implement-dispatch", dict(taskId=fx.task_id, commandId="rt-d", portId="local-implementer",
                                                   worktree=str(fx.worktree), finalizationRef="RU-02", budget=budget(),
                                                   role="implementer", purpose="coding-implementer",
                                                   authorityRef=OWNER), generation=generation)
        self.assertEqual(ctx.exception.code, results.EXECUTION_WRITER_BUSY)
        with self.assertRaises(Fault) as fenced:
            self.run_local(fx, out["execution"]["executionRequestId"])
        self.assertEqual(fenced.exception.code, "WRITER_CONFLICT")
        self.assertEqual(fx.inst()["attempts"][-1]["status"], states.CREATED)

    def test_real_serve_stdio_and_cli_share_protection(self):
        """AC-10: the product serve-stdio process initiates implement dispatch and Verify through its Runtime actions and
        the standalone CLI works on the same product line: one reservation, one execution record and one recovery
        protection; the entry holding an older control generation is refused; a restarted serve-stdio only reads."""
        from implement_verify_stdio import LoopHost, StdioImplementerHost, launch_files
        fx = self.fixture()
        fx.set_registration([entry(agent_path=fx.agent.path), embedded_entry()])
        case = self.directory / "stdio"
        case.mkdir()
        launch_files(case, fx, EMBEDDED, fx.agent.path)
        answers = StdioImplementerHost(fx.generation)
        answers.domain = fx.domain
        hosts = []

        def serve(tag):
            host = LoopHost(case, answers, output=case / ("frames-%s.jsonl" % tag))
            hosts.append(host)
            host.initialize()
            host.activate()
            return host

        def dispatch_payload():
            return dict(taskId=fx.task_id, portId=EMBEDDED, finalizationRef=fx.finalization_ref(), budget=budget(),
                        expectedRuntimeVersion=fx.inst()["runtimeVersion"])
        try:
            # Runtime: dispatch and implement (candidate "bad"), then Verify -> FAIL, both initiated through the Runtime.
            host = serve("one")
            self.assertTrue(host.action("implement.dispatch")["enabled"])
            self.assertFalse(host.action("verify.run")["enabled"])
            answers.effect, answers.scenario = self.commit_effect(fx, "bad"), "completed"
            accepted, p = host.invoke("implement.dispatch", dispatch_payload())
            self.assertIn(accepted["status"], ("accepted", "running"))
            op = host.wait_operation(p["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "IMPLEMENT-COMPLETED"), op)
            first = next(iter(fx.state()["tasks"][fx.task_id]["implementVerify"]["executions"]))
            self.assertEqual(fx.state()["executionDescriptors"][first]["operationId"], p["operationId"])
            self.assertTrue(host.action("verify.run")["enabled"])
            accepted, p = host.invoke("verify.run", dict(taskId=fx.task_id, expectedRuntimeVersion=fx.inst()["runtimeVersion"]))
            op = host.wait_operation(p["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "VERIFY-FAIL"), op)
            self.assertEqual(fx.inst()["position"], "N-VERIFY-BUDGET-DECISION")
            # CLI: its generation predates serve-stdio, so it is refused; the record is the one serve-stdio wrote.
            with self.assertRaises(WorkflowRejection) as stale:
                fx.run("implement-remediate", commandId="r-stale", budgetFact="none")
            self.assertEqual(stale.exception.code, workflow_results.STALE_CONTROL_GENERATION)
            fx.generation = fx.domain.bind_entry()
            self.rejects(results.POSITION_NOT_APPLICABLE, self.verify, fx, "cli-v")
            fx.budget_fact("b1", "Budget Remains")
            fx.run("implement-remediate", commandId="r1", budgetFact="b1")
            host.close()
            # Runtime again (it takes the generation back): the remediation dispatch stops unconfirmed (J-06).
            host = serve("two")
            answers.effect, answers.scenario = self.commit_effect(fx, "good"), "stopping"
            accepted, p = host.invoke("implement.dispatch", dispatch_payload())
            op = host.wait_operation(p["operationId"])
            self.assertEqual(op["status"], "unknown", op)
            executions = fx.state()["tasks"][fx.task_id]["implementVerify"]["executions"]
            second = next(k for k in executions if k != first)
            self.assertEqual(executions[second]["settlement"]["reason"], results.STOP_UNCONFIRMED)
            self.assertEqual(answers.methods.count("host.execution.start"), 2)
            self.assertFalse(host.action("implement.dispatch")["enabled"])
            self.assertFalse(host.action("verify.run")["enabled"])
            host.invoke("implement.dispatch", dispatch_payload(), error="PRECONDITION_CONFLICT")
            host.close()
            state = fx.state()
            self.assertEqual(state["tasks"][fx.task_id]["workflowInstance"]["reservations"][second]["status"], "held")
            self.assertIn(second, state["executionReservations"])
            # CLI: stale again, then with a fresh generation the same stop-unconfirmed protection holds.
            with self.assertRaises(WorkflowRejection) as stale:
                fx.run("implement-assess", assessmentId="stale")
            self.assertEqual(stale.exception.code, workflow_results.STALE_CONTROL_GENERATION)
            fx.generation = fx.domain.bind_entry()
            self.assertEqual(fx.run("implement-assess", assessmentId="a1")["assessment"], "INDETERMINATE")
            self.rejects(results.POSITION_NOT_APPLICABLE, fx.dispatch, command_id="again", port_id=EMBEDDED)
            self.rejects(results.POSITION_NOT_APPLICABLE, self.verify, fx, "cli-v2")
            self.rejects(workflow_results.ILLEGAL_TRANSITION, fx.run, "recover", commandId="rc",
                         action="RESTART_CURRENT_NODE", assessmentId="a1")
            launcher = [sys.executable, str(Path(__file__).resolve().parents[1] / "hp.py")]
            completed = subprocess.run(launcher + ["implement", "run", "--repository", str(fx.repo), "--task-id", fx.task_id,
                                                   "--execution-id", second], capture_output=True, text=True)
            self.assertEqual((completed.returncode, json.loads(completed.stdout)["result"]),
                             (1, results.REGISTRY_ENTRY_MISSING))
            # A restarted serve-stdio only reads: nothing is started again.
            host = serve("three")
            self.assertFalse(host.action("implement.dispatch")["enabled"])
            host.close()
            self.assertEqual(answers.methods.count("host.execution.start"), 2)
            self.assertEqual(fx.state()["tasks"][fx.task_id]["implementVerify"]["executions"][second]["settlement"]["reason"],
                             results.STOP_UNCONFIRMED)
        finally:
            for host in hosts:
                host.close()

    def test_cli_commands_exit_codes(self):
        """AC-03 AC-10: the product CLI (hp.py) drives dispatch, run on feature-t3's execution layer and Verify with 0 / 1 / 2 exit codes."""
        fx = self.fixture()
        launcher = [sys.executable, str(Path(__file__).resolve().parents[1] / "hp.py")]
        repo = str(fx.repo)

        def cli(*argv):
            completed = subprocess.run(launcher + list(argv), capture_output=True, text=True)
            return completed.returncode, json.loads(completed.stdout) if completed.stdout.strip() else completed.stderr
        fx.agent.set(mode="commit", content="bad")
        code, doc = cli("implement", "dispatch", "--repository", repo, "--task-id", fx.task_id, "--command-id", "c1",
                        "--authority-ref", OWNER, "--port-id", "local-implementer", "--worktree", str(fx.worktree),
                        "--finalization-ref", "RU-02", "--budget", json.dumps(budget()))
        self.assertEqual((code, doc["result"]), (0, results.DISPATCHED), doc)
        execution = doc["execution"]["executionRequestId"]
        code, doc = cli("implement", "dispatch", "--repository", repo, "--task-id", fx.task_id, "--command-id", "c2",
                        "--authority-ref", OWNER, "--port-id", "local-implementer", "--worktree", str(fx.worktree),
                        "--finalization-ref", "RU-02", "--budget", json.dumps(budget()))
        self.assertEqual((code, doc["result"]), (1, results.EXECUTION_WRITER_BUSY))
        code, doc = cli("implement", "run", "--repository", repo, "--task-id", fx.task_id, "--execution-id", execution)
        self.assertEqual((code, doc["result"]), (0, results.IMPLEMENT_COMPLETED), doc)
        code, doc = cli("verify", "run", "--repository", repo, "--task-id", fx.task_id, "--command-id", "v1",
                        "--authority-ref", OWNER)
        self.assertEqual((code, doc["result"]), (0, results.VERIFY_FAIL), doc)
        code, doc = cli("workflow", "advance", "--repository", repo, "--task-id", fx.task_id, "--command-id", "x",
                        "--authority-ref", OWNER, "--edge", "E-I06")
        self.assertEqual((code, doc["result"]), (1, workflow_results.ILLEGAL_TRANSITION))
        code, doc = cli("verify", "run", "--repository", repo, "--task-id", fx.task_id, "--command-id", "v1",
                        "--authority-ref", OWNER)
        self.assertEqual((code, doc["result"]), (0, results.IDEMPOTENT_REPLAY))
        self.assertEqual(doc["verification"]["result"], "FAIL")
        other = self.fixture("cli-na", declared=[])
        code, doc = cli("config", "set", "implementer-ports", json.dumps([entry(agent_path=other.agent.path)]),
                        "--repository", str(other.repo), "--authority-ref", OWNER)
        self.assertEqual((code, doc["result"]), (0, results.REGISTRATION_CONFIGURED), doc)
        code, doc = cli("implement", "dispatch", "--repository", str(other.repo), "--task-id", other.task_id,
                        "--command-id", "c1", "--authority-ref", OWNER, "--port-id", "local-implementer",
                        "--worktree", str(other.worktree), "--finalization-ref", "RU-02", "--budget", json.dumps(budget()))
        code, doc = cli("implement", "run", "--repository", str(other.repo), "--task-id", other.task_id,
                        "--execution-id", doc["execution"]["executionRequestId"])
        code, doc = cli("verify", "run", "--repository", str(other.repo), "--task-id", other.task_id,
                        "--command-id", "v1", "--authority-ref", OWNER)
        self.assertEqual((code, doc["result"]), (0, results.VERIFY_NOT_APPLICABLE))
        broken = self.fixture("cli-broken", declared=[dict(id="unit", argv=["/nonexistent/check"], timeoutSeconds=5)])
        cli("implement", "dispatch", "--repository", str(broken.repo), "--task-id", broken.task_id, "--command-id", "c1",
            "--authority-ref", OWNER, "--port-id", "local-implementer", "--worktree", str(broken.worktree),
            "--finalization-ref", "RU-02", "--budget", json.dumps(budget()))
        execution = broken.state()["tasks"][broken.task_id]["implementVerify"]["executions"]
        cli("implement", "run", "--repository", str(broken.repo), "--task-id", broken.task_id, "--execution-id",
            next(iter(execution)))
        code, doc = cli("verify", "run", "--repository", str(broken.repo), "--task-id", broken.task_id,
                        "--command-id", "v1", "--authority-ref", OWNER)
        self.assertEqual((code, doc["result"]), (2, results.CHECK_EXECUTION_FAILED))

    def test_production_wiring_and_three_port_seams(self):
        """AC-05 AC-11: feature-t3's execution layer runs the implementer executor; build_port gives the port its purpose,
        rediscovers the embedded program identity on every call and binds standalone from the product-side registration."""
        from runtime.executions import production_executors
        self.assertIsInstance(production_executors()["coding-implementer"], executors.ImplementExecutor)
        fx = self.fixture()
        fx.set_registration([entry(agent_path=fx.agent.path), embedded_entry()])
        self.assertEqual(seams.finalization(fx.state(), fx.task_id)["candidate"]["sha256"], fx.frozen["sha256"])
        host = ImplementerHost(fx.generation)
        port, binding = self.build(fx, self.embedded_env(fx, host), EMBEDDED)
        self.assertEqual((type(port).__name__, port.purpose, port.mode), ("HostExecutionPort", "coding-implementer", "embedded"))
        first = asyncio.run(port.discover()).profile["programIdentity"]
        fx.agent.write("synthetic-agent 3.0")
        second = asyncio.run(port.discover()).profile["programIdentity"]
        self.assertEqual((first["version"], second["version"]), ("synthetic-agent 1.0", "synthetic-agent 3.0"))
        self.assertNotEqual(first["binaryDigest"], second["binaryDigest"])
        env = self.embedded_env(fx, ImplementerHost(fx.generation))
        del env.config["executionBindings"][EMBEDDED]["launcher"]
        with self.assertRaises(ExecutionError) as exc:
            asyncio.run(self.build(fx, env, EMBEDDED)[0].discover())
        self.assertEqual(exc.exception.code, "execution-port-identity-unverified")
        local, binding = self.build(fx, self.local_env(fx), "local-implementer")
        found = registration.resolve(fx.state(), "local-implementer")
        self.assertEqual((type(local).__name__, local.purpose, local.mode), ("ImplementerLocalExecutionPort", "coding-implementer",
                                                                             "standalone"))
        self.assertNotIn("applicability", found)
        self.assertEqual((binding["credentialRevision"], binding["configurationRevision"], binding["agent"]),
                         (found["credentialRevision"], found["configurationRevision"], found["agent"]))


class RegistrationAndChecks(unittest.TestCase):
    def test_registration_closed_set(self):
        """AC-05 AC-06: the product-side registration refuses programIdentity, withdrawn digests and out-of-range budgets."""
        state = {}
        good = entry(agent_path="/synthetic/agent")
        registration.set_registration(state, [good], OWNER)
        self.assertEqual(registration.resolve(state, "local-implementer")["agent"], "agent:claude-code")
        self.assertIsNone(registration.resolve(state, "local-implementer", "review"))
        bad = []
        with_program = copy.deepcopy(good)
        with_program["profile"]["programIdentity"] = dict(launcher="/x", binaryDigest="a" * 64, version="1")
        bad.append(with_program)
        withdrawn = copy.deepcopy(good)
        withdrawn["profile"]["digest"] = registration.WITHDRAWN_DIGESTS[0]
        bad.append(withdrawn)
        bad.append(dict(good, budget=dict(good["budget"], maxOutputBytes=16777217)))
        bad.append(dict(good, purpose="review"))
        bad.append(dict(good, approval_policy="expected-range-gate"))
        for value in bad:
            with self.subTest(value=value.get("purpose")), self.assertRaises(ImplementVerifyRejection):
                registration.set_registration({}, [value], OWNER)
        with self.assertRaises(ImplementVerifyRejection):
            registration.set_registration({}, [good, good], OWNER)
        self.assertEqual(len(state["configuration"]["history"]), 1)

    def test_check_declarations_and_prescribed_section(self):
        """AC-03: declarations are validated, revisioned with history, and the Definition section lists required checks."""
        state = {}
        first = __import__("domain.implement_verify.checks", fromlist=["x"])
        out = first.set_checks(state, [check("unit")], OWNER)
        self.assertEqual(out["revision"], 1)
        out = first.set_checks(state, [check("unit"), check("lint")], OWNER)
        self.assertEqual(out["revision"], 2)
        self.assertEqual(len(state["configuration"]["history"]), 2)
        for value in ([dict(id="Bad Id", argv=["x"], timeoutSeconds=1)], [dict(id="a", argv="x", timeoutSeconds=1)],
                      [dict(id="a", argv=["x"], timeoutSeconds=0)], [dict(id="a", argv=["x"], timeoutSeconds=1, shell=True)]):
            with self.subTest(value=value), self.assertRaises(ImplementVerifyRejection):
                first.set_checks({}, value, OWNER)
        text = b"# x\n\n## Extension: Prescribed Checks\n\nMaps to: Acceptance Criteria\n\n- `unit`\n- `lint`\n\n## Other\n- `ignored`\n"
        self.assertEqual(first.prescribed(text), ["unit", "lint"])
        self.assertEqual(first.prescribed(b"# x\n"), [])


if __name__ == "__main__":
    unittest.main()
