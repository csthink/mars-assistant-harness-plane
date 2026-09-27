"""Terminal facts, dependency satisfaction and the bounded in-flight count (spec FR-32; design §依赖、授权与并发容量).

A single read rule: a task is terminal when the domain record carries a terminal slot, or when the
source revision tree holds a ruling with header Type done / close (D-09 item 3 manual-period equivalent).
Only later tasks write terminal slots; this module never writes.
"""
import re

from domain.acceptance.gitrepo import GitAbsent

RE_TYPE = re.compile(r"^> Type: (finalization|review-skip|finding-disposition|close|done)$")
DEFAULT_CONCURRENCY_LIMIT = 1

def ruling_types(repo, commit, task_id):
    """Header Type values of tasks/<id>/rulings/*.md at the commit; missing directory yields []."""
    kinds = []
    for name in repo.ls_tree(commit, f"tasks/{task_id}/rulings"):
        if not name.endswith(".md"):
            continue
        try:
            raw = repo.read(commit, f"tasks/{task_id}/rulings/{name}")
        except GitAbsent:
            continue
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if len(lines) >= 3:
            m = RE_TYPE.match(lines[2])
            if m:
                kinds.append(m.group(1))
    return kinds

def terminal_fact(state, repo, commit, task_id):
    """Return 'published' / 'closed' / 'done' / 'close' or None."""
    record = state.get("tasks", {}).get(task_id)
    if record and record.get("terminal"):
        return record["terminal"]["kind"]
    kinds = ruling_types(repo, commit, task_id)
    if "done" in kinds:
        return "done"
    if "close" in kinds:
        return "close"
    return None

def dependency_satisfied(fact):
    return fact in ("published", "done")

def unmet_dependencies(state, repo, commit, dependencies):
    return [d for d in dependencies if not dependency_satisfied(terminal_fact(state, repo, commit, d))]

def concurrency_limit(state):
    value = state.get("configuration", {}).get("concurrencyLimit")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else DEFAULT_CONCURRENCY_LIMIT

def in_flight(state, repo, commit):
    """Accepted tasks without a terminal fact plus claimed-but-unaccepted operations."""
    tasks = [t for t in state.get("tasks", {}) if terminal_fact(state, repo, commit, t) is None]
    claimed = [k for k, c in state.get("claims", {}).items() if c.get("state") == "claimed"]
    return dict(count=len(tasks) + len(claimed), tasks=tasks, claimed=claimed)
