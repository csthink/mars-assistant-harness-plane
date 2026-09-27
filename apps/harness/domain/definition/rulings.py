"""review-skip, finalization and finding-disposition rulings: exact bytes and the two-phase write.

Phase 1 (inside a domain transaction, elsewhere): the ruling number, every byte and its SHA-256 are
fixed and the ruling is recorded `registered`. Phase 2 (this module, outside any transaction): the
bytes are written to the task worktree and committed on the task branch, only when the task record
directory has no uncommitted change and the branch head equals the head read at registration.
Phase 3 records `written`. A retry first reads what the branch already carries: equal bytes are
completed, absence is written, anything else is `indeterminate` and stops. Nothing is overwritten or
deleted (Definition AC-08).
"""
import hashlib
from pathlib import Path
import re
import subprocess

from domain.acceptance.gitrepo import environment
from domain.definition.candidate import load_validator
from domain.definition.results import (
    RULING_WRITE_INDETERMINATE, RULING_WRITE_PRECONDITION_FAILED, TEMPLATE_STRUCTURE_INVALID, DefinitionRejection,
)

COMMITTER = {"GIT_AUTHOR_NAME": "HarnessPlane Domain", "GIT_AUTHOR_EMAIL": "harness-plane-domain@invalid",
             "GIT_COMMITTER_NAME": "HarnessPlane Domain", "GIT_COMMITTER_EMAIL": "harness-plane-domain@invalid"}
RE_RULING = re.compile(r"^RU-(\d{2,})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
SLUGS = {"review-skip": "definition-review-skip", "finalization": "definition-finalization",
         "finding-disposition": "definition-finding-disposition"}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def object_line(candidate):
    return f"{candidate['path']} · {candidate['bytes']} bytes · SHA-256 {candidate['sha256']}"


def render(number, date, kind, obj, basis, decision, body):
    """Six header lines, one blank line, then free text (ruling template)."""
    text = (f"> Ruling: RU-{number:02d}\n> Date: {date}\n> Type: {kind}\n> Object: {obj}\n> Basis: {basis}\n"
            f"> Decision: {decision}\n\n{body.rstrip()}\n")
    return text.encode("utf-8")


def filename(number, kind):
    return f"RU-{number:02d}-{SLUGS[kind]}.md"


def lint(repository_root, path, raw):
    module, identity = load_validator(repository_root)
    record = module.lint_file("ruling", path, data=raw)
    if record.get("state") != "PASS":
        raise DefinitionRejection(TEMPLATE_STRUCTURE_INVALID, "generated ruling fails the ruling template",
                                  path=path, checks=[c for c in record.get("checks", []) if c.get("state") != "PASS"],
                                  validator=identity)
    return identity


def _git(worktree, *args, extra_env=None):
    env = environment(worktree)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["git", "-C", str(worktree), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


def existing_numbers(worktree, task_id, commit):
    out = _git(worktree, "ls-tree", "--name-only", f"{commit}:tasks/{task_id}/rulings")
    if out.returncode != 0:
        return []
    return [int(m.group(1)) for m in (RE_RULING.match(n) for n in out.stdout.decode().split()) if m]


def branch_head(worktree, branch):
    head = _git(worktree, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch + "^{commit}")
    return head.stdout.decode().strip() if head.returncode == 0 else None


def write(worktree, branch, base_commit, task_id, items, message):
    """Phase 2. items = [{path, bytes, sha256, content}] fixed at registration. Returns the commit."""
    worktree = Path(worktree)
    current = branch_head(worktree, branch)
    carried = {}
    for item in items:
        shown = _git(worktree, "show", f"refs/heads/{branch}:{item['path']}")
        carried[item["path"]] = shown.stdout if shown.returncode == 0 else None
    if all(carried[i["path"]] is not None and sha256(carried[i["path"]]) == i["sha256"] for i in items):
        return dict(state="written", commit=current, replay=True)
    if any(carried[i["path"]] is not None and sha256(carried[i["path"]]) != i["sha256"] for i in items):
        raise DefinitionRejection(RULING_WRITE_INDETERMINATE, "the task branch already carries different bytes at a ruling path",
                                  paths=[i["path"] for i in items if carried[i["path"]] is not None])
    if current != base_commit:
        raise DefinitionRejection(RULING_WRITE_INDETERMINATE, "the task branch head moved after registration",
                                  expected=base_commit, actual=current)
    symbolic = _git(worktree, "symbolic-ref", "--quiet", "HEAD").stdout.decode().strip()
    if symbolic != "refs/heads/" + branch:
        raise DefinitionRejection(RULING_WRITE_PRECONDITION_FAILED, "the task worktree does not have the task branch checked out",
                                  checkedOut=symbolic, branch=branch)
    dirty = _git(worktree, "status", "--porcelain", "--untracked-files=all", "--", f"tasks/{task_id}/")
    if dirty.returncode != 0 or dirty.stdout.strip():
        raise DefinitionRejection(RULING_WRITE_PRECONDITION_FAILED, "the task record directory has uncommitted changes",
                                  status=dirty.stdout.decode(errors="replace")[:2048])
    for item in items:
        target = worktree / item["path"]
        if target.exists():
            raise DefinitionRejection(RULING_WRITE_INDETERMINATE, "an untracked file is already at a ruling path", path=item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as handle:
            handle.write(item["content"].encode("utf-8"))
    added = _git(worktree, "add", "--", *[i["path"] for i in items])
    if added.returncode != 0:
        raise DefinitionRejection(RULING_WRITE_INDETERMINATE, "git add failed after writing the ruling files",
                                  stderr=added.stderr.decode(errors="replace")[:1024])
    committed = _git(worktree, "commit", "-q", "-m", message, "--", *[i["path"] for i in items], extra_env=COMMITTER)
    if committed.returncode != 0:
        raise DefinitionRejection(RULING_WRITE_INDETERMINATE, "git commit of the ruling files failed",
                                  stderr=committed.stderr.decode(errors="replace")[:1024])
    return dict(state="written", commit=branch_head(worktree, branch), replay=False)
