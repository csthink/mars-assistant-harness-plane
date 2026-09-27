"""Release record (frozen release-record schema candidate), detached Ed25519 signature and publisher key.

The record binds the archive, the manifest, every member and the publisher identity; it never contains
its own digest or signature. Signing happens in a child process of the OpenSSL command line program with
the private key file the caller names; the key bytes never enter this process, the arguments, the output
or any file written here. Callers that sign in memory (tests with SYNTHETIC keys) pass their own signer.
"""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from bundle.layout import BuildRefusal, sha256
from bundle.manifest import dumps

RECORD_SCHEMA = "csthink-runtime-release/v1-candidate"


def spki_der(public_pem):
    """DER bytes of a PEM "PUBLIC KEY" block (SubjectPublicKeyInfo)."""
    text = public_pem.decode("ascii") if isinstance(public_pem, bytes) else public_pem
    lines = [line.strip() for line in text.strip().splitlines()]
    if not lines or lines[0] != "-----BEGIN PUBLIC KEY-----" or lines[-1] != "-----END PUBLIC KEY-----":
        raise BuildRefusal("publisher-key", "not a PEM public key")
    der = base64.b64decode("".join(lines[1:-1]), validate=True)
    # Ed25519 SubjectPublicKeyInfo: 30 2a 30 05 06 03 2b 65 70 03 21 00 || 32-byte key.
    if len(der) != 44 or der[:12] != bytes.fromhex("302a300506032b6570032100"):
        raise BuildRefusal("publisher-key", "not an Ed25519 public key")
    return der


def public_key_digest(public_pem):
    return hashlib.sha256(spki_der(public_pem)).hexdigest()


def record_bytes(*, runtime_id, publisher_id, public_pem, version, archive, manifest, members, permission_profile_digest,
                 source_reference, limits):
    return dumps(dict(
        schema=RECORD_SCHEMA, runtimeId=runtime_id,
        publisher=dict(id=publisher_id, signatureAlgorithm="ed25519", publicKeyDigest=public_key_digest(public_pem)),
        version=version, platform="darwin-arm64", dataFormat="hp-domain-v1",
        archive=dict(digest=sha256(archive), bytes=len(archive), format="ustar"),
        manifest=dict(path="manifest.json", digest=sha256(manifest), bytes=len(manifest)),
        files=[dict(path=p, bytes=len(d), sha256=sha256(d), mode=m) for p, d, m in members],
        limits=limits, dependencies=[], permissionProfileDigest=permission_profile_digest, maintenance=None,
        source=dict(kind="offline-import", reference=source_reference)))


def limits_for(members):
    """Fixed upper bounds rounded up from the measured values (256 members, 1 MiB)."""
    count = len(members)
    expanded = sum(len(d) for _, d, _ in members)
    return dict(expandedBytesMax=(expanded // 1048576 + 1) * 1048576, membersMax=(count // 256 + 1) * 256)


def program_identity(path):
    """Rediscovered at every use and recorded; never compared with an allowlist."""
    real = Path(path).resolve()
    if not real.is_file():
        raise BuildRefusal("openssl", "program not found: " + str(path))
    version = subprocess.run([str(real), "version"], capture_output=True, text=True, timeout=30)
    return dict(path=str(path), resolved=str(real), sha256=sha256(real.read_bytes()), version=version.stdout.strip())


class OpenSSLSigner:
    """Ed25519 signing by the OpenSSL command line program with an explicit private key path."""

    def __init__(self, key_path, openssl, public_pem):
        self.key_path, self.openssl = str(key_path), str(openssl)
        if not Path(self.key_path).is_file():
            raise BuildRefusal("signing-key", "private key file not found: " + self.key_path)
        self.public_pem = public_pem if isinstance(public_pem, bytes) else Path(public_pem).read_bytes()
        spki_der(self.public_pem)
        self.identity = program_identity(self.openssl)
        self.label = "openssl-pkeyutl"

    def sign(self, data):
        # OpenSSL signs Ed25519 in one shot and needs the message as a file; the message is public.
        with tempfile.TemporaryDirectory(prefix="hp-bundle-sign-") as directory:
            message = Path(directory) / "message"
            message.write_bytes(data)
            result = subprocess.run([self.openssl, "pkeyutl", "-sign", "-rawin", "-inkey", self.key_path, "-in", str(message)],
                                    capture_output=True, timeout=60)
        if result.returncode != 0 or len(result.stdout) != 64:
            raise BuildRefusal("signing-key", "OpenSSL signing failed (exit %d)" % result.returncode)
        return result.stdout


def openssl_verify(openssl, public_pem, data, signature):
    """Verify a detached Ed25519 signature with the OpenSSL program; only public material touches disk."""
    with tempfile.TemporaryDirectory(prefix="hp-bundle-verify-") as directory:
        base = Path(directory)
        (base / "publisher.pub").write_bytes(public_pem)
        (base / "data").write_bytes(data)
        (base / "sig").write_bytes(signature)
        result = subprocess.run([str(openssl), "pkeyutl", "-verify", "-pubin", "-inkey", str(base / "publisher.pub"), "-rawin",
                                 "-in", str(base / "data"), "-sigfile", str(base / "sig")], capture_output=True, timeout=60)
    return result.returncode == 0


def signature_text(signature):
    return (signature.hex() + "\n").encode("ascii")


def write_import_directory(directory, archive, record, signature, public_pem):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for name, data in (("bundle.tar", archive), ("release.json", record), ("release.sig", signature_text(signature)),
                       ("publisher.pub", public_pem)):
        (directory / name).write_bytes(data)
        os.chmod(directory / name, 0o644)
    return directory
