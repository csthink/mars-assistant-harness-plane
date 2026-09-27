"""Standalone Implementer execution port (feature-t4; spec FR-62 standalone uses LocalExecutionPort).

ImplementerLocalExecutionPort is the feature-t17 port with purpose coding-implementer and mode
standalone: preflight, the persisted reservation before release, start identity saved before release,
query of the original request, cancel and result reading are the unchanged HostExecutionPort logic.
ImplementerController answers the host.* calls locally: it starts one detached supervisor
(implementer_supervisor.py) per execution request in <git-common-dir>/harness/executions/<id>/, releases
it only after the supervisor identity is persisted, and projects the supervisor's append-only records
to the Contract PhysicalExecution shape. It never settles the domain and never infers completion from
process exit.

discover_program() rediscovers the program identity on every preflight (launcher path, binary digest,
`--version` readback). It is recorded with the execution and is never an allow list (OD-399).
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from runtime.protocol import evidence_key
from .host import HostExecutionPort, without_program
from .local import LocalController
from .port import ExecutionDiscovery, ExecutionError, require, sha

SUPERVISOR = Path(__file__).with_name("implementer_supervisor.py")


def discover_program(command):
    """Current launcher, binary digest and version of the Agent command; None when it cannot be read."""
    launcher = shutil.which(command)
    if launcher is None:
        return None
    path = Path(launcher).resolve()
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        version = subprocess.run([str(path), "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, timeout=15, text=True).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return dict(launcher=str(path), binaryDigest=digest, version=(version[0] if version else "unknown")[:256])


def make_discovery(entry, connection_ref):
    """The standalone discovery callback: registered profile plus the program identity found now."""
    async def discover():
        program = discover_program(entry["standalone"]["command"])
        if program is None:
            raise ExecutionError("execution-port-identity-unverified")
        profile = dict(copy.deepcopy(entry["profile"]), programIdentity=program)
        return ExecutionDiscovery(profile, connection_ref, entry["provider"], "", entry["configurationRevision"])
    return discover


class ImplementerLocalExecutionPort(HostExecutionPort):
    mode = "standalone"
    purpose = "coding-implementer"

    def __init__(self, domain, generation, registration, discover, authorize, *, worktree, executions_root, env=None):
        from domain.implement_verify import registration as product_registration
        controller = ImplementerController(self, domain, generation, Path(executions_root), Path(worktree), env)
        super().__init__(controller, domain, registration, product_registration.mapping(registration), discover,
                         authorize)

    def reserve(self, intent, seal_dir, instruction, manifest):
        record = super().reserve(intent, seal_dir, instruction, manifest)
        def bind(r):
            r.setdefault("local_implementer", dict(argv=list(self.registration["standalone"]["argv"])))
        return self.update(record, bind)


class ImplementerController(LocalController):
    def __init__(self, port, domain, generation, root, worktree, env):
        self.port, self.domain = port, domain
        self.context = dict(controlGeneration=generation)
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(not self.root.is_symlink())
        self.worktree = worktree
        self.env = env
        self.children = {}

    def directory(self, rec):
        return self.root / rec["start"]["domainOperationId"]

    async def start(self, p):
        key = p["operationId"]
        created = False

        def claim(state):
            nonlocal created
            records = state.setdefault("localExecutions", {})
            if key in records:
                require(records[key]["start"] == p)
                return copy.deepcopy(records[key])
            reservation = [r for r in state["executionReservations"].values() if r["start"] == p]
            require(len(reservation) == 1 and reservation[0]["start_dispatched"])
            record = dict(start=p, execution_ref="local-implement:" + sha(key.encode()), phase="booting",
                          supervisor=None, process_token=None, cancel_requested=False,
                          sources=reservation[0]["capture"]["sources"], local=reservation[0]["local_implementer"],
                          program=copy.deepcopy(self.port.program_identity))
            records[key] = record
            created = True
            return copy.deepcopy(record)
        rec = self.transact(claim)
        if not created:
            return self.operation(rec)
        directory = self.directory(rec)
        directory.mkdir(mode=0o700)  # an existing directory is never overwritten or replayed
        inputs = directory / "inputs"
        inputs.mkdir(mode=0o700)
        state = self.domain.read()
        for ref in rec["sources"]:
            value = state["resources"][evidence_key(ref)]
            require(value["evidence"] == ref)
            raw = base64.b64decode(value["dataBase64"], validate=True)
            require(len(raw) == ref["bytes"] and sha(raw) == ref["digest"])
            name = "instruction.md" if ref["objectRef"] == "instruction" else ref["objectRef"].replace(":", "-")
            (inputs / name).write_bytes(raw)
        argv = [rec["program"]["launcher"]] + [a.replace("{inputs}", str(inputs)).replace("{instruction}", str(inputs / "instruction.md"))
                                               for a in rec["local"]["argv"]]
        token = sha(os.urandom(32))
        env = dict(self.env) if self.env is not None else {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL") if k in os.environ}
        job = dict(argv=argv, cwd=str(self.worktree), env=env, budget=p["budget"], programIdentity=rec["program"], token=token)
        (directory / "job.json").write_text(json.dumps(job))
        os.chmod(directory / "job.json", 0o600)
        with (directory / "supervisor.stdout").open("xb") as out, (directory / "supervisor.stderr").open("xb") as err:
            process = subprocess.Popen([sys.executable, "-B", "-E", "-s", str(SUPERVISOR), str(directory)],
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True, close_fds=True)
        self.children[rec["execution_ref"]] = process
        deadline = time.monotonic() + 10
        while not (directory / "ready.json").exists():
            if process.poll() is not None or time.monotonic() > deadline:
                raise ExecutionError("execution-port-observation-incomplete")
            time.sleep(0.02)
        ready = json.loads((directory / "ready.json").read_text())
        require(ready["pid"] == process.pid and ready["token"] == token)
        supervisor = dict(pid=process.pid, startTime=ready["start_time"], image=str(Path(sys.executable).resolve()))

        def saved(state):
            value = state["localExecutions"][key]
            value.update(supervisor=supervisor, process_token=token, phase="running")
            return copy.deepcopy(value)
        rec = self.transact(saved)
        if not rec["cancel_requested"]:
            # Only a persisted supervisor identity receives the release.
            (directory / "go.json").write_text("{}")
        return self.operation(rec)

    def alive(self, rec):
        if rec["supervisor"] is None:
            return None
        child = self.children.get(rec["execution_ref"])
        if child is not None:
            child.poll()
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(rec["supervisor"]["pid"])], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        return result.returncode == 0 and " ".join(result.stdout.split()) == rec["supervisor"]["startTime"]

    def reap(self, rec):
        """Collect the exit status of a supervisor this controller started once its terminal record exists.

        The terminal record is the supervisor's last write, so it exits right after; a supervisor that is
        still alive after the short wait is left running and is never signalled.
        """
        child = self.children.get(rec["execution_ref"])
        if child is None or child.poll() is not None:
            return
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def cancel(self, rec):
        key = rec["start"]["operationId"]
        self.transact(lambda s: s["localExecutions"][key].update(cancel_requested=True))
        directory = self.directory(rec)
        if directory.exists():
            # The supervisor stops the target session itself; an unknown process is never signalled.
            (directory / "cancel.json").write_text("{}")

    def latest(self, rec):
        records = sorted(self.directory(rec).glob("record-*.json"))
        return json.loads(records[-1].read_text()) if records else None

    def output(self, rec):
        path = self.directory(rec) / "result.json"
        if not path.exists():
            return None
        require(not path.is_symlink())
        return json.loads(path.read_text())

    def result(self, rec):
        out = self.output(rec)
        require(out is not None)
        answer = out["answer"].encode()
        actual = dict(model=out["model"], source=out["source"], observedModels=[out["model"]])
        s = rec["start"]
        evidence = dict(answer=out["answer"], answerBytes=len(answer), answerDigest=sha(answer),
                        readback=dict(source=out["source"], model=out["model"]), programIdentity=rec["program"])
        return json.dumps(dict(**{k: s[k] for k in ("operationId", "profileId", "profileDigest")},
                               executionRef=rec["execution_ref"], actualBinding=actual, outcome="completed",
                               evidence=evidence), sort_keys=True).encode()

    def physical(self, rec):
        s = rec["start"]
        latest = self.latest(rec)
        supervisor_alive = self.alive(rec)
        base = dict(executionRef=rec["execution_ref"], scopeRef=s["scopeRef"], connectionRef=s["connectionRef"],
                    configurationRevision=s["configurationRevision"], model=s["model"],
                    requestIdentity={k: s[k] for k in ("operationId", "requestDigest", "profileDigest")},
                    supervisor=rec["supervisor"], approvalDecisionRefs=[], actualBinding=None, stopReason=None,
                    accounting=None, exit=None, observationCompleteness="unknown", resultRef=None,
                    reason="standalone implementer supervisor")
        terminal = latest is not None and latest["state"] in ("completed", "failed", "stopped", "unknown")
        if latest is None or (not terminal and supervisor_alive is not True):
            # No record yet, or the supervisor disappeared before a terminal record: never completion.
            state = "running" if latest is None and supervisor_alive is True else "unknown"
            base.update(state=state, observationCompleteness="partial" if rec["supervisor"] else "unknown",
                        reason="supervisor running, no record yet" if state == "running" else
                        "supervisor ended without a terminal record; the execution result is unknown")
            return base
        if terminal:
            self.reap(rec)
        base.update(state=latest["state"], stopReason=latest.get("stopReason"), exit=latest.get("exit"),
                    accounting=latest.get("accounting"), observationCompleteness=latest["observationCompleteness"],
                    reason=latest["reason"])
        if latest["state"] == "completed":
            raw = self.result(rec)
            out = self.output(rec)
            base.update(actualBinding=dict(model=out["model"], source=out["source"], observedModels=[out["model"]]),
                        resultRef=dict(authority="host", resourceHandle=s["resourceHandle"], scopeRef=s["scopeRef"],
                                       objectRef="execution-result:" + rec["execution_ref"], revision="1",
                                       mediaType="application/json", bytes=len(raw), digest=sha(raw)))
        return base
