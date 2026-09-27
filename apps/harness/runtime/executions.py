"""Purpose-agnostic execution layer and production execution-port wiring (feature-t3, reused by feature-t4).

Why not the acceptance `drain()`: drain runs synchronously inside `transaction()` on the caller's
thread. In serve-stdio that caller is a dispatcher coroutine on the event loop, while a review needs
ProductReview's worker thread to send Host calls back onto that very loop (run_coroutine_threadsafe).
Waiting for a review inside drain would therefore block the loop against itself and stop query and
cancel traffic for the whole review (FR-62). This layer instead schedules each persisted execution
descriptor as an asyncio task on the loop, and every start and settlement is its own domain
transaction.

Descriptors are domain state (`executionDescriptors`), created by domain commands inside the
transaction that accepted the operation. They carry data only; the executor is looked up by
purpose. A descriptor found `running` after a restart is never executed again: its executor is
asked to query the same request, and an unknown answer settles as unknown with the reservation held.

The production port factory takes the review registration from the live review-channel Registry;
other purposes pass their product-side registration objects by keyword (Assistant OD-399). The
program identity is rediscovered per execution by the port and recorded, never used as a
registration precondition or an allow-list. The coding-implementer purpose (feature-t4) is built from
its product-side registration: the port instance carries that purpose, embedded discovery rediscovers
the program identity of the trusted launch configuration's launcher on every call, and the standalone
binding is read from the registration itself, not from a Registry `applicability` block.
"""
import asyncio
import copy
import importlib
import traceback

from domain.definition import review as definition_review
from domain.definition.results import (
    AUTHORIZER_UNAVAILABLE, EXECUTION_BINDING_UNAVAILABLE, DefinitionRejection,
)

PENDING, RUNNING = "pending", "running"


class Environment:
    """What an executor may use: the entry, the domain, the current control generation and the Host."""

    def __init__(self, entry, domain, generation, host=None, config=None, repository_root=None, spool=None):
        self.entry, self.domain, self._generation = entry, domain, generation
        self.host, self.config = host, config or {}
        self.repository_root = repository_root or getattr(domain, "repository", None)
        self.spool = spool

    def generation(self):
        return self._generation() if callable(self._generation) else self._generation


PORT_ENTRY = {"runtime": "embedded", "cli": "standalone"}  # feature-t6 names the entries by port mode
SUBJECTS = {"review": "review-release", "coding-implementer": "implement-release"}


def production_authorizer(domain, task_id, subject, entry, generation, *, context=None, authority_ref=None):
    """feature-t6 `domain/policy/authorize.py` callback factory; absent means no release (fail closed).

    Five positional parameters as feature-t6 fixed them (entry is the port mode, generation a no-argument
    callable); context is a no-argument callable returning the request keys besides the intent;
    authority_ref, when given, is the locator of the authority that initiates the evaluation.
    """
    try:
        module = importlib.import_module("domain.policy.authorize")
    except ImportError as exc:
        raise DefinitionRejection(AUTHORIZER_UNAVAILABLE, "feature-t6 authorization callback not installed",
                                  module="domain.policy.authorize") from exc
    if authority_ref is None:
        return module.execution_authorizer(domain, task_id, subject, entry, generation, context=context)
    return module.execution_authorizer(domain, task_id, subject, entry, generation, context=context,
                                       authority_ref=authority_ref)


def host_binding(config, port_id):
    """Host connection facts for an embedded port come only from the trusted launch configuration."""
    bindings = (config or {}).get("executionBindings") or {}
    binding = bindings.get(port_id)
    required = ("connectionRef", "credentialRef", "credentialRevision", "configurationRevision", "agent", "protocolProvider")
    if not isinstance(binding, dict) or any(not isinstance(binding.get(k), str) or not binding.get(k) for k in required):
        raise DefinitionRejection(EXECUTION_BINDING_UNAVAILABLE,
                                  "the trusted launch configuration carries no complete execution binding for this port",
                                  portId=port_id, required=list(required))
    return copy.deepcopy(binding)


def build_port(env, task_id, purpose, *, registration=None, mapping=None, authorizer=production_authorizer,
               subject=None, spool=None, context=None, authority_ref=None, worktree=None):
    """Production execution-port factory. review: registration from the live Registry; other purposes pass theirs."""
    from execution.host import HostExecutionPort
    from execution.local import LocalExecutionPort
    from execution.port import ExecutionDiscovery
    if purpose == "review" and registration is None:
        registration, mapping, _revision = definition_review.select_port(env.repository_root, env.entry)
    if registration is None or mapping is None:
        raise DefinitionRejection("PORT_NOT_REGISTERED", "no registration was given for this execution purpose", purpose=purpose)
    extra = dict(context=context) if authority_ref is None else dict(context=context, authority_ref=authority_ref)
    authorize = authorizer(env.domain, task_id, subject or SUBJECTS.get(purpose, purpose), PORT_ENTRY[env.entry],
                           env.generation, **extra)
    if purpose == IMPLEMENTER:
        return implementer_port(env, registration, mapping, authorize, worktree)
    if env.entry == "runtime":
        binding = host_binding(env.config, registration["id"])

        async def discover():
            return ExecutionDiscovery(copy.deepcopy(registration["profile"]), binding["connectionRef"], registration["provider"],
                                      binding["protocolProvider"], binding["configurationRevision"])
        return HostExecutionPort(env.host, env.domain, registration, mapping, discover, authorize), binding
    binding = dict(connectionRef="standalone:" + registration["id"], credentialRef="standalone:" + registration["id"],
                   credentialRevision=registration["applicability"]["credentialRevision"],
                   configurationRevision=registration["applicability"]["configurationRevision"],
                   agent=registration.get("provider"), protocolProvider="")

    async def discover():
        return ExecutionDiscovery(copy.deepcopy(registration["profile"]), binding["connectionRef"], registration["provider"],
                                  "", binding["configurationRevision"])
    port = LocalExecutionPort(env.domain, env.generation(), env.repository_root, spool or env.spool, registration, mapping,
                              discover, authorize)
    return port, binding


IMPLEMENTER = "coding-implementer"


def implementer_port(env, registration, mapping, authorize, worktree):
    """feature-t4 coding-implementer port from the product-side registration (Assistant OD-399).

    embedded: HostExecutionPort with purpose coding-implementer; the connection facts and the Agent launcher
    come from the trusted launch configuration, and discovery rediscovers the launcher's program identity
    (resolved path, binary digest, `--version`) on every call. standalone: ImplementerLocalExecutionPort with
    the binding read from the registration's own revisions; no Registry `applicability` is involved.
    """
    from execution.host import HostExecutionPort
    from execution.implementer_local import ImplementerLocalExecutionPort, discover_program, make_discovery
    from execution.port import ExecutionDiscovery, ExecutionError
    if env.entry == "runtime":
        binding = host_binding(env.config, registration["id"])
        launcher = binding.get("launcher")

        async def discover():
            program = discover_program(launcher) if isinstance(launcher, str) and launcher else None
            if program is None:
                raise ExecutionError("execution-port-identity-unverified")
            profile = dict(copy.deepcopy(registration["profile"]), programIdentity=program)
            return ExecutionDiscovery(profile, binding["connectionRef"], registration["provider"],
                                      binding["protocolProvider"], binding["configurationRevision"])
        return HostExecutionPort(env.host, env.domain, registration, mapping, discover, authorize, purpose=IMPLEMENTER), binding
    if worktree is None:
        raise DefinitionRejection("PORT_NOT_REGISTERED", "a standalone implementer port needs the task worktree")
    binding = dict(connectionRef="standalone:" + registration["id"], credentialRef="credential:native-login",
                   credentialRevision=registration["credentialRevision"],
                   configurationRevision=registration["configurationRevision"], agent=registration["agent"],
                   protocolProvider="")
    port = ImplementerLocalExecutionPort(env.domain, env.generation(), registration,
                                         make_discovery(registration, binding["connectionRef"]), authorize,
                                         worktree=worktree, executions_root=env.domain.store.coordination / "executions")
    return port, binding


def production_executors():
    from domain.definition import dispatch
    from domain.implement_verify.executors import VERIFY_PURPOSE, ImplementExecutor, VerifyExecutor
    from domain.validation.review import ChangeReviewExecutor, channel_change_review_runner
    from domain.publish.executor import PublishExecutor, QueryExecutor
    return {"review": dispatch.ReviewExecutor(dispatch.channel_review_runner, build_port),
            "ruling-write": dispatch.ruling_executor, IMPLEMENTER: ImplementExecutor(build_port),
            VERIFY_PURPOSE: VerifyExecutor(),
            # feature-t5: the Validate Change impl-round review and its finding-disposition ruling write.
            "change-review": ChangeReviewExecutor(channel_change_review_runner, build_port),
            "validation-ruling-write": dispatch.ruling_executor,
            # feature-t7: the publish operation and its same-operation query (not an Agent call; no ExecutionPort).
            "publish": PublishExecutor(), "publish-query": QueryExecutor()}


class ExecutionLayer:
    """Schedules persisted execution descriptors on the running event loop; purpose-agnostic."""

    def __init__(self, domain, environment, executors=None):
        self.domain, self.env = domain, environment
        self.executors = executors if executors is not None else production_executors()
        self.inflight = {}
        self.accepting = True
        self.failures = []

    def schedule(self, resume=False):
        """Start every pending descriptor not already in flight; with resume, query running ones instead."""
        if not self.accepting or not hasattr(self.domain, "executions"):
            return []
        started = []
        for descriptor in self.domain.executions():
            execution_id = descriptor["executionId"]
            if execution_id in self.inflight:
                continue
            if descriptor["status"] == PENDING or (resume and descriptor["status"] == RUNNING):
                query_only = descriptor["status"] == RUNNING
                task = asyncio.get_running_loop().create_task(self._run(descriptor, query_only))
                self.inflight[execution_id] = task
                task.add_done_callback(lambda _t, key=execution_id: self.inflight.pop(key, None))
                started.append(execution_id)
        return started

    async def _run(self, descriptor, query_only):
        execution_id = descriptor["executionId"]
        executor = self.executors.get(descriptor["purpose"])
        try:
            if executor is None:
                outcome = dict(classification="unknown", failureCode="execution-layer-no-executor")
            elif query_only:
                query = getattr(executor, "query", None)
                outcome = await query(descriptor, self.env) if query else dict(classification="unknown",
                                                                                failureCode="execution-resumed-unknown")
            else:
                self.domain.start_execution(execution_id, self.env.generation())
                outcome = await executor(descriptor, self.env)
        except asyncio.CancelledError:
            outcome = dict(classification="unknown", failureCode="execution-layer-cancelled")
            await asyncio.to_thread(self._settle, execution_id, outcome)
            raise
        except DefinitionRejection as exc:
            outcome = dict(classification="preflight_failed", failureCode=exc.code, reason=exc.reason())
        except Exception as exc:  # the layer never loses a settlement
            self.failures.append(dict(executionId=execution_id, error=type(exc).__name__,
                                      trace=traceback.format_exc(limit=4)))
            outcome = dict(classification="unknown", failureCode="execution-layer-exception", error=type(exc).__name__)
        await asyncio.to_thread(self._settle, execution_id, outcome)

    def _settle(self, execution_id, outcome):
        return self.domain.settle_execution(execution_id, outcome, self.env.generation())

    def cancel(self, execution_id):
        task = self.inflight.get(execution_id)
        if task is not None:
            task.cancel()
            return True
        return False

    def stop(self):
        self.accepting = False
        for task in list(self.inflight.values()):
            task.cancel()

    async def idle(self):
        while self.inflight:
            await asyncio.gather(*list(self.inflight.values()), return_exceptions=True)


def run_pending(domain, environment, executors=None):
    """standalone CLI: run the pending descriptors to completion in this process's own event loop."""
    async def main():
        layer = ExecutionLayer(domain, environment, executors)
        layer.schedule(resume=True)
        await layer.idle()
        return layer.failures
    return asyncio.run(main())
