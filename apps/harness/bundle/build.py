"""Build the Runtime development bundle from one exact source commit (feature-t18). Publisher tool, not a product command.

    apps/harness/.venv/bin/python -B apps/harness/bundle/build.py \\
        --repository <hp repository> --source-commit <40-hex> --inputs-dir <build inputs directory> \\
        --runtime-id runtime:<name> --publisher-id publisher:<name> --source-reference <text> \\
        --signing-key <private key file> --publisher-key <publisher.pub> --openssl <openssl program> \\
        --identity-registry <jsonl file> --output <new directory>

Every location is an explicit argument; nothing defaults to a machine path and a missing argument is
refused by name. The output directory must not exist. It receives bundle/ (bundle.tar, release.json,
release.sig, publisher.pub: the four files a receiving Host imports) and build-record.json. Exit codes:
0 built, 1 refused (BuildRefusal names the field), 2 unexpected failure.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bundle import archive, layout, manifest, release
from bundle.layout import BuildRefusal, sha256

MEMBER_CEILING = 4096  # release-record schema files maxItems
PROBE_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def stage(directory, members):
    for path, data, mode in members:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o755 if mode == "0755" else 0o644)


def probe(staging):
    home = staging.parent / "probe-home"
    home.mkdir()
    result = subprocess.run([str(staging / manifest.ENTRYPOINT), "-I", "-B", str(Path(__file__).with_name("probe.py")), str(staging)],
                            cwd=staging, env=dict(PROBE_ENVIRONMENT, HOME=str(home)), capture_output=True, timeout=600)
    if result.returncode != 0:
        raise BuildRefusal("probe", "staged interpreter probe failed: " + result.stderr.decode(errors="replace")[-2000:])
    report = json.loads(result.stdout)
    if report["outsideRoot"]:
        raise BuildRefusal("probe", "modules resolved outside the bundle root: " + ", ".join(report["outsideRoot"][:5]))
    if report["flags"] != dict(isolated=1, dont_write_bytecode=1):
        raise BuildRefusal("probe", "staged interpreter did not run isolated without bytecode")
    return report


def registry_check(path, entry):
    """Same runtimeId and version must never name different bytes; an equal entry is idempotent."""
    path = Path(path)
    existing = []
    if path.exists():
        existing = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for item in existing:
        if item["runtimeId"] == entry["runtimeId"] and item["version"] == entry["version"]:
            if item["archiveDigest"] != entry["archiveDigest"] or item["manifestDigest"] != entry["manifestDigest"]:
                raise BuildRefusal("identity-registry", "%s %s is already registered with archive %s; refusing different bytes %s"
                                   % (entry["runtimeId"], entry["version"], item["archiveDigest"], entry["archiveDigest"]))
            return False
    return True


def registry_append(path, entry):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")


def builder_identity(tree):
    own = Path(__file__).resolve().parent
    files = []
    for name in ("__init__.py", "archive.py", "layout.py", "manifest.py", "release.py", "probe.py", "build.py", "inputs.lock.json"):
        data = (own / name).read_bytes()
        committed = tree.blob("apps/harness/bundle/" + name)[0]
        files.append(dict(path="apps/harness/bundle/" + name, sha256=sha256(data), sameAsSourceCommit=data == committed))
    return files


def build(*, repository, commit, inputs_dir, runtime_id, publisher_id, source_reference, signer, output, identity_registry,
          verify=None):
    """Build into output (must not exist). signer: object with sign(bytes)->64 bytes, public_pem, label, identity."""
    output = Path(output)
    if output.exists():
        raise BuildRefusal("output", "output directory must not exist: " + str(output))
    if not source_reference:
        raise BuildRefusal("source-reference", "required")
    version = manifest.version_of(commit)
    manifest.check_identity(runtime_id, publisher_id, version)
    tree = layout.SourceTree(repository, commit)
    inputs, members = layout.assemble(tree, inputs_dir)
    by_path = layout.forbidden_by_path(members)
    if by_path:
        raise BuildRefusal("layout", "governance or development material by path: " + ", ".join(by_path[:5]))
    governance, exempt = layout.governance_content(members, tree.blob_digests(layout.FORBIDDEN_ROOTS))
    by_content = layout.forbidden_by_content(members, governance)
    if by_content:
        raise BuildRefusal("layout", "members identical to governance or test files: " + json.dumps(by_content[:5]))
    output.mkdir(parents=True)
    staging = output / "staging"
    try:
        stage(staging, members)
        report = probe(staging)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(output / "probe-home", ignore_errors=True)
    capabilities, capability_members = manifest.capability_members(report)
    launch = manifest.launch_bytes()
    permission_profile_digest = sha256(launch)
    manifest_bytes = manifest.manifest_bytes(runtime_id, publisher_id, version, capabilities, permission_profile_digest)
    body = [("manifest.json", manifest_bytes, "0644"), ("launch.json", launch, "0644")] + capability_members + members
    bundle_json = manifest.bundle_bytes(runtime_id=runtime_id, version=version, commit=commit, source_reference=source_reference,
                                        inputs=inputs, capabilities=capabilities, members=body)
    ordered = [("bundle.json", bundle_json, "0644")] + body
    if len(ordered) > MEMBER_CEILING:
        raise BuildRefusal("layout", "%d members exceed the release-record ceiling %d" % (len(ordered), MEMBER_CEILING))
    tar = archive.write(ordered)
    limits = release.limits_for(ordered)
    record = release.record_bytes(runtime_id=runtime_id, publisher_id=publisher_id, public_pem=signer.public_pem, version=version,
                                  archive=tar, manifest=manifest_bytes, members=ordered,
                                  permission_profile_digest=permission_profile_digest, source_reference=source_reference,
                                  limits=limits)
    signature = signer.sign(record)
    if verify is not None and not verify(signer.public_pem, record, signature):
        raise BuildRefusal("signing-key", "the detached signature does not verify against the publisher key")
    entry = dict(runtimeId=runtime_id, version=version, sourceCommit=commit, archiveDigest=sha256(tar),
                 manifestDigest=sha256(manifest_bytes))
    new_entry = registry_check(identity_registry, entry)
    directory = release.write_import_directory(output / "bundle", tar, record, signature, signer.public_pem)
    if new_entry:
        registry_append(identity_registry, entry)
    build_record = dict(
        schema="hp-bundle-build-record/v1", runtimeId=runtime_id, publisherId=publisher_id, version=version, sourceCommit=commit,
        sourceReference=source_reference, archive=dict(sha256=sha256(tar), bytes=len(tar), members=len(ordered),
                                                        expandedBytes=sum(len(d) for _, d, _ in ordered)),
        manifest=dict(sha256=sha256(manifest_bytes), bytes=len(manifest_bytes)), launch=dict(sha256=permission_profile_digest, bytes=len(launch)),
        bundleJson=dict(sha256=sha256(bundle_json), bytes=len(bundle_json)),
        releaseRecord=dict(sha256=sha256(record), bytes=len(record)), signature=dict(sha256=sha256(release.signature_text(signature))),
        publisherKey=dict(sha256=sha256(signer.public_pem), spkiDigest=release.public_key_digest(signer.public_pem)),
        limits=limits, capabilities=capabilities, inputs=dict(interpreter=inputs["interpreter"], wheels=inputs["wheels"]),
        signer=dict(label=signer.label, program=signer.identity), probe=dict(python=report["python"], imported=len(report["imported"]),
                                                                            loadedFiles=report["loadedFiles"]),
        builder=builder_identity(tree), identityRegistry=dict(path=str(identity_registry), newEntry=new_entry),
        contentCheck=dict(governanceDigests=len(governance), exemptProductCopies=exempt),
        files={name: dict(bytes=(directory / name).stat().st_size, sha256=sha256((directory / name).read_bytes()))
               for name in ("bundle.tar", "release.json", "release.sig", "publisher.pub")})
    (output / "build-record.json").write_bytes(manifest.dumps(build_record))
    return build_record


def parser():
    top = argparse.ArgumentParser(prog="bundle-build", description="Build the Runtime development bundle from an exact commit.")
    for name in ("--repository", "--source-commit", "--inputs-dir", "--runtime-id", "--publisher-id", "--source-reference",
                 "--signing-key", "--publisher-key", "--openssl", "--identity-registry", "--output"):
        top.add_argument(name, required=True)
    return top


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        public_pem = Path(args.publisher_key).read_bytes()
        signer = release.OpenSSLSigner(args.signing_key, args.openssl, public_pem)
        record = build(repository=args.repository, commit=args.source_commit, inputs_dir=args.inputs_dir, runtime_id=args.runtime_id,
                       publisher_id=args.publisher_id, source_reference=args.source_reference, signer=signer, output=args.output,
                       identity_registry=args.identity_registry,
                       verify=lambda pem, data, sig: release.openssl_verify(args.openssl, pem, data, sig))
    except BuildRefusal as exc:
        sys.stdout.write(json.dumps(dict(result="REFUSED", field=exc.field, message=str(exc)), ensure_ascii=False) + "\n")
        return 1
    except OSError as exc:
        sys.stdout.write(json.dumps(dict(result="REFUSED", field="io", message=str(exc)), ensure_ascii=False) + "\n")
        return 1
    sys.stdout.write(json.dumps(dict(result="BUILT", archive=record["archive"], manifest=record["manifest"],
                                     releaseRecord=record["releaseRecord"], version=record["version"]), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
