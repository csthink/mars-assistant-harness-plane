#!/usr/bin/env python3
"""Offline positive, red, and self-failure fixtures for the reminder tool."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def resolve_tool(selftest_path: Path | None = None) -> Path:
    selftest = (selftest_path or Path(__file__)).resolve()
    exact = selftest.with_name("run_delivery_method_reminder.py")
    if exact.is_file():
        return exact
    candidates = sorted(
        path
        for path in selftest.parent.glob("*run_delivery_method_reminder.py")
        if path.resolve() != selftest
    )
    if len(candidates) != 1:
        raise RuntimeError(
            "cannot resolve reminder tool beside selftest; "
            f"expected one candidate, found {[path.name for path in candidates]}"
        )
    return candidates[0]


TOOL = resolve_tool()

SPEC_BASE = """# Spec

## Requirements

- **FR-01** First requirement.
- **FR-02** Second requirement.
- **NFR-01** Reliability requirement.
- **SC-1** Success scenario.
"""

MILESTONES_BASE = """# Milestones

## Tasks

  - feature-t0（identity note） Founding task · 类型：后端 · Spec 引用：spec.md@r1 FR-01 · 依赖：无
  - gov-t1 First task · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01、spec.md@r1 NFR-01 · 依赖：无
  - gov-t2 Second task · 类型：治理机制 · Spec 引用：spec.md@r1 FR-02 · 依赖：gov-t1
  - feature-t1 Final task · 类型：后端 · Spec 引用：spec.md@r1 SC-1 · 依赖：gov-t2
"""


class SelftestFailure(AssertionError):
    pass


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def invoke(
    root: Path,
    expected_exit: int,
    *,
    before_spec: Path | None = None,
    before_milestones: Path | None = None,
    explicit_candidates: bool = True,
) -> dict:
    command = [
        sys.executable,
        str(TOOL),
        "--repo-root",
        str(root),
    ]
    if explicit_candidates:
        command.extend(["--spec", "sdd/spec.md", "--milestones", "sdd/milestones.md"])
    if before_spec is not None:
        command.extend(["--before-spec", str(before_spec)])
    if before_milestones is not None:
        command.extend(["--before-milestones", str(before_milestones)])
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != expected_exit:
        raise SelftestFailure(
            f"expected exit {expected_exit}, got {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    try:
        report = json.loads(result.stdout)
        expect(report["non_blocking"] is True, "all conclusions remain non-blocking")
        expect(report["schema_version"] == 1, "report schema preserved")
        return report
    except json.JSONDecodeError as exc:
        raise SelftestFailure(f"tool output is not JSON: {result.stdout!r}") from exc


def fixture(root: Path) -> tuple[Path, Path]:
    before_spec = root / "before-spec.md"
    before_milestones = root / "before-milestones.md"
    write(before_spec, SPEC_BASE)
    write(before_milestones, MILESTONES_BASE)
    write(root / "sdd/spec.md", SPEC_BASE)
    write(root / "sdd/milestones.md", MILESTONES_BASE)
    return before_spec, before_milestones


def commit_baseline(root: Path, paths: tuple[str, ...]) -> None:
    # The reminder reads the clone configuration and HEAD before it reports affected
    # surface facts, so these fixtures need a repository with a commit. The identity is
    # local, and the commit disables signing and hooks so global Git configuration
    # cannot make the fixture fail.
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "selftest@example.invalid"],
        ["git", "config", "user.name", "Reminder Selftest"],
        ["git", "add", *paths],
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "baseline"],
    ):
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise SelftestFailure(f"git fixture command failed: {command!r}: {result.stderr!r}")


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise SelftestFailure(label)


def case_green(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
    expect(report["conclusion"] == "GREEN", "green fixture conclusion")
    expect(report["red_reasons"] == [], "green fixture red reasons")
    expect(report["facts"]["coverage_loss"]["newly_uncovered"] == [], "green coverage")
    expect(report["facts"]["dependency_reachability"]["cycles"] == [], "green cycles")
    expect(
        "feature-t0" in report["facts"]["dependency_reachability"]["active_tasks_after"],
        "task identity followed by a full-width parenthesis",
    )


def case_coverage_red(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    changed = MILESTONES_BASE.replace("spec.md@r1 SC-1", "spec.md@r1 FR-01")
    write(root / "sdd/milestones.md", changed)
    report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
    expect(report["conclusion"] == "RED", "coverage red conclusion")
    expect(
        report["facts"]["coverage_loss"]["newly_uncovered"] == ["SC-1"],
        "coverage red identifies single-digit SC-1",
    )
    expect("new_spec_coverage_loss" in report["red_reasons"], "coverage red reason")


def case_prose_reference_not_coverage(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    changed = MILESTONES_BASE.replace(
        "feature-t1 Final task · 类型：后端 · Spec 引用：spec.md@r1 SC-1 · 依赖：gov-t2",
        "feature-t1 Final task mentions SC-1 in prose · 类型：后端 · Spec 引用：spec.md@r1 FR-01 · 依赖：gov-t2",
    )
    write(root / "sdd/milestones.md", changed)
    report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
    expect(
        report["facts"]["coverage_loss"]["newly_uncovered"] == ["SC-1"],
        "prose reference does not count as Spec field coverage",
    )


def case_preexisting_uncovered_green(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    uncovered_spec = SPEC_BASE + "- **FR-03** Pre-existing uncovered requirement.\n"
    write(before_spec, uncovered_spec)
    write(root / "sdd/spec.md", uncovered_spec)
    report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
    coverage = report["facts"]["coverage_loss"]
    expect(coverage["uncovered_before"] == ["FR-03"], "pre-existing uncovered before")
    expect(coverage["uncovered_after"] == ["FR-03"], "pre-existing uncovered after")
    expect(coverage["newly_uncovered"] == [], "pre-existing uncovered remains green")


def case_graph_red(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    changed = MILESTONES_BASE.replace(
        "gov-t1 First task · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01、spec.md@r1 NFR-01 · 依赖：无",
        "gov-t1 First task · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01、spec.md@r1 NFR-01 · 依赖：gov-t2",
    )
    changed = changed.replace(
        "feature-t1 Final task · 类型：后端 · Spec 引用：spec.md@r1 SC-1 · 依赖：gov-t2",
        "feature-t1 Final task · 类型：后端 · Spec 引用：spec.md@r1 SC-1 · 依赖：gov-t99",
    )
    write(root / "sdd/milestones.md", changed)
    report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
    graph = report["facts"]["dependency_reachability"]
    expect(graph["cycles"] == [["gov-t1", "gov-t2"]], "graph cycle identified")
    expect(
        graph["broken_dependencies"]
        == [{"missing_dependency": "gov-t99", "task_id": "feature-t1"}],
        "broken dependency identified",
    )


def case_self_loop_and_three_node_cycle(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    changed = MILESTONES_BASE.replace(
        "feature-t0（identity note） Founding task · 类型：后端 · Spec 引用：spec.md@r1 FR-01 · 依赖：无",
        "feature-t0（identity note） Founding task · 类型：后端 · Spec 引用：spec.md@r1 FR-01 · 依赖：feature-t0",
    )
    changed = changed.replace(
        "gov-t1 First task · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01、spec.md@r1 NFR-01 · 依赖：无",
        "gov-t1 First task · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01、spec.md@r1 NFR-01 · 依赖：feature-t1",
    )
    write(root / "sdd/milestones.md", changed)
    report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
    expect(
        report["facts"]["dependency_reachability"]["cycles"]
        == [["feature-t0"], ["feature-t1", "gov-t1", "gov-t2"]],
        "self-loop and three-node cycle identified",
    )


def case_dependency_field_excludes_supersedes(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    changed = MILESTONES_BASE.replace(
        "feature-t1 Final task · 类型：后端 · Spec 引用：spec.md@r1 SC-1 · 依赖：gov-t2",
        "feature-t1 Final task · 类型：后端 · Spec 引用：spec.md@r1 SC-1 · 依赖：gov-t2 · Supersedes：gov-t99",
    )
    write(before_milestones, changed)
    write(root / "sdd/milestones.md", changed)
    report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
    expect(
        report["facts"]["dependency_reachability"]["broken_dependencies"] == [],
        "Supersedes task ID is not parsed as a dependency",
    )


def case_withdrawal_exact_tail_only(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    incidental = MILESTONES_BASE.replace(
        "gov-t1 First task",
        "gov-t1 First task discusses · WITHDRAWN (r2) and · WITHDRAWN in milestones.md@r2 and 已关闭 markers",
    )
    write(before_milestones, incidental)
    write(root / "sdd/milestones.md", incidental)
    report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
    expect(
        "gov-t1" in report["facts"]["dependency_reachability"]["active_tasks_after"],
        "incidental withdrawal words do not deactivate task",
    )
    for tail in (
        " · WITHDRAWN (r2)",
        " · WITHDRAWN in milestones.md@r1",
        " · WITHDRAWN in milestones.md@r12   ",
        " · Supersedes：gov-t99 · WITHDRAWN (r12)",
        " · Supersedes：gov-t99 · WITHDRAWN in milestones.md@r12",
    ):
        withdrawn = incidental.replace("· 依赖：gov-t2", "· 依赖：gov-t2" + tail)
        write(root / "sdd/milestones.md", withdrawn)
        report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
        expect(
            report["facts"]["dependency_reachability"]["active_tasks_after"]
            == ["feature-t0", "gov-t1", "gov-t2"],
            f"only exact withdrawal tail deactivates task: {tail}",
        )
        expect(
            report["facts"]["coverage_loss"]["newly_uncovered"] == ["SC-1"],
            f"withdrawn task no longer covers SC-1: {tail}",
        )


def case_withdrawn_baseline(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    for tail in (" · WITHDRAWN (r2)", " · WITHDRAWN in milestones.md@r2"):
        withdrawn = MILESTONES_BASE.replace("· 依赖：gov-t2", "· 依赖：gov-t2" + tail)
        write(before_milestones, withdrawn)
        write(root / "sdd/milestones.md", withdrawn)
        report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
        coverage = report["facts"]["coverage_loss"]
        expect(coverage["uncovered_before"] == ["SC-1"], "withdrawn baseline excludes coverage")
        expect(coverage["uncovered_after"] == ["SC-1"], "unchanged withdrawal excludes coverage")
        expect(coverage["newly_uncovered"] == [], "existing withdrawal is not new coverage loss")
        expect(report["facts"]["affected_surface"]["changed_milestone_tasks"] == [], "unchanged task")


def case_withdrawal_graph_and_evidence(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    commit_baseline(root, ("sdd/spec.md", "sdd/milestones.md"))
    cyclic = MILESTONES_BASE.replace("NFR-01 · 依赖：无", "NFR-01 · 依赖：gov-t2")
    write(before_milestones, cyclic)
    write(root / "tasks/gov-t1/rulings/RU-10-done.md", "> Type: done\n")
    write(root / "tasks/gov-t1/reviews/r1/verdict.md", "review evidence\n")
    write(root / "tasks/gov-t2/gov-t2.md", "> Status: FINALIZED r1\n")
    write(root / "tasks/feature-t1/feature-t1.md", "> Status: FINALIZED r1\n")
    reports = []
    for tail in (" · WITHDRAWN (r2)", " · WITHDRAWN in milestones.md@r2"):
        changed = cyclic.replace("NFR-01 · 依赖：gov-t2", "NFR-01 · 依赖：gov-t2" + tail)
        write(root / "sdd/milestones.md", changed)
        report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
        graph = report["facts"]["dependency_reachability"]
        expect(graph["active_tasks_after"] == ["feature-t0", "feature-t1", "gov-t2"], "withdrawn graph node excluded")
        expect(graph["cycles"] == [], "withdrawn node no longer forms a cycle")
        expect(graph["broken_dependencies"] == [{"task_id": "gov-t2", "missing_dependency": "gov-t1"}], "dependent on withdrawn node is broken")
        expect(report["facts"]["coverage_loss"]["newly_uncovered"] == ["NFR-01"], "withdrawn coverage loss")
        affected = report["facts"]["affected_surface"]["impacted_recorded_tasks"]
        expect([row["task_id"] for row in affected] == ["feature-t1", "gov-t1", "gov-t2"], "before and after dependent closure preserved")
        expect([row["state"] for row in affected] == ["in_progress", "completed", "in_progress"], "withdrawal does not erase recorded states")
        expect(affected[1]["review_evidence"] == ["tasks/gov-t1/reviews/r1/verdict.md"], "withdrawal does not hide completed review evidence")
        expect(affected[1]["reasons"] == ["task_definition_changed"], "withdrawal change reason")
        expect(affected[0]["reasons"] == ["depends_on_affected_task"], "transitive impact reason")
        expect(report["red_reasons"] == ["new_spec_coverage_loss", "broken_task_dependency", "recorded_task_or_evidence_affected"], "all affected fact groups reported")
        reports.append(report)
    expect(reports[0] == reports[1], "old and current withdrawal produce identical reports")


def case_invalid_withdrawal_tails(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    # The reminder is not a full milestones linter. Invalid markers must not
    # silently remove tasks from coverage and dependency calculations.
    for tail in (
        " · WITHDRAWN (r0)",
        " · WITHDRAWN (r01)",
        " · WITHDRAWN (r1٢)",
        " · WITHDRAWN (r2) extra",
        " · WITHDRAWN (r2",
        " · WITHDRAWN in milestones.md@r0",
        " · WITHDRAWN in milestones.md@r01",
        " · WITHDRAWN in milestones.md@r1٢",
        " · WITHDRAWN in milestones.md@r",
        " · WITHDRAWN in milestones.md@r2 extra",
        " · WITHDRAWN in milestonesXmd@r2",
        " · WITHDRAWN in other.md@r2",
        " · WITHDRAWN in milestones.md@r2 · Supersedes：gov-t99",
        " WITHDRAWN in milestones.md@r2",
        " · withdrawn in milestones.md@r2",
    ):
        changed = MILESTONES_BASE.replace("· 依赖：gov-t2", "· 依赖：gov-t2" + tail)
        write(before_milestones, changed)
        write(root / "sdd/milestones.md", changed)
        report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
        expect(
            report["facts"]["dependency_reachability"]["active_tasks_after"]
            == ["feature-t0", "feature-t1", "gov-t1", "gov-t2"],
            f"invalid tail does not silently deactivate: {tail}",
        )
        expect(report["facts"]["coverage_loss"]["uncovered_after"] == [], "invalid tail retains coverage")


def case_withdrawal_missing_required_field(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    for tail in (" · WITHDRAWN (r2)", " · WITHDRAWN in milestones.md@r2"):
        for marker in ("· Spec 引用：", "· 依赖："):
            changed = MILESTONES_BASE.replace("· 依赖：gov-t2", "· 依赖：gov-t2" + tail)
            changed = "\n".join(
                line.replace(marker, "· missing：", 1) if "feature-t1 Final task" in line else line
                for line in changed.splitlines()
            ) + "\n"
            write(root / "sdd/milestones.md", changed)
            report = invoke(root, 2, before_spec=before_spec, before_milestones=before_milestones)
            expect(report["conclusion"] == "SELF_FAILURE", "withdrawal does not suppress missing-field failure")
            expect(marker in report["error"], "missing-field error remains specific")


def case_affected_surface_red(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    commit_baseline(root, ("sdd/spec.md", "sdd/milestones.md"))
    changed_spec = SPEC_BASE.replace("First requirement.", "First requirement changed.")
    write(root / "sdd/spec.md", changed_spec)
    write(root / "tasks/gov-t1/gov-t1.md", "> Status: FINALIZED r1\n")
    write(root / "tasks/gov-t1/rulings/RU-10-done.md", "> Type: done\n")
    write(root / "tasks/gov-t1/reviews/r1/verdict.md", "review evidence\n")
    write(root / "tasks/gov-t2/gov-t2.md", "> Status: FINALIZED r1\n")
    write(root / "tasks/feature-t1/feature-t1.md", "> Status: FINALIZED r1\n")
    write(root / "tasks/design-t9/design-t9.md", "> Status: DRAFT\n")
    write(root / "tasks/design-t9/notes.md", "unstructured work\n")
    report = invoke(root, 1, before_spec=before_spec, before_milestones=before_milestones)
    affected = report["facts"]["affected_surface"]["impacted_recorded_tasks"]
    expect(
        [row["task_id"] for row in affected] == ["feature-t1", "gov-t1", "gov-t2"],
        "affected reverse-dependency closure through an intermediate task",
    )
    expect(affected[0]["state"] == "in_progress", "transitive in-progress state")
    expect(affected[1]["state"] == "completed", "completed state")
    expect(affected[2]["state"] == "in_progress", "in-progress state")
    expect(
        affected[1]["review_evidence"] == ["tasks/gov-t1/reviews/r1/verdict.md"],
        "review evidence listed",
    )


def case_recorded_state_carriers(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    changed_spec = SPEC_BASE.replace("First requirement.", "First requirement changed.")
    write(root / "sdd/spec.md", changed_spec)
    write(root / "tasks/gov-t1/gov-t1.md", "> Status: DRAFT\n")
    write(root / "tasks/gov-t1/notes.md", "non-empty directory\n")
    write(root / "tasks/gov-t2/gov-t2.md", "> Status: FINALIZED r1\n")
    write(root / "tasks/gov-t2/rulings/RU-20-close.md", "> Type: close\n")
    report = invoke(root, 0, before_spec=before_spec, before_milestones=before_milestones)
    expect(
        report["facts"]["affected_surface"]["impacted_recorded_tasks"] == [],
        "draft and closed tasks are not guessed into in-progress/completed set",
    )


def case_self_failure(root: Path) -> None:
    before_spec, before_milestones = fixture(root)
    malformed = MILESTONES_BASE + MILESTONES_BASE.splitlines()[4] + "\n"
    write(root / "sdd/milestones.md", malformed)
    report = invoke(root, 2, before_spec=before_spec, before_milestones=before_milestones)
    expect(report["conclusion"] == "SELF_FAILURE", "self failure conclusion")
    expect("duplicate task identities" in report["error"], "self failure detail")


def case_default_head_baseline(root: Path) -> None:
    fixture(root)
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "selftest@example.invalid"],
        ["git", "config", "user.name", "Reminder Selftest"],
        ["git", "add", "sdd/spec.md", "sdd/milestones.md"],
        ["git", "commit", "-q", "-m", "baseline"],
    ):
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise SelftestFailure(f"git fixture command failed: {command!r}: {result.stderr!r}")
    report = invoke(root, 0)
    expect(report["inputs"]["before_spec"] == "HEAD:sdd/spec.md", "default HEAD spec")
    expect(report["inputs"]["before_milestones"] == "HEAD:sdd/milestones.md", "default HEAD milestones")


def case_root_fused_auto_resolution(root: Path) -> None:
    write(root / "spec-fused.md", SPEC_BASE)
    write(root / "milestones-fused.md", MILESTONES_BASE)
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "selftest@example.invalid"],
        ["git", "config", "user.name", "Reminder Selftest"],
        ["git", "add", "spec-fused.md", "milestones-fused.md"],
        ["git", "commit", "-q", "-m", "baseline"],
    ):
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise SelftestFailure(f"git fixture command failed: {command!r}: {result.stderr!r}")
    report = invoke(root, 0, explicit_candidates=False)
    expect(report["inputs"]["after_spec"] == "spec-fused.md", "root fused spec auto-resolution")
    expect(
        report["inputs"]["after_milestones"] == "milestones-fused.md",
        "root fused milestones auto-resolution",
    )


def case_bundle_prefixed_tool_resolution(root: Path) -> None:
    selftest = root / "candidate--run_delivery_method_reminder_selftest.py"
    tool = root / "candidate--run_delivery_method_reminder.py"
    write(selftest, "selftest placeholder\n")
    write(tool, "tool placeholder\n")
    expect(
        resolve_tool(selftest).resolve() == tool.resolve(),
        "bundle-prefixed tool filename resolves uniquely",
    )


def main() -> int:
    cases = (
        ("green", case_green),
        ("coverage-red", case_coverage_red),
        ("prose-reference-not-coverage", case_prose_reference_not_coverage),
        ("preexisting-uncovered-green", case_preexisting_uncovered_green),
        ("graph-red", case_graph_red),
        ("self-loop-three-node-cycle", case_self_loop_and_three_node_cycle),
        ("dependency-field-excludes-supersedes", case_dependency_field_excludes_supersedes),
        ("withdrawal-exact-tail-only", case_withdrawal_exact_tail_only),
        ("withdrawn-baseline", case_withdrawn_baseline),
        ("withdrawal-graph-and-evidence", case_withdrawal_graph_and_evidence),
        ("invalid-withdrawal-tails", case_invalid_withdrawal_tails),
        ("withdrawal-missing-required-field", case_withdrawal_missing_required_field),
        ("affected-surface-red", case_affected_surface_red),
        ("recorded-state-carriers", case_recorded_state_carriers),
        ("self-failure", case_self_failure),
        ("default-head-baseline", case_default_head_baseline),
        ("root-fused-auto-resolution", case_root_fused_auto_resolution),
        ("bundle-prefixed-tool-resolution", case_bundle_prefixed_tool_resolution),
    )
    failures: list[str] = []
    for name, case in cases:
        with tempfile.TemporaryDirectory(prefix=f"delivery-reminder-{name}-") as directory:
            try:
                case(Path(directory))
                print(f"PASS {name}")
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"FAIL {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    if failures:
        print(f"delivery-method reminder selftest: FAIL ({len(failures)} failures)", file=sys.stderr)
        return 1
    print(f"delivery-method reminder selftest: PASS ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
