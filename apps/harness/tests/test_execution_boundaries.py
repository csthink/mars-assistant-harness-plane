"""Exact fixed J-06 policies, current structure and product evidence boundaries.

No live program discovery, model or product qualification is asserted by fixtures.
"""
import base64
import copy
import json
from pathlib import Path
import re
import shutil
import unittest
from unittest.mock import patch
import test_execution_port as EP
import test_execution_review as ER
from execution.port import ExecutionError,sha
from execution.host import HostExecutionPort
from execution.bridge import ProductReview,MECHANISM
import review_channel_base as B
import review_channel_contract as C
import review_channel_execution as X
import review_channel_receipt as RC
import review_evidence as E
import instance_area

ROOT=MECHANISM.parent.parent
J06='records/diagnostics/feature-t17/2026-09-21/inputs/assistant/docs/design/host-execution-facts-j06.md'
INVENTORY='records/governance/task-artifact-schema/HarnessPlane_Task_Tree_Alignment_Inventory_v1.json'

def j06_profiles(program):
    # Fixed Appendix A, r2. ProgramIdentity is explicitly synthetic/current input.
    common=dict(version='1',trustModel='current-user',programIdentity=program,maxToolCalls=20,maxRunSeconds=600)
    reviewer=dict(common,id='review/codex-native-readonly',digest='8061614dbefcbb03bab19bb15b2c23a1427d4555ffadd06ea859bed8b83a5d63',purpose='review',nativeApprovalPolicy='expected-range-gate',capabilities=['read-only','native-approval','effort'],limitations=['no-write','no-network','no-mcp','no-subagents','single-turn','one-approval'],operations=['review'],maxContextBytes=8388608)
    implementer=dict(common,id='coding-implementer/claude-print-restricted',digest='2c9583da0f4101cc04e86251d85ba15c3a2bc9d6fda024f8d79081566744f16c',purpose='coding-implementer',nativeApprovalPolicy='auto-deny',capabilities=['tool:Read','tool:Edit','tool:Write','effort'],limitations=['no-shell','no-network-tools','no-mcp','no-prompts','cwd-confined'],operations=['implement'],maxContextBytes=4194304)
    for p in (reviewer,implementer):p['configurationDigest']=p['digest']
    return reviewer,implementer

class IdentityCases(unittest.IsolatedAsyncioTestCase):
    make_port=EP.HostExecutionCases.make_port
    setUp=EP.HostExecutionCases.setUp
    tearDown=EP.HostExecutionCases.tearDown
    @instance_area.needed
    async def test_exact_j06_r2_and_every_profile_field_mismatch(self):
        reviewer,implementer=j06_profiles(self.intent['profile']['programIdentity'])
        text=instance_area.path(J06).read_text()
        for p in (reviewer,implementer):
            self.assertIn(p['digest'],text);self.assertTrue(X.profile(p))
            self.assertEqual(p['configurationDigest'],p['digest'])
        self.registration['id']='embedded';self.registration['profile']=reviewer
        self.intent.update(portId='embedded',profile=copy.deepcopy(reviewer))
        self.intent['executionBinding']['agent']='agent:codex';self.port=self.make_port()
        await self.port.preflight(self.intent)
        for field,value in reviewer.items():
            wrong=copy.deepcopy(self.intent)
            if isinstance(value,str):wrong['profile'][field]=value+'-changed'
            elif isinstance(value,int):wrong['profile'][field]=value+1
            elif isinstance(value,list):wrong['profile'][field]=value+['unexpected']
            else:wrong['profile'][field]['version']='new-unverified'
            with self.subTest(field=field),self.assertRaises(ExecutionError):await self.port.preflight(wrong)
        for field,value in [('portId','other'),('transport','http'),('effort','low'),('credentialRevision','9')]:
            wrong=copy.deepcopy(self.intent);wrong[field]=value
            with self.subTest(field=field),self.assertRaises(ExecutionError):await self.port.preflight(wrong)
        for field,value in [('model','model:unknown'),('modelVendor','Anthropic'),('configurationRevision','9'),('routeVendor','Zhipu')]:
            wrong=copy.deepcopy(self.intent);wrong['executionBinding'][field]=value
            with self.subTest(field=field),self.assertRaises(ExecutionError):await self.port.preflight(wrong)
        old=copy.deepcopy(self.intent);old['profile']['digest']='5bb506537410fc36347f5b66c6cf4b6d3d4dbe1dc14b60580bf4cd25898e9062'
        with self.assertRaises(ExecutionError):await self.port.preflight(old)
        self.registration['profile']=implementer;self.registration['approval_policy']='auto-deny';self.intent['profile']=copy.deepcopy(implementer);self.port=self.make_port()
        with self.assertRaises(ExecutionError) as exc:await self.port.preflight(self.intent)
        self.assertEqual(exc.exception.code,'execution-port-purpose-mismatch')
        self.assertNotIn('host.execution.start',self.host.methods)
    async def test_missing_scanner_and_barrier_prevent_start(self):
        port=HostExecutionPort(self.host,self.domain,self.registration,self.mapping,self.port.discover,self.port.authorize)
        with self.assertRaises(ExecutionError):await port.preflight(self.intent)
        self.assertEqual(self.host.methods,[])
        self.domain.transaction(self.host.context['controlGeneration'],lambda s:s.update(barrier={'synthetic':True}))
        from runtime.protocol import Fault
        with self.assertRaises(Fault):self.port.reserve(self.intent,self.seal,b'instruction',self.manifest)
        self.assertEqual(self.domain.read().get('executionReservations',{}),{})
        self.assertEqual(self.host.methods,[])

class DefinitionCases(unittest.TestCase):
    @instance_area.needed
    def test_definition_matrix_exact_bytes_and_legacy_inventory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target='tasks/feature-t17/feature-t17.md';file=root/target;file.parent.mkdir(parents=True)
            lint=root/'mechanisms/artifact-templates/artifact_lint.py';lint.parent.mkdir(parents=True);shutil.copy(ROOT/'mechanisms/artifact-templates/artifact_lint.py',lint)
            raw=instance_area.path(target).read_bytes();rq=dict(stage='task',task_record='feature-t17',inputs=dict(candidates=[target]))
            X.check_definition(root,rq,{target:raw})
            changes=[raw.replace(b'## Goal\n',b'## Removed\n'),raw.replace(b'## Goal\n',b'## Goal\n\n## Goal\n'),raw.replace(b'## Goal Conditions',b'## Scope In',1),raw.replace(b'Task record ID: `feature-t17`',b'Task record ID: `feature-t999`'),raw.replace(b'feature-t17',b'feature-t01'),raw.replace(b'- Product line:',b'- Wrong:')]
            for changed in changes:
                with self.assertRaises(B.PreflightError):X.check_definition(root,rq,{target:changed})
            # A working tree cannot add itself to historical legacy-v0 inventory.
            file.write_bytes(b'# no required headings\n');inv=root/'records/governance/task-artifact-schema/HarnessPlane_Task_Tree_Alignment_Inventory_v1.json';inv.parent.mkdir(parents=True)
            inv.write_text(json.dumps(dict(task_record_summaries={'feature-t17':dict(profile='legacy-v0',definition=dict(path=target,identity=dict(bytes=file.stat().st_size,sha256=sha(file.read_bytes()))))})))
            with self.assertRaises(B.PreflightError):X.check_definition(root,rq,{target:file.read_bytes()})
        # Accepted historical bytes remain readable and unchanged.
        # check_definition reads the inventory at its product-line location under the root it is given.
        inventory=instance_area.path(INVENTORY)
        data=json.loads(inventory.read_bytes());count=0
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/INVENTORY).parent.mkdir(parents=True);shutil.copy(inventory,root/INVENTORY)
            for rid,item in data['task_record_summaries'].items():
                path=item.get('definition',{}).get('path','')
                if item.get('profile')=='legacy-v0' and path and instance_area.path(path).is_file():
                    old=instance_area.path(path).read_bytes();X.check_definition(root,dict(stage='task',task_record=rid,inputs=dict(candidates=[path])),{path:old});self.assertEqual(instance_area.path(path).read_bytes(),old);count+=1;break
        self.assertEqual(count,1)

class SchemaCases(unittest.TestCase):
    def test_projection_equals_frozen_and_nested_malformed_rejects(self):
        source=json.loads((ROOT/'apps/harness/contract/schema.json').read_bytes())
        projection=json.loads((MECHANISM/'review_channel_execution_schema.json').read_bytes())
        for name,value in projection['definitions'].items():self.assertEqual(value,source['definitions'][name])
        self.assertTrue(X.execution_problems(dict.fromkeys(X.EXECUTION_KEYS)))
        for value in (None,{},[],True,'x'):
            self.assertFalse(X.applicability(value))

class ProductBoundaryCases(unittest.IsolatedAsyncioTestCase):
    make_port=ER.ReviewCases.make_port
    setUp=ER.ReviewCases.setUp
    tearDown=ER.ReviewCases.tearDown
    install_registry=ER.ReviewCases.install_registry
    configure_archive=ER.ReviewCases.configure_archive
    options=ER.ReviewCases.options
    receipts=ER.ReviewCases.receipts
    run_review=ER.ReviewCases.run_review
    def fresh_bridge(self):
        self.port=HostExecutionPort(self.host,self.domain,self.registration,self.mapping,self.discover,self.authorize)
        self.port.bind_context=lambda intent,ctx:setattr(self,'current_context',ctx)
        return ProductReview(self.port,self.intent,lambda:[b'sk-fake-secret-value-123'])
    async def test_archive_previous_bad_shapes_sources_and_request_version(self):
        self.configure_archive()
        badrefs=[[],dict(kind='unknown'),dict(kind='archive'),dict(kind='archive',repository_id='different-repository',object_sha256='1'*64),dict(kind='archive',repository_id='synthetic-product',object_sha256='2'*64)]
        for ref in badrefs:
            opts=self.options();path=Path(opts.request);obj=json.loads(path.read_bytes());obj.update(round='r2',previous_round=dict(evidence=ref,response=None),remediation_statement='synthetic correction');path.write_text(json.dumps(obj));original=path.read_bytes()
            bridge=self.fresh_bridge();code=await bridge.review('review',opts);self.assertEqual(code,1,(bridge.reports,bridge.diagnostics))
            report=bridge.reports[-1]
            completed=json.loads((Path(report['receipt']).parent/'publication-completed.json').read_bytes())
            source=dict(kind='archive',repository_id=self.archive.repository_id,object_sha256=completed['object_sha256'])
            d,files=self.archive.read(source);self.assertEqual(d['kind'],'attempt');self.assertEqual(d['parents'],[])
            self.assertIn(original,files.values());r=json.loads(E.role_file(d,files,'receipt')[1]);self.assertEqual(r['verdict_validation'],'NOT_REACHED');self.assertFalse(r['verdict_published'])
        opts=self.options();path=Path(opts.request);obj=json.loads(path.read_bytes());obj['request_schema']='review-channel-request/v4';path.write_text(json.dumps(obj))
        bridge=self.fresh_bridge();self.assertEqual(await bridge.review('review',opts),1)
        self.assertEqual(self.host.methods,[])
    async def test_product_result_failure_matrix_and_reemit_budget(self):
        from dataclasses import replace
        for case in ('empty','failed','secret','post-proven','reemit-budget'):
            # Independent r1 attempt and authorization identity, same long-lived Runtime.
            self.intent['executionRequestId']='boundary:'+case
            self.intent['invocation_authorization']='selftest:OD-01'
            self.env.control(behavior='empty' if case=='empty' else 'secret-leak' if case=='secret' else 'truncated' if case in ('post-proven','reemit-budget') else 'valid',reemit='valid')
            self.host.methods=[];original=self.host.physical
            def physical(original=original,case=case):
                p=original()
                if case=='failed' or (case=='post-proven' and self.current_context['call_index']==2):p.update(state='failed',stopReason='execution_failed',exit=dict(code=1,signal=None,pipesClosed=False),resultRef=None)
                return p
            self.host.physical=physical
            prior=self.authorize
            async def authorize(i,case=case,prior=prior):return replace(await prior(i),authorization_ref='authorization:'+case,max_calls=1 if case=='reemit-budget' else 2)
            self.authorize=authorize;bridge=self.fresh_bridge();opts=self.options()
            code=await bridge.review('review',opts);self.assertEqual(code,1,(case,bridge.reports,bridge.diagnostics))
            receipt=next(r for r in self.receipts() if r['attempt_id']==bridge.reports[-1]['attempt_id'])
            self.assertFalse(receipt['verdict_published']);self.assertEqual(receipt['execution']['capability_suggestion'],'CONFIGURED')
            self.assertEqual(self.host.methods.count('host.execution.start'),2 if case=='post-proven' else 1)
            if case in ('failed','post-proven','reemit-budget'):self.assertEqual(receipt['classification'],'execution_port_failure');self.assertEqual(receipt['verdict_validation'],'NOT_REACHED')
            if case=='post-proven':self.assertEqual(receipt['effective_profile']['calls'][0]['call_path_proof'],'PROVEN')
            self.host.physical=original;self.authorize=prior
    async def test_registry_exact_archived_tuple_and_version_matrix(self):
        self.configure_archive();code,bridge=await self.run_review();self.assertEqual(code,0,(bridge.reports,bridge.diagnostics))
        report=bridge.reports[-1];ref=report['source'];d,files=self.archive.read(ref);rp,raw=E.role_file(d,files,'receipt');receipt=json.loads(raw)
        formal='records/governance/review-channel/synthetic-product-result.md'
        self.repo.write(formal,'# Synthetic result, no real qualification\n\n```review-result\n'+json.dumps(report['review_result'])+'\n```\n');self.repo.commit('synthetic fixed result')
        port=copy.deepcopy(self.registration);port['capability']=dict(status='REVIEW_ENABLED',evidence=dict(kind='archive',ref=ref,receipt_path=rp,receipt_sha256=sha(raw),decision=dict(commit=self.repo.git('rev-parse','HEAD').stdout.strip(),path=formal,locator='review-result')))
        X.verify_port_evidence(self.repo.root,port,self.mapping,RC.profile_shape_problems)
        mutations=[('port_id','wrong'),('mode','standalone'),('mapping_id','wrong'),('mapping_revision',99),('mapping_sha256','0'*64),('program_identity',dict(launcher='/wrong',binaryDigest='0'*64,version='wrong')),('request_digest','0'*64),('execution_ref','wrong'),('capability_suggestion','CALL_ONLY')]
        for key,value in mutations:
            altered=copy.deepcopy(receipt);altered['execution'][key]=value
            await self.reject_receipt(port,d,files,rp,altered)
        for field in ('route_provider','requested_model','transport','requested_effort','effective_effort','claimed_vendor'):
            altered=copy.deepcopy(receipt);altered['effective_profile'][field]='wrong'
            await self.reject_receipt(port,d,files,rp,altered)
        for field in ('model','modelVendor','routeVendor','configurationRevision','profileDigest'):
            altered=copy.deepcopy(receipt);altered['execution']['execution_binding'][field]='wrong'
            await self.reject_receipt(port,d,files,rp,altered)
        # Wrong serialized envelope is refused even when its transport outer digest is unchanged.
        alteredfiles=dict(files);alteredfiles['response.json']=b'{}'
        with patch.object(E,'configured',return_value=self.archive),patch.object(self.archive,'read',return_value=(d,alteredfiles)),self.assertRaises(B.PreflightError):X.verify_port_evidence(self.repo.root,port,self.mapping,RC.profile_shape_problems)
        # An archived full window is a synthetic fixture of prior physical facts.
        historic=[]
        for index in range(256):
            observation=copy.deepcopy(receipt['execution']['physical_observations'][0]);observation['physical_execution']['reason']='synthetic-history:'+str(index);observation['sha256']=sha(B.canonical_json(observation['physical_execution']));historic.append(observation)
        encoded=B.canonical_json(historic);digest=sha(encoded)
        historyref=dict(authority='runtime',resourceHandle=self.intent['resourceHandle'],scopeRef=self.intent['scopeRef'],objectRef='execution-observations:'+sha(receipt['execution']['request_id'].encode()),revision='1',mediaType='application/json',bytes=len(encoded),digest=digest)
        events=json.loads(files['runtime_events.jsonl']);events['observation_history']=[dict(evidence=historyref,observations=historic)]
        historyfiles=dict(files);historyfiles['runtime_events.jsonl']=B.canonical_json(events)
        with patch.object(E,'configured',return_value=self.archive),patch.object(self.archive,'read',return_value=(d,historyfiles)):X.verify_port_evidence(self.repo.root,port,self.mapping,RC.profile_shape_problems)
        for bad in ('missing-window','changed-fact','wrong-digest'):
            changed=copy.deepcopy(events)
            if bad=='missing-window':changed['observation_history'][0].pop('observations')
            elif bad=='changed-fact':changed['observation_history'][0]['observations'][0]['physical_execution']['reason']='altered'
            else:changed['observation_history'][0]['evidence']['digest']='0'*64
            historyfiles['runtime_events.jsonl']=B.canonical_json(changed)
            with patch.object(E,'configured',return_value=self.archive),patch.object(self.archive,'read',return_value=(d,historyfiles)),self.assertRaises(B.PreflightError):X.verify_port_evidence(self.repo.root,port,self.mapping,RC.profile_shape_problems)
        maintenance=copy.deepcopy(receipt);maintenance['execution']=None;maintenance['effective_profile']['execution_applicability']=None
        self.assertEqual(RC.receipt_shape_problems(maintenance),[])
        mixed=copy.deepcopy(maintenance);mixed['effective_profile']['profile_schema']='review-channel-effective-profile/v3';mixed['effective_profile'].pop('execution_applicability')
        self.assertTrue(RC.receipt_shape_problems(mixed))
        for version in ('review-channel-receipt/v2','review-channel-receipt/v3'):
            old=copy.deepcopy(mixed);old['receipt_schema']=version;old.pop('execution')
            if version.endswith('v2'):old.pop('evidence_storage')
            self.assertEqual(RC.receipt_shape_problems(old),[])
            for classification,code in [('cancelled_by_host','cancelled_by_host'),('execution_port_failure','execution-port-profile-mismatch')]:
                bad=copy.deepcopy(old);bad.update(classification=classification,failure_code=code);self.assertTrue(RC.receipt_shape_problems(bad))
        # Product Host evidence cannot be consumed by a standalone port or vice versa.
        wrong=copy.deepcopy(port);wrong['mode']='standalone'
        with self.assertRaises(B.PreflightError):X.verify_port_evidence(self.repo.root,wrong,self.mapping,RC.profile_shape_problems)
    async def test_product_archive_inheritance_and_maintenance_cross_reject(self):
        self.configure_archive();self.env.control(behavior='valid',verdict='FAIL');code,first=await self.run_review();self.assertEqual(code,0)
        source=first.reports[-1]['source']
        decision=dict(schema='review-channel-decisions-input/v2',subject='demo',task_record='gov-t1',stage='impl',round='r1',decisions=[dict(finding_id='R1-B1',action='fix',instructions='Synthetic correction',owner_verbatim='Fix synthetic finding')],source=source,supersedes=None)
        path=Path(self.engine.tmp_root)/'response.json';path.write_text(json.dumps(decision))
        code,out,err,response=self.env.run('respond',str(path));self.assertEqual(code,0,(out,err))
        nr=response['next_round'];self.env.control(behavior='valid',verdict='PASS');self.repo.write('mechanisms/demo/HarnessPlane_Demo_Design_v1.md',self.repo.read('mechanisms/demo/HarnessPlane_Demo_Design_v1.md').decode()+'\nSynthetic correction.\n');request=self.repo.request('r2',request_schema='review-channel-request/v5',previous=dict(evidence=source,response=response['source']),remediation=nr['remediation_statement']+'\nSynthetic followup.',residuals=nr['accepted_residuals'])
        opts=self.options();opts.request=request;self.intent['executionRequestId']='review-request:r2'
        # Maintenance cannot inherit the product port's previous applicability.
        code,out,err,report=self.env.run('preflight',request)
        self.assertEqual(code,1);self.assertEqual(report['failure_code'],'inherit-unmaterializable')
        second=self.fresh_bridge();self.assertEqual(await second.review('review',opts),0,(second.reports,second.diagnostics))
        d,files=self.archive.read(second.reports[-1]['source']);receipt=json.loads(E.role_file(d,files,'receipt')[1]);self.assertEqual(receipt['execution']['capability_suggestion'],'REVIEW_ENABLED')

    async def test_definition_rejection_is_before_provider_and_host(self):
        target='tasks/gov-t1/gov-t1.md';self.repo.write(target,'# malformed task\n');self.repo.commit('malformed synthetic candidate')
        bridge=self.fresh_bridge();code=await bridge.review('review',self.options(stage='task',inputs=dict(candidates=[target],references=[])))
        self.assertEqual(code,1);self.assertEqual(bridge.reports[-1]['failure_code'],'definition-structure-invalid');self.assertEqual(self.host.methods,[])

    async def reject_receipt(self,port,d,files,rp,receipt):
        raw=B.canonical_json(receipt);p=copy.deepcopy(port);p['capability']['evidence']['receipt_sha256']=sha(raw);changed=dict(files);changed[rp]=raw
        with patch.object(E,'configured',return_value=self.archive),patch.object(self.archive,'read',return_value=(d,changed)),self.assertRaises(B.PreflightError):X.verify_port_evidence(self.repo.root,p,self.mapping,RC.profile_shape_problems)
