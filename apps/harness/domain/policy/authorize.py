"""Production authorization callback for the feature-t17 execution ports (feature-t6).

HostExecutionPort.authority() awaits the injected `authorize(intent)` at preflight, before release,
and on query, cancel and checkpoint (execution/host.py). This factory builds that callback: every call
runs the Policy Gate through the same Domain Core command ("policy-evaluate") the standalone CLI uses,
under the control generation the port itself uses, and returns an ExecutionAuthorization only for an
ALLOW decision produced by the Policy Gate. Anything else raises ExecutionError before any release.

Constructing ports and injecting this callback in production is feature-t3's wiring (seam ruling S-03);
feature-t4 reuses it. This module does not construct ports.
"""
import copy

from domain.policy import rules
from domain.policy.results import ALLOW, DENY, PolicyInputInvalid
from domain.workflow.progression import POLICY_PRODUCER
from domain.workflow.results import WorkflowRejection
from execution.port import ExecutionAuthorization, ExecutionError, identity, sha

AUTHORITY_REF = "policy-gate:execution-authorizer"
CLASSIFICATION = "preflight_failed"


def execution_authorizer(domain, task_id, subject, entry, generation, *, context=None, authority_ref=AUTHORITY_REF):
    """Return `async authorize(intent)` bound to one task, subject, entry and control generation source.

    generation is a no-argument callable returning the control generation the port's own
    transactions use; context is a no-argument callable returning the request keys other than the
    intent (reviewed object, author execution references, review settings, maxCalls, ...).
    """
    if subject not in (rules.REVIEW_RELEASE, rules.IMPLEMENT_RELEASE):
        raise ValueError("execution authorization covers review-release and implement-release only")
    if entry not in rules.ENTRIES or not callable(generation):
        raise ValueError("entry must be embedded or standalone and generation a callable")

    async def authorize(intent):
        extra = dict(context()) if context is not None else {}
        request = dict(schema=rules.REQUEST_SCHEMA, subject=subject, taskId=task_id, entry=entry,
                       portId=intent.get("portId"), intent=copy.deepcopy(intent), **extra)
        payload = dict(taskId=task_id, authorityRef=authority_ref, request=request,
                       call=dict(executionRequestId=intent.get("executionRequestId"), scopeRef=intent.get("scopeRef")))
        try:
            outcome = domain.run("policy-evaluate", payload, generation=generation())
        except PolicyInputInvalid as exc:
            raise ExecutionError("policy-not-determinable", CLASSIFICATION) from exc
        except WorkflowRejection as exc:
            raise ExecutionError("policy-not-determinable", CLASSIFICATION) from exc
        if outcome.get("conclusion") != ALLOW:
            code = "policy-denied" if outcome.get("conclusion") == DENY else "policy-not-determinable"
            raise ExecutionError(code, CLASSIFICATION)
        fact = domain.store.read()["tasks"][task_id]["workflowInstance"]["facts"].get(outcome["factId"]) or {}
        if fact.get("producer") != POLICY_PRODUCER or (fact.get("payload") or {}).get("conclusion") != ALLOW:
            raise ExecutionError("policy-not-determinable", CLASSIFICATION)
        derived = fact["payload"]["derived"]
        vendors = tuple(derived.get("authorVendors") or ())
        evidence = tuple(derived.get("authorEvidenceRefs") or ()) or (outcome["factId"],)
        return ExecutionAuthorization(intent_digest=identity(intent),
                                      invocation_sha256=sha(intent["invocation_authorization"].encode()),
                                      caller=intent["caller"], author_vendors=vendors, author_evidence_refs=evidence,
                                      owner_formal=bool(derived.get("ownerFormal")), max_calls=request["maxCalls"],
                                      authorization_ref=outcome["factId"], human_only=not vendors)

    return authorize
