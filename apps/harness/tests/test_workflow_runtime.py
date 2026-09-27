"""AC-02 / AC-07: the two entries drive one Domain Core through a real serve-stdio process.

The Runtime path here is the production composition: the same HarnessDomain the product entrypoint
installs, over a synthetic product line. Host and Human decisions are explicitly synthetic inputs.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.core import COMMANDS, HarnessDomain, open_domain
from domain.definition import projection as definition_projection
from domain.implement_verify import projection as implement_verify_projection
from domain.workflow import projection, results, states
from host_driver import Host, request_digest
from runtime.main import NO_REPOSITORY, domain_for
from workflow_fixture import create

APP = Path(__file__).resolve().parents[1]
PY = sys.executable
OWNER = "owner:synthetic"


class WorkflowHost(Host):
    """Host driver bound to the workflow capability of the production Domain Core."""

    def __init__(self, directory, output=None):
        directory = Path(directory)
        template = json.loads((directory / "host-template.json").read_text())
        command = [sys.executable, str(APP / "tests/serve_workflow.py"), "serve-stdio",
                   "--launch-config", str(directory / "launch.json"), "--repository", template["repository"]]
        super().__init__(directory, output=output, command=command)

    def activate(self):
        result = self.call("runtime.scope.open", dict(binding=self.template["binding"]))
        methods = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                   "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]
        self.grants = [dict(ref=dict(id="grant:%s:%d" % (capability["id"], i), revision="1"),
                            installationId=self.context["installationId"], instanceId=self.context["instanceId"],
                            scopeRef=result["scopeRef"], resourceHandle="resource:one", capability=capability["id"],
                            operation=method, executionRef=None, bundleDigest="b" * 64,
                            expiresAt="2099-01-01T00:00:00Z", status="active", purpose="Workflow tests")
                       for capability in self.template["capabilities"] for i, method in enumerate(methods)]
        self.call("runtime.scope.authorize", dict(scopeRef=result["scopeRef"], grantRefs=self.refs()))
        return result["scopeRef"]

    def action_params(self, action, payload, **overrides):
        p = dict(scopeRef=self.template["scopeRef"], actionId=action["actionId"], objectRef=action["objectRef"],
                 expectedRevision=action["expectedRevision"], candidateRef=action["candidateRef"],
                 grantRefs=self.refs(), payload=payload, decisionRef=None)
        p.update(overrides)
        return self.mutation("runtime.action.invoke", **p)

    def decide(self, p, **overrides):
        decision = dict(decisionRef="decision:" + p["operationId"], scopeRef=p["scopeRef"],
                        domainOperationId=p["operationId"], method="runtime.action.invoke",
                        requestDigest=p["requestDigest"], actionId=p["actionId"], objectRef=p["objectRef"],
                        candidateRef=p["candidateRef"], expectedRevision=p["expectedRevision"], evidence=[],
                        actorRef="human:synthetic", source="host-trusted-ui", recordedAt="2026-09-22T00:00:00Z",
                        status="valid")
        decision.update(overrides)
        self.decisions[decision["decisionRef"]] = decision
        return decision["decisionRef"]

    def decided(self, action, payload, **overrides):
        p = self.action_params(action, payload, **overrides)
        p["decisionRef"] = self.decide(p)
        p["requestDigest"] = request_digest("runtime.action.invoke", p)
        p["decisionRef"] = self.decide(p)
        return p


class RuntimeWorkflow(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t2-runtime-")
            self.directory = Path(self.temp.name) / "case"
        self.template = create(self.directory)
        self.repo = Path(self.template["repository"])
        self.hosts = []

    def tearDown(self):
        for h in self.hosts:
            h.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def start(self):
        h = WorkflowHost(self.directory, output=self.directory / ("frames-%d.jsonl" % len(self.hosts)))
        self.hosts.append(h)
        return h

    def active(self, host):
        host.initialize()
        return host.activate()

    def domain(self, entry="cli"):
        return HarnessDomain(self.repo, entry=entry)

    def cli(self, *args):
        proc = subprocess.run([PY, "-B", str(APP / "hp.py"), *args], capture_output=True, text=True, cwd=APP)
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr

    def walk_to_gate(self, domain, generation):
        """Drive the definition lane to the Definition escalation gate, where the generic decide stays legal.

        feature-t3 moved Authorize & Freeze to the Definition entry (it needs a finalization ruling), so the
        generic-decision cases here use the escalation gate's Continue instead.
        """
        steps = [("condition", dict(condition=states.RESULT_RECORDED)), ("advance", dict(edgeId="E-D01")),
                 ("advance", dict(edgeId="E-D02"))]
        for edge in ("E-D03", "E-D05", "E-D06", "E-D08"):
            steps += [("condition", dict(condition=states.EXECUTING)), ("condition", dict(condition=states.RESULT_RECORDED)),
                      ("advance", dict(edgeId=edge))]
        for n, (name, payload) in enumerate(steps):
            domain.run(name, dict(taskId="feature-t0", authorityRef=OWNER, commandId="g%d" % n, **payload), generation=generation)
        # feature-t5 narrows the generic commands at the budget node: SYNTHETIC direct walk (test only), then the gate.
        import guarded_walk
        guarded_walk.settle_and_advance(domain, generation, "feature-t0", "g-e-d10", "E-D10", OWNER)
        domain.run("condition", dict(taskId="feature-t0", authorityRef=OWNER, commandId="g-await",
                                     condition=states.AWAITING_HUMAN_ACTION), generation=generation)

    # -- AC-02 ----------------------------------------------------------------------------------
    def test_projection_is_read_only_and_derives_the_legal_action_set(self):
        """AC-02: the snapshot projects Workflow state and enables an action only where the state allows it."""
        host = self.start()
        scope = self.active(host)
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        objects = {o["objectRef"] for o in page["objects"]}
        self.assertIn(projection.WORKFLOW_OBJECT, objects)
        self.assertIn("task:feature-t0", objects)
        actions = {a["actionId"]: a for a in page["actions"]}
        # feature-t3, feature-t4, feature-t5 and feature-t7 add their own capabilities' actions (each update authorized by the coordinator).
        from domain.budget import projection as budget_projection
        from domain.publish import projection as publish_projection
        from domain.validation import projection as validation_projection
        self.assertEqual(set(actions) - set(definition_projection.ACTIONS) - set(implement_verify_projection.ACTIONS)
                         - set(budget_projection.ACTIONS) - set(validation_projection.ACTIONS) - set(publish_projection.ACTIONS),
                         {"task.accept", projection.ACTION_DECIDE, projection.ACTION_CLOSE})
        # OD-425: decide is the capability document itself, close is its definitions entry.
        self.assertEqual(actions[projection.ACTION_DECIDE]["payloadSchemaDigest"], projection.capability()["schemaDigest"])
        self.assertEqual(actions[projection.ACTION_CLOSE]["payloadSchemaDigest"],
                         projection.DOCUMENT.payload_digest(projection.ACTION_CLOSE))
        self.assertTrue(all(a["requiresHumanDecision"] for a in actions.values()))
        # The task waits at a Human Action, not at a Human Gate, so no decision is legal yet.
        self.assertFalse(actions[projection.ACTION_DECIDE]["enabled"])
        self.assertEqual(actions[projection.ACTION_DECIDE]["disabledCode"], projection.NO_GATE)
        self.assertTrue(actions[projection.ACTION_CLOSE]["enabled"])

    def test_two_entries_reach_the_same_state_and_write_the_same_commit_shape(self):
        """AC-02: the standalone entry and the Runtime action drive one Domain Core to the same result."""
        domain = self.domain()
        generation = domain.bind_entry()
        self.walk_to_gate(domain, generation)
        before = domain.status("feature-t0")["tasks"][0]
        self.assertEqual([d["decision"] for d in before["decisions"]], ["Continue", "Close Task"])
        host = self.start()
        scope = self.active(host)
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        action = next(a for a in page["actions"] if a["actionId"] == projection.ACTION_DECIDE)
        self.assertTrue(action["enabled"])
        payload = dict(taskId="feature-t0", decision="Continue",
                       expectedRuntimeVersion=before["runtimeVersion"])
        p = host.decided(action, payload)
        op = host.call("runtime.action.invoke", p)
        self.assertEqual(op["status"], "succeeded")
        self.assertEqual(op["resultCode"], "ADVANCED")
        after = open_domain(self.repo).status("feature-t0")["tasks"][0]
        self.assertEqual(after["position"], "N-DEF-CONTINUE")
        chunk = host.call("runtime.resource.read", dict(scopeRef=scope, evidence=op["resultRef"],
                                                        grantRefs=host.refs(), offset=0,
                                                        length=op["resultRef"]["bytes"]))
        outcome = json.loads(base64.b64decode(chunk["dataBase64"]))
        self.assertEqual(outcome["commit"]["transitionKind"], states.POSITION_ADVANCE)
        self.assertEqual(outcome["commit"]["selectedEdge"], "E-D12")
        # The Host decisionRef already names a decision; it is recorded once, not as decision:decision:... (KB-298).
        self.assertEqual(outcome["commit"]["authorityRef"], p["decisionRef"])
        # The same command through the standalone entry produces the same record shape.
        keys = set(outcome["commit"])
        cli_domain = self.domain()
        cli_generation = cli_domain.bind_entry()
        cli_outcome = cli_domain.run("advance", dict(taskId="feature-t0", authorityRef=OWNER, commandId="c-cli",
                                                     edgeId="E-D15"), generation=cli_generation)
        self.assertEqual(set(cli_outcome["commit"]), keys)
        self.assertEqual(cli_outcome["commit"]["transitionKind"], states.POSITION_ADVANCE)

    def test_runtime_entry_is_fenced_out_by_a_newer_control_generation(self):
        """AC-02: after the standalone entry takes the control generation the Runtime connection is stale."""
        host = self.start()
        scope = self.active(host)
        standalone = self.domain()
        standalone.bind_entry()
        error = host.call("runtime.snapshot.open", dict(scopeRef=scope), error="WRITER_CONFLICT")
        self.assertEqual(error["data"]["recovery"], "reconnect")

    def test_projection_cannot_widen_authority(self):
        """AC-02: a forged action, a stale binding and an out-of-date Runtime Version are refused."""
        domain = self.domain()
        generation = domain.bind_entry()
        self.walk_to_gate(domain, generation)
        version = domain.status("feature-t0")["tasks"][0]["runtimeVersion"]
        host = self.start()
        scope = self.active(host)
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        action = next(a for a in page["actions"] if a["actionId"] == projection.ACTION_DECIDE)
        forged = dict(action, actionId="workflow.authorize")
        host.call("runtime.action.invoke", host.decided(forged, dict(taskId="feature-t0", decision="Continue",
                                                                     expectedRuntimeVersion=version)),
                  error="PRECONDITION_CONFLICT")
        stale_binding = dict(action, expectedRevision="99")
        host.call("runtime.action.invoke", host.decided(stale_binding, dict(taskId="feature-t0",
                                                                            decision="Continue",
                                                                            expectedRuntimeVersion=version)),
                  error="PRECONDITION_CONFLICT")
        host.call("runtime.action.invoke", host.action_params(action, dict(taskId="feature-t0",
                                                                          decision="Continue",
                                                                          expectedRuntimeVersion=version)),
                  error="PERMISSION_DENIED")
        stale = host.decided(action, dict(taskId="feature-t0", decision="Continue", expectedRuntimeVersion="1"))
        op = host.call("runtime.action.invoke", stale)
        self.assertEqual(op["status"], "failed")
        self.assertEqual(op["resultCode"], "VERSION-CONFLICT")
        self.assertEqual(open_domain(self.repo).status("feature-t0")["tasks"][0]["position"], "N-DEF-ESCALATION-GATE")

    # -- AC-05 through the Runtime -------------------------------------------------------------
    def test_close_through_the_runtime_and_a_disabled_action_cannot_be_invoked(self):
        """AC-05: a disabled projected action cannot be invoked at all, and the Runtime closes a live task."""
        host = self.start()
        scope = self.active(host)
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        decide = next(a for a in page["actions"] if a["actionId"] == projection.ACTION_DECIDE)
        version = open_domain(self.repo).status("feature-t0")["tasks"][0]["runtimeVersion"]
        self.assertFalse(decide["enabled"])
        host.call("runtime.action.invoke", host.decided(decide, dict(taskId="feature-t0",
                                                                     decision="Authorize & Freeze",
                                                                     expectedRuntimeVersion=version)),
                  error="PRECONDITION_CONFLICT")
        close = next(a for a in page["actions"] if a["actionId"] == projection.ACTION_CLOSE)
        op = host.call("runtime.action.invoke", host.decided(close, dict(taskId="feature-t0",
                                                                         reasonCategory="human-initiated",
                                                                         expectedRuntimeVersion=version)))
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "FINALIZED"))
        facts = open_domain(self.repo).status("feature-t0")["tasks"][0]
        self.assertEqual((facts["lifecycle"], facts["condition"]), (states.CLOSED, states.RESULT_RECORDED))
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        close = next(a for a in page["actions"] if a["actionId"] == projection.ACTION_CLOSE)
        self.assertFalse(close["enabled"])
        self.assertEqual(close["disabledCode"], projection.NO_ACTIVE)

    # -- AC-07 ----------------------------------------------------------------------------------
    def test_operation_identity_replays_and_a_changed_digest_conflicts(self):
        """AC-07: the same operation replays its recorded result; the same key with another digest conflicts."""
        host = self.start()
        scope = self.active(host)
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        close = next(a for a in page["actions"] if a["actionId"] == projection.ACTION_CLOSE)
        version = open_domain(self.repo).status("feature-t0")["tasks"][0]["runtimeVersion"]
        p = host.decided(close, dict(taskId="feature-t0", reasonCategory="human-initiated",
                                     expectedRuntimeVersion=version))
        first = host.call("runtime.action.invoke", p)
        replay = host.call("runtime.action.invoke", p)
        self.assertEqual(first, replay)
        fetched = host.call("runtime.operation.get", dict(scopeRef=scope, operationId=p["operationId"]))
        self.assertEqual(fetched["resultCode"], "FINALIZED")
        conflicting = dict(p, payload=dict(taskId="feature-t0", reasonCategory="blocked-escalation",
                                           expectedRuntimeVersion=version))
        conflicting["requestDigest"] = request_digest("runtime.action.invoke", conflicting)
        host.call("runtime.action.invoke", conflicting, error="IDEMPOTENCY_CONFLICT")
        commits = open_domain(self.repo).status("feature-t0")["tasks"][0]["commits"]
        self.assertEqual(commits, 1)

    def test_production_entrypoint_binds_the_domain_core_and_reports_a_missing_repository(self):
        """AC-07: serve-stdio installs the production Domain Core; without a repository it is degraded, with a reason."""
        degraded = domain_for(None)
        self.assertFalse(degraded.available)
        self.assertEqual(degraded.unavailable_reason, NO_REPOSITORY)
        bound = domain_for(self.repo)
        self.assertTrue(bound.available)
        self.assertIsInstance(bound, HarnessDomain)
        self.assertEqual({c["id"] for c in bound.capabilities},
                         {"harness.task-acceptance", "harness.workflow", "harness.definition", "harness.implement-verify",
                          "harness.autonomous-budget", "harness.validate-change", "harness.publish"})
        host = self.start()
        host.initialize()
        health = host.call("runtime.health")
        self.assertEqual((health["health"], health["reason"]), ("ready", ""))

    def test_standalone_cli_runs_the_same_command_function(self):
        """AC-02: the CLI subcommands map onto apply_command, the one function both entries call."""
        code, document, stderr = self.cli("workflow", "status", "--repository", str(self.repo))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(document["tasks"][0]["position"], "N-DEF-HUMAN")
        code, document, stderr = self.cli("workflow", "close", "--repository", str(self.repo), "--task-id",
                                          "feature-t0", "--authority-ref", OWNER, "--command-id", "cli-1",
                                          "--reason-category", "human-initiated")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(document["result"], results.FINALIZED)
        self.assertEqual(document["entry"], "cli")
        code, document, stderr = self.cli("workflow", "close", "--repository", str(self.repo), "--task-id",
                                          "feature-t0", "--authority-ref", OWNER, "--command-id", "cli-2",
                                          "--reason-category", "human-initiated")
        self.assertEqual(code, 1, stderr)
        self.assertEqual(document["result"], results.TASK_TERMINAL)
        self.assertIn("close", COMMANDS)


if __name__ == "__main__":
    unittest.main()
