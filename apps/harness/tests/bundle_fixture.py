"""Test-only fixtures for feature-t18: a bundle built from the code under test with a SYNTHETIC in-memory key,
tampered import directories for the admission refusals, and the minimal path walked through an installed bundle.

The build inputs (the fixed interpreter asset and the locked wheels) are read from the directory named by
the environment variable HP_BUNDLE_INPUTS_DIR; there is no default location, and a missing variable is a
failure that names it. Everything else lives in directories the tests create themselves. The real
development publisher key is never used here.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bundle import archive, build, release
import ed25519_synthetic

APP = Path(__file__).resolve().parents[1]
REPOSITORY = APP.parents[1]
INPUTS_VARIABLE = "HP_BUNDLE_INPUTS_DIR"
OPENSSL_VARIABLE = "HP_BUNDLE_OPENSSL"
RUNTIME_ID = "runtime:hp-bundle-test"
PUBLISHER_ID = "publisher:hp-bundle-test"
SOURCE_REFERENCE = "hp bundle test build"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


class MissingInput(RuntimeError):
    pass


def inputs_dir():
    value = os.environ.get(INPUTS_VARIABLE)
    if not value:
        raise MissingInput(INPUTS_VARIABLE + " is not set: name the build inputs directory (interpreter asset and wheels)")
    return Path(value)


def openssl():
    """The OpenSSL program used only to cross-verify signatures; optional, named explicitly."""
    return os.environ.get(OPENSSL_VARIABLE)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def snapshot_commit(scratch):
    """HEAD when apps/ and mechanisms/ are clean, else a commit object of the working tree (no ref, index or HEAD change)."""
    dirty = subprocess.run(["git", "-C", str(REPOSITORY), "status", "--porcelain", "--", "apps", "mechanisms"], capture_output=True,
                           text=True, check=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if not dirty:
        return head, False
    env = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch) / "snapshot-index"), GIT_AUTHOR_NAME="snapshot",
               GIT_AUTHOR_EMAIL="snapshot@invalid", GIT_COMMITTER_NAME="snapshot", GIT_COMMITTER_EMAIL="snapshot@invalid",
               GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z")

    def g(*args):
        return subprocess.run(["git", "-C", str(REPOSITORY), *args], env=env, capture_output=True, text=True, check=True).stdout.strip()
    g("read-tree", "HEAD")
    g("add", "-A", "--", "apps", "mechanisms")
    tree = g("write-tree")
    return g("commit-tree", tree, "-p", head, "-m", "SYNTHETIC working tree snapshot for bundle tests"), True


class Built:
    """One synthetic-key build of the code under test, shared by a test module."""

    _cache = None

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hp-t18-build-")
        self.root = Path(self.temp.name)
        self.inputs = inputs_dir()
        self.commit, self.snapshot = snapshot_commit(self.root)
        self.key = ed25519_synthetic.SyntheticKey()
        self.registry = self.root / "identity-registry.jsonl"
        self.record = build.build(repository=REPOSITORY, commit=self.commit, inputs_dir=self.inputs, runtime_id=RUNTIME_ID,
                                  publisher_id=PUBLISHER_ID, source_reference=SOURCE_REFERENCE, signer=self.key,
                                  output=self.root / "out", identity_registry=self.registry)
        self.import_dir = self.root / "out" / "bundle"
        self.archive = (self.import_dir / "bundle.tar").read_bytes()
        self.members = [(m["path"], m["data"], m["mode"]) for m in archive.read(self.archive)]
        self.by_path = {p: (d, m) for p, d, m in self.members}
        self.release = json.loads((self.import_dir / "release.json").read_bytes())
        self.manifest = json.loads(self.by_path["manifest.json"][0])

    @classmethod
    def shared(cls):
        if cls._cache is None:
            cls._cache = cls()
        return cls._cache

    def rebuild(self, output, **overrides):
        values = dict(repository=REPOSITORY, commit=self.commit, inputs_dir=self.inputs, runtime_id=RUNTIME_ID,
                      publisher_id=PUBLISHER_ID, source_reference=SOURCE_REFERENCE, signer=self.key, output=output,
                      identity_registry=self.root / ("registry-" + Path(output).name + ".jsonl"))
        values.update(overrides)
        return build.build(**values)

    def variant(self, directory, *, members=None, record=None, manifest=None, launch=None, raw_archive=None, sign_with=None,
                signature=None, recompute=True):
        """A re-signed import directory with mutations. manifest(dict) and launch(dict) edit those descriptors;
        members(list)->list edits the member list ([path, data, mode] or [path, data, mode, typeflag, linkname]);
        the record is recomputed from the result unless recompute is False, then record(dict) may edit it;
        raw_archive(bytes)->bytes edits the archive after the record was computed; sign_with signs and is shipped
        as publisher.pub; signature(text)->text edits the signature file."""
        directory = Path(directory)
        items = [list(m) for m in self.members]
        index = {item[0]: i for i, item in enumerate(items)}
        for name, edit in (("launch.json", launch), ("manifest.json", manifest)):
            if edit:
                value = json.loads(items[index[name]][1])
                edit(value)
                items[index[name]][1] = _dumps(value)
        if members:
            items = members(items)
        tar = raw_tar(items)
        key = sign_with or self.key
        value = copy.deepcopy(self.release)
        if recompute:
            regular = [item for item in items if len(item) < 4 or item[3] == "0"]
            manifest_bytes = next((item[1] for item in items if item[0] == "manifest.json"), b"")
            value.update(archive=dict(digest=sha256(tar), bytes=len(tar), format="ustar"),
                         manifest=dict(path="manifest.json", digest=sha256(manifest_bytes), bytes=len(manifest_bytes)),
                         files=[dict(path=item[0], bytes=len(item[1]), sha256=sha256(item[1]), mode=item[2]) for item in regular])
            value["publisher"]["publicKeyDigest"] = release.public_key_digest(key.public_pem)
        if record:
            record(value)
        record_bytes = _dumps(value)
        if raw_archive:
            tar = raw_archive(tar)
        text = release.signature_text(key.sign(record_bytes))
        if signature:
            text = signature(text)
        directory.mkdir(parents=True)
        (directory / "bundle.tar").write_bytes(tar)
        (directory / "release.json").write_bytes(record_bytes)
        (directory / "release.sig").write_bytes(text)
        (directory / "publisher.pub").write_bytes(key.public_pem)
        return directory


def _dumps(value):
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def raw_header(path, size, mode, typeflag="0", linkname=""):
    """A ustar header without the writer's path and type validation (for refusal cases only)."""
    block = bytearray(512)
    raw = path.encode("utf-8")
    name, prefix = (raw, b"") if len(raw) <= 100 else (raw[raw.rindex(b"/", 0, len(raw) - 1) + 1:], raw[:raw.rindex(b"/", 0, len(raw) - 1)])
    block[0:len(name)] = name
    block[100:108] = ("%07o" % int(mode, 8)).encode() + b"\0"
    block[108:116] = b"0000000\0"
    block[116:124] = b"0000000\0"
    block[124:136] = ("%011o" % size).encode() + b"\0"
    block[136:148] = b"00000000000\0"
    block[148:156] = b" " * 8
    block[156:157] = typeflag.encode()
    block[157:157 + len(linkname)] = linkname.encode()
    block[257:263] = b"ustar\0"
    block[263:265] = b"00"
    block[345:345 + len(prefix)] = prefix
    block[148:156] = ("%06o" % sum(block)).encode() + b"\0 "
    return bytes(block)


def raw_tar(items):
    """items: [path, data, mode] or [path, data, mode, typeflag, linkname]."""
    out = bytearray()
    for item in items:
        path, data, mode = item[0], item[1], item[2]
        typeflag = item[3] if len(item) > 3 else "0"
        linkname = item[4] if len(item) > 4 else ""
        payload = data if typeflag == "0" else b""
        out += raw_header(path, len(payload), mode, typeflag, linkname)
        out += payload + b"\0" * ((512 - len(payload) % 512) % 512)
    return bytes(out + b"\0" * 1024)


def bundle_command(package, *args):
    return [str(Path(package) / "python" / "bin" / "python3.12"), "-I", "-B", "-m", "hp", *args]


def run_bundle_cli(package, env, *args, check=True):
    """The standalone CLI inside an installed bundle; one JSON document on stdout."""
    result = subprocess.run(bundle_command(package, *args), capture_output=True, text=True, env=env, timeout=600)
    document = json.loads(result.stdout) if result.stdout.strip() else None
    if check and result.returncode != 0:
        raise AssertionError("bundle CLI %s exited %d: %s %s" % (" ".join(args[:2]), result.returncode, result.stdout[-2000:],
                                                                   result.stderr[-2000:]))
    return result.returncode, document, result.stderr


class BundlePath:
    """The J-03 minimal path walked through an installed bundle (Definition AC-08).

    Test-side setup plays the environment and the Human: a synthetic product line with its validator, author
    evidence, Registry copy and ignore rule; a local bare remote; the SYNTHETIC platform program and Agent; the
    candidate Definition commit. Every domain command runs inside the installed bundle: acceptance and the final
    projection through its serve-stdio under the synthetic Host, everything else through its standalone CLI.
    """

    def __init__(self, root, installation, *, handle="resource:bundle-path"):
        import definition_fixture as DF
        import implement_verify_fixture as IF
        import publish_fixture as PF
        from product_line import create_product_line, git, write
        self.DF, self.IF, self.PF, self.git = DF, IF, PF, git
        self.root, self.installation, self.handle, self.task_id = Path(root), installation, handle, "feature-t0"
        self.repo, _ = create_product_line(self.root / "repo")
        git(self.repo, "config", "user.name", "Synthetic")
        git(self.repo, "config", "user.email", "synthetic@invalid")
        write(self.repo, DF.VALIDATOR, (DF.HP / DF.VALIDATOR).read_bytes())
        write(self.repo, DF.EVIDENCE, "Synthetic author evidence: human declaration fixture.\n")
        write(self.repo, DF.REGISTRY, json.dumps(DF.live_registry_copy(standalone=True), indent=1) + "\n")
        write(self.repo, ".gitignore", "tasks/*/attempts/\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "synthetic validator, registry, author evidence and ignore rule")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.bare = self.root / "remote.git"
        git(self.root, "init", "-q", "--bare", str(self.bare))
        git(self.repo, "remote", "add", "origin", str(self.bare))
        self.platform = PF.SyntheticPlatform(self.root / "platform", self.bare)
        self.agent = IF.SyntheticAgent(self.root / "agent")
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = dict(GIT_ENV, PATH="/usr/bin:/bin", HOME=str(self.home))
        self.steps = []

    def cli(self, *args):
        code, document, stderr = run_bundle_cli(self.installation.package, self.env, *args, "--repository", str(self.repo))
        self.steps.append(dict(entry="bundle-cli", argv=list(args[:2]), exit=code, result=(document or {}).get("result")))
        return document

    def owner(self):
        return self.IF.OWNER

    def write_binding(self):
        code, document, stderr = run_bundle_cli(self.installation.package, self.installation.environment(), "binding", "write",
                                                "--instance-dir", str(self.installation.instance_dir), "--repository", str(self.repo),
                                                "--resource-handle", self.handle, "--authority-ref", self.owner())
        self.steps.append(dict(entry="bundle-cli", argv=["binding", "write"], exit=code, result=document["result"]))
        return document

    def accept_through_runtime(self, host):
        """Runtime segment: task.accept with a trusted Host decision, through the bundle's serve-stdio."""
        from domain.acceptance import projection as acceptance_projection
        host.start()
        cap = acceptance_projection.capability()["id"]
        methods = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                   "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]
        scope, _ = host.open_scope(self.handle, [(cap, m) for m in methods])
        page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
        action = next(a for a in page["actions"] if a["actionId"] == "task.accept")
        params = dict(operationId="op:accept-1", idempotencyKey="key:accept-1", scopeRef=scope, actionId=action["actionId"],
                      objectRef=action["objectRef"], expectedRevision=action["expectedRevision"], candidateRef=action["candidateRef"],
                      grantRefs=[g["ref"] for g in host.grants],
                      payload=dict(taskType="feature", taskId=self.task_id, baseRef="main", worktreeRoot=str(self.root / "worktrees")),
                      decisionRef=None)
        decided = decide(host, params)
        accepted = host.call("runtime.action.invoke", decided)
        operation = wait_operation(host, scope, decided["operationId"])
        self.steps.append(dict(entry="bundle-serve-stdio", argv=["runtime.action.invoke", "task.accept"], exit=0,
                               result=operation["status"]))
        return scope, page, accepted, operation

    def definition_and_freeze(self):
        worktree = Path(self.state()["tasks"][self.task_id]["worktree"])
        self.worktree = worktree
        commit = self.DF.commit_candidate(worktree, self.IF.definition_text(self.task_id), task_id=self.task_id)
        owner = self.owner()
        self.cli("definition", "submit", "--task-id", self.task_id, "--command-id", "def-submit", "--authority-ref", owner,
                 "--commit", commit, "--author", json.dumps(self.DF.author(self.head)))
        self.cli("definition", "decide", "--task-id", self.task_id, "--command-id", "def-decide", "--authority-ref", owner,
                 "--decision", "Authorize & Freeze", "--decision-text", "定稿 " + self.task_id)
        self.cli("workflow", "advance", "--task-id", self.task_id, "--command-id", "def-e-d17", "--authority-ref", owner,
                 "--edge", "E-D17")
        return commit

    def configure_and_implement(self, agent_version=None):
        import validation_fixture as VF
        owner = self.owner()
        self.cli("config", "set", "implementer-ports", json.dumps([self.IF.entry(agent_path=self.agent.path)]), "--authority-ref", owner)
        for model, vendor in self.IF.VENDORS.items():
            self.cli("config", "set", "author-vendor", vendor, "--agent", self.IF.AGENT_ID, "--model", model, "--authority-ref", owner)
        self.cli("verify", "checks-set", "--checks", json.dumps([VF.check()]), "--authority-ref", owner)
        if agent_version:
            self.agent.write(agent_version)  # a new Agent version with different bytes after registration (OD-399)
        self.agent.set(mode="commit", content="good-1")
        view = self.cli_read("definition", "status")
        finalization = next(r for r in view["frozen"]["rulings"] if r["type"] == "finalization")
        out = self.cli("implement", "dispatch", "--task-id", self.task_id, "--command-id", "d1", "--authority-ref", owner,
                       "--port-id", "local-implementer", "--worktree", str(self.worktree),
                       "--finalization-ref", "RU-%02d" % finalization["number"], "--budget", json.dumps(self.IF.budget()))
        execution_id = out["execution"]["executionRequestId"]
        ran = self.cli("implement", "run", "--task-id", self.task_id, "--execution-id", execution_id)
        verified = self.cli("verify", "run", "--task-id", self.task_id, "--command-id", "v1", "--authority-ref", owner)
        configured = self.cli("validate", "configure", "--task-id", self.task_id, "--command-id", "cfg-1", "--authority-ref", owner)
        return ran, verified, configured

    def cli_read(self, *args):
        code, document, stderr = run_bundle_cli(self.installation.package, self.env, *args, "--repository", str(self.repo),
                                                "--task-id", self.task_id)
        return document

    def publish(self, platform_version=None):
        owner = self.owner()
        value = dict(provider="github", host="github.com", repository=self.PF.REPOSITORY, repositoryId=self.PF.REPOSITORY_ID,
                     remote="origin", remoteAddress=str(self.bare), targetBranch="main", cli=str(self.platform.path))
        self.cli("config", "set", "publish-target", json.dumps(value), "--authority-ref", owner)
        context = self.cli("publish", "context", "--task-id", self.task_id)
        proposed = context["publishBinding"]
        body = self.root / "body.md"
        body.write_text(proposed["pullRequest"]["body"], encoding="utf-8")
        self.cli("publish", "authorize", "--task-id", self.task_id, "--command-id", "auth-1", "--authority-ref", owner,
                 "--decision-text", "发布 " + self.task_id, "--candidate-commit", proposed["candidateCommit"],
                 "--source-branch", proposed["sourceBranch"], "--remote", proposed["remote"], "--target-branch",
                 proposed["targetBranch"], "--title", proposed["pullRequest"]["title"], "--body-file", str(body),
                 "--context-digest", context["contextDigest"])
        self.cli("publish", "dispatch", "--task-id", self.task_id, "--command-id", "pub-1", "--authority-ref", owner)
        if platform_version:
            self.platform.upgrade(platform_version)  # new platform program version and bytes before the run (OD-399)
        ran = self.cli("publish", "run", "--task-id", self.task_id)
        status = self.cli("publish", "status", "--task-id", self.task_id)
        return ran, status

    def state(self):
        from domain.store import RuntimeStore
        return RuntimeStore(self.repo).read()

    def edges(self):
        inst = self.state()["tasks"][self.task_id]["workflowInstance"]
        return [c.get("edgeId") for c in inst["commits"] if c.get("edgeId")]

    def remote_ref(self, branch):
        out = self.git(self.bare, "for-each-ref", "--format=%(objectname)", "refs/heads/" + branch)
        return out or None


def decide(host, params):
    """A trusted Host decision bound to the exact request (the feature-t0 Runtime test form)."""
    from host_driver import request_digest
    p = dict(params)

    def record(p):
        decision = dict(decisionRef="decision:" + p["operationId"], scopeRef=p["scopeRef"], domainOperationId=p["operationId"],
                        method="runtime.action.invoke", requestDigest=p["requestDigest"], actionId=p["actionId"],
                        objectRef=p["objectRef"], candidateRef=p["candidateRef"], expectedRevision=p["expectedRevision"], evidence=[],
                        actorRef="human:synthetic", source="host-trusted-ui", recordedAt="2026-09-24T00:00:00Z", status="valid")
        host.decisions[decision["decisionRef"]] = decision
        return decision["decisionRef"]
    p["requestDigest"] = request_digest("runtime.action.invoke", p)
    p["decisionRef"] = record(p)
    p["requestDigest"] = request_digest("runtime.action.invoke", p)
    p["decisionRef"] = record(p)
    return p


def wait_operation(host, scope, operation_id, statuses=("succeeded", "failed", "unknown")):
    op = None
    for _ in range(100):
        op = host.call("runtime.operation.get", dict(scopeRef=scope, operationId=operation_id))
        if op["status"] in statuses:
            return op
    raise AssertionError("operation did not settle: " + json.dumps(op))
