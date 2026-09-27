"""Actual stdio/HostClient/runner/material read path. Synthetic Host/model only."""
import asyncio
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
import test_execution_review as ER
from execution.port import sha
from runtime.protocol import DIGEST,VERSION,Fault,digest,Schemas,METHODS
import review_channel_runtime as RT
import review_channel_contract as C
import review_channel_inputs as I


class HostDriver:
    def __init__(self,case,fixture,job):
        self.case,self.fixture,self.job=case,fixture,job
        self.context=job['context'];self.methods=[];self.frames=[];self.pending={};self.serial=0;self.raw_lines=[];self.tasks=[];self.start=None;self.snapshots={};self.capture=None;self.cancelled=False;self.starts=0
        self.schemas=Schemas()
    async def write(self,frame):
        self.frames.append(dict(direction='host-to-runtime',frame=frame));self.process.stdin.write(json.dumps(frame).encode()+b'\n');await self.process.stdin.drain()
    async def call_runtime(self,method,p):
        self.serial+=1;key='h:'+str(self.serial);future=asyncio.get_running_loop().create_future();self.pending[key]=future
        await self.write(dict(jsonrpc='2.0',id=key,method=method,params=dict(context=self.context,**p)))
        return await asyncio.wait_for(future,10)
    async def reader(self):
        while line:=await self.process.stdout.readline():
            self.raw_lines.append(line.decode());frame=json.loads(line);self.frames.append(dict(direction='runtime-to-host',frame=frame))
            if frame.get('jsonrpc')!='2.0':raise AssertionError('non-RPC stdout')
            if 'method' in frame:self.tasks.append(asyncio.create_task(self.respond(frame)))
            else:
                if frame['id'] is None:raise AssertionError(frame)
                f=self.pending.pop(frame['id']);f.set_result(frame.get('result')) if 'result' in frame else f.set_exception(RuntimeError(frame['error']))
    async def respond(self,frame):
        method,p=frame['method'],frame['params'];self.methods.append(method)
        self.schemas.validate(METHODS[method]['params'],p)
        try:
            result=await self.handle(method,p)
            await self.write(dict(jsonrpc='2.0',id=frame['id'],result=dict(context=self.context,**result)))
        except Fault as exc:await self.write(dict(jsonrpc='2.0',id=frame['id'],error=exc.error(p)))
    def op(self):
        s=self.start
        return dict(scopeRef=s['scopeRef'],operationId=s['operationId'],requestDigest=s['requestDigest'],executionRef='execution:synthetic',status='accepted',resultRef=None,reason='synthetic',resultCode=None,revision='1')
    def answer(self):
        if self.job['review_mode']=='probe':return b'PROBE-OK'
        rq=json.loads(Path(self.job['request']).read_text());adapter=RT.load_adapter('fake',self.fixture.env.adapters)
        candidates=[]
        for rel in rq['inputs']['candidates']:
            name=Path(rel).name;obj='material:'+sha(name.encode())[:32]
            matches=[raw for ref,raw in self.snapshots.values() if ref['objectRef']==obj]
            if len(matches)!=1:raise AssertionError('candidate material unavailable')
            candidates.append(dict(role='candidate',bundle_name=name,sha256=sha(matches[0])))
        ctx=dict(inputs=candidates,required_question_ids=C.required_question_ids(rq['stage']),round=rq['round'],previous_finding_ids=None,subject=rq['subject'],stage=rq['stage'],residual_ids=[r['id'] for r in rq['review_brief']['accepted_residuals']],task_file=I.taskbook_filename(rq['subject'],rq['round']))
        block,narr=adapter.build_block(ctx)
        return ('```review-channel-verdict\n'+json.dumps(block)+'\n```\n\n'+narr).encode()
    def actual(self):return dict(model=self.start['model'],observedModels=[self.start['model']],source='protocol-result')
    def result(self):
        s=self.start;answer=self.answer()
        return json.dumps(dict(**{k:s[k] for k in ('operationId','profileId','profileDigest')},executionRef='execution:synthetic',actualBinding=self.actual(),outcome='completed',evidence=dict(answer=answer.decode(),answerBytes=len(answer),answerDigest=sha(answer),readback=dict(modelProvider='protocol-independent')))).encode()
    async def handle(self,method,p):
        if method=='host.grants.get':
            i=self.job['intent'];return dict(grants=[dict(ref=r,installationId=self.context['installationId'],instanceId=self.context['instanceId'],scopeRef=i['scopeRef'],resourceHandle=i['resourceHandle'],capability='hp.synthetic',operation='runtime.resource.read',executionRef=None,bundleDigest='b'*64,expiresAt='2099-01-01T00:00:00Z',status='active',purpose='synthetic material read') for r in p['grantRefs']])
        if method=='host.execution.preflight':return dict(status='supported',profileDigest=p['profileDigest'],checks=[dict(id='synthetic',passed=True,detail='No real model')],reason='synthetic')
        if method=='host.context.capture':
            snapshots=[]
            for n,source in enumerate(p['sources']):
                if source['scopeRef']!=self.job['intent']['scopeRef'] or source['resourceHandle']!=self.job['intent']['resourceHandle']:raise Fault('PERMISSION_DENIED')
                raw=bytearray()
                while len(raw)<source['bytes']:
                    chunk=await self.call_runtime('runtime.resource.read',dict(scopeRef=source['scopeRef'],evidence=source,grantRefs=p['grantRefs'],offset=len(raw),length=min(65536,source['bytes']-len(raw))))
                    raw.extend(base64.b64decode(chunk['dataBase64'],validate=True))
                if len(raw)!=source['bytes'] or sha(raw)!=source['digest']:raise AssertionError('Runtime source bytes')
                snapshot=dict(source,authority='host',resourceHandle='snapshot:'+str(n));self.snapshots[snapshot['resourceHandle']]=(snapshot,bytes(raw));snapshots.append(dict(source=source,snapshot=snapshot))
            self.capture=dict(**{k:p[k] for k in ('scopeRef','domainOperationId','operationId','requestDigest')},status='succeeded',snapshots=snapshots,reason='synthetic');return self.capture
        if method=='host.context.get':return self.capture
        if method=='host.execution.start':
            self.starts+=1
            if p['requestDigest']!=digest(method,p):raise AssertionError('start digest')
            if self.case=='busy' and self.starts==1:raise Fault('BUSY',recovery='retry-later')
            if self.case=='denied':raise Fault('PERMISSION_DENIED')
            self.start=copy.deepcopy(p)
            for ref in p['contextRefs']:
                if self.snapshots[ref['resourceHandle']][0]!=ref:raise AssertionError('snapshot identity')
            if self.case=='unknown':raise Fault('RESULT_UNKNOWN')
            return self.op()
        if method=='host.operation.get':return self.op()
        if method=='host.execution.cancel':self.cancelled=True;return dict(self.op(),operationId=p['operationId'],requestDigest=p['requestDigest'])
        if method=='host.execution.get':
            s=self.start;raw=self.result();running=self.case=='cancel' and not self.cancelled
            return dict(executionRef='execution:synthetic',scopeRef=s['scopeRef'],state='stopped' if self.cancelled else 'running' if running else 'completed',connectionRef=s['connectionRef'],configurationRevision=s['configurationRevision'],model=s['model'],requestIdentity={k:s[k] for k in ('operationId','requestDigest','profileDigest')},supervisor=None,approvalDecisionRefs=[],actualBinding=None if running else self.actual(),stopReason='cancelled' if self.cancelled else None,accounting=None,exit=None if running else dict(code=0,signal=None,pipesClosed=False),observationCompleteness='partial',resultRef=None if running or self.cancelled else dict(authority='host',resourceHandle=s['resourceHandle'],scopeRef=s['scopeRef'],objectRef='execution-result:synthetic',revision='1',mediaType='application/json',bytes=len(raw),digest=sha(raw)),reason='Synthetic Host only')
        if method=='host.resource.read':
            if self.case=='not-found':raise Fault('NOT_FOUND',absence=True)
            raw=self.result();chunk=raw[p['offset']:p['offset']+p['length']]
            if self.case=='integrity':chunk=b'X'+chunk[1:]
            e=p['evidence'];return dict(resourceHandle=e['resourceHandle'],revision=e['revision'],digest=e['digest'],offset=p['offset'],dataBase64=base64.b64encode(chunk).decode(),eof=p['offset']+len(chunk)==len(raw))
        raise AssertionError(method)


class StdioExecutionCases(unittest.IsolatedAsyncioTestCase):
    async def test_formal_and_probe_success_faults_cancel_and_backpressure(self):
        for case in ('review','probe','unknown','busy','denied','integrity','not-found','cancel'):
            with self.subTest(case=case):await self.run_case(case)
    async def run_case(self,case):
        fixture=ER.ReviewCases('test_probe_suggests_call_only');fixture.setUp()
        try:
            config=json.loads((fixture.root/'fixture/launch.json').read_text());generation=str(int(fixture.domain.read()['generation'])+1)
            context=dict(protocolVersion=VERSION,contractDigest=DIGEST,controlGeneration=generation,**{k:config[k] for k in ('installationId','instanceId','incarnationId','connectionId')})
            options=fixture.options();job=dict(case=case,review_mode='review' if case=='review' else 'probe',domain=str(fixture.root/'fixture/domain'),seed=fixture.seed,context=context,configuration=config,intent=fixture.intent,registration=fixture.registration,mapping=fixture.mapping,repository=fixture.repo.root,request=options.request)
            path=Path(fixture.engine.tmp_root)/'job.json';path.write_text(json.dumps(job));output=path.with_name('output.json')
            driver=HostDriver(case,fixture,job)
            driver.process=await asyncio.create_subprocess_exec(sys.executable,'-B',str(Path(__file__).with_name('probe_execution_port.py')),str(path),str(output),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            reader=asyncio.create_task(driver.reader())
            try:
                await asyncio.wait_for(driver.process.wait(),30);await reader
                await asyncio.gather(*driver.tasks)
                stderr=(await driver.process.stderr.read()).decode();observed=json.loads(output.read_text())
                (path.parent/'frames.json').write_text(json.dumps(driver.frames,indent=2));(path.parent/'stderr.log').write_text(stderr)
                self.assertNotIn('error',observed,observed)
                expected=0 if case in ('review','probe','unknown','busy') else 1
                self.assertEqual(observed['code'],expected,(observed,stderr));self.assertEqual(driver.starts,2 if case=='busy' else 1)
                reports=observed['reports'];self.assertTrue(reports,reports)
                receipt=fixture.receipts()[-1]
                expected_class='completed_with_valid_verdict' if case=='review' else 'probe_completed' if expected==0 else 'cancelled_by_host' if case=='cancel' else 'execution_port_failure'
                self.assertEqual(receipt['classification'],expected_class)
                self.assertEqual(receipt['execution']['capability_suggestion'],'REVIEW_ENABLED' if case=='review' else 'CALL_ONLY' if expected==0 else 'CONFIGURED')
                if expected:self.assertEqual(receipt['verdict_validation'],'NOT_REACHED')
                if case in ('denied','not-found'):
                    last=list(observed['reservations'].values())[-1]['last_fault'];self.assertEqual(last['code'],'PERMISSION_DENIED' if case=='denied' else 'NOT_FOUND');self.assertEqual(last['absence_proven'],case=='not-found')
                self.assertTrue(all(x['frame'].get('jsonrpc')=='2.0' for x in driver.frames))
                self.assertTrue(any(x['frame'].get('method')=='runtime.resource.read' for x in driver.frames))
                if case=='unknown':self.assertIn('host.operation.get',driver.methods)
                if case=='cancel':self.assertIn('host.execution.cancel',driver.methods)
                if case=='busy':
                    starts=[x['frame']['params'] for x in driver.frames if x['frame'].get('method')=='host.execution.start'];self.assertEqual(starts[0],starts[1])
            finally:
                if driver.process.returncode is None:driver.process.kill();await driver.process.wait()
                reader.cancel();await asyncio.gather(reader,return_exceptions=True)
                await asyncio.gather(*driver.tasks,return_exceptions=True)
                (path.parent/'frames.json').write_text(json.dumps(driver.frames,indent=2))
                (path.parent/'stdout-lines.json').write_text(json.dumps(driver.raw_lines))
                if not (path.parent/'stderr.log').exists():(path.parent/'stderr.log').write_bytes(await driver.process.stderr.read())
        finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
