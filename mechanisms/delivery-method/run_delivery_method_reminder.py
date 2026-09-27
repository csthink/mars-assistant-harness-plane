#!/usr/bin/env python3
"""HarnessPlane delivery-method mechanical reminder.

This tool is deliberately a non-blocking decision aid, not a gate.  It emits
three frozen fact groups and a GREEN/RED conclusion for Human consideration:

1. spec coverage lost from the milestones task list;
2. broken dependencies or cycles in the milestones task graph;
3. in-progress or completed task records, plus review evidence, affected by
   the candidate change.

Exit codes are mechanically distinct:

* 0: GREEN
* 1: RED
* 2: SELF_FAILURE (the reminder itself could not complete)

RED never authorizes a caller to block progression.  SELF_FAILURE must remain
visible, but likewise is not a delivery gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'repo-layout'))
try:
    import history_read as history
except ImportError:
    history = None



EXIT_GREEN = 0
EXIT_RED = 1
EXIT_SELF_FAILURE = 2

SPEC_ID_PATTERN = r"(?:(?:FR|NFR)-\d{2,3}|SC-\d{1,3})"
SPEC_ITEM_RE = re.compile(rf"(?m)^\s*-\s+\*\*({SPEC_ID_PATTERN})\*\*\s*(.*)$")
SPEC_REF_RE = re.compile(rf"\b{SPEC_ID_PATTERN}\b")
TASK_ID_PATTERN = r"(?:feature|design|gov)-t\d+"
TASK_ID_RE = re.compile(rf"\b{TASK_ID_PATTERN}\b")
TASK_LINE_RE = re.compile(rf"(?m)^\s{{2}}-\s+({TASK_ID_PATTERN})(?=\s|（)(.+)$")
SPEC_MARKER = "· Spec 引用："
DEPENDENCY_MARKER = "· 依赖："
OPTIONAL_TAIL_MARKERS = ("· Supersedes：", "· WITHDRAWN (", "· WITHDRAWN in ")
# Current milestones template plus the historical withdrawal spelling.
# Only a complete tail excludes a task; this reminder is not a syntax linter.
WITHDRAWN_TAIL_RE = re.compile(
    r"· WITHDRAWN (?:in milestones\.md@r[1-9][0-9]*|\(r[1-9][0-9]*\))\s*$"
)
TASK_STATUS_RE = re.compile(r"(?mi)^>\s*Status:\s*([^\r\n]+?)\s*$")
RULING_TYPE_RE = re.compile(r"(?mi)^>\s*Type:\s*([a-z][a-z-]*)\s*$")


class ReminderFailure(RuntimeError):
    """Input, parsing, or runtime failure of the reminder itself."""


@dataclass(frozen=True)
class TaskEntry:
    task_id: str
    body: str
    spec_refs: tuple[str, ...]
    dependencies: tuple[str, ...]
    active: bool


@dataclass(frozen=True)
class Inputs:
    repo_root: Path
    spec_path: Path
    milestones_path: Path
    before_spec_source: str
    before_milestones_source: str
    before_spec_text: str
    after_spec_text: str
    before_milestones_text: str
    after_milestones_text: str


def read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReminderFailure(f"cannot read UTF-8 file {path}: {exc}") from exc


def repo_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ReminderFailure(f"candidate path is outside repo root: {path}") from exc


def git_head_text(root: Path, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"HEAD:{relative_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReminderFailure(f"cannot read HEAD:{relative_path}: {detail}")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReminderFailure(f"HEAD:{relative_path} is not UTF-8") from exc


def resolve_candidate(root: Path, explicit: str | None, choices: tuple[str, ...], label: str) -> Path:
    if explicit:
        path = Path(explicit)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            raise ReminderFailure(f"{label} candidate does not exist: {path}")
        return path.resolve()
    existing = [root / choice for choice in choices if (root / choice).is_file()]
    if len(existing) != 1:
        rendered = ", ".join(str(path) for path in existing) or "none"
        raise ReminderFailure(
            f"cannot auto-resolve {label} candidate; expected exactly one of {choices}, found {rendered}"
        )
    return existing[0].resolve()


def resolve_before(
    root: Path,
    override: str | None,
    candidate: Path,
    label: str,
) -> tuple[str, str]:
    if override:
        path = Path(override)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            raise ReminderFailure(f"{label} before snapshot does not exist: {path}")
        return str(path.resolve()), read_utf8(path)
    relative = repo_relative(candidate, root)
    return f"HEAD:{relative}", git_head_text(root, relative)


def load_inputs(args: argparse.Namespace) -> Inputs:
    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        raise ReminderFailure(f"repo root does not exist: {root}")
    spec_path = resolve_candidate(root, args.spec, ("sdd/spec.md", "spec-fused.md"), "spec")
    milestones_path = resolve_candidate(
        root,
        args.milestones,
        ("sdd/milestones.md", "milestones-fused.md"),
        "milestones",
    )
    before_spec_source, before_spec_text = resolve_before(
        root, args.before_spec, spec_path, "spec"
    )
    before_milestones_source, before_milestones_text = resolve_before(
        root, args.before_milestones, milestones_path, "milestones"
    )
    return Inputs(
        repo_root=root,
        spec_path=spec_path,
        milestones_path=milestones_path,
        before_spec_source=before_spec_source,
        before_milestones_source=before_milestones_source,
        before_spec_text=before_spec_text,
        after_spec_text=read_utf8(spec_path),
        before_milestones_text=before_milestones_text,
        after_milestones_text=read_utf8(milestones_path),
    )


def unique_map(pairs: Iterable[tuple[str, str]], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    duplicates: list[str] = []
    for identity, body in pairs:
        if identity in result:
            duplicates.append(identity)
        else:
            result[identity] = body.strip()
    if duplicates:
        raise ReminderFailure(f"duplicate {label} identities: {', '.join(sorted(set(duplicates)))}")
    if not result:
        raise ReminderFailure(f"no {label} identities found")
    return result


def parse_spec(text: str) -> dict[str, str]:
    return unique_map(((match.group(1), match.group(2)) for match in SPEC_ITEM_RE.finditer(text)), "spec item")


def parse_tasks(text: str) -> dict[str, TaskEntry]:
    raw = unique_map(((match.group(1), match.group(2)) for match in TASK_LINE_RE.finditer(text)), "task")
    tasks: dict[str, TaskEntry] = {}
    for task_id, body in raw.items():
        if SPEC_MARKER not in body:
            raise ReminderFailure(f"task {task_id} has no {SPEC_MARKER!r} field")
        if DEPENDENCY_MARKER not in body:
            raise ReminderFailure(f"task {task_id} has no {DEPENDENCY_MARKER!r} field")
        before_dependency, dependency_text = body.split(DEPENDENCY_MARKER, 1)
        if SPEC_MARKER not in before_dependency:
            raise ReminderFailure(
                f"task {task_id} has {DEPENDENCY_MARKER!r} before {SPEC_MARKER!r}"
            )
        spec_text = before_dependency.split(SPEC_MARKER, 1)[1]
        dependency_field = dependency_text
        for marker in OPTIONAL_TAIL_MARKERS:
            dependency_field = dependency_field.split(marker, 1)[0]
        dependencies = tuple(sorted(set(TASK_ID_RE.findall(dependency_field))))
        refs = tuple(sorted(set(SPEC_REF_RE.findall(spec_text))))
        active = WITHDRAWN_TAIL_RE.search(dependency_text) is None
        tasks[task_id] = TaskEntry(task_id, body, refs, dependencies, active)
    return tasks


def changed_identities(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        identity
        for identity in set(before) | set(after)
        if before.get(identity) != after.get(identity)
    )


def task_bodies(tasks: dict[str, TaskEntry]) -> dict[str, str]:
    return {task_id: entry.body for task_id, entry in tasks.items()}


def active_tasks(tasks: dict[str, TaskEntry]) -> dict[str, TaskEntry]:
    return {task_id: entry for task_id, entry in tasks.items() if entry.active}


def broken_dependencies(tasks: dict[str, TaskEntry]) -> list[dict[str, str]]:
    active = active_tasks(tasks)
    return [
        {"task_id": task_id, "missing_dependency": dependency}
        for task_id, entry in sorted(active.items())
        for dependency in entry.dependencies
        if dependency not in active
    ]


def strongly_connected_cycles(tasks: dict[str, TaskEntry]) -> list[list[str]]:
    graph = {
        task_id: tuple(dep for dep in entry.dependencies if dep in tasks and tasks[dep].active)
        for task_id, entry in active_tasks(tasks).items()
    }
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for dependency in graph[node]:
            if dependency not in indices:
                visit(dependency)
                lowlinks[node] = min(lowlinks[node], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[dependency])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            component.sort()
            if len(component) > 1 or node in graph[node]:
                components.append(component)

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def reverse_dependents(tasks: dict[str, TaskEntry], seeds: set[str]) -> set[str]:
    reverse: dict[str, set[str]] = {}
    for task_id, entry in active_tasks(tasks).items():
        for dependency in entry.dependencies:
            reverse.setdefault(dependency, set()).add(task_id)
    result = set(seeds)
    frontier = list(seeds)
    while frontier:
        current = frontier.pop()
        for dependent in sorted(reverse.get(current, set())):
            if dependent not in result:
                result.add(dependent)
                frontier.append(dependent)
    return result


def recorded_task_state(task_dir: Path) -> str | None:
    """Return only states named by frozen rule 3 using current archive carriers.

    A `done` Owner ruling is the completion authority.  A `close` or `closed`
    ruling is terminal without completion and is outside the frozen reminder's
    in-progress/completed set.  Otherwise a FINALIZED task contract denotes a
    task eligible for work and is reported as in progress.  Draft, review, and
    unstructured directories are not guessed into a state.
    """
    if not task_dir.is_dir():
        return None
    ruling_files = sorted((task_dir / "rulings").glob("*.md")) if (task_dir / "rulings").is_dir() else []
    ruling_types: set[str] = set()
    for path in ruling_files:
        text = read_utf8(path)
        match = RULING_TYPE_RE.search(text)
        if match:
            ruling_types.add(match.group(1).lower())
    if "done" in ruling_types:
        return "completed"
    if ruling_types.intersection({"close", "closed"}):
        return None
    task_contract = task_dir / f"{task_dir.name}.md"
    if not task_contract.is_file():
        return None
    status_match = TASK_STATUS_RE.search(read_utf8(task_contract))
    if status_match and re.fullmatch(r"FINALIZED(?:\s+r[1-9]\d*)?", status_match.group(1)):
        return "in_progress"
    return None


def review_evidence(repo_root: Path, task_id: str) -> list[str]:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'review-channel'))
    import review_evidence as archives
    try:
        archive=archives.configured(repo_root)
        if archive:
            boundary=re.compile(rf'(?<![A-Za-z0-9]){re.escape(task_id)}(?![A-Za-z0-9])')
            return sorted({key for key in archives.published_rounds(repo_root,archive)
                           if key.startswith('tasks/'+task_id+'/reviews/') or boundary.search(key)})
    except archives.EvidenceError as exc:raise ReminderFailure(str(exc)) from exc
    if history is None:
        raise ReminderFailure('history-unavailable: shared helper absent')
    evidence: set[str] = set()
    local_reviews = repo_root / "tasks" / task_id / "reviews"
    if local_reviews.is_dir():
        for path in local_reviews.rglob("*"):
            if path.is_file():
                evidence.add(path.relative_to(repo_root).as_posix())
    boundary = re.compile(rf"(?<![A-Za-z0-9]){re.escape(task_id)}(?!\d)")
    for root in (repo_root / "reviews", repo_root / "docs" / "reviews"):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and boundary.search(path.relative_to(root).as_posix()):
                evidence.add(path.relative_to(repo_root).as_posix())
    try:
        for prefix in ('tasks/'+task_id+'/reviews/', 'reviews/', 'docs/reviews/'):
            for item in history.working_history(repo_root, prefix):
                relative = item['path'][len(prefix):]
                if prefix.startswith('tasks/') or boundary.search(relative):
                    current = repo_root/item['path']
                    if current.exists() and hashlib.sha256(current.read_bytes()).hexdigest() != item['sha256']:
                        raise ReminderFailure('history-integrity: conflicting review evidence '+item['path'])
                    evidence.add(item['path'])
    except history.HistoryReadError as exc:
        raise ReminderFailure(exc.code+': '+exc.message)
    return sorted(evidence)


def affected_surface(
    repo_root: Path,
    changed_spec: set[str],
    changed_tasks: set[str],
    before_tasks: dict[str, TaskEntry],
    after_tasks: dict[str, TaskEntry],
) -> list[dict[str, object]]:
    direct = set(changed_tasks)
    reasons: dict[str, set[str]] = {task_id: {"task_definition_changed"} for task_id in changed_tasks}
    for label, tasks in (("before", before_tasks), ("after", after_tasks)):
        for task_id, entry in tasks.items():
            intersect = changed_spec.intersection(entry.spec_refs)
            if intersect:
                direct.add(task_id)
                reasons.setdefault(task_id, set()).update(
                    f"references_changed_spec_item:{identity}" for identity in intersect
                )
    impacted = reverse_dependents(before_tasks, direct) | reverse_dependents(after_tasks, direct)
    for task_id in impacted - direct:
        reasons.setdefault(task_id, set()).add("depends_on_affected_task")

    records: list[dict[str, object]] = []
    for task_id in sorted(impacted):
        state = recorded_task_state(repo_root / "tasks" / task_id)
        if state is None:
            continue
        records.append(
            {
                "task_id": task_id,
                "state": state,
                "reasons": sorted(reasons.get(task_id, {"depends_on_affected_task"})),
                "review_evidence": review_evidence(repo_root, task_id),
            }
        )
    return records


def build_report(inputs: Inputs) -> dict[str, object]:
    before_spec = parse_spec(inputs.before_spec_text)
    after_spec = parse_spec(inputs.after_spec_text)
    before_tasks = parse_tasks(inputs.before_milestones_text)
    after_tasks = parse_tasks(inputs.after_milestones_text)

    before_active = active_tasks(before_tasks)
    after_active = active_tasks(after_tasks)
    referenced_before = {ref for task in before_active.values() for ref in task.spec_refs}
    referenced_after = {ref for task in after_active.values() for ref in task.spec_refs}
    uncovered_before = set(before_spec) - referenced_before
    uncovered_after = set(after_spec) - referenced_after
    newly_uncovered = uncovered_after - uncovered_before

    broken = broken_dependencies(after_tasks)
    cycles = strongly_connected_cycles(after_tasks)
    changed_spec = set(changed_identities(before_spec, after_spec))
    changed_tasks = set(changed_identities(task_bodies(before_tasks), task_bodies(after_tasks)))
    affected = affected_surface(
        inputs.repo_root,
        changed_spec,
        changed_tasks,
        before_tasks,
        after_tasks,
    )

    red_reasons: list[str] = []
    if newly_uncovered:
        red_reasons.append("new_spec_coverage_loss")
    if broken:
        red_reasons.append("broken_task_dependency")
    if cycles:
        red_reasons.append("task_dependency_cycle")
    if affected:
        red_reasons.append("recorded_task_or_evidence_affected")

    return {
        "tool": "HarnessPlane delivery-method mechanical reminder",
        "schema_version": 1,
        "non_blocking": True,
        "conclusion": "RED" if red_reasons else "GREEN",
        "inputs": {
            "repo_root": str(inputs.repo_root),
            "before_spec": inputs.before_spec_source,
            "after_spec": repo_relative(inputs.spec_path, inputs.repo_root),
            "before_milestones": inputs.before_milestones_source,
            "after_milestones": repo_relative(inputs.milestones_path, inputs.repo_root),
        },
        "facts": {
            "coverage_loss": {
                "spec_items_after": sorted(after_spec),
                "referenced_after": sorted(referenced_after),
                "uncovered_before": sorted(uncovered_before),
                "uncovered_after": sorted(uncovered_after),
                "newly_uncovered": sorted(newly_uncovered),
            },
            "dependency_reachability": {
                "active_tasks_after": sorted(after_active),
                "broken_dependencies": broken,
                "cycles": cycles,
            },
            "affected_surface": {
                "changed_spec_items": sorted(changed_spec),
                "changed_milestone_tasks": sorted(changed_tasks),
                "impacted_recorded_tasks": affected,
            },
        },
        "red_reasons": red_reasons,
    }


def failure_report(message: str) -> dict[str, object]:
    return {
        "tool": "HarnessPlane delivery-method mechanical reminder",
        "schema_version": 1,
        "non_blocking": True,
        "conclusion": "SELF_FAILURE",
        "error": message,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Emit the three frozen mechanical-reminder fact groups. "
            "This is a non-blocking Human decision aid, never a CI gate."
        )
    )
    result.add_argument("--repo-root", default=".", help="repository root, default: current directory")
    result.add_argument("--spec", help="candidate spec path relative to repo root")
    result.add_argument("--milestones", help="candidate milestones path relative to repo root")
    result.add_argument("--before-spec", help="explicit pre-change spec snapshot; default: HEAD:<candidate>")
    result.add_argument(
        "--before-milestones",
        help="explicit pre-change milestones snapshot; default: HEAD:<candidate>",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        report = build_report(load_inputs(args))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_RED if report["conclusion"] == "RED" else EXIT_GREEN
    except ReminderFailure as exc:
        print(json.dumps(failure_report(str(exc)), ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_SELF_FAILURE
    except Exception as exc:  # Defensive visibility for unexpected tool failures.
        print(
            json.dumps(
                failure_report(f"unexpected {type(exc).__name__}: {exc}"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_SELF_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
