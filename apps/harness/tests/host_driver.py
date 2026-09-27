"""Independent Host wire driver. No dispatcher or domain logic imports.

Expected replies are specified in test cases, not generated from Runtime handlers.
Uses the shipped frozen schema only for wire shape validation.

Waiting policy: a wait is bounded by how long the Runtime stays silent, not by how long the whole
exchange takes. Every frame that arrives restarts the idle budget, so a loaded machine that makes
slow progress does not turn latency into a false red; a separate, much larger overall cap still
catches a Runtime that chatters without ever answering. HP_TEST_TIMEOUT_SCALE multiplies every
budget for deliberately slow environments. A wait that does expire raises HostTimeout carrying what
was awaited, how long it waited, whether the child process is alive, its accumulated stderr and the
last frames exchanged, so the failure can be located from the report alone.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import rfc8785

SCALE_VARIABLE = "HP_TEST_TIMEOUT_SCALE"
IDLE_SECONDS = 10.0
OVERALL_SECONDS = 120.0
SHUTDOWN_SECONDS = 2.0
RECENT_FRAMES = 8

def scale():
    try:
        value = float(os.environ.get(SCALE_VARIABLE, "1"))
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0

def budget(seconds):
    """Scale one wait budget; callers keep stating the budget they mean, not a scaled number."""
    return max(0.0, float(seconds)) * scale()

class HostTimeout(TimeoutError):
    """A bounded wait expired. The message is the diagnosis, so a bare traceback still locates it."""
    def __init__(self, diagnosis):
        self.diagnosis = diagnosis
        super().__init__(json.dumps(diagnosis, ensure_ascii=False, indent=2, default=str))

def request_digest(method, params):
    return hashlib.sha256(rfc8785.dumps({"method":method, **{k:v for k,v in params.items()
                                      if k not in ("context","requestDigest")}})).hexdigest()

class Host:
    def __init__(self, directory, *, product=False, output=None, command=None):
        self.directory=Path(directory).resolve()
        self.template=json.loads((self.directory/"host-template.json").read_text())
        self.context=None
        self.grants=[]
        self.decisions={}
        self.frames=[]
        self.events=[]
        self.responses={}
        self.counter=0
        self.output=Path(output) if output else None
        self.queue=queue.Queue()
        self.stderr=[]
        app=Path(__file__).resolve().parents[1]
        custom=command is not None
        if custom:
            command=list(command)
        elif product:
            command=[sys.executable,"-m","runtime.main","serve-stdio","--launch-config",str(self.directory/"launch.json")]
        else:
            command=[sys.executable,str(app/"tests/serve_synthetic.py"),"serve-stdio","--launch-config",str(self.directory/"launch.json"),
                     "--seed",str(self.directory/"seed.json"),"--repository",str(self.directory/"domain")]
        if not product and not custom and (self.directory/"fault.json").exists():
            command += ["--fault-config",str(self.directory/"fault.json")]
        self.command=command
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=app,bufsize=0)
        def reader():
            for line in self.process.stdout:
                self.queue.put(line)
            self.queue.put(None)
        def errors():
            for line in self.process.stderr:
                self.stderr.append(line.decode(errors="replace"))
        self.reader=threading.Thread(target=reader,daemon=True)
        self.reader.start()
        self.error_reader=threading.Thread(target=errors,daemon=True)
        self.error_reader.start()
        self.handlers={"host.grants.get":self.grants_get,"host.decision.get":self.decision_get}

    def record(self,direction,frame):
        entry=dict(direction=direction,frame=copy.deepcopy(frame))
        self.frames.append(entry)
        if self.output:
            with self.output.open("a") as f:
                f.write(json.dumps(entry,separators=(",", ":"))+"\n")

    def send(self,frame):
        self.record("host-to-runtime",frame)
        self.process.stdin.write(json.dumps(frame,separators=(",", ":")).encode()+b"\n")
        self.process.stdin.flush()

    def grants_get(self,p):
        return dict(context=p["context"],grants=[g for g in self.grants if g["ref"]["id"] in {r["id"] for r in p["grantRefs"]}])

    def decision_get(self,p):
        return dict(context=p["context"],**self.decisions[p["decisionRef"]])

    def frame_summary(self,entry):
        frame=entry["frame"]
        summary=dict(direction=entry["direction"],id=frame.get("id"),method=frame.get("method"))
        if isinstance(frame.get("error"),dict):
            summary["errorCode"]=frame["error"].get("data",{}).get("code")
        return summary

    def diagnose(self,**extra):
        """Everything needed to locate a stalled exchange without re-running it."""
        returncode=self.process.poll()
        return dict(awaiting=extra.pop("awaiting",None),processAlive=returncode is None,returncode=returncode,
            command=list(self.command),directory=str(self.directory),timeoutScale=scale(),
            pendingResponses=sorted(str(k) for k in self.responses),framesExchanged=len(self.frames),
            eventsReceived=len(self.events),recentFrames=[self.frame_summary(e) for e in self.frames[-RECENT_FRAMES:]],
            stderr="".join(self.stderr)[-4000:],**extra)

    def pump(self,timeout=None,awaiting=None):
        idle=budget(IDLE_SECONDS if timeout is None else timeout)
        started=time.monotonic()
        try:
            raw=self.queue.get(timeout=idle)
        except queue.Empty:
            raise HostTimeout(self.diagnose(awaiting=awaiting or "any frame",reason="runtime stayed silent",
                waitedSeconds=round(time.monotonic()-started,3),idleBudgetSeconds=round(idle,3))) from None
        if raw is None:
            raise EOFError("Runtime exited; "+json.dumps(self.diagnose(awaiting=awaiting or "any frame",
                reason="runtime closed stdout"),ensure_ascii=False,default=str))
        frame=json.loads(raw)
        self.record("runtime-to-host",frame)
        if "method" in frame and "id" in frame:
            try:
                result=self.handlers[frame["method"]](frame["params"])
                if result is not None:
                    self.send(dict(jsonrpc="2.0",id=frame["id"],result=result))
            except KeyError:
                self.send(dict(jsonrpc="2.0",id=frame["id"],error=dict(code=-32000,message="Synthetic host denied",
                    data=dict(code="PERMISSION_DENIED",scopeRef=frame["params"].get("scopeRef"),operationId=None,recovery="none",absenceProven=False))))
        elif "method" in frame:
            self.events.append(frame)
        else:
            self.responses[frame["id"]]=frame
        return frame

    def call(self,method,params=None,*,error=None,timeout=None,overall=None):
        """Send one request and wait for its reply.

        timeout is the idle budget: how long the Runtime may stay silent before the wait is declared
        expired. It is restarted by every frame, including the reverse host.* calls this exchange
        needs, so total exchange time is not the failure criterion. overall bounds a Runtime that
        keeps sending frames but never answers this request.
        """
        p=copy.deepcopy(params or {})
        if method!="runtime.initialize":p={"context":self.context,**p}
        self.counter+=1
        request_id="h:"+str(self.counter)
        awaiting=method+" "+request_id
        self.send(dict(jsonrpc="2.0",id=request_id,method=method,params=p))
        idle=IDLE_SECONDS if timeout is None else timeout
        cap=budget(OVERALL_SECONDS if overall is None else overall)
        started=time.monotonic()
        while request_id not in self.responses:
            waited=time.monotonic()-started
            if waited>cap:
                raise HostTimeout(self.diagnose(awaiting=awaiting,reason="runtime never answered this request",
                    waitedSeconds=round(waited,3),idleBudgetSeconds=round(budget(idle),3),overallBudgetSeconds=round(cap,3)))
            self.pump(idle,awaiting=awaiting)
        frame=self.responses.pop(request_id)
        if error:
            assert frame.get("error",{}).get("data",{}).get("code")==error,frame
            return frame["error"]
        assert "result"in frame,frame
        return frame["result"]

    def initialize(self,overrides=None):
        p=copy.deepcopy(self.template["initialize"])
        p.update(overrides or {})
        result=self.call("runtime.initialize",p)
        self.context=result["context"]
        self.call("runtime.ready")
        return result

    def activate(self):
        result=self.call("runtime.scope.open",dict(binding=self.template["binding"]))
        assert result["scopeRef"]==self.template["scopeRef"]
        methods=["runtime.snapshot.open","runtime.snapshot.next","runtime.events.subscribe","runtime.events.ack",
                 "runtime.action.invoke","runtime.operation.get","runtime.operation.cancel","runtime.resource.read"]
        self.grants=[dict(ref=dict(id="grant:"+str(i),revision="1"),installationId=self.context["installationId"],
            instanceId=self.context["instanceId"],scopeRef=result["scopeRef"],resourceHandle="resource:one",
            capability="hp.synthetic",operation=method,executionRef=None,bundleDigest="b"*64,
            expiresAt="2099-01-01T00:00:00Z",status="active",purpose="Synthetic conformance") for i,method in enumerate(methods)]
        self.call("runtime.scope.authorize",dict(scopeRef=result["scopeRef"],grantRefs=self.refs()))
        return result["scopeRef"]

    def refs(self):return [copy.deepcopy(g["ref"]) for g in self.grants]

    def mutation(self,method,**params):
        params=dict(operationId="op:"+str(self.counter+1),idempotencyKey="key:"+str(self.counter+1),**params)
        params["requestDigest"]=request_digest(method,params)
        return params

    def invoke_params(self,**overrides):
        action=self.template["action"]
        p=dict(scopeRef=self.template["scopeRef"],actionId=action["actionId"],objectRef=action["objectRef"],
            expectedRevision=action["expectedRevision"],candidateRef=action["candidateRef"],grantRefs=self.refs(),payload={"value":"test"},decisionRef=None)
        p.update(overrides)
        return self.mutation("runtime.action.invoke",**p)

    def close(self):
        shutdown=budget(SHUTDOWN_SECONDS)
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=shutdown)
            except subprocess.TimeoutExpired:
                self.process.kill();self.process.wait(timeout=shutdown)
        self.reader.join(timeout=shutdown)
        self.error_reader.join(timeout=shutdown)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):stream.close()
