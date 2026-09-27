"""SYNTHETIC Host for a real serve-stdio process (feature-t4 AC-10). Tests only.

LoopHost drives the product entrypoint (`python -m runtime.main serve-stdio`): it opens a scope, grants
the capabilities, invokes the `implement.dispatch` and `verify.run` Runtime actions with a synthetic
trusted Human decision, and answers the reverse host.* calls. StdioImplementerHost reuses
ImplementerHost's scenarios (the J-06 fixed projections among them) and completes every answer to the
Contract result shape the Runtime's HostClient validates; the J-06 projections are returned in the scope the
Host opened (scopeRef rebound, see answer()). No real Assistant, Agent or model.
"""
import asyncio
import copy
import json
from pathlib import Path

from host_driver import Host, request_digest
from implement_verify_host import SAMPLE, ImplementerHost

METHODS = ("host.execution.preflight", "host.context.capture", "host.context.get", "host.execution.start",
           "host.operation.get", "host.execution.cancel", "host.execution.get", "host.resource.read")


class StdioImplementerHost(ImplementerHost):
    def handlers(self):
        return {method: (lambda p, method=method: self.answer(method, p)) for method in METHODS}

    def answer(self, method, p):
        result = copy.deepcopy(asyncio.run(self.call(method, p)))
        if method == "host.execution.preflight":
            result.update(profileDigest=p["profileDigest"], reason="synthetic Host",
                          checks=[dict(id="synthetic", passed=True, detail="synthetic Host, no real Agent")])
        elif method in ("host.context.capture", "host.context.get"):
            result["reason"] = "synthetic Host"
        elif method in ("host.execution.start", "host.operation.get", "host.execution.cancel"):
            result.update(status="accepted", resultRef=None, reason="synthetic Host", resultCode=None, revision="1")
            if method == "host.execution.cancel":
                result.update(operationId=p["operationId"], requestDigest=p["requestDigest"])
        elif method == "host.execution.get":
            # The J-06 fixed projections carry the sample's scope; a Runtime-accepted action runs in the scope the
            # Host opened, and the HostClient checks the reply scope against the request. Only scopeRef is rebound
            # here (in addition to requestIdentity); every other sample field is returned unchanged.
            result["scopeRef"] = p["scopeRef"]
        elif method == "host.resource.read":
            evidence = p["evidence"]
            result.update(resourceHandle=evidence["resourceHandle"], revision=evidence["revision"], digest=evidence["digest"])
        return dict(context=p["context"], **result)


def launch_files(directory, fx, port_id, launcher):
    """launch.json / host-template.json for the product serve-stdio entry over the fixture repository."""
    import definition_fixture as DF
    from domain.implement_verify import projection
    DF.runtime_files(directory, dict(repo=fx.repo, taskId=fx.task_id))
    template_path = Path(directory) / "host-template.json"
    template = json.loads(template_path.read_text())
    for holder in (template, template["initialize"]):
        holder["capabilities"] = holder["capabilities"] + [projection.capability()]
    template_path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n")
    path = Path(directory) / "launch.json"
    config = json.loads(path.read_text())
    config["executionBindings"] = {port_id: dict(
        connectionRef=SAMPLE["connectionRef"], credentialRef="credential:claude-native", credentialRevision="1",
        configurationRevision=SAMPLE["configurationRevision"], agent="agent:claude-code", protocolProvider="anthropic",
        launcher=str(launcher), scopeRef=SAMPLE["scopeRef"], resourceHandle="resource:synthetic")}
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return template


class LoopHost(Host):
    """host_driver.Host over the product entrypoint, with scope activation and decided action invocation."""

    def __init__(self, directory, answers, output=None):
        super().__init__(directory, product=True, output=output)
        self.handlers.update(answers.handlers())

    def activate(self):
        result = self.call("runtime.scope.open", dict(binding=self.template["binding"]))
        methods = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                   "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]
        self.grants = [dict(ref=dict(id="grant:%s:%d" % (cap["id"], i), revision="1"),
                            installationId=self.context["installationId"], instanceId=self.context["instanceId"],
                            scopeRef=result["scopeRef"], resourceHandle="resource:one", capability=cap["id"],
                            operation=method, executionRef=None, bundleDigest="b" * 64, expiresAt="2099-01-01T00:00:00Z",
                            status="active", purpose="feature-t4 tests")
                       for cap in self.template["capabilities"] for i, method in enumerate(methods)]
        self.call("runtime.scope.authorize", dict(scopeRef=result["scopeRef"], grantRefs=self.refs()))
        return result["scopeRef"]

    def action(self, action_id):
        page = self.call("runtime.snapshot.open", dict(scopeRef=self.template["scopeRef"]))
        return next(a for a in page["actions"] if a["actionId"] == action_id)

    def invoke(self, action_id, payload, error=None):
        action = self.action(action_id)
        p = self.mutation("runtime.action.invoke", scopeRef=self.template["scopeRef"], actionId=action["actionId"],
                          objectRef=action["objectRef"], expectedRevision=action["expectedRevision"],
                          candidateRef=action["candidateRef"], grantRefs=self.refs(), payload=payload, decisionRef=None)
        for _ in range(2):
            decision = dict(decisionRef="decision:" + p["operationId"], scopeRef=p["scopeRef"], domainOperationId=p["operationId"],
                            method="runtime.action.invoke", requestDigest=p["requestDigest"], actionId=p["actionId"],
                            objectRef=p["objectRef"], candidateRef=p["candidateRef"], expectedRevision=p["expectedRevision"],
                            evidence=[], actorRef="human:synthetic", source="host-trusted-ui",
                            recordedAt="2026-09-23T00:00:00Z", status="valid")
            self.decisions[decision["decisionRef"]] = decision
            p["decisionRef"] = decision["decisionRef"]
            p["requestDigest"] = request_digest("runtime.action.invoke", p)
        return self.call("runtime.action.invoke", p, error=error), p

    def wait_operation(self, operation_id, statuses=("succeeded", "failed", "unknown"), seconds=90):
        import time
        deadline = time.monotonic() + seconds
        op = None
        while time.monotonic() < deadline:
            op = self.call("runtime.operation.get", dict(scopeRef=self.template["scopeRef"], operationId=operation_id))
            if op["status"] in statuses:
                return op
            time.sleep(0.1)
        raise AssertionError("operation did not settle: %s" % op)
