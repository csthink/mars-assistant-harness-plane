"""Bundle composition: which bytes become members, read only from an exact source commit and from build
inputs whose digests are fixed.

Members are (path, data, mode) triples. Product source comes from `git cat-file` on the named commit,
never from the working tree. The interpreter comes from the fixed python-build-standalone asset, the
dependencies from the wheels whose hashes apps/harness/requirements.lock pins at that commit. Nothing is
downloaded: a missing or mismatching input is a refusal.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

from bundle.archive import valid_relative_path
from domain.acceptance.gitrepo import without_repository_locating

LOCK = "apps/harness/bundle/inputs.lock.json"
REQUIREMENTS = "apps/harness/requirements.lock"
SITE = "python/lib/python3.12/site-packages/"
PTH = SITE + "hp-runtime.pth"
PTH_TEXT = b"../../../../app/apps/harness\n"
APP_PREFIX = "app/"

# Product source: whole directories of apps/harness plus the two bundle modules the Runtime needs itself.
PRODUCT_DIRECTORIES = ("apps/harness/cli/", "apps/harness/contract/", "apps/harness/domain/", "apps/harness/execution/",
                       "apps/harness/runtime/")
PRODUCT_FILES = ("apps/harness/hp.py", "apps/harness/bundle/__init__.py", "apps/harness/bundle/archive.py")
# Mechanism modules the product imports at run time from its own tree (execution/bridge.py and
# domain/policy/inputs.py locate them relative to apps/harness). Self-tests, fixtures, design text and
# the live Registry are not members.
MECHANISM_FILES = tuple("mechanisms/review-channel/" + name for name in (
    "review_channel.py", "review_channel_base.py", "review_channel_contract.py", "review_channel_decisions.py",
    "review_channel_execution.py", "review_channel_execution_schema.json", "review_channel_history.py",
    "review_channel_inputs.py", "review_channel_instruction.py", "review_channel_receipt.py", "review_channel_registry.py",
    "review_channel_request.py", "review_channel_runtime.py", "review_channel_secrets.py", "review_channel_selection.py",
    "review_channel_taskbook.py", "review_channel_verdict.py", "review_evidence.py", "adapters/__init__.py",
    "adapters/claude.py", "adapters/codex.py", "adapters/http.py"))
# Governance and development material that must never be a member, checked by path and by content.
FORBIDDEN_ROOTS = ("tasks/", "records/", "HANDOFF/", "decisions/", "reviews/", "sdd/", "changelog/", ".agents/",
                   "apps/harness/tests/", "mechanisms/review-channel/review_channel_registry.json")
# hp's own tests and governance material are refused among app/ members; third-party wheels are unpacked
# unchanged (their own test packages included), and no member anywhere may be bytecode or a virtualenv.
FORBIDDEN_PATH_PARTS = ("/tests/", "/.venv/", "/HANDOFF/", "/records/", "/reviews/", "review_channel_registry.json")
FORBIDDEN_EVERYWHERE = ("/__pycache__/", "/.venv/")


class BuildRefusal(Exception):
    """A build input is missing, does not match its fixed digest, or cannot become a member."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(field + ": " + message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(repository, *args, data=None):
    result = subprocess.run(["git", "-C", str(repository), *args], input=data, capture_output=True,
                            env=without_repository_locating(os.environ))
    if result.returncode != 0:
        raise BuildRefusal("repository", "git " + " ".join(args[:2]) + " failed: " + result.stderr.decode(errors="replace").strip())
    return result.stdout


class SourceTree:
    """Read-only view of one exact commit."""

    def __init__(self, repository, commit):
        if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
            raise BuildRefusal("source-commit", "must be a full 40-character lowercase commit id")
        self.repository, self.commit = Path(repository), commit
        if git(repository, "cat-file", "-t", commit).strip() != b"commit":
            raise BuildRefusal("source-commit", "not a commit in the repository")
        self.entries = {}
        listing = git(repository, "ls-tree", "-r", "-z", "--full-tree", commit)
        for record in listing.split(b"\0"):
            if not record:
                continue
            meta, path = record.split(b"\t", 1)
            mode, kind, blob = meta.split()
            self.entries[path.decode("utf-8")] = (mode.decode(), kind.decode(), blob.decode())

    def blob(self, path):
        return self.blobs([path])[path]

    def blobs(self, paths):
        """Read many blobs with one `git cat-file --batch` process; path -> (bytes, mode)."""
        wanted = []
        for path in paths:
            if path not in self.entries:
                raise BuildRefusal("source-commit", "path absent at the source commit: " + path)
            mode, kind, blob = self.entries[path]
            if kind != "blob" or mode not in ("100644", "100755"):
                raise BuildRefusal("source-commit", "not a regular file at the source commit: " + path)
            wanted.append((path, blob, "0755" if mode == "100755" else "0644"))
        output = git(self.repository, "cat-file", "--batch", data="".join(b + "\n" for _, b, _ in wanted).encode())
        result, offset = {}, 0
        for path, blob, mode in wanted:
            end = output.index(b"\n", offset)
            header = output[offset:end].split()
            if len(header) != 3 or header[0].decode() != blob or header[1] != b"blob":
                raise BuildRefusal("source-commit", "unexpected object for " + path)
            size = int(header[2])
            result[path] = (output[end + 1:end + 1 + size], mode)
            offset = end + 1 + size + 1
        return result

    def paths(self, prefix):
        return sorted(p for p in self.entries if p.startswith(prefix))

    def blob_digests(self, roots):
        """SHA-256 of every file under the given roots at this commit (content check of forbidden material)."""
        digests = {}
        paths = [p for p in sorted(self.entries) if any(p.startswith(root) or p == root for root in roots)
                 and self.entries[p][1] == "blob" and self.entries[p][0] in ("100644", "100755")]
        for path, (data, _) in self.blobs(paths).items():
            if data:  # an empty file carries no governance content and would match every empty module
                digests.setdefault(sha256(data), path)
        return digests


def product_members(tree):
    members = []
    paths = [p for d in PRODUCT_DIRECTORIES for p in tree.paths(d)] + list(PRODUCT_FILES) + list(MECHANISM_FILES)
    wanted = [p for p in sorted(set(paths)) if "/__pycache__/" not in p and not p.endswith(".pyc")]
    for path, (data, mode) in tree.blobs(wanted).items():
        members.append((APP_PREFIX + path, data, mode))
    return members


def lock(tree):
    data, _ = tree.blob(LOCK)
    return json.loads(data)


def requirements(tree):
    data, _ = tree.blob(REQUIREMENTS)
    pins = []
    for line in data.decode("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)\s+--hash=sha256:([0-9a-f]{64})", line)
        if not match:
            raise BuildRefusal("requirements", "unparsable pin: " + line)
        pins.append(dict(name=match.group(1), version=match.group(2), sha256=match.group(3)))
    return pins


def interpreter_asset(inputs, spec):
    path = Path(inputs) / "python-build-standalone" / spec["releaseTag"] / spec["asset"]
    if not path.is_file():
        raise BuildRefusal("inputs-dir", "interpreter asset missing: " + str(path))
    data = path.read_bytes()
    if len(data) != spec["bytes"] or sha256(data) != spec["sha256"]:
        raise BuildRefusal("inputs-dir", "interpreter asset digest differs from inputs.lock.json: " + str(path))
    return path, data


def _excluded(path, rules):
    return any(rule in path if rule in ("__pycache__/", ".pyc") else path.startswith(rule) for rule in rules)


def interpreter_members(inputs, spec):
    path, data = interpreter_asset(inputs, spec)
    members = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for info in tar.getmembers():
            name = info.name
            if not info.isfile():
                continue  # directories and the convenience symbolic links are never members
            if not any(name == rule or (rule.endswith("/") and name.startswith(rule)) for rule in spec["include"]):
                continue
            if _excluded(name, spec["exclude"]):
                continue
            if not valid_relative_path(name):
                raise BuildRefusal("inputs-dir", "interpreter member path is not bundle-relative: " + name)
            content = tar.extractfile(info).read()
            members.append((name, content, "0755" if info.mode & 0o111 else "0644"))
    if not any(m[0] == spec["entrypoint"] for m in members):
        raise BuildRefusal("inputs-dir", "interpreter entrypoint not found in the asset: " + spec["entrypoint"])
    return dict(path=str(path), bytes=len(data), sha256=sha256(data)), members


def wheel_members(inputs, pins):
    directory = Path(inputs) / "wheels"
    available = {}
    if directory.is_dir():
        for wheel in sorted(directory.glob("*.whl")):
            available.setdefault(sha256(wheel.read_bytes()), wheel)
    members, identities = [], []
    for pin in pins:
        wheel = available.get(pin["sha256"])
        if wheel is None:
            raise BuildRefusal("inputs-dir", "no wheel with the locked hash for %s==%s in %s" % (pin["name"], pin["version"], directory))
        identities.append(dict(pin, file=wheel.name, bytes=wheel.stat().st_size))
        with zipfile.ZipFile(wheel) as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                if info.is_dir():
                    continue
                name = info.filename
                if re.match(r"^[^/]+\.data/", name):
                    raise BuildRefusal("inputs-dir", "wheel with a .data directory is not supported: " + wheel.name)
                target = SITE + name
                if not valid_relative_path(target):
                    raise BuildRefusal("inputs-dir", "wheel member path is not bundle-relative: " + name)
                mode = "0755" if (info.external_attr >> 16) & 0o111 else "0644"
                members.append((target, archive.read(info), mode))
    return identities, members


def forbidden_by_path(members):
    refused = []
    for path, _, _ in members:
        if any(part in "/" + path for part in FORBIDDEN_EVERYWHERE) or path.endswith(".pyc"):
            refused.append(path)
        elif path.startswith(APP_PREFIX):
            source = path[len(APP_PREFIX):]
            if source.startswith(FORBIDDEN_ROOTS) or any(part in "/" + source for part in FORBIDDEN_PATH_PARTS):
                refused.append(path)
    return refused


def governance_content(members, governance_digests):
    """Governance bytes that must not appear in any member. A governance file whose bytes equal a tracked product
    source member is a recorded copy of that product input (for example the frozen Contract under
    records/diagnostics/*/inputs/), not governance material inside the bundle; it is reported as exempt."""
    product = {sha256(data): path for path, data, _ in members if path.startswith(APP_PREFIX)}
    exempt = [dict(governancePath=gpath, productMember=product[digest]) for digest, gpath in sorted(governance_digests.items(),
                                                                                                  key=lambda item: item[1])
              if digest in product]
    return {d: p for d, p in governance_digests.items() if d not in product}, exempt


def forbidden_by_content(members, governance_digests):
    return [dict(member=path, sameBytesAs=governance_digests[sha256(data)]) for path, data, _ in members
            if sha256(data) in governance_digests]


def assemble(tree, inputs):
    """All members except the generated descriptors (manifest, launch, capabilities, bundle.json)."""
    spec = lock(tree)
    pins = requirements(tree)
    interpreter, python_members = interpreter_members(inputs, spec["interpreter"])
    wheels, site_members = wheel_members(inputs, pins)
    members = python_members + site_members + [(PTH, PTH_TEXT, "0644")] + product_members(tree)
    paths = [m[0] for m in members]
    if len(paths) != len(set(paths)):
        duplicates = sorted({p for p in paths if paths.count(p) > 1})
        raise BuildRefusal("layout", "duplicate member paths: " + ", ".join(duplicates[:10]))
    return dict(lock=spec, interpreter=interpreter, wheels=wheels), sorted(members, key=lambda m: m[0].encode("utf-8"))
