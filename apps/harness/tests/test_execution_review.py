"""Formal runner and actual Local worker acceptance with isolated fake adapters."""
import asyncio
import base64
import copy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import test_execution_port as EP
import uuid
from execution.bridge import ProductReview, MECHANISM
from execution.local import LocalExecutionPort
from execution.host import HostExecutionPort
from execution.port import ExecutionAuthorization, ExecutionDiscovery, ExecutionError, identity, sha
import review_channel as C
import review_channel_base as B
import review_channel_receipt as RC
import review_channel_execution as X
import review_channel_runtime as RT
import review_channel_selftest as ST
import review_channel_selftest_channel as SC
import review_evidence as E


class ReviewCases(unittest.IsolatedAsyncioTestCase):
    make_port=EP.HostExecutionCases.make_port
    reserve=EP.HostExecutionCases.reserve
    def setUp(self):
        EP.HostExecutionCases.setUp(self)
        self.engine=ST.Engine(str(MECHANISM))
        os.rmdir(self.engine.tmp_root)
        base=Path(os.environ.get('HP_EXECUTION_TEST_OUTPUT',str(Path.home()/'.local/share/harness-plane/test-runs/feature-t17'))).resolve()
        self.engine.tmp_root=str(base/(self._testMethodName+'-'+uuid.uuid4().hex));Path(self.engine.tmp_root).mkdir(parents=True)
        self.env=SC.Env(self.engine,dict(behavior='valid',identity='fake-model'))
        self.repo=self.env.repo
        # The isolated fixture normally imports the original unit in subprocesses;
        # Local's worker loads its governed repository copy instead.
        target=Path(self.repo.root)/'mechanisms/review-channel'
        for path in list(MECHANISM.glob('*.py'))+[MECHANISM/'review_channel_execution_schema.json']:
            shutil.copy(path,target/path.name)
        self.registration.update(provider='fake-official',model_ref='fake-model',transport='responses')
        self.mapping.update(provider='fake-official',model_ref='fake-model',model_vendor='DeepSeek',actual_models=['fake-model'])
        self.intent.update(caller='selftest',invocation_authorization='selftest:OD-01',transport='responses')
        self.intent['executionBinding'].update(model='fake-model',modelVendor='DeepSeek',agent='synthetic')
        self.host.actual=lambda:dict(model='fake-model',observedModels=['fake-model'],source='protocol-result')
        self.current_context=None
        def result_bytes():
            ctx=self.current_context
            adapter=RT.load_adapter('fake',self.env.adapters)
            result=adapter.run(ctx);answer=result['final_message'].decode()
            start=self.host.start
            return json.dumps(dict(**{k:start[k] for k in ('operationId','profileId','profileDigest')},executionRef='execution:one',actualBinding=self.host.actual(),outcome='completed',evidence=dict(answer=answer,answerBytes=len(answer.encode()),answerDigest=sha(answer.encode()),readback=dict(modelProvider='protocol-independent')))).encode()
        self.host.result_bytes=result_bytes
        async def discover():return ExecutionDiscovery(copy.deepcopy(self.registration['profile']),self.intent['connectionRef'],self.registration['provider'],'protocol-independent','7')
        async def authorize(intent):return ExecutionAuthorization(identity(intent),sha(intent['invocation_authorization'].encode()),intent['caller'],('Anthropic',),('author:fixed',),True,2,'owner:synthetic')
        self.discover=discover;self.authorize=authorize
        self.port=HostExecutionPort(self.host,self.domain,self.registration,self.mapping,discover,authorize)
        self.port.bind_context=lambda intent,ctx:setattr(self,'current_context',ctx)
        self.archive=None
        self.install_registry()
    def tearDown(self):
        if not os.environ.get('HP_EXECUTION_TEST_OUTPUT'):self.engine.cleanup()
        EP.HostExecutionCases.tearDown(self)
    def install_registry(self):
        p=Path(self.env.registry);reg=json.loads(p.read_text());reg.update(registry_schema='review-channel-registry/v5',execution_ports=[self.registration],model_mappings=[self.mapping]);p.write_text(json.dumps(reg))
        self.repo.commit('synthetic product registration only')
    def configure_archive(self):
        primary=Path(self.engine.tmp_root)/'primary';backup=Path(self.engine.tmp_root)/'backup';primary.mkdir();backup.mkdir()
        self.archive=E.initialize(self.repo.root,'synthetic-product',primary,backup)
        ref=self.archive.publish('inventory',None,None,{'inventory.json':(E.canonical(dict(schema='review-archive-inventory/v1',files=[],missing=[],unclassified=[])),'other-original')})
        cutoff=self.repo.git('rev-parse','HEAD').stdout.strip()
        switch=dict(schema='review-archive-switch/v1',repository_id='synthetic-product',mode='archive-v1',implementation_commit=cutoff,legacy_commit=cutoff,inventory_ref=ref,authorized_by='Synthetic test only')
        self.repo.write('records/governance/review-channel/HarnessPlane_Review_Channel_Owner_Decisions_v1.md','# Synthetic\n\n```review-archive-switch\n'+json.dumps(switch)+'\n```\n');self.repo.commit('synthetic archive switch')
        for key,value in dict(repositoryId='synthetic-product',primaryRoot=str(primary),backupRoot=str(backup),mode='archive-v1').items():self.repo.git('config','reviewArchive.'+key,value)
    def options(self,**request_fields):
        opts=C.Options();opts.repo_root=self.repo.root;opts.request=self.repo.request('r1',**request_fields)
        if self.archive:
            path=Path(opts.request);obj=json.loads(path.read_text());obj['request_schema']='review-channel-request/v5';path.write_text(json.dumps(obj))
        return opts
    def receipts(self):
        if self.archive:
            return [json.loads(p.read_bytes()) for p in (self.archive.primary/'pending').glob('*/receipt.json')]
        return [r for _,r in self.env.receipts('r1')]
    async def run_review(self,mode='review',**fields):
        bridge=ProductReview(self.port,self.intent,lambda:[b'sk-fake-secret-value-123'])
        opts=self.options(**fields)
        code=await bridge.review(mode,opts)
        return code,bridge
    async def test_formal_runner_legacy_product_receipt_and_result_original(self):
        code,bridge=await self.run_review();self.assertEqual(code,0,(bridge.reports,bridge.diagnostics))
        r=self.receipts()[-1];self.assertEqual(RC.receipt_shape_problems(r),[])
        self.assertEqual(r['execution']['capability_suggestion'],'REVIEW_ENABLED')
        self.assertIsNone(r['evidence_storage']);self.assertEqual(r['receipt_schema'],'review-channel-receipt/v4')
        rec=self.port.current(bridge.reservations[1]);self.assertEqual(sha(base64.b64decode(rec['result_envelope'])),rec['observations'][-1]['physical_execution']['resultRef']['digest'])
    async def test_archive_formal_runner_v5_and_dual_publication(self):
        self.configure_archive();code,bridge=await self.run_review();self.assertEqual(code,0,(bridge.reports,bridge.diagnostics))
        r=self.receipts()[-1];self.assertEqual(RC.receipt_shape_problems(r),[])
        self.assertEqual(r['execution']['capability_suggestion'],'REVIEW_ENABLED')
        refs=list(self.archive.publications());self.assertTrue(any(d['kind']=='round' for _,d,_ in refs))
    async def test_probe_suggests_call_only(self):
        code,_=await self.run_review('probe');self.assertEqual(code,0)
        self.assertEqual(self.receipts()[-1]['execution']['capability_suggestion'],'CALL_ONLY')
    async def test_known_secret_request_rejected_before_host(self):
        code,_=await self.run_review(caller='sk-fake-secret-value-123');self.assertEqual(code,1)
        self.assertEqual(self.receipts()[-1]['failure_code'],'secret-in-input');self.assertEqual(self.host.methods,[])
    async def test_unknown_failure_never_reemits_or_qualifies(self):
        self.host.mode='start-unknown';self.intent['budget']['maxRunSeconds']=1
        async def query_unknown(*args,**kw):return dict(state='unknown',reservation=self.port.current(args[0]))
        self.port.query=query_unknown
        code,_=await self.run_review();self.assertEqual(code,1)
        r=self.receipts()[-1];self.assertEqual(r['classification'],'execution_port_failure');self.assertEqual(r['verdict_validation'],'NOT_REACHED');self.assertEqual(r['execution']['capability_suggestion'],'CONFIGURED');self.assertEqual(self.host.methods.count('host.execution.start'),1)
    async def test_external_task_cancel_keeps_loop_until_receipt_and_releases_lock(self):
        self.host.mode='start-unknown'
        original=self.host.physical
        def running():
            p=original()
            if not self.host.cancelled:p.update(state='running',actualBinding=None,exit=None,resultRef=None)
            return p
        self.host.physical=running
        bridge=ProductReview(self.port,self.intent,lambda:[]);opts=self.options()
        with patch('sys.stdout',io.StringIO()),patch('sys.stderr',io.StringIO()):
            task=asyncio.create_task(bridge.review('review',opts))
            for _ in range(150):
                if self.host.start is not None:break
                await asyncio.sleep(.02)
            self.assertIsNotNone(self.host.start);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            await asyncio.wait_for(bridge.background,5)
        self.assertIsNone(bridge.loop);r=self.receipts()[-1]
        self.assertEqual(r['classification'],'cancelled_by_host');self.assertEqual(r['verdict_validation'],'NOT_REACHED')
        import fcntl
        with open(self.repo.path(self.repo.attempts_dir('r1'))+'/.in-progress','a') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    async def test_local_supervisor_real_worker_and_exact_program_identity(self):
        self.registration['mode']='standalone';self.registration['applicability']['executionPort']='standalone';self.mapping['allowed_sources']=['adapter-report']
        program=dict(launcher=str(Path(sys.executable).resolve()),binaryDigest=sha(Path(sys.executable).read_bytes()),version='synthetic-python-worker')
        self.registration['profile']['programIdentity']=program;self.intent['profile']=copy.deepcopy(self.registration['profile'])
        self.install_registry()
        adapter=Path(self.env.adapters)/'fake.py';s=adapter.read_text().replace('return {"tool_version": c.get("version", "fake 1.0"), "recognition": "checked"}', 'return {"binary": '+repr(program['launcher'])+', "tool_version": '+repr(program['version'])+', "recognition": "checked"}');adapter.write_text(s)
        self.port=LocalExecutionPort(self.domain,self.host.context['controlGeneration'],self.repo.root,self.root/'spool',self.registration,self.mapping,self.discover,self.authorize)
        with patch.dict(os.environ,HOME=self.engine.tmp_root):code,bridge=await self.run_review()
        self.assertEqual(code,0,(bridge.reports,bridge.diagnostics))
        r=self.receipts()[-1];self.assertEqual(RC.receipt_shape_problems(r),[])
        self.assertEqual(r['execution']['mode'],'standalone');self.assertEqual(r['execution']['physical_observations'][-1]['physical_execution']['observationCompleteness'],'partial')
        self.assertTrue(self.port.current(bridge.reservations[1])['protected'])

    async def test_local_program_mismatch_refuses_before_adapter_run(self):
        self.registration['mode']='standalone';self.registration['applicability']['executionPort']='standalone';self.mapping['allowed_sources']=['adapter-report']
        real=str(Path(sys.executable).resolve());program=dict(launcher=real,binaryDigest='0'*64,version='synthetic-python-worker')
        self.registration['profile']['programIdentity']=program;self.intent['profile']=copy.deepcopy(self.registration['profile']);self.install_registry()
        marker=self.root/'adapter-called';adapter=Path(self.env.adapters)/'fake.py';s=adapter.read_text().replace('return {"tool_version": c.get("version", "fake 1.0"), "recognition": "checked"}', 'return {"binary": '+repr(real)+', "tool_version": "synthetic-python-worker", "recognition": "checked"}').replace('def run(ctx):','def run(ctx):\n    open('+repr(str(marker))+', "w").write("called")')
        adapter.write_text(s)
        self.port=LocalExecutionPort(self.domain,self.host.context['controlGeneration'],self.repo.root,self.root/'spool',self.registration,self.mapping,self.discover,self.authorize)
        with patch.dict(os.environ,HOME=self.engine.tmp_root):code,bridge=await self.run_review()
        self.assertEqual(code,1);self.assertFalse(marker.exists());self.assertEqual(self.receipts()[-1]['classification'],'execution_port_failure')
        self.assertEqual(self.receipts()[-1]['execution']['capability_suggestion'],'CONFIGURED')

    async def test_round_scope_overlapping_threads_same_key_and_exception(self):
        import threading,fcntl
        self.configure_archive();key='tasks/gov-t1/reviews/impl-r9'
        first=threading.Event();overlap=threading.Event();released=threading.Event();errors=[]
        def one():
            try:
                with E.lock_scope():self.archive.lock(key);first.set();overlap.wait(3)
                released.set()
            except BaseException as exc:errors.append(exc);released.set()
        def two():
            try:
                first.wait(3)
                with E.lock_scope():overlap.set();released.wait(3);self.archive.lock(key)
            except BaseException as exc:errors.append(exc)
        a=threading.Thread(target=one);b=threading.Thread(target=two);a.start();b.start();a.join(5);b.join(5)
        self.assertFalse(a.is_alive() or b.is_alive());self.assertEqual(errors,[])
        with E.lock_scope():self.archive.lock(key)
        with self.assertRaises(RuntimeError):
            with E.lock_scope():self.archive.lock(key);raise RuntimeError('synthetic exception')
        with E.lock_scope():self.archive.lock(key)

if __name__=='__main__':unittest.main()
