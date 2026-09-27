import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.protocol import Fault, LIMITS, Schemas, decode, digest
from runtime.host import HostClient
from test_runtime import RuntimeCases

class SchemaCases(unittest.TestCase):
    def test_local_registry_resolves_and_never_downloads(self):
        root={"$id":"urn:test:root","type":"object","properties":{"x":{"$ref":"urn:test:child#/definitions/value"}}}
        child={"$id":"urn:test:child","definitions":{"value":{"type":"integer"}}}
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden")):
            schemas=Schemas({"urn:test:root":root,"urn:test:child":child})
            schemas.payload("urn:test:root",{"x":1})
            with self.assertRaises(Fault):schemas.payload("urn:test:root",{"x":"wrong"})
        for ref in ("https://example.invalid/schema","file:///etc/passwd","urn:test:missing","#/missing"):
            with self.subTest(ref=ref),self.assertRaises(ValueError):
                Schemas({"urn:test:root":{"$id":"urn:test:root","$ref":ref}})

    def test_canonical_digest_not_raw_bytes(self):
        one={"context":{"connectionId":"first"},"operationId":"op:one","payload":{"z":1,"a":"é"},"requestDigest":"ignored"}
        two={"payload":{"a":"é","z":1.0},"operationId":"op:one","context":{"connectionId":"second"}}
        self.assertEqual(digest("runtime.action.invoke",one),digest("runtime.action.invoke",two))
        with self.assertRaises(Fault):digest("runtime.action.invoke",{"x":9007199254740992})

    def test_strict_frames(self):
        invalid=[b'[]\n',b'1\n',b'\xef\xbb\xbf{}\n',b'{"a":1,"a":2}\n',b'{"a":NaN}\n',b'{"a":Infinity}\n',b'{"a":"\xff"}\n',
                 b'{"a":9007199254740992}\n',b'{"a":"\\ud800"}\n',b'{}']
        for raw in invalid:
            with self.subTest(raw=raw),self.assertRaises(Fault):decode(raw,LIMITS)
        self.assertEqual(decode(b'{"a":9007199254740991}\n',LIMITS)["a"],9007199254740991)

class ProtocolCases(RuntimeCases):
    # Inherits the fixture setup only; discovery is limited below to avoid duplicate base cases.
    def test_params_correlation_and_liveness(self):
        self.active()
        self.h.send(dict(jsonrpc="2.0",id="h:bad",method="runtime.health",params=[]))
        while "h:bad" not in self.h.responses:self.h.pump()
        self.assertEqual(self.h.responses["h:bad"]["error"]["code"],-32602)
        self.assertEqual(self.h.call("runtime.health")["health"],"ready")

    def test_negotiated_unterminated_frame_closes(self):
        self.h.initialize(dict(limits=dict(LIMITS,frameBytes=4096)))
        self.h.process.stdin.write(b"x"*4096);self.h.process.stdin.flush()
        self.h.process.wait(timeout=2)

    def test_launch_and_required_capability_digests(self):
        p=copy.deepcopy(self.h.template["initialize"])
        p["installationId"]="installation:forged"
        self.h.call("runtime.initialize",p,error="PERMISSION_DENIED")
        p=copy.deepcopy(self.h.template["initialize"])
        p["capabilities"][0].update(required=True,schemaDigest="a"*64)
        self.h.call("runtime.initialize",p,error="UNSUPPORTED_CAPABILITY")
        self.h.close()
        seed=json.loads((self.directory/"seed.json").read_text())
        seed["capabilities"][0].update(required=True,schemaDigest="f"*64)
        (self.directory/"seed.json").write_text(json.dumps(seed))
        self.h=self.start()
        self.h.process.wait(timeout=3)
        self.assertNotEqual(self.h.process.returncode,0)
        self.h.error_reader.join(timeout=1)
        self.assertIn("schemaDigest", "".join(self.h.stderr))

    def test_grant_revoked_while_decision_awaited(self):
        self.active()
        p=self.h.invoke_params(actionId="action:human",decisionRef="decision:one")
        decision=dict(decisionRef=p["decisionRef"],scopeRef=p["scopeRef"],domainOperationId=p["operationId"],
            method="runtime.action.invoke",requestDigest=p["requestDigest"],actionId=p["actionId"],objectRef=p["objectRef"],
            candidateRef=p["candidateRef"],expectedRevision=p["expectedRevision"],evidence=[self.h.template["evidence"]],actorRef="human:test",
            source="host-trusted-ui",recordedAt="2026-09-21T00:00:00Z",status="valid")
        def revoke(params):
            self.h.grants[4]["status"]="revoked"
            return dict(context=params["context"],**decision)
        self.h.handlers["host.decision.get"]=revoke
        self.h.call("runtime.action.invoke",p,error="PERMISSION_REVOKED")
        self.assertEqual(self.state()["acceptedCount"],0)

    def test_event_window_preserves_control_requests(self):
        self.h.initialize(dict(limits=dict(LIMITS,eventWindow=1)))
        scope=self.h.activate()
        snap=self.h.call("runtime.snapshot.open",dict(scopeRef=scope))
        for _ in range(3):self.h.call("runtime.action.invoke",self.h.invoke_params())
        result=self.h.call("runtime.events.subscribe",dict(scopeRef=scope,snapshotId=snap["snapshotId"],
            streamId=snap["streamId"],epoch=snap["epoch"],afterSeq="0"))
        while not self.h.events:self.h.pump()
        self.h.call("runtime.health")
        self.assertEqual(len(self.h.events),1)
        self.h.call("runtime.events.ack",dict(subscriptionId=result["subscriptionId"],streamId=snap["streamId"],epoch=snap["epoch"],seq="1"))
        while len(self.h.events)<2:self.h.pump()
        self.assertEqual(self.h.events[1]["params"]["event"]["seq"],"2")

    def test_epoch_loss_and_cross_scope_tokens(self):
        scope=self.active()
        snap=self.h.call("runtime.snapshot.open",dict(scopeRef=scope))
        self.edit(lambda s:s["scopes"][scope].update(epoch="2"))
        self.h.call("runtime.events.subscribe",dict(scopeRef=scope,snapshotId=snap["snapshotId"],streamId=snap["streamId"],epoch="1",afterSeq="0"),error="RESYNC_REQUIRED")

    def test_duplicate_notification_does_not_execute(self):
        self.active()
        p={"context":self.h.context,**self.h.invoke_params()}
        self.h.send(dict(jsonrpc="2.0",method="runtime.action.invoke",params=p))
        while None not in self.h.responses:self.h.pump()
        self.assertEqual(self.h.responses[None]["error"]["code"],-32600)
        self.assertEqual(self.state()["acceptedCount"],0)

    def test_cancel_completed_target_preserves_terminal(self):
        scope=self.active();p=self.h.invoke_params()
        self.h.call("runtime.action.invoke",p)
        self.edit(lambda s:s["operations"][p["operationId"]]["value"].update(status="succeeded"))
        cancel=self.h.mutation("runtime.operation.cancel",scopeRef=scope,targetOperationId=p["operationId"])
        self.h.call("runtime.operation.cancel",cancel)
        self.assertEqual(self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]))["status"],"succeeded")

    def test_snapshot_cache_is_bounded(self):
        scope=self.active()
        for _ in range(8):self.h.call("runtime.snapshot.open",dict(scopeRef=scope))
        error=self.h.call("runtime.snapshot.open",dict(scopeRef=scope),error="RESOURCE_LIMIT")
        self.assertEqual(error["data"]["recovery"],"retry-later")

    def test_shared_writer_obeys_upgrade_barrier(self):
        self.active()
        p=self.h.mutation("runtime.upgrade.prepare",sourceBundleDigest="b"*64,targetBundleDigest="b"*64,
            sourceDataFormat="synthetic-v1",targetDataFormat="synthetic-v1")
        self.h.call("runtime.upgrade.prepare",p)
        before=self.state()
        with self.assertRaises(Fault):self.edit(lambda s:s.update(secondWriterMarker=True))
        self.assertEqual(self.state(),before)

    def test_inflight_grant_result_cannot_reactivate_scope(self):
        scope=self.active()
        captured=[]
        def hold(params):
            captured.append(params)
            return None
        self.h.handlers["host.grants.get"]=hold
        self.h.send(dict(jsonrpc="2.0",id="h:waiting",method="runtime.snapshot.open",params=dict(context=self.h.context,scopeRef=scope)))
        request=None
        while not captured:
            frame=self.h.pump()
            if frame.get("method")=="host.grants.get":request=frame
        self.h.call("runtime.scope.authorize",dict(scopeRef=scope,grantRefs=[]))
        self.h.send(dict(jsonrpc="2.0",id=request["id"],result=dict(context=self.h.context,grants=self.h.grants)))
        while "h:waiting" not in self.h.responses:self.h.pump()
        self.assertEqual(self.h.responses["h:waiting"]["error"]["data"]["code"],"PERMISSION_REVOKED")

    def test_snapshot_lease_expiry_with_controlled_clock(self):
        # Clock control is an isolated unit test; real 60s wire probe is separate J-02 evidence.
        from runtime.dispatcher import Dispatcher
        from datetime import datetime, timezone
        from unittest.mock import patch
        self.active()
        d=Dispatcher(self.domain(),json.loads((self.directory/"launch.json").read_text()),None)
        d.snapshots["snapshot:expired"]={"expires":"2000-01-01T00:00:00Z","pages":[{"scopeRef":self.h.template["scopeRef"]}]}
        with self.assertRaises(Fault) as failure:
            d.snapshot(dict(snapshotId="snapshot:expired",scopeRef=self.h.template["scopeRef"]))
        self.assertEqual(failure.exception.code,"RESYNC_REQUIRED")

    def fault_restart(self, phase, method, params):
        self.h.close()
        fault=self.directory/"fault.json"
        fault.write_text(json.dumps(dict(phase=phase,operationId=params["operationId"])))
        self.h=self.start();self.active()
        with self.assertRaises(EOFError):self.h.call(method,params)
        self.h.process.wait(timeout=3)
        self.assertEqual(self.h.process.returncode,-9)
        proof=json.loads(fault.with_suffix(".fired.json").read_text())
        self.assertEqual(proof["phase"],phase)
        if phase=="before-commit":self.assertEqual(proof["beforeCommit"],proof["actualCommit"])
        else:self.assertNotEqual(proof["beforeCommit"],proof["actualCommit"])
        fault.rename(self.directory/(method+"-fault-used.json"))
        self.h=self.start();self.active()
        return proof

    def test_crash_before_durable_acceptance(self):
        scope=self.active();p=self.h.invoke_params()
        self.fault_restart("before-commit","runtime.action.invoke",p)
        self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]),error="NOT_FOUND")
        self.assertEqual(self.state()["acceptedCount"],0)
        self.h.call("runtime.action.invoke",p)
        self.assertEqual(self.state()["acceptedCount"],1)

    def test_crash_after_commit_before_invoke_reply(self):
        scope=self.active();p=self.h.invoke_params()
        self.fault_restart("after-commit","runtime.action.invoke",p)
        self.assertEqual(self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]))["status"],"accepted")
        self.h.call("runtime.action.invoke",p)
        self.assertEqual(self.state()["acceptedCount"],1)

    def test_crash_after_cancel_commit_before_reply(self):
        scope=self.active();p=self.h.invoke_params();self.h.call("runtime.action.invoke",p)
        cancel=self.h.mutation("runtime.operation.cancel",scopeRef=scope,targetOperationId=p["operationId"])
        self.fault_restart("after-commit","runtime.operation.cancel",cancel)
        result=self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=cancel["operationId"]))
        self.assertEqual(result,self.h.call("runtime.operation.cancel",cancel))
        self.assertEqual(self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]))["status"],"cancelled")

    def test_crash_after_release_commit_before_reply(self):
        self.active()
        p=self.h.mutation("runtime.upgrade.prepare",sourceBundleDigest="b"*64,targetBundleDigest="b"*64,
            sourceDataFormat="synthetic-v1",targetDataFormat="synthetic-v1")
        prepared=self.h.call("runtime.upgrade.prepare",p)
        release=self.h.mutation("runtime.upgrade.release",prepareOperationId=p["operationId"],barrierRef=prepared["barrierRef"],
            disposition="activated",runningBundleDigest="b"*64,dataFormat="synthetic-v1")
        self.fault_restart("after-commit","runtime.upgrade.release",release)
        result=self.h.call("runtime.operation.get",dict(scopeRef="instance",operationId=release["operationId"]))
        upgrade=self.h.call("runtime.upgrade.get",dict(operationId=p["operationId"]))
        self.assertEqual(upgrade["status"],"released")
        self.assertEqual(result["revision"],upgrade["releasedDomainRevision"])
        before=self.state()["revision"]
        self.assertEqual(result,self.h.call("runtime.upgrade.release",release))
        self.assertEqual(self.state()["revision"],before)

    def test_tiny_limit_profile_is_rejected_without_partial_initialize(self):
        p=copy.deepcopy(self.h.template["initialize"])
        p["limits"]["frameBytes"]=1
        self.h.call("runtime.initialize",p,error="RESOURCE_LIMIT")
        self.assertEqual(self.state()["generation"],"0")
        self.h.initialize()
        self.assertEqual(self.h.call("runtime.health")["health"],"ready")

def load_tests(loader,tests,pattern):
    suite=unittest.TestSuite(loader.loadTestsFromTestCase(SchemaCases))
    for name in ProtocolCases.__dict__:
        if name.startswith("test_"):suite.addTest(ProtocolCases(name))
    return suite
