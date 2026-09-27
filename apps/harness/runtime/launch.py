"""Bundle launch mode of serve-stdio and the instance binding file (feature-t18).

A Host starts the bundle with the Manifest argv template, whose only variable parts are the frozen
placeholders: `-I -B -m hp serve-stdio --bundle --runtime-root ${runtimeRoot} --instance-dir ${instanceDir}
--contract-digest ${contractDigest}`. Nothing is taken from environment variables, and `${resourceHandle}`
is not used.

At start the Runtime checks the contract digest argument, verifies every member of its own package
against bundle.json and rebuilds the archive bytes to obtain its real bundle digest, and reads the
Manifest for the data format and the execution profile requirements. The product-line repository, the
resource handles it may bind and the embedded execution bindings come only from the hp binding file in
${instanceDir} (Owner ruling feature-t18:OD-04), written on the receiving machine with
`hp binding write`. A missing or unusable binding still starts the Runtime; health is degraded with
the reason and no domain state is written.

Initialize adopts the connection identities the Host assigns and accepts only its own verified bundle
digest and launch configuration digest (INTEGRITY_MISMATCH otherwise). runtime.scope.open accepts only a
resource handle the binding file lists (PERMISSION_DENIED otherwise). Everything else is the feature-t16
Dispatcher unchanged.
"""
import argparse
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from bundle import archive
from domain.acceptance.gitrepo import REPOSITORY_LOCATING, environment
from domain.core import DegradedDomain, open_domain
from runtime.dispatcher import Dispatcher
from runtime.protocol import DIGEST, Fault
from runtime.transport import Stdio

BINDING_FILE = "hp-binding.json"
BINDING_SCHEMA = "hp-runtime-binding/v1"
HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}$")
EXECUTION_BINDING_KEYS = ("connectionRef", "credentialRef", "credentialRevision", "configurationRevision", "agent",
                          "protocolProvider")


def package_root():
    return Path(__file__).resolve().parents[4]


class BundleIdentity:
    """Result of the start-time self-check: the rebuilt archive digest or the reason it failed."""

    def __init__(self, root):
        self.root, self.digest, self.launch_digest, self.manifest, self.reason = root, None, None, None, None
        try:
            self._verify()
        except (OSError, ValueError, KeyError, archive.ArchiveError) as exc:
            self.digest, self.reason = None, "bundle self-check failed: " + str(exc)

    def _verify(self):
        executable = Path(sys.executable).resolve()
        if not str(executable).startswith(str(self.root) + os.sep):
            raise ValueError("the interpreter is not the bundle's own: " + str(executable))
        description_bytes = (self.root / "bundle.json").read_bytes()
        description = json.loads(description_bytes)
        if description.get("schema") != "hp-runtime-bundle/v1" or description.get("selfPosition") != 0:
            raise ValueError("bundle.json is not an hp-runtime-bundle/v1 description")
        members = [("bundle.json", description_bytes, "0644")]
        for entry in description["members"]:
            path = entry["path"]
            if not archive.valid_relative_path(path):
                raise ValueError("member path escapes the package: " + path)
            target = self.root / path
            if target.is_symlink() or not target.is_file():
                raise ValueError("member missing or not a regular file: " + path)
            data = target.read_bytes()
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("member bytes differ from bundle.json: " + path)
            executable_bit = bool(target.stat().st_mode & 0o111)
            if executable_bit != (entry["mode"] == "0755"):
                raise ValueError("member mode differs from bundle.json: " + path)
            members.append((path, data, entry["mode"]))
        self.digest = archive.digest(members)
        self.launch_digest = hashlib.sha256((self.root / "launch.json").read_bytes()).hexdigest()
        self.manifest = json.loads((self.root / "manifest.json").read_bytes())
        if self.manifest["permissionProfileDigest"] != self.launch_digest:
            raise ValueError("manifest permissionProfileDigest differs from launch.json")


def read_binding(instance_dir):
    """The binding document, or (None, reason). Never guesses a repository from anything else."""
    path = Path(instance_dir) / BINDING_FILE
    if not path.is_file():
        return None, "no instance binding file: " + BINDING_FILE + " is absent from the instance directory"
    try:
        binding = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        return None, "instance binding file is unreadable: " + str(exc)
    problems = binding_problems(binding)
    if problems:
        return None, "instance binding file is invalid: " + "; ".join(problems)
    return binding, None


def binding_problems(binding):
    problems = []
    if not isinstance(binding, dict) or set(binding) != {"schema", "repository", "resourceHandles", "executionBindings",
                                                         "authorityRef", "writtenAt"}:
        return ["fields differ from " + BINDING_SCHEMA]
    if binding["schema"] != BINDING_SCHEMA:
        problems.append("schema")
    if not isinstance(binding["repository"], str) or not os.path.isabs(binding["repository"]):
        problems.append("repository must be an absolute path")
    handles = binding["resourceHandles"]
    if not isinstance(handles, list) or not handles or not all(isinstance(h, str) and HANDLE.fullmatch(h) for h in handles):
        problems.append("resourceHandles must be a non-empty list of resource handles")
    bindings = binding["executionBindings"]
    if not isinstance(bindings, dict) or not all(
            isinstance(v, dict) and all(isinstance(v.get(k), str) and v.get(k) for k in EXECUTION_BINDING_KEYS)
            for v in bindings.values()):
        problems.append("executionBindings entries need " + ", ".join(EXECUTION_BINDING_KEYS))
    if not isinstance(binding["authorityRef"], str) or not binding["authorityRef"]:
        problems.append("authorityRef")
    return problems


class BundleDispatcher(Dispatcher):
    """The feature-t16 Dispatcher with the two bundle-mode checks in front of initialize and scope.open."""

    def __init__(self, domain, configuration, transport, *, identity, handles, binding_reason):
        super().__init__(domain, configuration, transport)
        self.identity, self.handles, self.binding_reason = identity, frozenset(handles), binding_reason

    def initialize(self, p):
        if self.context is None:
            if self.identity.digest is None:
                raise Fault("INTEGRITY_MISMATCH", self.identity.reason)
            auth = p["launchAuthorization"]
            if p["bundleDigest"] != self.identity.digest or auth["bundleDigest"] != self.identity.digest:
                raise Fault("INTEGRITY_MISMATCH", "bundleDigest differs from this bundle's own archive digest")
            if auth["permissionProfileDigest"] != self.identity.launch_digest:
                raise Fault("INTEGRITY_MISMATCH", "permissionProfileDigest differs from this bundle's launch configuration")
            for key in ("installationId", "instanceId", "incarnationId", "connectionId"):
                self.config[key] = p[key]
            self.config["launchAuthorization"] = copy.deepcopy(auth)
        return super().initialize(p)

    async def scope_open(self, p):
        handle = p["binding"]["resourceHandle"]
        if self.binding_reason is not None:
            raise Fault("PERMISSION_DENIED", self.binding_reason)
        if handle not in self.handles:
            raise Fault("PERMISSION_DENIED", "resource handle is not bound to this instance by its binding file")
        return await super().scope_open(p)


def ignore_git_environment():
    """The repository-locating Git variables (GIT_DIR, GIT_WORK_TREE and the rest of gitrepo.REPOSITORY_LOCATING) would
    steer git subprocesses away from the named or bound repository, including those of mechanism code running in this
    process; hp.main calls this before any route (standalone CLI, binding, development Runtime, bundle mode) and bundle
    mode calls it again before the domain opens. The list is the one the domain strips from its own git subprocesses.
    Transport and authentication variables stay. Only the names are reported, on stderr."""
    ignored = sorted(name for name in os.environ if name in REPOSITORY_LOCATING)
    for name in ignored:
        del os.environ[name]
    if ignored:
        sys.stderr.write("hp ignores repository-locating environment variables: " + ", ".join(ignored) + "\n")
    return ignored


def serve(args):
    if args.contract_digest != DIGEST:
        sys.stderr.write("contract digest argument differs from the frozen Contract 0.1.0 digest\n")
        return 2
    ignore_git_environment()
    root = package_root()
    identity = BundleIdentity(root)
    binding, binding_reason = read_binding(args.instance_dir)
    if identity.digest is None:
        domain, handles, bindings = DegradedDomain(identity.reason), (), {}
    elif binding is None:
        domain, handles, bindings = DegradedDomain(binding_reason), (), {}
    else:
        domain = open_domain(binding["repository"], entry="runtime")
        handles, bindings = binding["resourceHandles"], binding["executionBindings"]
        if not getattr(domain, "available", False):
            binding_reason = getattr(domain, "unavailable_reason", "product-line repository unusable")
    manifest = identity.manifest or {}
    config = dict(installationId=None, instanceId=None, incarnationId=None, connectionId=None, bundleDigest=identity.digest,
                  dataFormat=manifest.get("dataFormat"), launchAuthorization=None,
                  executionProfileRequirements=copy.deepcopy(manifest.get("executionProfileRequirements", [])),
                  executionBindings=copy.deepcopy(bindings), repository=binding["repository"] if binding else None,
                  runtimeRoot=args.runtime_root, instanceDir=args.instance_dir)
    transport = Stdio()
    transport.dispatcher = BundleDispatcher(domain, config, transport, identity=identity, handles=handles,
                                            binding_reason=binding_reason)
    asyncio.run(transport.run())
    return 0


def serve_parser():
    top = argparse.ArgumentParser(prog="hp serve-stdio --bundle")
    top.add_argument("command", choices=["serve-stdio"])
    top.add_argument("--bundle", action="store_true", required=True)
    top.add_argument("--runtime-root", required=True)
    top.add_argument("--instance-dir", required=True)
    top.add_argument("--contract-digest", required=True)
    return top


def main(argv):
    return serve(serve_parser().parse_args(argv))


# -- hp binding write / show ------------------------------------------------------------------------
def emit(document):
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def load_execution_bindings(text):
    if text is None:
        return {}
    raw = Path(text[1:]).read_text() if text.startswith("@") else text
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--execution-bindings must be a JSON object keyed by port id")
    return value


def binding_write(args):
    instance = Path(args.instance_dir)
    if not instance.is_dir():
        return fail("instance-dir", "not an existing directory: " + str(instance))
    repository = Path(args.repository)
    if not repository.is_absolute() or not repository.is_dir():
        return fail("repository", "must be an absolute path of an existing directory")
    # The same environment as the domain's git calls: never an enclosing repository, no repository-locating variables.
    env = environment(repository)
    probe = subprocess.run(["git", "-C", str(repository), "rev-parse", "--show-toplevel"], capture_output=True, text=True, env=env)
    if probe.returncode != 0:
        return fail("repository", "not a Git repository")
    if Path(probe.stdout.strip()).resolve() != repository.resolve():
        return fail("repository", "not the top level of its Git repository")
    try:
        bindings = load_execution_bindings(args.execution_bindings)
    except (OSError, ValueError) as exc:
        return fail("execution-bindings", str(exc))
    document = dict(schema=BINDING_SCHEMA, repository=str(repository.resolve()), resourceHandles=sorted(set(args.resource_handle)),
                    executionBindings=bindings, authorityRef=args.authority_ref,
                    writtenAt=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    problems = binding_problems(document)
    if problems:
        return fail("binding", "; ".join(problems))
    target = instance / BINDING_FILE
    if target.exists() and not args.replace:
        return fail("instance-dir", BINDING_FILE + " already exists; pass --replace to replace it")
    raw = (json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    temporary = instance / (BINDING_FILE + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    emit(dict(result="BINDING_WRITTEN", path=str(target), sha256=hashlib.sha256(raw).hexdigest(), binding=document,
              effect="the Runtime reads it at its next start; ask the Host to reconnect the instance"))
    return 0


def binding_show(args):
    binding, reason = read_binding(args.instance_dir)
    if binding is None:
        return fail("instance-dir", reason)
    raw = (Path(args.instance_dir) / BINDING_FILE).read_bytes()
    emit(dict(result="BINDING_READ", sha256=hashlib.sha256(raw).hexdigest(), binding=binding))
    return 0


def fail(field, message):
    emit(dict(result="BINDING_REFUSED", field=field, message=message))
    return 1


def binding_parser():
    top = argparse.ArgumentParser(prog="hp binding")
    sub = top.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("--instance-dir", required=True)
    write.add_argument("--repository", required=True)
    write.add_argument("--resource-handle", action="append", required=True)
    write.add_argument("--execution-bindings", default=None, help="JSON object by port id, or @<file>")
    write.add_argument("--authority-ref", required=True)
    write.add_argument("--replace", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("--instance-dir", required=True)
    return top


def binding_main(argv):
    args = binding_parser().parse_args(argv)
    return binding_write(args) if args.command == "write" else binding_show(args)
