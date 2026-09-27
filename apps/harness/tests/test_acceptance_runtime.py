"""AC-07: the Runtime action path drives the same acceptance domain through a real serve-stdio process."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acceptance_fixture import create
from domain.acceptance import results
from domain.acceptance.accept import accept_task
from domain.acceptance.results import Rejection
from domain.acceptance.schema import DIGEST, SCHEMA_ID
from domain.store import RuntimeStore
from host_driver import Host, request_digest
from product_line import git

APP = Path(__file__).resolve().parents[1]

class AcceptanceHost(Host):
    """Host driver bound to the acceptance capability; grants and payload differ from the feature-t16 sample."""
    def __init__(self, directory, output=None, kill_at_phase=None):
        directory = Path(directory)
        template = json.loads((directory / "host-template.json").read_text())
        command = [sys.executable, str(APP / "tests/serve_acceptance.py"), "serve-stdio", "--launch-config", str(directory / "launch.json"),
                   "--repository", template["repository"]]
        if kill_at_phase:
            command += ["--kill-at-phase", kill_at_phase]
        super().__init__(directory, output=output, command=command)

    def activate(self):
        result = self.call("runtime.scope.open", dict(binding=self.template["binding"]))
        methods = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                   "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]
        self.grants = [dict(ref=dict(id="grant:" + str(i), revision="1"), installationId=self.context["installationId"],
                            instanceId=self.context["instanceId"], scopeRef=result["scopeRef"], resourceHandle="resource:one",
                            capability=self.template["capability"]["id"], operation=method, executionRef=None, bundleDigest="b" * 64,
                            expiresAt="2099-01-01T00:00:00Z", status="active", purpose="Acceptance tests") for i, method in enumerate(methods)]
        self.call("runtime.scope.authorize", dict(scopeRef=result["scopeRef"], grantRefs=self.refs()))
        self.refresh_action()
        return result["scopeRef"]

    def refresh_action(self):
        """Bind to task.accept as currently projected. Its expectedRevision is the revision of the task list,
        which advances when an acceptance adds a row (KB-296), so a Host re-reads it after a settled operation."""
        page = self.call("runtime.snapshot.open", dict(scopeRef=self.template["scopeRef"]))
        self.action = next(a for a in page["actions"] if a["actionId"] == self.template["action"]["actionId"])

    def payload(self, **overrides):
        payload = dict(taskType="feature", taskId="feature-t0", baseRef="main", worktreeRoot=self.template["worktreeRoot"])
        payload.update(overrides)
        return payload

    def invoke_params(self, **overrides):
        action = self.action
        p = dict(scopeRef=self.template["scopeRef"], actionId=action["actionId"], objectRef=action["objectRef"],
                 expectedRevision=action["expectedRevision"], candidateRef=action["candidateRef"], grantRefs=self.refs(),
                 payload=self.payload(), decisionRef=None)
        p.update(overrides)
        return self.mutation("runtime.action.invoke", **p)

    def decide(self, p, **overrides):
        decision = dict(decisionRef="decision:" + p["operationId"], scopeRef=p["scopeRef"], domainOperationId=p["operationId"],
                        method="runtime.action.invoke", requestDigest=p["requestDigest"], actionId=p["actionId"], objectRef=p["objectRef"],
                        candidateRef=p["candidateRef"], expectedRevision=p["expectedRevision"], evidence=[], actorRef="human:synthetic",
                        source="host-trusted-ui", recordedAt="2026-09-22T00:00:00Z", status="valid")
        decision.update(overrides)
        self.decisions[decision["decisionRef"]] = decision
        return decision["decisionRef"]

    def decided_invoke(self, **overrides):
        p = self.invoke_params(**overrides)
        p["decisionRef"] = self.decide(p)
        p["requestDigest"] = request_digest("runtime.action.invoke", p)
        p["decisionRef"] = self.decide(p)
        return p

class RuntimeAcceptance(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t0-runtime-")
            self.directory = Path(self.temp.name) / "case"
        self.template = create(self.directory)
        self.repo = Path(self.template["repository"])
        self.hosts = []
        self.h = self.start()

    def start(self, **kw):
        h = AcceptanceHost(self.directory, output=self.directory / ("frames-" + str(len(self.hosts)) + ".jsonl"), **kw)
        self.hosts.append(h)
        return h

    def tearDown(self):
        for h in self.hosts:
            h.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def store(self):
        return RuntimeStore(self.repo, payload_schemas={DIGEST: SCHEMA_ID})

    def active(self):
        self.h.initialize()
        return self.h.activate()

    def wait_operation(self, scope, operation_id, statuses=("succeeded", "failed", "unknown")):
        for _ in range(50):
            op = self.h.call("runtime.operation.get", dict(scopeRef=scope, operationId=operation_id))
            if op["status"] in statuses:
                self.h.refresh_action()
                return op
        raise AssertionError("operation did not settle: " + json.dumps(op))

    def test_projection_action_and_accept_through_runtime(self):
        """AC-07: snapshot projects the task list and task.accept; a trusted decision accepts through the same domain; result readable."""
        scope = self.active()
        page = self.h.call("runtime.snapshot.open", dict(scopeRef=scope))
        self.assertEqual([o["objectRef"] for o in page["objects"]], ["sources:milestones"])
        self.assertEqual([(a["actionId"], a["requiresHumanDecision"], a["payloadSchemaDigest"]) for a in page["actions"]],
                         [("task.accept", True, DIGEST)])
        self.h.call("runtime.action.invoke", self.h.invoke_params(), error="PERMISSION_DENIED")
        self.assertEqual(self.store().read()["tasks"], {})
        p = self.h.decided_invoke()
        accepted = self.h.call("runtime.action.invoke", p)
        self.assertEqual(accepted["status"], "accepted")
        op = self.wait_operation(scope, p["operationId"])
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "ACCEPTED"))
        chunk = self.h.call("runtime.resource.read", dict(scopeRef=scope, evidence=op["resultRef"], grantRefs=self.h.refs(), offset=0, length=op["resultRef"]["bytes"]))
        outcome = json.loads(base64.b64decode(chunk["dataBase64"]))
        self.assertEqual((outcome["result"], outcome["task"]["branch"], outcome["task"]["provenance"]), (results.ACCEPTED, "harness/feature-t0", p["operationId"]))
        self.assertEqual(git(self.repo, "rev-parse", "refs/heads/harness/feature-t0"), self.template["head"])
        self.assertTrue(Path(outcome["task"]["worktree"]).is_dir())
        state = self.store().read()
        self.assertEqual(state["tasks"]["feature-t0"]["anchor"]["digest"], outcome["task"]["anchor"]["digest"])
        # The Host decisionRef already names a decision; it is recorded once, not as decision:decision:... (KB-298).
        self.assertEqual(state["acceptance"][p["operationId"]]["intent"]["authorityRef"], p["decisionRef"])
        page = self.h.call("runtime.snapshot.open", dict(scopeRef=scope))
        self.assertEqual(sorted(o["objectRef"] for o in page["objects"]), ["sources:milestones", "task:feature-t0"])
        replay = self.h.call("runtime.action.invoke", p)
        self.assertEqual((replay["operationId"], replay["status"], replay["resultCode"]), (accepted["operationId"], "succeeded", "ACCEPTED"))
        self.assertEqual(replay, op)
        with self.assertRaises(Rejection) as ctx:
            accept_task(self.store(), dict(requestId="cli-1", repository=str(self.repo), taskType="feature", taskId="feature-t0",
                                           baseRef="main", worktreeRoot=self.template["worktreeRoot"], authorityRef="owner:cli"))
        self.assertEqual(ctx.exception.code, results.DUPLICATE_ACCEPTED_TASK)
        second = self.h.decided_invoke()
        self.h.call("runtime.action.invoke", second)
        op = self.wait_operation(scope, second["operationId"])
        self.assertEqual((op["status"], op["resultCode"]), ("failed", "DUPLICATE-ACCEPTED-TASK"))
        self.assertIsNone(op["resultRef"])
        events = self.store().read()["scopes"][scope]["events"]
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds.count("operation.changed"), 4)  # accepted + settled, for each of the two operations
        # KB-296: the accepted Task and the task list it changed both reach the stream; the refused duplicate changes
        # no projected object, so it adds no object event.
        upserts = [e["payload"] for e in events if e["kind"] == "object.upsert"]
        lists = [o for o in upserts if o["objectRef"] == "sources:milestones"]
        self.assertEqual([[r["title"] for r in o["view"]["rows"]] for o in lists], [[], ["feature-t0"]])
        self.assertEqual([o["objectRef"] for o in upserts].count("task:feature-t0"), 1)

    def test_rejections_before_durable_acceptance(self):
        """AC-07: forged action, stale revision, different request digest, decision without evidence binding and bad payload are rejected before any domain write."""
        scope = self.active()
        before = self.store().head()
        self.h.call("runtime.action.invoke", self.h.decided_invoke(actionId="task.forge"), error="PRECONDITION_CONFLICT")
        self.h.call("runtime.action.invoke", self.h.decided_invoke(expectedRevision="999"), error="PRECONDITION_CONFLICT")
        p = self.h.decided_invoke()
        self.h.call("runtime.action.invoke", dict(p, requestDigest="a" * 64), error="INTEGRITY_MISMATCH")
        mismatched = self.h.invoke_params()
        mismatched["decisionRef"] = self.h.decide(mismatched, actionId="task.other")
        mismatched["requestDigest"] = request_digest("runtime.action.invoke", mismatched)
        self.h.decisions[mismatched["decisionRef"]]["requestDigest"] = mismatched["requestDigest"]
        self.h.call("runtime.action.invoke", mismatched, error="PERMISSION_DENIED")
        self.h.call("runtime.action.invoke", self.h.decided_invoke(payload=dict(taskType="feature", taskId="feature-t0")), error="PRECONDITION_CONFLICT")
        self.h.call("runtime.action.invoke", self.h.decided_invoke(payload=self.h.payload(taskType="feature", extra="x")), error="PRECONDITION_CONFLICT")
        state = self.store().read()
        self.assertEqual((state["tasks"], state["acceptance"], state["claims"]), ({}, {}, {}))
        self.assertEqual(len(git(self.repo, "branch", "--list", "harness/*")), 0)
        # Only control-plane writes (scope open) happened before; no acceptance record exists.
        self.assertIsNotNone(before)

    def test_runtime_rejections_settle_as_failed_operations(self):
        """AC-07: dependency, hotfix lane and concurrency rejections reach the Host as failed operations with distinct result codes."""
        scope = self.active()
        p = self.h.decided_invoke(payload=self.h.payload(taskId="feature-t1"))
        self.h.call("runtime.action.invoke", p)
        op = self.wait_operation(scope, p["operationId"])
        self.assertEqual((op["status"], op["resultCode"]), ("failed", "DEPENDENCY-UNMET"))
        self.assertIsNone(op["resultRef"])
        p = self.h.decided_invoke(payload=self.h.payload(taskType="hotfix", taskId="hotfix-h" + "0" * 64))
        self.h.call("runtime.action.invoke", p)
        self.assertEqual(self.wait_operation(scope, p["operationId"])["resultCode"], "SOURCE-LANE-UNAVAILABLE")
        p = self.h.decided_invoke()
        self.h.call("runtime.action.invoke", p)
        self.assertEqual(self.wait_operation(scope, p["operationId"])["resultCode"], "ACCEPTED")
        p = self.h.decided_invoke(payload=self.h.payload(taskId="gov-t0"))
        self.h.call("runtime.action.invoke", p)
        op = self.wait_operation(scope, p["operationId"])
        self.assertEqual((op["status"], op["resultCode"]), ("failed", "CONCURRENCY-LIMIT-REACHED"))
        self.assertEqual(list(self.store().read()["tasks"]), ["feature-t0"])

    def test_kill_during_runtime_acceptance_resumes_on_restart(self):
        """AC-07 / AC-05: SIGKILL of the Runtime after the claim leaves the Operation accepted and no Task; the restarted Runtime completes it."""
        h = self.start(kill_at_phase="after-branch")
        self.h.close()
        self.h = h
        scope = self.active()
        p = self.h.decided_invoke()
        with self.assertRaises((EOFError, AssertionError)):
            self.h.call("runtime.action.invoke", p, timeout=8)
        self.h.process.wait(timeout=5)
        self.assertEqual(self.h.process.returncode, -9)
        state = self.store().read()
        self.assertEqual(state["tasks"], {})
        self.assertEqual(state["acceptance"][p["operationId"]]["status"], "claimed")
        self.assertEqual(state["operations"][p["operationId"]]["value"]["status"], "accepted")
        restarted = self.start()
        self.h = restarted
        scope = self.active()
        op = self.wait_operation(scope, p["operationId"])
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "ACCEPTED"))
        self.assertEqual(list(self.store().read()["tasks"]), ["feature-t0"])
        self.assertEqual(len(git(self.repo, "worktree", "list").splitlines()), 2)

if __name__ == "__main__":
    unittest.main()
