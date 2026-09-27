"""Projection events and object revisions through a real serve-stdio process (Assistant KB-296, KB-298).

Runtime Contract, 快照、事件与竞争: every object binds its own domain revision, which advances only when that
object's rows change; changes after a snapshot watermark are replayed on the scope's ordered stream as
object / action / pending upsert and remove. The check here is the Host's own rule: the projection a Host holds
after applying, in order, every event after its snapshot watermark must equal, object by object, a new full
snapshot taken at the same point. The composition is the production Domain Core over a synthetic product line;
Host and Human decisions are explicitly synthetic inputs.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance import projection as acceptance_projection
from domain.core import open_domain
from domain.workflow import projection as workflow_projection
from host_driver import request_digest
from test_workflow_runtime import WorkflowHost
from workflow_fixture import create

KINDS = {"object": ("objects", "objectRef"), "action": ("actions", "actionId"), "pending": ("pendingItems", "itemRef")}


class Replica:
    """What a Host holds: one full snapshot, then every data event after its watermark applied in order."""

    def __init__(self, snapshot):
        self.seq = int(snapshot["throughSeq"])
        self.content = {k: dict(snapshot[k]) for k in ("objects", "actions", "pendingItems")}
        self.history = {ref: [o["revision"]] for ref, o in snapshot["objects"].items()}

    def apply(self, event):
        seq = int(event["seq"])
        if seq != self.seq + 1:
            raise AssertionError("event stream is not contiguous: expected seq %d, got %d" % (self.seq + 1, seq))
        self.seq = seq
        family, _, verb = event["kind"].partition(".")
        if family not in KINDS:
            return
        bucket, key = KINDS[family]
        if verb == "upsert":
            self.content[bucket][event["payload"][key]] = event["payload"]
            if family == "object":
                self.history.setdefault(event["payload"]["objectRef"], []).append(event["payload"]["revision"])
        elif verb == "remove":
            self.content[bucket].pop(event["payload"][key], None)


class ProjectionEvents(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-kb296-")
            self.directory = Path(self.temp.name) / "case"
        self.template = create(self.directory, accept=False)
        self.repo = Path(self.template["repository"])
        self.host = WorkflowHost(self.directory, output=self.directory / "frames.jsonl")
        self.host.initialize()
        self.scope = self.host.activate()
        self.cursor = 0

    def tearDown(self):
        self.host.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    # -- Host side ---------------------------------------------------------------------------------
    def snapshot(self):
        page = self.host.call("runtime.snapshot.open", dict(scopeRef=self.scope))
        pages = [page]
        while page["nextPageToken"]:
            page = self.host.call("runtime.snapshot.next", dict(scopeRef=self.scope, snapshotId=pages[0]["snapshotId"],
                                                                 pageToken=page["nextPageToken"]))
            pages.append(page)
        first = pages[0]
        out = dict(snapshotId=first["snapshotId"], streamId=first["streamId"], epoch=first["epoch"],
                   throughSeq=first["throughSeq"], objects={}, actions={}, pendingItems={})
        for page in pages:
            self.assertEqual((page["throughSeq"], page["revision"]), (first["throughSeq"], first["revision"]))
            for bucket, key in KINDS.values():
                for item in page[bucket]:
                    self.assertNotIn(item[key], out[bucket], "duplicate identity in one snapshot")
                    out[bucket][item[key]] = item
        return out

    def subscribe(self, snapshot):
        result = self.host.call("runtime.events.subscribe", dict(scopeRef=self.scope, snapshotId=snapshot["snapshotId"],
                                                                 streamId=snapshot["streamId"], epoch=snapshot["epoch"],
                                                                 afterSeq=snapshot["throughSeq"]))
        self.subscription = dict(id=result["subscriptionId"], streamId=snapshot["streamId"], epoch=snapshot["epoch"])
        return Replica(snapshot)

    def catch_up(self, replica, through):
        """Apply delivered data events until the replica reaches the watermark of a snapshot taken now."""
        while replica.seq < int(through):
            while self.cursor >= len(self.host.events):
                self.host.pump(awaiting="runtime.event up to seq " + str(through))
            frame = self.host.events[self.cursor]
            self.cursor += 1
            event = frame["params"]["event"]
            if event["kind"] == "stream.caughtUp":
                continue
            self.assertEqual(event["subscriptionId"], self.subscription["id"])
            replica.apply(event)
        self.host.call("runtime.events.ack", dict(subscriptionId=self.subscription["id"], streamId=self.subscription["streamId"],
                                                  epoch=self.subscription["epoch"], seq=str(replica.seq)))

    def assert_replayed_equals_snapshot(self, replica, label):
        fresh = self.snapshot()
        self.catch_up(replica, fresh["throughSeq"])
        self.assertEqual(replica.seq, int(fresh["throughSeq"]), label)
        for bucket in ("objects", "actions", "pendingItems"):
            self.assertEqual(sorted(replica.content[bucket]), sorted(fresh[bucket]), label + ": " + bucket + " identities")
            for ref, item in fresh[bucket].items():
                self.assertEqual(replica.content[bucket][ref], item, label + ": " + bucket + " " + ref)
        # Object-level revision: every action binds the current revision of the object it targets.
        for action in fresh["actions"].values():
            target = fresh["objects"].get(action["objectRef"])
            if target is not None:
                self.assertEqual(action["expectedRevision"], target["revision"], label + ": " + action["actionId"])
        return fresh

    # -- Human side (synthetic) --------------------------------------------------------------------
    def invoke(self, action, payload, *, decision_ref=None):
        if decision_ref is None:
            p = self.host.decided(action, payload)
        else:
            p = self.host.action_params(action, payload, decisionRef=decision_ref)
            p["requestDigest"] = request_digest("runtime.action.invoke", p)
            self.host.decide(p, decisionRef=decision_ref)
        accepted = self.host.call("runtime.action.invoke", p)
        op = accepted
        for _ in range(50):
            if op["status"] in ("succeeded", "failed", "unknown", "cancelled"):
                break
            op = self.host.call("runtime.operation.get", dict(scopeRef=self.scope, operationId=p["operationId"]))
        return p, op

    def accept(self, snapshot, task_id, **kw):
        action = snapshot["actions"][acceptance_projection.ACTION_ID]
        return self.invoke(action, dict(taskType="feature", taskId=task_id, baseRef="main",
                                        worktreeRoot=self.template["worktreeRoot"]), **kw)

    # -- cases -------------------------------------------------------------------------------------
    def test_replayed_projection_equals_a_new_snapshot_through_accept_refuse_and_close(self):
        """KB-296: accept, refusal and a later Workflow change each reach a subscribed Host as events."""
        first = self.snapshot()
        replica = self.subscribe(first)
        sources = first["objects"][acceptance_projection.SOURCES_OBJECT]
        self.assertEqual(sources["view"]["rows"], [])

        _, op = self.accept(first, "feature-t0")
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "ACCEPTED"))
        after_accept = self.assert_replayed_equals_snapshot(replica, "after accept")
        rows = replica.content["objects"][acceptance_projection.SOURCES_OBJECT]["view"]["rows"]
        self.assertEqual([(r["title"], r["detail"]) for r in rows], [("feature-t0", "harness/feature-t0")])
        self.assertNotEqual(after_accept["objects"][acceptance_projection.SOURCES_OBJECT]["revision"], sources["revision"])
        self.assertIn("task:feature-t0", replica.content["objects"])

        _, op = self.accept(after_accept, "feature-t1")
        self.assertEqual((op["status"], op["resultCode"]), ("failed", "DEPENDENCY-UNMET"))
        after_refusal = self.assert_replayed_equals_snapshot(replica, "after refusal")
        # A refusal changes no projected object, so no object keeps a different revision.
        for ref, obj in after_accept["objects"].items():
            self.assertEqual(after_refusal["objects"][ref]["revision"], obj["revision"], ref)

        version = open_domain(self.repo).status("feature-t0")["tasks"][0]["runtimeVersion"]
        close = after_refusal["actions"][workflow_projection.ACTION_CLOSE]
        self.assertTrue(close["enabled"])
        _, op = self.invoke(close, dict(taskId="feature-t0", reasonCategory="human-initiated", expectedRuntimeVersion=version))
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "FINALIZED"))
        after_close = self.assert_replayed_equals_snapshot(replica, "after close")
        self.assertFalse(replica.content["actions"][workflow_projection.ACTION_CLOSE]["enabled"])
        self.assertEqual(replica.content["objects"]["task:feature-t0"]["stateLabel"], after_close["objects"]["task:feature-t0"]["stateLabel"])
        for ref in ("task:feature-t0", workflow_projection.WORKFLOW_OBJECT):
            self.assertNotEqual(after_close["objects"][ref], after_refusal["objects"][ref], ref)
            self.assertNotEqual(after_close["objects"][ref]["revision"], after_refusal["objects"][ref]["revision"], ref)

        # Revisions only move forward, and only for an object whose own content changed.
        for ref, revisions in replica.history.items():
            numbers = [int(r) for r in revisions]
            self.assertEqual(numbers, sorted(set(numbers)), ref + " revisions " + json.dumps(revisions))

    def test_accept_intent_records_the_decision_reference_once(self):
        """KB-298: the authority of a Runtime acceptance names the trusted decision without a doubled prefix."""
        first = self.snapshot()
        prefixed = "decision:kb298-prefixed"
        p, op = self.accept(first, "feature-t0", decision_ref=prefixed)
        self.assertEqual(op["status"], "succeeded", json.dumps(op))
        state = open_domain(self.repo).store.read()
        self.assertEqual(state["acceptance"][p["operationId"]]["intent"]["authorityRef"], prefixed)

    def test_an_unprefixed_decision_reference_is_named_as_a_decision(self):
        """KB-298: a Host decision reference without the kind prefix still records as a decision authority."""
        first = self.snapshot()
        bare = "kb298-bare"
        p, op = self.accept(first, "feature-t0", decision_ref=bare)
        self.assertEqual(op["status"], "succeeded", json.dumps(op))
        state = open_domain(self.repo).store.read()
        self.assertEqual(state["acceptance"][p["operationId"]]["intent"]["authorityRef"], "decision:" + bare)


if __name__ == "__main__":
    unittest.main()
