"""Test-only SYNTHETIC Host for the Runtime development bundle (feature-t18).

It reproduces, in hp's own Python, the receiving Host's admission order and launch behaviour as read
from the Assistant receiver implementation (fixed identities in records/diagnostics/feature-t18/2026-09-24/
inputs.json): the four-file import directory, the seven admission steps with their refusal classes,
installation into an immutable package directory with a re-check before every launch, the `direct`
launcher with the closed argv placeholders (an empty ${resourceHandle}), the instance directory as working
directory and a fixed three-variable environment, and Initialize parameters whose identities the Host
generates. It imports no Assistant code and is never product code; passing here proves the bundle on this
reproduction only, not the receiver's real behaviour.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bundle import archive
import ed25519_synthetic
from host_driver import Host

CONTRACT_VERSION = "0.1.0-draft.5"
CONTRACT_DIGEST = "9d6e6af19a39cc52d0b86f7ce610b44d4b21517feebecf5d88df05f73b83a352"
ARCHIVE_BYTES_MAX = 256 * 1024 * 1024
EXPANDED_CEILING = 1024 * 1024 * 1024
MEMBERS_CEILING = 20000
PLACEHOLDERS = ("${runtimeRoot}", "${instanceDir}", "${contractDigest}", "${resourceHandle}")
LAUNCHERS = ("direct", "electron-node", "python3")
RANK = ["INVALID_SOURCE", "INTEGRITY_MISMATCH", "RESOURCE_LIMIT", "UNSUPPORTED_CAPABILITY", "UNSUPPORTED_VERSION"]
DIGEST = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_ID = re.compile(r"^runtime:[A-Za-z0-9._-]{1,120}$")
PUBLISHER_ID = re.compile(r"^publisher:[A-Za-z0-9._-]{1,120}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
LIMITS = dict(frameBytes=1048576, depth=32, members=1000, inFlight=32, bufferBytes=4194304, eventWindow=128, pageObjects=100,
              textCharacters=65536)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    """The receiver's canonical JSON: sorted keys, no whitespace, JSON.stringify scalars."""
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical(value[k]) for k in sorted(value)) + "}"
    return json.dumps(value, ensure_ascii=False)


def exact(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def record_problems(v):
    problems = []
    if not exact(v, ["schema", "runtimeId", "publisher", "version", "platform", "dataFormat", "archive", "manifest", "files",
                     "limits", "dependencies", "permissionProfileDigest", "maintenance", "source"]):
        return ["release record fields differ from the schema"]
    if v["schema"] != "csthink-runtime-release/v1-candidate":
        problems.append("schema identifier")
    if not isinstance(v["runtimeId"], str) or not RUNTIME_ID.fullmatch(v["runtimeId"]):
        problems.append("runtimeId")
    p = v["publisher"]
    if not (exact(p, ["id", "signatureAlgorithm", "publicKeyDigest"]) and isinstance(p["id"], str) and PUBLISHER_ID.fullmatch(p["id"])
            and p["signatureAlgorithm"] == "ed25519" and isinstance(p["publicKeyDigest"], str) and DIGEST.fullmatch(p["publicKeyDigest"])):
        problems.append("publisher identity")
    if not isinstance(v["version"], str) or not IDENTIFIER.fullmatch(v["version"]):
        problems.append("version")
    if v["platform"] not in ("darwin-arm64", "darwin-x86_64"):
        problems.append("platform")
    if not isinstance(v["dataFormat"], str) or not IDENTIFIER.fullmatch(v["dataFormat"]):
        problems.append("dataFormat")
    if not exact(v["archive"], ["digest", "bytes", "format"]) or v["archive"]["format"] != "ustar":
        problems.append("archive")
    if not exact(v["manifest"], ["path", "digest", "bytes"]) or v["manifest"]["path"] != "manifest.json":
        problems.append("manifest entry")
    if not isinstance(v["files"], list) or not all(exact(f, ["path", "bytes", "sha256", "mode"]) and archive.valid_relative_path(f["path"])
                                                  and f["mode"] in ("0644", "0755") for f in v["files"]):
        problems.append("files")
    if not exact(v["limits"], ["expandedBytesMax", "membersMax"]):
        problems.append("limits")
    if not isinstance(v["dependencies"], list):
        problems.append("dependencies")
    if not isinstance(v["permissionProfileDigest"], str) or not DIGEST.fullmatch(v["permissionProfileDigest"]):
        problems.append("permissionProfileDigest")
    if v["maintenance"] is not None:
        m = v["maintenance"]
        if not (exact(m, ["entrypoint", "argv"]) and archive.valid_relative_path(m["entrypoint"])):
            problems.append("maintenance")
    if not exact(v["source"], ["kind", "reference"]) or v["source"]["kind"] not in ("built-in", "catalog", "offline-import"):
        problems.append("source")
    for forbidden in ("releaseDigest", "recordDigest", "signature", "downloadUrl"):
        if forbidden in v:
            problems.append("forbidden field " + forbidden)
    return problems


def manifest_problems(v):
    keys = ["manifestVersion", "runtimeId", "publisher", "version", "entrypoint", "argv", "platform", "minimumOs", "protocols",
            "capabilities", "permissionProfileDigest", "executionProfileRequirements", "dataFormat", "dependencies"]
    if not exact(v, keys):
        return ["manifest fields differ from the Contract schema"]
    problems = []
    if v["manifestVersion"] != CONTRACT_VERSION:
        problems.append("manifestVersion")
    if not RUNTIME_ID.fullmatch(str(v["runtimeId"])):
        problems.append("runtimeId")
    if not PUBLISHER_ID.fullmatch(str(v["publisher"])):
        problems.append("publisher")
    if not IDENTIFIER.fullmatch(str(v["version"])):
        problems.append("version")
    if not archive.valid_relative_path(v["entrypoint"]):
        problems.append("entrypoint")
    if not isinstance(v["argv"], list) or not all(isinstance(a, str) for a in v["argv"]) or len(v["argv"]) > 64:
        problems.append("argv")
    if v["platform"] != "darwin-arm64":
        problems.append("platform")
    if not re.fullmatch(r"\d+(\.\d+){0,2}", str(v["minimumOs"])):
        problems.append("minimumOs")
    if not isinstance(v["protocols"], list) or not v["protocols"]:
        problems.append("protocols")
    if not isinstance(v["capabilities"], list) or not all(exact(c, ["id", "version", "schemaDigest", "required"]) for c in v["capabilities"]):
        problems.append("capabilities")
    if not DIGEST.fullmatch(str(v["permissionProfileDigest"])):
        problems.append("permissionProfileDigest")
    if not IDENTIFIER.fullmatch(str(v["dataFormat"])):
        problems.append("dataFormat")
    return problems


def launch_problems(v):
    if not exact(v, ["schema", "entrypoint", "argv", "environmentAllowList", "dependencies", "launcher", "trustModel"]):
        return ["launch configuration fields"]
    problems = []
    if v["schema"] != "csthink-runtime-launch/v1":
        problems.append("launch schema")
    if v["launcher"] not in LAUNCHERS:
        problems.append("launcher")
    if v["trustModel"] != "current-user":
        problems.append("trustModel")
    return problems


def placeholder_problems(argv):
    return ["argv placeholder outside the closed set: " + m for a in argv for m in re.findall(r"\$\{[^}]*\}?", a)
            if m not in PLACEHOLDERS]


def schema_refs_ok(value):
    if isinstance(value, list):
        return all(schema_refs_ok(v) for v in value)
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and (not isinstance(child, str) or not child.startswith("#/")):
                return False
            if not schema_refs_ok(child):
                return False
    return True


def os_at_least(actual, minimum):
    a = [int(x) for x in actual.split(".")]
    m = [int(x) for x in minimum.split(".")]
    for i in range(max(len(a), len(m))):
        x, y = (a[i] if i < len(a) else 0), (m[i] if i < len(m) else 0)
        if x != y:
            return x > y
    return True


def below_minimum_os(minimum_os, os_version=None):
    """Why this Host's macOS is below a bundle's minimumOs, or None when it satisfies it.

    The comparison is the one admission step 7 makes, with the Host version read the same way (os_version, else
    platform.mac_ver()); os_version lets a test name the Host version instead of reading this machine's.
    """
    host_os = os_version or platform.mac_ver()[0] or "0"
    if os_at_least(host_os, minimum_os):
        return None
    return "host macOS %s is below the bundle minimumOs %s" % (host_os, minimum_os)


class Verdict:
    def __init__(self):
        self.failures, self.identity_verified, self.incompatibility = {}, False, None
        self.record = self.manifest = self.launch = None
        self.members, self.artifact_digest, self.release_digest, self.public_key_digest = {}, None, None, None
        self.order = []

    def fail(self, code, reason):
        self.failures.setdefault(code, []).append(reason)

    @property
    def code(self):
        if self.failures:
            return sorted(self.failures, key=RANK.index)[0]
        return self.incompatibility["code"] if self.incompatibility else None

    @property
    def reasons(self):
        if self.failures:
            return [r for c in sorted(self.failures, key=RANK.index) for r in self.failures[c]]
        return self.incompatibility["reasons"] if self.incompatibility else []


def admit(source, *, pins=None, host_platform="darwin-arm64", os_version=None):
    """The seven receiver admission steps over an import directory; returns a Verdict."""
    source, v = Path(source), Verdict()
    pins = pins or {}
    files = {n: (source / n).read_bytes() if (source / n).is_file() else None
             for n in ("release.json", "release.sig", "publisher.pub", "bundle.tar")}
    for name, data in files.items():
        if data is None:
            v.fail("INVALID_SOURCE", "missing " + name)
    if v.failures:
        return v
    # 1. signature over the raw record bytes with the bundled publisher key
    try:
        public = ed25519_synthetic.public_from_pem(files["publisher.pub"])
    except ValueError:
        v.fail("INVALID_SOURCE", "publisher.pub is not an Ed25519 public key")
        return v
    v.public_key_digest = sha256(ed25519_synthetic.SPKI_PREFIX + public)
    text = files["release.sig"].decode("utf-8", "replace").strip()
    signature = bytes.fromhex(text) if re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) % 2 == 0 else b""
    if not ed25519_synthetic.verify(public, files["release.json"], signature):
        v.fail("INVALID_SOURCE", "release signature does not verify against publisher.pub")
        return v
    v.release_digest = sha256(files["release.json"])
    # 2. record structure, publisher identity and pinned key
    try:
        record = json.loads(files["release.json"])
    except ValueError:
        v.fail("INTEGRITY_MISMATCH", "release record is not JSON")
        return v
    for problem in record_problems(record):
        v.fail("INTEGRITY_MISMATCH", "release record: " + problem)
    if v.failures:
        return v
    v.record = record
    if record["publisher"]["publicKeyDigest"] != v.public_key_digest:
        v.fail("INVALID_SOURCE", "publisher key digest in the record differs from publisher.pub")
    pinned = pins.get(record["runtimeId"])
    if pinned and pinned != v.public_key_digest:
        v.fail("INVALID_SOURCE", "publisher key differs from the key pinned for " + record["runtimeId"])
    if v.failures:
        return v
    # 3. archive digest and the member list against the signed file list
    tar = files["bundle.tar"]
    v.artifact_digest = sha256(tar)
    if len(tar) > ARCHIVE_BYTES_MAX:
        v.fail("RESOURCE_LIMIT", "archive exceeds the Host archive limit")
    if record["archive"]["digest"] != v.artifact_digest or record["archive"]["bytes"] != len(tar):
        v.fail("INTEGRITY_MISMATCH", "archive digest or size differs from the signed release record")
    if v.failures:
        return v
    try:
        entries = archive.read(tar)
    except archive.ArchiveError as exc:
        v.fail("INTEGRITY_MISMATCH", "archive: " + str(exc))
        return v
    if record["limits"]["membersMax"] > MEMBERS_CEILING or record["limits"]["expandedBytesMax"] > EXPANDED_CEILING:
        v.fail("RESOURCE_LIMIT", "release limits exceed the Host ceiling")
    if len(entries) > record["limits"]["membersMax"]:
        v.fail("RESOURCE_LIMIT", "member count %d exceeds membersMax" % len(entries))
    expanded = 0
    for entry in entries:
        name = entry["path"]
        if entry["type"] != "0":
            v.fail("INTEGRITY_MISMATCH", "member %s is not a regular file (type %s)" % (name, entry["type"]))
            continue
        if not archive.valid_relative_path(name):
            v.fail("INTEGRITY_MISMATCH", "member %s escapes the bundle root" % name)
            continue
        if name in v.members:
            v.fail("INTEGRITY_MISMATCH", "duplicate member path " + name)
            continue
        v.members[name] = (entry["data"], entry["mode"])
        v.order.append(name)
        expanded += entry["size"]
    if expanded > record["limits"]["expandedBytesMax"]:
        v.fail("RESOURCE_LIMIT", "expanded size %d exceeds expandedBytesMax" % expanded)
    listed = {f["path"]: f for f in record["files"]}
    if len(listed) != len(record["files"]):
        v.fail("INTEGRITY_MISMATCH", "duplicate path in the signed file list")
    for name, (data, mode) in v.members.items():
        f = listed.get(name)
        if f is None:
            v.fail("INTEGRITY_MISMATCH", "member %s is not in the signed file list" % name)
        elif f["bytes"] != len(data) or f["sha256"] != sha256(data) or f["mode"] != mode:
            v.fail("INTEGRITY_MISMATCH", "member %s bytes, digest or mode differ from the signed file list" % name)
    for name in listed:
        if name not in v.members:
            v.fail("INTEGRITY_MISMATCH", "listed file %s is missing from the archive" % name)
    if v.failures:
        return v
    # 4. manifest member
    if "manifest.json" not in v.members:
        v.fail("INTEGRITY_MISMATCH", "manifest.json missing")
        return v
    manifest_bytes = v.members["manifest.json"][0]
    if sha256(manifest_bytes) != record["manifest"]["digest"] or len(manifest_bytes) != record["manifest"]["bytes"]:
        v.fail("INTEGRITY_MISMATCH", "manifest digest or size differs from the signed release record")
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError:
        v.fail("INTEGRITY_MISMATCH", "manifest is not JSON")
        return v
    for problem in manifest_problems(manifest):
        v.fail("INTEGRITY_MISMATCH", "manifest: " + problem)
    if v.failures:
        return v
    v.manifest = manifest
    for field, a, b in (("runtimeId", manifest["runtimeId"], record["runtimeId"]), ("publisher", manifest["publisher"], record["publisher"]["id"]),
                        ("version", manifest["version"], record["version"]), ("platform", manifest["platform"], record["platform"]),
                        ("dataFormat", manifest["dataFormat"], record["dataFormat"]),
                        ("permissionProfileDigest", manifest["permissionProfileDigest"], record["permissionProfileDigest"])):
        if a != b:
            v.fail("INTEGRITY_MISMATCH", "%s differs between manifest and release record" % field)
    key = lambda d: "%s@%s#%s" % (d["id"], d["version"], d["digest"])
    if {key(d) for d in manifest["dependencies"]} != {key(d) for d in record["dependencies"]}:
        v.fail("INTEGRITY_MISMATCH", "dependencies differ between manifest and release record")
    if manifest["entrypoint"] not in v.members:
        v.fail("INTEGRITY_MISMATCH", "manifest entrypoint is not a bundle member")
    for problem in placeholder_problems(manifest["argv"]):
        v.fail("INTEGRITY_MISMATCH", problem)
    # 5. launch configuration bound by permissionProfileDigest
    launch_member = v.members.get("launch.json")
    if launch_member is None:
        v.fail("INTEGRITY_MISMATCH", "launch.json missing")
    elif sha256(launch_member[0]) != manifest["permissionProfileDigest"]:
        v.fail("INTEGRITY_MISMATCH", "launch.json digest differs from permissionProfileDigest")
    else:
        launch = json.loads(launch_member[0])
        issues = launch_problems(launch)
        for problem in issues:
            v.fail("INTEGRITY_MISMATCH", problem)
        if not issues:
            if launch["entrypoint"] != manifest["entrypoint"] or canonical(launch["argv"]) != canonical(manifest["argv"]):
                v.fail("INTEGRITY_MISMATCH", "launch configuration entrypoint or argv differ from the manifest")
            if {key(d) for d in launch["dependencies"]} != {key(d) for d in manifest["dependencies"]}:
                v.fail("INTEGRITY_MISMATCH", "launch configuration dependencies differ from the manifest")
            v.launch = launch
    # 6. capability schemas
    for capability in manifest["capabilities"]:
        member = v.members.get("capabilities/%s.json" % capability["id"])
        if member is None:
            v.fail("UNSUPPORTED_CAPABILITY", "capability %s has no packaged schema member" % capability["id"])
            continue
        try:
            schema = json.loads(member[0])
        except ValueError:
            v.fail("UNSUPPORTED_CAPABILITY", "capability %s schema is not JSON" % capability["id"])
            continue
        if sha256(canonical(schema).encode("utf-8")) != capability["schemaDigest"]:
            v.fail("UNSUPPORTED_CAPABILITY", "capability %s schemaDigest differs from its packaged schema" % capability["id"])
        elif not schema_refs_ok(schema):
            v.fail("UNSUPPORTED_CAPABILITY", "capability %s schema uses a non-local $ref" % capability["id"])
    if v.failures:
        return v
    v.identity_verified = True
    # 7. compatibility with this Host
    incompatible = []
    host_os = os_version or platform.mac_ver()[0] or "0"
    if manifest["platform"] != host_platform or record["platform"] != host_platform:
        incompatible.append("platform %s does not match %s" % (manifest["platform"], host_platform))
    if not os_at_least(host_os, manifest["minimumOs"]):
        incompatible.append("minimumOs %s is above this system %s" % (manifest["minimumOs"], host_os))
    if not any(p.get("version") == CONTRACT_VERSION and p.get("contractDigest") == CONTRACT_DIGEST for p in manifest["protocols"]):
        incompatible.append("manifest does not offer Contract 0.1.0 at the frozen contractDigest")
    if manifest["dependencies"]:
        incompatible.append("dependencies are not provided")
    if v.launch and v.launch["launcher"] == "direct" and v.members[manifest["entrypoint"]][1] != "0755":
        incompatible.append("direct launcher requires an executable (0755) entrypoint member")
    if incompatible:
        v.incompatibility = dict(code="UNSUPPORTED_VERSION", reasons=incompatible)
    return v


def install(verdict, runtime_root):
    """Unpack a verified, compatible bundle into packages/<runtimeId>/<artifactDigest> with an install listing."""
    assert verdict.identity_verified and not verdict.incompatibility, verdict.reasons
    target = Path(runtime_root) / "packages" / re.sub(r"[^A-Za-z0-9._-]", "_", verdict.record["runtimeId"]) / verdict.artifact_digest
    if target.exists():
        return target
    for name, (data, mode) in verdict.members.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.chmod(path, 0o755 if mode == "0755" else 0o644)
    (target / ".install").mkdir()
    (target / ".install" / "files.json").write_text(json.dumps(dict(artifactDigest=verdict.artifact_digest,
                                                                   files=verdict.record["files"]), indent=1))
    return target


def verify_installed(directory):
    listing = json.loads((Path(directory) / ".install" / "files.json").read_text())
    return [f["path"] for f in listing["files"]
            if not (Path(directory) / f["path"]).is_file() or sha256((Path(directory) / f["path"]).read_bytes()) != f["sha256"]]


def expand(argv, values):
    out = []
    for arg in argv:
        for key in ("runtimeRoot", "instanceDir", "contractDigest", "resourceHandle"):
            arg = arg.replace("${" + key + "}", values[key])
        out.append(arg)
    return out


class Installation:
    """One admitted installation and its primary instance directory."""

    def __init__(self, verdict, runtime_root, instance="instance:" + uuid.uuid4().hex):
        self.verdict, self.runtime_root = verdict, Path(runtime_root)
        self.package = install(verdict, runtime_root)
        self.installation_id = "installation:" + uuid.uuid4().hex
        self.instance_id = instance
        self.instance_dir = self.runtime_root / "instances" / re.sub(r"[^A-Za-z0-9._-]", "_", instance)
        self.instance_dir.mkdir(parents=True, exist_ok=True)

    def launch_command(self):
        manifest = self.verdict.manifest
        expanded = expand(manifest["argv"], dict(runtimeRoot=str(self.runtime_root), instanceDir=str(self.instance_dir),
                                                 contractDigest=CONTRACT_DIGEST, resourceHandle=""))
        return [str(self.package / manifest["entrypoint"]), *expanded]

    def environment(self, extra=None):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.instance_dir), "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(extra or {})
        return env

    def initialize_params(self, **overrides):
        incarnation, connection = "incarnation:" + uuid.uuid4().hex, "connection:" + uuid.uuid4().hex
        params = dict(installationId=self.installation_id, instanceId=self.instance_id, incarnationId=incarnation,
                      connectionId=connection, bundleDigest=self.verdict.artifact_digest,
                      protocols=[dict(version=CONTRACT_VERSION, contractDigest=CONTRACT_DIGEST)],
                      capabilities=self.verdict.manifest["capabilities"],
                      launchAuthorization=dict(authorizationRef="launch:" + incarnation[12:], bundleDigest=self.verdict.artifact_digest,
                                               permissionProfileDigest=self.verdict.manifest["permissionProfileDigest"],
                                               expiresAt="2099-01-01T00:00:00Z"),
                      executionProfiles=[], limits=dict(LIMITS))
        params.update(overrides)
        return params


class BundleHost(Host):
    """host_driver.Host speaking to an installed bundle started like the receiver starts it."""

    def __init__(self, installation, *, output=None, extra_env=None, argv=None, recheck_package=True):
        self.directory = installation.instance_dir
        self.template = {}
        self.context, self.grants, self.decisions = None, [], {}
        self.frames, self.events, self.responses, self.counter = [], [], {}, 0
        self.output = Path(output) if output else None
        self.queue, self.stderr = queue.Queue(), []
        if recheck_package:  # the receiver re-verifies the installed package before every launch
            missing = verify_installed(installation.package)
            assert not missing, "installed package changed: " + ", ".join(missing[:5])
        self.command = argv or installation.launch_command()
        self.installation = installation
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=installation.instance_dir, env=installation.environment(extra_env), bufsize=0)

        def reader():
            for line in self.process.stdout:
                self.queue.put(line)
            self.queue.put(None)

        def errors():
            for line in self.process.stderr:
                self.stderr.append(line.decode(errors="replace"))
        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        self.error_reader = threading.Thread(target=errors, daemon=True)
        self.error_reader.start()
        self.handlers = {"host.grants.get": self.grants_get, "host.decision.get": self.decision_get}

    def frame(self, method, params):
        """Send one request and return its raw reply frame (result or error), for replies a test must branch on."""
        p = dict(context=self.context, **params)
        self.counter += 1
        request_id = "h:" + str(self.counter)
        self.send(dict(jsonrpc="2.0", id=request_id, method=method, params=p))
        while request_id not in self.responses:
            self.pump(awaiting=method + " " + request_id)
        return self.responses.pop(request_id)

    def start(self, **overrides):
        params = self.installation.initialize_params(**overrides)
        result = self.call("runtime.initialize", params)
        self.check_initialized(params, result)
        self.context = result["context"]
        self.call("runtime.ready")
        return result

    @staticmethod
    def check_initialized(offered, result):
        """The receiver's re-check of Initialized against what it offered (INTEGRITY_MISMATCH otherwise)."""
        context = result["context"]
        for key in ("installationId", "instanceId", "incarnationId", "connectionId"):
            assert context[key] == offered[key], key
        assert context["protocolVersion"] == CONTRACT_VERSION and context["contractDigest"] == CONTRACT_DIGEST
        assert result["selectedProtocol"] == dict(version=CONTRACT_VERSION, contractDigest=CONTRACT_DIGEST)
        offered_caps = {(c["id"], c["version"], c["schemaDigest"]) for c in offered["capabilities"]}
        assert all((c["id"], c["version"], c["schemaDigest"]) in offered_caps for c in result["capabilities"])
        assert all(p in [dict(id=o["id"], version=o["version"], digest=o["digest"]) for o in offered["executionProfiles"]]
                   for p in result["executionProfiles"])

    def open_scope(self, handle, capability_grants):
        """scope.open with a binding for handle, then Grants for the given (capability, operation) pairs and authorize."""
        binding = dict(bindingRef="binding:" + sha256((self.installation.instance_id + "|" + handle).encode())[:32],
                       resourceHandle=handle, expiresAt="2099-01-01T00:00:00Z")
        scope = self.call("runtime.scope.open", dict(binding=binding))["scopeRef"]
        start = len(self.grants)
        for i, (capability, operation) in enumerate(capability_grants):
            self.grants.append(dict(ref=dict(id="grant:%d" % (start + i), revision="1"), installationId=self.context["installationId"],
                                    instanceId=self.context["instanceId"], scopeRef=scope, resourceHandle=handle, capability=capability,
                                    operation=operation, executionRef=None, bundleDigest=self.installation.verdict.artifact_digest,
                                    expiresAt="2099-01-01T00:00:00Z", status="active", purpose="SYNTHETIC bundle acceptance"))
        self.call("runtime.scope.authorize", dict(scopeRef=scope, grantRefs=[g["ref"] for g in self.grants[start:]]))
        return scope, binding
