"""Change review execution (outside any domain transaction), on feature-t3's execution layer.

The executor starts the attempt in its own transaction, rebuilds the reviewed materials and proves they
are byte-identical to the identities fixed at dispatch, builds the review port through feature-t3's
production factory (feature-t6's authorization callback injected, review-release for a candidate-change
object) and calls the runner. Production passes `channel_change_review_runner`, which materializes the
materials under the task's ignored attempts area and runs the one governed channel runner (FR-40) as an
impl round via feature-t17's ProductReview; tests pass an explicitly synthetic runner. The execution
budget in the port intent is exactly tool calls, run time, output bytes and cleanup time (FR-62); there is
no monetary cost field. The program identity is rediscovered by the port on every execution and recorded,
never used as a registration precondition or an allow-list (Assistant OD-399).
"""
import asyncio
import copy
import json
from pathlib import Path
import sys

from domain.implement_verify import seams
from domain.validation import dispatch, materials, records
from domain.validation.results import ValidationRejection
from domain.workflow import progression

STAGE = "impl"
QUESTIONS = ("Q-CHANGE", "Q-UPSTREAM", "Q-PREMISE", "Q-REFERENCE", "Q-BOUNDARY")
CHECK_SURFACES = ("impl round five questions. Under Q-CHANGE assess every Goal Condition and every Acceptance "
                  "Criterion of the finalized Definition (reference definition.md) against the candidate change "
                  "document, cite evidence_refs for each, and raise a finding for each one that is not met.")


def round_of(state, descriptor):
    record = records.ledger(state, descriptor["taskId"])
    return next(r for r in record["rounds"] if r["executionId"] == descriptor["executionId"])


def authors(state, round_record):
    """artifact_author.authors from the author executions: agent, actual model and the product-side vendor."""
    out = []
    for execution_id in round_record["authorExecutionRefs"]:
        port = state.get("executionReservations", {}).get(execution_id) or {}
        binding = ((port.get("intent") or {}).get("executionBinding") or {})
        observed = (port.get("observations") or [{}])[-1].get("physical_execution") or {}
        model = (observed.get("actualBinding") or {}).get("model") or binding.get("model")
        agent = binding.get("agent")
        vendor = seams.vendor_of(state, agent, model) if agent and model else None
        row = dict(tool=str(agent or "unknown").replace("agent:", ""), model=str(model or "unknown"), vendor=vendor or "unknown")
        if row not in out:
            out.append(row)
    return out


def request_document(state, descriptor, round_record, document_path, reference_paths):
    data = descriptor["input"]
    request = {"request_schema": "review-channel-request/v4", "subject": data["subject"], "stage": STAGE,
               "round": round_record["round"], "caller": "harness-plane-domain", "task_record": descriptor["taskId"],
               "artifact_author": {"human_only": False, "authors": authors(state, round_record)},
               "inputs": {"candidates": [document_path], "references": list(reference_paths)},
               "review_brief": {"background": "Validate Change of %s: candidate %s against its finalized Definition"
                                % (descriptor["taskId"], round_record["candidateCommit"]),
                                "check_surfaces": CHECK_SURFACES, "evidence_limits": [], "accepted_residuals": []},
               "invocation_authorization": descriptor["authorityRef"],
               "formal_review_authorized_by_owner": bool(round_record.get("formalFactId"))}
    if round_record.get("previousRound"):
        request["previous_round"] = copy.deepcopy(round_record["previousRound"])
        request["review_brief"]["remediation_statement"] = round_record.get("remediationStatement") or "Implementer remediation"
    if round_record.get("roundExtensions"):
        request["round_extensions"] = copy.deepcopy(round_record["roundExtensions"])
    return request


def intent_document(descriptor, env, registration, mapping, binding, request):
    data = descriptor["input"]
    runtime = data.get("runtime") or {}
    profile = registration["profile"]
    budget = dict(maxToolCalls=profile["maxToolCalls"], maxRunSeconds=profile["maxRunSeconds"], maxOutputBytes=4194304,
                  cleanupSeconds=10)
    return dict(portId=registration["id"], executionRequestId=descriptor["executionId"],
                resourceHandle=runtime.get("resourceHandle") or "resource:" + descriptor["taskId"],
                scopeRef=runtime.get("scopeRef") or "scope:standalone",
                domainOperationId=runtime.get("operationId") or descriptor["executionId"], domainNodeRef=dispatch.REVIEWER,
                controlGeneration=env.generation(),
                executionBinding=dict(profileDigest=profile["digest"], agent=binding["agent"], model=registration["model_ref"],
                                      modelVendor=mapping["model_vendor"], routeVendor=mapping.get("route_vendor"),
                                      credentialRef=binding["credentialRef"], configurationRevision=binding["configurationRevision"]),
                profile=copy.deepcopy(profile), connectionRef=binding["connectionRef"],
                credentialRevision=binding["credentialRevision"], transport=registration["transport"],
                effort=registration["effort"], constraints=[], grantRefs=copy.deepcopy(runtime.get("grantRefs") or []),
                decisionRef=runtime.get("decisionRef") or descriptor["authorityRef"], budget=budget,
                caller=request["caller"], invocation_authorization=request["invocation_authorization"],
                formal_review_authorized_by_owner=request["formal_review_authorized_by_owner"])


def policy_context(round_record):
    """Request keys of feature-t6's review-release evaluation besides the intent (candidate-change object)."""
    context = dict(object=dict(kind="candidate-change", path=round_record["document"]["path"],
                               commit=round_record["candidateCommit"]),
                   authorExecutionRefs=list(round_record["authorExecutionRefs"]),
                   review=dict(stage=STAGE, maxRounds=None, roundExtensions=copy.deepcopy(round_record["roundExtensions"])),
                   maxCalls=round_record.get("maxCalls", 1), round=int(round_record["round"][1:]),
                   attemptId=round_record["attemptId"])
    return lambda: copy.deepcopy(context)


def rebuild(state, descriptor, round_record):
    task = dict(state["tasks"][descriptor["taskId"]], taskId=descriptor["taskId"])
    built = materials.build(descriptor["input"]["worktree"], task, round_record["round"], round_record["baseCommit"],
                            round_record["candidateCommit"], _verification(state, descriptor["taskId"], round_record),
                            round_record["finalization"]["candidate"])
    materials.check(dict(document={k: round_record["document"][k] for k in ("name", "bytes", "sha256")},
                         references=round_record["references"]), built)
    return built


def _verification(state, task_id, round_record):
    from domain.implement_verify import steps
    return steps.ledger(state, task_id)["verifications"][round_record["verification"]["verificationId"]]


async def channel_change_review_runner(descriptor, env, port, binding, registration, mapping, *, built, round_record):
    """Production: the governed channel runner, impl round, via ProductReview in the task worktree."""
    worktree = Path(descriptor["input"]["worktree"])
    mechanism = worktree / "mechanisms/review-channel"
    if str(mechanism) not in sys.path:
        sys.path.insert(0, str(mechanism))
    import review_channel as C
    import review_evidence as E
    from execution.bridge import ProductReview
    from domain.definition.dispatch import read_published, unread_outcome
    document_path, reference_paths = materials.materialize(worktree, descriptor["taskId"], round_record["round"], built)
    request = request_document(env.domain.read(), descriptor, round_record, document_path, reference_paths)
    if E.storage_mode(str(worktree)) != "legacy-git":
        request["request_schema"] = "review-channel-request/v5"
    request_path = worktree / materials.directory(descriptor["taskId"], round_record["round"]) / ("request-a%d.json" % round_record["attempt"])
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    intent = intent_document(descriptor, env, registration, mapping, binding, request)
    bridge = ProductReview(port, intent, lambda: [])
    options = C.Options()
    options.repo_root, options.request, options.reemit = str(worktree), str(request_path), True
    code = await bridge.review("review", options)
    outcome = read_published(worktree, request, stage=STAGE)
    if outcome is None:
        return unread_outcome(bridge, code)
    outcome["runnerCode"] = code
    return outcome


class ChangeReviewExecutor:
    """change-review purpose: start, material proof, port construction, runner call; query-only on resume."""

    def __init__(self, runner, port_factory):
        self.runner, self.port_factory = runner, port_factory

    async def __call__(self, descriptor, env):
        task_id = descriptor["taskId"]

        def begin(state):
            inst = progression.instance(state, task_id)
            return dispatch.start(state, env.domain.topology(inst), task_id, descriptor["executionId"])
        await asyncio.to_thread(env.domain.transaction, env.generation(), begin)
        state = env.domain.read()
        round_record = round_of(state, descriptor)
        try:
            built = rebuild(state, descriptor, round_record)
        except ValidationRejection as exc:
            return dict(classification="preflight_failed", failureCode="review-material-mismatch", reason=exc.reason())
        spool = Path(descriptor["input"]["worktree"]) / "tasks" / task_id / "attempts" / "local-execution"
        port, binding = self.port_factory(env, task_id, "review", spool=spool, context=policy_context(round_record))
        registration, mapping = port.registration, port.mapping
        return await self.runner(descriptor, env, port, binding, registration, mapping, built=built,
                                 round_record=round_record)

    async def query(self, descriptor, env):
        query = getattr(self.runner, "query", None)
        if query is not None:
            return await query(descriptor, env)
        from domain.definition.dispatch import read_published
        state = env.domain.read()
        round_record = round_of(state, descriptor)
        request = dict(task_record=descriptor["taskId"], round=round_record["round"], subject=descriptor["input"]["subject"])
        found = await asyncio.to_thread(read_published, descriptor["input"]["worktree"], request, stage=STAGE)
        return found or dict(classification="unknown", failureCode="execution-resumed-unknown")
