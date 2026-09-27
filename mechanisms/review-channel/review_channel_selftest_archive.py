"""Archive integration acceptance, isolated repositories and fake provider only.

Standalone: python3 -B review_channel_selftest_archive.py --scratch-root <durable-dir>
The explicit scratch root retains full originals outside product Git. Legacy
selftest discovery does not create archives in its temporary-directory fixtures.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

import review_evidence as E
import review_channel_selftest as ST
import review_channel_selftest_channel as SC
import review_channel_verdict as V

SCRATCH = None


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.e = ST.Engine(ST.UNIT_DIR)
        os.rmdir(self.e.tmp_root)
        self.e.tmp_root = str(SCRATCH / uuid.uuid4().hex)
        Path(self.e.tmp_root).mkdir()
        self.env = SC.Env(self.e, {"behavior": "valid", "verdict": "FAIL"})
        self.repo = self.env.repo
        self.primary = Path(self.e.tmp_root) / "primary"
        self.primary.mkdir()
        self.backup = Path(self.e.tmp_root) / "backup"
        self.backup.mkdir()
        self.arc = E.initialize(
            self.repo.root, "test-product", self.primary, self.backup
        )
        cutoff = self.repo.git("rev-parse", "HEAD").stdout.strip()
        inv = {
            "schema": "review-archive-inventory/v1",
            "files": [],
            "missing": [],
            "unclassified": [],
        }
        ref = self.arc.publish(
            "inventory",
            None,
            None,
            {"inventory.json": (E.canonical(inv), "other-original")},
        )
        switch = {
            "schema": "review-archive-switch/v1",
            "repository_id": "test-product",
            "mode": "archive-v1",
            "implementation_commit": cutoff,
            "legacy_commit": cutoff,
            "inventory_ref": ref,
            "authorized_by": "isolated fixture authorization",
        }
        path = "records/governance/review-channel/HarnessPlane_Review_Channel_Owner_Decisions_v1.md"
        self.repo.write(
            path,
            "# Test only\n\n```review-archive-switch\n"
            + json.dumps(switch)
            + "\n```\n",
        )
        self.repo.git("add", "--", path)
        p = self.repo.git("commit", "-m", "isolated switch")
        self.assertEqual(p.returncode, 0, p.stderr)
        for k, v in {
            "repositoryId": "test-product",
            "primaryRoot": str(self.primary),
            "backupRoot": str(self.backup),
            "mode": "archive-v1",
        }.items():
            self.assertEqual(
                self.repo.git("config", "--local", "reviewArchive." + k, v).returncode,
                0,
            )

    def request(self, rnd, task=True, **kw):
        return self.repo.request(
            rnd, task=task, request_schema="review-channel-request/v5", **kw
        )

    def run_channel(self, sub, req):
        code, out, err, obj = self.env.run(sub, req)
        self.assertEqual(code, 0, (out, err))
        self.assertIsInstance(obj, dict, (out, err))
        return obj

    def test_subject_and_task_fail_respond_pass(self):
        for task in (False, True):
            with self.subTest(task=task):
                self.env.control(behavior="valid", verdict="FAIL")
                first = self.run_channel("review", self.request("r1", task))
                self.assertEqual(first["verdict"], "FAIL")
                ref = first["source"]
                d, files = self.arc.read(ref)
                _, vb = E.role_file(d, files, "verdict")
                v, _, _ = V.parse_published(vb)
                self.assertEqual(d["kind"], "round")
                original = files["inputs/HarnessPlane_Demo_Design_v1.md"]
                decisions = [
                    {
                        "finding_id": f["id"],
                        "action": "fix",
                        "instructions": "correct fixture",
                        "owner_verbatim": "fix this fixture",
                    }
                    for f in v["findings"]
                ]
                obj = {
                    "schema": "review-channel-decisions-input/v2",
                    "subject": "demo",
                    "stage": "impl",
                    "round": "r1",
                    "decisions": decisions,
                    "source": ref,
                    "supersedes": None,
                }
                if task:
                    obj["task_record"] = "gov-t1"
                p = Path(self.e.tmp_root) / ("response-" + str(task) + ".json")
                p.write_bytes(E.canonical(obj))
                response = self.run_channel("respond", str(p))
                repeated = self.run_channel("respond", str(p))
                self.assertEqual(response["source"], repeated["source"])
                self.repo.write(
                    "mechanisms/demo/HarnessPlane_Demo_Design_v1.md",
                    original.decode() + "\nA verified change.\n",
                )
                self.env.control(behavior="valid", verdict="PASS")
                nr = response["next_round"]
                second = self.run_channel(
                    "review",
                    self.request(
                        "r2",
                        task,
                        previous={"evidence": ref, "response": response["source"]},
                        remediation=nr["remediation_statement"] + "\nFixed.",
                        residuals=nr["accepted_residuals"],
                    ),
                )
                self.assertEqual(second["verdict"], "PASS")
                d2, files2 = self.arc.read(second["source"])
                self.assertIn(original, files2.values())
                self.assertFalse(
                    Path(self.repo.path(self.repo.tracked_dir("r2", task))).exists()
                )
                restore = Path(self.e.tmp_root) / ("restore-" + str(task))
                restore.mkdir()
                restored = self.arc.restore(second["source"], restore)
                self.assertEqual(restored["files"], len(files2))
                rounds = E.scan_rounds(
                    self.repo.root,
                    "tasks/gov-t1/reviews" if task else "reviews/demo",
                    "task" if task else "subject",
                    "impl",
                )
                self.assertEqual(sum(r["receipt"] for r in rounds.values()), 2)
                code, out, err, obj = self.env.run(
                    "review",
                    self.request(
                        "r2",
                        task,
                        previous={"evidence": ref, "response": response["source"]},
                    ),
                )
                self.assertEqual(code, 1, (out, err))

    def test_missing_configuration_does_not_restart(self):
        self.repo.git("config", "--unset", "reviewArchive.primaryRoot")
        code, out, err, obj = self.env.run("preflight", self.request("r1"))
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(obj["failure_code"], "archive-unconfigured")

    def test_corruption_and_independent_backup(self):
        ref = self.arc.publish(
            "attempt",
            "reviews/sample/r1",
            "sample",
            {"original.txt": (b"original", "other-original")},
        )
        target = self.backup / "objects" / ref["object_sha256"] / "payload/original.txt"
        target.write_bytes(b"corrupted")
        with self.assertRaises(E.EvidenceError):
            self.arc.read(ref)
        target.write_bytes(b"original")
        target.unlink()
        os.link(
            self.primary / "objects" / ref["object_sha256"] / "payload/original.txt",
            target,
        )
        with self.assertRaises(E.EvidenceError):
            self.arc.read(ref)

    def test_symlink_and_alias_roots(self):
        with self.assertRaises(E.EvidenceError):
            E.Archive(self.repo.root, "test-product", self.primary, self.primary)
        link = Path(self.e.tmp_root) / "alias"
        link.symlink_to(self.primary, target_is_directory=True)
        with self.assertRaises(E.EvidenceError):
            E.Archive(self.repo.root, "test-product", link, self.backup)

    def fault_run(self, fault, request):
        driver = Path(self.e.tmp_root) / ("fault-" + uuid.uuid4().hex + ".py")
        driver.write_text(
            "import sys,os\nsys.path.insert(0,"
            + repr(ST.UNIT_DIR)
            + ")\nimport review_evidence as E\nimport review_channel as RC\n"
            + fault
            + "\nsys.exit(RC.main(sys.argv[1:]))\n"
        )
        cache = Path(self.e.tmp_root) / "cache"
        cache.mkdir(exist_ok=True)
        args = [
            sys.executable,
            "-B",
            "-E",
            "-s",
            "-S",
            "-X",
            "pycache_prefix=" + str(cache),
            str(driver),
            "review",
            "--request",
            request,
            "--repo-root",
            self.repo.root,
        ]
        env = {"PATH": os.environ["PATH"], "HOME": self.e.tmp_root, "LC_ALL": "C"}
        p = subprocess.run(args, env=env, capture_output=True, text=True)
        (driver.with_suffix(".stdout")).write_text(p.stdout)
        (driver.with_suffix(".stderr")).write_text(p.stderr)
        return p

    def test_backup_failure_recover_without_provider(self):
        p = self.fault_run(
            "original=E.Archive._install\ndef fail(self,root,*args):\n    if root==self.backup:raise E.EvidenceError('archive-unavailable','injected backup failure')\n    return original(self,root,*args)\nE.Archive._install=fail",
            self.request("r1"),
        )
        self.assertEqual(p.returncode, 1, (p.stdout, p.stderr))
        report = json.loads(p.stdout)
        self.assertEqual(report["classification"], "reviewer_output_invalid")
        pending = Path(report["pending"])
        self.assertTrue((pending / "receipt.json").exists())
        raw_before = {
            str(p): p.read_bytes()
            for p in pending.rglob("*")
            if p.is_file()
            and p.name in ("request.json", "reviewer_last_message.md", "attempt.json")
        }
        with self.assertRaises(E.EvidenceError):
            E.check_pending(self.arc, "tasks/gov-t1/reviews/impl-r1")
        result = E.recover(self.arc, report["attempt_id"])
        self.assertFalse(result["provider_repeated"])
        self.assertEqual(result, E.recover(self.arc, report["attempt_id"]))
        self.assertEqual(raw_before, {p: Path(p).read_bytes() for p in raw_before})
        self.assertEqual(
            len([x for x in self.arc.publications() if x[1]["kind"] == "round"]), 1
        )

    def test_phase_interruptions_never_repeat_provider(self):
        for phase in ("routed", "sealed", "calling", "called", "validated"):
            with self.subTest(phase=phase):
                subject = "interrupted-" + phase
                request = self.request("r1", False, subject=subject)
                if phase == "routed":
                    fault = "original=RC.Attempt.allocate\ndef fail(self,*a,**k):\n    original(self,*a,**k)\n    os._exit(90)\nRC.Attempt.allocate=fail"
                else:
                    fault = (
                        "original=RC.Attempt.advance\ndef fail(self,phase,*a,**k):\n    original(self,phase,*a,**k)\n    if phase=="
                        + repr(phase)
                        + ":os._exit(90)\nRC.Attempt.advance=fail"
                    )
                p = self.fault_run(fault, request)
                self.assertEqual(p.returncode, 90, (p.stdout, p.stderr))
                states = [
                    x
                    for x in (self.primary / "pending").glob("*/attempt.json")
                    if json.loads(x.read_bytes())["routing"]["subject"] == subject
                ]
                self.assertEqual(len(states), 1)
                state = states[0]
                before = state.read_bytes()
                if phase in ("routed", "sealed"):
                    result = E.recover(self.arc, state.parent.name)
                    self.assertFalse(result["provider_repeated"])
                else:
                    with self.assertRaises(E.EvidenceError):
                        E.recover(self.arc, state.parent.name)
                self.assertEqual(before, state.read_bytes())

    def test_cross_worktree_lock_is_shared(self):
        other = Path(self.e.tmp_root) / "other-worktree"
        p = self.repo.git("worktree", "add", "--detach", str(other), "HEAD")
        self.assertEqual(p.returncode, 0, p.stderr)
        key = "reviews/locked/r1"
        with E.lock_scope():
            self.arc.lock(key)
            code = (
                "import sys;sys.path.insert(0,"
                + repr(ST.UNIT_DIR)
                + ");import review_evidence as E\nwith E.lock_scope():E.Archive("
                + repr(str(other))
                + ").lock("
                + repr(key)
                + ")"
            )
            child = subprocess.run(
                [sys.executable, "-B", "-c", code], capture_output=True, text=True
            )
            self.assertNotEqual(child.returncode, 0)
            self.assertIn("archive-conflict", child.stderr)
            code = code.replace(repr(key), repr("reviews/independent/r1"))
            child = subprocess.run(
                [sys.executable, "-B", "-c", code], capture_output=True, text=True
            )
            self.assertEqual(child.returncode, 0, child.stderr)

    def test_all_new_commits_detect_added_then_removed_original(self):
        target = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.write("reviews/hidden/r1/raw.md", "full original")
        self.repo.git("add", "-f", "--", "reviews/hidden/r1/raw.md")
        self.repo.git("commit", "-m", "hidden original")
        self.repo.git("rm", "--", "reviews/hidden/r1/raw.md")
        self.repo.git("commit", "-m", "remove original")
        source = self.repo.git("rev-parse", "HEAD").stdout.strip()
        with self.assertRaises(E.EvidenceError) as ctx:
            E.verify_new_commits(self.repo.root, target, source)
        self.assertIn("forbidden evidence path", str(ctx.exception))

    def test_registry_archive_fixed_result(self):
        import review_channel_registry as G
        import review_channel_receipt as RC
        from review_channel_runtime import load_adapter

        first = self.run_channel("review", self.request("r1"))
        formal = "records/governance/review-channel/capability.md"
        self.repo.write(
            formal,
            "# Fixture formal decision\n\n```review-result\n"
            + json.dumps(first["review_result"])
            + "\n```\n",
        )
        self.repo.git("add", "--", formal)
        self.repo.git("commit", "-m", "fixture formal result")
        commit = self.repo.git("rev-parse", "HEAD").stdout.strip()
        d, files = self.arc.read(first["source"])
        rp, rb = E.role_file(d, files, "receipt")
        receipt = json.loads(rb)
        ep = receipt["effective_profile"]
        registry = json.loads(Path(self.env.registry).read_bytes())
        registry["registry_schema"] = "review-channel-registry/v4"
        cap = registry["providers"][ep["route_provider"]]["models"][
            ep["requested_model"]
        ]["capability"]
        cap.update(
            status="REVIEW_ENABLED",
            bound_transport=ep["transport"],
            bound_effort=ep["effective_effort"],
            evidence={
                "kind": "archive",
                "ref": first["source"],
                "receipt_path": rp,
                "receipt_sha256": E.sha(rb),
                "decision": {
                    "commit": commit,
                    "path": formal,
                    "locator": "review-result",
                },
            },
        )
        Path(self.env.registry).write_text(json.dumps(registry))
        loader = lambda rid: load_adapter(rid, self.env.adapters)
        G.load_registry(
            self.env.registry,
            loader,
            self.repo.root,
            profile_checker=RC.profile_shape_problems,
        )
        cap["evidence"]["receipt_sha256"] = "0" * 64
        Path(self.env.registry).write_text(json.dumps(registry))
        with self.assertRaises(Exception):
            G.load_registry(
                self.env.registry,
                loader,
                self.repo.root,
                profile_checker=RC.profile_shape_problems,
            )

    def test_publication_crash_boundaries(self):
        for fault_point in (
            "primary-rename",
            "primary-rename-before",
            "backup-rename",
            "backup-publication-before",
            "primary-publication-before",
            "backup-publication",
            "primary-publication",
            "before-return",
        ):
            with self.subTest(fault_point=fault_point):
                subject = "crash-" + fault_point
                request = self.request("r1", False, subject=subject)
                if fault_point == "before-return":
                    fault = "original=E.Archive.publish\ndef fail(self,*a,**k):\n    original(self,*a,**k)\n    os._exit(91)\nE.Archive.publish=fail"
                else:
                    root = (
                        self.primary
                        if fault_point.startswith("primary")
                        else self.backup
                    )
                    segment = (
                        "/objects/" if "rename" in fault_point else "/publications/"
                    )
                    fault = (
                        "original=E.os.rename\ndef fail(src,dst,*a,**k):\n    original(src,dst,*a,**k)\n    if str(dst).startswith("
                        + repr(str(root) + segment)
                        + "):os._exit(91)\nE.os.rename=fail"
                    )
                if fault_point.endswith("-before"):
                    fault = fault.replace("    original(src,dst,*a,**k)\n", "").replace(
                        "os._exit(91)\nE.os.rename=fail",
                        "os._exit(91)\n    original(src,dst,*a,**k)\nE.os.rename=fail",
                    )
                p = self.fault_run(fault, request)
                self.assertEqual(p.returncode, 91, (p.stdout, p.stderr))
                states = [
                    x
                    for x in (self.primary / "pending").glob("*/attempt.json")
                    if json.loads(x.read_bytes())["routing"]["subject"] == subject
                ]
                self.assertEqual(len(states), 1)
                result = E.recover(self.arc, states[0].parent.name)
                self.assertFalse(result["provider_repeated"])
                result2 = E.recover(self.arc, states[0].parent.name)
                self.assertEqual(result, result2)
                self.arc.read(result["source"])

    def test_restore_without_primary_root(self):
        ref = self.arc.publish(
            "attempt",
            "reviews/restore/r1",
            "restore",
            {"original.txt": (b"keep me", "other-original")},
        )
        moved = self.primary.with_name("offline-primary")
        self.primary.rename(moved)
        restore = Path(self.e.tmp_root) / "restored"
        restore.mkdir()
        backup_reader = E.Archive(self.repo.root, restore=True)
        result = backup_reader.restore(ref, restore)
        self.assertEqual(result["files"], 1)
        self.assertEqual((restore / "payload/original.txt").read_bytes(), b"keep me")
        self.assertFalse(self.primary.exists())

    def test_nested_legacy_import_and_missing_snapshot_are_preserved(self):
        path = "tasks/gov-t20/reviews/changelog-cl-14/r1"
        originals = {
            path + "/receipt-r1.json": E.canonical(
                {
                    "receipt_schema": "review-channel-receipt/v1",
                    "classification": "completed_with_valid_verdict",
                    "verdict_published": True,
                }
            ),
            path + "/extra-original.txt": b"original appendix",
        }
        for name, raw in originals.items():
            self.repo.write(name, raw.decode())
        self.repo.git("add", "-f", "--", path)
        self.repo.git("commit", "-m", "legacy fixture")
        cutoff = self.repo.git("rev-parse", "HEAD").stdout.strip()
        group = {
            "round_key": "reviews/changelog-cl-14/r1",
            "legacy_source": {"commit": cutoff, "round_path": path},
            "files": [],
            "limitations": ["original candidate snapshot unlocated"],
        }
        for name, raw in originals.items():
            item = E.fixed_file(self.repo.root, cutoff, name)
            group["files"].append(
                {
                    "source_root": self.repo.root,
                    "path": name,
                    "payload_path": name,
                    "bytes": len(raw),
                    "sha256": E.sha(raw),
                    "role": "receipt" if name.endswith(".json") else "other-original",
                    "source_commit": cutoff,
                    "blob_oid": item["blob_oid"],
                }
            )
        plan = {
            "schema": "review-archive-migration/v1",
            "legacy_commit": cutoff,
            "groups": [group],
            "missing": ["candidate snapshot unlocated"],
            "unclassified": ["unrelated task file remains"],
        }
        restore = Path(self.e.tmp_root) / "migration-restore"
        restore.mkdir()
        result = E.import_migration_plan(self.repo.root, self.arc, plan, restore)
        self.assertEqual(result["files"], 2)
        self.assertFalse(result["sources_deleted"])
        inv, files = self.arc.read(result["inventory_ref"])
        original_ref = inv["parents"][0]
        d, payload = self.arc.read(original_ref)
        self.assertEqual(payload, originals)
        self.assertEqual(d["limitations"], group["limitations"])
        self.assertTrue(Path(self.repo.path(path + "/extra-original.txt")).exists())

    def test_existing_product_bytes_are_not_new_evidence(self):
        # A legacy capture can label a product snapshot as runtime output.
        # Appending a formal record does not reintroduce those baseline bytes.
        original = E.canonical(
            {
                "revision": 1,
                "event": "freeze",
                "instruction": "Existing formal product decision. " * 8,
            }
        )
        path = "records/governance/demo/freeze-records.jsonl"
        self.repo.write(path, original.decode())
        self.repo.git("add", "--", path)
        self.repo.git("commit", "-m", "existing formal record")
        base = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.arc.publish(
            "attempt",
            "reviews/demo/r1",
            "legacy-product-snapshot",
            {"inputs/freeze-records.jsonl": (original, "raw-output")},
        )
        self.repo.write(
            path,
            original.decode()
            + E.canonical({"revision": 2, "event": "re-freeze"}).decode(),
        )
        self.repo.git("add", "--", path)
        self.repo.git("commit", "-m", "append formal product decision")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        E.verify_new_commits(self.repo.root, base, head)
        self.repo.write("renamed-capture.md", original.decode())
        self.repo.git("add", "--", "renamed-capture.md")
        self.repo.git("commit", "-m", "new copy of captured original")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        with self.assertRaises(E.EvidenceError):
            E.verify_new_commits(self.repo.root, base, head)

    def test_request_template_is_product_documentation(self):
        template = {
            "request_schema": "review-channel-request/v5",
            "subject": "<subject>",
            "stage": "impl",
            "round": "r<N>",
            "inputs": {"candidates": ["<path>"]},
            "review_brief": {"background": "<background>"},
        }
        self.assertFalse(E.full_evidence_document(E.canonical(template)))
        actual = dict(template, subject="demo", round="r1")
        self.assertTrue(E.full_evidence_document(E.canonical(actual)))
        mixed = E.canonical(template) + b"\n" + E.canonical(actual)
        self.assertTrue(E.full_evidence_document(mixed))
        self.repo.write("guide.md", "Example:\n" + E.canonical(template).decode())
        base = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.git("add", "--", "guide.md")
        self.repo.git("commit", "-m", "product request template")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(
            E.verify_new_commits(self.repo.root, base, head)["commits_checked"], 1
        )
        self.repo.write("renamed-request.md", E.canonical(actual).decode())
        self.repo.git("add", "--", "renamed-request.md")
        self.repo.git("commit", "-m", "forbidden actual request")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        with self.assertRaises(E.EvidenceError):
            E.verify_new_commits(self.repo.root, base, head)

    def test_local_transition_round_survives_migration(self):
        path = "reviews/local-transition/r1/receipt-r1.json"
        raw = E.canonical(
            {
                "receipt_schema": "review-channel-receipt/v2",
                "classification": "completed_with_valid_verdict",
                "verdict_published": True,
            }
        )
        self.repo.write(path, raw.decode())
        group = {
            "round_key": "reviews/local-transition/r1",
            "legacy_source": None,
            "limitations": ["original local round, not a Git source"],
            "files": [
                {
                    "source_root": self.repo.root,
                    "path": path,
                    "payload_path": path,
                    "bytes": len(raw),
                    "sha256": E.sha(raw),
                    "role": "receipt",
                    "source_commit": None,
                    "blob_oid": None,
                }
            ],
        }
        plan = {
            "schema": "review-archive-migration/v1",
            "legacy_commit": self.repo.git("rev-parse", "HEAD").stdout.strip(),
            "groups": [group],
            "missing": [],
            "unclassified": [],
        }
        restore = Path(self.e.tmp_root) / "transition-restore"
        restore.mkdir()
        result = E.import_migration_plan(self.repo.root, self.arc, plan, restore)
        inv, _ = self.arc.read(result["inventory_ref"])
        self.assertEqual(len(inv["parents"]), 1)
        d, files = self.arc.read(inv["parents"][0])
        self.assertEqual(d["kind"], "legacy-import")
        self.assertIsNone(d["legacy_source"])
        self.assertEqual(files[path], raw)
        rounds = E.scan_rounds(
            self.repo.root, "reviews/local-transition", "subject", "impl"
        )
        self.assertTrue(rounds[1]["receipt"])
        Path(self.repo.path(path)).unlink()
        self.assertEqual(
            rounds,
            E.scan_rounds(
                self.repo.root, "reviews/local-transition", "subject", "impl"
            ),
        )

    def test_forged_and_missing_sealed_originals_refused(self):
        first = self.run_channel("review", self.request("r1"))
        d, files = self.arc.read(first["source"])
        candidate = next(x for x in d["files"] if x["role"] == "candidate")
        missing = (
            self.primary
            / "objects"
            / first["source"]["object_sha256"]
            / "payload"
            / candidate["path"]
        )
        missing.unlink()
        with self.assertRaises(E.EvidenceError):
            self.arc.read(first["source"])
        broken = dict(first["source"], object_sha256="0" * 64)
        with self.assertRaises(E.EvidenceError):
            self.arc.read(broken)

    def test_renamed_and_embedded_raw_evidence_refused(self):
        first = self.run_channel("review", self.request("r1"))
        d, files = self.arc.read(first["source"])
        _, verdict = E.role_file(d, files, "verdict")
        target = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.write(
            "product-note.md", "Preamble\n" + verdict.decode() + "\nAfterword"
        )
        self.repo.git("add", "--", "product-note.md")
        self.repo.git("commit", "-m", "embedded original")
        with self.assertRaises(E.EvidenceError):
            E.verify_new_commits(
                self.repo.root,
                target,
                self.repo.git("rev-parse", "HEAD").stdout.strip(),
            )

    def test_new_review_to_handoff_publish_preflight(self):
        first = self.run_channel("review", self.request("r1"))
        formal = "records/governance/review-channel/result.md"
        self.repo.write(
            formal,
            "# Fixture result\n\n```review-result\n"
            + json.dumps(first["review_result"])
            + "\n```\n",
        )
        self.repo.git("add", "--", formal)
        self.repo.git("commit", "-m", "formal result")
        sys.path.insert(0, str(Path(ST.UNIT_DIR).parent / "handoff-protocol"))
        import handoff_status as HS
        import handoff_workflow as HW

        repo = HS.Repository(self.repo.root)
        q = {
            "task": "repo-od-01",
            "mode": "mr",
            "authority_refs": [formal + "#review-result"],
            "conditions": [],
            "handoff": {"evidence": [], "version": 1, "next": {"kind": "wait-owner"}},
        }
        # Same production check_refs function invoked by prepare(mr); no remote adapter.
        from unittest.mock import patch

        with patch.object(HW.reader, "suggestion_refs", return_value=None):
            HW.check_refs(repo, q, "HEAD")
        source = self.repo.git("rev-parse", "HEAD").stdout.strip()
        target = self.repo.git("rev-parse", "HEAD^").stdout.strip()
        result = E.verify_new_commits(self.repo.root, target, source)
        self.assertIn(formal, result["formal_results"])
        backup = (
            self.backup / "objects" / first["source"]["object_sha256"] / "archive.json"
        )
        backup.unlink()
        with (
            patch.object(HW.reader, "suggestion_refs", return_value=None),
            self.assertRaises(HW.Stop),
        ):
            HW.check_refs(repo, q, "HEAD")

    def test_legacy_snapshot_only_in_archived_attempt(self):
        import review_channel_inputs as inputs

        raw = b"original reviewed candidate, not present in product history"
        ref = self.arc.publish(
            "attempt",
            "reviews/snapshot/r1",
            "snapshot",
            {"inputs/old.md": (raw, "candidate")},
        )
        sources = []
        result = inputs.recover_baseline(
            self.repo.root, "mechanisms/demo/missing.md", E.sha(raw), None, sources
        )
        self.assertEqual(result, raw)
        self.assertEqual(sources[0]["evidence"], ref)
        self.assertIsNone(
            inputs.recover_baseline(
                self.repo.root, "mechanisms/demo/missing.md", "0" * 64, None
            )
        )

    def test_two_worktrees_issue_exactly_one_provider_call(self):
        log = Path(self.e.tmp_root) / "provider-calls.txt"
        adapter = Path(self.env.adapters) / "fake.py"
        text = adapter.read_text().replace(
            "def run(ctx):",
            "def run(ctx):\n    with open("
            + repr(str(log))
            + ', "a") as log:log.write("call\\n")',
        )
        adapter.write_text(text)
        self.repo.git("add", "--", "mechanisms/review-channel")
        self.repo.git("commit", "-m", "fixture runtime")
        other = Path(self.e.tmp_root) / "parallel-worktree"
        p = self.repo.git("worktree", "add", "--detach", str(other), "HEAD")
        self.assertEqual(p.returncode, 0, p.stderr)
        request = self.request("r1")
        cache = Path(self.e.tmp_root) / "concurrent-cache"
        cache.mkdir()
        prefix = [
            sys.executable,
            "-B",
            "-E",
            "-s",
            "-S",
            "-X",
            "pycache_prefix=" + str(cache),
            str(Path(ST.UNIT_DIR) / "review_channel.py"),
            "review",
            "--request",
            request,
            "--repo-root",
        ]
        env = {"PATH": os.environ["PATH"], "HOME": self.e.tmp_root, "LC_ALL": "C"}
        children = [
            subprocess.Popen(
                prefix + [str(root)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for root in (self.repo.root, other)
        ]
        results = [(child, child.communicate(timeout=60)) for child in children]
        self.assertEqual(
            sorted(child.returncode for child, _ in results),
            [0, 1],
            [(c.returncode, out) for c, out in results],
        )
        self.assertEqual(log.read_text().splitlines(), ["call"])
        self.assertEqual(
            len([x for x in self.arc.publications() if x[1]["kind"] == "round"]), 1
        )
        for n, (child, (out, err)) in enumerate(results):
            (Path(self.e.tmp_root) / ("concurrent-" + str(n) + ".stdout")).write_text(
                out
            )
            (Path(self.e.tmp_root) / ("concurrent-" + str(n) + ".stderr")).write_text(
                err
            )

    def test_old_target_deletion_and_query_failure(self):
        path = "reviews/legacy/r1/old.md"
        self.repo.write(path, "old target original")
        self.repo.git("add", "-f", "--", path)
        self.repo.git("commit", "-m", "old target fixture")
        target = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.git("rm", "--", path)
        self.repo.git("commit", "-m", "retire old original")
        source = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(
            E.verify_new_commits(self.repo.root, target, source)["commits_checked"], 1
        )
        with self.assertRaises(E.EvidenceError):
            E.verify_new_commits(self.repo.root, "0" * 40, source)


def cases():
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch-root", required=True)
    args, rest = parser.parse_known_args()
    SCRATCH = Path(args.scratch_root).resolve()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
