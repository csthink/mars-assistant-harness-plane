"""feature-t0 acceptance domain tests on synthetic product lines. Docstrings carry the AC tags for the report."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance import results
from domain.acceptance.accept import accept_task, set_configuration
from domain.acceptance.results import Rejection
from domain.acceptance.schema import DIGEST, SCHEMA_ID
from domain.acceptance.sources import parse_task_rows, resolve
from domain.acceptance import gitrepo
from domain.store import RuntimeStore, StoreUnavailable
from product_line import TASK_ROWS, add_done_ruling, commit_change, create_product_line, git
import instance_area

APP = Path(__file__).resolve().parents[1]
PY = sys.executable

class AcceptanceCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t0-tests-")
            self.directory = Path(self.temp.name)
        self.worktrees = self.directory / "worktrees"

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def product_line(self, name="repo", **kw):
        repo, head = create_product_line(self.directory / name, **kw)
        return repo, head, RuntimeStore(repo, payload_schemas={DIGEST: SCHEMA_ID})

    def request(self, repo, request_id="req-1", **overrides):
        base = dict(requestId=request_id, repository=str(repo), taskType="feature", taskId="feature-t0", baseRef="main",
                    worktreeRoot=str(self.worktrees), authorityRef="owner:synthetic")
        base.update(overrides)
        return base

    def reject(self, store, request, code, **kw):
        with self.assertRaises(Rejection) as ctx:
            accept_task(store, request, **kw)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception

    def cli(self, *args, cwd=None):
        proc = subprocess.run([PY, "-B", str(APP / "hp.py"), *args], capture_output=True, text=True, cwd=cwd or APP)
        document = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc.returncode, document, proc.stderr

class SourceResolution(AcceptanceCase):
    def test_resolved_anchor_components(self):
        """AC-02: four sources resolved, component list complete, anchor reproducible on repeated resolution."""
        repo, head, _ = self.product_line()
        first = resolve(str(repo), "feature", "feature-t0", "main")
        second = resolve(str(repo), "feature", "feature-t0", "main")
        self.assertEqual(first["outcome"], "RESOLVED")
        self.assertEqual([c["role"] for c in first["components"]], ["proposal", "spec", "milestones", "task"])
        self.assertTrue(all(c["outcome"] == "RESOLVED" for c in first["components"]))
        self.assertEqual(first["anchor"]["digest"], second["anchor"]["digest"])
        self.assertEqual(first["anchor"]["sourceRevision"], head)
        self.assertEqual(first["anchor"]["milestone"], "M-01")
        self.assertEqual(first["anchor"]["dependencies"], [])
        self.assertEqual(first["anchor"]["components"]["spec"]["subject"], "spec")
        self.assertEqual(first["anchor"]["components"]["milestones"]["freezeRevision"], 1)

    def test_unresolved_causes_are_determinate_and_itemized(self):
        """AC-02: missing source, subject without freeze record, byte mismatch, missing / duplicate / withdrawn / malformed task id are UNRESOLVED with component reasons."""
        repo, _, _ = self.product_line("missing", include=("sdd/spec.md", "sdd/milestones.md"))
        r = resolve(str(repo), "feature", "feature-t0", "main")
        self.assertEqual((r["outcome"], r["components"][0]["role"], r["components"][0]["outcome"]), ("UNRESOLVED", "proposal", "UNRESOLVED"))
        repo, _, _ = self.product_line("nofreeze", freeze=("proposal", "milestones"))
        r = resolve(str(repo), "feature", "feature-t0", "main")
        self.assertEqual(r["outcome"], "UNRESOLVED")
        self.assertIn("no freeze record", r["reason"])
        repo, _, _ = self.product_line("mismatch")
        commit_change(repo, "sdd/spec.md", (repo / "sdd/spec.md").read_text() + "\n- **FR-16** drifted.\n", refreeze=False)
        r = resolve(str(repo), "feature", "feature-t0", "main")
        self.assertEqual(r["outcome"], "UNRESOLVED")
        self.assertIn("bytes differ", r["reason"])
        self.assertEqual([c["outcome"] for c in r["components"]], ["RESOLVED", "UNRESOLVED"])
        repo, _, _ = self.product_line("rows", withdrawn_rows=["  - feature-t9 撤回 · 类型：后端 · Spec 引用：spec.md@r1 FR-01 · 依赖：无"])
        self.assertEqual(resolve(str(repo), "feature", "feature-t7", "main")["outcome"], "UNRESOLVED")
        self.assertEqual(resolve(str(repo), "feature", "feature-t9", "main")["reason"], "task row is WITHDRAWN")
        self.assertEqual(resolve(str(repo), "feature", "hotfix-h" + "0" * 64, "main")["reason"], "task id does not match the milestones task-id grammar")
        repo, _, _ = self.product_line("dup", rows=TASK_ROWS + [TASK_ROWS[0]])
        r = resolve(str(repo), "feature", "feature-t0", "main")
        self.assertEqual((r["outcome"], r["components"][-1]["identity"]["matches"]), ("UNRESOLVED", 2))
        repo, _, _ = self.product_line("ref")
        self.assertIn("does not resolve", resolve(str(repo), "feature", "feature-t0", "refs/heads/nope")["reason"])
        r = resolve(str(self.directory / "nowhere"), "feature", "feature-t0", "main")
        self.assertEqual(r["outcome"], "UNRESOLVED")

    def test_task_id_grammar_is_the_review_channel_definition(self):
        """Acceptance and review routing share one task-id grammar, the review channel's TASK_ID_RE of this hp tree."""
        from domain.acceptance import sources
        from domain.channel_contract import CONTRACT, PATH
        self.assertIs(sources.RE_TASK_ID, CONTRACT.TASK_ID_RE)
        self.assertEqual(PATH, APP.parents[1] / "mechanisms" / "review-channel" / "review_channel_contract.py")
        self.assertEqual(Path(CONTRACT.__file__).resolve(), PATH)
        for task_id in ("feature-t0", "design-t0", "gov-t0", "feature-t12"):
            self.assertTrue(sources.RE_TASK_ID.match(task_id) and CONTRACT.TASK_RECORD_RE.match(task_id), task_id)
        for task_id in ("feature-t00", "gov-t01", "feature-t", "hotfix-h" + "0" * 64):
            self.assertIsNone(sources.RE_TASK_ID.match(task_id), task_id)
        repo, _, _ = self.product_line("padded")
        r = resolve(str(repo), "feature", "feature-t00", "main")
        self.assertEqual((r["outcome"], r["reason"]), ("UNRESOLVED", "task id does not match the milestones task-id grammar"))

    def test_indeterminate_when_git_cannot_answer(self):
        """AC-02: an unreadable source system yields INDETERMINATE, never a missing-component claim."""
        repo, _, _ = self.product_line()
        shim = self.directory / "shim"
        shim.mkdir()
        (shim / "git").write_text("#!/bin/sh\necho 'fatal: simulated outage' >&2\nexit 2\n")
        (shim / "git").chmod((shim / "git").stat().st_mode | stat.S_IEXEC)
        original = os.environ["PATH"]
        os.environ["PATH"] = str(shim) + os.pathsep + original
        try:
            r = resolve(str(repo), "feature", "feature-t0", "main")
        finally:
            os.environ["PATH"] = original
        self.assertEqual(r["outcome"], "INDETERMINATE")
        self.assertEqual(r["components"], [])
        (shim / "git").write_text("#!/bin/sh\nsleep 5\n")
        original_timeout = gitrepo.TIMEOUT
        gitrepo.TIMEOUT = 1
        os.environ["PATH"] = str(shim) + os.pathsep + original
        try:
            r = resolve(str(repo), "feature", "feature-t0", "main")
        finally:
            os.environ["PATH"] = original
            gitrepo.TIMEOUT = original_timeout
        self.assertEqual(r["outcome"], "INDETERMINATE")
        self.assertIn("TimeoutExpired", r["reason"])

    @unittest.skipIf(os.geteuid() == 0, "permission denial cannot be simulated as root")
    def test_permission_denied_is_indeterminate_and_recovers(self):
        """AC-02: an inaccessible .git (EACCES) is INDETERMINATE for resolve and accept, never a missing-component claim nor an enclosing repository; access restored gives RESOLVED / ACCEPTED."""
        outer = self.directory / "outer"
        outer.mkdir()
        git(outer, "init", "-q", "-b", "main")
        (outer / "README").write_text("outer\n")
        git(outer, "add", "-A")
        git(outer, "commit", "-q", "-m", "outer")
        repo, head, store = self.product_line("outer/inner")
        request = self.request(repo)
        dot = repo / ".git"
        dot.chmod(0)
        try:
            r = resolve(str(repo), "feature", "feature-t0", "main")
            self.assertEqual((r["outcome"], r["components"]), ("INDETERMINATE", []))
            self.assertIn("not accessible", r["reason"])
            with self.assertRaises(StoreUnavailable) as ctx:
                RuntimeStore(repo, payload_schemas={DIGEST: SCHEMA_ID})
            self.assertFalse(ctx.exception.determinate)
            with self.assertRaises(Rejection) as rejected:
                accept_task(store, request)
            self.assertEqual(rejected.exception.code, results.INDETERMINATE)
            code, doc, _ = self.cli("task", "resolve", "--repository", str(repo), "--type", "feature", "--task-id", "feature-t0", "--base-ref", "main")
            self.assertEqual((code, doc["result"]), (2, "INDETERMINATE"))
            code, doc, _ = self.cli("task", "accept", "--repository", str(repo), "--type", "feature", "--task-id", "feature-t0", "--base-ref", "main",
                                    "--request-id", "req-cli", "--authority-ref", "owner:cli", "--worktree-root", str(self.worktrees))
            self.assertEqual((code, doc["result"], doc["reason"]["code"]), (2, results.INDETERMINATE, results.INDETERMINATE))
        finally:
            dot.chmod(0o755)
        self.assertEqual(git(outer, "for-each-ref", "refs/harness"), "")
        self.assertFalse((outer / ".git/harness").exists())
        self.assertIsNone(store.head())
        self.assertEqual(resolve(str(repo), "feature", "feature-t0", "main")["outcome"], "RESOLVED")
        self.assertEqual(accept_task(store, request)["result"], results.ACCEPTED)

    def test_nonexistent_or_non_root_reference_is_unresolved(self):
        """AC-02: a missing path or a directory without .git is a determinate UNRESOLVED, even inside an enclosing repository."""
        repo, _, _ = self.product_line()
        (repo / "sub").mkdir()
        r = resolve(str(repo / "sub"), "feature", "feature-t0", "main")
        self.assertEqual(r["outcome"], "UNRESOLVED")
        self.assertIn("no .git entry", r["reason"])
        r = resolve(str(self.directory / "nowhere"), "feature", "feature-t0", "main")
        self.assertEqual(r["outcome"], "UNRESOLVED")
        self.assertIn("does not exist", r["reason"])
        code, doc, _ = self.cli("task", "accept", "--repository", str(self.directory / "nowhere"), "--type", "feature", "--task-id", "feature-t0",
                                "--base-ref", "main", "--request-id", "req-cli", "--authority-ref", "owner:cli", "--worktree-root", str(self.worktrees))
        self.assertEqual((code, doc["result"]), (1, results.UNRESOLVED))
        code, doc, _ = self.cli("task", "resolve", "--repository", str(repo / "sub"), "--type", "feature", "--task-id", "feature-t0", "--base-ref", "main")
        self.assertEqual((code, doc["result"]), (0, "UNRESOLVED"))

    @instance_area.needed
    def test_task_row_grammar_matches_repository_linter(self):
        """AC-02: the task row parser agrees with artifact_lint on hp's own milestones."""
        text = instance_area.path("sdd/milestones.md").read_text()
        rows = parse_task_rows(text)
        ids = [r["taskId"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        row = [r for r in rows if r["taskId"] == "feature-t0"][0]
        self.assertEqual((row["milestone"], row["dependencies"]), ("M-04", ["gov-t19", "gov-t20", "gov-t21", "gov-t22"]))
        self.assertTrue(all(r["withdrawn"] for r in rows if r["milestone"] == "M-06"))
        lint = subprocess.run([PY, "-B", str(APP.parents[1] / "mechanisms/artifact-templates/artifact_lint.py"), "milestones",
                               str(instance_area.path("sdd/milestones.md"))], capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        listed = [line.split()[1] for line in text.splitlines() if line.startswith("  - ") and " · 类型：" in line]
        self.assertEqual(sorted(ids), sorted(listed))

    def test_accepted_anchor_does_not_follow_upstream_change(self):
        """AC-02: after acceptance an upstream re-freeze changes new resolutions but not the accepted anchor."""
        repo, head, store = self.product_line()
        accepted = accept_task(store, self.request(repo))
        before = accepted["task"]["anchor"]
        commit_change(repo, "sdd/spec.md", (repo / "sdd/spec.md").read_text() + "\n- **FR-16** amended.\n", refreeze=True)
        self.assertNotEqual(resolve(str(repo), "feature", "feature-t0", "main")["anchor"]["digest"], before["digest"])
        self.assertEqual(store.read()["tasks"]["feature-t0"]["anchor"], before)
        self.assertEqual(accept_task(store, self.request(repo))["task"]["anchor"]["sourceRevision"], head)

class Acceptance(AcceptanceCase):
    def test_accept_establishes_task_branch_worktree_and_instance(self):
        """AC-01: RESOLVED anchor, branch at the source revision, worktree under the given root, Workflow Instance initial record."""
        repo, head, store = self.product_line()
        out = accept_task(store, self.request(repo))
        self.assertEqual(out["result"], results.ACCEPTED)
        task = out["task"]
        self.assertEqual(task["branch"], "harness/feature-t0")
        self.assertEqual(git(repo, "rev-parse", "refs/heads/harness/feature-t0"), head)
        worktree = Path(task["worktree"])
        self.assertEqual(worktree, (self.worktrees / "harness/feature-t0").resolve())
        self.assertEqual(git(worktree, "rev-parse", "--abbrev-ref", "HEAD"), "harness/feature-t0")
        self.assertIn(str(worktree), git(repo, "worktree", "list"))
        instance = task["workflowInstance"]
        # feature-t2 owns the Workflow Instance record: the Current Position is the stable topology
        # node identity, not a display name, and the initial record carries the layered facts.
        self.assertEqual(instance["position"], "N-DEF-HUMAN")
        self.assertEqual((instance["lifecycle"], instance["condition"]), ("ACTIVE", "AWAITING_HUMAN_ACTION"))
        self.assertEqual(instance["runtimeVersion"], "1")
        self.assertEqual(instance["definition"]["path"], "mechanisms/delivery-method/MVP_Workflow_v5.drawio")
        self.assertEqual(instance["reviewConfiguration"], dict(definitionReview=False, changeValidation=False, source="default"))
        self.assertEqual(task["anchor"]["sourceRevision"], head)
        self.assertEqual(task["provenance"], "req-1")
        state = store.read()
        self.assertEqual(list(state["tasks"]), ["feature-t0"])
        self.assertEqual(state["acceptance"]["req-1"]["status"], "accepted")
        self.assertEqual(list(state["claims"].values())[0]["state"], "accepted")
        self.assertTrue((repo / ".git/harness/writer.lock").exists())

    def test_cli_and_function_share_one_domain(self):
        """AC-01: the CLI accepts through the same domain function; a second CLI request sees the same claim."""
        repo, head, store = self.product_line()
        code, doc, err = self.cli("task", "accept", "--repository", str(repo), "--type", "feature", "--task-id", "feature-t0",
                                  "--base-ref", "main", "--request-id", "cli-1", "--authority-ref", "owner:cli", "--worktree-root", str(self.worktrees))
        self.assertEqual((code, doc["result"]), (0, results.ACCEPTED), err)
        self.assertEqual(doc["task"]["anchor"]["sourceRevision"], head)
        self.assertEqual(store.read()["tasks"]["feature-t0"]["provenance"], "cli-1")
        self.reject(store, self.request(repo, "func-2"), results.DUPLICATE_ACCEPTED_TASK)
        self.assertEqual(accept_task(store, self.request(repo, "cli-1", authorityRef="owner:cli"))["result"], results.IDEMPOTENT_REPLAY)

    def test_dry_run_has_no_effect(self):
        """AC-01: dry run reports readiness and intended identities without any durable or physical effect."""
        repo, head, store = self.product_line()
        out = accept_task(store, self.request(repo), dry_run=True)
        self.assertEqual((out["readiness"], out["intended"]["branch"]), ("READY", "harness/feature-t0"))
        self.assertIsNone(store.head())
        self.assertIsNone(gitrepo.Repository(repo).branch_target("harness/feature-t0"))
        self.assertFalse(self.worktrees.exists())
        self.reject(store, self.request(repo, taskId="feature-t1"), results.DEPENDENCY_UNMET, dry_run=True)
        self.assertIsNone(store.head())

class Idempotency(AcceptanceCase):
    def test_same_request_replays_and_conflicting_intent_rejected(self):
        """AC-03: same requestId + same intent replays; same requestId + different intent is REQUEST_CONFLICT."""
        repo, _, store = self.product_line()
        first = accept_task(store, self.request(repo))
        again = accept_task(store, self.request(repo))
        self.assertEqual((first["result"], again["result"]), (results.ACCEPTED, results.IDEMPOTENT_REPLAY))
        self.assertEqual(first["task"], again["task"])
        self.assertEqual(git(repo, "branch", "--list", "harness/*").count("harness/"), 1)
        self.assertEqual(len(list(self.worktrees.rglob(".git"))), 1)
        exc = self.reject(store, self.request(repo, baseRef="HEAD"), results.REQUEST_CONFLICT)
        self.assertEqual(exc.detail["recorded"], store.read()["acceptance"]["req-1"]["intentDigest"])

    def test_duplicate_of_accepted_and_terminal_tasks(self):
        """AC-03: other requestIds for the same upstream task get DUPLICATE_ACCEPTED_TASK, also once the Task is terminal."""
        repo, _, store = self.product_line()
        accept_task(store, self.request(repo))
        exc = self.reject(store, self.request(repo, "req-2"), results.DUPLICATE_ACCEPTED_TASK)
        self.assertEqual(exc.detail["task"], "task:feature-t0")
        add_done_ruling(repo, "feature-t0")
        self.reject(store, self.request(repo, "req-3"), results.DUPLICATE_ACCEPTED_TASK)
        def publish(s):
            s["tasks"]["feature-t0"]["terminal"] = dict(kind="published", at="2026-09-22T00:00:00Z")
        store.transaction(None, publish)
        self.reject(store, self.request(repo, "req-4"), results.DUPLICATE_ACCEPTED_TASK)
        self.assertEqual(len(store.read()["tasks"]), 1)

    def test_in_progress_claim_blocks_others_until_resumed(self):
        """AC-03 / AC-05: a claimed operation blocks other requests; the same request resumes and completes."""
        repo, _, store = self.product_line()
        class Stop(Exception):
            pass
        def observer(phase, detail=None):
            if phase == "after-claim":
                raise Stop()
        with self.assertRaises(Stop):
            accept_task(store, self.request(repo), observer=observer)
        state = store.read()
        self.assertEqual((state["acceptance"]["req-1"]["status"], state["tasks"]), ("claimed", {}))
        exc = self.reject(store, self.request(repo, "req-2"), results.DUPLICATE_ACCEPTANCE_IN_PROGRESS)
        self.assertEqual(exc.detail["operation"], "req-1")
        self.assertEqual(accept_task(store, self.request(repo))["result"], results.ACCEPTED)
        self.reject(store, self.request(repo, "req-2"), results.DUPLICATE_ACCEPTED_TASK)

    def test_concurrent_requests_yield_one_claim(self):
        """AC-03: two concurrent requests for the same task produce at most one claim and one Task."""
        repo, _, store = self.product_line()
        set_configuration(store, "concurrency-limit", 4, "owner:synthetic")
        barrier = threading.Barrier(2)
        outcomes = {}
        def run(request_id):
            barrier.wait()
            try:
                outcomes[request_id] = accept_task(RuntimeStore(repo, payload_schemas={DIGEST: SCHEMA_ID}), self.request(repo, request_id))["result"]
            except Rejection as exc:
                outcomes[request_id] = exc.code
        threads = [threading.Thread(target=run, args=(rid,)) for rid in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes.values())[0], results.ACCEPTED)
        self.assertIn(sorted(outcomes.values())[1], (results.DUPLICATE_ACCEPTANCE_IN_PROGRESS, results.DUPLICATE_ACCEPTED_TASK))
        self.assertEqual(len(store.read()["tasks"]), 1)
        self.assertEqual(git(repo, "branch", "--list", "harness/*").count("harness/"), 1)

class Concurrency(AcceptanceCase):
    def test_default_limit_rejects_and_configured_limit_admits(self):
        """AC-04: default limit 1 rejects the second acceptance distinctly; an authorized limit change admits it; replay is not counted."""
        repo, _, store = self.product_line()
        accept_task(store, self.request(repo))
        exc = self.reject(store, self.request(repo, "req-2", taskId="gov-t0"), results.CONCURRENCY_LIMIT_REACHED)
        self.assertEqual((exc.detail["limit"], exc.detail["inFlight"]["count"]), (1, 1))
        self.assertEqual(accept_task(store, self.request(repo))["result"], results.IDEMPOTENT_REPLAY)
        with self.assertRaises(Rejection) as ctx:
            set_configuration(store, "concurrency-limit", 2, "")
        self.assertEqual(ctx.exception.code, results.AUTHORITY_MISSING)
        with self.assertRaises(Rejection):
            set_configuration(store, "concurrency-limit", 0, "owner:synthetic")
        change = set_configuration(store, "concurrency-limit", 2, "owner:synthetic")
        self.assertEqual((change["previous"], change["value"]), (None, 2))
        self.assertEqual(store.read()["configuration"]["history"][0]["authorityRef"], "owner:synthetic")
        self.assertEqual(accept_task(store, self.request(repo, "req-2", taskId="gov-t0"))["result"], results.ACCEPTED)
        self.reject(store, self.request(repo, "req-3", taskId="gov-t1"), results.CONCURRENCY_LIMIT_REACHED)

    def test_limit_one_keeps_serial_semantics_and_terminal_frees_capacity(self):
        """AC-04: with limit 1 a terminal (done) task frees capacity; claimed operations count as in flight."""
        repo, _, store = self.product_line()
        accept_task(store, self.request(repo))
        self.reject(store, self.request(repo, "req-2", taskId="gov-t0"), results.CONCURRENCY_LIMIT_REACHED)
        add_done_ruling(repo, "feature-t0")
        self.assertEqual(accept_task(store, self.request(repo, "req-2", taskId="gov-t0"))["result"], results.ACCEPTED)
        class Stop(Exception):
            pass
        add_done_ruling(repo, "gov-t0")
        def observer(phase, detail=None):
            if phase == "after-claim":
                raise Stop()
        with self.assertRaises(Stop):
            accept_task(store, self.request(repo, "req-3", taskId="gov-t1"), observer=observer)
        exc = self.reject(store, self.request(repo, "req-4", taskId="feature-t1"), results.CONCURRENCY_LIMIT_REACHED)
        self.assertEqual(exc.detail["inFlight"]["claimed"], [k for k, c in store.read()["claims"].items() if c["state"] == "claimed"])
        self.assertEqual(exc.detail["inFlight"]["count"], 1)

class Atomicity(AcceptanceCase):
    PHASES = ("after-claim", "after-branch", "after-worktree", "before-accept")

    def kill_then_resume(self, phase):
        repo, head, store = self.product_line(phase)
        request = self.request(repo, worktreeRoot=str(self.directory / (phase + "-worktrees")))
        request_file = self.directory / (phase + "-request.json")
        request_file.write_text(json.dumps(request))
        proc = subprocess.run([PY, "-B", str(APP / "tests/accept_with_fault.py"), phase, str(request_file)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, -9, proc.stdout + proc.stderr)
        self.assertTrue(request_file.with_suffix(".fired.json").exists())
        state = store.read()
        self.assertEqual(state["tasks"], {})
        self.assertEqual(state["acceptance"]["req-1"]["status"], "claimed")
        self.reject(store, dict(request, requestId="other"), results.DUPLICATE_ACCEPTANCE_IN_PROGRESS)
        repository = gitrepo.Repository(repo)
        branch_before = repository.branch_target("harness/feature-t0")
        resumed = accept_task(store, request)
        self.assertEqual(resumed["result"], results.ACCEPTED)
        self.assertEqual(repository.branch_target("harness/feature-t0"), head)
        if branch_before is not None:
            self.assertEqual(branch_before, head)
        self.assertEqual(len(git(repo, "worktree", "list").splitlines()), 2)
        self.assertEqual(store.read()["tasks"]["feature-t0"]["provenance"], "req-1")
        return repo, store

    def test_kill_after_claim(self):
        """AC-05: SIGKILL after the claim commit leaves no visible Task; the same request resumes to ACCEPTED."""
        self.kill_then_resume("after-claim")

    def test_kill_after_branch(self):
        """AC-05: SIGKILL after branch creation; the owned branch is verified and reused, not recreated."""
        self.kill_then_resume("after-branch")

    def test_kill_after_worktree(self):
        """AC-05: SIGKILL after worktree creation; the registered worktree is verified and reused."""
        self.kill_then_resume("after-worktree")

    def test_kill_before_accept(self):
        """AC-05: SIGKILL right before the Acceptance Commit Point; nothing is visible until the resumed commit."""
        self.kill_then_resume("before-accept")

    def test_partial_effect_mismatch_stops_and_keeps_claim(self):
        """AC-05: a branch that no longer points at the source revision stops the resume; nothing is deleted, the claim stays."""
        repo, head, store = self.product_line()
        request = self.request(repo)
        request_file = self.directory / "request.json"
        request_file.write_text(json.dumps(request))
        proc = subprocess.run([PY, "-B", str(APP / "tests/accept_with_fault.py"), "after-branch", str(request_file)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, -9)
        other = commit_change(repo, "sdd/proposal.md", (repo / "sdd/proposal.md").read_text() + "\nmore\n", refreeze=True)
        git(repo, "branch", "-f", "harness/feature-t0", other)
        exc = self.reject(store, request, results.PARTIAL_EFFECT_UNRESOLVED)
        self.assertEqual((exc.detail["actual"], exc.detail["expected"]), (other, head))
        self.assertEqual(git(repo, "rev-parse", "refs/heads/harness/feature-t0"), other)
        state = store.read()
        self.assertEqual((state["acceptance"]["req-1"]["status"], state["acceptance"]["req-1"]["outcome"]), ("claimed", results.PARTIAL_EFFECT_UNRESOLVED))
        self.reject(store, dict(request, requestId="req-2"), results.DUPLICATE_ACCEPTANCE_IN_PROGRESS)
        stray = self.worktrees / "harness/feature-t0"
        git(repo, "branch", "-f", "harness/feature-t0", head)
        stray.mkdir(parents=True)
        self.reject(store, request, results.PARTIAL_EFFECT_UNRESOLVED)
        self.assertTrue(stray.exists())

    def test_workspace_error_before_claim_and_after(self):
        """AC-05 / AC-06: pre-existing branch or worktree path is a determinate WORKSPACE_ERROR before any claim; an invalid root never reaches the domain."""
        repo, head, store = self.product_line()
        git(repo, "branch", "harness/feature-t0", head)
        self.reject(store, self.request(repo), results.WORKSPACE_ERROR)
        self.assertEqual(store.read()["claims"], {})
        git(repo, "branch", "-D", "harness/feature-t0")
        recorded = store.read()["acceptance"]
        self.reject(store, self.request(repo, "req-2", worktreeRoot="relative/root"), results.WORKSPACE_ERROR)
        self.reject(store, self.request(repo, "req-3", worktreeRoot=str(repo / "inside")), results.WORKSPACE_ERROR)
        self.assertEqual(store.read()["acceptance"], recorded)

class Preconditions(AcceptanceCase):
    def test_dependency_unmet_until_done_fact(self):
        """AC-06: a listed dependency without a done fact rejects; a committed done ruling satisfies it; close does not."""
        repo, _, store = self.product_line()
        exc = self.reject(store, self.request(repo, taskId="feature-t1"), results.DEPENDENCY_UNMET)
        self.assertEqual(exc.detail["unmet"], ["feature-t0"])
        (repo / "tasks/feature-t0/rulings").mkdir(parents=True)
        (repo / "tasks/feature-t0/rulings/RU-01-close.md").write_text("> Ruling: RU-01\n> Date: 2026-09-22\n> Type: close\n> Object: feature-t0\n> Basis: x\n> Decision: x\n\n# close\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "close")
        self.reject(store, self.request(repo, taskId="feature-t1"), results.DEPENDENCY_UNMET)
        add_done_ruling(repo, "feature-t0")
        self.assertEqual(accept_task(store, self.request(repo, taskId="feature-t1"))["result"], results.ACCEPTED)

    def test_authority_and_hotfix_lane(self):
        """AC-06: missing authority and hotfix requests are rejected before any effect with distinct codes."""
        repo, _, store = self.product_line()
        self.reject(store, self.request(repo, authorityRef=""), results.AUTHORITY_MISSING)
        self.assertIsNone(store.head())
        exc = self.reject(store, self.request(repo, taskType="hotfix", taskId="hotfix-h" + "a" * 64), results.SOURCE_LANE_UNAVAILABLE)
        self.assertEqual(store.read()["acceptance"]["req-1"]["outcome"], results.SOURCE_LANE_UNAVAILABLE)
        self.assertEqual(store.read()["claims"], {})

    def test_cli_closed_set_and_exit_codes(self):
        """AC-06: CLI emits machine-readable results from the closed set with exit codes 0 / 1 / 2."""
        repo, head, store = self.product_line()
        common = ["--repository", str(repo), "--type", "feature", "--task-id", "feature-t0", "--base-ref", "main"]
        accept = ["--request-id", "cli-1", "--authority-ref", "owner:cli", "--worktree-root", str(self.worktrees)]
        code, doc, _ = self.cli("task", "resolve", *common)
        self.assertEqual((code, doc["result"], doc["anchor"]["sourceRevision"]), (0, "RESOLVED", head))
        code, doc, _ = self.cli("task", "resolve", *common[:-2], "--base-ref", "refs/heads/nope")
        self.assertEqual((code, doc["result"]), (0, "UNRESOLVED"))
        code, doc, _ = self.cli("task", "accept", *common, *accept, "--dry-run")
        self.assertEqual((code, doc["readiness"], doc["dryRun"]), (0, "READY", True))
        code, doc, _ = self.cli("task", "accept", *common, *accept)
        self.assertEqual((code, doc["result"]), (0, results.ACCEPTED))
        code, doc, _ = self.cli("task", "accept", *common, *accept)
        self.assertEqual((code, doc["result"]), (0, results.IDEMPOTENT_REPLAY))
        code, doc, _ = self.cli("task", "accept", *common, "--request-id", "cli-2", *accept[2:])
        self.assertEqual((code, doc["result"], doc["reason"]["code"]), (1, results.DUPLICATE_ACCEPTED_TASK, results.DUPLICATE_ACCEPTED_TASK))
        code, doc, _ = self.cli("task", "accept", *common[:4], "--task-id", "gov-t0", "--base-ref", "main", "--request-id", "cli-3", *accept[2:])
        self.assertEqual((code, doc["result"]), (1, results.CONCURRENCY_LIMIT_REACHED))
        code, doc, _ = self.cli("task", "accept", "--repository", str(repo), "--type", "hotfix", "--task-id", "hotfix-h" + "b" * 64,
                                "--base-ref", "main", "--request-id", "cli-4", *accept[2:])
        self.assertEqual((code, doc["result"]), (1, results.SOURCE_LANE_UNAVAILABLE))
        code, doc, _ = self.cli("config", "set", "concurrency-limit", "3", "--repository", str(repo), "--authority-ref", "D-09")
        self.assertEqual((code, doc["result"], doc["value"]), (0, "CONFIGURED", 3))
        code, doc, _ = self.cli("config", "set", "concurrency-limit", "x", "--repository", str(repo), "--authority-ref", "D-09")
        self.assertEqual((code, doc["result"]), (1, results.WORKSPACE_ERROR))
        shim = self.directory / "shim"
        shim.mkdir()
        (shim / "git").write_text("#!/bin/sh\necho 'fatal: simulated outage' >&2\nexit 2\n")
        (shim / "git").chmod((shim / "git").stat().st_mode | stat.S_IEXEC)
        proc = subprocess.run([PY, "-B", str(APP / "hp.py"), "task", "resolve", *common], capture_output=True, text=True,
                              env={**os.environ, "PATH": str(shim) + os.pathsep + os.environ["PATH"]})
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["result"]), (2, "INDETERMINATE"))
        proc = subprocess.run([PY, "-B", str(APP / "hp.py"), "task", "accept", *common, "--request-id", "cli-5", *accept[2:]], capture_output=True, text=True,
                              env={**os.environ, "PATH": str(shim) + os.pathsep + os.environ["PATH"]})
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["result"]), (2, results.INDETERMINATE))
        self.assertTrue(set(results.RESULTS) >= {results.ACCEPTED, results.IDEMPOTENT_REPLAY, results.DUPLICATE_ACCEPTED_TASK,
                                                 results.CONCURRENCY_LIMIT_REACHED, results.SOURCE_LANE_UNAVAILABLE, results.INDETERMINATE})

if __name__ == "__main__":
    unittest.main()
