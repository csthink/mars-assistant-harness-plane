import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.protocol import DIGEST, VERSION
from make_fixture import create
from host_samples import samples

class HostClientCases(unittest.TestCase):
    def test_all_ten_reverse_methods_real_pipes(self):
        self.run_samples("success")

    def test_all_ten_reject_mismatched_context(self):
        self.run_samples("wrong-context")

    def test_all_ten_propagate_host_error(self):
        self.run_samples("host-error")

    def test_all_ten_timeout_preserves_unknown(self):
        self.run_samples("timeout")

    def test_all_ten_reject_schema_violation(self):
        self.run_samples("bad-schema")

    def test_resource_rejects_invalid_base64(self):
        self.run_samples("chunk-base64")

    def test_resource_rejects_excess_length(self):
        self.run_samples("chunk-length")

    def test_resource_rejects_excess_remaining_bytes(self):
        self.run_samples("chunk-remaining")

    def test_resource_rejects_false_eof(self):
        self.run_samples("chunk-eof")

    def test_resource_rejects_full_digest_mismatch(self):
        self.run_samples("chunk-digest")

    def test_resource_rejects_missing_eof_at_end(self):
        self.run_samples("chunk-missing-eof")

    def test_resource_accepts_complete_verified_content(self):
        self.run_samples("chunk-valid-full")

    def test_resource_rejects_no_progress(self):
        self.run_samples("chunk-empty")

    def run_samples(self,mode):
        temp=None
        if os.environ.get("HP_TEST_OUTPUT"):
            root=Path(os.environ["HP_TEST_OUTPUT"])/self._testMethodName
        else:
            temp=tempfile.TemporaryDirectory(prefix="hp-host-client-");root=Path(temp.name)/"case"
        root.mkdir(parents=True,exist_ok=False)
        fixture=create(root/"fixture")
        context=dict(protocolVersion=VERSION,contractDigest=DIGEST,controlGeneration="1",installationId="installation:test",
                     instanceId="instance:test",incarnationId="incarnation:test",connectionId="connection:test")
        try:
            for method,(params,result) in samples(context,fixture["scopeRef"],fixture["evidence"]).items():
                if mode.startswith("chunk-") and method != "host.resource.read":
                    continue
                with self.subTest(method=method):
                    import base64
                    if mode == "chunk-base64":result["dataBase64"]="A"
                    if mode == "chunk-length":result["dataBase64"]=base64.b64encode(b"too-long").decode()
                    if mode == "chunk-remaining":
                        params["offset"]=fixture["evidence"]["bytes"]-1
                        result["offset"]=params["offset"]
                    if mode == "chunk-eof":result["eof"]=True
                    if mode == "chunk-digest":
                        params["length"]=fixture["evidence"]["bytes"]
                        result.update(dataBase64=base64.b64encode(b"X"*params["length"]).decode(),eof=True)
                    if mode == "chunk-empty":result["dataBase64"]=""
                    if mode in ("chunk-missing-eof","chunk-valid-full"):
                        params["length"]=fixture["evidence"]["bytes"]
                        result.update(dataBase64=base64.b64encode(b"Synthetic immutable evidence\n").decode(),eof=mode=="chunk-valid-full")
                    job=root/(method+"-job.json");output=root/(method+"-result.json")
                    job.write_text(json.dumps(dict(context=context,method=method,params=params,timeout=.5)))
                    process=subprocess.Popen([sys.executable,str(Path(__file__).with_name("probe_host_client.py")),str(job),str(output)],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    try:
                        ready,_,_=select.select([process.stdout],[],[],3)
                        self.assertTrue(ready,"No reverse request")
                        line=process.stdout.readline()
                        frame=json.loads(line)
                        self.assertEqual(frame["method"],method)
                        self.assertEqual(frame["params"],dict(context=context,**params))
                        response=dict(jsonrpc="2.0",id=frame["id"],result=dict(context=context,**result))
                        if mode=="wrong-context":response["result"]["context"]=dict(context,connectionId="connection:stale")
                        if mode=="bad-schema":response["result"]["unexpected"]=True
                        if mode=="host-error":response=dict(jsonrpc="2.0",id=frame["id"],error=dict(code=-32000,message="Synthetic denied",
                            data=dict(code="PERMISSION_DENIED",scopeRef=None,operationId=None,recovery="none",absenceProven=False)))
                        if mode!="timeout":
                            process.stdin.write(json.dumps(response).encode()+b"\n");process.stdin.flush()
                        process.wait(timeout=3)
                        (root/(method+"-frames.jsonl")).write_text(json.dumps(dict(direction="runtime-to-host",frame=frame))+"\n"+
                            (json.dumps(dict(direction="host-to-runtime",frame=response))+"\n" if mode!="timeout" else ""))
                        self.assertEqual(process.returncode,0,process.stderr.read().decode())
                        observed=json.loads(output.read_text())
                        if mode=="chunk-valid-full":self.assertEqual(observed["result"],dict(context=context,**result))
                        elif mode.startswith("chunk-"):self.assertEqual(observed.get("error",{}).get("data",{}).get("code"),"INTEGRITY_MISMATCH",observed)
                        elif mode=="success":self.assertEqual(observed["result"],dict(context=context,**result))
                        else:self.assertEqual(observed["error"]["data"]["code"],{"wrong-context":"WRITER_CONFLICT","host-error":"PERMISSION_DENIED",
                            "timeout":"RESULT_UNKNOWN","bad-schema":"PRECONDITION_CONFLICT"}[mode])
                    finally:
                        if process.poll() is None:process.kill();process.wait()
                        for stream in (process.stdin,process.stdout,process.stderr):stream.close()
        finally:
            if temp:temp.cleanup()
