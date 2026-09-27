"""Define Task: the Candidate Task Definition enters the domain as exact bytes from a task-branch commit.

The structure gate loads the same current task validator the review channel's Definition check loads
(`mechanisms/artifact-templates/artifact_lint.py` under the product-line repository root, see
mechanisms/review-channel/review_channel_execution.check_definition), so no second grammar exists in
product code. The identity chain ties the candidate to the accepted Canonical Source Anchor (D-02 §6,
D-03 §6): the Primary source must name the milestones freeze revision fixed at acceptance.

Human-declared author identity and its evidence are fixed here and only handed on; deriving the
actual author vendor set and judging reviewer eligibility belong to the feature-t6 authorization
callback (seam ruling S-01).
"""
import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

from domain.acceptance.gitrepo import GitAbsent, GitUnavailable, environment
from domain.definition.results import (
    AUTHOR_EVIDENCE_UNREADABLE, CANDIDATE_NOT_IN_COMMIT, CANDIDATE_NOT_ON_TASK_BRANCH, IDENTITY_MISMATCH, INPUT_INVALID,
    SOURCE_ANCHOR_MISMATCH, TEMPLATE_STRUCTURE_INVALID, TEMPLATE_VALIDATOR_UNAVAILABLE, DefinitionRejection,
)

VALIDATOR = "mechanisms/artifact-templates/artifact_lint.py"
RE_SHA = re.compile(r"^[0-9a-f]{40}$")
AUTHOR_KEYS = {"tool", "model", "vendor", "humanOnly", "evidenceRefs"}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def definition_path(task_id):
    return f"tasks/{task_id}/{task_id}.md"


def load_validator(repository_root):
    """Load the product-line repository's current task validator; unavailable fails closed."""
    path = Path(repository_root) / VALIDATOR
    if not path.is_file():
        raise DefinitionRejection(TEMPLATE_VALIDATOR_UNAVAILABLE, "current task validator unavailable", path=VALIDATOR)
    raw = path.read_bytes()
    name = "hp_definition_task_lint_" + sha256(raw)[:16]
    module = sys.modules.get(name)
    if module is None:
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        except Exception as exc:  # the validator itself is untrusted input bytes
            sys.modules.pop(name, None)
            raise DefinitionRejection(TEMPLATE_VALIDATOR_UNAVAILABLE, "task validator could not be loaded",
                                      path=VALIDATOR, error=type(exc).__name__) from exc
    return module, dict(path=VALIDATOR, bytes=len(raw), sha256=sha256(raw))


def structure_gate(repository_root, task_id, raw):
    """Run the same validator the review channel runs; return its identity or raise."""
    module, identity = load_validator(repository_root)
    try:
        record = module.lint_file("task", str(Path(repository_root) / definition_path(task_id)), data=raw)
    except Exception as exc:
        raise DefinitionRejection(TEMPLATE_VALIDATOR_UNAVAILABLE, "task validator raised", error=type(exc).__name__) from exc
    if record.get("state") != "PASS":
        failing = [dict(check=c["check"], state=c["state"], findings=c.get("findings", [])[:5], reason=c.get("reason"))
                   for c in record.get("checks", []) if c.get("state") != "PASS"]
        raise DefinitionRejection(TEMPLATE_STRUCTURE_INVALID, "candidate fails the current task template structure gate",
                                  validatorState=record.get("state"), checks=failing, validator=identity)
    return identity


def _git(repository, *args):
    return subprocess.run(["git", "-C", str(repository), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=environment(repository))


def read_commit_file(repo, commit, path, missing_code, message):
    try:
        blob = repo.blob_id(commit, path)
        raw = repo.read(commit, path)
    except GitAbsent:
        raise DefinitionRejection(missing_code, message, commit=commit, path=path) from None
    return blob, raw


def on_task_branch(repo, task, commit):
    """The candidate commit must be reachable from the task's bound branch (not the worktree)."""
    if not isinstance(commit, str) or not RE_SHA.match(commit):
        raise DefinitionRejection(INPUT_INVALID, "commit must be a full lowercase 40-hex commit id", commit=commit)
    try:
        resolved = repo.resolve(commit)
    except GitAbsent:
        raise DefinitionRejection(CANDIDATE_NOT_ON_TASK_BRANCH, "commit does not exist in the product-line repository",
                                  commit=commit) from None
    result = _git(repo.path, "merge-base", "--is-ancestor", resolved, "refs/heads/" + task["branch"])
    if result.returncode == 1:
        raise DefinitionRejection(CANDIDATE_NOT_ON_TASK_BRANCH, "commit is not reachable from the task branch",
                                  commit=commit, branch=task["branch"])
    if result.returncode != 0:
        raise GitUnavailable("merge-base failed: " + result.stderr.decode(errors="replace").strip(), transient=True)
    return resolved


def identity_chain(task, raw):
    """H1, Identity, header dependency and Primary source must bind to the accepted anchor."""
    task_id = task["taskId"]
    anchor = task["anchor"]
    revision = anchor["components"]["milestones"]["freezeRevision"]
    expected_source = f"milestones.md@r{revision} {task_id}"
    text = raw.decode("utf-8")
    lines = text.split("\n")
    problems = []
    if not lines or not lines[0].startswith(f"# {task_id} · "):
        problems.append("H1 does not name the task record id")
    if f"- Task record ID: `{task_id}`" not in lines:
        problems.append("Identity task record id differs")
    if f"- Definition subject: `{task_id}-task`" not in lines:
        problems.append("Identity definition subject differs")
    if problems:
        raise DefinitionRejection(IDENTITY_MISMATCH, "candidate identity fields do not name the accepted task",
                                  problems=problems, taskId=task_id)
    header = f"> `{expected_source}`"
    primary = f"- Primary source: `{expected_source}`"
    mismatches = []
    if len(lines) < 4 or lines[3] != header:
        mismatches.append(dict(field="Depends on", expected=header, actual=lines[3] if len(lines) > 3 else None))
    if primary not in lines:
        found = [line for line in lines if line.startswith("- Primary source:")]
        mismatches.append(dict(field="Primary source", expected=primary, actual=found[0] if found else None))
    if mismatches:
        raise DefinitionRejection(SOURCE_ANCHOR_MISMATCH,
                                  "candidate source does not equal the milestones revision and task fixed at acceptance",
                                  mismatches=mismatches, anchorMilestonesRevision=revision,
                                  sourceRevision=anchor["sourceRevision"])
    return dict(primarySource=expected_source, anchorDigest=anchor.get("digest"), sourceRevision=anchor["sourceRevision"])


def author_evidence(repo, author):
    """Fix the Human-declared author identity and the exact evidence bytes it points at."""
    if not isinstance(author, dict) or set(author) != AUTHOR_KEYS:
        raise DefinitionRejection(INPUT_INVALID, "author must declare exactly tool, model, vendor, humanOnly and evidenceRefs",
                                  keys=sorted(author) if isinstance(author, dict) else None)
    if type(author["humanOnly"]) is not bool:
        raise DefinitionRejection(INPUT_INVALID, "author.humanOnly must be a boolean")
    for key in ("tool", "model", "vendor"):
        value = author[key]
        if author["humanOnly"]:
            if value is not None:
                raise DefinitionRejection(INPUT_INVALID, "a human-only declaration carries no tool, model or vendor", field=key)
        elif not isinstance(value, str) or not value:
            raise DefinitionRejection(INPUT_INVALID, "an agent-assisted declaration names tool, model and vendor", field=key)
    refs = author["evidenceRefs"]
    if not isinstance(refs, list) or not refs:
        raise DefinitionRejection(AUTHOR_EVIDENCE_UNREADABLE, "author identity needs at least one fixed evidence reference")
    fixed = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"commit", "path"}:
            raise DefinitionRejection(INPUT_INVALID, "each evidence reference is {commit, path}")
        try:
            commit = repo.resolve(ref["commit"])
            raw = repo.read(commit, ref["path"])
        except (GitAbsent, TypeError):
            raise DefinitionRejection(AUTHOR_EVIDENCE_UNREADABLE, "author evidence is not readable at the named commit",
                                      reference=ref) from None
        fixed.append(dict(commit=commit, path=ref["path"], bytes=len(raw), sha256=sha256(raw)))
    return dict(tool=author["tool"], model=author["model"], vendor=author["vendor"], humanOnly=author["humanOnly"],
                evidence=fixed)


def author_identity(author):
    """The fixed author identity in the shape feature-t6's Policy Gate reads (candidates[].authorIdentity).

    agents carry (agent, model) pairs; the vendor is derived by feature-t6 from its product-side mapping,
    never taken from this declaration. evidenceRefs name each fixed evidence object by commit, path and digest.
    """
    agents = [] if author["humanOnly"] else [dict(agent=author["tool"], model=author["model"])]
    refs = ["%s:%s#sha256=%s" % (e["commit"], e["path"], e["sha256"]) for e in author["evidence"]]
    return dict(humanOnly=author["humanOnly"], agents=agents, evidenceRefs=refs)


def load_candidate(repo, repository_root, task, commit, author):
    """Everything the Define Task submission needs, checked before any state change."""
    task_id = task["taskId"]
    resolved = on_task_branch(repo, task, commit)
    path = definition_path(task_id)
    blob, raw = read_commit_file(repo, resolved, path, CANDIDATE_NOT_IN_COMMIT,
                                 "the commit does not carry the task Definition file")
    validator = structure_gate(repository_root, task_id, raw)
    chain = identity_chain(task, raw)
    fixed_author = author_evidence(repo, author)
    return dict(commit=resolved, path=path, blob=blob, bytes=len(raw), sha256=sha256(raw), validator=validator,
                identityChain=chain, author=fixed_author, authorIdentity=author_identity(fixed_author))
