"""feature-t3 through a real serve-stdio process (AC-08, AC-09) plus production wiring checks (AC-09).

The Runtime runs the production Domain Core, dispatcher and execution layer over a synthetic product
line; the Host, the reviewer and the feature-t6 callback are explicitly synthetic (serve_definition).
"""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import definition_fixture as F
from domain.core import HarnessDomain
from domain.definition import gate, projection as definition_projection, results as R
from domain.workflow import projection as workflow_projection, states
from host_driver import Host, request_digest

APP = Path(__file__).resolve().parents[1]
OWNER = F.OWNER


class DefinitionHost(Host):
    def __init__(self, directory, env, output=None):
        directory = Path(directory)
        template = json.loads((directory / "host-template.json").read_text())
        command = [sys.executable, str(APP / "tests/serve_definition.py"), "serve-stdio",
                   "--launch-config", str(directory / "launch.json"), "--repository", template["repository"]]
        saved = dict(os.environ)
        os.environ.update(env)
        try:
            super().__init__(directory, output=output, command=command)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def activate(self):
        result = self.call("runtime.scope.open", dict(binding=self.template["binding"]))
        methods = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                   "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]
        self.grants = [dict(ref=dict(id="grant:%s:%d" % (cap["id"], i), revision="1"), installationId=self.context["installationId"],
                            instanceId=self.context["instanceId"], scopeRef=result["scopeRef"], resourceHandle="resource:one",
                            capability=cap["id"], operation=method, executionRef=None, bundleDigest="b" * 64,
                            expiresAt="2099-01-01T00:00:00Z", status="active", purpose="Definition tests")
                       for cap in self.template["capabilities"] for i, method in enumerate(methods)]
        self.call("runtime.scope.authorize", dict(scopeRef=result["scopeRef"], grantRefs=self.refs()))
        return result["scopeRef"]

    def action(self, action_id):
        page = self.call("runtime.snapshot.open", dict(scopeRef=self.template["scopeRef"]))
        return next(a for a in page["actions"] if a["actionId"] == action_id)

    def invoke(self, action, payload, error=None):
        p = self.mutation("runtime.action.invoke", scopeRef=self.template["scopeRef"], actionId=action["actionId"],
                          objectRef=action["objectRef"], expectedRevision=action["expectedRevision"],
                          candidateRef=action["candidateRef"], grantRefs=self.refs(), payload=payload, decisionRef=None)
        for _ in range(2):
            decision = dict(decisionRef="decision:" + p["operationId"], scopeRef=p["scopeRef"], domainOperationId=p["operationId"],
                            method="runtime.action.invoke", requestDigest=p["requestDigest"], actionId=p["actionId"],
                            objectRef=p["objectRef"], candidateRef=p["candidateRef"], expectedRevision=p["expectedRevision"],
                            evidence=[], actorRef="human:synthetic", source="host-trusted-ui",
                            recordedAt="2026-09-23T00:00:00Z", status="valid")
            self.decisions[decision["decisionRef"]] = decision
            p["decisionRef"] = decision["decisionRef"]
            p["requestDigest"] = request_digest("runtime.action.invoke", p)
        return self.call("runtime.action.invoke", p, error=error), p


class DefinitionRuntime(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("t3-rt-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=False)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t3-runtime-")
            self.directory = Path(self.temp.name)
        self.hosts = []

    def tearDown(self):
        for h in self.hosts:
            h.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def fixture(self, **kw):
        self.fx = F.create(self.directory / "case", **kw)
        F.runtime_files(self.directory / "case", self.fx)
        self.log = self.directory / "reviewer.log"
        self.gate = self.directory / "gate"

    def start(self, gated=False, verdict="PASS"):
        env = dict(HP_T3_LOG=str(self.log), HP_T3_VERDICT=verdict)
        if gated:
            env["HP_T3_GATE"] = str(self.gate)
        host = DefinitionHost(self.directory / "case", env, output=self.directory / ("frames-%d.jsonl" % len(self.hosts)))
        self.hosts.append(host)
        host.initialize()
        host.activate()
        return host

    def cli_domain(self):
        domain = F.TestHarnessDomain(self.fx["repo"], entry="cli")
        return domain, domain.bind_entry()

    def state(self):
        return HarnessDomain(self.fx["repo"], entry="cli").store.read()

    def wait_operation(self, host, operation_id, statuses, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            op = host.call("runtime.operation.get", dict(scopeRef=host.template["scopeRef"], operationId=operation_id))
            if op["status"] in statuses:
                return op
            time.sleep(0.1)
        self.fail("operation did not reach %s: %s" % (statuses, op))

    def submit_payload(self):
        commit = F.commit_candidate(self.fx["worktree"], F.definition_text())
        return dict(taskId="feature-t0", commit=commit, author=F.author(self.fx["head"]), expectedRuntimeVersion="1")

    # -- AC-08 ---------------------------------------------------------------------------------------
    def test_projection_derives_definition_actions_from_the_position(self):
        """AC-08: only legal Definition actions are enabled; a disabled one is refused; forged ids are refused."""
        self.fixture()
        host = self.start()
        actions = {a: host.action(a) for a in definition_projection.ACTIONS}
        self.assertTrue(actions["definition.submit"]["enabled"])
        self.assertFalse(actions["definition.dispatch"]["enabled"])
        self.assertFalse(actions["definition.decide"]["enabled"])
        self.assertTrue(all(a["requiresHumanDecision"] for a in actions.values()))
        host.invoke(actions["definition.dispatch"], dict(taskId="feature-t0", expectedRuntimeVersion="1"), error="PRECONDITION_CONFLICT")
        forged = dict(actions["definition.submit"], actionId="definition.freeze")
        host.invoke(forged, dict(taskId="feature-t0"), error="PRECONDITION_CONFLICT")

    def test_two_entries_record_the_same_candidate_and_route(self):
        """AC-08: the Runtime action and the standalone command produce the same Definition result shape."""
        self.fixture()
        host = self.start()
        payload = self.submit_payload()
        op, _p = host.invoke(host.action("definition.submit"), payload)
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "CANDIDATE-RECORDED"))
        chunk = host.call("runtime.resource.read", dict(scopeRef=host.template["scopeRef"], evidence=op["resultRef"],
                                                        grantRefs=host.refs(), offset=0, length=op["resultRef"]["bytes"]))
        runtime_outcome = json.loads(base64.b64decode(chunk["dataBase64"]))
        # Standalone entry on a second synthetic product line with the same input.
        other = F.create(self.directory / "other")
        domain = F.TestHarnessDomain(other["repo"], entry="cli")
        generation = domain.bind_entry()
        commit = F.commit_candidate(other["worktree"], F.definition_text())
        cli_outcome = domain.run_definition("submit", dict(taskId="feature-t0", commandId="cli-1", authorityRef=OWNER,
                                                           commit=commit, author=F.author(other["head"])), generation=generation)
        self.assertEqual(set(runtime_outcome), set(cli_outcome))
        self.assertEqual(set(runtime_outcome["candidate"]), set(cli_outcome["candidate"]))
        for key in ("result", "position", "condition", "runtimeVersion", "route"):
            if key == "route":
                self.assertEqual({k: v for k, v in runtime_outcome[key].items() if k != "switchFact"},
                                 {k: v for k, v in cli_outcome[key].items() if k != "switchFact"})
            else:
                self.assertEqual(runtime_outcome[key], cli_outcome[key])
        self.assertEqual(runtime_outcome["candidate"]["sha256"], cli_outcome["candidate"]["sha256"])
        # The same legal Definition action set on both sides, and the Runtime projection shows exactly it.
        legal_runtime = definition_projection.legal(self.state(), "feature-t0")
        legal_cli = definition_projection.legal(domain.store.read(), "feature-t0")
        self.assertEqual(legal_runtime, legal_cli)
        enabled = {a for a in definition_projection.ACTIONS if host.action(a)["enabled"]}
        self.assertEqual(enabled, legal_runtime)

    def test_generic_decide_projection_is_narrowed_at_the_authorization_gate(self):
        """AC-08: at the authorization gate workflow.decide is disabled and definition.decide carries the freeze."""
        self.fixture()
        host = self.start()
        host.invoke(host.action("definition.submit"), self.submit_payload())
        decide = host.action(workflow_projection.ACTION_DECIDE)
        self.assertFalse(decide["enabled"])
        self.assertEqual(decide["disabledCode"], workflow_projection.NO_GATE)
        definition_decide = host.action("definition.decide")
        self.assertTrue(definition_decide["enabled"])
        version = self.state()["tasks"]["feature-t0"]["workflowInstance"]["runtimeVersion"]
        op, _p = host.invoke(definition_decide, dict(taskId="feature-t0", decision=gate.AUTHORIZE, decisionText="定稿 feature-t0",
                                                     expectedRuntimeVersion=version))
        self.assertEqual(op["status"], "running")
        done = self.wait_operation(host, op["operationId"], ("succeeded", "failed", "unknown"))
        self.assertEqual((done["status"], done["resultCode"]), ("succeeded", "DEFINITION-FROZEN"))
        self.assertEqual(self.state()["tasks"]["feature-t0"]["workflowInstance"]["position"], "N-DEF-FROZEN")
        self.assertTrue((self.fx["worktree"] / "tasks/feature-t0/rulings/RU-02-definition-finalization.md").is_file())

    # -- AC-09 ---------------------------------------------------------------------------------------
    def test_review_runs_off_the_transaction_and_the_runtime_keeps_answering(self):
        """AC-09: while a review executes, operation.get and snapshot.open answer; attempt goes CREATED, RUNNING, COMPLETED."""
        self.fixture(definition_review=True)
        host = self.start(gated=True)
        host.invoke(host.action("definition.submit"), self.submit_payload())
        version = self.state()["tasks"]["feature-t0"]["workflowInstance"]["runtimeVersion"]
        op, _p = host.invoke(host.action("definition.dispatch"), dict(taskId="feature-t0", expectedRuntimeVersion=version))
        self.assertEqual(op["status"], "running")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not self.log.exists():
            time.sleep(0.05)
        self.assertTrue(self.log.exists())
        # The review is held by the gate; the Runtime still answers queries and snapshots.
        started = time.monotonic()
        running = host.call("runtime.operation.get", dict(scopeRef=host.template["scopeRef"], operationId=op["operationId"]))
        page = host.call("runtime.snapshot.open", dict(scopeRef=host.template["scopeRef"]))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(running["status"], "running")
        self.assertTrue(page["actions"])
        attempt = self.state()["tasks"]["feature-t0"]["workflowInstance"]["attempts"][-1]
        self.assertEqual(attempt["status"], "RUNNING")
        self.gate.write_text("go\n")
        done = self.wait_operation(host, op["operationId"], ("succeeded", "failed", "unknown"))
        self.assertEqual((done["status"], done["resultCode"]), ("succeeded", "VERDICT-RECORDED"))
        inst = self.state()["tasks"]["feature-t0"]["workflowInstance"]
        attempt = inst["attempts"][-1]
        self.assertEqual(attempt["status"], "COMPLETED")
        self.assertTrue(attempt["startedAt"] and attempt["settledAt"])
        self.assertEqual(inst["position"], gate.AUTH_GATE)

    def test_restart_queries_an_unsettled_review_and_never_executes_it_again(self):
        """AC-09: a Runtime killed mid-review restarts and only queries the same request."""
        self.fixture(definition_review=True)
        host = self.start(gated=True)
        host.invoke(host.action("definition.submit"), self.submit_payload())
        version = self.state()["tasks"]["feature-t0"]["workflowInstance"]["runtimeVersion"]
        op, _p = host.invoke(host.action("definition.dispatch"), dict(taskId="feature-t0", expectedRuntimeVersion=version))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not self.log.exists():
            time.sleep(0.05)
        host.process.kill()
        host.process.wait(timeout=10)
        self.hosts.remove(host)
        host.close()
        second = self.start(gated=True)
        deadline = time.monotonic() + 20
        events = []
        while time.monotonic() < deadline:
            events = [json.loads(line) for line in self.log.read_text().splitlines()]
            if any(e["event"] == "query" for e in events):
                break
            time.sleep(0.1)
        self.assertEqual([e["event"] for e in events], ["execute", "query"])
        done = self.wait_operation(second, op["operationId"], ("unknown", "failed", "succeeded"))
        self.assertEqual(done["status"], "unknown")
        inst = self.state()["tasks"]["feature-t0"]["workflowInstance"]
        self.assertEqual((inst["position"], inst["condition"]), ("N-DEF-REVIEWER", states.RECOVERY_REQUIRED))
        self.assertEqual(inst["reservations"]["review:feature-t0:r1"]["status"], "held")

    def test_runtime_review_through_the_real_callback(self):
        """AC-09: serve-stdio dispatch through the production factory and feature-t6's real callback (embedded entry)."""
        self.fixture(definition_review=True, registry_doc=F.live_registry_copy(standalone=False), author_vendor=True)
        env = dict(HP_T3_LOG=str(self.log), HP_T3_VERDICT="PASS", HP_T3_AUTHORIZER="REAL")
        host = DefinitionHost(self.directory / "case", env, output=self.directory / "frames-real.jsonl")
        self.hosts.append(host)
        host.initialize()
        host.activate()
        host.invoke(host.action("definition.submit"), self.submit_payload())
        version = self.state()["tasks"]["feature-t0"]["workflowInstance"]["runtimeVersion"]
        op, _p = host.invoke(host.action("definition.formal-authorize"), dict(taskId="feature-t0", maxCalls=1,
                                                                              expectedRuntimeVersion=version))
        self.assertEqual(op["status"], "succeeded", op)
        version = self.state()["tasks"]["feature-t0"]["workflowInstance"]["runtimeVersion"]
        op, _p = host.invoke(host.action("definition.dispatch"), dict(taskId="feature-t0", expectedRuntimeVersion=version))
        done = self.wait_operation(host, op["operationId"], ("succeeded", "failed", "unknown"))
        self.assertEqual((done["status"], done["resultCode"]), ("succeeded", "VERDICT-RECORDED"), done)
        inst = self.state()["tasks"]["feature-t0"]["workflowInstance"]
        policy = [f for f in inst["facts"].values() if f["kind"] == "policy-decision"]
        self.assertTrue(policy and policy[-1]["payload"]["conclusion"] == "ALLOW")
        self.assertEqual(policy[-1]["producer"], "policy-gate")
        self.assertEqual(inst["position"], gate.AUTH_GATE)
        self.assertEqual(inst["attempts"][-1]["status"], "COMPLETED")

    def test_production_wiring_uses_the_feature_t6_callback_and_no_test_double(self):
        """AC-09: production executors build ports through build_port with the feature-t6 callback factory."""
        import inspect
        from runtime import executions
        from runtime.dispatcher import Dispatcher
        from domain.definition import dispatch
        producers = executions.production_executors()
        review = producers["review"]
        self.assertIs(review.port_factory, executions.build_port)
        self.assertIs(review.runner, dispatch.channel_review_runner)
        self.assertIs(inspect.signature(executions.build_port).parameters["authorizer"].default, executions.production_authorizer)
        self.assertIsNone(Dispatcher.execution_executors(object.__new__(Dispatcher)))
        # feature-t6 is integrated: the production factory is its execution_authorizer, bound by keyword context.
        from domain.policy import authorize as policy_authorize
        self.assertTrue(callable(executions.production_authorizer(object(), "feature-t0", "review-release", "embedded",
                                                                  lambda: "1", context=lambda: {})))
        self.assertIn("context", inspect.signature(policy_authorize.execution_authorizer).parameters)
        self.assertEqual(executions.PORT_ENTRY, {"runtime": "embedded", "cli": "standalone"})
        # No production module imports a test double.
        for path in list((APP / "domain").rglob("*.py")) + list((APP / "runtime").glob("*.py")) + list((APP / "cli").glob("*.py")):
            text = path.read_text()
            self.assertNotIn("definition_fixture", text, path)
            self.assertNotIn("synthetic_authorizer", text, path)


if __name__ == "__main__":
    unittest.main()
