"""Read-only facts about a task's bound branch and worktree (D-03 §5, spec FR-22).

The Task Branch identity is fixed at acceptance; its HEAD moves with candidates. Evidence binds to the
commit an attempt produced, never to the moving HEAD. Nothing here writes to the repository: reading
the worktree is the input to dispatch baselines, candidate checks and recovery assessment.
"""
import hashlib
import os
from pathlib import Path
import subprocess

from domain.acceptance.gitrepo import without_repository_locating
from domain.implement_verify.results import INDETERMINATE, WORKTREE_BINDING_MISMATCH, ImplementVerifyRejection

ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}


def git(path, *args, check=True):
    result = subprocess.run(["git", "-C", str(path), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**without_repository_locating(os.environ), **ENV,
                                 "GIT_CEILING_DIRECTORIES": str(Path(path).parent)})
    if check and result.returncode:
        raise ImplementVerifyRejection(INDETERMINATE, "git could not read the task worktree",
                                       argv=list(args), stderr=result.stderr.decode(errors="replace")[:2048])
    return result


def text(path, *args):
    return git(path, *args).stdout.decode().strip()


def bound(task):
    """Branch and worktree bound at acceptance; the worktree must still be that branch's checkout."""
    path = Path(task["worktree"])
    if not path.is_dir():
        raise ImplementVerifyRejection(WORKTREE_BINDING_MISMATCH, "the bound worktree does not exist",
                                       worktree=str(path))
    branch = git(path, "symbolic-ref", "--quiet", "HEAD", check=False).stdout.decode().strip()
    if branch != "refs/heads/" + task["branch"]:
        raise ImplementVerifyRejection(WORKTREE_BINDING_MISMATCH, "the bound worktree is not on the task branch",
                                       worktree=str(path), expected=task["branch"], actual=branch or None)
    return path


def snapshot(path):
    """HEAD, index/worktree cleanliness and the untracked file set (the dispatch baseline)."""
    head = text(path, "rev-parse", "HEAD")
    status = git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    entries = [e for e in status.split(b"\0") if e]
    tracked = sorted(e[3:].decode(errors="replace") for e in entries if not e.startswith(b"??"))
    untracked = sorted(e[3:].decode(errors="replace") for e in entries if e.startswith(b"??"))
    return dict(head=head, clean=not entries, trackedChanges=tracked, untracked=untracked,
                statusDigest=hashlib.sha256(status).hexdigest())


def is_ancestor(path, ancestor, descendant):
    return git(path, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def changed_files(path, base, head):
    raw = git(path, "diff", "--name-only", "-z", base, head).stdout
    return sorted(p.decode(errors="replace") for p in raw.split(b"\0") if p)


def blob(path, commit, file):
    return git(path, "show", commit + ":" + file).stdout


def compare(baseline, current):
    """How the worktree moved since the baseline: 'unchanged', 'committed-clean' or 'uncommitted'."""
    if current["head"] == baseline["head"] and current["statusDigest"] == baseline["statusDigest"]:
        return "unchanged"
    if current["clean"]:
        return "committed-clean"
    return "uncommitted"
