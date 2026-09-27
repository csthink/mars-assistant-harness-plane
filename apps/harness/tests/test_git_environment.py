"""feature-t18:KB-03 regression: repository-locating Git variables never steer the domain's git subprocesses.

With GIT_DIR and GIT_WORK_TREE pointing at another repository, the standalone CLI must write domain state only into
the repository named by --repository, the task worktree reads of implement, verify and Validate Change must address
the bound worktree, and the bundle builder must read --repository. The hp entry removes the repository-locating
variables before any dispatch, so mechanism code that runs inside an hp process reads the named repository too. The
shared stripping function removes exactly the repository-locating variables and keeps transport and authentication
variables. Synthetic product lines only.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance import gitrepo
from product_line import commit_change, create_product_line, git

APP = Path(__file__).resolve().parents[1]
MECHANISM = APP.parents[1] / "mechanisms" / "review-channel"
# Runs hp.main with the dispatch target of one route replaced by a probe that calls the review channel's
# storage_mode in the same process, the way definition and change review call it (feature-t18:OD-08).
ENTRY_PROBE = r"""
import json, os, sys
app, mechanism, target, route = sys.argv[1:5]
sys.path[:0] = [app, mechanism]
import hp
import review_evidence

def probe(*_args, **_kwargs):
    try:
        mode = review_evidence.storage_mode(target)
    except Exception as exc:
        mode = "%s: %s" % (type(exc).__name__, exc)
    print(json.dumps(dict(mode=mode, located=sorted(k for k in ("GIT_DIR", "GIT_WORK_TREE") if k in os.environ))))
    return 0

if route == "cli":
    import cli.main
    cli.main.main, argv = probe, ["task"]
elif route == "binding":
    import runtime.launch
    runtime.launch.binding_main, argv = probe, ["binding"]
else:
    import runtime.main
    runtime.main.main, argv = probe, ["serve-stdio"]
sys.exit(hp.main(argv))
"""
LOCATING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR", "GIT_NAMESPACE")


class GitEnvironmentCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("t18-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=False)
            self.temp = None
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t18-gitenv-")
            self.directory = Path(self.temp.name)
        self.target, _ = create_product_line(self.directory / "target" / "repo")
        self.other, _ = create_product_line(self.directory / "other" / "repo")

    def tearDown(self):
        if self.temp is not None:
            self.temp.cleanup()

    def cli(self, *args):
        env = dict(os.environ, GIT_DIR=str(self.other / ".git"), GIT_WORK_TREE=str(self.other), GIT_CONFIG_GLOBAL="/dev/null",
                   GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        return subprocess.run([sys.executable, "-B", str(APP / "hp.py"), *args, "--repository", str(self.target),
                               "--authority-ref", "owner:synthetic"], capture_output=True, text=True, env=env, timeout=300)

    def test_hp_entry_strips_before_dispatch_so_in_process_mechanism_code_reads_the_target(self):
        """KB-03 residual (feature-t18:OD-08): with GIT_DIR and GIT_WORK_TREE naming another repository whose clone configuration sets reviewArchive.mode, the review channel's storage_mode called inside an hp process (standalone CLI, binding and development Runtime routes of hp.main) reads the named repository, because hp.main removes the repository-locating variables before any dispatch."""
        git(self.other, "config", "--local", "reviewArchive.mode", "archive-v1")
        env = dict(os.environ, GIT_DIR=str(self.other / ".git"), GIT_WORK_TREE=str(self.other), GIT_CONFIG_GLOBAL="/dev/null",
                   GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        for route in ("cli", "binding", "serve-stdio"):
            with self.subTest(route=route):
                result = subprocess.run([sys.executable, "-B", "-c", ENTRY_PROBE, str(APP), str(MECHANISM), str(self.target), route],
                                        capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout.splitlines()[-1]), dict(mode="legacy-git", located=[]))
                self.assertIn("hp ignores repository-locating environment variables: GIT_DIR, GIT_WORK_TREE", result.stderr)

    def harness_refs(self, repo):
        return subprocess.run(["git", "-C", str(repo), "for-each-ref", "refs/harness/"], capture_output=True, text=True,
                              env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")}).stdout.strip()

    def test_cli_domain_state_lands_only_in_the_named_repository(self):
        """KB-03: with GIT_DIR and GIT_WORK_TREE naming another repository, verify checks-set (takes the control generation) and config set (feature-t0 configuration) write only the --repository product line."""
        for args in (("verify", "checks-set", "--checks", "[]"), ("config", "set", "concurrency-limit", "2")):
            with self.subTest(command=" ".join(args[:2])):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(self.harness_refs(self.target), "no domain state in the named repository")
                self.assertEqual(self.harness_refs(self.other), "", "domain state leaked into the GIT_DIR repository")
        self.assertFalse((self.other / ".git" / "harness").exists())

    def test_shared_function_strips_locating_and_keeps_transport_variables(self):
        """KB-03: environment() removes exactly the repository-locating variables and keeps transport and authentication ones."""
        extra = {name: "/nowhere/" + name.lower() for name in LOCATING}
        kept = {"GIT_SSH_COMMAND": "ssh -o BatchMode=yes", "GIT_ASKPASS": "/usr/bin/false", "GIT_CONFIG_GLOBAL": "/dev/null"}
        saved = {k: os.environ.get(k) for k in list(extra) + list(kept)}
        os.environ.update(extra)
        os.environ.update(kept)
        try:
            env = gitrepo.environment(self.target)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual([name for name in LOCATING if name in env], [])
        for name, value in kept.items():
            self.assertEqual(env.get(name), value)
        self.assertEqual(env["GIT_CEILING_DIRECTORIES"], str(Path(self.target).resolve().parent))
        self.assertEqual(tuple(gitrepo.REPOSITORY_LOCATING), LOCATING)
        self.assertEqual(git(self.target, "rev-parse", "--show-toplevel"), str(Path(self.target).resolve()))

    def located_elsewhere(self):
        """os.environ as a caller would leave it: GIT_DIR and GIT_WORK_TREE naming the other repository."""
        saved = {k: os.environ.get(k) for k in ("GIT_DIR", "GIT_WORK_TREE")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        os.environ.update(GIT_DIR=str(self.other / ".git"), GIT_WORK_TREE=str(self.other))
        self.addCleanup(restore)

    def diverge(self):
        """The target gains one commit on its branch; the other repository sits on another branch at another commit."""
        base = git(self.target, "rev-parse", "HEAD")
        head = commit_change(self.target, "notes/target.md", "target only\n", refreeze=False)
        git(self.other, "checkout", "-q", "-b", "elsewhere")
        commit_change(self.other, "notes/other.md", "other only\n", refreeze=False)
        return base, head, git(self.target, "symbolic-ref", "--short", "HEAD")

    def test_implement_verify_and_validation_worktree_reads_follow_the_bound_worktree(self):
        """KB-03 residual (feature-t18:OD-07): with GIT_DIR and GIT_WORK_TREE naming another repository, the worktree reads that implement, verify and Validate Change materials make (branch binding, baseline snapshot, ancestry, changed paths, blobs, file existence and diff) address the bound worktree."""
        from domain.implement_verify import worktree
        from domain.validation import materials
        base, head, branch = self.diverge()
        self.located_elsewhere()
        target = Path(self.target)
        reads = (
            ("bound", lambda: worktree.bound(dict(worktree=str(target), branch=branch)), target),
            ("snapshot head", lambda: worktree.snapshot(target)["head"], head),
            ("is_ancestor", lambda: worktree.is_ancestor(target, base, head), True),
            ("changed_files", lambda: worktree.changed_files(target, base, head), ["notes/target.md"]),
            ("blob", lambda: worktree.blob(target, head, "notes/target.md"), b"target only\n"),
            ("materials file check", lambda: materials._show(target, head, "notes/target.md"), b"target only\n"),
            ("materials diff", lambda: "+target only" in worktree.git(target, "diff", "--no-color", "--no-ext-diff",
                                                                      "--no-renames", base, head).stdout.decode(), True),
        )
        for name, read, expected in reads:
            with self.subTest(read=name):
                try:
                    found = read()
                except Exception as exc:  # the unfixed reads raise on the other repository's objects
                    found = "%s: %s" % (type(exc).__name__, exc)
                self.assertEqual(found, expected)

    def test_bundle_source_tree_reads_the_named_repository(self):
        """KB-03 sweep: the bundle builder's source reads (bundle/layout.py) address --repository even with GIT_DIR and GIT_WORK_TREE naming another repository."""
        from bundle import layout
        _, head, _ = self.diverge()
        self.located_elsewhere()
        try:
            found = layout.SourceTree(self.target, head).blob("notes/target.md")
        except layout.BuildRefusal as exc:
            found = "BuildRefusal: %s" % exc
        self.assertEqual(found, (b"target only\n", "0644"))


if __name__ == "__main__":
    unittest.main()
