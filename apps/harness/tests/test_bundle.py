"""feature-t18 Runtime development bundle: composition, identity, reproducibility, admission, launch, binding,
recovery and the J-03 minimal path through an installed bundle.

The bundle under test is built from the code under test (HEAD, or a commit object of the working tree) with a
SYNTHETIC in-memory Ed25519 key. Build inputs come from HP_BUNDLE_INPUTS_DIR and the OpenSSL program used for
signature cross-checks from HP_BUNDLE_OPENSSL; both must be named explicitly. The Host is the SYNTHETIC
reproduction in bundle_host.py; product lines, remotes, platform and Agent are synthetic. No real Host, model,
remote, platform or publisher key is used.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bundle import archive, build, layout, release
from bundle.layout import BuildRefusal
from runtime.protocol import Schemas
import bundle_fixture as BF
import bundle_host as BH
import ed25519_synthetic
from host_driver import request_digest
from product_line import create_product_line, git
import instance_area

APP = Path(__file__).resolve().parents[1]
# feature-t7 AC-08 reference edge sequence (records/diagnostics/feature-t7/2026-09-23/implementation-r1/report.json,
# persistentState of test_publish.PublishCase.test_j03_minimal_path_from_acceptance_to_published).
T7_J03_EDGES = ["E-D01", "E-D02", "E-D04", "E-D09", "E-D17", "E-I01", "E-I02", "E-I03", "E-I04", "E-I06", "E-V02", "E-V06"]
# Private key encodings: a PEM private key block with a body, the Ed25519 PKCS#8 base64 and DER prefixes and their hex.
PRIVATE_PATTERNS = (re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=]{16,}"),
                    re.compile(re.escape(__import__("base64").b64encode(ed25519_synthetic.PKCS8_PREFIX)[:20])),
                    re.compile(re.escape(ed25519_synthetic.PKCS8_PREFIX)), re.compile(re.escape(ed25519_synthetic.PKCS8_PREFIX.hex().encode())))
ACCEPT_METHODS = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                  "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]


def instance_governance_digests():
    """SHA-256 of every non-empty file under the instance-area roots of layout.FORBIDDEN_ROOTS (tasks/, records/, ...).
    In a product-line repository these files are part of the source commit; this repository carries the mechanism
    area only, so they are read from the instance area (instance_area)."""
    digests = {}
    for root in layout.FORBIDDEN_ROOTS:
        if not root.endswith("/") or root.startswith(("apps/", "mechanisms/", ".agents/")):
            continue
        base = instance_area.path(root.rstrip("/"))
        for path in sorted(p for p in base.rglob("*") if p.is_file() and not p.is_symlink()) if base.is_dir() else []:
            data = path.read_bytes()
            if data:
                digests.setdefault(layout.sha256(data), root + path.relative_to(base).as_posix())
    return digests


def case_directory(test, prefix):
    root = os.environ.get("HP_TEST_OUTPUT")
    if root:
        directory = Path(root) / ("t18-" + test._testMethodName)
        directory.mkdir(parents=True, exist_ok=False)
        return directory, None
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    return Path(temp.name), temp


def required_openssl():
    value = BF.openssl()
    if not value:
        raise BF.MissingInput(BF.OPENSSL_VARIABLE + " is not set: name the OpenSSL program used to cross-verify signatures")
    return value


class Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = BF.Built.shared()

    def setUp(self):
        self.directory, self.temp = case_directory(self, "hp-t18-")
        self.hosts = []

    def tearDown(self):
        for host in self.hosts:
            host.close()
        if self.temp is not None:
            self.temp.cleanup()

    def host(self, installation, **kw):
        h = BH.BundleHost(installation, output=self.directory / ("frames-%d.jsonl" % len(self.hosts)), **kw)
        self.hosts.append(h)
        return h

    def installation(self, name="rt"):
        verdict = BH.admit(self.b.import_dir)
        self.assertTrue(verdict.identity_verified and not verdict.incompatibility, verdict.reasons)
        return BH.Installation(verdict, self.directory / name)

    def product_line(self, name="pl"):
        repo, head = create_product_line(self.directory / name / "repo")
        return repo, head

    def bind(self, installation, repo, *handles, extra=()):
        code, doc, err = BF.run_bundle_cli(installation.package, installation.environment(), "binding", "write", "--instance-dir",
                                           str(installation.instance_dir), "--repository", str(repo),
                                           *[x for h in handles for x in ("--resource-handle", h)], "--authority-ref",
                                           "owner:synthetic", *extra)
        self.assertEqual(doc["result"], "BINDING_WRITTEN", doc)
        return doc


# -- AC-01, AC-02, AC-03, AC-09 (static), AC-10 -------------------------------------------------------------------
class BuildCase(Case):
    def test_ac01_members_trace_to_the_commit_and_fixed_inputs(self):
        """AC-01: every member comes from the source commit, the fixed interpreter asset, a locked wheel or a generated descriptor."""
        tree = layout.SourceTree(BF.REPOSITORY, self.b.commit)
        spec = layout.lock(tree)["interpreter"]
        _, python_members = layout.interpreter_members(self.b.inputs, spec)
        _, wheel_members = layout.wheel_members(self.b.inputs, layout.requirements(tree))
        product = {p: (d, m) for p, d, m in layout.product_members(tree)}
        expected = {p: (d, m) for p, d, m in python_members + wheel_members}
        expected.update(product)
        expected[layout.PTH] = (layout.PTH_TEXT, "0644")
        generated = {"bundle.json", "manifest.json", "launch.json"} | {"capabilities/%s.json" % c["id"] for c in self.b.manifest["capabilities"]}
        for path, data, mode in self.b.members:
            if path in generated:
                continue
            self.assertIn(path, expected, path)
            self.assertEqual((data, mode), expected[path], path)
        self.assertEqual(set(p for p, _, _ in self.b.members) - generated, set(expected))
        for path in product:
            self.assertTrue(path.startswith("app/"), path)
            data, _ = tree.blob(path[len("app/"):])
            self.assertEqual(data, product[path][0])

    @instance_area.needed
    def test_ac01_no_governance_test_or_development_material(self):
        """AC-01: by path and by content no governance record, contract, ruling, progress file, review original, live Registry, test or venv is a member; injected ones are refused."""
        self.assertEqual(layout.forbidden_by_path(self.b.members), [])
        tree = layout.SourceTree(BF.REPOSITORY, self.b.commit)
        digests = tree.blob_digests(layout.FORBIDDEN_ROOTS)
        for digest, path in instance_governance_digests().items():
            digests.setdefault(digest, path)
        governance, exempt = layout.governance_content(self.b.members, digests)
        self.assertEqual(layout.forbidden_by_content(self.b.members, governance), [])
        self.assertEqual({e["productMember"] for e in exempt}, {"app/apps/harness/contract/methods.json", "app/apps/harness/contract/schema.json"})
        paths = [p for p, _, _ in self.b.members]
        self.assertFalse([p for p in paths if p.startswith(("app/tasks/", "app/records/", "app/HANDOFF/", "app/apps/harness/tests/"))])
        self.assertNotIn("app/mechanisms/review-channel/review_channel_registry.json", paths)
        self.assertFalse([p for p in paths if "selftest" in p and p.startswith("app/")])
        for injected in ("app/tasks/feature-t18/rulings/RU-02-definition-finalization.md", "app/HANDOFF/progress/feature-t18.md",
                         "app/apps/harness/tests/test_bundle.py", "app/mechanisms/review-channel/review_channel_registry.json",
                         "python/lib/python3.12/__pycache__/os.cpython-312.pyc", "app/apps/harness/.venv/bin/python"):
            self.assertEqual(layout.forbidden_by_path([(injected, b"x", "0644")]), [injected])
        ruling = instance_area.path("tasks/feature-t18/rulings/RU-02-definition-finalization.md").read_bytes()
        registry = tree.blob("mechanisms/review-channel/review_channel_registry.json")[0]
        hidden = [("python/lib/python3.12/site-packages/x/notes.md", ruling, "0644"), ("app/apps/harness/domain/r.json", registry, "0644")]
        self.assertEqual(len(layout.forbidden_by_content(hidden, governance)), 2)

    def test_ac01_bundle_json_declares_subset_sources_and_missing_capabilities(self):
        """AC-01: bundle.json names the source commit, the delivered subset, the missing capabilities and that it is not the complete public package."""
        description = json.loads(self.b.by_path["bundle.json"][0])
        self.assertEqual(description["schema"], "hp-runtime-bundle/v1")
        self.assertEqual(description["sourceCommit"], self.b.commit)
        self.assertIn("not the complete public installation package", description["statement"])
        self.assertEqual(description["delivered"]["capabilities"], [c["id"] for c in self.b.manifest["capabilities"]])
        joined = " ".join(description["missing"])
        for needle in ("installation, upgrade and uninstall", "check / init / fix", "mechanism payload", "notarisation"):
            self.assertIn(needle, joined)
        self.assertEqual(description["buildInputs"]["interpreter"]["sha256"], self.b.record["inputs"]["interpreter"]["sha256"])
        self.assertEqual([m["path"] for m in description["members"]], [p for p, _, _ in self.b.members[1:]])
        self.assertEqual(self.b.members[0][0], "bundle.json")

    def test_ac02_release_record_binds_archive_manifest_members_and_publisher(self):
        """AC-02: the record binds archive, manifest, every member, publisher, limits and the launch digest, never itself; same-name fields agree."""
        r, m = self.b.release, self.b.manifest
        self.assertEqual(BH.record_problems(r), [])
        self.assertEqual(r["archive"], dict(digest=BF.sha256(self.b.archive), bytes=len(self.b.archive), format="ustar"))
        manifest_bytes = self.b.by_path["manifest.json"][0]
        self.assertEqual(r["manifest"], dict(path="manifest.json", digest=BF.sha256(manifest_bytes), bytes=len(manifest_bytes)))
        self.assertEqual(r["files"], [dict(path=p, bytes=len(d), sha256=BF.sha256(d), mode=mo) for p, d, mo in self.b.members])
        self.assertEqual(r["permissionProfileDigest"], BF.sha256(self.b.by_path["launch.json"][0]))
        self.assertEqual(r["publisher"], dict(id=BF.PUBLISHER_ID, signatureAlgorithm="ed25519",
                                              publicKeyDigest=release.public_key_digest(self.b.key.public_pem)))
        self.assertEqual((r["dependencies"], r["maintenance"], r["source"]["kind"]), ([], None, "offline-import"))
        for field in ("runtimeId", "version", "platform", "dataFormat", "permissionProfileDigest"):
            self.assertEqual(m[field], r[field], field)
        self.assertEqual(m["publisher"], r["publisher"]["id"])
        self.assertLessEqual(len(self.b.members), r["limits"]["membersMax"])
        self.assertLessEqual(sum(len(d) for _, d, _ in self.b.members), r["limits"]["expandedBytesMax"])
        for forbidden in ("releaseDigest", "recordDigest", "signature", "downloadUrl"):
            self.assertNotIn(forbidden, r)

    def test_ac02_manifest_and_launch_follow_the_frozen_contract(self):
        """AC-02: the Manifest validates against the frozen Contract schema, the argv uses only the closed placeholders, launch.json repeats entry and argv."""
        Schemas().validate("Manifest", self.b.manifest)
        self.assertEqual(BH.manifest_problems(self.b.manifest), [])
        self.assertEqual(BH.placeholder_problems(self.b.manifest["argv"]), [])
        self.assertNotIn("${resourceHandle}", " ".join(self.b.manifest["argv"]))
        launch = json.loads(self.b.by_path["launch.json"][0])
        self.assertEqual(BH.launch_problems(launch), [])
        self.assertEqual((launch["entrypoint"], launch["argv"], launch["launcher"]), (self.b.manifest["entrypoint"], self.b.manifest["argv"], "direct"))
        self.assertEqual(self.b.by_path[self.b.manifest["entrypoint"]][1], "0755")
        self.assertEqual(self.b.manifest["protocols"], [dict(version=BH.CONTRACT_VERSION, contractDigest=BH.CONTRACT_DIGEST)])

    def test_ac02_capability_members_match_their_schema_digests(self):
        """AC-02: each capabilities/<id>.json hashes to its schemaDigest under RFC 8785 and the receiver's canonical JSON, with local references only."""
        import rfc8785
        self.assertEqual(len(self.b.manifest["capabilities"]), 7)
        for capability in self.b.manifest["capabilities"]:
            data = self.b.by_path["capabilities/%s.json" % capability["id"]][0]
            schema = json.loads(data)
            self.assertEqual(BF.sha256(rfc8785.dumps(schema)), capability["schemaDigest"])
            self.assertEqual(BF.sha256(BH.canonical(schema).encode()), capability["schemaDigest"])
            self.assertTrue(BH.schema_refs_ok(schema))
            self.assertFalse(capability["required"])

    def test_ac02_every_action_payload_schema_is_in_its_packaged_capability(self):
        """AC-02 (OD-425 R1, R4): every action the Runtime can offer names a declared capability whose packaged capabilities/<id>.json holds its payload schema, as the document itself or as exactly one definitions entry named by the actionId."""
        import rfc8785
        from domain.core import HarnessDomain
        declared = {c["id"]: c for c in self.b.manifest["capabilities"]}
        with tempfile.TemporaryDirectory(prefix="hp-od425-bundle-") as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            domain = HarnessDomain(directory, entry="runtime")
            state = domain.store.read()
            state["scopes"]["scope:probe"] = dict(resourceHandle="r", objects=[], actions=[], pendingItems=[], events=[],
                                                  streamId="s", epoch="1", seq="0", logFloor="0")
            domain.build_projections(state)
        actions = state["scopes"]["scope:probe"]["actions"]
        self.assertEqual(len(actions), 20)
        for action in actions:
            capability = action["capability"]
            self.assertEqual(declared[capability["id"]], capability, action["actionId"])
            document = json.loads(self.b.by_path["capabilities/%s.json" % capability["id"]][0])
            if action["payloadSchemaDigest"] == capability["schemaDigest"]:
                continue
            entries = document.get("definitions", {})
            names = [n for n, e in entries.items() if BF.sha256(rfc8785.dumps(e)) == action["payloadSchemaDigest"]]
            self.assertEqual(names, [action["actionId"]], action["actionId"])
            self.assertEqual(BF.sha256(BH.canonical(entries[action["actionId"]]).encode()), action["payloadSchemaDigest"])

    def test_ac02_detached_signature_verifies_with_two_implementations(self):
        """AC-02: the detached Ed25519 signature verifies with the synthetic Host's pure implementation and with OpenSSL; tampering fails both."""
        record = (self.b.import_dir / "release.json").read_bytes()
        signature = bytes.fromhex((self.b.import_dir / "release.sig").read_text().strip())
        public_pem = (self.b.import_dir / "publisher.pub").read_bytes()
        self.assertTrue(ed25519_synthetic.verify(ed25519_synthetic.public_from_pem(public_pem), record, signature))
        self.assertFalse(ed25519_synthetic.verify(ed25519_synthetic.public_from_pem(public_pem), record + b" ", signature))
        openssl = required_openssl()
        self.assertTrue(release.openssl_verify(openssl, public_pem, record, signature))
        self.assertFalse(release.openssl_verify(openssl, public_pem, record + b" ", signature))
        self.assertEqual(release.program_identity(openssl)["path"], openssl)

    def test_ac03_rebuild_from_the_same_commit_is_byte_identical(self):
        """AC-03: two independent builds of the same commit and inputs produce the same archive, manifest, record and signature bytes."""
        second = self.b.rebuild(self.directory / "second")
        for name in ("bundle.tar", "release.json", "release.sig", "publisher.pub"):
            self.assertEqual((self.directory / "second" / "bundle" / name).read_bytes(), (self.b.import_dir / name).read_bytes(), name)
        self.assertEqual(second["archive"], self.b.record["archive"])
        self.assertEqual(second["version"], "0.1.0-dev." + self.b.commit[:12])

    def test_ac03_missing_or_mismatching_inputs_are_refused_without_download(self):
        """AC-03: a missing wheel, a tampered interpreter asset or a missing asset refuses the build and names the input; nothing is fetched."""
        inputs = self.directory / "inputs"
        shutil.copytree(self.b.inputs / "wheels", inputs / "wheels")
        spec = layout.lock(layout.SourceTree(BF.REPOSITORY, self.b.commit))["interpreter"]
        asset_dir = inputs / "python-build-standalone" / spec["releaseTag"]
        asset_dir.mkdir(parents=True)
        (asset_dir / spec["asset"]).symlink_to(self.b.inputs / "python-build-standalone" / spec["releaseTag"] / spec["asset"])
        wheel = sorted((inputs / "wheels").glob("rpds_py-*.whl"))[0]
        wheel.unlink()
        with self.assertRaises(BuildRefusal) as caught:
            self.b.rebuild(self.directory / "no-wheel", inputs_dir=inputs)
        self.assertEqual(caught.exception.field, "inputs-dir")
        self.assertIn("rpds-py", str(caught.exception))
        self.assertFalse((self.directory / "no-wheel").exists())
        shutil.copy(self.b.inputs / "wheels" / wheel.name, wheel)
        (asset_dir / spec["asset"]).unlink()
        tampered = bytearray((self.b.inputs / "python-build-standalone" / spec["releaseTag"] / spec["asset"]).read_bytes())
        tampered[-1] ^= 1
        (asset_dir / spec["asset"]).write_bytes(bytes(tampered))
        with self.assertRaises(BuildRefusal) as caught:
            self.b.rebuild(self.directory / "tampered", inputs_dir=inputs)
        self.assertIn("digest differs from inputs.lock.json", str(caught.exception))
        (asset_dir / spec["asset"]).unlink()
        with self.assertRaises(BuildRefusal) as caught:
            self.b.rebuild(self.directory / "no-asset", inputs_dir=inputs)
        self.assertIn("interpreter asset missing", str(caught.exception))
        self.assertNotIn(b"urllib", (APP / "bundle" / "layout.py").read_bytes() + (APP / "bundle" / "build.py").read_bytes())

    def test_ac03_same_version_with_different_bytes_is_refused(self):
        """AC-03: the identity registry refuses a second archive for the same runtimeId and version; the same archive is idempotent."""
        registry = self.directory / "registry.jsonl"
        entry = dict(runtimeId=BF.RUNTIME_ID, version=self.b.record["version"], sourceCommit=self.b.commit,
                     archiveDigest="0" * 64, manifestDigest="1" * 64)
        registry.write_text(json.dumps(entry) + "\n")
        with self.assertRaises(BuildRefusal) as caught:
            self.b.rebuild(self.directory / "conflict", identity_registry=registry)
        self.assertEqual(caught.exception.field, "identity-registry")
        self.assertFalse((self.directory / "conflict" / "bundle").exists())
        again = self.directory / "again.jsonl"
        first = self.b.rebuild(self.directory / "first", identity_registry=again)
        repeat = self.b.rebuild(self.directory / "repeat", identity_registry=again)
        self.assertEqual((first["identityRegistry"]["newEntry"], repeat["identityRegistry"]["newEntry"]), (True, False))
        self.assertEqual(len(again.read_text().splitlines()), 1)

    def test_ac03_every_location_is_an_explicit_argument(self):
        """AC-03: the build command has no default location; each missing argument is refused by its name."""
        full = ["--repository", "r", "--source-commit", "c", "--inputs-dir", "i", "--runtime-id", "runtime:x", "--publisher-id",
                "publisher:x", "--source-reference", "s", "--signing-key", "k", "--publisher-key", "p", "--openssl", "o",
                "--identity-registry", "f", "--output", "d"]
        for index in range(0, len(full), 2):
            argv = full[:index] + full[index + 2:]
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                build.main(argv)
            self.assertIn(full[index], stderr.getvalue())

    def test_ac09_descriptors_name_no_program_version(self):
        """AC-09: manifest, launch.json, capability and profile requirements carry no Agent or platform program version or digest."""
        self.assertEqual(self.b.manifest["executionProfileRequirements"], [])
        self.assertEqual(self.b.manifest["dependencies"], [])
        text = (self.b.by_path["manifest.json"][0] + self.b.by_path["launch.json"][0]).decode().lower()
        for needle in ("claude", "codex", "programidentity", "binarydigest", "gh ", "version\": \"2."):
            self.assertNotIn(needle, text)

    def test_ac10_no_private_key_material_in_the_outputs(self):
        """AC-10: no member, import file or build record carries private key markers or encodings."""
        blobs = [d for _, d, _ in self.b.members] + [p.read_bytes() for p in self.b.import_dir.iterdir()]
        blobs.append((self.b.root / "out" / "build-record.json").read_bytes())
        hits = [pattern.pattern for blob in blobs for pattern in PRIVATE_PATTERNS if pattern.search(blob)]
        self.assertEqual(hits, [])
        probe = ed25519_synthetic.PKCS8_PREFIX + b"\x00" * 32
        pem = b"-----BEGIN PRIVATE KEY-----\n" + __import__("base64").b64encode(probe) + b"\n-----END PRIVATE KEY-----\n"
        self.assertTrue(all(any(p.search(sample) for p in PRIVATE_PATTERNS) for sample in (probe, pem, probe.hex().encode())))
        self.assertEqual(self.b.record["signer"]["label"], ed25519_synthetic.SyntheticKey.label)


# -- AC-04 ---------------------------------------------------------------------------------------------------------
class AdmissionCase(Case):
    def test_ac04_the_bundle_is_admitted_and_installed(self):
        """AC-04: the synthetic Host admits the bundle in the receiver's order, installs it and re-verifies it before launch."""
        verdict = BH.admit(self.b.import_dir, pins={BF.RUNTIME_ID: release.public_key_digest(self.b.key.public_pem)})
        self.assertTrue(verdict.identity_verified, verdict.reasons)
        self.assertIsNone(verdict.incompatibility)
        package = BH.install(verdict, self.directory / "rt")
        self.assertEqual(BH.verify_installed(package), [])
        self.assertEqual(verdict.artifact_digest, self.b.record["archive"]["sha256"])

    def test_ac04_each_refusal_is_classified_and_starts_nothing(self):
        """AC-04: signature, publisher, pin, archive, member list, links, traversal, duplicates, limits, field agreement, launch, placeholders, capability schemas, platform and OS refusals."""
        other = ed25519_synthetic.SyntheticKey()
        good = self.b.members

        def drop(path):
            return lambda items: [i for i in items if i[0] != path]

        def append(item):
            return lambda items: items + [item]
        cases = [
            ("signature", dict(signature=lambda t: (("0" if t[:1] != b"0" else "1") + t.decode()[1:]).encode()), "INVALID_SOURCE", "signature"),
            ("record-publisher-digest", dict(sign_with=other, record=lambda r: r["publisher"].update(publicKeyDigest=release.public_key_digest(self.b.key.public_pem))),
             "INVALID_SOURCE", "publisher key digest"),
            ("archive-digest", dict(raw_archive=lambda t: t + b"\0" * 512), "INTEGRITY_MISMATCH", "archive digest"),
            ("extra-member", dict(record=lambda r: r.update(files=[f for f in r["files"] if f["path"] != "app/apps/harness/hp.py"])),
             "INTEGRITY_MISMATCH", "not in the signed file list"),
            ("missing-member", dict(members=drop("app/apps/harness/hp.py"),
                                    record=lambda r: r["files"].append(dict(path="app/apps/harness/hp.py", bytes=1, sha256="0" * 64, mode="0644"))),
             "INTEGRITY_MISMATCH", "missing from the archive"),
            ("symlink", dict(members=append(["python/bin/python3", b"", "0755", "2", "python3.12"])), "INTEGRITY_MISMATCH", "not a regular file"),
            ("hardlink", dict(members=append(["python/bin/python", b"", "0755", "1", "python/bin/python3.12"])), "INTEGRITY_MISMATCH", "not a regular file"),
            ("traversal", dict(members=append(["../outside.txt", b"x", "0644"]),
                               record=lambda r: r.update(files=[f for f in r["files"] if f["path"] != "../outside.txt"])),
             "INTEGRITY_MISMATCH", "escapes the bundle root"),
            ("duplicate", dict(members=append(["app/apps/harness/hp.py", b"# second copy\n", "0644"])), "INTEGRITY_MISMATCH", "duplicate"),
            ("expanded-limit", dict(record=lambda r: r["limits"].update(expandedBytesMax=1024)), "RESOURCE_LIMIT", "expandedBytesMax"),
            ("member-limit", dict(record=lambda r: r["limits"].update(membersMax=10)), "RESOURCE_LIMIT", "membersMax"),
            ("field-agreement", dict(manifest=lambda m: m.update(version="0.1.0-dev.other")), "INTEGRITY_MISMATCH", "version differs"),
            ("launch-digest", dict(launch=lambda l: l.update(environmentAllowList=["HOME", "PATH"])), "INTEGRITY_MISMATCH", "launch.json digest"),
            ("placeholder", dict(manifest=lambda m: m.update(argv=m["argv"] + ["${home}"]), launch=lambda l: l.update(argv=l["argv"] + ["${home}"])),
             "INTEGRITY_MISMATCH", "placeholder outside the closed set"),
            ("capability-digest", dict(members=lambda items: [i if i[0] != "capabilities/harness.workflow.json" else
                                                              [i[0], json.dumps(dict(json.loads(i[1]), description="changed")).encode(), i[2]]
                                                              for i in items]),
             "UNSUPPORTED_CAPABILITY", "schemaDigest differs"),
        ]
        ref_schema = json.dumps({"$ref": "https://example.invalid/x.json"}).encode()
        results = []
        for name, mutation, code, reason in cases:
            with self.subTest(case=name):
                directory = self.b.variant(self.directory / name, **mutation)
                verdict = BH.admit(directory)
                results.append(dict(case=name, code=verdict.code, reason=(verdict.reasons or [""])[0]))
                self.assertFalse(verdict.identity_verified and not verdict.incompatibility, name)
                self.assertEqual(verdict.code, code, verdict.reasons)
                self.assertTrue(any(reason in r for r in verdict.reasons), verdict.reasons)
                with self.assertRaises(AssertionError):
                    BH.install(verdict, self.directory / ("rt-" + name))
                self.assertFalse((self.directory / ("rt-" + name)).exists())
        with self.subTest(case="non-local-ref"):
            cap = self.b.manifest["capabilities"][1]
            directory = self.b.variant(self.directory / "non-local-ref",
                                       members=lambda items: [i if i[0] != "capabilities/%s.json" % cap["id"] else [i[0], ref_schema, i[2]] for i in items],
                                       manifest=lambda m: m["capabilities"][1].update(schemaDigest=BF.sha256(BH.canonical(json.loads(ref_schema)).encode())))
            verdict = BH.admit(directory)
            self.assertEqual(verdict.code, "UNSUPPORTED_CAPABILITY", verdict.reasons)
            self.assertTrue(any("non-local $ref" in r for r in verdict.reasons), verdict.reasons)
        with self.subTest(case="pinned-key"):
            verdict = BH.admit(self.b.import_dir, pins={BF.RUNTIME_ID: release.public_key_digest(other.public_pem)})
            self.assertEqual(verdict.code, "INVALID_SOURCE")
            self.assertTrue(any("pinned" in r for r in verdict.reasons))
        with self.subTest(case="platform"):
            verdict = BH.admit(self.b.import_dir, host_platform="darwin-x86_64")
            self.assertTrue(verdict.identity_verified)
            self.assertEqual(verdict.incompatibility["code"], "UNSUPPORTED_VERSION")
            with self.assertRaises(AssertionError):
                BH.install(verdict, self.directory / "rt-platform")
        with self.subTest(case="minimum-os"):
            verdict = BH.admit(self.b.import_dir, os_version="26.0")
            self.assertEqual(verdict.incompatibility["code"], "UNSUPPORTED_VERSION")
            self.assertTrue(any("minimumOs" in r for r in verdict.reasons))
        (self.directory / "refusals.json").write_text(json.dumps(results, indent=1))
        self.assertEqual(len(good), len(self.b.members))


# -- AC-05, AC-06, AC-07 -------------------------------------------------------------------------------------------
class LaunchCase(Case):
    def ready(self, handle="resource:t18"):
        installation = self.installation()
        repo, _ = self.product_line()
        self.bind(installation, repo, handle)
        return installation, repo

    def test_ac05_initialize_under_the_receiver_launch(self):
        """AC-05: started like the receiver starts it, the bundle adopts the Host identities and selects only offered protocol, capabilities and profiles."""
        installation, repo = self.ready()
        h = self.host(installation)
        offered = installation.initialize_params(capabilities=installation.verdict.manifest["capabilities"][:3])
        result = h.call("runtime.initialize", offered)
        BH.BundleHost.check_initialized(offered, result)
        self.assertEqual([c["id"] for c in result["capabilities"]], [c["id"] for c in offered["capabilities"]])
        self.assertEqual(result["executionProfiles"], [])
        h.context = result["context"]
        h.call("runtime.ready")
        self.assertEqual(h.call("runtime.health")["health"], "ready")
        self.assertEqual(h.command[0], str(installation.package / "python/bin/python3.12"))
        self.assertIn(str(installation.instance_dir), h.command)
        self.assertEqual(sorted(installation.environment()), ["HOME", "PATH", "PYTHONDONTWRITEBYTECODE"])

    def test_ac05_contract_digest_argument_mismatch_exits_before_the_protocol(self):
        """AC-05: a contract digest argument other than the frozen digest ends the process before any frame."""
        installation, repo = self.ready()
        argv = [a if a != BH.CONTRACT_DIGEST else "0" * 64 for a in installation.launch_command()]
        process = subprocess.run(argv, cwd=installation.instance_dir, env=installation.environment(), input=b"", capture_output=True, timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, b"")
        self.assertIn(b"contract digest", process.stderr)

    def test_ac05_integrity_and_negotiation_refusals(self):
        """AC-05: a bundleDigest or permissionProfileDigest other than the bundle's own is INTEGRITY_MISMATCH; unsupported protocol and required capability are refused; none reaches ready."""
        installation, repo = self.ready()
        cap = dict(installation.verdict.manifest["capabilities"][1], required=True, schemaDigest="f" * 64)
        cases = [
            ("bundle-digest", dict(bundleDigest="a" * 64), "INTEGRITY_MISMATCH"),
            ("authorization-bundle-digest", dict(launchAuthorization=dict(installation.initialize_params()["launchAuthorization"], bundleDigest="a" * 64)), "INTEGRITY_MISMATCH"),
            ("profile-digest", dict(launchAuthorization=dict(installation.initialize_params()["launchAuthorization"], permissionProfileDigest="c" * 64)), "INTEGRITY_MISMATCH"),
            ("protocol", dict(protocols=[dict(version=BH.CONTRACT_VERSION, contractDigest="e" * 64)]), "UNSUPPORTED_VERSION"),
            ("required-capability", dict(capabilities=[cap]), "UNSUPPORTED_CAPABILITY"),
            ("expired-authorization", dict(launchAuthorization=dict(installation.initialize_params()["launchAuthorization"], expiresAt="2020-01-01T00:00:00Z")), "PERMISSION_DENIED"),
        ]
        for name, overrides, code in cases:
            with self.subTest(case=name):
                h = self.host(installation)
                error = h.call("runtime.initialize", installation.initialize_params(**overrides), error=code)
                self.assertEqual(error["data"]["code"], code)
                h.close()

    def test_ac05_self_check_refuses_a_changed_package(self):
        """AC-05: a package member changed after installation makes the self-check fail: health degraded, Initialize INTEGRITY_MISMATCH."""
        installation, repo = self.ready()
        target = installation.package / "app/apps/harness/domain/port.py"
        os.chmod(target, 0o644)
        target.write_bytes(target.read_bytes() + b"\n# changed after installation\n")
        self.assertEqual(BH.verify_installed(installation.package), ["app/apps/harness/domain/port.py"])
        h = self.host(installation, recheck_package=False)  # a change the Host did not catch: the Runtime's own check must
        error = h.call("runtime.initialize", installation.initialize_params(), error="INTEGRITY_MISMATCH")
        self.assertIn("bundle self-check failed", error["message"])
        self.assertIn("domain/port.py", error["message"])

    def test_ac05_environment_resource_paths_are_ignored(self):
        """AC-05: resource path and interpreter variables in the environment change neither the bound repository nor the behaviour."""
        installation, repo = self.ready()
        other, _ = self.product_line("other")
        h = self.host(installation, extra_env={"PYTHONPATH": str(self.directory / "nowhere"), "PYTHONHOME": str(self.directory / "nowhere"),
                                               "HP_REPOSITORY": str(other), "HARNESS_REPOSITORY": str(other), "GIT_DIR": str(other / ".git")})
        h.start()
        self.assertEqual(h.call("runtime.health")["health"], "ready")
        scope, _ = h.open_scope("resource:t18", [("harness.task-acceptance", "runtime.snapshot.open")])
        page = h.call("runtime.snapshot.open", dict(scopeRef=scope))
        self.assertIn("task.accept", [a["actionId"] for a in page["actions"]])
        self.assertIn("hp ignores repository-locating environment variables: GIT_DIR", "".join(h.stderr))
        self.assertTrue(git(repo, "rev-parse", "--verify", "refs/harness/runtime"))
        self.assertEqual(git(other, "for-each-ref", "refs/harness/"), "")

    def test_ac06_missing_binding_is_degraded_and_writes_nothing(self):
        """AC-06: without a binding file the Runtime starts, health is degraded with the reason, scope.open is refused and no domain state appears."""
        installation = self.installation()
        repo, _ = self.product_line()
        h = self.host(installation)
        h.start()
        health = h.call("runtime.health")
        self.assertEqual(health["health"], "degraded")
        self.assertIn("no instance binding file", health["reason"])
        error = h.call("runtime.scope.open", dict(binding=dict(bindingRef="binding:x", resourceHandle="resource:t18",
                                                                   expiresAt="2099-01-01T00:00:00Z")), error="PERMISSION_DENIED")
        self.assertIn("no instance binding file", error["message"])
        self.assertEqual(git(repo, "for-each-ref", "refs/harness"), "")

    def test_ac06_unusable_repository_and_invalid_binding_are_degraded(self):
        """AC-06: a binding to a non-repository or an invalid binding file is reported, not guessed around."""
        installation = self.installation()
        plain = self.directory / "plain"
        plain.mkdir()
        document = dict(schema="hp-runtime-binding/v1", repository=str(plain), resourceHandles=["resource:t18"], executionBindings={},
                        authorityRef="owner:synthetic", writtenAt="2026-09-24T00:00:00Z")
        (installation.instance_dir / "hp-binding.json").write_text(json.dumps(document))
        h = self.host(installation)
        h.start()
        health = h.call("runtime.health")
        self.assertEqual(health["health"], "degraded")
        self.assertIn("not usable", health["reason"])
        h.close()
        (installation.instance_dir / "hp-binding.json").write_text(json.dumps(dict(document, repository="relative/path")))
        h = self.host(installation)
        h.start()
        self.assertIn("instance binding file is invalid", h.call("runtime.health")["reason"])

    def test_ac06_a_handle_not_in_the_binding_is_refused(self):
        """AC-06: scope.open accepts only a resource handle the binding file lists; the empty argv handle is never used."""
        installation, repo = self.ready()
        h = self.host(installation)
        h.start()
        error = h.call("runtime.scope.open", dict(binding=dict(bindingRef="binding:y", resourceHandle="resource:other",
                                                                   expiresAt="2099-01-01T00:00:00Z")), error="PERMISSION_DENIED")
        self.assertIn("not bound to this instance", error["message"])
        scope, _ = h.open_scope("resource:t18", [("harness.task-acceptance", "runtime.snapshot.open")])
        self.assertTrue(scope.startswith("scope:"))

    def test_ac06_binding_command_validates_and_protects_the_file(self):
        """AC-06: `hp binding write` refuses relative or non-repository paths and an existing file without --replace, and writes mode 0600."""
        installation = self.installation()
        repo, _ = self.product_line()
        env = installation.environment()
        base = ["binding", "write", "--instance-dir", str(installation.instance_dir), "--resource-handle", "resource:t18",
                "--authority-ref", "owner:synthetic", "--repository"]
        code, doc, _ = BF.run_bundle_cli(installation.package, env, *base, "relative", check=False)
        self.assertEqual((code, doc["field"]), (1, "repository"))
        plain = self.directory / "plain"
        plain.mkdir()
        code, doc, _ = BF.run_bundle_cli(installation.package, env, *base, str(plain), check=False)
        self.assertEqual((code, doc["message"]), (1, "not a Git repository"))
        nested = repo / "sub"
        nested.mkdir()
        code, doc, _ = BF.run_bundle_cli(installation.package, env, *base, str(nested), check=False)
        self.assertEqual((code, doc["field"]), (1, "repository"), doc)
        code, doc, _ = BF.run_bundle_cli(installation.package, dict(env, GIT_DIR=str(repo / ".git")), *base, str(plain), check=False)
        self.assertEqual((code, doc["message"]), (1, "not a Git repository"))
        self.bind(installation, repo, "resource:t18")
        self.assertEqual(os.stat(installation.instance_dir / "hp-binding.json").st_mode & 0o777, 0o600)
        code, doc, _ = BF.run_bundle_cli(installation.package, env, *base, str(repo), check=False)
        self.assertEqual((code, doc["field"]), (1, "instance-dir"))
        code, doc, _ = BF.run_bundle_cli(installation.package, env, *base, str(repo), "--replace")
        self.assertEqual(doc["result"], "BINDING_WRITTEN")
        code, doc, _ = BF.run_bundle_cli(installation.package, env, "binding", "show", "--instance-dir", str(installation.instance_dir))
        self.assertEqual(doc["binding"]["repository"], str(repo.resolve()))

    def test_ac06_the_bundle_cli_and_runtime_share_one_writer(self):
        """AC-06: when the bundle CLI takes the control generation the Runtime's older generation is refused (WRITER_CONFLICT) and writes nothing; a new incarnation takes control back."""
        installation, repo = self.ready()
        h = self.host(installation)
        first = h.start()
        scope, _ = h.open_scope("resource:t18", [("harness.task-acceptance", m) for m in ACCEPT_METHODS])
        env = dict(BF.GIT_ENV, PATH="/usr/bin:/bin", HOME=str(self.directory))
        # verify checks-set takes the control generation (feature-t0 configuration keys write without one, under the lock only)
        code, doc, _ = BF.run_bundle_cli(installation.package, env, "verify", "checks-set", "--checks", "[]", "--repository", str(repo),
                                         "--authority-ref", "owner:synthetic")
        self.assertEqual(doc["result"], "CHECKS_CONFIGURED", doc)
        before = git(repo, "rev-parse", "refs/harness/runtime")
        page = h.call("runtime.snapshot.open", dict(scopeRef=scope), error="WRITER_CONFLICT")
        self.assertIn("Stale control generation", page["message"])
        self.assertEqual(git(repo, "rev-parse", "refs/harness/runtime"), before)
        h.close()
        h2 = self.host(installation)
        second = h2.start()
        self.assertGreater(int(second["context"]["controlGeneration"]), int(first["context"]["controlGeneration"]) + 1)
        self.assertEqual(h2.call("runtime.health")["health"], "ready")

    def _accept_params(self, h, scope, key):
        page = h.call("runtime.snapshot.open", dict(scopeRef=scope))
        action = next(a for a in page["actions"] if a["actionId"] == "task.accept")
        params = dict(operationId="op:" + key, idempotencyKey="key:" + key, scopeRef=scope, actionId=action["actionId"],
                      objectRef=action["objectRef"], expectedRevision=action["expectedRevision"], candidateRef=action["candidateRef"],
                      grantRefs=[g["ref"] for g in h.grants], decisionRef=None,
                      payload=dict(taskType="feature", taskId="feature-t0", baseRef="main", worktreeRoot=str(self.directory / "worktrees")))
        return BF.decide(h, params)

    def _restart(self, installation, handle="resource:t18"):
        h = self.host(installation)
        h.start()
        scope, binding = h.open_scope(handle, [("harness.task-acceptance", m) for m in ACCEPT_METHODS])
        return h, scope

    def test_ac07_killed_after_acceptance_the_same_operation_is_recovered(self):
        """AC-07: the process is killed after an accepted action; a new incarnation reopens the same scope, reads the persisted operation, and a same-key retry replays it without a second acceptance."""
        installation, repo = self.ready()
        h, scope = self._restart(installation)
        params = self._accept_params(h, scope, "k1")
        accepted = h.call("runtime.action.invoke", params)
        self.assertEqual(accepted["operationId"], "op:k1")
        os.kill(h.process.pid, signal.SIGKILL)
        h.process.wait(timeout=30)
        h2, scope2 = self._restart(installation)
        self.assertEqual(scope2, scope)
        op = BF.wait_operation(h2, scope2, "op:k1")
        self.assertIn(op["status"], ("succeeded", "failed", "unknown"))
        h2.decisions.update(h.decisions)
        replay = h2.call("runtime.action.invoke", params)
        self.assertEqual((replay["operationId"], replay["requestDigest"]), ("op:k1", params["requestDigest"]))
        state = json.loads(git(repo, "show", "refs/harness/runtime:state.json"))
        self.assertEqual(list(state["tasks"]), ["feature-t0"])
        conflict = dict(params, payload=dict(params["payload"], baseRef="other"))
        conflict["requestDigest"] = request_digest("runtime.action.invoke", conflict)
        h2.call("runtime.action.invoke", conflict, error="IDEMPOTENCY_CONFLICT")

    def test_ac07_killed_before_the_reply_nothing_is_duplicated(self):
        """AC-07: the process is killed right after the request is written; the new incarnation proves absence or returns the persisted record, and the same key yields exactly one task."""
        installation, repo = self.ready()
        h, scope = self._restart(installation)
        params = self._accept_params(h, scope, "k2")
        h.send(dict(jsonrpc="2.0", id="h:raw", method="runtime.action.invoke", params=dict(context=h.context, **params)))
        os.kill(h.process.pid, signal.SIGKILL)
        h.process.wait(timeout=30)
        h2, scope2 = self._restart(installation)
        h2.decisions.update(h.decisions)
        frame = h2.frame("runtime.operation.get", dict(scopeRef=scope2, operationId="op:k2"))
        if "error" in frame:
            self.assertEqual((frame["error"]["data"]["code"], frame["error"]["data"]["absenceProven"]), ("NOT_FOUND", True))
        else:
            self.assertIn(frame["result"]["status"], ("accepted", "succeeded", "failed", "unknown"))
        (self.directory / "kill-before-reply.json").write_text(json.dumps(frame, indent=1))
        h2.call("runtime.action.invoke", params)
        BF.wait_operation(h2, scope2, "op:k2")
        state = json.loads(git(repo, "show", "refs/harness/runtime:state.json"))
        self.assertEqual(list(state["tasks"]), ["feature-t0"])

    def test_ac07_quiesce_keeps_queries_and_shutdown_persists_before_exit(self):
        """AC-07: after quiesce new actions are refused (BUSY, retry-later) while queries answer; shutdown is persisted and the process exits."""
        installation, repo = self.ready()
        h, scope = self._restart(installation)
        params = self._accept_params(h, scope, "k3")
        quiesce = dict(operationId="op:q", idempotencyKey="key:q", reason="SYNTHETIC maintenance")
        quiesce["requestDigest"] = request_digest("runtime.quiesce", quiesce)
        self.assertEqual(h.call("runtime.quiesce", quiesce)["status"], "succeeded")
        error = h.call("runtime.action.invoke", params, error="BUSY")
        self.assertEqual(error["data"]["recovery"], "retry-later")
        self.assertIn("task.accept", [a["actionId"] for a in h.call("runtime.snapshot.open", dict(scopeRef=scope))["actions"]])
        shutdown = dict(operationId="op:s", idempotencyKey="key:s", reason="SYNTHETIC stop")
        shutdown["requestDigest"] = request_digest("runtime.shutdown", shutdown)
        self.assertEqual(h.call("runtime.shutdown", shutdown)["status"], "succeeded")
        self.assertEqual(h.process.wait(timeout=30), 0)
        state = json.loads(git(repo, "show", "refs/harness/runtime:state.json"))
        self.assertTrue(state["shutdown"] and state["quiesced"])
        self.assertEqual(state["tasks"], {})


# -- AC-08, AC-09 --------------------------------------------------------------------------------------------------
class MinimalPathCase(Case):
    def test_ac08_minimal_path_through_the_installed_bundle(self):
        """AC-08 AC-09: acceptance through the bundle's serve-stdio, Definition to Published through its CLI, with new Agent and platform program versions mid-path; edges match feature-t7 AC-08."""
        from domain.acceptance.gitrepo import Repository
        from domain.acceptance.terminal import in_flight
        installation = self.installation()
        path = BF.BundlePath(self.directory / "path", installation)
        path.write_binding()
        h = self.host(installation)
        scope, page, accepted, operation = path.accept_through_runtime(h)
        self.assertEqual(operation["status"], "succeeded")
        before = in_flight(path.state(), Repository(path.repo), path.head)["count"]
        path.definition_and_freeze()
        ran, verified, configured = path.configure_and_implement(agent_version="synthetic-agent 2.0")
        self.assertEqual((ran["result"], verified["result"], configured["result"]), ("IMPLEMENT_COMPLETED", "VERIFY_PASS", "VALIDATION_CONFIGURED"))
        published, status = path.publish(platform_version="synthetic-platform 2.0")
        self.assertEqual((published["lifecycle"], published["terminal"]["kind"], status["legal"]), ("COMPLETED", "published", []))
        state = path.state()
        task = state["tasks"][path.task_id]
        inst = task["workflowInstance"]
        edges = [c["selectedEdge"] for c in inst["commits"] if c.get("selectedEdge")]
        self.assertEqual(edges, T7_J03_EDGES)
        self.assertEqual(path.remote_ref(task["branch"]), git(path.repo, "rev-parse", "refs/heads/" + task["branch"]))
        pulls = path.platform.pulls()
        self.assertEqual(len(pulls), 1)
        self.assertEqual(pulls[0]["head"]["sha"], path.remote_ref(task["branch"]))
        after = in_flight(state, Repository(path.repo), path.head)["count"]
        self.assertEqual((before, after), (1, 0))
        implement = next(iter(task["implementVerify"]["executions"].values()))
        self.assertEqual(implement["programIdentity"]["version"], "synthetic-agent 2.0")
        self.assertEqual(task["publish"]["executions"][0]["outcome"]["evidence"]["program"]["version"], "synthetic-platform 2.0")
        h.close()
        h2 = self.host(installation)
        h2.start()
        scope2, _ = h2.open_scope(path.handle, [("harness.workflow", "runtime.snapshot.open"), ("harness.task-acceptance", "runtime.snapshot.open")])
        final = h2.call("runtime.snapshot.open", dict(scopeRef=scope2))
        self.assertEqual(scope2, scope)
        rows = json.dumps(final["objects"])
        self.assertIn("COMPLETED", rows)
        (self.directory / "path-steps.json").write_text(json.dumps(dict(steps=path.steps, edges=edges, referenceEdges=T7_J03_EDGES,
                                                                        inFlight=dict(before=before, after=after),
                                                                        remote=path.remote_ref(task["branch"]),
                                                                        pulls=[dict(number=p["number"], state=p["state"], head=p["head"]["sha"]) for p in pulls],
                                                                        versions=dict(agent="synthetic-agent 2.0", platform="synthetic-platform 2.0"),
                                                                        package=str(installation.package.name)), indent=1))


if __name__ == "__main__":
    unittest.main()
