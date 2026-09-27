"""Read-only Git access for source resolution and physical workspace facts.

Determinate absence (missing ref, missing path) and indeterminate failure (git unavailable,
timeout, permission) are distinct exceptions so that callers never conflate them.
"""
import os
from pathlib import Path
import subprocess

TIMEOUT = 30

class GitUnavailable(Exception):
    """git could not answer: missing binary, timeout, permission or unexpected failure.

    transient=True marks spawn failures and timeouts (the answer may exist but was not obtained);
    transient=False marks a git command that ran and reported a failure.
    """
    def __init__(self, message, transient=False):
        self.transient = transient
        super().__init__(message)

class GitAbsent(Exception):
    """git answered determinately that the object does not exist."""

def probe(path):
    """Classify a repository reference before any git call.

    Determinate absence (GitAbsent): the path does not exist, or it has no `.git` entry, or the gitdir
    file points at a missing directory. Indeterminate (GitUnavailable, transient): the path or its
    `.git` (or the directory a gitdir file points at) exists but cannot be accessed (EACCES, EPERM,
    I/O errors). Never walks up to an enclosing repository.
    """
    path = Path(path)
    try:
        if not path.exists():
            raise GitAbsent(f"repository path does not exist: {path}")
        if not os.access(path, os.R_OK | os.X_OK):
            raise GitUnavailable(f"repository path is not accessible: {path}", transient=True)
        dot = path / ".git"
        if not dot.exists():
            if os.access(path, os.R_OK | os.X_OK):
                raise GitAbsent(f"no .git entry at repository root: {path}")
            raise GitUnavailable(f"repository path is not accessible: {path}", transient=True)
        if dot.is_dir():
            os.listdir(dot)
            return dot
        text = dot.read_text(errors="replace").strip()
        if not text.startswith("gitdir:"):
            raise GitAbsent(f".git file is not a gitdir pointer: {dot}")
        target = Path(text[len("gitdir:"):].strip())
        if not target.is_absolute():
            target = (path / target)
        if not target.exists():
            raise GitAbsent(f"gitdir target does not exist: {target}")
        os.listdir(target)
        return target
    except PermissionError as exc:
        raise GitUnavailable(f"repository is not accessible: {exc}", transient=True) from exc
    except OSError as exc:
        raise GitUnavailable(f"repository could not be inspected: {exc}", transient=True) from exc

# Variables that relocate the repository, its work tree, index, object store or ref namespace. They are removed from
# every domain git subprocess so that `git -C <path>` addresses the repository at <path> only (feature-t18:KB-03);
# transport and authentication variables such as GIT_SSH_COMMAND or GIT_ASKPASS are kept.
REPOSITORY_LOCATING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                       "GIT_COMMON_DIR", "GIT_NAMESPACE")

def without_repository_locating(env):
    """A copy of env without the repository-locating Git variables (shared by the domain, the bundle builder and the bundle
    launch mode)."""
    return {k: v for k, v in env.items() if k not in REPOSITORY_LOCATING}

def environment(path):
    """git may discover only the repository at `path`, never an enclosing one or one named by the caller's environment."""
    ceiling = str(Path(path).resolve().parent)
    return {**without_repository_locating(os.environ), "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
            "GIT_CEILING_DIRECTORIES": ceiling, "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0"}

class Repository:
    def __init__(self, path):
        self.path = Path(path)
        self.probed = False

    def run(self, *args, data=None, timeout=None, absent_codes=(128,)):
        if not self.probed:
            probe(self.path)
            self.probed = True
        env = environment(self.path)
        try:
            result = subprocess.run(["git", "-C", str(self.path), *args], input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env, timeout=timeout or TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitUnavailable(f"git {args[0]}: {exc.__class__.__name__}", transient=True) from exc
        if result.returncode == 0:
            return result.stdout
        text = result.stderr.decode(errors="replace").strip()
        if result.returncode == 1 and "--verify" in args and "Permission denied" not in text:
            raise GitAbsent(text or "object not found")
        if result.returncode in absent_codes and ("not a git repository" in text or "does not exist" in text
                                                  or "cannot change to" in text or "No such file or directory" in text
                                                  or "Not a valid object name" in text or "exists on disk, but not in" in text
                                                  or "unknown revision" in text or "bad revision" in text
                                                  or "invalid object name" in text or "Needed a single revision" in text):
            raise GitAbsent(text)
        if result.returncode in absent_codes and "Permission denied" in text:
            raise GitUnavailable(text, transient=True)
        raise GitUnavailable(f"git {args[0]} failed ({result.returncode}): {text}")

    def text(self, *args, **kw):
        return self.run(*args, **kw).decode().strip()

    def common_dir(self):
        return Path(self.text("rev-parse", "--path-format=absolute", "--git-common-dir"))

    def resolve(self, ref):
        return self.text("rev-parse", "--verify", "--quiet", ref + "^{commit}", absent_codes=(1, 128))

    def root_commits(self, commit):
        return sorted(self.text("rev-list", "--max-parents=0", commit).split())

    def blob_id(self, commit, path):
        return self.text("rev-parse", "--verify", "--quiet", f"{commit}:{path}", absent_codes=(1, 128))

    def read(self, commit, path):
        return self.run("show", f"{commit}:{path}")

    def blob(self, blob_id):
        """Read one immutable blob by object id; the bound Workflow Definition Revision uses this."""
        return self.run("cat-file", "blob", blob_id, absent_codes=(1, 128))

    def ls_tree(self, commit, path):
        try:
            out = self.text("ls-tree", "--name-only", f"{commit}:{path}")
        except GitAbsent:
            return []
        return [line for line in out.splitlines() if line]

    def branch_target(self, branch):
        try:
            return self.text("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}", absent_codes=(1, 128))
        except GitAbsent:
            return None

    def worktrees(self):
        entries, current = [], {}
        for line in self.text("worktree", "list", "--porcelain").splitlines():
            if not line:
                if current:
                    entries.append(current)
                current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        if current:
            entries.append(current)
        return entries

    def create_branch(self, branch, commit):
        self.run("branch", "--no-track", branch, commit)

    def add_worktree(self, path, branch):
        self.run("worktree", "add", "--", str(path), branch)
