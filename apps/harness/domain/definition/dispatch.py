"""Review Definition executors: the review request, the channel run and the ruling write.

Everything here runs outside a domain transaction, on the execution layer (runtime/executions.py).
The review runs in the task worktree through the one governed channel runner (FR-40) via
feature-t17's ProductReview; the domain only prepares the request, checks the reviewed materials are
the bound candidate bytes and the anchor-revision upstream sources, and reads back the published
verdict and Receipt. The runner seam (`runner(descriptor, env, port, binding)`) exists so the test
launcher can supply explicitly synthetic reviewer output; production passes `channel_review_runner`.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys

from domain.definition import rulings
from domain.definition.results import REVIEW_MATERIAL_MISMATCH, DefinitionRejection

REFERENCES = ("sdd/proposal.md", "sdd/spec.md", "sdd/milestones.md")
ROLE = {"proposal": "sdd/proposal.md", "spec": "sdd/spec.md", "milestones": "sdd/milestones.md"}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def check_materials(descriptor):
    """The reviewed worktree files must be the bound candidate and the anchor-revision sources, byte for byte."""
    data = descriptor["input"]
    root = Path(data["worktree"])
    problems = []
    candidate = data["candidate"]
    path = root / candidate["path"]
    if not path.is_file() or sha256(path.read_bytes()) != candidate["sha256"]:
        problems.append(dict(path=candidate["path"], expected=candidate["sha256"]))
    for role, identity in data["anchor"]["components"].items():
        target = root / ROLE.get(role, "")
        if role in ROLE and (not target.is_file() or sha256(target.read_bytes()) != identity["sha256"]):
            problems.append(dict(path=ROLE[role], expected=identity["sha256"]))
    if problems:
        raise DefinitionRejection(REVIEW_MATERIAL_MISMATCH,
                                  "the review worktree does not carry the bound candidate and anchor-revision sources",
                                  problems=problems)


def request_document(descriptor, formal):
    data = descriptor["input"]
    author = data["author"]
    authors = [] if author["humanOnly"] else [dict(tool=author["tool"], model=author["model"], vendor=author["vendor"])]
    request = {"request_schema": data.get("requestSchema", "review-channel-request/v4"), "subject": data["subject"],
               "stage": "task", "round": data["round"], "caller": "harness-plane-domain", "task_record": descriptor["taskId"],
               "artifact_author": {"human_only": author["humanOnly"], "authors": authors},
               "inputs": {"candidates": [data["candidate"]["path"]], "references": list(REFERENCES)},
               "review_brief": {"background": "Review Definition of %s against its accepted source anchor %s"
                                % (descriptor["taskId"], data["anchor"]["sourceRevision"]),
                                "check_surfaces": "task round five questions", "evidence_limits": [],
                                "accepted_residuals": []},
               "invocation_authorization": descriptor["authorityRef"], "formal_review_authorized_by_owner": bool(formal)}
    if data.get("previousRound"):
        request["previous_round"] = copy.deepcopy(data["previousRound"])
        request["review_brief"]["remediation_statement"] = data.get("remediationStatement") or "revised candidate"
    return request


def intent_document(descriptor, env, registration, mapping, binding, request):
    data = descriptor["input"]
    runtime = data.get("runtime") or {}
    profile = registration["profile"]
    budget = dict(maxToolCalls=profile["maxToolCalls"], maxRunSeconds=profile["maxRunSeconds"], maxOutputBytes=4194304,
                  cleanupSeconds=10)
    return dict(portId=registration["id"], executionRequestId=descriptor["executionId"],
                resourceHandle=runtime.get("resourceHandle") or "resource:" + descriptor["taskId"],
                scopeRef=runtime.get("scopeRef") or "scope:standalone", domainOperationId=runtime.get("operationId") or descriptor["executionId"],
                domainNodeRef="N-DEF-REVIEWER", controlGeneration=env.generation(),
                executionBinding=dict(profileDigest=profile["digest"], agent=binding["agent"], model=registration["model_ref"],
                                      modelVendor=mapping["model_vendor"], routeVendor=mapping.get("route_vendor"),
                                      credentialRef=binding["credentialRef"], configurationRevision=binding["configurationRevision"]),
                profile=copy.deepcopy(profile), connectionRef=binding["connectionRef"],
                credentialRevision=binding["credentialRevision"], transport=registration["transport"],
                effort=registration["effort"], constraints=[], grantRefs=copy.deepcopy(runtime.get("grantRefs") or []),
                decisionRef=runtime.get("decisionRef") or descriptor["authorityRef"], budget=budget,
                caller=request["caller"], invocation_authorization=request["invocation_authorization"],
                formal_review_authorized_by_owner=request["formal_review_authorized_by_owner"])


def read_published(worktree, request, *, stage="task"):
    """legacy-git publication in the task worktree; archive-v1 read-back is reported as unknown.

    stage selects the round directory; feature-t5 reads its impl rounds with stage="impl".
    """
    mechanism = Path(worktree) / "mechanisms/review-channel"
    if str(mechanism) not in sys.path:
        sys.path.insert(0, str(mechanism))
    import review_channel_inputs as I
    import review_channel_verdict as V
    import review_evidence as E
    if E.storage_mode(str(worktree)) != "legacy-git":
        return None
    tracked = "tasks/%s/reviews/%s-%s" % (request["task_record"], stage, request["round"])
    receipt_rel = tracked + "/receipt-%s.json" % request["round"]
    verdict_rel = tracked + "/" + I.verdict_filename(request["subject"], request["round"])
    receipt_path = Path(worktree) / receipt_rel
    if not receipt_path.is_file():
        return None
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw)
    outcome = dict(classification=receipt.get("classification"), failureCode=receipt.get("failure_code"), receipt=receipt,
                   receiptRef=dict(kind="legacy-git-working", path=receipt_rel, sha256=sha256(receipt_raw)))
    verdict_path = Path(worktree) / verdict_rel
    if verdict_path.is_file():
        raw = verdict_path.read_bytes()
        block, _json, _narrative = V.parse_published(raw)
        outcome.update(verdict=block, verdictSha256=sha256(raw),
                       evidenceRef=dict(kind="legacy-git-working", path=verdict_rel, sha256=sha256(raw)),
                       published=dict(verdict_path=verdict_rel, receipt_path=receipt_rel))
    return outcome


async def channel_review_runner(descriptor, env, port, binding, registration, mapping):
    """Production: the governed channel runner via ProductReview in the task worktree."""
    worktree = Path(descriptor["input"]["worktree"])
    mechanism = worktree / "mechanisms/review-channel"
    if str(mechanism) not in sys.path:
        sys.path.insert(0, str(mechanism))
    import review_channel as C
    import review_evidence as E
    from execution.bridge import ProductReview
    request = request_document(descriptor, descriptor["input"].get("formalFactId"))
    if E.storage_mode(str(worktree)) != "legacy-git":
        request["request_schema"] = "review-channel-request/v5"
    request_dir = worktree / "tasks" / descriptor["taskId"] / "attempts" / "definition-requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / ("task-%s.json" % request["round"])
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    intent = intent_document(descriptor, env, registration, mapping, binding, request)
    bridge = ProductReview(port, intent, lambda: [])
    options = C.Options()
    options.repo_root, options.request, options.reemit = str(worktree), str(request_path), True
    code = await bridge.review("review", options)
    outcome = read_published(worktree, request)
    if outcome is None:
        return dict(classification="unknown", failureCode="channel-result-not-read", runnerCode=code,
                    reports=bridge.reports[-3:])
    outcome["runnerCode"] = code
    return outcome


def policy_context(descriptor):
    """Request keys feature-t6's review-release evaluation needs besides the intent (its design, 评估对象)."""
    data = descriptor["input"]
    candidate = data["candidate"]
    author = data["author"]
    context = dict(object=dict(kind="definition", path=candidate["path"], commit=candidate["commit"],
                               bytes=candidate["bytes"], sha256=candidate["sha256"]),
                   authorExecutionRefs=[], review=dict(stage="task", maxRounds=None, roundExtensions=[]),
                   maxCalls=data.get("maxCalls", 1), round=int(data["round"][1:]), attemptId=descriptor["attemptId"],
                   declaredAuthors=dict(vendors=[] if author["humanOnly"] else [author["vendor"]], humanOnly=author["humanOnly"]))
    return lambda: copy.deepcopy(context)


class ReviewExecutor:
    """review purpose: material check, port construction, runner call; query-only on resume."""

    def __init__(self, runner, port_factory):
        self.runner, self.port_factory = runner, port_factory

    async def __call__(self, descriptor, env):
        check_materials(descriptor)
        spool = Path(descriptor["input"]["worktree"]) / "tasks" / descriptor["taskId"] / "attempts" / "local-execution"
        port, binding = self.port_factory(env, descriptor["taskId"], "review", spool=spool, context=policy_context(descriptor))
        registration, mapping = port.registration, port.mapping
        return await self.runner(descriptor, env, port, binding, registration, mapping)

    async def query(self, descriptor, env):
        request = request_document(descriptor, descriptor["input"].get("formalFactId"))
        query = getattr(self.runner, "query", None)
        if query is not None:
            return await query(descriptor, env)
        found = await asyncio.to_thread(read_published, descriptor["input"]["worktree"], request)
        return found or dict(classification="unknown", failureCode="execution-resumed-unknown")


async def ruling_executor(descriptor, env):
    data = descriptor["input"]
    try:
        return await asyncio.to_thread(rulings.write, data["worktree"], data["branch"], data["base"], descriptor["taskId"],
                                       data["items"], data["message"])
    except DefinitionRejection as exc:
        return dict(state="not-written", code=exc.code, reason=exc.reason())


# A ruling write is idempotent by construction (it reads the branch first), so resuming it is a query.
ruling_executor.query = ruling_executor
