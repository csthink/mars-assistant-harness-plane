"""实际规则与命令的隔离测试；临时 Git 仓不读取真实仓历史、不调用网络。"""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
import gates_base as base
import gates_generate as gen
import gates_layout as layout
import gates_manifest as manifest

UNIT = Path(__file__).resolve().parent
CATALOG = None


def git(root, *args):
    result = subprocess.run([shutil.which("git"), "-C", str(root),
                             "-c", "user.name=selftest", "-c", "user.email=selftest@local",
                             "-c", "commit.gpgsign=false", *args],
                            env=base.git_environment(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout


def write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def design():
    return "# Demo\n\n> Depends on:\n> 无\n>\n> 权威状态: subject `demo`（治理记录目录按所在仓的布局规则解析；唯一状态正本）\n\n正文。\n"


def baseline(root):
    for path, content in {
        "AGENTS.md": "# 契约\n", "CLAUDE.md": "@AGENTS.md\n", "README.md": "# README\n",
        ".gitignore": "review-attempts/\ntasks/*/attempts/\n",
        "sdd/proposal.md": "# Proposal\n", "sdd/spec.md": "# Spec\n",
        "sdd/milestones.md": "# Milestones\n", "tasks/gov-t0/task.md": "# Task\n",
        "records/founding/note.md": "# Provenance\n",
        "mechanisms/demo/HarnessPlane_Demo_Design_v1.md": design(),
        "mechanisms/gates/mechanisms_source.md": "# 单元\n\n<!--table:units-->\n\n尾注。\n",
        "mechanisms/gates/root_readme_source.md": "# README\n\n<!--table:top_level_map-->\n\n目录\n\n<!--table:subject_roster-->\n\n尾注。\n",
        "mechanisms/gates/readme_data.json": json.dumps({"top_level": {
            name: {"zone": "实例区", "gloss": "说明"}
            for name in ("mechanisms", "records", "sdd", "tasks")}}, ensure_ascii=False) + "\n",
        "mechanisms/gates/rules_catalog.json": json.dumps(CATALOG, ensure_ascii=False) + "\n",
    }.items():
        write(root, path, content)


def context(root):
    catalog = base.load_catalog(root / "mechanisms/gates")
    return base.Context(str(root), base.profile_from_catalog(catalog), catalog)


@contextlib.contextmanager
def repo():
    with tempfile.TemporaryDirectory(prefix="hp-lint-test-", dir=tempfile.gettempdir()) as directory:
        root = Path(directory)
        git(root, "init", "-q")
        baseline(root)
        yield root


def cli(root, command, *args, env=None):
    return subprocess.run([sys.executable, str(UNIT / "gates.py"), command,
                           "--repo-root", str(root), *args], capture_output=True,
                          env=env if env is not None else base.git_environment())


def setup_fixture(root, steps):
    for step in steps:
        action = step["action"]
        if action in ("bootstrap_baseline", "manifest_baseline"):
            baseline(root)
        elif action == "write_file":
            write(root, step["path"], step["content"])
        elif action == "append_file":
            with (root / step["path"]).open("ab") as stream:
                stream.write(step["content"].encode("utf-8"))
        elif action == "remove":
            target = root / step["path"]
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        elif action == "git_stage":
            git(root, "add", "-f", "--", *step["paths"])
        elif action == "demo_unit":
            write(root, "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", design())
        elif action == "run_manifest_write":
            code, messages = gen.write_all(context(root))
            if code:
                raise RuntimeError(messages)
        else:
            raise ValueError("未知测试动作：%s" % action)


class RuleExamples(unittest.TestCase):
    def test_content_examples(self):
        for module in (layout, manifest):
            examples = importlib.import_module("selftest_" + module.GATE.name).FIXTURES
            for fixture in examples:
                with self.subTest(case=fixture["id"]), repo() as root:
                    setup_fixture(root, fixture["setup"])
                    rule = next(r for r in module.RULES if r.id == fixture["rule_id"])
                    result = base.run_rule(rule, context(root))
                    self.assertEqual(result.state, fixture["expect"], result)

    def test_negative_examples_detect_removed_checks(self):
        # 对每个现存负例使用同一断言。将实际检查替换为空实现，原断言必须失败。
        for module in (layout, manifest):
            examples = importlib.import_module("selftest_" + module.GATE.name).FIXTURES
            for fixture in examples:
                if fixture["kind"] != "negative":
                    continue
                with self.subTest(case=fixture["id"]), repo() as root:
                    setup_fixture(root, fixture["setup"])
                    rule = next(r for r in module.RULES if r.id == fixture["rule_id"])
                    mutant = rule._replace(check=lambda _ctx: [])
                    with self.assertRaises(AssertionError):
                        self.assertEqual(base.run_rule(mutant, context(root)).state, fixture["expect"])


class CommandTests(unittest.TestCase):
    def test_sdd_architecture_symlink_is_rejected(self):
        with repo() as root:
            write(root, "records/architecture-source.md", "# Not a member\n")
            (root / "sdd/architecture.md").symlink_to("../records/architecture-source.md")
            result = cli(root, "layout")
            self.assertEqual(result.returncode, 1, result.stderr)
            findings = [f for c in json.loads(result.stdout)["checks"]
                        if c["check"] == "sdd-members" for f in c["findings"]]
            self.assertTrue(any(f["subject"] == "sdd/architecture.md" for f in findings), findings)

    def test_case_only_rename_is_not_hidden_by_git_config(self):
        with repo() as root:
            git(root, "add", "--", "sdd/spec.md")
            git(root, "config", "core.ignoreCase", "true")
            (root / "sdd/spec.md").rename(root / "sdd/Spec.md")
            result = cli(root, "layout")
            self.assertEqual(result.returncode, 1, result.stderr)
            findings = [f for c in json.loads(result.stdout)["checks"]
                        if c["check"] == "sdd-members" for f in c["findings"]]
            self.assertTrue(any(f["subject"] == "sdd/Spec.md" for f in findings), findings)

    def test_unicode_paths_and_nul_delimiters_ignore_display_config(self):
        with repo() as root:
            decomposed = "cafe\u0301"
            write(root, "mechanisms/" + decomposed + "/note.txt", "unicode\n")
            write(root, "mechanisms/demo/tab\tfile.txt", "tab\n")
            outputs = []
            for value in ("true", "false"):
                git(root, "config", "core.precomposeUnicode", value)
                git(root, "config", "core.quotePath", value)
                ctx = context(root)
                entries = {entry.path for entry in ctx.entries()}
                self.assertIn("mechanisms/" + decomposed + "/note.txt", entries)
                self.assertIn("mechanisms/demo/tab\tfile.txt", entries)
                outputs.append(gen.generate(ctx, "mechanisms/MECHANISMS.md"))
            self.assertEqual(outputs[0], outputs[1])

    def test_violation_manual_commit_and_read_only(self):
        with repo() as root:
            gen.write_all(context(root))
            write(root, "sdd/extra.md", "extra\n")
            before = snapshot(root)
            for command in ("layout", "all"):
                result = cli(root, command)
                self.assertEqual(result.returncode, 1, result.stderr)
                record = json.loads(result.stdout)
                self.assertEqual(record["state"], base.VIOLATION)
                self.assertTrue(any(c["check"] == "sdd-members" and c["state"] == base.VIOLATION
                                    for c in record["checks"]))
            self.assertEqual(before, snapshot(root))
            # clone 仍配置旧 hook 路径时，候选中已无 hook；普通 commit 不需要绕过参数。
            self.assertFalse((UNIT / "hooks/pre-commit").exists())
            self.assertFalse((UNIT.parent.parent / ".gitlab-ci.yml").exists())
            git(root, "config", "core.hooksPath", "mechanisms/gates/hooks")
            paths = [p.relative_to(root).as_posix() for p in root.rglob("*")
                     if p.is_file() and ".git" not in p.relative_to(root).parts]
            git(root, "add", "--", *paths)
            git(root, "commit", "-qm", "isolated violation can commit")
            self.assertEqual(cli(root, "layout").returncode, 1)

    def test_missing_bad_inputs_and_precedence(self):
        for path, value in (("rules_catalog.json", None), ("rules_catalog.json", "{"),
                            ("readme_data.json", None), ("readme_data.json", "{bad}\n")):
            with self.subTest(path=path, value=value), repo() as root:
                gen.write_all(context(root))
                write(root, "sdd/extra.md", "bad\n")
                target = root / "mechanisms/gates" / path
                target.unlink() if value is None else target.write_text(value)
                result = cli(root, "all")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)["state"], base.NOT_CHECKED)
        with repo() as root:
            write(root, ".gitignore", b"\xff")
            write(root, "sdd/extra.md", "bad\n")
            self.assertEqual(cli(root, "layout").returncode, 2)

    def test_git_unavailable_and_failure(self):
        with repo() as root:
            env = base.git_environment()
            env["PATH"] = str(root / "absent")
            result = cli(root, "all", env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Git", json.loads(result.stdout)["reason"])
            shutil.rmtree(root / ".git")
            (root / ".git").write_text("gitdir: /does-not-exist\n")
            result = cli(root, "layout")
            self.assertEqual(result.returncode, 2)
            self.assertTrue(any(c["state"] == base.NOT_CHECKED for c in json.loads(result.stdout)["checks"]))

    def test_old_arguments_and_output_contract(self):
        with repo() as root:
            for command, args in (("layout", ("--source", "index")), ("doctor", ()),
                                  ("layout", ("--write",)), ("layout", ("--source", "worktree"))):
                self.assertEqual(cli(root, command, *args).returncode, 2)
            result = cli(root, "layout")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(json.loads(result.stdout)), {"command", "state", "exit_code", "repo_root", "checks"})

    def test_tracked_attempts_after_worktree_delete_and_shallow_clone(self):
        with repo() as root, tempfile.TemporaryDirectory(prefix="hp-lint-clone-") as directory:
            paths = [p.relative_to(root).as_posix() for p in root.rglob("*")
                     if p.is_file() and ".git" not in p.relative_to(root).parts]
            git(root, "add", "--", *paths)
            git(root, "commit", "-qm", "baseline")
            write(root, "records/second.md", "second\n")
            git(root, "add", "--", "records/second.md")
            git(root, "commit", "-qm", "second")
            clone = Path(directory) / "clone"
            git(root, "clone", "--depth", "1", root.as_uri(), str(clone))
            self.assertEqual(git(clone, "rev-parse", "--is-shallow-repository").strip(), b"true")
            self.assertEqual(cli(clone, "layout").returncode, 0)
            attempt = "tasks/gov-t0/attempts/raw.txt"
            write(clone, attempt, "raw\n")
            git(clone, "add", "-f", "--", attempt)
            (clone / attempt).unlink()
            result = cli(clone, "layout")
            self.assertEqual(result.returncode, 1)
            self.assertTrue(any(f["subject"] == attempt for c in json.loads(result.stdout)["checks"]
                                for f in c["findings"]))


class GenerationTests(unittest.TestCase):
    def test_stale_source_and_idempotent_generation(self):
        with repo() as root:
            result = cli(root, "manifest", "--write")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("state", json.loads(result.stdout))
            before = snapshot(root)
            self.assertEqual(cli(root, "manifest", "--write").returncode, 0)
            self.assertEqual(before, snapshot(root))
            self.assertEqual(cli(root, "manifest").returncode, 0)
            with (root / "mechanisms/gates/root_readme_source.md").open("a") as stream:
                stream.write("新增说明。\n")
            self.assertEqual(cli(root, "manifest").returncode, 1)
            self.assertEqual(cli(root, "manifest", "--write").returncode, 0)
            self.assertEqual(cli(root, "manifest").returncode, 0)

    def test_compute_all_before_write(self):
        with repo() as root:
            gen.write_all(context(root))
            previous = (root / "mechanisms/MECHANISMS.md").read_bytes()
            write(root, "mechanisms/demo/extra.py", "pass\n")
            (root / "mechanisms/gates/readme_data.json").unlink()
            code, messages = gen.write_all(context(root))
            self.assertEqual(code, 2)
            self.assertEqual((root / "mechanisms/MECHANISMS.md").read_bytes(), previous)
            self.assertIn("未写入任何文件", messages[0])

    def test_reject_symlink_and_partial_write_failure(self):
        with repo() as root:
            outside = root / "records/outside.md"
            outside.write_text("untouched")
            (root / "README.md").unlink()
            (root / "README.md").symlink_to(outside)
            code, messages = gen.write_all(context(root))
            self.assertEqual(code, 2)
            self.assertEqual(outside.read_text(), "untouched")
            self.assertFalse((root / "mechanisms/MECHANISMS.md").exists())
            (root / "README.md").unlink()
            (root / "README.md").mkdir()
            write(root, "README.md/keep", "retained")
            data_path = root / "mechanisms/gates/readme_data.json"
            data = json.loads(data_path.read_text())
            data["top_level"]["README.md"] = {"zone": "测试", "gloss": "写入失败目标"}
            data_path.write_text(json.dumps(data, ensure_ascii=False) + "\n")
            code, messages = gen.write_all(context(root))
            self.assertEqual(code, 2)
            self.assertTrue((root / "mechanisms/MECHANISMS.md").is_file())
            self.assertTrue(any(m.startswith("已写入 mechanisms/MECHANISMS.md") for m in messages))
            self.assertIn("未完成：README.md", messages)
            self.assertEqual((root / "README.md/keep").read_text(), "retained")
            self.assertFalse(list(root.rglob(".hp-write-*")))

    def test_bad_input_formats(self):
        for value in (b"\xef\xbb\xbf# Source\n", b"# Source\r\n", b"\xff\n", b"# Source\n\n", b"# Source",
                      b"# Source\n\n<!--table:units-->\n\n<!--table:units-->\n"):
            with self.subTest(value=value), repo() as root:
                write(root, "mechanisms/gates/mechanisms_source.md", value)
                self.assertEqual(cli(root, "manifest").returncode, 2)
        for value in ('{"top_level":{},"top_level":{}}\n', '{"x":NaN}\n'):
            with self.subTest(value=value), repo() as root:
                write(root, "mechanisms/gates/readme_data.json", value)
                self.assertEqual(cli(root, "manifest").returncode, 2)

    def test_path_mapping_and_unreadable_target(self):
        with repo() as root:
            catalog = CATALOG.copy()
            catalog["generated"] = [{"path": "README.md", "source": "../external", "table_names": []}]
            write(root, "mechanisms/gates/rules_catalog.json", json.dumps(catalog) + "\n")
            self.assertEqual(cli(root, "manifest", "--write").returncode, 2)
        with repo() as root:
            gen.write_all(context(root))
            with mock.patch.object(base.Context, "read", autospec=True) as read:
                original = Path.read_bytes
                def content(ctx, path):
                    if path == "README.md":
                        raise PermissionError("simulated unreadable target")
                    return original(Path(ctx.repo_root) / path)
                read.side_effect = content
                checks = base.run_gate(manifest.GATE, context(root))
                self.assertEqual(base.aggregate_states(c.state for c in checks), base.NOT_CHECKED)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def run_selftest(repo_root):
    global CATALOG
    CATALOG = base.load_catalog(Path(repo_root) / "mechanisms/gates")
    base.profile_from_catalog(CATALOG)
    output = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    print(output.getvalue(), file=sys.stderr, end="")
    state = base.NOT_CHECKED if result.errors else (base.VIOLATION if result.failures else base.PASS)
    details = [{"check": test.id(), "state": base.NOT_CHECKED if (test, trace) in result.errors else base.VIOLATION,
                "reason": trace, "findings": []} for test, trace in result.errors + result.failures]
    from gates import emit
    return emit("selftest", state, details or [{"check": "isolated-tests", "state": base.PASS,
                                               "findings": [], "tests_run": result.testsRun}], repo_root)


if __name__ == "__main__":
    from gates import main
    sys.exit(main(["selftest", *sys.argv[1:]]))
