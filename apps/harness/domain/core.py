"""The production Domain Core: the single domain writer behind both entries (feature-t2).

standalone CLI and the delegated serve-stdio Runtime enter here. They share one Domain Core, one
writer lock, one bootstrap and binding, one control generation and one formal state; the only
difference between them is the call protocol and how a trusted Human decision is obtained. Every
Workflow command both entries can issue runs through apply_command below, so neither entry can hold
a second rule set, a second state or a second writer protocol (spec FR-31, NFR-01).

This module installs the production DomainPort that replaces UnavailableDomain in serve-stdio. It
does not implement the definition or validation loops, the execution port, the Policy Gate or any
remote publication: those belong to feature-t3 through feature-t7 and consume the progression
surface delivered here. feature-t6 adds one command, "policy-evaluate", which records a Policy
Decision fact through the same writer and never moves the Workflow.
"""
import base64
import copy
import hashlib
import json

from domain import capability_schema, projection_stream
from domain.acceptance import projection as acceptance_projection
from domain.acceptance.gitrepo import GitAbsent, GitUnavailable, Repository
from domain.acceptance.runtime_binding import AcceptanceDomain, decision_authority
from domain.acceptance.schema import PAYLOAD_SCHEMA as ACCEPTANCE_SCHEMA, SCHEMA_ID as ACCEPTANCE_SCHEMA_ID
from domain.port import UnavailableDomain
from domain.store import Drift, LockUnavailable, RuntimeStore, StoreUnavailable
from domain.workflow import progression, projection, recovery, reservations, topology as topology_module
from domain.definition import commands as definition_commands, gate as definition_gate
from domain.definition import projection as definition_projection
from domain.definition.results import DefinitionRejection
from domain.policy import evaluate as policy_evaluate, inputs as policy_input_module
from domain.workflow.results import (
    DECISION_NOT_LEGAL_HERE, EXTERNAL_DRIFT, INDETERMINATE, LOCK_UNAVAILABLE, STALE_CONTROL_GENERATION, STORE_UNAVAILABLE,
    VERSION_CONFLICT,
    TOPOLOGY_UNREADABLE, WorkflowRejection,
)
from domain.implement_verify import commands as implement_verify_commands, registration as implement_verify_registration
from domain.implement_verify import executors as implement_verify_executors
from domain.implement_verify import projection as implement_verify_projection
from domain.implement_verify import verify as implement_verify_verify
from domain.implement_verify.results import ImplementVerifyRejection
from domain.budget import commands as budget_commands, projection as budget_projection, schema as budget_schema
from domain.budget.results import BudgetRejection
from domain.validation import commands as validation_commands, gate as validation_gate
from domain.validation import projection as validation_projection
from domain.validation.results import OPERATION_SUCCEEDED as VALIDATION_SUCCEEDED, ValidationRejection
from domain.policy.results import PolicyInputInvalid
from domain.publish import commands as publish_commands, gate as publish_gate, platform as publish_platform_module
from domain.publish import projection as publish_projection
from domain.publish.results import OPERATION_SUCCEEDED as PUBLISH_SUCCEEDED, PublishRejection
from runtime.protocol import Fault

COMMANDS = ("fact", "advance", "condition", "decide", "close", "publish-finalize", "attempt-open",
            "attempt-settle", "reserve", "reservation-settle", "recover-assess", "recover", "attempt-start",
            "policy-evaluate", *implement_verify_commands.COMMANDS, *budget_commands.COMMANDS,
            *validation_commands.COMMANDS, *publish_commands.COMMANDS)


# feature-t5 Operation settlement: purpose -> (resource handle prefix, projected object, label).
FEATURE_T5_OPERATIONS = {
    "budget": ("autonomous-budget:", budget_projection.OBJECT, "Autonomous budget"),
    "validation": ("validate-change:", validation_projection.OBJECT, "Validate Change"),
    "change-review": ("validate-change:", validation_projection.OBJECT, "Validate Change"),
    "validation-ruling-write": ("validate-change:", validation_projection.OBJECT, "Validate Change"),
}
# feature-t7 Operation settlement, same shape.
FEATURE_T7_OPERATIONS = {
    "publish": ("publish:", publish_projection.OBJECT, "Publish"),
    "publish-query": ("publish:", publish_projection.OBJECT, "Publish"),
}


def generic_decision_filter(position, decisions):
    """feature-t3, feature-t5 and feature-t7 narrowings of the generic decide, applied to projections and status."""
    return publish_gate.generic_filter(position, validation_gate.generic_filter(
        position, definition_gate.generic_filter(position, decisions)))


class DegradedDomain(UnavailableDomain):
    """No production domain is usable here, and the reason is reported rather than hidden."""

    def __init__(self, reason):
        self.unavailable_reason = reason


def apply_command(state, resolve, name, payload, *, revision, inputs=None):
    """The one place every Workflow command is executed, whichever entry issued it.

    inputs is the read-only Policy input view (feature-t6); only "policy-evaluate" uses it, and without
    it that command evaluates nothing and records no decision.
    """
    task_id = payload.get("taskId")
    if name in implement_verify_commands.COMMANDS:
        # feature-t4: the Implement and Verify loop; a dispatch may name a task that is not accepted.
        return implement_verify_commands.apply(state, resolve, name, payload, revision=revision,
                                               repository=getattr(getattr(resolve, "__self__", None), "repository", None))
    if name in budget_commands.COMMANDS:
        # feature-t5: the Policy Gate budget decision and its routing, in this one transaction.
        return budget_commands.apply(state, resolve, name, payload, revision=revision, inputs=inputs)
    if name in validation_commands.COMMANDS:
        # feature-t5: the Validate Change loop reads the product line through feature-t3's Definition context.
        owner = getattr(resolve, "__self__", None)
        if owner is None or not hasattr(owner, "definition_context"):
            raise WorkflowRejection(INDETERMINATE, "the Validate Change commands need the production Domain Core context")
        return validation_commands.apply(state, resolve, name, payload, revision=revision, context=owner.definition_context())
    if name in publish_commands.COMMANDS:
        # feature-t7: Publish authorization, dispatch and the same-operation recovery, with the Policy inputs.
        owner = getattr(resolve, "__self__", None)
        if owner is None or not hasattr(owner, "definition_context"):
            raise WorkflowRejection(INDETERMINATE, "the Publish commands need the production Domain Core context")
        return publish_commands.apply(state, resolve, name, payload, revision=revision, context=owner.definition_context(),
                                      inputs=inputs)
    inst = progression.instance(state, task_id)
    bound = resolve(inst)
    if bound is None:
        raise WorkflowRejection(TOPOLOGY_UNREADABLE, "the bound Workflow topology could not be read",
                                definition=copy.deepcopy(inst["definition"]))
    args = (state, bound, task_id, payload)
    # feature-t4: generic commands cannot record facts or move the nodes the Implement/Verify loop owns.
    implement_verify_commands.guard(state, task_id, name)
    # feature-t5: generic commands cannot record facts or move the budget nodes or the Validate Change nodes.
    budget_commands.guard(state, task_id, name)
    validation_commands.guard(state, task_id, name)
    # feature-t7: generic commands cannot record facts, move, finalise or assess the recovery of the Publish nodes.
    publish_commands.guard(state, task_id, name)
    if name == "fact":
        return progression.record_fact(state, bound, task_id, payload["fact"], revision=revision)
    if name == "advance":
        return progression.advance(*args, revision=revision)
    if name == "condition":
        return progression.update_condition(*args, revision=revision)
    if name == "decide":
        if definition_gate.requires_definition_entry(inst["position"], payload.get("decision")):
            # feature-t3: intentional narrowing of the feature-t2 generic decide. These two decisions
            # freeze the Definition and must come with a finalization ruling (FR-20).
            raise WorkflowRejection(DECISION_NOT_LEGAL_HERE, "this decision freezes the Definition; use the Definition entry",
                                    decision=payload.get("decision"), position=inst["position"],
                                    definitionEntryRequired=True, reasonCode="DECISION_REQUIRES_DEFINITION_ENTRY")
        if validation_gate.requires_validation_entry(inst["position"], payload.get("decision")):
            # feature-t5: intentional narrowing of the generic decide. Accept With reservation at the Validation
            # escalation gate is that path's Publish authorization and must carry the reservation and context (FR-26).
            raise WorkflowRejection(DECISION_NOT_LEGAL_HERE, "this decision needs the reservation and its FAIL context; "
                                    "use the Validate Change entry", decision=payload.get("decision"),
                                    position=inst["position"], validationEntryRequired=True,
                                    reasonCode="DECISION_REQUIRES_VALIDATION_ENTRY")
        if publish_gate.requires_publish_entry(inst["position"], payload.get("decision")):
            # feature-t7: intentional narrowing of the generic decide. Publish authorization must carry the exact
            # binding and the digest of the context the Human saw (FR-29, FR-26).
            raise WorkflowRejection(DECISION_NOT_LEGAL_HERE, "this decision must bind the exact candidate and target; "
                                    "use the Publish entry", decision=payload.get("decision"), position=inst["position"],
                                    publishEntryRequired=True, reasonCode="DECISION_REQUIRES_PUBLISH_ENTRY")
        return progression.decide(*args, revision=revision)
    if name == "close":
        return progression.close_task(*args, revision=revision)
    if name == "publish-finalize":
        return progression.finalize_publish(*args, revision=revision)
    if name == "attempt-open":
        return progression.open_attempt(*args, revision=revision)
    if name == "attempt-settle":
        return progression.settle_attempt(*args, revision=revision)
    if name == "reserve":
        return reservations.reserve(*args, revision=revision)
    if name == "reservation-settle":
        return reservations.settle(*args, revision=revision)
    if name == "recover-assess":
        return recovery.assess(*args, revision=revision)
    if name == "recover":
        return recovery.recover(*args, revision=revision)
    if name == "attempt-start":
        return progression.start_attempt(*args, revision=revision)
    if name == "policy-evaluate":
        return policy_evaluate.evaluate(*args, revision=revision, inputs=inputs)
    raise WorkflowRejection(INDETERMINATE, "unknown workflow command: " + str(name), commands=list(COMMANDS))


class HarnessDomain(AcceptanceDomain):
    """Acceptance (feature-t0) plus Workflow progression (feature-t2) behind one DomainPort."""

    def __init__(self, repository, store=None, observer=None, entry="runtime"):
        # OD-425: the preinstalled schemas are exactly the seven capability documents; every other action's payload
        # schema is a `definitions` entry of its capability's document (domain/capability_schema.py).
        documents = {ACCEPTANCE_SCHEMA_ID: ACCEPTANCE_SCHEMA, **budget_schema.SCHEMAS,
                     **{d.id: d.schema for d in (projection.DOCUMENT, definition_projection.DOCUMENT,
                                                 implement_verify_projection.DOCUMENT, validation_projection.DOCUMENT,
                                                 publish_projection.DOCUMENT)}}
        schemas = {capability_schema.digest(schema): identifier for identifier, schema in documents.items()}
        store = store or RuntimeStore(repository, payload_schemas=schemas, observer=observer)
        super().__init__(repository, store=store, observer=observer)
        self.entry = entry
        self.repo = Repository(repository)
        self.capabilities = [acceptance_projection.capability(), projection.capability(), definition_projection.capability(),
                             implement_verify_projection.capability(), budget_projection.capability(),
                             validation_projection.capability(), publish_projection.capability()]
        self.schemas = documents
        self.payload_schemas = schemas
        self._topologies = {}

    # -- bound topology -------------------------------------------------------------------------
    def topology(self, instance):
        """Parse the topology bytes the Workflow Instance is bound to; cached by blob identity."""
        definition = instance.get("definition") or {}
        blob = definition.get("blob")
        if not blob:
            return None
        if blob not in self._topologies:
            try:
                raw = self.repo.blob(blob)
            except (GitAbsent, GitUnavailable):
                return None
            if hashlib.sha256(raw).hexdigest() != definition.get("sha256"):
                return None
            try:
                self._topologies[blob] = topology_module.parse(raw)
            except topology_module.TopologyInvalid:
                return None
        return self._topologies[blob]

    def warm(self, state=None):
        state = self.store.read() if state is None else state
        for task in state.get("tasks", {}).values():
            self.topology(task.get("workflowInstance") or {})
        return state

    # -- DomainPort -----------------------------------------------------------------------------
    def acquire_generation(self):
        return self.store.acquire_generation(self.entry)

    def transaction(self, generation, callback, *, intent="domain", lock_wait=None):
        self.warm()

        def wrapped(s):
            for digest_value, schema_id in self.payload_schemas.items():
                s["payloadSchemas"].setdefault(digest_value, schema_id)
            result = callback(s)
            self.refresh_projections(s)
            return result
        result = self.store.transaction(generation, wrapped, intent=intent, lock_wait=lock_wait, fence_surface=True)
        self.drain()
        return result

    def refresh_projections(self, s):
        """Rebuild every projection and publish each change on the scope streams in this commit (KB-296)."""
        projection_stream.rebuild(s, self.build_projections)

    def build_projections(self, s):
        acceptance_projection.refresh(s)
        projection.refresh(s, self.topology, generic_decision_filter)
        definition_projection.refresh(s)
        implement_verify_projection.refresh(s)
        budget_projection.refresh(s)
        validation_projection.refresh(s)
        publish_projection.refresh(s, self.repository)

    def action(self, state, scope, action_id):
        """The legal action as the scope projects it, bound to its target object's current revision."""
        return projection_stream.bind(state, scope, self.build_action(state, scope, action_id))

    def build_action(self, state, scope, action_id):
        if scope not in state.get("scopes", {}):
            raise Fault("PRECONDITION_CONFLICT", "No legal domain action")
        if action_id == acceptance_projection.ACTION_ID:
            return acceptance_projection.accept_action(scope, acceptance_projection.capability())
        if action_id in definition_projection.ACTIONS:
            return definition_projection.action(scope, action_id, definition_projection.rows(state),
                                                definition_projection.capability())
        if action_id in implement_verify_projection.ACTIONS:
            return implement_verify_projection.action(scope, action_id, implement_verify_projection.rows(state),
                                                      implement_verify_projection.capability())
        if action_id in budget_projection.ACTIONS:
            return budget_projection.action(scope, action_id, budget_projection.rows(state), budget_projection.capability())
        if action_id in validation_projection.ACTIONS:
            return validation_projection.action(scope, action_id, validation_projection.rows(state),
                                                validation_projection.capability())
        if action_id in publish_projection.ACTIONS:
            return publish_projection.action(scope, action_id, publish_projection.rows(state), publish_projection.capability())
        if action_id in (projection.ACTION_DECIDE, projection.ACTION_CLOSE):
            rows = projection.instance_rows(state, self.topology, generic_decision_filter)
            cap = projection.capability()
            builder = projection.decide_action if action_id == projection.ACTION_DECIDE else projection.close_action
            return builder(scope, rows, cap)
        raise Fault("PRECONDITION_CONFLICT", "No legal domain action")

    def accept_action(self, state, operation, request):
        """Durable acceptance and, for Workflow actions, the domain work in the same transaction.

        Acceptance of a milestones task keeps feature-t0's two-phase shape because it establishes a
        branch and a worktree outside the transaction. A Workflow progression has no external effect,
        so it is applied here: the operation record and the progression share one atomic commit and
        the operation index makes a repeated invocation idempotent.
        """
        action_id = request["actionId"]
        if action_id == acceptance_projection.ACTION_ID:
            return super().accept_action(state, operation, request)
        if action_id in definition_projection.ACTIONS:
            return self.accept_definition_action(state, operation, request)
        if action_id in implement_verify_projection.ACTIONS:
            return self.accept_implement_verify_action(state, operation, request)
        if action_id in budget_projection.ACTIONS or action_id in validation_projection.ACTIONS:
            return self.accept_validation_budget_action(state, operation, request)
        if action_id in publish_projection.ACTIONS:
            return self.accept_publish_action(state, operation, request)
        payload = dict(request["payload"])
        task_id = payload["taskId"]
        authority = decision_authority(request["decisionRef"])
        command_id = "runtime:" + request["operationId"]
        if action_id == projection.ACTION_DECIDE:
            name = "decide"
            body = dict(taskId=task_id, commandId=command_id, decision=payload["decision"],
                        authorityRef=authority, expectedRuntimeVersion=payload["expectedRuntimeVersion"])
        else:
            name = "close"
            body = dict(taskId=task_id, commandId=command_id, reasonCategory=payload["reasonCategory"],
                        authorityRef=authority, expectedRuntimeVersion=payload["expectedRuntimeVersion"])
        try:
            outcome = apply_command(state, self.topology, name, body, revision=state["revision"])
        except WorkflowRejection as exc:
            operation.update(status="failed", resultCode=exc.code.replace("_", "-"),
                             reason=str(exc)[:2048], revision=state["revision"])
            return
        raw = json.dumps(outcome, ensure_ascii=False, sort_keys=True).encode()
        handle = "workflow:" + request["operationId"]
        evidence = dict(authority="runtime", resourceHandle=handle, scopeRef=request["scopeRef"],
                        objectRef=projection.WORKFLOW_OBJECT, revision=state["revision"], mediaType="application/json",
                        bytes=len(raw), digest=hashlib.sha256(raw).hexdigest())
        state["resources"][handle] = dict(evidence=evidence, dataBase64=base64.b64encode(raw).decode())
        operation.update(status="succeeded", resultRef=evidence, resultCode=outcome["result"].replace("_", "-"),
                         reason="Workflow progression committed", revision=state["revision"])

    # -- standalone CLI entry -------------------------------------------------------------------
    def bind_entry(self):
        """Take the control generation for this entry; the other entry becomes stale at once."""
        return self.acquire_generation()

    # -- feature-t3 Definition loop and the purpose-agnostic execution layer -------------------------
    def definition_context(self):
        return _DefinitionContext(self.repo, self.repository, self.entry)

    def accept_definition_action(self, state, operation, request):
        """A Definition action runs its domain command in the accepting transaction; external effects are
        registered as execution descriptors and settle the Operation later. A refused command leaves
        no partial change: the touched state keys are restored before the Operation is failed."""
        payload = dict(request["payload"])
        name = {"definition.submit": "submit", "definition.dispatch": "dispatch", "definition.decide": "decide",
                "definition.formal-authorize": "formal-authorize"}[request["actionId"]]
        body = dict(payload, commandId="runtime:" + request["operationId"], authorityRef=decision_authority(request["decisionRef"]))
        scope_view = state.get("scopes", {}).get(request["scopeRef"], {})
        if name == "dispatch":
            body["runtimeContext"] = dict(operationId=request["operationId"], scopeRef=request["scopeRef"],
                                          grantRefs=copy.deepcopy(request.get("grantRefs") or []),
                                          decisionRef=request["decisionRef"], resourceHandle=scope_view.get("resourceHandle"))
        saved = {k: copy.deepcopy(state.get(k)) for k in ("tasks", "executionDescriptors")}
        try:
            outcome = self.definition_apply(state, name, body)
        except (WorkflowRejection, DefinitionRejection) as exc:
            for key, value in saved.items():
                if value is None:
                    state.pop(key, None)
                else:
                    state[key] = value
            operation.update(status="failed", resultCode=exc.code.replace("_", "-"), reason=str(exc)[:2048],
                             revision=state["revision"])
            return
        execution_id = outcome.get("executionId")
        descriptor = state.get("executionDescriptors", {}).get(execution_id) if execution_id else None
        if descriptor is not None and descriptor["status"] == "pending" and outcome["result"] != "IDEMPOTENT_REPLAY":
            descriptor["operationId"] = request["operationId"]
            descriptor["scopeRef"] = request["scopeRef"]
            operation.update(status="running", executionRef=execution_id, resultCode=None,
                             reason="Definition work accepted; external effect pending", revision=state["revision"])
            return
        self._settle_operation(state, operation, request["operationId"], request["scopeRef"], outcome, "succeeded")

    def accept_implement_verify_action(self, state, operation, request):
        """feature-t4 actions: the domain command runs in the accepting transaction under the verified Human
        decision; the Agent execution or the checks are registered as execution descriptors and settle the
        Operation later on this entry's execution layer. A refused command leaves no partial change."""
        payload = dict(request["payload"])
        task_id = payload["taskId"]
        authority = decision_authority(request["decisionRef"])
        command_id = "runtime:" + request["operationId"]
        scope_view = state.get("scopes", {}).get(request["scopeRef"], {})
        runtime = dict(operationId=request["operationId"], scopeRef=request["scopeRef"],
                       grantRefs=copy.deepcopy(request.get("grantRefs") or []), decisionRef=request["decisionRef"],
                       resourceHandle=scope_view.get("resourceHandle"))
        saved = {k: copy.deepcopy(state.get(k)) for k in ("tasks", "executionDescriptors")}
        execution_id = None
        try:
            task = state.get("tasks", {}).get(task_id)
            if task is not None and str(payload["expectedRuntimeVersion"]) != task["workflowInstance"]["runtimeVersion"]:
                raise WorkflowRejection(VERSION_CONFLICT, "expected Runtime Version does not match the current one",
                                        expected=str(payload["expectedRuntimeVersion"]),
                                        current=task["workflowInstance"]["runtimeVersion"])
            if request["actionId"] == implement_verify_projection.DISPATCH:
                body = dict(taskId=task_id, commandId=command_id, authorityRef=authority, portId=payload["portId"],
                            finalizationRef=payload["finalizationRef"], budget=copy.deepcopy(payload["budget"]),
                            worktree=(task or {}).get("worktree"), role="implementer", purpose="coding-implementer",
                            runtimeContext=runtime)
                outcome = implement_verify_commands.apply(state, self.topology, "implement-dispatch", body,
                                                          revision=state["revision"], repository=self.repository)
                execution_id = outcome["execution"]["executionRequestId"]
            else:
                inst = progression.instance(state, task_id)
                outcome = implement_verify_verify.prepare(state, self.topology(inst), task_id,
                                                          dict(commandId=command_id, authorityRef=authority),
                                                          revision=state["revision"])
                if outcome["result"] == "PENDING":
                    execution_id = implement_verify_executors.verify_descriptor(
                        state, task_id, outcome["verification"], authority, state["revision"], runtime)
        except (WorkflowRejection, ImplementVerifyRejection, DefinitionRejection) as exc:
            for key, value in saved.items():
                if value is None:
                    state.pop(key, None)
                else:
                    state[key] = value
            operation.update(status="failed", resultCode=exc.code.replace("_", "-"), reason=str(exc)[:2048],
                             revision=state["revision"])
            return
        descriptor = state.get("executionDescriptors", {}).get(execution_id) if execution_id else None
        if descriptor is not None and descriptor["status"] == "pending" and descriptor.get("entry") == self.entry \
                and outcome["result"] != "IDEMPOTENT_REPLAY":
            descriptor["operationId"] = request["operationId"]
            descriptor["scopeRef"] = request["scopeRef"]
            operation.update(status="running", executionRef=execution_id, resultCode=None,
                             reason="Implement/Verify work accepted; external effect pending", revision=state["revision"])
            return
        status = "succeeded" if outcome["result"] in implement_verify_executors.OPERATION_SUCCEEDED else "failed"
        self._settle_operation(state, operation, request["operationId"], request["scopeRef"], outcome, status,
                               purpose=implement_verify_executors.VERIFY_PURPOSE)

    def accept_validation_budget_action(self, state, operation, request):
        """feature-t5 actions run their Domain Core command in the accepting transaction under the verified Human
        decision. budget.decide gets the Policy inputs this entry holds; a DENY or NOT_DETERMINABLE decision stays
        recorded and fails the Operation. A change review is registered as an execution descriptor and settles
        the Operation later on this entry's execution layer. A refused command leaves no partial change."""
        payload = dict(request["payload"])
        action_id = request["actionId"]
        body = dict(payload, commandId="runtime:" + request["operationId"], authorityRef=decision_authority(request["decisionRef"]))
        budget = action_id in budget_projection.ACTIONS
        if action_id == validation_projection.DECIDE:
            body["decision"] = validation_gate.ACCEPT_RESERVATION
        if action_id == validation_projection.DISPATCH:
            scope_view = state.get("scopes", {}).get(request["scopeRef"], {})
            body["runtimeContext"] = dict(operationId=request["operationId"], scopeRef=request["scopeRef"],
                                          grantRefs=copy.deepcopy(request.get("grantRefs") or []),
                                          decisionRef=request["decisionRef"], resourceHandle=scope_view.get("resourceHandle"))
        saved = {k: copy.deepcopy(state.get(k)) for k in ("tasks", "executionDescriptors")}
        try:
            if budget:
                inst = progression.instance(state, body.get("taskId"))
                if str(payload.get("expectedRuntimeVersion")) != inst["runtimeVersion"]:
                    raise WorkflowRejection(VERSION_CONFLICT, "expected Runtime Version does not match the current one",
                                            expected=str(payload.get("expectedRuntimeVersion")), current=inst["runtimeVersion"])
                outcome = budget_commands.apply(state, self.topology, "budget-decide", body, revision=state["revision"],
                                                inputs=self.policy_inputs())
            else:
                outcome = validation_commands.apply(state, self.topology, validation_projection.COMMAND_OF[action_id], body,
                                                    revision=state["revision"], context=self.definition_context())
        except (WorkflowRejection, BudgetRejection, ValidationRejection, DefinitionRejection, ImplementVerifyRejection,
                PolicyInputInvalid) as exc:
            for key, value in saved.items():
                if value is None:
                    state.pop(key, None)
                else:
                    state[key] = value
            code = getattr(exc, "code", "INPUT_INVALID")
            operation.update(status="failed", resultCode=str(code).replace("_", "-"), reason=str(exc)[:2048],
                             revision=state["revision"])
            return
        execution_id = outcome.get("executionId")
        descriptor = state.get("executionDescriptors", {}).get(execution_id) if execution_id else None
        if descriptor is not None and descriptor["status"] == "pending" and descriptor.get("entry") in (None, self.entry) \
                and outcome["result"] != "IDEMPOTENT_REPLAY":
            descriptor["operationId"] = request["operationId"]
            descriptor["scopeRef"] = request["scopeRef"]
            operation.update(status="running", executionRef=execution_id, resultCode=None,
                             reason="Validate Change work accepted; external effect pending", revision=state["revision"])
            return
        succeeded = ("BUDGET_ROUTED", "IDEMPOTENT_REPLAY") if budget else VALIDATION_SUCCEEDED
        status = "succeeded" if outcome["result"] in succeeded else "failed"
        self._settle_operation(state, operation, request["operationId"], request["scopeRef"], outcome, status,
                               purpose="budget" if budget else "validation")

    def accept_publish_action(self, state, operation, request):
        """feature-t7 actions run their Domain Core command in the accepting transaction under the verified Human
        decision, with this entry's Policy inputs. A push permit other than ALLOW stays recorded and fails the
        Operation. A publish execution or query is registered as an execution descriptor and settles the Operation
        later on this entry's execution layer. The Human recovery authorization of a reconcile is the verified
        decision itself, bound to this instance, occurrence, version, assessment, action and publish operation.
        A refused command leaves no partial change."""
        payload = dict(request["payload"])
        action_id = request["actionId"]
        task_id = payload.get("taskId")
        authority = decision_authority(request["decisionRef"])
        body = dict(payload, commandId="runtime:" + request["operationId"], authorityRef=authority)
        scope_view = state.get("scopes", {}).get(request["scopeRef"], {})
        body["runtimeContext"] = dict(operationId=request["operationId"], scopeRef=request["scopeRef"],
                                      grantRefs=copy.deepcopy(request.get("grantRefs") or []),
                                      decisionRef=request["decisionRef"], resourceHandle=scope_view.get("resourceHandle"))
        saved = {k: copy.deepcopy(state.get(k)) for k in ("tasks", "executionDescriptors")}
        try:
            if action_id == publish_projection.RECONCILE:
                from domain.publish import recovery as publish_recovery
                inst = progression.instance(state, task_id)
                body["humanAuthorization"] = dict(
                    workflowInstance=task_id, occurrence=progression.occurrence(inst, task_id),
                    expectedRuntimeVersion=str(payload.get("expectedRuntimeVersion")), assessmentId=payload.get("assessmentId"),
                    action="RECONCILE_CURRENT_NODE", effectScope=publish_recovery.scope_of(state, task_id),
                    authorizationRef=authority)
            outcome = publish_commands.apply(state, self.topology, publish_projection.COMMAND_OF[action_id], body,
                                             revision=state["revision"], context=self.definition_context(),
                                             inputs=self.policy_inputs())
        except (WorkflowRejection, PublishRejection, DefinitionRejection, ValidationRejection, PolicyInputInvalid) as exc:
            for key, value in saved.items():
                if value is None:
                    state.pop(key, None)
                else:
                    state[key] = value
            code = getattr(exc, "code", "INPUT_INVALID")
            operation.update(status="failed", resultCode=str(code).replace("_", "-"), reason=str(exc)[:2048],
                             revision=state["revision"])
            return
        execution_id = outcome.get("executionId")
        descriptor = state.get("executionDescriptors", {}).get(execution_id) if execution_id else None
        if descriptor is not None and descriptor["status"] == "pending" and descriptor.get("entry") in (None, self.entry) \
                and outcome["result"] != "IDEMPOTENT_REPLAY":
            descriptor["operationId"] = request["operationId"]
            descriptor["scopeRef"] = request["scopeRef"]
            operation.update(status="running", executionRef=execution_id, resultCode=None,
                             reason="Publish work accepted; external effect pending", revision=state["revision"])
            return
        status = "succeeded" if outcome["result"] in PUBLISH_SUCCEEDED else "failed"
        self._settle_operation(state, operation, request["operationId"], request["scopeRef"], outcome, status,
                               purpose="publish")

    def _settle_operation(self, state, operation, operation_id, scope, outcome, status, purpose=None):
        raw = json.dumps(outcome, ensure_ascii=False, sort_keys=True).encode()
        loop = purpose in implement_verify_executors.EXECUTION_SETTLE
        handle = ("implement-verify:" if loop else "definition:") + operation_id
        object_ref = implement_verify_projection.OBJECT if loop else definition_projection.OBJECT
        label = "Implement/Verify" if loop else "Definition"
        if purpose in FEATURE_T5_OPERATIONS:
            prefix, object_ref, label = FEATURE_T5_OPERATIONS[purpose]
            handle = prefix + operation_id
        if purpose in FEATURE_T7_OPERATIONS:
            prefix, object_ref, label = FEATURE_T7_OPERATIONS[purpose]
            handle = prefix + operation_id
        evidence = dict(authority="runtime", resourceHandle=handle, scopeRef=scope, objectRef=object_ref,
                        revision=state["revision"], mediaType="application/json", bytes=len(raw),
                        digest=hashlib.sha256(raw).hexdigest())
        state["resources"][handle] = dict(evidence=evidence, dataBase64=base64.b64encode(raw).decode())
        operation.update(status=status, resultRef=evidence if status == "succeeded" else None,
                         resultCode=str(outcome.get("result", "UNKNOWN")).replace("_", "-"),
                         reason=label + " work settled", revision=state["revision"])

    def definition_apply(self, state, name, payload):
        task_id = payload.get("taskId")
        inst = progression.instance(state, task_id)
        bound = self.topology(inst)
        if bound is None:
            raise WorkflowRejection(TOPOLOGY_UNREADABLE, "the bound Workflow topology could not be read")
        return definition_commands.apply(state, bound, self.definition_context(), name, payload)

    def run_definition(self, name, payload, *, generation=None, lock_wait=None):
        """standalone entry: one Definition command in one domain transaction."""
        try:
            return self.transaction(generation, lambda s: self.definition_apply(s, name, payload), lock_wait=lock_wait)
        except Drift as exc:
            raise WorkflowRejection(EXTERNAL_DRIFT, "a non-cooperating change was observed; the facts are fixed and the writer stopped",
                                    **exc.detail()) from exc
        except LockUnavailable as exc:
            raise WorkflowRejection(LOCK_UNAVAILABLE, str(exc)) from exc
        except StoreUnavailable as exc:
            raise WorkflowRejection(STORE_UNAVAILABLE, str(exc), determinate=exc.determinate) from exc
        except Fault as exc:
            if exc.code == "WRITER_CONFLICT":
                raise WorkflowRejection(STALE_CONTROL_GENERATION,
                                        "an older control generation may not commit; reconnect and read the current state",
                                        offered=generation) from exc
            raise

    def executions(self, state=None):
        """Read-only: execution descriptors that still need the execution layer."""
        state = self.store.read() if state is None else state
        # feature-t4: a descriptor naming an entry (cli or runtime, by its port mode) is run only there.
        return [copy.deepcopy(d) for _k, d in sorted(state.get("executionDescriptors", {}).items())
                if d["status"] in ("pending", "running") and d.get("entry") in (None, self.entry)]

    def start_execution(self, execution_id, generation):
        def commit(s):
            descriptor = s["executionDescriptors"][execution_id]
            if descriptor["status"] != "pending":
                return copy.deepcopy(descriptor)
            starter = definition_commands.EXECUTION_START.get(descriptor["purpose"])
            if starter is not None:
                inst = progression.instance(s, descriptor["taskId"])
                starter(s, self.topology(inst), descriptor, generation)
            descriptor.update(status="running", startedAt=definition_commands.now())
            op = s.get("operations", {}).get(descriptor.get("operationId") or "")
            if op is not None:
                op["value"].update(status="running", executionRef=execution_id, revision=s["revision"])
            return copy.deepcopy(descriptor)
        return self.transaction(generation, commit)

    def settle_execution(self, execution_id, outcome, generation):
        def commit(s):
            descriptor = s["executionDescriptors"][execution_id]
            if descriptor["status"] in ("settled", "indeterminate"):
                return dict(result="IDEMPOTENT_REPLAY", descriptor=copy.deepcopy(descriptor))
            inst = progression.instance(s, descriptor["taskId"])
            settle = {**definition_commands.EXECUTION_SETTLE, **implement_verify_executors.EXECUTION_SETTLE,
                      **validation_commands.EXECUTION_SETTLE, **publish_commands.EXECUTION_SETTLE}[descriptor["purpose"]]
            result = settle(s, self.topology(inst), descriptor, outcome)
            if result.get("blocked"):
                descriptor.update(status="blocked", lastError=copy.deepcopy(outcome))
            else:
                unknown = result.get("indeterminate") or outcome.get("classification") == "unknown"
                descriptor.update(status="indeterminate" if unknown else "settled", result=copy.deepcopy(outcome),
                                  settledAt=definition_commands.now())
            op = s.get("operations", {}).get(descriptor.get("operationId") or "")
            if op is not None:
                if result.get("result") in ("VERDICT_RECORDED", "DEFINITION_FROZEN", "FINDING_DISPOSED") or \
                        (descriptor["purpose"] in implement_verify_executors.EXECUTION_SETTLE
                         and not result.get("indeterminate")
                         and result.get("result") in implement_verify_executors.OPERATION_SUCCEEDED) or \
                        (descriptor["purpose"] in publish_commands.EXECUTION_SETTLE and not result.get("indeterminate")
                         and result.get("result") in PUBLISH_SUCCEEDED):
                    status = "succeeded"
                else:
                    status = "unknown" if descriptor["status"] == "indeterminate" else "failed"
                self._settle_operation(s, op["value"], descriptor["operationId"], descriptor.get("scopeRef"), result, status,
                                       purpose=descriptor["purpose"])
                from domain.acceptance.runtime_binding import emit
                if descriptor.get("scopeRef") in s.get("scopes", {}):
                    emit(s, descriptor["scopeRef"], "operation.changed", op["value"], descriptor["operationId"])
            return result
        return self.transaction(generation, commit)

    def definition_status(self, task_id):
        return definition_commands.view(self.warm(), task_id)

    def status(self, task_id=None):
        state = self.warm()
        rows = []
        for identity, task in sorted(state.get("tasks", {}).items()):
            if task_id and identity != task_id:
                continue
            inst = task["workflowInstance"]
            bound = self.topology(inst)
            if bound is None:
                rows.append(dict(taskId=identity, topology="unreadable", definition=copy.deepcopy(inst.get("definition"))))
                continue
            rows.append(dict(taskId=identity, branch=task["branch"], worktree=task["worktree"],
                             decisions=generic_decision_filter(inst["position"], progression.decisions(inst, bound)),
                             **progression.view(inst, bound, identity)))
        return dict(generation=state["generation"], domainRevision=state["revision"],
                    binding=self.store.binding(), tasks=rows)

    def run(self, name, payload, *, generation=None, lock_wait=None):
        """Run one Workflow command under the control generation this entry holds."""
        try:
            return self.transaction(generation, lambda s: apply_command(s, self.topology, name, payload, revision=s["revision"],
                                                                        inputs=self.policy_inputs()),
                                    lock_wait=lock_wait)
        except Drift as exc:
            raise WorkflowRejection(EXTERNAL_DRIFT,
                                    "a non-cooperating change was observed; the facts are fixed and the writer stopped",
                                    **exc.detail()) from exc
        except LockUnavailable as exc:
            raise WorkflowRejection(LOCK_UNAVAILABLE, str(exc)) from exc
        except StoreUnavailable as exc:
            raise WorkflowRejection(STORE_UNAVAILABLE, str(exc), determinate=exc.determinate) from exc
        except Fault as exc:
            if exc.code == "WRITER_CONFLICT":
                raise WorkflowRejection(STALE_CONTROL_GENERATION,
                                        "an older control generation may not commit; reconnect and read the current state",
                                        offered=generation) from exc
            raise


    # -- Policy Gate inputs (feature-t6) ---------------------------------------------------------
    # feature-t4 injects its product-side Implementer registration reader (Assistant OD-399):
    # reader(state, port_id) -> the coding-implementer entry for that port, or None.
    policy_sources = dict(implementer_registrations=implement_verify_registration.resolve)
    # feature-t7: the Publish platform adapter factory, built per execution from the authorized binding's platform
    # and the configured program path (GitHub only in this phase, Assistant KB-272).
    publish_platform = staticmethod(publish_platform_module.production)

    def policy_inputs(self):
        """A fresh read-only Policy input view bound to this product line; one per unit of work.

        policy_sources carries feature-t4's Implementer registration reader in production and, in tests
        only, synthetic Registry and round readers.
        """
        return policy_input_module.PolicyInputs(self.repo, **self.policy_sources)


class _DefinitionContext:
    """What Definition commands may read: the product-line repository and the calling entry."""

    def __init__(self, repo, repository_root, entry):
        from domain.definition.review import authorizer_available
        self.repo, self.repository_root, self.entry = repo, repository_root, entry
        # Production check that the feature-t6 execution authorization callback is installed.
        self.authorizer_check = authorizer_available


def open_domain(repository, *, entry="cli", observer=None):
    """Build the production Domain Core, or a degraded port that states why it is unusable."""
    try:
        return HarnessDomain(repository, observer=observer, entry=entry)
    except StoreUnavailable as exc:
        return DegradedDomain("Product-line repository is not usable for domain state: " + str(exc))
