"""Standalone review port with a durable, separately supervised adapter worker.

Only this module spawns the worker. HostExecutionPort never imports this module.
The local controller supplies the same physical fact representation internally;
no external Host RPC is issued and no domain settlement is inferred from exit.
"""
import asyncio
import base64
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from .host import HostExecutionPort
from runtime.protocol import evidence_key
from .port import require, ExecutionError, sha


class LocalExecutionPort(HostExecutionPort):
    mode='standalone'
    def __init__(self,domain,generation,repository,spool,registration,mapping,discover,authorize):
        self.contexts={}
        controller=LocalController(self,domain,generation,repository,spool)
        super().__init__(controller,domain,registration,mapping,discover,authorize)
    def verify_readback(self,e,intent,discovered,actual):
        # The maintenance adapter reports a model claim, not Codex protocol provider.
        # Do not manufacture protocol-init or modelProvider from Registry values.
        require(actual['source']=='adapter-report' and e.get('readback')==dict(source='adapter-report',reported_model=actual['model']) and e.get('programIdentity')==intent['profile']['programIdentity'],'execution-port-identity-unverified')

    def bind_context(self,intent,ctx):
        # SecretHandle is recreated only by the worker from governed provider config.
        clean={k:copy.deepcopy(v) for k,v in ctx.items() if k!='secrets'}
        self.contexts[intent['executionRequestId']]=clean
    def reserve(self,intent,seal_dir,instruction,manifest):
        require(intent['executionRequestId'] in self.contexts,'execution-port-capability-unverified')
        r=super().reserve(intent,seal_dir,instruction,manifest)
        ctx=self.contexts[intent['executionRequestId']]
        def bind(record):
            require(record.get('local_context') is None or record['local_context']==ctx)
            record['local_context']=ctx
        return self.update(r,bind)


class LocalController:
    def __init__(self,port,domain,generation,repository,spool):
        self.port,self.domain=port,domain
        self.context=dict(controlGeneration=generation)
        self.repository=Path(repository).resolve(strict=True)
        self.spool=Path(spool).resolve();self.spool.mkdir(parents=True,exist_ok=True,mode=0o700)
        require(not self.spool.is_symlink())
        self.children={}
    def transact(self,fn):return self.domain.transaction(self.context['controlGeneration'],fn)
    def operation(self,rec):
        s=rec['start'];return dict(scopeRef=s['scopeRef'],operationId=s['operationId'],requestDigest=s['requestDigest'],executionRef=rec['execution_ref'])
    def record(self,operation=None,ref=None):
        matches=[r for r in self.domain.read().get('localExecutions',{}).values() if (operation is not None and r['start']['operationId']==operation) or (ref is not None and r['execution_ref']==ref)]
        require(len(matches)==1,'execution-port-result-unknown');return matches[0]
    async def call(self,method,p):
        if method=='host.execution.preflight':return dict(status='supported',checks=[dict(passed=True)])
        if method=='host.context.capture':
            result=dict(**{k:p[k] for k in ('scopeRef','domainOperationId','operationId','requestDigest')},status='succeeded',snapshots=[dict(source=s,snapshot=dict(s,authority='host',resourceHandle='local-snapshot:'+sha(json.dumps(s,sort_keys=True).encode()))) for s in p['sources']])
            self.transact(lambda state:state.setdefault('localCaptures',{}).setdefault(p['operationId'],result));return result
        if method=='host.context.get':
            value=self.domain.read().get('localCaptures',{}).get(p['operationId']);require(value is not None,'execution-port-result-unknown');return value
        if method=='host.execution.start':return await self.start(p)
        if method=='host.operation.get':return self.operation(self.record(operation=p['operationId']))
        if method=='host.execution.get':return self.physical(self.record(ref=p['executionRef']))
        if method=='host.execution.cancel':
            rec=self.record(ref=p['executionRef']);self.cancel(rec);return self.operation(self.record(ref=p['executionRef']))
        if method=='host.resource.read':
            rec=self.record(ref=p['evidence']['objectRef'].removeprefix('execution-result:'))
            raw=self.result(rec);require(len(raw)==p['evidence']['bytes'] and sha(raw)==p['evidence']['digest'])
            part=raw[p['offset']:p['offset']+p['length']]
            return dict(offset=p['offset'],dataBase64=base64.b64encode(part).decode(),eof=p['offset']+len(part)==len(raw))
        raise ExecutionError('execution_port_failure')
    async def start(self,p):
        key=p['operationId'];created=False
        def claim(state):
            nonlocal created
            records=state.setdefault('localExecutions',{})
            if key in records:
                require(records[key]['start']==p);return copy.deepcopy(records[key])
            reservation=[r for r in state['executionReservations'].values() if r['start']==p]
            require(len(reservation)==1 and reservation[0]['start_dispatched'])
            rec=dict(start=p,execution_ref='local-execution:'+sha(key.encode()),phase='booting',supervisor=None,process_token=None,cancel_requested=False,context=reservation[0]['local_context'],sources=reservation[0]['capture']['sources'])
            records[key]=rec;created=True;return copy.deepcopy(rec)
        rec=self.transact(claim)
        if not created:return self.operation(rec)
        directory=self.spool/sha(key.encode())
        directory.mkdir(mode=0o700)  # existing directory is never overwritten/replayed
        inputs=directory/'inputs';inputs.mkdir(mode=0o700)
        state=self.domain.read();ctx=copy.deepcopy(rec['context'])
        for item,ref in zip(ctx['manifest']['inputs'],rec['sources'][1:]):
            value=state['resources'][evidence_key(ref)];require(value['evidence']==ref)
            raw=base64.b64decode(value['dataBase64'],validate=True)
            require(len(raw)==item['bytes'] and sha(raw)==item['sha256'])
            name=item['bundle_name'];require(Path(name).name==name)
            (inputs/name).write_bytes(raw)
        first=rec['sources'][0];ctx['instruction']=base64.b64decode(state['resources'][evidence_key(first)]['dataBase64'],validate=True).decode()
        ctx.update(instruction_user=None,seal_dir=str(inputs),attempt_dir=str(directory))
        job=directory/'job.json';job.write_text(json.dumps(dict(context=ctx,mechanism=str(self.repository/'mechanisms/review-channel'),program_identity=self.port.registration['profile']['programIdentity'])))
        os.chmod(job,0o600)
        worker=Path(__file__).with_name('local_worker.py')
        with (directory/'worker.stdout').open('xb') as out, (directory/'worker.stderr').open('xb') as err:
            process=subprocess.Popen([sys.executable,'-B','-E','-s',str(worker),str(job)],stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True,close_fds=True,env={k:os.environ[k] for k in ('HOME','PATH','TMPDIR','LANG','LC_ALL') if k in os.environ})
        self.children[rec['execution_ref']]=process
        deadline=time.monotonic()+5
        while not (directory/'ready.json').exists():
            if process.poll() is not None or time.monotonic()>deadline:raise ExecutionError('execution-port-observation-incomplete')
            await asyncio.sleep(.02)
        ready=json.loads((directory/'ready.json').read_text());require(ready['pid']==process.pid and bool(ready['token']))
        supervisor=dict(pid=process.pid,startTime=ready['start_time'],image=str(Path(sys.executable).resolve()))
        def saved(state):
            value=state['localExecutions'][key];value.update(supervisor=supervisor,process_token=ready['token'],phase='running')
            return copy.deepcopy(value)
        rec=self.transact(saved)
        if not rec['cancel_requested']:
            # Only a persisted process identity can receive permission to run.
            (directory/'go.json').write_text('{}')
        return self.operation(rec)
    def directory(self,rec):return self.spool/sha(rec['start']['operationId'].encode())
    def alive(self,rec):
        import review_channel_base as B
        if rec['supervisor'] is None:return None
        child=self.children.get(rec['execution_ref'])
        if child:child.poll()
        return B.owner_alive(rec['supervisor']['pid'],rec['process_token'])
    def cancel(self,rec):
        key=rec['start']['operationId']
        self.transact(lambda s:s['localExecutions'][key].update(cancel_requested=True))
        if self.alive(rec) is True:
            os.killpg(rec['supervisor']['pid'],signal.SIGTERM)
        # Unknown PID/token is never signalled. The reservation remains protected.
    def output(self,rec):
        path=self.directory(rec)/'result.json'
        if not path.exists():return None
        require(not path.is_symlink());return json.loads(path.read_bytes())
    def result(self,rec):
        out=self.output(rec);require(out is not None)
        answer=base64.b64decode(out['answer'],validate=True)
        actual=dict(model=out['model'],source='adapter-report',observedModels=[out['model']])
        s=rec['start'];e=dict(answer=answer.decode(),answerBytes=len(answer),answerDigest=sha(answer),readback=dict(source='adapter-report',reported_model=out['model']),programIdentity=out['program_identity'])
        return json.dumps(dict(**{k:s[k] for k in ('operationId','profileId','profileDigest')},executionRef=rec['execution_ref'],actualBinding=actual,outcome='completed',evidence=e),sort_keys=True).encode()
    def physical(self,rec):
        s=rec['start'];alive=self.alive(rec);out=self.output(rec)
        physical=dict(executionRef=rec['execution_ref'],scopeRef=s['scopeRef'],state='running' if alive is True else 'unknown',connectionRef=s['connectionRef'],configurationRevision=s['configurationRevision'],model=s['model'],requestIdentity={k:s[k] for k in ('operationId','requestDigest','profileDigest')},supervisor=rec['supervisor'],approvalDecisionRefs=[],actualBinding=None,stopReason=None,accounting=None,exit=None,observationCompleteness='partial' if rec['supervisor'] else 'unknown',resultRef=None,reason='standalone supervised review')
        if rec['cancel_requested']:
            physical.update(state='stopping' if alive is True else 'unknown',stopReason='cancelled',reason='cancel requested; descendants and complete exit remain unproven')
            return physical
        if alive is not False or out is None:return physical
        if out['failure'] is not None or out['process']['exit_code']!=0:
            physical.update(state='failed',exit=dict(code=out['process']['exit_code'],signal=None,pipesClosed=False));return physical
        raw=self.result(rec)
        physical.update(state='completed',actualBinding=dict(model=out['model'],source='adapter-report',observedModels=[out['model']]),exit=dict(code=0,signal=None,pipesClosed=False),resultRef=dict(authority='host',resourceHandle=s['resourceHandle'],scopeRef=s['scopeRef'],objectRef='execution-result:'+rec['execution_ref'],revision='1',mediaType='application/json',bytes=len(raw),digest=sha(raw)))
        return physical
