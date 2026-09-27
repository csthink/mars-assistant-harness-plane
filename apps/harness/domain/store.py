"""Persistence and the two-entry coordination surface for the shared domain state.

Durable state lives at refs/harness/runtime of the product-line repository; the writer lock,
bootstrap and binding live under <git-common-dir>/harness/ (repo-layout r17 §8.1 names exactly these
common-dir members plus harness/executions/). This module implements the DomainPort transaction seam
from domain/port.py:

- one exclusive lock per unit of work, compare-and-swap ref update, no half-written state;
- shared domainRevision advances once per successful write; read-only work never advances it;
- generation is the control generation: whichever entry last acquired it is the current writer, and
  a transaction offered an older generation is refused (feature-t2, FR-31 / NFR-01);
- bootstrap and binding record the facts the standalone CLI and serve-stdio share, and a
  non-cooperating change to them, or to the domain ref inside a held lock, is reported as drift and
  stops the writer instead of being reconciled (FR-31, FR-30).

The control generation itself is persisted inside the domain state at refs/harness/runtime, so no
common-dir member beyond the ones repo-layout §8.1 names is introduced.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from domain.acceptance.gitrepo import GitAbsent, GitUnavailable, environment, probe
from runtime.protocol import Fault

REF = "refs/harness/runtime"
DATA_FORMAT = "hp-domain-v1"
ZERO = "0" * 40
BOOTSTRAP_SCHEMA = "hp-domain-bootstrap/v1"
BINDING_SCHEMA = "hp-domain-binding/v1"
ENTRIES = ("cli", "runtime")

def initial_state(payload_schemas=None):
    return dict(generation="0", revision="0", scopes={}, bindings={}, operations={}, keys={}, indexComplete=True,
                quiesced=False, shutdown=False, barrier=None, upgrades={}, protectedReferences=[], dataFormat=DATA_FORMAT,
                payloadSchemas=dict(payload_schemas or {}), decisionEvidence={}, resources={},
                tasks={}, claims={}, acceptance={}, configuration={})

class StoreUnavailable(Exception):
    """The repository or its common dir cannot be used for durable domain state.

    determinate=True: the reference is not a repository (missing path or .git); False: it exists
    but could not be accessed or answered (permission, timeout, git failure).
    """
    def __init__(self, message, determinate=False):
        self.determinate = determinate
        super().__init__(message)

class Drift(Exception):
    """A non-cooperating change to the domain ref or to the common-dir coordination surface.

    The observed identity, the expected identity and the surface are kept so the caller can fix the
    facts and stop. Drift is never repaired here: no rollback, no synthesised approval, no retry
    under a fresh request identity (FR-31).
    """
    def __init__(self, surface, expected, observed, message=None):
        self.surface, self.expected, self.observed = surface, expected, observed
        super().__init__(message or f"{surface}: expected {expected}, observed {observed}")

    def detail(self):
        return dict(surface=self.surface, expected=self.expected, observed=self.observed)

class LockUnavailable(Exception):
    """The writer lock is held by another writer and was not obtained within the given wait."""

class RuntimeStore:
    REF = REF

    def __init__(self, repository, payload_schemas=None, observer=None):
        self.path = Path(repository)
        self.payload_schemas = dict(payload_schemas or {})
        self.observer = observer  # test-only hook: observer(phase, detail); production passes None
        try:
            probe(self.path)
        except GitAbsent as exc:
            raise StoreUnavailable("not a repository: " + str(exc), determinate=True) from exc
        except GitUnavailable as exc:
            raise StoreUnavailable("repository not accessible: " + str(exc)) from exc
        self.common = Path(self._git("rev-parse", "--path-format=absolute", "--git-common-dir"))
        self.coordination = self.common / "harness"
        self.lock_path = self.coordination / "writer.lock"
        self.bootstrap_path = self.coordination / "bootstrap.json"
        self.binding_path = self.coordination / "binding.json"
        self.expected_bootstrap = None

    def _git(self, *args, data=None):
        env = {**environment(self.path), "GIT_AUTHOR_NAME": "harness", "GIT_AUTHOR_EMAIL": "harness@invalid",
               "GIT_COMMITTER_NAME": "harness", "GIT_COMMITTER_EMAIL": "harness@invalid"}
        try:
            result = subprocess.run(["git", "-C", str(self.path), *args], input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreUnavailable("git " + args[0] + ": " + exc.__class__.__name__) from exc
        if result.returncode:
            raise StoreUnavailable("git " + args[0] + ": " + result.stderr.decode(errors="replace").strip())
        return result.stdout.decode().strip()

    def head(self):
        try:
            result = subprocess.run(["git", "-C", str(self.path), "rev-parse", "--verify", "--quiet", REF], env=environment(self.path),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreUnavailable("git rev-parse: " + exc.__class__.__name__) from exc
        if result.returncode == 0:
            return result.stdout.decode().strip()
        if result.returncode == 1 and not result.stderr.strip():
            return None
        raise StoreUnavailable("domain ref unreadable: " + result.stderr.decode(errors="replace").strip())

    def load(self, commit):
        if commit is None:
            return initial_state(self.payload_schemas)
        try:
            raw = subprocess.run(["git", "-C", str(self.path), "show", REF + ":state.json"], env=environment(self.path),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreUnavailable("git show: " + exc.__class__.__name__) from exc
        if raw.returncode:
            raise StoreUnavailable("domain state unreadable at " + commit)
        return json.loads(raw.stdout)

    def read(self):
        return self.load(self.head())

    def save(self, state, old):
        blob = self._git("hash-object", "-w", "--stdin", data=json.dumps(state, sort_keys=True, ensure_ascii=False).encode())
        tree = self._git("mktree", data=f"100644 blob {blob}\tstate.json\n".encode())
        args = ["commit-tree", tree, "-m", "harness domain transaction"]
        if old:
            args += ["-p", old]
        commit = self._git(*args)
        self._git("update-ref", REF, commit, old or ZERO)
        return commit

    def _locked(self, wait=None):
        """Hold the one writer lock both entries compete for (repo-layout §8.1).

        wait=None blocks until the lock is free. A numeric wait polls and gives up with
        LockUnavailable, which lets a caller prove that another writer holds it without hanging.
        The lock is a cooperating-entry protocol; it does not stop a same-account external program
        from rewriting the repository, which is what drift detection is for.
        """
        self.coordination.mkdir(parents=True, exist_ok=True)
        lock = self.lock_path.open("a")
        if wait is None:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return lock
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock
            except OSError:
                if time.monotonic() >= deadline:
                    lock.close()
                    raise LockUnavailable("writer lock held by another writer: " + str(self.lock_path)) from None
                time.sleep(0.02)

    def _read_json(self, path):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None, None
        except OSError as exc:
            raise StoreUnavailable("coordination surface unreadable: " + str(exc)) from exc
        digest = hashlib.sha256(raw).hexdigest()
        try:
            return json.loads(raw.decode()), digest
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "unparsable", digest

    def bootstrap(self):
        """Create or verify <git-common-dir>/harness/bootstrap.json; returns (record, digest).

        The record pins the facts both entries must agree on before either writes: the domain ref,
        the data format and the repository identity (its root commits). A mismatch is drift.
        """
        record, digest = self._read_json(self.bootstrap_path)
        roots = sorted(self._git("rev-list", "--max-parents=0", "HEAD").split()) if self.head_commit() else []
        expected = dict(schema=BOOTSTRAP_SCHEMA, ref=REF, dataFormat=DATA_FORMAT, repositoryIdentity=roots)
        if record is None:
            self.coordination.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(expected, ensure_ascii=False, sort_keys=True).encode()
            self.bootstrap_path.write_bytes(raw)
            return expected, hashlib.sha256(raw).hexdigest()
        if record == "unparsable" or not isinstance(record, dict) or record.get("schema") != BOOTSTRAP_SCHEMA:
            raise Drift("bootstrap", BOOTSTRAP_SCHEMA, record if record == "unparsable" else (record or {}).get("schema"))
        for field in ("ref", "dataFormat"):
            if record.get(field) != expected[field]:
                raise Drift("bootstrap." + field, expected[field], record.get(field))
        if roots and record.get("repositoryIdentity") and record["repositoryIdentity"] != roots:
            raise Drift("bootstrap.repositoryIdentity", roots, record["repositoryIdentity"])
        return record, digest

    def head_commit(self):
        try:
            return self._git("rev-parse", "--verify", "--quiet", "HEAD")
        except StoreUnavailable:
            return None

    def bind(self, entry, generation):
        """Record the current writer binding; both entries read it and neither may share it."""
        if entry not in ENTRIES:
            raise ValueError("unknown entry: " + str(entry))
        record, digest = self.bootstrap()
        self.expected_bootstrap = digest
        binding = dict(schema=BINDING_SCHEMA, entry=entry, controlGeneration=generation, pid=os.getpid(),
                       ref=REF, bootstrapDigest=digest)
        self.binding_path.write_bytes(json.dumps(binding, ensure_ascii=False, sort_keys=True).encode())
        return binding

    def binding(self):
        record, _ = self._read_json(self.binding_path)
        return None if record in (None, "unparsable") else record

    def verify_surface(self, generation):
        """Check the common-dir coordination surface before a fenced write; drift raises Drift."""
        record, digest = self.bootstrap()
        if self.expected_bootstrap is not None and digest != self.expected_bootstrap:
            raise Drift("bootstrap.bytes", self.expected_bootstrap, digest)
        if generation is None:
            return
        binding = self.binding()
        if binding is None:
            raise Drift("binding", BINDING_SCHEMA, None, "writer binding is missing while a fenced write was attempted")
        if binding.get("schema") != BINDING_SCHEMA or binding.get("ref") != REF:
            raise Drift("binding.schema", BINDING_SCHEMA, binding.get("schema"))

    def transaction(self, generation, callback, *, intent="domain", lock_wait=None, fence_surface=False):
        with self._locked(lock_wait) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if fence_surface:
                self.verify_surface(generation)
            old = self.head()
            state = self.load(old)
            before = copy.deepcopy(state)
            if generation is not None and state["generation"] != generation:
                raise Fault("WRITER_CONFLICT", recovery="reconnect")
            if before["barrier"] and intent == "domain":
                raise Fault("BUSY", "Shared domain barrier blocks this writer", recovery="retry-later")
            state["revision"] = str(int(state["revision"]) + 1)
            result = callback(state)
            if before["barrier"] and any(ref not in before["protectedReferences"] for ref in state["protectedReferences"]):
                raise Fault("PRECONDITION_CONFLICT", "Protected references cannot grow behind barrier")
            changed = dict(state, revision=before["revision"]) != before
            if changed:
                if self.observer:
                    self.observer("before-commit", dict(before=before, after=state, old=old))
                # The ref was read under this lock. A different value now is a non-cooperating writer.
                current = self.head()
                if current != old:
                    raise Drift("refs/harness/runtime", old, current, "domain ref moved inside a held writer lock")
                self.save(state, old)
                if self.observer:
                    self.observer("after-commit", dict(before=before, after=state, old=old))
            return copy.deepcopy(result)

    def acquire_generation(self, entry="runtime"):
        """Take over as the current control generation and record the writer binding."""
        def acquire(state):
            state["generation"] = str(int(state["generation"]) + 1)
            return state["generation"]
        generation = self.transaction(None, acquire, intent="control")
        self.bind(entry, generation)
        return generation
