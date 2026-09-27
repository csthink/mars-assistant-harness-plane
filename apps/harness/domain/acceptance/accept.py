"""Logically atomic task acceptance (spec FR-15 / FR-16 / FR-22 / FR-32; design §接纳次序与原子性).

Order: operation record -> read-only source resolution -> claim commit (dependencies, capacity, claim,
intended identities) -> physical branch and worktree -> Acceptance Commit Point. A Task is visible only
after the last commit. Same requestId + same intent resumes or replays the same operation; a claim is
never released automatically; partial effects are re-verified before reuse and never deleted.

observer(phase, operation) is a test-only hook called at after-claim, after-branch, after-worktree and
before-accept; production callers pass None.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import rfc8785

from domain import projection_stream
from domain.acceptance import projection, results
from domain.acceptance.gitrepo import GitAbsent, GitUnavailable, Repository
from domain.acceptance.results import Rejection
from domain.acceptance.sources import RESOLVED, TASK_TYPES, resolve
from domain.acceptance.terminal import concurrency_limit, in_flight, unmet_dependencies
from domain.workflow.progression import initial_instance

INTENT_KEYS = ("repository", "taskType", "taskId", "baseRef", "worktreeRoot", "authorityRef")
RE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}$")
WORKFLOW_DEFINITION = "mechanisms/delivery-method/MVP_Workflow_v5.drawio"

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def intent_of(request):
    missing = [k for k in INTENT_KEYS if not isinstance(request.get(k), str) or not request[k]]
    if "authorityRef" in missing:
        raise Rejection(results.AUTHORITY_MISSING, "authorityRef is required: acceptance is an authorized Human action")
    if missing:
        raise Rejection(results.WORKSPACE_ERROR, "missing request fields: " + ", ".join(missing), fields=missing)
    if request["taskType"] not in TASK_TYPES:
        raise Rejection(results.WORKSPACE_ERROR, "unknown task type: " + request["taskType"])
    return {k: request[k] for k in INTENT_KEYS}

def intent_digest(intent):
    return hashlib.sha256(rfc8785.dumps(intent)).hexdigest()

def dedup_key(repository_identity, task_type, task_id):
    return json.dumps([repository_identity, task_type, task_id], separators=(",", ":"))

def branch_name(task_id):
    return "harness/" + task_id

def check_worktree_root(repo, root):
    path = Path(root)
    if not path.is_absolute():
        raise Rejection(results.WORKSPACE_ERROR, "worktreeRoot must be an absolute path")
    try:
        top = Path(repo.text("rev-parse", "--show-toplevel")).resolve()
        common = repo.common_dir().resolve()
    except GitAbsent as exc:
        raise Rejection(results.UNRESOLVED, "repository reference is not a repository: " + str(exc),
                        components=[dict(role="repository", path=str(repo.path), outcome="UNRESOLVED", reason=str(exc), identity=None)]) from exc
    except GitUnavailable as exc:
        raise Rejection(results.INDETERMINATE, "repository could not be read: " + str(exc)) from exc
    resolved = path.resolve()
    for inside in (top, common):
        if resolved == inside or inside in resolved.parents:
            raise Rejection(results.WORKSPACE_ERROR, "worktreeRoot must lie outside the repository")
    return resolved

def workflow_definition(repo, commit):
    try:
        blob = repo.blob_id(commit, WORKFLOW_DEFINITION)
        raw = repo.read(commit, WORKFLOW_DEFINITION)
    except GitAbsent:
        raise Rejection(results.UNRESOLVED, "official Workflow topology missing at the source revision: " + WORKFLOW_DEFINITION,
                        components=[dict(role="workflow", path=WORKFLOW_DEFINITION, outcome="UNRESOLVED", reason="missing", identity=None)]) from None
    return dict(path=WORKFLOW_DEFINITION, blob=blob, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def review_configuration(state):
    cfg = state.get("configuration", {})
    return dict(definitionReview=bool(cfg.get("definitionReview", False)), changeValidation=bool(cfg.get("changeValidation", False)),
                source="configuration" if ("definitionReview" in cfg or "changeValidation" in cfg) else "default")

def registered_worktree(repo, path):
    for entry in repo.worktrees():
        if "worktree" in entry and Path(entry["worktree"]).resolve() == path:
            return entry
    return None

def verify_partial_effects(repo, intended, source_revision, path):
    """Prove ownership of an existing branch / worktree before reuse; unknown state stops."""
    target = repo.branch_target(intended["branch"])
    if target is not None and target != source_revision:
        raise Rejection(results.PARTIAL_EFFECT_UNRESOLVED, "branch exists but does not point at the source revision",
                        branch=intended["branch"], actual=target, expected=source_revision)
    entry = registered_worktree(repo, path)
    if entry is None and path.exists():
        raise Rejection(results.PARTIAL_EFFECT_UNRESOLVED, "worktree path exists but is not registered for this branch", worktree=str(path))
    if entry is not None:
        if entry.get("branch") != "refs/heads/" + intended["branch"] or (target is not None and entry.get("HEAD") != target):
            raise Rejection(results.PARTIAL_EFFECT_UNRESOLVED, "registered worktree is bound to another branch or commit",
                            worktree=str(path), registered=entry)
    return target, entry

def result_view(op, task=None):
    view = dict(result=results.ACCEPTED, requestId=op["requestId"],
                operation=dict(requestId=op["requestId"], status=op["status"], intentDigest=op["intentDigest"]))
    if task:
        view["task"] = copy.deepcopy(task)
    return view

def accept_task(store, request, *, dry_run=False, observer=None):
    """Run or resume one acceptance. Returns a result dict; rejections are raised as Rejection."""
    intent = intent_of(request)
    request_id = request.get("requestId")
    if not isinstance(request_id, str) or not RE_REQUEST_ID.match(request_id):
        raise Rejection(results.WORKSPACE_ERROR, "requestId must be a stable identifier")
    digest = intent_digest(intent)
    repo = Repository(intent["repository"])
    root = check_worktree_root(repo, intent["worktreeRoot"])
    notify = observer or (lambda phase, detail=None: None)

    if dry_run:
        return readiness(store, repo, intent, request_id, root)

    def establish(s):
        op = s["acceptance"].get(request_id)
        if op is None:
            op = dict(requestId=request_id, intentDigest=digest, intent=intent, status="started", outcome=None,
                      claim=None, intended=None, task=None, startedAt=now(), history=[])
            s["acceptance"][request_id] = op
        elif op["intentDigest"] != digest:
            raise Rejection(results.REQUEST_CONFLICT, "requestId already bound to a different creation intent",
                            recorded=op["intentDigest"], offered=digest)
        return copy.deepcopy(op)
    op = store.transaction(None, establish)
    if op["status"] == "accepted":
        return dict(result_view(op, store.read()["tasks"][op["task"]]), result=results.IDEMPOTENT_REPLAY)

    if op["status"] == "claimed":
        anchor = op["intended"]["anchor"]
    else:
        anchor = qualify(store, repo, intent, request_id)
        op = claim(store, repo, intent, request_id, anchor, root)
        if op["status"] == "accepted":
            return dict(result_view(op, store.read()["tasks"][op["task"]]), result=results.IDEMPOTENT_REPLAY)
    notify("after-claim", op)
    intended = op["intended"]
    path = Path(intended["worktree"])
    source_revision = anchor["sourceRevision"]
    try:
        target, entry = verify_partial_effects(repo, intended, source_revision, path)
        if target is None:
            repo.create_branch(intended["branch"], source_revision)
        notify("after-branch", op)
        if entry is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            repo.add_worktree(path, intended["branch"])
        notify("after-worktree", op)
    except (GitUnavailable, GitAbsent, OSError) as exc:
        code = results.INDETERMINATE if getattr(exc, "transient", False) else results.WORKSPACE_ERROR
        record_failure(store, request_id, code, str(exc))
        raise Rejection(code, "branch or worktree could not be established: " + str(exc)) from exc
    except Rejection as exc:
        record_failure(store, request_id, exc.code, str(exc))
        raise
    notify("before-accept", op)
    return commit_point(store, repo, request_id, intended, path)

def qualify(store, repo, intent, request_id):
    """Read-only source resolution; rejections are recorded on the operation and raised."""
    if intent["taskType"] != "feature":
        record_failure(store, request_id, results.SOURCE_LANE_UNAVAILABLE, "hotfix source lane is delivered by feature-t1")
        raise Rejection(results.SOURCE_LANE_UNAVAILABLE, "no source resolver for task type " + intent["taskType"])
    resolution = resolve(intent["repository"], intent["taskType"], intent["taskId"], intent["baseRef"])
    if resolution["outcome"] != RESOLVED:
        code = results.UNRESOLVED if resolution["outcome"] == "UNRESOLVED" else results.INDETERMINATE
        record_failure(store, request_id, code, resolution["reason"], resolution=resolution)
        raise Rejection(code, resolution["reason"], components=resolution["components"])
    anchor = resolution["anchor"]
    try:
        anchor["workflowDefinition"] = workflow_definition(repo, anchor["sourceRevision"])
    except Rejection as exc:
        record_failure(store, request_id, exc.code, str(exc), resolution=resolution)
        raise
    except GitUnavailable as exc:
        record_failure(store, request_id, results.INDETERMINATE, str(exc))
        raise Rejection(results.INDETERMINATE, "workflow topology could not be read: " + str(exc)) from exc
    anchor["digest"] = hashlib.sha256(rfc8785.dumps({k: v for k, v in anchor.items() if k != "digest"})).hexdigest()
    return anchor

def claim(store, repo, intent, request_id, anchor, root):
    key = dedup_key(anchor["repositoryIdentity"], "feature", intent["taskId"])
    branch = branch_name(intent["taskId"])
    worktree = str(root / branch)
    def commit(s):
        op = s["acceptance"][request_id]
        if op["status"] in ("accepted", "claimed"):
            return copy.deepcopy(op)
        existing = s["claims"].get(key)
        if existing is not None and existing["operation"] != request_id:
            if existing["state"] == "accepted":
                raise Rejection(results.DUPLICATE_ACCEPTED_TASK, "this upstream task already has an accepted Task",
                                task=copy.deepcopy(s["tasks"][existing["task"]]["taskRef"]), claim=key)
            raise Rejection(results.DUPLICATE_ACCEPTANCE_IN_PROGRESS, "another acceptance operation holds the claim",
                            operation=existing["operation"], claim=key)
        unmet = unmet_dependencies(s, repo, anchor["sourceRevision"], anchor["dependencies"])
        if unmet:
            raise Rejection(results.DEPENDENCY_UNMET, "dependencies without a terminal done fact: " + ", ".join(unmet), unmet=unmet)
        flight = in_flight(s, repo, anchor["sourceRevision"])
        limit = concurrency_limit(s)
        if flight["count"] >= limit:
            raise Rejection(results.CONCURRENCY_LIMIT_REACHED, f"in-flight tasks {flight['count']} reached the limit {limit}",
                            limit=limit, inFlight=flight)
        if repo.branch_target(branch) is not None:
            raise Rejection(results.WORKSPACE_ERROR, "branch already exists before acceptance: " + branch, branch=branch)
        if Path(worktree).exists() or registered_worktree(repo, Path(worktree)) is not None:
            raise Rejection(results.WORKSPACE_ERROR, "worktree path already exists before acceptance: " + worktree, worktree=worktree)
        s["claims"][key] = dict(state="claimed", operation=request_id, task=None, taskId=intent["taskId"], claimedAt=now())
        op.update(status="claimed", claim=key, intended=dict(taskRef="task:" + intent["taskId"], branch=branch, worktree=worktree,
                                                             anchor=copy.deepcopy(anchor)))
        op["history"].append(dict(at=now(), event=results.CLAIM_ACQUIRED))
        return copy.deepcopy(op)
    try:
        return store.transaction(None, commit)
    except Rejection as exc:
        record_failure(store, request_id, exc.code, str(exc))
        raise

def commit_point(store, repo, request_id, intended, path):
    def commit(s):
        op = s["acceptance"][request_id]
        if op["status"] == "accepted":
            return ("replay", copy.deepcopy(op), copy.deepcopy(s["tasks"][op["task"]]))
        anchor = intended["anchor"]
        target = repo.branch_target(intended["branch"])
        entry = registered_worktree(repo, path)
        if target != anchor["sourceRevision"] or entry is None or entry.get("branch") != "refs/heads/" + intended["branch"]:
            raise Rejection(results.PARTIAL_EFFECT_UNRESOLVED, "branch or worktree changed before the acceptance commit",
                            branch=intended["branch"], actual=target, worktree=str(path), registered=entry)
        task_id = anchor["taskId"]
        task = dict(taskId=task_id, taskRef=intended["taskRef"], taskType="feature", repositoryIdentity=anchor["repositoryIdentity"],
                    anchor=copy.deepcopy(anchor), branch=intended["branch"], worktree=str(path),
                    workflowInstance=initial_instance(anchor["workflowDefinition"], review_configuration(s), s["revision"]),
                    acceptedAt=now(), acceptedRevision=s["revision"], provenance=request_id, terminal=None)
        s["tasks"][task_id] = task
        s["claims"][op["claim"]].update(state="accepted", task=task_id)
        op.update(status="accepted", task=task_id, outcome=results.ACCEPTED)
        op["history"].append(dict(at=now(), event=results.ACCEPTED))
        # The accepted Task and the task list reach every open scope's stream in this commit (KB-296); a Runtime
        # acceptance attributes them to its Operation in its own scope.
        projection_stream.rebuild(s, projection.refresh, {op["scope"]: request_id} if op.get("channel") == "runtime" else None)
        return ("accepted", copy.deepcopy(op), copy.deepcopy(task))
    try:
        kind, op, task = store.transaction(None, commit)
    except Rejection as exc:
        record_failure(store, request_id, exc.code, str(exc))
        raise
    return dict(result_view(op, task), result=results.ACCEPTED if kind == "accepted" else results.IDEMPOTENT_REPLAY)

def record_failure(store, request_id, code, message, **detail):
    def commit(s):
        op = s["acceptance"].get(request_id)
        if op is None or op["status"] == "accepted":
            return None
        if op["status"] in ("started", "queued"):
            op["status"] = "rejected"
        op["outcome"] = code
        op["history"].append(dict(at=now(), event=code, message=message, **{k: v for k, v in detail.items() if k != "resolution"}))
        return None
    store.transaction(None, commit)

def readiness(store, repo, intent, request_id, root):
    """Dry run: same qualification and claim evaluation without any durable or physical effect."""
    s = store.read()
    op = s["acceptance"].get(request_id)
    if op is not None and op["intentDigest"] != intent_digest(intent):
        raise Rejection(results.REQUEST_CONFLICT, "requestId already bound to a different creation intent")
    if op is not None and op["status"] == "accepted":
        return dict(dryRun=True, readiness="READY", result=results.IDEMPOTENT_REPLAY, task=copy.deepcopy(s["tasks"][op["task"]]))
    if intent["taskType"] != "feature":
        raise Rejection(results.SOURCE_LANE_UNAVAILABLE, "no source resolver for task type " + intent["taskType"])
    resolution = resolve(intent["repository"], intent["taskType"], intent["taskId"], intent["baseRef"])
    if resolution["outcome"] != RESOLVED:
        code = results.UNRESOLVED if resolution["outcome"] == "UNRESOLVED" else results.INDETERMINATE
        raise Rejection(code, resolution["reason"], components=resolution["components"])
    anchor = resolution["anchor"]
    anchor["workflowDefinition"] = workflow_definition(repo, anchor["sourceRevision"])
    key = dedup_key(anchor["repositoryIdentity"], "feature", intent["taskId"])
    existing = s["claims"].get(key)
    if existing is not None and existing["operation"] != request_id:
        code = results.DUPLICATE_ACCEPTED_TASK if existing["state"] == "accepted" else results.DUPLICATE_ACCEPTANCE_IN_PROGRESS
        raise Rejection(code, "claim held by " + existing["operation"], claim=key)
    unmet = unmet_dependencies(s, repo, anchor["sourceRevision"], anchor["dependencies"])
    if unmet:
        raise Rejection(results.DEPENDENCY_UNMET, "dependencies without a terminal done fact: " + ", ".join(unmet), unmet=unmet)
    flight = in_flight(s, repo, anchor["sourceRevision"])
    limit = concurrency_limit(s)
    if flight["count"] >= limit and existing is None:
        raise Rejection(results.CONCURRENCY_LIMIT_REACHED, f"in-flight tasks {flight['count']} reached the limit {limit}", limit=limit, inFlight=flight)
    return dict(dryRun=True, readiness="READY", result="READY", resolution=resolution, inFlight=flight, limit=limit,
                intended=dict(branch=branch_name(intent["taskId"]), worktree=str(root / branch_name(intent["taskId"]))))

def set_configuration(store, key, value, authority_ref):
    """Authorized configuration write in the same unit of work; hp's own value 4 is carried by D-09."""
    if not isinstance(authority_ref, str) or not authority_ref:
        raise Rejection(results.AUTHORITY_MISSING, "authorityRef is required to change configuration")
    if key == "concurrency-limit":
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise Rejection(results.WORKSPACE_ERROR, "concurrency limit must be a positive integer")
        field = "concurrencyLimit"
    elif key in ("definition-review", "change-validation"):
        if not isinstance(value, bool):
            raise Rejection(results.WORKSPACE_ERROR, key + " must be a boolean")
        field = "definitionReview" if key == "definition-review" else "changeValidation"
    elif key == "author-vendor":
        # feature-t6 (Assistant OD-399): the product-side author vendor mapping read by the Policy Gate.
        from domain.policy.inputs import vendors
        if not isinstance(value, dict) or set(value) != {"agent", "model", "vendor"} \
                or not all(isinstance(value[k], str) and value[k].strip() for k in value):
            raise Rejection(results.WORKSPACE_ERROR, "author-vendor needs non-empty agent, model and vendor")
        if value["vendor"] not in vendors():
            raise Rejection(results.WORKSPACE_ERROR, "vendor outside the model vendor closed set", vendors=list(vendors()))
        def commit(s):
            table = s["configuration"].setdefault("authorVendors", {})
            previous = table.get(value["agent"], {}).get(value["model"])
            table.setdefault(value["agent"], {})[value["model"]] = value["vendor"]
            key_value = dict(agent=value["agent"], model=value["model"])
            s["configuration"].setdefault("history", []).append(dict(at=now(), field="authorVendors", key=key_value,
                                                                     previous=previous, value=value["vendor"],
                                                                     authorityRef=authority_ref))
            return dict(field="authorVendors", entry=key_value, previous=previous, value=value["vendor"], revision=s["revision"])
        return store.transaction(None, commit)
    else:
        raise Rejection(results.WORKSPACE_ERROR, "unknown configuration key: " + str(key))
    def commit(s):
        previous = s["configuration"].get(field)
        s["configuration"][field] = value
        s["configuration"].setdefault("history", []).append(dict(at=now(), field=field, previous=previous, value=value, authorityRef=authority_ref))
        return dict(field=field, previous=previous, value=value, revision=s["revision"])
    return store.transaction(None, commit)
