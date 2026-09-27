"""SYNTHETIC composition root and Host driver for feature-t5 through a real serve-stdio process (AC-10). Tests only.

Run as `validation_stdio.py serve-stdio --launch-config <file> --repository <synthetic product line>`: the
production Domain Core, dispatcher, Runtime actions, execution layer, port factory and the real feature-t6
Policy Gate callback run in the child process; only the impl-round reviewer output is SYNTHETIC
(SyntheticImplReviewer in `authority` mode: the real callback decides, no Host execution is started).
ValidationHost drives it with host_driver's wire client: scope, grants, decided action invocations and
operation queries. No real Assistant, Agent or model.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from host_driver import Host, request_digest

APP = Path(__file__).resolve().parents[1]


def launch_files(directory, fx):
    """launch.json / host-template.json over the fixture repository, offering the feature-t5 capabilities."""
    import definition_fixture as DF
    from domain.budget import projection as budget_projection
    from domain.validation import projection as validation_projection
    DF.runtime_files(directory, dict(repo=fx.repo, taskId=fx.task_id))
    path = Path(directory) / "host-template.json"
    template = json.loads(path.read_text())
    for holder in (template, template["initialize"]):
        holder["capabilities"] = holder["capabilities"] + [budget_projection.capability(), validation_projection.capability()]
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n")
    return template


class ValidationHost(Host):
    def __init__(self, directory, env, output=None):
        directory = Path(directory)
        template = json.loads((directory / "host-template.json").read_text())
        command = [sys.executable, str(APP / "tests/validation_stdio.py"), "serve-stdio",
                   "--launch-config", str(directory / "launch.json"), "--repository", template["repository"]]
        saved = dict(os.environ)
        os.environ.update(env)
        try:
            super().__init__(directory, output=output, command=command)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def activate(self):
        result = self.call("runtime.scope.open", dict(binding=self.template["binding"]))
        methods = ["runtime.snapshot.open", "runtime.snapshot.next", "runtime.events.subscribe", "runtime.events.ack",
                   "runtime.action.invoke", "runtime.operation.get", "runtime.operation.cancel", "runtime.resource.read"]
        self.grants = [dict(ref=dict(id="grant:%s:%d" % (cap["id"], i), revision="1"), installationId=self.context["installationId"],
                            instanceId=self.context["instanceId"], scopeRef=result["scopeRef"], resourceHandle="resource:one",
                            capability=cap["id"], operation=method, executionRef=None, bundleDigest="b" * 64,
                            expiresAt="2099-01-01T00:00:00Z", status="active", purpose="feature-t5 tests")
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
        deadline = time.monotonic() + seconds
        op = None
        while time.monotonic() < deadline:
            op = self.call("runtime.operation.get", dict(scopeRef=self.template["scopeRef"], operationId=operation_id))
            if op["status"] in statuses:
                return op
            time.sleep(0.1)
        raise AssertionError("operation did not settle: %s" % op)


def serve():
    import validation_fixture as VF
    from domain.core import HarnessDomain
    from runtime.dispatcher import Dispatcher
    from runtime.executions import production_executors
    from runtime.protocol import Schemas
    from runtime.transport import Stdio

    class ValidationDispatcher(Dispatcher):
        def execution_executors(self):
            executors = production_executors()
            options = dict(human=True) if os.environ.get("HP_T5_HUMAN") == "1" else {}
            reviewer = VF.SyntheticImplReviewer(("valid", os.environ.get("HP_T5_VERDICT", "PASS"), options), mode="authority")
            executors.update(VF.executors(reviewer))
            return executors

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve-stdio"])
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    if not (args.repository / ".synthetic-hp-domain").is_file():
        raise SystemExit("Synthetic repository marker required")
    configuration = json.loads(args.launch_config.read_text())
    Schemas().validate("LaunchAuthorization", configuration["launchAuthorization"])
    transport = Stdio()
    transport.dispatcher = ValidationDispatcher(HarnessDomain(args.repository, entry="runtime"), configuration, transport)
    asyncio.run(transport.run())


if __name__ == "__main__":
    serve()
