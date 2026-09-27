"""The exact Publish authorization binding `publishBinding` (feature-t7 design, publishBinding 与 KB-265 取舍).

The Human gives six values: candidateCommit, sourceBranch, remote, targetBranch and the pull request title
and body, plus the digest of the Publish authorization context they saw. `require` checks each against the
current facts and completes the derived fields in the authorizing transaction; any mismatch is refused with
the offending field path (repo:KB-05) and nothing is recorded.

Assistant KB-265: the binding names the task-branch head that the push will publish. The candidate that
Verify (and, when it ran, Validate Change) confirmed is recorded as verifiedCandidateCommit and must be an
ancestor; every commit between the two must be one of this task's recorded ruling writes (feature-t3 or
feature-t5) touching only its recorded paths. Anything else is an uncontrolled governance change and stops.
feature-t6's push permit compares candidateCommit, sourceBranch, remote and targetBranch of this binding with
the push request, so the exact comparison is about the commit the remote branch will point at.
"""
import copy
import hashlib
import re
import subprocess

from domain.acceptance.gitrepo import environment
from domain.publish import configuration, context as publish_context
from domain.publish.results import (
    BINDING_MISMATCH, CANDIDATE_NOT_VERIFIED, CONTEXT_STALE, INDETERMINATE, INPUT_INVALID, PUBLISH_TARGET_NOT_CONFIGURED,
    UNCONTROLLED_CHANGE, PublishRejection,
)
from domain.validation import dispatch as validation_dispatch, records as validation_records
from domain.validation.results import ValidationRejection

HUMAN_KEYS = ("candidateCommit", "sourceBranch", "remote", "targetBranch", "pullRequest")
PULL_REQUEST_KEYS = ("title", "body")
TITLE_MAX = 256
BODY_MAX_BYTES = 60000
RE_SHA = re.compile(r"^[0-9a-f]{40}$")
RE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
GIT_TIMEOUT = 60


class GitFailed(Exception):
    def __init__(self, message, transient=False):
        self.transient = transient
        super().__init__(message)


def git(repository, *args, timeout=GIT_TIMEOUT):
    """git in the product-line repository only; returns the completed process (the caller reads returncode)."""
    try:
        return subprocess.run(["git", "-C", str(repository), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=environment(repository), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GitFailed("git %s timed out" % args[0], transient=True) from exc
    except OSError as exc:
        raise GitFailed("git %s could not start: %s" % (args[0], exc.__class__.__name__), transient=True) from exc


def is_ancestor(repository, older, newer):
    """True / False from `merge-base --is-ancestor`; an object missing locally is not an ancestor."""
    result = git(repository, "merge-base", "--is-ancestor", older, newer)
    return result.returncode == 0


def push_addresses(repository, remote):
    result = git(repository, "remote", "get-url", "--push", "--all", remote)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.decode().splitlines() if line.strip()]


def remote_address(repository, remote):
    """(raw address, normalised address) of the single push address of the remote, or (None, reason)."""
    addresses = push_addresses(repository, remote)
    if len(addresses) != 1:
        return None, "the remote has %d push addresses; exactly one is required" % len(addresses)
    try:
        return addresses[0], configuration.normalize_address(addresses[0])
    except configuration.AddressInvalid as exc:
        return None, str(exc)


def _rulings(state, task_id):
    """commit -> recorded paths of every ruling this task's domain wrote (feature-t3 and feature-t5)."""
    task = state["tasks"][task_id]
    written = {}
    rows = list((task.get("taskDefinition") or {}).get("rulings", [])) + list(validation_records.view_of(state, task_id)["rulings"])
    for row in rows:
        if row.get("status") == "written" and row.get("commit"):
            written.setdefault(row["commit"], set()).add(row["path"])
    return written


def governance_commits(state, repository, task_id, verified, candidate):
    """[{commit, paths}] between verified (exclusive) and candidate; raises UNCONTROLLED_CHANGE for any other commit."""
    listed = git(repository, "rev-list", "--reverse", "--parents", "%s..%s" % (verified, candidate))
    if listed.returncode != 0:
        raise PublishRejection(UNCONTROLLED_CHANGE, "the commits between the verified candidate and the head cannot be listed",
                               field="publishBinding.governanceCommits")
    allowed = _rulings(state, task_id)
    out = []
    for line in listed.stdout.decode().splitlines():
        ids = line.split()
        commit, parents = ids[0], ids[1:]
        changed = git(repository, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
        paths = sorted(p for p in changed.stdout.decode().splitlines() if p)
        if len(parents) != 1 or commit not in allowed or not set(paths) <= allowed[commit]:
            raise PublishRejection(UNCONTROLLED_CHANGE, "a commit between the verified candidate and the task-branch head "
                                   "is not a ruling write recorded by this task's domain (non-controlled governance change)",
                                   field="publishBinding.governanceCommits", commit=commit, paths=paths, parents=len(parents))
        out.append(dict(commit=commit, paths=paths))
    return out


def _text(field, value, *, single_line, limit_bytes=None, limit_chars=None, minimum=1):
    if not isinstance(value, str) or len(value) < minimum:
        raise PublishRejection(INPUT_INVALID, "%s must be a string of at least %d character(s)" % (field, minimum), field=field)
    allowed = () if single_line else ("\n", "\t")
    bad = [i for i, c in enumerate(value) if (ord(c) < 32 or ord(c) == 127) and c not in allowed]
    if bad:
        raise PublishRejection(INPUT_INVALID, "%s contains a %s at offset %d" % (
            field, "line break or control character" if single_line else "control character", bad[0]), field=field, offset=bad[0])
    if limit_chars is not None and len(value) > limit_chars:
        raise PublishRejection(INPUT_INVALID, "%s exceeds %d characters" % (field, limit_chars), field=field)
    if limit_bytes is not None and len(value.encode("utf-8")) > limit_bytes:
        raise PublishRejection(INPUT_INVALID, "%s exceeds %d bytes" % (field, limit_bytes), field=field)


def _shape(offered):
    if not isinstance(offered, dict) or set(offered) != set(HUMAN_KEYS):
        raise PublishRejection(INPUT_INVALID, "publishBinding takes exactly " + ", ".join(HUMAN_KEYS), field="publishBinding",
                               offered=sorted(offered) if isinstance(offered, dict) else None)
    for key in ("candidateCommit", "sourceBranch", "remote", "targetBranch"):
        _text("publishBinding." + key, offered[key], single_line=True, limit_chars=255)
    if not RE_SHA.match(offered["candidateCommit"]):
        raise PublishRejection(INPUT_INVALID, "publishBinding.candidateCommit is a full lowercase commit id",
                               field="publishBinding.candidateCommit")
    pull = offered["pullRequest"]
    if not isinstance(pull, dict) or set(pull) != set(PULL_REQUEST_KEYS):
        raise PublishRejection(INPUT_INVALID, "publishBinding.pullRequest takes exactly title and body",
                               field="publishBinding.pullRequest")
    _text("publishBinding.pullRequest.title", pull["title"], single_line=True, limit_chars=TITLE_MAX)
    _text("publishBinding.pullRequest.body", pull["body"], single_line=False, limit_bytes=BODY_MAX_BYTES, minimum=0)


def _mismatch(field, expected, offered):
    raise PublishRejection(BINDING_MISMATCH, "%s differs from the fact it must equal" % field, field=field,
                           expected=expected, offered=offered)


def verified_candidate(state, task_id):
    """The candidate Verify confirmed (feature-t4 routing) and, when Validate Change ran, its last verdict's candidate."""
    try:
        found = validation_dispatch.candidate(state, task_id)
    except ValidationRejection as exc:
        raise PublishRejection(CANDIDATE_NOT_VERIFIED, "no routed candidate with a PASS or not-applicable Verify result",
                               field="publishBinding.verifiedCandidateCommit", cause=exc.code) from exc
    last = validation_records.last_verdict_round(validation_records.view_of(state, task_id))
    if last is not None and last["candidateCommit"] != found["commit"]:
        raise PublishRejection(CANDIDATE_NOT_VERIFIED, "the last Validate Change verdict is bound to another candidate",
                               field="publishBinding.verifiedCandidateCommit", verdictCandidate=last["candidateCommit"],
                               routedCandidate=found["commit"])
    return found


def require(state, repository, task_id, offered, context_digest):
    """Check the Human's binding and the context digest; return (binding with derived fields, current digest)."""
    try:
        return _require(state, repository, task_id, offered, context_digest)
    except GitFailed as exc:
        raise PublishRejection(INDETERMINATE, "the product-line repository could not be read: " + str(exc),
                               field="publishBinding") from exc


def _require(state, repository, task_id, offered, context_digest):
    target = configuration.current(state)
    if target is None:
        raise PublishRejection(PUBLISH_TARGET_NOT_CONFIGURED, "configure publish-target before a Publish authorization",
                               field="publishTarget")
    _shape(offered)
    if not isinstance(context_digest, str) or not RE_DIGEST.match(context_digest):
        raise PublishRejection(INPUT_INVALID, "contextDigest is the SHA-256 of the Publish authorization context",
                               field="contextDigest")
    current = publish_context.digest(publish_context.view(state, repository, task_id))
    if context_digest != current:
        raise PublishRejection(CONTEXT_STALE, "the Publish authorization context changed since it was read",
                               field="contextDigest", offered=context_digest, current=current)
    task = state["tasks"][task_id]
    if offered["sourceBranch"] != task["branch"]:
        _mismatch("publishBinding.sourceBranch", task["branch"], offered["sourceBranch"])
    if offered["remote"] != target["remote"]:
        _mismatch("publishBinding.remote", target["remote"], offered["remote"])
    if offered["targetBranch"] != target["targetBranch"]:
        _mismatch("publishBinding.targetBranch", target["targetBranch"], offered["targetBranch"])
    head = publish_context.branch_head(repository, task["branch"])
    if offered["candidateCommit"] != head:
        _mismatch("publishBinding.candidateCommit", head, offered["candidateCommit"])
    found = verified_candidate(state, task_id)
    verified = found["commit"]
    if verified != head and not is_ancestor(repository, verified, head):
        raise PublishRejection(UNCONTROLLED_CHANGE, "the verified candidate is not an ancestor of the task-branch head",
                               field="publishBinding.verifiedCandidateCommit", verified=verified, head=head)
    governance = governance_commits(state, repository, task_id, verified, head) if verified != head else []
    raw, address = remote_address(repository, target["remote"])
    if raw is None:
        raise PublishRejection(BINDING_MISMATCH, "the remote's push address: " + str(address), field="publishBinding.remoteAddress")
    if address != target["remoteAddress"]:
        _mismatch("publishBinding.remoteAddress", target["remoteAddress"], address)
    body = offered["pullRequest"]["body"]
    binding = dict(candidateCommit=head, sourceBranch=task["branch"], remote=target["remote"],
                   targetBranch=target["targetBranch"],
                   pullRequest=dict(title=offered["pullRequest"]["title"], body=body,
                                    bodySha256=hashlib.sha256(body.encode("utf-8")).hexdigest()),
                   verifiedCandidateCommit=verified, verification=copy.deepcopy(
                       {k: found["verification"].get(k) for k in ("verificationId", "result")}),
                   governanceCommits=governance, remoteAddress=address,
                   platform={k: target[k] for k in ("provider", "host", "repository", "repositoryId")},
                   repositoryIdentity=task.get("repositoryIdentity"))
    return binding, current


def proposal(state, repository, task_id):
    """Read only: the context, its digest and a proposed Human binding (the Human may change title and body)."""
    view = publish_context.view(state, repository, task_id)
    target = configuration.current(state)
    task = state["tasks"][task_id]
    frozen = (view["definition"] or {}).get("frozen") or {}
    title = "%s: publish %s" % (task_id, (view["taskBranch"]["head"] or "")[:12])
    heading = None
    if frozen.get("commit") and frozen.get("path"):
        shown = git(repository, "show", "%s:%s" % (frozen["commit"], frozen["path"]))
        if shown.returncode == 0:
            first = shown.stdout.decode("utf-8", "replace").splitlines()[:1]
            heading = first[0][2:].strip() if first and first[0].startswith("# ") else None
    if heading:
        title = heading[:TITLE_MAX]
    candidate = view["candidate"]
    switch = view["validateChange"]["switch"]
    lines = ["Task: %s" % task_id, "Task branch: %s at %s" % (task["branch"], view["taskBranch"]["head"]),
             "Verified candidate: %s (Verify %s)" % (candidate.get("commit"), (candidate.get("verification") or {}).get("result")),
             "Validate Change: %s" % (("enabled" if switch[-1]["changeValidation"] else "disabled") if switch else "not recorded"),
             "Reservations: %d" % (len(view["definition"]["reservations"]) + len(view["validateChange"]["reservations"])),
             "Publish authorization context: %s" % publish_context.digest(view)]
    human = dict(candidateCommit=view["taskBranch"]["head"], sourceBranch=task["branch"],
                 remote=(target or {}).get("remote"), targetBranch=(target or {}).get("targetBranch"),
                 pullRequest=dict(title=title, body="\n".join(lines) + "\n"))
    return dict(context=view, contextDigest=publish_context.digest(view), publishBinding=human, publishTarget=target)
