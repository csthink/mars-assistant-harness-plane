"""DomainPort implementation that exposes task acceptance to the Runtime (design §两个入口).

The Runtime durably accepts a task.accept Operation (dispatcher.action_invoke -> accept_action); the
same-process execution layer (drain) then runs accept.accept_task, the function the CLI calls, and
settles the Operation. No acceptance rule lives here. Production wiring of serve-stdio to this domain
is feature-t2's; tests compose it through tests/serve_acceptance.py.
"""
import base64
import hashlib
import json
from pathlib import Path

from domain import projection_stream
from domain.acceptance import projection, results
from domain.acceptance.accept import accept_task, intent_digest
from domain.acceptance.results import Rejection
from domain.acceptance.schema import DIGEST, PAYLOAD_SCHEMA, SCHEMA_ID
from domain.store import RuntimeStore
from runtime.protocol import Fault

def result_code(code):
    return code.replace("_", "-")

def decision_authority(decision_ref):
    """The authorityRef naming a trusted Human decision (Assistant KB-298).

    A Host decisionRef that already carries the decision kind prefix is the reference itself; only a bare one
    is prefixed, so a Runtime entry never records decision:decision:...
    """
    ref = str(decision_ref)
    return ref if ref.startswith("decision:") else "decision:" + ref

emit = projection_stream.emit

class AcceptanceDomain:
    available = True

    def __init__(self, repository, store=None, observer=None):
        self.repository = str(Path(repository))
        self.store = store or RuntimeStore(repository, payload_schemas={DIGEST: SCHEMA_ID}, observer=observer)
        self.capabilities = [projection.capability()]
        self.schemas = {SCHEMA_ID: PAYLOAD_SCHEMA}
        self.observer = observer

    def acquire_generation(self):
        return self.store.acquire_generation()

    def read(self):
        return self.store.read()

    def refresh_projections(self, s):
        """Rebuild every projection this domain owns and publish each change on the scope streams (KB-296);
        feature-t2 extends it with the Workflow view."""
        projection_stream.rebuild(s, projection.refresh)

    def transaction(self, generation, callback, *, intent="domain"):
        def wrapped(s):
            s["payloadSchemas"].setdefault(DIGEST, SCHEMA_ID)
            result = callback(s)
            self.refresh_projections(s)
            return result
        result = self.store.transaction(generation, wrapped, intent=intent)
        self.drain()
        return result

    def action(self, state, scope, action_id):
        if scope in state.get("scopes", {}) and action_id == projection.ACTION_ID:
            return projection_stream.bind(state, scope, projection.accept_action(scope, projection.capability()))
        raise Fault("PRECONDITION_CONFLICT", "No legal domain action")

    def accept_action(self, state, operation, request):
        """Durable acceptance of the Runtime Operation only; the acceptance itself runs after commit."""
        payload = request["payload"]
        request_id = request["operationId"]
        intent = dict(repository=self.repository, taskType=payload["taskType"], taskId=payload["taskId"], baseRef=payload["baseRef"],
                      worktreeRoot=payload["worktreeRoot"], authorityRef=decision_authority(request["decisionRef"]))
        existing = state["acceptance"].get(request_id)
        if existing is not None:
            raise Fault("IDEMPOTENCY_CONFLICT", "Acceptance request identity already recorded")
        state["acceptance"][request_id] = dict(requestId=request_id, intentDigest=intent_digest(intent), intent=intent, status="queued", outcome=None, claim=None, intended=None, task=None,
            startedAt=None, history=[], channel="runtime", scope=request["scopeRef"])

    def pending(self, state):
        for request_id, op in state.get("acceptance", {}).items():
            record = state["operations"].get(request_id)
            if op.get("channel") == "runtime" and record and record["value"]["status"] == "accepted" and op["status"] != "accepted":
                yield request_id, op

    def drain(self):
        state = self.store.read()
        for request_id, op in list(self.pending(state)):
            self.execute(request_id, op)

    def execute(self, request_id, op):
        request = dict(requestId=request_id, **op["intent"])
        outcome, rejection = None, None
        try:
            outcome = accept_task(self.store, request, observer=self.observer)
        except Rejection as exc:
            rejection = exc
        def settle(s):
            record = s["operations"].get(request_id)
            if record is None or record["value"]["status"] != "accepted":
                return None
            value = record["value"]
            scope = value["scopeRef"]
            if rejection is None:
                task = outcome["task"]
                raw = json.dumps(outcome, ensure_ascii=False, sort_keys=True).encode()
                handle = "acceptance:" + request_id
                evidence = dict(authority="runtime", resourceHandle=handle, scopeRef=scope, objectRef=task["taskRef"],
                                revision=s["revision"], mediaType="application/json", bytes=len(raw), digest=hashlib.sha256(raw).hexdigest())
                s["resources"][handle] = dict(evidence=evidence, dataBase64=base64.b64encode(raw).decode())
                value.update(status="succeeded", resultRef=evidence, resultCode=result_code(outcome["result"]),
                             reason="Task accepted" if outcome["result"] == results.ACCEPTED else "Same request replayed", revision=s["revision"])
            else:
                if rejection.code in results.NOT_DETERMINABLE:
                    value.update(status="unknown", resultCode=result_code(rejection.code), reason=str(rejection)[:2048], revision=s["revision"])
                else:
                    value.update(status="failed", resultCode=result_code(rejection.code), reason=str(rejection)[:2048], revision=s["revision"])
            emit(s, scope, "operation.changed", value, request_id)
            # Every projected object this acceptance changed reaches the stream here or in the accept commit.
            self.refresh_projections(s)
            return None
        self.store.transaction(None, settle)
