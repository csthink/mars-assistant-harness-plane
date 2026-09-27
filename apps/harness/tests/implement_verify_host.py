"""SYNTHETIC embedded Host for the Implementer purpose. Tests only; no real Assistant, Agent or model.

It answers the host.* methods HostExecutionPort calls. On host.execution.start it applies a test-chosen
effect to the task worktree (standing in for the Agent the real Host would run) and then projects the
physical execution the scenario asks for. The J-06 scenarios return the fixed sample projections
(records/diagnostics/feature-t4/2026-09-23/inputs/assistant/docs/design/evidence/host-execution-facts-j06/)
with every field byte-for-byte except requestIdentity.operationId and requestIdentity.requestDigest,
which the port computes for the current request and checks; the sample's executionRef is returned by
host.operation.get unchanged, and the embedded registration and context reuse the sample's scope,
connection, model and configuration revision.
"""
import base64
import copy
import json
from pathlib import Path

from execution.port import ExecutionDiscovery, sha
import instance_area

if instance_area.configured():
    SAMPLES = instance_area.path("records/diagnostics/feature-t4/2026-09-23/inputs/assistant/docs/design/evidence/host-execution-facts-j06")
    STOPPING = SAMPLES / "physical-execution.stopping.json"
    STOPPED = SAMPLES / "physical-execution.stopped.json"
    SAMPLE = json.loads(STOPPING.read_text())
else:  # the samples live in a product-line instance area; the tests that use them skip (instance_area.REASON)
    SAMPLES = STOPPING = STOPPED = SAMPLE = None
PROGRAM = dict(launcher="/synthetic/claude", binaryDigest="c" * 64, version="synthetic 1.0")


def sample_context(generation):
    return dict(generation=generation, scopeRef=SAMPLE["scopeRef"], resourceHandle="resource:synthetic",
                connectionRef=SAMPLE["connectionRef"], credentialRef="credential:claude-native", grantRefs=[],
                decisionRef=None, targetBinding=dict(resourceHandle="resource:synthetic", relativePath="worktree"))


def make_discovery(entry, program=None):
    async def discover():
        profile = dict(copy.deepcopy(entry["profile"]), programIdentity=copy.deepcopy(program or PROGRAM))
        return ExecutionDiscovery(profile, SAMPLE["connectionRef"], entry["provider"], "anthropic",
                                  entry["configurationRevision"])
    return discover


class ImplementerHost:
    def __init__(self, generation, effect=None):
        self.context = dict(controlGeneration=generation)
        self.methods = []
        self.start = None
        self.captured = None
        self.scenario = "completed"
        self.effect = effect
        self.cancelled = False
        self.approvals = []
        self.model = SAMPLE["actualBinding"]["model"]
        self.observed_reservation = None
        self.domain = None

    async def call(self, method, p):
        self.methods.append(method)
        if method == "host.execution.preflight":
            return dict(status="supported", checks=[dict(passed=True)])
        if method == "host.context.capture":
            self.captured = dict(**{k: p[k] for k in ("scopeRef", "domainOperationId", "operationId", "requestDigest")},
                                 status="succeeded",
                                 snapshots=[dict(source=copy.deepcopy(x), snapshot=dict(x, authority="host",
                                                                                        resourceHandle="snapshot:%d" % n))
                                            for n, x in enumerate(p["sources"])])
            return self.captured
        if method == "host.context.get":
            return self.captured
        if method == "host.execution.start":
            if self.domain is not None:
                # What the domain had persisted at the moment of release (reservation before effect).
                self.observed_reservation = copy.deepcopy(
                    self.domain.read().get("executionReservations", {}).get(p["domainOperationId"]))
            self.start = copy.deepcopy(p)
            if self.effect:
                self.effect(self.scenario)
            if self.scenario == "start-unknown":
                self.scenario = "completed"
                raise TimeoutError()
            return self.operation()
        if method == "host.operation.get":
            return self.operation()
        if method == "host.execution.cancel":
            self.cancelled = True
            return self.operation()
        if method == "host.execution.get":
            return self.physical()
        if method == "host.resource.read":
            raw = self.result_bytes()
            chunk = raw[p["offset"]:p["offset"] + p["length"]]
            return dict(offset=p["offset"], dataBase64=base64.b64encode(chunk).decode(),
                        eof=p["offset"] + len(chunk) == len(raw))
        raise AssertionError(method)

    def operation(self):
        s = self.start
        return dict(scopeRef=s["scopeRef"], operationId=s["operationId"], requestDigest=s["requestDigest"],
                    executionRef=SAMPLE["executionRef"])

    def actual(self):
        return dict(model=self.model, source="protocol-init", observedModels=[self.model])

    def result_bytes(self):
        s = self.start
        answer = "Implemented the Definition (synthetic embedded Agent)."
        evidence = dict(answer=answer, answerBytes=len(answer), answerDigest=sha(answer.encode()),
                        readback=dict(source="protocol-init", model=self.model))
        return json.dumps(dict(**{k: s[k] for k in ("operationId", "profileId", "profileDigest")},
                               executionRef=SAMPLE["executionRef"], actualBinding=self.actual(), outcome="completed",
                               evidence=evidence), sort_keys=True).encode()

    def rebound(self, path):
        value = json.loads(Path(path).read_text())
        value["requestIdentity"] = dict(value["requestIdentity"], operationId=self.start["operationId"],
                                        requestDigest=self.start["requestDigest"])
        return value

    def physical(self):
        s = self.start
        if self.scenario == "stopping":
            return self.rebound(STOPPING)
        if self.scenario == "stopped":
            return self.rebound(STOPPED)
        base = dict(executionRef=SAMPLE["executionRef"], scopeRef=s["scopeRef"], connectionRef=s["connectionRef"],
                    model=s["model"], configurationRevision=s["configurationRevision"],
                    requestIdentity={k: s[k] for k in ("operationId", "requestDigest", "profileDigest")},
                    supervisor=copy.deepcopy(SAMPLE["supervisor"]), approvalDecisionRefs=list(self.approvals),
                    actualBinding=None, stopReason=None, accounting=None, exit=None, observationCompleteness="partial",
                    resultRef=None, reason="synthetic embedded execution")
        if self.scenario == "running":
            base.update(state="running")
            return base
        if self.scenario == "unknown":
            base.update(state="unknown", reason="host restarted before the target was released")
            return base
        if self.scenario == "failed":
            base.update(state="failed", exit=dict(code=3, signal=None, pipesClosed=True), observationCompleteness="complete",
                        accounting=dict(toolCalls=1, runSeconds=1, outputBytes=10, waited=True, pidGoneAfterExit=True))
            return base
        raw = self.result_bytes()
        base.update(state="completed", exit=dict(code=0, signal=None, pipesClosed=True), actualBinding=self.actual(),
                    observationCompleteness="complete",
                    accounting=dict(toolCalls=2, runSeconds=1, outputBytes=len(raw), waited=True, pidGoneAfterExit=True),
                    resultRef=dict(authority="host", resourceHandle=s["resourceHandle"], scopeRef=s["scopeRef"],
                                   objectRef="execution-result:" + SAMPLE["executionRef"], revision="1",
                                   mediaType="application/json", bytes=len(raw), digest=sha(raw)))
        return base
