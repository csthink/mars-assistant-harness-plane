"""Standalone Implementer supervisor: the single writer of one physical execution observation directory.

Started detached by execution/implementer_local.py with a job file in
<git-common-dir>/harness/executions/<executionRequestId>/ (repo-layout §8.1). It waits for the release
file, checks that the executable is still the one discovered at preflight (launcher path and binary
digest; the version is recorded, never allow-listed), starts the Agent as its own session leader in
the task worktree, registers every descendant with (pid, start time, image, session) while the target
runs, enforces run time, output bytes, tool-call count and cleanup time, and records exit facts.

Stop unconfirmed follows J-06 r2: after the target exits, a registered descendant that is still alive
outside the target session (or whose identity cannot be read) keeps the execution in `stopping` with a
reason starting `stop unconfirmed after`; the supervisor never signals it and keeps observing until
every such process has exited, then writes the resolved record. Processes still alive inside the
target session are terminated by process group (TERM, then KILL after the cleanup time).

Observation records are append-only JSON files record-NNNNNN.json; result.json carries the protocol
result the Agent reported. Nothing here writes the domain state.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

POLL = 0.25
RECHECK = 1.0
STOP_PREFIX = "stop unconfirmed after"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True))
    os.replace(temporary, path)


def identity(pid):
    """(startTime, image) of a live pid, or None when absent."""
    result = subprocess.run(["ps", "-o", "lstart=", "-o", "comm=", "-p", str(pid)], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)
    line = result.stdout.strip()
    if result.returncode or not line:
        return None
    parts = line.split()
    return " ".join(parts[:5]), " ".join(parts[5:])


def session(pid):
    try:
        return os.getsid(pid)
    except (ProcessLookupError, PermissionError):
        return None


def table():
    result = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid="], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True)
    pairs = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            pairs.append((int(fields[0]), int(fields[1])))
    return pairs


def descendants(root):
    children = {}
    for pid, parent in table():
        children.setdefault(parent, []).append(pid)
    found, stack = [], [root]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child)
    return found


def alive(entry):
    """True when the same process (pid and start time) still runs; None when it cannot be observed."""
    current = identity(entry["pid"])
    if current is None:
        return False
    return current[0] == entry["startTime"]


class Supervisor:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.job = json.loads((self.directory / "job.json").read_text())
        self.seq = 0
        self.children = {}
        self.target = None

    def record(self, **facts):
        self.seq += 1
        facts.update(seq=self.seq, at=now())
        atomic(self.directory / ("record-%06d.json" % self.seq), facts)

    def wait_release(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (self.directory / "cancel.json").exists():
                return "cancelled"
            if (self.directory / "go.json").exists():
                return "go"
            time.sleep(0.02)
        return "not-released"

    def program_matches(self):
        expected = self.job["programIdentity"]
        launcher = Path(expected["launcher"])
        try:
            digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
        except OSError:
            return False
        return digest == expected["binaryDigest"]

    def register(self):
        for pid in descendants(self.target.pid):
            if pid in self.children:
                continue
            current = identity(pid)
            if current is None:
                continue
            self.children[pid] = dict(pid=pid, startTime=current[0], image=current[1], session=session(pid))

    def tool_calls(self):
        path = self.directory / "transcript.ndjson"
        count = 0
        try:
            with path.open("rb") as stream:
                for line in stream:
                    if b'"type":"tool_use"' in line.replace(b" ", b""):
                        count += 1
        except OSError:
            pass
        return count

    def output_bytes(self):
        return sum((self.directory / name).stat().st_size for name in ("transcript.ndjson", "stderr.log")
                   if (self.directory / name).exists())

    def stop_group(self, cleanup):
        try:
            os.killpg(self.target.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + cleanup
        while time.monotonic() < deadline and self.target.poll() is None:
            time.sleep(POLL)
        if self.target.poll() is None:
            try:
                os.killpg(self.target.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def run(self):
        job = self.job
        atomic(self.directory / "ready.json", dict(pid=os.getpid(), start_time=identity(os.getpid())[0],
                                                   token=job["token"]))
        release = self.wait_release()
        if release != "go":
            self.record(state="stopped" if release == "cancelled" else "failed",
                        stopReason="cancelled" if release == "cancelled" else None, exit=None, accounting=None,
                        observationCompleteness="complete", reason="execution was not released: " + release)
            return
        if not self.program_matches():
            self.record(state="failed", stopReason=None, exit=None, accounting=None, observationCompleteness="complete",
                        reason="the executable no longer matches the program identity discovered at preflight")
            return
        budget = job["budget"]
        out = (self.directory / "transcript.ndjson").open("wb")
        err = (self.directory / "stderr.log").open("wb")
        started = time.monotonic()
        self.target = subprocess.Popen(job["argv"], cwd=job["cwd"], stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       start_new_session=True, close_fds=True, env=job["env"])
        target_identity = identity(self.target.pid)
        target_session = self.target.pid
        self.record(state="running", stopReason=None, exit=None, accounting=None, observationCompleteness="partial",
                    reason="target running", target=dict(pid=self.target.pid, startTime=target_identity[0] if target_identity else "",
                                                         image=target_identity[1] if target_identity else job["argv"][0]))
        stop_reason = None
        while self.target.poll() is None:
            self.register()
            elapsed = time.monotonic() - started
            if (self.directory / "cancel.json").exists():
                stop_reason = "cancelled"
            elif elapsed > budget["maxRunSeconds"]:
                stop_reason = "timeout"
            elif self.output_bytes() > budget["maxOutputBytes"]:
                stop_reason = "output-limit"
            elif self.tool_calls() > budget["maxToolCalls"]:
                stop_reason = "tool-call-budget"
            if stop_reason:
                self.stop_group(budget["cleanupSeconds"])
                break
            time.sleep(POLL)
        code = self.target.wait()
        out.close()
        err.close()
        exit_fact = dict(code=code if code >= 0 else None, signal=None if code >= 0 else signal.Signals(-code).name,
                         pipesClosed=True)
        accounting = dict(toolCalls=self.tool_calls(), runSeconds=int(time.monotonic() - started),
                          outputBytes=self.output_bytes(), waited=True, pidGoneAfterExit=identity(self.target.pid) is None)
        # A descendant may have left the target session after it was registered: read its session again.
        for child in self.children.values():
            if alive(child):
                current = session(child["pid"])
                if current is not None:
                    child["session"] = current
        # Descendants inside the target session are reclaimed by process group; outside it they are only observed.
        inside = [c for c in self.children.values() if c["session"] == target_session and alive(c)]
        if inside:
            try:
                os.killpg(target_session, signal.SIGTERM)
                time.sleep(min(budget["cleanupSeconds"], 5))
                os.killpg(target_session, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        remaining_inside = [c for c in self.children.values() if c["session"] == target_session and alive(c)]
        escaped = [c for c in self.children.values() if c["session"] != target_session and alive(c) is not False]
        cause = stop_reason or "exit"
        if escaped:
            self.record(state="stopping", stopReason=None, exit=exit_fact, accounting=accounting,
                        observationCompleteness="partial", exitClassification="children-remaining",
                        reason="%s %s: %d process(es) outside the target session still alive (%s)" % (
                            STOP_PREFIX, cause, len(escaped), ", ".join(str(c["pid"]) for c in escaped)),
                        escaped=[dict(pid=c["pid"], session=c["session"], image=c["image"]) for c in escaped])
            while any(alive(c) is not False for c in escaped):
                time.sleep(RECHECK)
            self.record(state="stopped" if stop_reason else "failed", stopReason=stop_reason, exit=exit_fact,
                        accounting=accounting, observationCompleteness="complete",
                        reason="stop confirmed: every process outside the target session has exited")
            return
        if remaining_inside:
            self.record(state="unknown", stopReason=None, exit=exit_fact, accounting=accounting,
                        observationCompleteness="partial", exitClassification="children-remaining",
                        reason="processes inside the target session could not be reclaimed")
            return
        if stop_reason:
            self.record(state="stopped", stopReason=stop_reason, exit=exit_fact, accounting=accounting,
                        observationCompleteness="complete", reason="stopped: " + stop_reason)
            return
        if accounting["outputBytes"] > budget["maxOutputBytes"] or accounting["toolCalls"] > budget["maxToolCalls"]:
            # The target finished before a poll saw the overrun: its output is outside the budget and not consumed.
            self.record(state="failed", stopReason=None, exit=exit_fact, accounting=accounting,
                        observationCompleteness="complete", reason="budget exceeded before exit was observed")
            return
        if code != 0:
            self.record(state="failed", stopReason=None, exit=exit_fact, accounting=accounting,
                        observationCompleteness="complete", reason="target exited with a failure")
            return
        report = self.protocol_result()
        if report is None:
            self.record(state="failed", stopReason=None, exit=exit_fact, accounting=accounting,
                        observationCompleteness="complete", reason="no protocol result could be read back")
            return
        atomic(self.directory / "result.json", report)
        self.record(state="completed", stopReason=None, exit=exit_fact, accounting=accounting,
                    observationCompleteness="complete", reason="target completed", model=report["model"])

    def protocol_result(self):
        """The last `{"type": "result"}` line the Agent wrote: its text and the model it reports."""
        try:
            lines = (self.directory / "transcript.ndjson").read_bytes().splitlines()
        except OSError:
            return None
        for raw in reversed(lines):
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(value, dict) and value.get("type") == "result" and isinstance(value.get("result"), str):
                model = value.get("model")
                if not model and isinstance(value.get("modelUsage"), dict) and len(value["modelUsage"]) == 1:
                    model = next(iter(value["modelUsage"]))
                if isinstance(model, str) and model:
                    return dict(answer=value["result"], model=model, source="protocol-result")
        return None


def main():
    Supervisor(sys.argv[1]).run()


if __name__ == "__main__":
    main()
