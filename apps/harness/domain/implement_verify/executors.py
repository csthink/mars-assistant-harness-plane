"""Executors that bracket external work between domain transactions (spec FR-62; seam ruling S-02).

The implementer purpose runs on feature-t3's execution layer (runtime/executions.py): implement-dispatch
records a data-only descriptor (purpose coding-implementer, entry cli or runtime by port mode), the layer
of the owning entry schedules it and calls ImplementExecutor, which builds the port through feature-t3's
production factory `build_port` (feature-t6 authorize callback injected there, S-03, S-11) and drives
run_implement(); the layer then settles the descriptor through settle_descriptor(). A descriptor found
running after a restart is only queried (ImplementExecutor.query), never executed again.

run_implement(): start transaction -> seal inputs -> port.reserve (persisted before any effect) ->
port.execute (preflight, release, query of the original request on lost answers) -> poll the same
request until a terminal fact or the budget window ends -> settle transaction that re-reads everything.

run_verify(): prepare transaction -> run each selected check in the worktree -> settle transaction.
Verify is not an Agent call and runs in the calling entry.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time

from domain.workflow import progression
from domain.workflow.results import TOPOLOGY_UNREADABLE, WorkflowRejection
from domain.implement_verify import checks, implement, registration, seams, settlement, verify, worktree
from domain.implement_verify.results import (
    DISPATCHED, IDEMPOTENT_REPLAY, IMPLEMENT_COMPLETED, PENDING, REGISTRY_ENTRY_MISSING, RESULT_UNKNOWN, STOP_UNCONFIRMED,
    VENDOR_MAPPING_UNKNOWN, VERIFY_FAIL, VERIFY_NOT_APPLICABLE, VERIFY_PASS, ImplementVerifyRejection,
)
from domain.implement_verify.steps import ledger as steps_ledger
from execution.port import ExecutionError, sha
from runtime.protocol import Fault

INSTRUCTION = """Implement the finalized Task Definition supplied as material `definition.md`.

- Work only inside the current working directory; it is the task worktree bound to branch `{branch}`.
- Commit the complete candidate change on that branch before you finish and leave the worktree clean.
- Do not push, do not create or change any other branch or worktree, and do not rewrite history.
- The Definition is the only goal authority; `design.md`, when present, is non-binding engineering input.
{remediation}
When done, reply with a short completion declaration. It is recorded as an implementation claim only;
deterministic Verify checks decide PASS or FAIL.
"""
REMEDIATION = ("- This is a remediation run: `verification.json` holds the previous Verification Result and its "
               "findings. Fix the candidate so the prescribed checks pass; the Definition does not change.")


def transact(domain, generation, task_id, function):
    """Run function(state, topology) as one domain transaction under the entry's control generation."""
    def callback(state):
        bound = domain.topology(progression.instance(state, task_id))
        if bound is None:
            raise WorkflowRejection(TOPOLOGY_UNREADABLE, "the bound Workflow topology could not be read")
        return function(state, bound)
    return domain.transaction(generation, callback)


def seal(record, root):
    """Seal the Definition, optional design and remediation inputs; returns (seal_dir, instruction, manifest)."""
    final = record["finalization"]["candidate"]
    path = Path(record["worktree"])
    materials = [("definition.md", worktree.blob(path, final["commit"], final["path"]))]
    if hashlib.sha256(materials[0][1]).hexdigest() != final["sha256"]:
        raise ImplementVerifyRejection(implement.POSITION_NOT_APPLICABLE, "finalized Definition bytes changed")
    design = str(Path(final["path"]).parent / "design.md")
    probe = worktree.git(path, "cat-file", "-e", final["commit"] + ":" + design, check=False)
    if probe.returncode == 0:
        materials.append(("design.md", worktree.blob(path, final["commit"], design)))
    if record.get("remediation"):
        materials.append(("verification.json", json.dumps(record["remediation"], ensure_ascii=False,
                                                           sort_keys=True).encode()))
    directory = Path(tempfile.mkdtemp(prefix="hp-implement-seal-", dir=root))
    entries = []
    for name, raw in materials:
        (directory / name).write_bytes(raw)
        entries.append(dict(bundle_name=name, bytes=len(raw), sha256=sha(raw)))
    manifest = dict(inputs=entries, manifest_sha256=sha(json.dumps(entries, ensure_ascii=False, sort_keys=True,
                                                                     separators=(",", ":"), allow_nan=False).encode()))
    instruction = INSTRUCTION.format(branch=record["branch"],
                                     remediation=REMEDIATION if record.get("remediation") else "").encode()
    return directory, instruction, manifest


def intent_for(state, record, entry, context):
    """The execution request; connection fields come from the entry's trusted context, never from a caller."""
    vendor = seams.vendor_of(state, entry["agent"], entry["model_ref"])
    if vendor is None:
        raise ImplementVerifyRejection(VENDOR_MAPPING_UNKNOWN, "the registered agent and model have no vendor in the "
                                       "product-side mapping", agent=entry["agent"], model=entry["model_ref"])
    profile = copy.deepcopy(entry["profile"])
    return dict(portId=entry["id"], executionRequestId=record["executionRequestId"],
                resourceHandle=context["resourceHandle"], scopeRef=context["scopeRef"],
                domainOperationId=record["executionRequestId"], domainNodeRef=implement.IMPLEMENT_NODE,
                controlGeneration=context["generation"],
                executionBinding=dict(profileDigest=profile["digest"], agent=entry["agent"], model=entry["model_ref"],
                                      modelVendor=vendor, routeVendor=None, credentialRef=context["credentialRef"],
                                      configurationRevision=entry["configurationRevision"]),
                profile=profile, connectionRef=context["connectionRef"], credentialRevision=entry["credentialRevision"],
                transport=entry["transport"], effort=entry["effort"], constraints=[], grantRefs=context["grantRefs"],
                decisionRef=context.get("decisionRef"), budget=copy.deepcopy(record["budget"]), caller="hp-implement",
                invocation_authorization=record["authorityRef"] + " / " + str(record["finalization"]["ruling"].get("ruling")),
                targetBinding=context.get("targetBinding"))


async def run_implement(domain, generation, task_id, execution_id, *, port, context, seal_root, poll=0.05, grace=15):
    """Drive one dispatched execution to a settled outcome; every committed fact is re-read by settle()."""
    record = implement.descriptor(domain.read(), task_id, execution_id)
    if record["status"] == "settled":
        return await refresh(domain, task_id, record, port)
    transact(domain, generation, task_id, lambda s, t: implement.start(s, t, task_id, execution_id, revision=s["revision"]))
    state = domain.read()
    record = implement.descriptor(state, task_id, execution_id)
    entry = registration.resolve(state, record["portId"])
    port_error = None
    try:
        if entry is None:
            raise ImplementVerifyRejection(REGISTRY_ENTRY_MISSING, "the registration was withdrawn before release",
                                           portId=record["portId"])
        intent = intent_for(state, record, entry, context)
        directory, instruction, manifest = seal(record, seal_root)
    except ImplementVerifyRejection as exc:
        # Nothing was reserved or released: a pre-release failure of this attempt.
        port_error = dict(code="pre-release:" + exc.code, classification="preflight_failed", detail=exc.reason())
    if port_error is None:
        try:
            reservation = port.reserve(intent, directory, instruction, manifest)
            outcome = await port.execute(reservation)
            deadline = time.monotonic() + record["budget"]["maxRunSeconds"] + record["budget"]["cleanupSeconds"] + grace
            while outcome.get("state") != "completed" and time.monotonic() < deadline:
                if settlement.classify(implement.port_record(domain.read(), execution_id))["kind"] != "pending":
                    break
                await asyncio.sleep(poll)
                outcome = await port.query(reservation)
        except ExecutionError as exc:
            port_error = dict(code=exc.code, classification=exc.classification)
        except Fault as exc:
            port_error = dict(code="fault:" + exc.code, classification="execution_port_failure")
    return transact(domain, generation, task_id,
                    lambda s, t: implement.settle(s, t, task_id, execution_id, revision=s["revision"],
                                                  port_error=port_error))


async def refresh(domain, task_id, record, port):
    """A settled but unresolved execution (stop unconfirmed, unknown): query the original request only.

    The port records the new physical observation in the domain state (for example the Host's automatic
    `stopped` after every escaped process exited); settlement is not changed here, the recovery
    assessment reads the refreshed facts. Nothing is started again.
    """
    reason = (record.get("settlement") or {}).get("reason")
    if reason not in ("STOP_UNCONFIRMED", "RESULT_UNKNOWN"):
        return dict(result="IDEMPOTENT_REPLAY", execution=copy.deepcopy(record))
    reservation = implement.port_record(domain.read(), record["executionRequestId"])
    if reservation is not None:
        try:
            await port.query(reservation)
        except (ExecutionError, Fault):
            pass
    physical = settlement.classify(implement.port_record(domain.read(), record["executionRequestId"]))
    return dict(result=PENDING, refreshed=True, execution=copy.deepcopy(record), physical=physical)


def run_verify(domain, generation, task_id, payload):
    """Prepare, run the selected checks outside any transaction, then settle."""
    prepared = transact(domain, generation, task_id,
                        lambda s, t: verify.prepare(s, t, task_id, payload, revision=s["revision"]))
    if prepared["result"] != PENDING:
        return prepared
    verification = prepared["verification"]
    path = worktree.bound(domain.read()["tasks"][task_id])
    results = [checks.run(check, path) for check in verification["checks"]]
    return transact(domain, generation, task_id,
                    lambda s, t: verify.settle(s, t, task_id, verification["verificationId"], results,
                                               revision=s["revision"]))


def execution_context(env, task_id, binding, runtime=None):
    """Trusted request context: connection facts from the port binding; scope, resource, grants and decision
    from the accepted Runtime Operation when the action came through the Runtime, else from the launch
    configuration (CLI dispatch executed by serve-stdio) or the standalone defaults."""
    configured = ((env.config or {}).get("executionBindings") or {}).get(binding.get("portId") or "", {})
    runtime = runtime or {}
    return dict(generation=env.generation(),
                scopeRef=runtime.get("scopeRef") or configured.get("scopeRef") or "scope:" + env.entry + ":" + task_id,
                resourceHandle=runtime.get("resourceHandle") or configured.get("resourceHandle") or "resource:" + task_id,
                connectionRef=binding["connectionRef"], credentialRef=binding["credentialRef"],
                grantRefs=copy.deepcopy(runtime.get("grantRefs") or []), decisionRef=runtime.get("decisionRef"),
                targetBinding=None)


def classification(result):
    """Descriptor classification for feature-t3's layer: unresolved physical facts stay unknown."""
    if result.get("reason") in (STOP_UNCONFIRMED, RESULT_UNKNOWN) or result.get("result") == PENDING:
        return "unknown"
    return "completed" if result.get("result") == IMPLEMENT_COMPLETED else "failed"


class ImplementExecutor:
    """coding-implementer purpose on feature-t3's execution layer."""

    def __init__(self, port_factory, seal_root=None):
        self.port_factory, self.seal_root = port_factory, seal_root

    def port(self, env, task_id, record):
        state = env.domain.read()
        entry = registration.resolve(state, record["portId"])
        if entry is None:
            raise ImplementVerifyRejection(REGISTRY_ENTRY_MISSING, "the registration was withdrawn before release",
                                           portId=record["portId"])
        task = state["tasks"][task_id]

        def context():
            final = seams.finalization(env.domain.read(), task_id)
            # Nothing to authorise against: feature-t6 then rejects the incomplete request.
            return seams.policy_context(final) if final is not None else dict(maxCalls=seams.MAX_CALLS)
        port, binding = self.port_factory(env, task_id, registration.PURPOSE, registration=entry,
                                          mapping=registration.mapping(entry), context=context,
                                          authority_ref=record["authorityRef"], worktree=task["worktree"])
        port.bind_result_scanner(port, lambda: [])
        return port, dict(binding, portId=entry["id"])

    def root(self, env):
        root = Path(self.seal_root) if self.seal_root else Path(env.domain.store.coordination) / "implement-seal"
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

    async def __call__(self, descriptor, env):
        task_id, execution_id = descriptor["taskId"], descriptor["executionId"]
        record = implement.descriptor(env.domain.read(), task_id, execution_id)
        try:
            port, binding = self.port(env, task_id, record)
        except ImplementVerifyRejection as exc:
            # Nothing was reserved or released: settle this attempt as a pre-release failure.
            result = await asyncio.to_thread(
                transact, env.domain, env.generation(), task_id,
                lambda s, t: _settle_start(s, t, task_id, execution_id, dict(code="pre-release:" + exc.code,
                                                                          classification="preflight_failed",
                                                                          detail=exc.reason())))
            return dict(classification="failed", result=result["result"], reason=result.get("reason"))
        runtime = (descriptor.get("input") or {}).get("runtime")
        result = await run_implement(env.domain, env.generation(), task_id, execution_id, port=port,
                                     context=execution_context(env, task_id, binding, runtime), seal_root=self.root(env))
        return dict(classification=classification(result), result=result["result"], reason=result.get("reason"))

    async def query(self, descriptor, env):
        """Restart: query the original request only; nothing is started again."""
        task_id, execution_id = descriptor["taskId"], descriptor["executionId"]
        record = implement.descriptor(env.domain.read(), task_id, execution_id)
        reservation = implement.port_record(env.domain.read(), execution_id)
        if reservation is not None and reservation.get("start_dispatched"):
            port, _binding = self.port(env, task_id, record)
            try:
                await port.query(reservation)
            except (ExecutionError, Fault):
                pass
        result = await asyncio.to_thread(
            transact, env.domain, env.generation(), task_id,
            lambda s, t: implement.settle(s, t, task_id, execution_id, revision=s["revision"]))
        return dict(classification=classification(result), result=result["result"], reason=result.get("reason"))


def _settle_start(state, topology, task_id, execution_id, port_error):
    implement.start(state, topology, task_id, execution_id, revision=state["revision"])
    return implement.settle(state, topology, task_id, execution_id, revision=state["revision"], port_error=port_error)


VERIFY_PURPOSE = "verify"


def verify_descriptor(state, task_id, verification, authority, revision, runtime):
    """A Runtime-accepted Verify: the checks run outside the transaction on the runtime entry's layer."""
    execution_id = verification["verificationId"]
    state.setdefault("executionDescriptors", {})[execution_id] = dict(
        executionId=execution_id, purpose=VERIFY_PURPOSE, taskId=task_id, status="pending",
        attemptId=verification["attemptId"], createdAt=progression.now(), createdRevision=revision, authorityRef=authority,
        result=None, lastError=None, entry="runtime",
        input=dict(kind="verify", verificationId=execution_id, runtime=copy.deepcopy(runtime)))
    return execution_id


class VerifyExecutor:
    """verify purpose on feature-t3's execution layer: the same checks and settlement as `verify run`."""

    async def __call__(self, descriptor, env):
        task_id, verification_id = descriptor["taskId"], descriptor["input"]["verificationId"]
        state = env.domain.read()
        verification = steps_ledger(state, task_id)["verifications"][verification_id]
        path = worktree.bound(state["tasks"][task_id])
        results = await asyncio.to_thread(lambda: [checks.run(check, path) for check in verification["checks"]])
        settled = await asyncio.to_thread(
            transact, env.domain, env.generation(), task_id,
            lambda s, t: verify.settle(s, t, task_id, verification_id, results, revision=s["revision"]))
        ok = settled["result"] in (VERIFY_PASS, VERIFY_FAIL)
        return dict(classification="completed" if ok else "failed", result=settled["result"])

    async def query(self, descriptor, env):
        """Restart: the checks are not re-run by the layer; the Verify node goes through recovery."""
        return dict(classification="unknown", result=RESULT_UNKNOWN, reason="verify-resumed-unknown")


def settle_descriptor(state, topology, descriptor, outcome):
    """feature-t3 layer settlement hook: the domain facts were committed by the executor already."""
    return dict(result=outcome.get("result") or outcome.get("failureCode"), reason=outcome.get("reason"),
                indeterminate=outcome.get("classification") == "unknown")


EXECUTION_SETTLE = {registration.PURPOSE: settle_descriptor, VERIFY_PURPOSE: settle_descriptor}
# Results that settle a Runtime Operation of this loop as succeeded; any other settles it failed or unknown.
OPERATION_SUCCEEDED = (IMPLEMENT_COMPLETED, VERIFY_PASS, VERIFY_FAIL, VERIFY_NOT_APPLICABLE, DISPATCHED,
                       IDEMPOTENT_REPLAY)
