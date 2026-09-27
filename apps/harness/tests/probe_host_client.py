"""Test-only composition for exercising the reverse client through real pipes."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from domain.port import UnavailableDomain
from runtime.dispatcher import Dispatcher
from runtime.host import HostClient
from runtime.protocol import Fault
from runtime.transport import Stdio

async def probe(job,output):
    transport=Stdio()
    dispatcher=Dispatcher(UnavailableDomain(),{},transport)
    dispatcher.context=job["context"]
    transport.dispatcher=dispatcher
    task=asyncio.create_task(transport.run())
    try:
        result=await HostClient(transport,dispatcher.schemas,job["context"]).call(job["method"],job["params"],job.get("timeout",1))
        output.write_text(json.dumps(dict(result=result)))
    except Fault as exc:
        output.write_text(json.dumps(dict(error=exc.error(job["params"]))))
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("job",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args();asyncio.run(probe(json.loads(args.job.read_text()),args.output))
