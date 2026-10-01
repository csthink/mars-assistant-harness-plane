"""Actual execution code and Git transactions; synthetic Host, no model call."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from execution.host import HostExecutionPort, host_program_identity
from execution.port import ExecutionAuthorization, ExecutionDiscovery, ExecutionError, identity, sha
from execution.materials import sealed_materials
from make_fixture import create
from git_domain import GitDomain


def fixtures(scope, generation):
    digest='8061614dbefcbb03bab19bb15b2c23a1427d4555ffadd06ea859bed8b83a5d63'
    profile=dict(id='review/codex-native-readonly',version='1',digest=digest,trustModel='current-user',purpose='review',programIdentity=dict(launcher='/synthetic/codex',binaryDigest='e'*64,version='synthetic'),nativeApprovalPolicy='expected-range-gate',configurationDigest=digest,capabilities=['read-only'],limitations=['current-user'],operations=['review'],maxContextBytes=1048576,maxToolCalls=20,maxRunSeconds=600)
    mapping=dict(id='codex-native',revision=1,provider='codex-builtin',model_ref='gpt-6-sol',actual_models=['gpt-6-sol'],model_vendor='OpenAI',route_vendor=None,allowed_sources=['protocol-init','protocol-result'])
    app=dict(executionPort='embedded',purpose='review',trustModel='current-user',profileDigest=digest,configurationRevision='7',credentialRevision='2')
    reg=dict(id='codex-review-host',mode='embedded',profile=profile,provider=mapping['provider'],model_ref=mapping['model_ref'],transport='builtin',effort='high',mapping_id=mapping['id'],approval_policy=profile['nativeApprovalPolicy'],applicability=app,capability=dict(status='CONFIGURED',evidence=None))
    binding=dict(profileDigest=digest,agent='codex',model='gpt-6-sol',modelVendor='OpenAI',routeVendor=None,credentialRef='credential:codex',configurationRevision='7')
    intent=dict(portId=reg['id'],executionRequestId='review-request:one',resourceHandle='resource:one',scopeRef=scope,domainOperationId='domain:one',domainNodeRef='node:one',controlGeneration=generation,executionBinding=binding,profile=profile,connectionRef='connection:independent-id',credentialRevision='2',transport='builtin',effort='high',constraints=[],grantRefs=[dict(id='grant:one',revision='1')],decisionRef='decision:one',budget=dict(maxToolCalls=2,maxRunSeconds=60),caller='hp-review',invocation_authorization='decision:one / synthetic scope',formal_review_authorized_by_owner=True)
    return reg,mapping,intent


class SyntheticHost:
    def __init__(self,generation):
        self.context=dict(controlGeneration=generation);self.methods=[];self.start=None;self.captured=None;self.mode=None;self.cancelled=False;self.preflight_checks=None
    async def call(self,method,p):
        self.methods.append(method)
        if method=='host.execution.preflight':return dict(status='supported',checks=self.preflight_checks if self.preflight_checks is not None else [dict(id='program-identity/v1',passed=True,detail=json.dumps(self.program_identity,sort_keys=True,separators=(',',':')))])
        if method=='host.context.capture':
            self.captured=dict(**{k:p[k] for k in ('scopeRef','domainOperationId','operationId','requestDigest')},status='succeeded',snapshots=[dict(source=copy.deepcopy(x),snapshot=dict(x,authority='host',resourceHandle='snapshot:'+str(n))) for n,x in enumerate(p['sources'])])
            if self.mode=='capture-unknown':raise TimeoutError()
            return self.captured
        if method=='host.context.get':return self.captured
        if method=='host.execution.start':
            self.start=copy.deepcopy(p)
            if self.mode=='start-unknown':raise TimeoutError()
            return self.operation()
        if method=='host.operation.get':return self.operation()
        if method=='host.execution.cancel':self.cancelled=True;return self.operation()
        if method=='host.execution.get':return self.physical()
        if method=='host.resource.read':
            b=self.result_bytes();chunk=b[p['offset']:p['offset']+p['length']]
            if self.mode=='bad-body':chunk=b'X'+chunk[1:]
            return dict(offset=p['offset'],dataBase64=base64.b64encode(chunk).decode(),eof=p['offset']+len(chunk)==len(b))
        raise AssertionError(method)
    def operation(self):
        s=self.start
        return dict(scopeRef=s['scopeRef'],operationId=s['operationId'],requestDigest='f'*64 if self.mode=='wrong-digest' else s['requestDigest'],executionRef='execution:one')
    def actual(self):return dict(model='gpt-6-sol',observedModels=['gpt-6-sol'],source='protocol-result')
    def result_bytes(self):
        s=self.start;answer='PROBE-OK'
        e=dict(answer=answer,answerBytes=len(answer),answerDigest=sha(answer.encode()),readback=dict(modelProvider='openai'),programIdentity=copy.deepcopy(self.program_identity))
        if self.mode=='bad-answer':e['answerDigest']='0'*64
        out=dict(**{k:s[k] for k in ('operationId','profileId','profileDigest')},executionRef='execution:one',actualBinding=self.actual(),outcome='completed',evidence=e)
        if self.mode=='bad-outer':out['operationId']='start:wrong'
        return json.dumps(out).encode()
    def physical(self):
        s=self.start;raw=self.result_bytes()
        return dict(scopeRef=s['scopeRef'],executionRef='execution:one',connectionRef=s['connectionRef'],model=s['model'],configurationRevision=s['configurationRevision'],requestIdentity={k:s[k] for k in ('operationId','requestDigest','profileDigest')},state='failed' if self.cancelled else 'completed',stopReason='cancelled' if self.cancelled else None,supervisor=None,approvalDecisionRefs=[],accounting=None,reason='synthetic',exit=dict(code=0,signal=None,pipesClosed=False),actualBinding=self.actual(),observationCompleteness='partial',resultRef=dict(authority='host',resourceHandle=s['resourceHandle'],scopeRef=s['scopeRef'],objectRef='execution-result:one',revision='1',mediaType='application/json',bytes=len(raw),digest=sha(raw)))


class HostExecutionCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='hp-execution-');self.root=Path(self.temp.name)
        fixture=create(self.root/'fixture');self.seed=json.loads((self.root/'fixture/seed.json').read_text())
        self.domain=GitDomain(self.root/'fixture/domain',self.seed);generation=self.domain.acquire_generation()
        self.registration,self.mapping,self.intent=fixtures(fixture['scopeRef'],generation)
        self.host=SyntheticHost(generation);self.host.program_identity=copy.deepcopy(self.registration['profile']['programIdentity']);self.port=self.make_port()
        self.seal=self.root/'seal';self.seal.mkdir();(self.seal/'instruction').write_text('Original document\n')
        raw=(self.seal/'instruction').read_bytes();inputs=[dict(bundle_name='instruction',bytes=len(raw),sha256=sha(raw))]
        self.manifest=dict(inputs=inputs,manifest_sha256=sha(json.dumps(inputs,sort_keys=True,separators=(',',':')).encode()))
    def tearDown(self):self.temp.cleanup()
    def make_port(self):
        async def discover():return ExecutionDiscovery(copy.deepcopy(self.registration['profile']),self.intent['connectionRef'],'codex-builtin','openai','7')
        async def authorize(i):return ExecutionAuthorization(identity(i),sha(i['invocation_authorization'].encode()),i['caller'],('Anthropic',),('author:one',),True,2,'authorization:one')
        port=HostExecutionPort(self.host,self.domain,self.registration,self.mapping,discover,authorize)
        port.bind_result_scanner(self,lambda:[])
        return port
    def reserve(self):return self.port.reserve(self.intent,self.seal,b'Review these files',self.manifest)
    async def test_identity_check_missing_duplicate_failed_or_malformed_stops_before_start(self):
        good=dict(id='program-identity/v1',passed=True,detail=json.dumps(self.host.program_identity,sort_keys=True,separators=(',',':')))
        cases=[[],[good,good],[dict(good,passed=False)],[dict(good,detail='not-json')],
               [dict(good,detail=json.dumps(self.host.program_identity))],
               [dict(good,detail=json.dumps(dict(self.host.program_identity,binaryDigest='bad'),sort_keys=True,separators=(',',':')))]]
        for checks in cases:
            with self.subTest(checks=checks):
                self.host.preflight_checks=checks;self.port=self.make_port()
                with self.assertRaises(ExecutionError) as error:await self.port.execute(self.reserve())
                self.assertEqual(error.exception.code,'execution-port-identity-unverified')
                self.assertNotIn('host.execution.start',self.host.methods)
    async def test_identity_changes_between_preflights_stop_before_start(self):
        original=self.host.call;count=0
        async def switch(method,params):
            nonlocal count
            if method=='host.execution.preflight':
                count+=1
                if count==2:self.host.program_identity=dict(self.host.program_identity,version='new-version')
            return await original(method,params)
        self.host.call=switch
        with self.assertRaises(ExecutionError) as error:await self.port.execute(self.reserve())
        self.assertEqual(error.exception.code,'execution-port-identity-unverified')
        self.assertNotIn('host.execution.start',self.host.methods)
    async def assert_result_identity_rejected(self,variant):
        original=self.host.result_bytes
        def altered():
            value=json.loads(original())
            if variant=='missing':del value['evidence']['programIdentity']
            elif variant=='malformed':value['evidence']['programIdentity']['binaryDigest']='not-a-digest'
            else:value['evidence']['programIdentity']['version']='different-version'
            return json.dumps(value).encode()
        self.host.result_bytes=altered
        with self.assertRaises(ExecutionError) as error:await self.port.execute(self.reserve())
        self.assertEqual(error.exception.code,'execution-port-identity-unverified')
    async def test_result_identity_missing_is_rejected(self):await self.assert_result_identity_rejected('missing')
    async def test_result_identity_malformed_is_rejected(self):await self.assert_result_identity_rejected('malformed')
    async def test_result_identity_different_is_rejected(self):await self.assert_result_identity_rejected('different')
    async def test_distinct_ids_material_roles_actual_instruction_hash_and_once(self):
        r=self.reserve();result=await self.port.execute(r)
        self.assertEqual(result['answer'],b'PROBE-OK');self.assertTrue(result['reservation']['protected'])
        sources=r['capture']['sources'];self.assertEqual(sources[0]['objectRef'],'instruction');self.assertTrue(sources[1]['objectRef'].startswith('material:'))
        self.assertEqual(r['instruction_sha256'],sources[0]['digest'])
        await self.port.execute(r);self.assertEqual(self.host.methods.count('host.execution.start'),1)
    async def test_cancel_capture_never_starts(self):
        r=self.reserve();self.port.update(r,lambda x:x.update(phase='capturing'))
        with self.assertRaises(ExecutionError) as error:await self.port.cancel(r)
        self.assertEqual(error.exception.classification,'cancelled_by_host')
        with self.assertRaises(ExecutionError):await self.port.query(r)
        self.assertEqual(self.host.methods,[])
    async def test_cancel_unknown_start_queries_original_and_cancels(self):
        r=self.reserve();self.host.mode='start-unknown';result=await self.port.execute(r)
        self.assertEqual(result['state'],'unknown')
        with self.assertRaises(ExecutionError) as error:await self.port.cancel(r)
        self.assertEqual(error.exception.classification,'cancelled_by_host')
        self.assertEqual(self.host.methods.count('host.execution.start'),1);self.assertEqual(self.host.methods.count('host.execution.cancel'),1)
    async def test_restart_new_generation_keeps_original_identity(self):
        r=self.reserve();self.host.mode='start-unknown';await self.port.execute(r);old=copy.deepcopy(self.host.start)
        self.domain=GitDomain(self.root/'fixture/domain',self.seed);self.host.context['controlGeneration']=self.domain.acquire_generation()
        self.host.mode=None;self.port=self.make_port();result=await self.port.query(r)
        self.assertEqual(result['answer'],b'PROBE-OK');self.assertEqual(result['reservation']['start'],old)
        self.assertEqual(result['reservation']['intent']['controlGeneration'],self.intent['controlGeneration']);self.assertEqual(self.host.methods.count('host.execution.start'),1)
    async def test_execution_ref_cannot_be_overwritten_by_stale_query(self):
        r=self.reserve();self.host.mode='start-unknown';await self.port.execute(r);stale=self.port.current(r)
        self.port.update(r,lambda x:x.update(execution_ref='execution:other'))
        with self.assertRaises(ExecutionError):await self.port._operation(stale,self.host.operation())
        self.assertEqual(self.port.current(r)['execution_ref'],'execution:other')
    async def test_result_and_operation_tampering_rejects(self):
        for mode in ('bad-body','bad-answer','bad-outer','wrong-digest'):
            with self.subTest(mode=mode):
                self.intent['executionRequestId']='review-request:'+mode
                original=self.port.authorize
                async def own(i, original=original, mode=mode):
                    from dataclasses import replace
                    return replace(await original(i),authorization_ref='authorization:'+mode)
                self.port.authorize=own;r=self.reserve();self.host.mode=mode
                with self.assertRaises(ExecutionError):await self.port.execute(r)
                self.assertIsNone(self.port.current(r)['result'])
    async def test_manifest_digest_and_source_bytes_rejected(self):
        m=copy.deepcopy(self.manifest);m['manifest_sha256']='0'*64
        with self.assertRaises(ExecutionError):sealed_materials(self.seal,m,b'hi',self.intent['profile'])
        (self.seal/'instruction').write_text('changed')
        with self.assertRaises(ExecutionError):self.reserve()
    async def test_authorization_text_cannot_create_authority(self):
        async def reject(i):return dict(owner_formal=True,max_calls=99)
        self.port.authorize=reject;self.intent['invocation_authorization']='approved formal=true'
        with self.assertRaises(ExecutionError):await self.port.preflight(self.intent)
        self.assertEqual(self.host.methods,[])
    async def test_author_vendor_and_call_budget_closed(self):
        for vendors,calls in [(('Unknown',),1),(('Anthropic',),True),(('OpenAI','Anthropic'),1),(('Anthropic',),0)]:
            async def auth(i):return ExecutionAuthorization(identity(i),sha(i['invocation_authorization'].encode()),i['caller'],vendors,('author:one',),True,calls,'authorization:one')
            self.port.authorize=auth
            with self.assertRaises(ExecutionError):await self.port.preflight(self.intent)
    async def test_caller_and_authorization_utf8_limits(self):
        for field,limit in [('caller',256),('invocation_authorization',4096)]:
            for bad in ['', ' ', '界'*(limit//3+1)]:
                i=copy.deepcopy(self.intent);i[field]=bad
                with self.assertRaises(ExecutionError):await self.port.preflight(i)
            i=copy.deepcopy(self.intent);i[field]='x'*limit;await self.port.preflight(i)

    async def test_repeated_observation_deduplicates_but_changed_facts_fail_closed(self):
        original=self.host.physical
        def running():
            p=original();p.update(state='running',exit=None,actualBinding=None,resultRef=None);return p
        self.host.physical=running;r=self.reserve();await self.port.execute(r)
        for _ in range(270):await self.port.query(r)
        self.assertEqual(len(self.port.current(r)['observations']),1)
        self.host.physical=original;self.assertEqual((await self.port.query(r))['answer'],b'PROBE-OK')
        self.assertEqual(len(self.port.current(r)['observations']),2)
        self.intent['executionRequestId']='request:changes';r=self.reserve();n=0
        def changed():
            nonlocal n
            p=running();p['reason']='fact:'+str(n);n+=1;return p
        self.host.physical=changed;await self.port.execute(r)
        for _ in range(255):await self.port.query(r)
        with self.assertRaises(ExecutionError) as error:await self.port.query(r)
        self.assertEqual(error.exception.code,'execution-port-observation-incomplete')
        current=self.port.current(r);self.assertEqual(len(current['observations']),256);self.assertTrue(current['protected'])
        self.assertEqual(self.host.methods.count('host.execution.start'),2)
        old_start=copy.deepcopy(current['start'])
        from unittest.mock import patch
        with patch.object(self.domain,'save',side_effect=RuntimeError('synthetic persistence failure')),self.assertRaises(RuntimeError):await self.port.checkpoint_observations(r)
        self.assertEqual(self.port.current(r)['observations'],current['observations']);self.assertNotIn('observation_history',self.port.current(r))
        resumed=await self.port.checkpoint_observations(r)
        self.assertEqual(resumed['observations'],[]);self.assertEqual(resumed['start'],old_start)
        history=self.port.historical_observations(r);self.assertEqual(len(history[0]['observations']),256)
        self.host.physical=original;self.assertEqual((await self.port.query(r))['answer'],b'PROBE-OK')
        self.assertEqual(self.host.methods.count('host.execution.start'),2);self.assertTrue(self.port.current(r)['protected'])

    async def test_material_snapshot_identity_rejected(self):
        for field in ('objectRef','revision','scopeRef','digest','bytes','mediaType'):
            r=self.reserve();self.port.update(r,lambda x:x.update(phase='capturing'))
            result=await self.host.call('host.context.capture',r['capture'])
            result['snapshots'][0]['snapshot'][field]=0 if field=='bytes' else 'wrong'
            with self.assertRaises(ExecutionError):await self.port._captured(r,result)
        self.assertNotIn('host.execution.start',self.host.methods)

    async def test_persistent_authorization_budget_and_human_only(self):
        from dataclasses import replace
        original=self.port.authorize
        async def human(i):return replace(await original(i),author_vendors=(),human_only=True)
        self.port.authorize=human
        for n in range(2):
            self.intent['executionRequestId']='request:'+str(n);await self.port.execute(self.reserve())
        self.intent['executionRequestId']='request:third';r=self.reserve()
        with self.assertRaises(ExecutionError) as error:await self.port.execute(r)
        self.assertEqual(error.exception.code,'execution-port-capability-unverified')
        self.assertEqual(self.host.methods.count('host.execution.start'),2)
        async def unproven(i):return replace(await human(i),author_evidence_refs=())
        self.port.authorize=unproven
        with self.assertRaises(ExecutionError):await self.port.preflight(self.intent)

    async def test_shared_port_scanner_cannot_be_rebound(self):
        from execution.bridge import ProductReview
        port=HostExecutionPort(self.host,self.domain,self.registration,self.mapping,self.port.discover,self.port.authorize)
        first=ProductReview(port,self.intent,lambda:[b'PROBE-OK'])
        with self.assertRaises(ExecutionError):ProductReview(port,self.intent,lambda:[b'other'])
        r=port.reserve(self.intent,self.seal,b'Review',self.manifest)
        with self.assertRaises(ExecutionError) as error:await port.execute(r)
        self.assertEqual(error.exception.code,'secret-leak');self.assertIsNone(port.current(r)['result']);self.assertNotIn('result_envelope',port.current(r))
        self.assertEqual(first.scan_set(),[b'PROBE-OK'])

    async def test_physical_and_escaped_answer_known_secret_never_persisted(self):
        for location in ('physical','answer'):
            port=HostExecutionPort(self.host,self.domain,self.registration,self.mapping,self.port.discover,self.port.authorize)
            port.bind_result_scanner(self,lambda:[b'known-secret-value'])
            self.intent['executionRequestId']='secret:'+location
            original_physical=self.host.physical;original_result=self.host.result_bytes
            if location=='physical':
                def physical():
                    p=original_physical();p['reason']='known-secret-value';return p
                self.host.physical=physical
            else:
                def result():
                    doc=json.loads(original_result());answer='known-secret-value';doc['evidence'].update(answer=answer,answerBytes=len(answer),answerDigest=sha(answer.encode()))
                    return json.dumps(doc).replace('known-secret-value',''.join('\\u%04x'%ord(c) for c in answer)).encode()
                self.host.result_bytes=result
            r=port.reserve(self.intent,self.seal,b'Review',self.manifest)
            with self.assertRaises(ExecutionError) as error:await port.execute(r)
            self.assertEqual(error.exception.code,'secret-leak');record=port.current(r)
            self.assertIsNone(record['result']);self.assertNotIn('result_envelope',record)
            self.assertNotIn('known-secret-value',json.dumps(self.domain.read()))
            if location=='physical':self.assertEqual(record['observations'],[])
            self.host.physical=original_physical;self.host.result_bytes=original_result

    async def test_reservation_same_identity_and_changed_identity_conflict(self):
        first=self.reserve();second=self.reserve();self.assertEqual(first,second)
        changed=copy.deepcopy(self.intent);changed['caller']='different'
        with self.assertRaises(ExecutionError):self.port.reserve(changed,self.seal,b'Review these files',self.manifest)
        self.assertEqual(self.host.methods,[]);self.assertEqual(len(self.domain.read()['executionReservations']),1)

if __name__=='__main__':unittest.main()
