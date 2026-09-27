import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from make_fixture import create, LIMITS
from host_driver import Host, request_digest
from git_domain import GitDomain

class RuntimeCases(unittest.TestCase):
    def setUp(self):
        root=os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory=Path(root)/self._testMethodName
            self.directory.parent.mkdir(parents=True,exist_ok=True)
        else:
            self.temp=tempfile.TemporaryDirectory(prefix="hp-t16-tests-")
            self.directory=Path(self.temp.name)/"case"
        create(self.directory)
        self.hosts=[]
        self.h=self.start()

    def start(self,product=False):
        h=Host(self.directory,product=product,output=self.directory/("frames-"+str(len(self.hosts))+".jsonl"))
        self.hosts.append(h)
        return h

    def tearDown(self):
        for h in self.hosts:h.close()
        if hasattr(self,"temp"):self.temp.cleanup()

    def domain(self):return GitDomain(self.directory/"domain",json.loads((self.directory/"seed.json").read_text()))
    def state(self):return self.domain().read()
    def edit(self,callback):
        domain=self.domain()
        return domain.transaction(domain.read()["generation"],callback)
    def active(self):
        self.h.initialize()
        return self.h.activate()

    def test_basic_scopes_and_pagination(self):
        self.h.initialize(dict(limits=dict(LIMITS,pageObjects=2)))
        scope=self.h.activate()
        first=self.h.call("runtime.snapshot.open",dict(scopeRef=scope))
        pages=[first]
        while pages[-1]["nextPageToken"]:
            p=dict(scopeRef=scope,snapshotId=first["snapshotId"],pageToken=pages[-1]["nextPageToken"])
            page=self.h.call("runtime.snapshot.next",p)
            self.assertEqual(page,self.h.call("runtime.snapshot.next",p))
            self.assertEqual(page["revision"],first["revision"])
            pages.append(page)
        self.assertEqual(sum(len(p["objects"])+len(p["actions"])+len(p["pendingItems"]) for p in pages),5)
        pending=[i for p in pages for i in p["pendingItems"]][0]
        self.assertEqual(pending["pendingSince"],"2026-09-21T00:00:00Z")
        self.assertIsNone(pending["processedAt"])
        self.h.call("runtime.snapshot.next",dict(scopeRef=scope,snapshotId=first["snapshotId"],pageToken="page:forged"),error="RESYNC_REQUIRED")

    def test_dynamic_grants_and_inactive(self):
        self.h.initialize()
        scope=self.h.call("runtime.scope.open",dict(binding=self.h.template["binding"]))["scopeRef"]
        self.h.call("runtime.snapshot.open",dict(scopeRef=scope),error="PERMISSION_DENIED")
        self.h.activate()
        self.h.grants[0]["status"]="revoked"
        self.h.call("runtime.snapshot.open",dict(scopeRef=scope),error="PERMISSION_REVOKED")
        self.h.grants[0]["status"]="active"
        self.h.call("runtime.scope.authorize",dict(scopeRef=scope,grantRefs=[]))
        self.h.call("runtime.snapshot.open",dict(scopeRef=scope),error="PERMISSION_DENIED")

    def test_auth_before_dedup(self):
        self.active()
        p=self.h.invoke_params()
        self.h.call("runtime.action.invoke",p)
        self.h.grants[4]["status"]="revoked"
        self.h.call("runtime.action.invoke",p,error="PERMISSION_REVOKED")
        self.assertEqual(self.state()["acceptedCount"],1)

    def test_idempotency_and_digest(self):
        self.active()
        p=self.h.invoke_params()
        result=self.h.call("runtime.action.invoke",p)
        self.assertEqual(result,self.h.call("runtime.action.invoke",p))
        self.assertEqual(self.state()["acceptedCount"],1)
        other=dict(p,operationId="op:different")
        other["requestDigest"]=request_digest("runtime.action.invoke",other)
        self.h.call("runtime.action.invoke",other,error="IDEMPOTENCY_CONFLICT")
        other=dict(p,payload={"value":"different"})
        other["requestDigest"]=request_digest("runtime.action.invoke",other)
        self.h.call("runtime.action.invoke",other,error="IDEMPOTENCY_CONFLICT")
        self.h.call("runtime.action.invoke",dict(p,requestDigest="a"*64),error="INTEGRITY_MISMATCH")

    def test_replay_after_action_removed(self):
        self.active()
        p=self.h.invoke_params()
        result=self.h.call("runtime.action.invoke",p)
        self.edit(lambda s:s["scopes"][p["scopeRef"]].update(actions=[]))
        self.assertEqual(result,self.h.call("runtime.action.invoke",p))

    def test_tombstone_and_unknown_index(self):
        scope=self.active()
        p=self.h.invoke_params()
        self.h.call("runtime.action.invoke",p)
        def tombstone(s):s["operations"][p["operationId"]]["tombstone"]=True
        self.edit(tombstone)
        self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]),error="RESULT_UNKNOWN")
        self.assertEqual(self.h.call("runtime.action.invoke",p)["status"],"unknown")
        self.edit(lambda s:s.update(indexComplete=False))
        self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId="op:missing"),error="RESULT_UNKNOWN")

    def test_missing_operation_and_action(self):
        scope=self.active()
        error=self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId="op:missing"),error="NOT_FOUND")
        self.assertTrue(error["data"]["absenceProven"])
        self.h.call("runtime.action.invoke",self.h.invoke_params(actionId="action:missing"),error="PRECONDITION_CONFLICT")

    def test_read_only_retry_preserves_revision(self):
        self.active()
        p=self.h.invoke_params()
        self.h.call("runtime.action.invoke",p)
        before=self.state()["revision"]
        self.h.call("runtime.action.invoke",p)
        self.assertEqual(self.state()["revision"],before)

    def test_cancel_quiesce_and_shutdown(self):
        scope=self.active()
        p=self.h.invoke_params()
        self.h.call("runtime.action.invoke",p)
        q=self.h.mutation("runtime.quiesce",reason="test")
        self.h.call("runtime.quiesce",q)
        self.assertEqual(self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]))["status"],"accepted")
        self.h.call("runtime.action.invoke",self.h.invoke_params(),error="BUSY")
        cancel=self.h.mutation("runtime.operation.cancel",scopeRef=scope,targetOperationId=p["operationId"])
        result=self.h.call("runtime.operation.cancel",cancel)
        self.assertEqual(result,self.h.call("runtime.operation.cancel",cancel))
        self.assertEqual(self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]))["status"],"cancelled")
        shutdown=self.h.mutation("runtime.shutdown",reason="test")
        self.h.call("runtime.shutdown",shutdown)
        self.h.process.wait(timeout=3)
        self.assertTrue(self.state()["shutdown"])
        self.assertIn(shutdown["operationId"],self.state()["operations"])

    def test_upgrade_release_atomic_revision(self):
        self.active()
        p=self.h.mutation("runtime.upgrade.prepare",sourceBundleDigest="b"*64,targetBundleDigest="b"*64,
            sourceDataFormat="synthetic-v1",targetDataFormat="synthetic-v1")
        prepared=self.h.call("runtime.upgrade.prepare",p)
        self.assertEqual(prepared["status"],"prepared")
        self.h.call("runtime.action.invoke",self.h.invoke_params(),error="BUSY")
        release=self.h.mutation("runtime.upgrade.release",prepareOperationId=p["operationId"],barrierRef=prepared["barrierRef"],
            disposition="activated",runningBundleDigest="b"*64,dataFormat="synthetic-v1")
        result=self.h.call("runtime.upgrade.release",release)
        state=self.state()
        self.assertIsNone(state["barrier"])
        self.assertEqual(state["upgrades"][p["operationId"]]["releasedDomainRevision"],state["revision"])
        self.assertEqual(state["operations"][release["operationId"]]["value"]["revision"],state["revision"])
        self.assertEqual(result,self.h.call("runtime.upgrade.release",release))
        self.assertEqual(self.state()["revision"],state["revision"])
        self.edit(lambda s:s.update(secondWriterMarker=True))
        self.assertGreater(int(self.state()["revision"]),int(state["revision"]))

    def test_blocked_upgrade_and_restart_barrier(self):
        self.active()
        protected=dict(scopeRef=self.h.template["scopeRef"],objectRef="object:one",revision="1",reason="Synthetic active reference")
        self.edit(lambda s:s.update(protectedReferences=[protected]))
        p=self.h.mutation("runtime.upgrade.prepare",sourceBundleDigest="b"*64,targetBundleDigest="b"*64,
            sourceDataFormat="synthetic-v1",targetDataFormat="synthetic-v1")
        blocked=self.h.call("runtime.upgrade.prepare",p)
        self.assertEqual(blocked["protectedReferences"],[protected])
        self.assertIsNone(blocked["barrierRef"])
        self.edit(lambda s:s.update(protectedReferences=[]))
        self.assertEqual(blocked,self.h.call("runtime.upgrade.prepare",p))
        p=self.h.mutation("runtime.upgrade.prepare",sourceBundleDigest="b"*64,targetBundleDigest="b"*64,
            sourceDataFormat="synthetic-v1",targetDataFormat="synthetic-v1")
        prepared=self.h.call("runtime.upgrade.prepare",p)
        self.h.close()
        self.h=self.start();self.active()
        self.assertEqual(self.h.call("runtime.upgrade.get",dict(operationId=p["operationId"]))["barrierRef"],prepared["barrierRef"])
        self.h.call("runtime.action.invoke",self.h.invoke_params(),error="BUSY")

    def test_crash_recovery_and_fencing(self):
        scope=self.active()
        p=self.h.invoke_params()
        accepted=self.h.call("runtime.action.invoke",p)
        self.h.process.kill();self.h.process.wait(timeout=3)
        self.h=self.start();self.active()
        recovered=self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=p["operationId"]))
        self.assertEqual(recovered["status"],accepted["status"])
        second=self.domain();second.acquire_generation()
        self.h.call("runtime.health",error="WRITER_CONFLICT")

    def test_resource_identity_and_terminal_errors(self):
        scope=self.active()
        evidence=self.h.template["evidence"]
        p=dict(scopeRef=scope,evidence=evidence,grantRefs=self.h.refs(),offset=0,length=4)
        result=self.h.call("runtime.resource.read",p)
        self.assertEqual(result["digest"],evidence["digest"])
        self.assertFalse(result["eof"])
        self.h.call("runtime.resource.read",dict(p,evidence=dict(evidence,authority="host")),error="INVALID_SOURCE")
        self.h.call("runtime.resource.read",dict(p,evidence=dict(evidence,digest="a"*64)),error="INTEGRITY_MISMATCH")
        op=self.h.invoke_params();self.h.call("runtime.action.invoke",op)
        self.edit(lambda s:s["operations"][op["operationId"]]["value"].update(status="failed",resultRef=evidence))
        self.h.call("runtime.resource.read",p,error="EXECUTION_FAILED")
        self.assertEqual(self.h.call("runtime.operation.get",dict(scopeRef=scope,operationId=op["operationId"]))["status"],"failed")
        self.edit(lambda s:s["operations"][op["operationId"]]["value"].update(status="cancelled"))
        self.h.call("runtime.resource.read",p,error="CANCELLED")

    def test_action_payload_and_human_decision(self):
        self.active()
        self.h.call("runtime.action.invoke",self.h.invoke_params(payload={"unexpected":True}),error="PRECONDITION_CONFLICT")
        self.h.call("runtime.action.invoke",self.h.invoke_params(expectedRevision="99"),error="PRECONDITION_CONFLICT")
        self.h.call("runtime.action.invoke",self.h.invoke_params(actionId="action:disabled"),error="PRECONDITION_CONFLICT")
        self.h.call("runtime.action.invoke",self.h.invoke_params(actionId="action:human"),error="PERMISSION_DENIED")
        p=self.h.invoke_params(actionId="action:human",decisionRef="decision:one")
        decision=dict(decisionRef=p["decisionRef"],scopeRef=p["scopeRef"],domainOperationId=p["operationId"],
            method="runtime.action.invoke",requestDigest=p["requestDigest"],actionId=p["actionId"],objectRef=p["objectRef"],
            candidateRef=p["candidateRef"],expectedRevision=p["expectedRevision"],evidence=[],actorRef="human:test",
            source="host-trusted-ui",recordedAt="2026-09-21T00:00:00Z",status="valid")
        self.h.decisions[p["decisionRef"]]=decision
        self.h.call("runtime.action.invoke",p,error="PERMISSION_DENIED")
        decision["evidence"]=[self.h.template["evidence"]]
        self.assertEqual(self.h.call("runtime.action.invoke",p)["status"],"accepted")

    def test_snapshot_to_subscribe_and_ack(self):
        scope=self.active()
        snap=self.h.call("runtime.snapshot.open",dict(scopeRef=scope))
        self.h.call("runtime.action.invoke",self.h.invoke_params())
        args=dict(scopeRef=scope,snapshotId=snap["snapshotId"],streamId=snap["streamId"],epoch=snap["epoch"],afterSeq=snap["throughSeq"])
        result=self.h.call("runtime.events.subscribe",args)
        while len(self.h.events)<2:self.h.pump()
        self.assertEqual(self.h.events[0]["params"]["event"]["seq"],"1")
        self.assertEqual(self.h.events[1]["params"]["event"]["kind"],"stream.caughtUp")
        ack=dict(subscriptionId=result["subscriptionId"],streamId=snap["streamId"],epoch=snap["epoch"],seq="1")
        self.assertEqual(self.h.call("runtime.events.ack",ack)["acknowledgedSeq"],"1")
        self.assertEqual(self.h.call("runtime.events.ack",ack)["acknowledgedSeq"],"1")
        self.h.call("runtime.events.ack",dict(ack,seq="2"),error="PRECONDITION_CONFLICT")
        replace=self.h.call("runtime.events.subscribe",args)
        self.assertEqual(replace["replacedSubscriptionId"],result["subscriptionId"])
        self.h.call("runtime.events.ack",ack,error="RESYNC_REQUIRED")

    def test_product_has_no_synthetic_capability(self):
        self.h.close()
        self.h=self.start(product=True)
        initialized=self.h.initialize()
        self.assertEqual(initialized["capabilities"],[])
        self.assertEqual(self.h.call("runtime.health")["health"],"degraded")
        self.h.call("runtime.scope.open",dict(binding=self.h.template["binding"]),error="UNSUPPORTED_CAPABILITY")

if __name__=="__main__":unittest.main()
