"""Explicit trusted product entry to the existing formal review runner.

The runner remains synchronous in an independent thread. All physical I/O runs
on the Runtime loop, which remains available for query/cancel/control traffic.
"""
import asyncio
import base64
import copy
import json
from pathlib import Path
import sys
import time
from .port import ExecutionError, require, sha
from .materials import sealed_materials

MECHANISM=Path(__file__).resolve().parents[3]/'mechanisms/review-channel'
if str(MECHANISM) not in sys.path:sys.path.insert(0,str(MECHANISM))
import review_channel as channel
import review_channel_base as B
import review_channel_execution as X
import review_channel_runtime as RT


def same_applicability_policy(previous, current):
    """Across rounds the policy/mapping must match; the installed program may change."""
    return (isinstance(previous, dict) and isinstance(current, dict)
            and {k:v for k,v in previous.items() if k!='program_identity'}
            == {k:v for k,v in current.items() if k!='program_identity'})


class ProductReview:
    INLINE_DELIVERY=False

    def __init__(self,port,intent,secret_scanner):
        require(callable(secret_scanner),"execution-port-capability-unverified")
        self.secret_scanner=secret_scanner
        self.port=port
        self.port.bind_result_scanner(self,self.scan_set)
        self.intent=copy.deepcopy(intent)
        self.loop=None
        self.reservations={}
        self.stop_requested=False
        self.background=None
        self.reports=[]
        self.diagnostics=[]
        self.applicability=X.effective_applicability(dict(port_id=port.registration['id'],mode=port.mode,profile=port.registration['profile'],reviewer_applicability=port.registration['applicability'],mapping_id=port.mapping['id'],mapping_revision=port.mapping['revision'],mapping_sha256=sha(B.canonical_json(port.mapping))))

    def scan_set(self):
        values=self.secret_scanner()
        require(isinstance(values,(list,tuple)) and all(isinstance(x,(str,bytes)) and x for x in values),"execution-port-capability-unverified")
        return [x.encode() if isinstance(x,str) else x for x in values]

    def sync(self,coro):
        require(self.loop is not None,'execution-port-capability-unverified')
        return asyncio.run_coroutine_threadsafe(coro,self.loop).result()

    def validate_selection(self,reg,request,selection,previous,mode):
        try:
            r=self.port.registration;m=self.port.mapping
            require(r in reg['registry'].get('execution_ports',[]) and m in reg['registry'].get('model_mappings',[]),'execution-port-unregistered')
            require((selection['provider_id'],selection['model_slug'],selection['provider']['transport'],selection['effort'])==(r['provider'],r['model_ref'],r['transport'],r['effort']),'execution-port-binding-mismatch')
            require(not selection['overrides'],'execution-port-binding-mismatch')
            for key in ('caller','invocation_authorization','formal_review_authorized_by_owner'):
                require(request[key]==self.intent[key],'execution-port-capability-unverified')
            if previous is not None:
                # A previous round binds policy and mapping, not an obsolete installed binary.
                require(previous['receipt'].get('execution') is not None and same_applicability_policy(
                        previous['receipt']['effective_profile'].get('execution_applicability'),self.applicability),
                        'inherit-unmaterializable')
            auth=self.sync(self.port.authority(self.intent))
            require(set(request['model_vendors'])==set(auth.author_vendors) and request['artifact_author']['human_only']==auth.human_only,'eligibility')
            self.mode=mode
        except ExecutionError as exc:raise B.PreflightError(exc.code,'trusted product selection rejected') from exc

    def preflight(self,ctx):
        try:
            self.sync(self.port.preflight(self.intent))
            if self.port.mode=='embedded':
                require(self.port.program_identity is not None,'execution-port-identity-unverified')
                self.intent['profile']['programIdentity']=copy.deepcopy(self.port.program_identity)
                self.applicability=X.effective_applicability(dict(port_id=self.port.registration['id'],mode=self.port.mode,
                    profile=self.intent['profile'],reviewer_applicability=self.port.registration['applicability'],
                    mapping_id=self.port.mapping['id'],mapping_revision=self.port.mapping['revision'],
                    mapping_sha256=sha(B.canonical_json(self.port.mapping))))
            return dict(execution_port=self.port.registration['id'],mode=self.port.mode,profile_digest=self.intent['profile']['digest'])
        except ExecutionError as exc:raise B.PreflightError(exc.code,'execution preflight rejected') from exc

    async def run_call(self,ctx):
        if self.stop_requested:raise ExecutionError("cancelled_by_host","cancelled_by_host")
        intent=copy.deepcopy(self.intent)
        intent['executionRequestId'] += ':call:'+str(ctx['call_index'])
        instruction=ctx['instruction'].encode('utf-8')
        if ctx.get('instruction_user') is not None:
            instruction+=b'\n\n'+ctx['instruction_user'].encode('utf-8')
        materials=sealed_materials(ctx['seal_dir'],ctx['manifest'],instruction,intent['profile'])
        intent.update(inputManifestSha256=ctx['manifest']['manifest_sha256'],instructionSha256=sha(materials[0][2]))
        if hasattr(self.port,'bind_context'):self.port.bind_context(intent,ctx)
        await self.port.preflight(intent)
        reservation=self.port.reserve(intent,ctx['seal_dir'],instruction,ctx['manifest'])
        self.reservations[ctx['call_index']]=reservation
        result=RT.empty_result();failure=None;outcome=None
        try:
            if self.stop_requested:await self.port.cancel(reservation)
            outcome=await self.port.execute(reservation)
            deadline=time.monotonic()+intent['budget']['maxRunSeconds']
            while outcome['state'] not in ('completed',) and time.monotonic()<deadline:
                if self.stop_requested:await self.port.cancel(reservation)
                await asyncio.sleep(0.05)
                outcome=await self.port.query(reservation)
            if outcome['state']!='completed':raise ExecutionError('execution-port-result-unknown')
            result['final_message']=outcome['answer']
            current=self.port.current(reservation)
            physical=current['observations'][-1]['physical_execution']
            actual=physical['actualBinding']
            # Exact registered canonical mapping, with original actualBinding retained.
            require(actual['model'] in self.port.mapping['actual_models'],'execution-port-identity-unverified')
            result['identity_claim']=intent['executionBinding']['model']
            result['process']=dict(exit_code=0,timed_out=False,stderr_summary='')
            result['tool_version']=intent['profile']['programIdentity']['version']
            result['runtime_evidence'].update(request_count=1,request_ids=[current['start']['operationId']])
        except ExecutionError as exc:
            failure=exc.code;result['failure']=exc.classification
        except Exception as exc:
            failure='execution_port_failure';result['failure']='execution_port_failure'
            result['process']['stderr_summary']=type(exc).__name__
        current=self.port.current(reservation)
        if current.get('start') is not None:
            auth=await self.port.authority(intent)
            result['execution']=dict(port_id=self.port.registration['id'],mode=self.port.mode,request_id=current['request_id'],start_operation_id=current['start']['operationId'],request_digest=current['start']['requestDigest'],execution_ref=current['execution_ref'],profile=intent['profile'],execution_binding=intent['executionBinding'],reviewer_applicability=self.port.registration['applicability'],program_identity=intent['profile']['programIdentity'],input_manifest_sha256=current['manifest_sha256'],instruction_sha256=current['instruction_sha256'],reservation_ref=current['reservation_ref'],physical_observations=current['observations'],final_message_sha256=sha(result['final_message']) if failure is None else None,failure_code=failure,mapping_id=self.port.mapping['id'],mapping_revision=self.port.mapping['revision'],mapping_sha256=sha(B.canonical_json(self.port.mapping)),author_evidence_refs=list(auth.author_evidence_refs),capability_suggestion='CONFIGURED')
        result['raw']=dict(events=(json.dumps(dict(reservation_ref=current['reservation_ref'],phase=current['phase'],last_fault=current.get('last_fault'),protected=current['protected'],observation_history=self.port.historical_observations(current)),sort_keys=True)+'\n').encode())
        if current.get('result_envelope') is not None:result['raw']['response']=base64.b64decode(current['result_envelope'],validate=True)
        return result

    def run(self,ctx):
        try:return self.sync(self.run_call(ctx))
        except ExecutionError as exc:
            result=RT.empty_result();result['failure']=exc.classification
            result['process']['stderr_summary']=exc.code
            return result

    async def review(self,mode,options):
        require(mode in ('review','probe'),'request-invalid')
        require(self.loop is None,'round-in-progress')
        self.loop=asyncio.get_running_loop();options.execution_context=self
        options.report_sink=self.reports.append;options.diagnostic_sink=self.diagnostics.append
        worker=asyncio.create_task(asyncio.to_thread(channel.run_attempt,mode,options))
        self.background=worker
        try:return await asyncio.shield(worker)
        except asyncio.CancelledError:
            self.stop_requested=True
            for reservation in list(self.reservations.values()):
                try:await self.port.cancel(reservation)
                except Exception:pass  # worker owns final conservative Receipt and originals
            try:await asyncio.wait_for(asyncio.shield(worker),10)
            except (TimeoutError,Exception):pass
            raise
        finally:
            if worker.done():self.loop=None
            else:worker.add_done_callback(lambda _:setattr(self,'loop',None))

    def refusal(self):
        """The channel's refusal before it allocated an attempt, or None.

        Before allocation the channel reports a request-unrouteable diagnostic or a REJECTED report without an
        attempt_id (review channel design §6.1); neither leaves an attempt, a Receipt or a port reservation, so
        no Host request exists. Any port reservation makes the outcome something other than such a refusal."""
        if self.reservations:return None
        for report in self.reports:
            if (isinstance(report,dict) and report.get('state')=='REJECTED' and 'attempt_id' not in report
                    and isinstance(report.get('failure_code'),str) and report['failure_code']):
                return dict(code=report['failure_code'],problems=[str(p) for p in report.get('problems') or []])
        prefix='request-unrouteable: '
        for line in self.diagnostics:
            if isinstance(line,str) and line.startswith(prefix):
                return dict(code='request-unrouteable',problems=[line[len(prefix):]])
        return None

    async def cancel(self,call_index):
        require(call_index in self.reservations,'execution-port-result-unknown')
        return await self.port.cancel(self.reservations[call_index])
