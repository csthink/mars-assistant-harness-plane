"""Test-only product runner composition over real stdio and persistent GitDomain."""
import asyncio
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from git_domain import GitDomain
from runtime.dispatcher import Dispatcher
from runtime.host import HostClient
from runtime.protocol import Schemas
from runtime.transport import Stdio
from execution.host import HostExecutionPort
from execution.bridge import ProductReview
from execution.port import ExecutionAuthorization,ExecutionDiscovery,identity,sha
import review_channel as C

async def main(job,output):
    domain=GitDomain(job['domain'],job['seed']);generation=domain.acquire_generation()
    context=dict(job['context'],controlGeneration=generation)
    transport=Stdio();dispatcher=Dispatcher(domain,job['configuration'],transport)
    dispatcher.context=context;dispatcher.ready=True
    dispatcher.host=HostClient(transport,dispatcher.schemas,context)
    intent=job['intent'];dispatcher.grants[intent['scopeRef']]=intent['grantRefs']
    dispatcher.authorization_serial[intent['scopeRef']]=1
    transport.dispatcher=dispatcher
    async def discover():return ExecutionDiscovery(copy.deepcopy(intent['profile']),intent['connectionRef'],job['registration']['provider'],'protocol-independent','7')
    async def authorize(i):
        await dispatcher.authorize(dict(context=context,scopeRef=i['scopeRef'],grantRefs=i['grantRefs']),'runtime.resource.read')
        # Synthetic Owner/domain decision fixture, never a production authority.
        return ExecutionAuthorization(identity(i),sha(i['invocation_authorization'].encode()),i['caller'],('Anthropic',),('synthetic-author:fixed',),True,2,'synthetic-owner:one')
    port=HostExecutionPort(dispatcher.host,domain,job['registration'],job['mapping'],discover,authorize)
    bridge=ProductReview(port,intent,lambda:[b'sk-fake-secret-value-123'])
    opts=C.Options();opts.repo_root=job['repository'];opts.request=job['request']
    transport_task=asyncio.create_task(transport.run())
    try:
        worker=asyncio.create_task(bridge.review(job['review_mode'],opts))
        if job['case']=='cancel':
            for _ in range(300):
                records=domain.read().get('executionReservations',{})
                if any(r.get('execution_ref') is not None for r in records.values()):break
                await asyncio.sleep(.01)
            worker.cancel()
        try:code=await worker
        except asyncio.CancelledError:code=1
        if bridge.background is not None:await bridge.background
        output.write_text(json.dumps(dict(code=code,reports=bridge.reports,diagnostics=bridge.diagnostics,reservations=domain.read().get('executionReservations',{}))))
    except BaseException as exc:
        output.write_text(json.dumps(dict(error=type(exc).__name__,detail=str(exc))))
    finally:
        transport_task.cancel();await asyncio.gather(transport_task,return_exceptions=True)

if __name__=='__main__':asyncio.run(main(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2])))
