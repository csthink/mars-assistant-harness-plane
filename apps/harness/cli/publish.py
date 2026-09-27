"""harness publish context|authorize|dispatch|run|query|reconcile|status | config set publish-target (feature-t7).

The standalone entry calls the same Domain Core command point (apply_command) the Runtime actions use and runs
publish executions and queries on feature-t3's execution layer with the production executors; no second rule
set lives here. Every state-changing command takes the control generation first, so the other entry holding an
older generation is fenced out. `run` executes this entry's pending publish descriptors and, for a descriptor
found running after a restart, only queries the same publish operation. `query` and `reconcile` register their
execution and run it at once. Exit codes: 0 completed, 1 determinate refusal (a DENY push permit included; its
record stays), 2 not determinable. Output is one JSON document on stdout.
"""
import json
from pathlib import Path
import sys

from domain.core import open_domain
from domain.definition.results import DefinitionRejection
from domain.policy.results import PolicyInputInvalid
from domain.publish import binding as publish_binding, configuration, records, results as publish_results
from domain.publish.results import PublishRejection
from domain.store import StoreUnavailable
from domain.validation.results import ValidationRejection
from domain.workflow import results as workflow_results
from domain.workflow.results import WorkflowRejection


def emit(document):
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def _json(value, field):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--{field} must be a JSON document: {exc}")


def exit_code(code):
    if code in publish_results.RESULTS:
        return publish_results.exit_code(code)
    if code in workflow_results.RESULTS:
        return workflow_results.exit_code(code)
    return 2


def _domain(repository):
    domain = open_domain(repository, entry="cli")
    if not getattr(domain, "available", False):
        return None, dict(result=workflow_results.STORE_UNAVAILABLE,
                          reason=dict(code=workflow_results.STORE_UNAVAILABLE,
                                      message=getattr(domain, "unavailable_reason", "domain unavailable")))
    return domain, None


def _run(label, function):
    try:
        outcome = function()
    except (PublishRejection, WorkflowRejection, ValidationRejection, DefinitionRejection) as exc:
        emit(dict(command=label, result=exc.code, reason=exc.reason()))
        return exit_code(exc.code) if exc.code in publish_results.RESULTS + workflow_results.RESULTS else 1
    except PolicyInputInvalid as exc:
        emit(dict(command=label, result="INPUT_INVALID", reason=exc.reason()))
        return 2
    except StoreUnavailable as exc:
        emit(dict(command=label, result=workflow_results.STORE_UNAVAILABLE,
                  reason=dict(code=workflow_results.STORE_UNAVAILABLE, message=str(exc))))
        return 2
    emit(dict(command=label, entry="cli", **outcome))
    return exit_code(outcome["result"])


# -- the binding arguments, shared with `validate decide` (feature-t5 Accept With reservation) ----------------------
def binding_arguments(parser):
    parser.add_argument("--candidate-commit", required=True, help="the task-branch head commit to publish (full id)")
    parser.add_argument("--source-branch", required=True, help="the Task Branch bound at acceptance")
    parser.add_argument("--remote", required=True, help="the Git remote name of publish-target")
    parser.add_argument("--target-branch", required=True, help="the pull request target branch of publish-target")
    parser.add_argument("--title", required=True, help="pull request title (one line)")
    parser.add_argument("--body-file", required=True, help="UTF-8 file with the pull request body")
    parser.add_argument("--context-digest", required=True, help="digest printed by `harness publish context`")


def binding_payload(args):
    try:
        body = Path(args.body_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemExit("--body-file must be a readable UTF-8 file: " + exc.__class__.__name__)
    return dict(publishBinding=dict(candidateCommit=args.candidate_commit, sourceBranch=args.source_branch, remote=args.remote,
                                    targetBranch=args.target_branch, pullRequest=dict(title=args.title, body=body)),
                contextDigest=args.context_digest)


def set_publish_target(repository, value, authority_ref):
    """`config set publish-target`: one fenced transaction on the product-side configuration."""
    domain, failure = _domain(repository)
    if failure:
        emit(dict(command="config set", **failure))
        return 2
    document = _json(value, "value")

    def apply():
        generation = domain.bind_entry()
        return domain.transaction(generation, lambda s: configuration.set_target(s, document, authority_ref))
    return _run("config set", apply)


def run_publish(domain, task_id):
    """Run this entry's pending publish and publish-query descriptors; running ones are only queried."""
    from runtime.executions import Environment, run_pending
    generation = domain.bind_entry()
    env = Environment("cli", domain, generation, repository_root=str(domain.repository))
    failures = run_pending(domain, env)
    state = domain.read()
    inst = state["tasks"][task_id]["workflowInstance"]
    return dict(result=publish_results.PUBLISH_READ, failures=failures, lifecycle=inst["lifecycle"], position=inst["position"],
                condition=inst["condition"], terminal=state["tasks"][task_id].get("terminal"),
                publish=records.view_of(state, task_id))


def status(domain, task_id):
    state = domain.read()
    inst = state["tasks"][task_id]["workflowInstance"]
    from domain.publish import projection
    return dict(result=publish_results.PUBLISH_READ, taskId=task_id, lifecycle=inst["lifecycle"], position=inst["position"],
                condition=inst["condition"], legal=sorted(projection.legal(state, task_id)),
                terminal=state["tasks"][task_id].get("terminal"), publish=records.view_of(state, task_id),
                recovery=dict(current=inst["recovery"]["current"],
                              assessment=(inst["recovery"]["assessments"].get(inst["recovery"]["current"] or "") or {}).get("assessment")))


def cmd_publish(args):
    domain, failure = _domain(args.repository)
    label = "publish " + args.command
    if failure:
        emit(dict(command=label, **failure))
        return 2
    if args.command == "status":
        return _run(label, lambda: status(domain, args.task_id))
    if args.command == "context":
        return _run(label, lambda: dict(result=publish_results.PUBLISH_CONTEXT_READ,
                                        **publish_binding.proposal(domain.read(), domain.repository, args.task_id)))
    if args.command == "run":
        return _run(label, lambda: run_publish(domain, args.task_id))
    payload = dict(taskId=args.task_id, commandId=args.command_id, authorityRef=args.authority_ref)
    if args.command == "authorize":
        payload.update(binding_payload(args), decisionText=args.decision_text)
    if args.command == "reconcile":
        payload.update(humanAuthorization=_json(args.human_authorization, "human-authorization"))
        if args.assessment_id:
            payload["assessmentId"] = args.assessment_id

    def apply():
        generation = domain.bind_entry()
        outcome = domain.run("publish-" + args.command, payload, generation=generation, lock_wait=args.lock_wait)
        if args.command in ("query", "reconcile") and outcome["result"] in (publish_results.QUERY_DISPATCHED,
                                                                            publish_results.RECONCILE_DISPATCHED):
            ran = run_publish(domain, args.task_id)
            execution = outcome["executionId"]
            descriptor = domain.read().get("executionDescriptors", {}).get(execution) or {}
            settled = descriptor.get("result") or {}
            outcome = dict(outcome, settled=dict(descriptor=descriptor.get("status"), classification=settled.get("classification"),
                                                 failureCode=settled.get("failureCode")), after=ran)
        return outcome
    return _run(label, apply)


def register(sub):
    group = sub.add_parser("publish").add_subparsers(dest="command", required=True)
    for name in ("context", "authorize", "dispatch", "run", "query", "reconcile", "status"):
        p = group.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--task-id", required=True)
        if name in ("context", "run", "status"):
            continue
        p.add_argument("--command-id", required=True)
        p.add_argument("--authority-ref", required=True)
        p.add_argument("--lock-wait", type=float, default=None)
        if name == "authorize":
            p.add_argument("--decision-text", required=True)
            binding_arguments(p)
        if name == "reconcile":
            p.add_argument("--human-authorization", required=True,
                           help="JSON {workflowInstance, occurrence, expectedRuntimeVersion, assessmentId, action, effectScope, "
                                "authorizationRef}; effectScope is publish-operation:<operation id>")
            p.add_argument("--assessment-id", default=None)


def dispatch(args):
    return cmd_publish(args)
