"""Synthetic Git DomainPort. Imported only by the explicit test server.

No task lifecycle is implemented. Seed facts and action outcomes are test data.
All state lives in a synthetic repository's refs/harness/runtime, never user repos.
"""
import copy
import fcntl
import json
import os
import signal
from pathlib import Path
import subprocess
from runtime.protocol import Fault

class GitDomain:
    available = True
    REF = "refs/harness/runtime"

    def __init__(self, repository, seed, fault_config=None):
        self.path = Path(repository).resolve()
        if not (self.path / ".synthetic-hp-domain").is_file():
            raise ValueError("Synthetic repository marker required")
        self.seed = copy.deepcopy(seed)
        self.fault_config = Path(fault_config) if fault_config else None
        self.capabilities = seed["capabilities"]
        self.schemas = seed["schemas"]
        self.lock = self.path / ".git" / "hp-test-writer.lock"
        with self.lock.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not self.git("rev-parse", "--verify", self.REF, check=False):
                self.save(copy.deepcopy(seed["state"]), None)

    def git(self, *args, data=None, check=True):
        env = {**os.environ, "GIT_AUTHOR_NAME": "Synthetic test", "GIT_AUTHOR_EMAIL": "test@invalid",
               "GIT_COMMITTER_NAME": "Synthetic test", "GIT_COMMITTER_EMAIL": "test@invalid"}
        result = subprocess.run(["git", "-C", str(self.path), *args], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if result.returncode:
            if check:
                raise RuntimeError("Synthetic Git transaction failed")
            return None
        return result.stdout.decode().strip()

    def read(self):
        return json.loads(self.git("show", self.REF + ":state.json"))

    def save(self, state, old):
        blob = self.git("hash-object", "-w", "--stdin", data=json.dumps(state, sort_keys=True).encode())
        tree = self.git("mktree", data=f"100644 blob {blob}\tstate.json\n".encode())
        args = ["commit-tree", tree, "-m", "Synthetic domain transaction"]
        if old:
            args += ["-p", old]
        commit = self.git(*args)
        self.git("update-ref", self.REF, commit, old or "0" * 40)

    def _transaction(self, generation, callback, *, intent="domain"):
        with self.lock.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            old = self.git("rev-parse", self.REF)
            state = self.read()
            before = copy.deepcopy(state)
            if generation is not None and state["generation"] != generation:
                raise Fault("WRITER_CONFLICT", recovery="reconnect")
            if before["barrier"] and intent == "domain":
                raise Fault("BUSY", "Shared domain barrier blocks this writer", recovery="retry-later")
            # Next revision is available to all members of this same transaction.
            state["revision"] = str(int(state["revision"]) + 1)
            result = callback(state)
            if before["barrier"] and any(ref not in before["protectedReferences"] for ref in state["protectedReferences"]):
                raise Fault("PRECONDITION_CONFLICT", "Protected references cannot grow behind barrier")
            changed = dict(state, revision=before["revision"]) != before
            if changed:
                self.inject_fault("before-commit", before, state, old)
                self.save(state, old)
                self.inject_fault("after-commit", before, state, old)
            return copy.deepcopy(result)

    def inject_fault(self, phase, before, after, old):
        if not self.fault_config or not self.fault_config.is_file():
            return
        config = json.loads(self.fault_config.read_text())
        operation_id = config["operationId"]
        if config["phase"] == phase and operation_id not in before["operations"] and operation_id in after["operations"]:
            proof = dict(phase=phase, operationId=operation_id, beforeCommit=old,
                         actualCommit=self.git("rev-parse", self.REF), signal="SIGKILL")
            self.fault_config.with_suffix(".fired.json").write_text(json.dumps(proof, indent=2))
            os.kill(os.getpid(), signal.SIGKILL)

    def transaction(self, generation, callback, *, intent="domain"):
        return self._transaction(generation, callback, intent=intent)

    def acquire_generation(self):
        def acquire(state):
            state["generation"] = str(int(state["generation"]) + 1)
            return state["generation"]
        return self._transaction(None, acquire, intent="control")

    def action(self, state, scope, action_id):
        for action in state["scopes"][scope]["actions"]:
            if action["actionId"] == action_id:
                return action
        raise Fault("PRECONDITION_CONFLICT", "No legal domain action")

    def accept_action(self, state, operation, request):
        # Durable acceptance only. Test control can settle the synthetic operation later.
        state["acceptedCount"] += 1
