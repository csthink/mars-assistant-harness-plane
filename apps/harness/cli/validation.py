"""harness budget decide|status | harness validate <command> | config set autonomous-budget (feature-t5).

The standalone entry calls the same Domain Core command point (apply_command) the Runtime actions use and
runs change reviews on feature-t3's execution layer with the production executors; no second rule set
lives here. Every state-changing command takes the control generation first, so the other entry holding an
older generation is fenced out. Exit codes: 0 completed, 1 determinate refusal (a DENY budget decision
included; its record stays), 2 not determinable (a NOT_DETERMINABLE budget decision included). Output is
one JSON document on stdout.
"""
import json
import sys

from domain.budget import commands as budget_commands, configuration, results as budget_results
from domain.budget.results import BudgetRejection
from domain.core import open_domain
from domain.definition.results import DefinitionRejection
from domain.implement_verify.results import ImplementVerifyRejection
from domain.policy.results import PolicyInputInvalid
from domain.store import StoreUnavailable
from domain.validation import records, results as validation_results
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
    if code in budget_results.RESULTS:
        return budget_results.exit_code(code)
    if code in validation_results.RESULTS:
        return validation_results.exit_code(code)
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
    except (BudgetRejection, ValidationRejection, WorkflowRejection, DefinitionRejection, ImplementVerifyRejection) as exc:
        emit(dict(command=label, result=exc.code, reason=exc.reason()))
        return exit_code(exc.code) if exc.code in budget_results.RESULTS + validation_results.RESULTS + workflow_results.RESULTS else 1
    except PolicyInputInvalid as exc:
        emit(dict(command=label, result="INPUT_INVALID", reason=exc.reason()))
        return 2
    except StoreUnavailable as exc:
        emit(dict(command=label, result=workflow_results.STORE_UNAVAILABLE,
                  reason=dict(code=workflow_results.STORE_UNAVAILABLE, message=str(exc))))
        return 2
    emit(dict(command=label, entry="cli", **outcome))
    return exit_code(outcome["result"])


def set_autonomous_budget(repository, value, authority_ref):
    """`config set autonomous-budget`: one fenced transaction on the product-side configuration."""
    domain, failure = _domain(repository)
    if failure:
        emit(dict(command="config set", **failure))
        return 2
    document = _json(value, "value")

    def apply():
        generation = domain.bind_entry()
        return domain.transaction(generation, lambda s: configuration.set_budget(s, document, authority_ref))
    return _run("config set", apply)


def cmd_budget(args):
    domain, failure = _domain(args.repository)
    label = "budget " + args.command
    if failure:
        emit(dict(command=label, **failure))
        return 2
    if args.command == "status":
        return _run(label, lambda: dict(result=budget_results.BUDGET_READ, taskId=args.task_id,
                                        **budget_commands.status(domain.read(), args.task_id)))

    def apply():
        generation = domain.bind_entry()
        return domain.run("budget-decide", dict(taskId=args.task_id, commandId=args.command_id, authorityRef=args.authority_ref),
                          generation=generation, lock_wait=args.lock_wait)
    return _run(label, apply)


def run_changes(domain, task_id):
    """Run this entry's pending change-review and ruling descriptors on feature-t3's execution layer."""
    from runtime.executions import Environment, run_pending
    generation = domain.bind_entry()
    env = Environment("cli", domain, generation, repository_root=str(domain.repository))
    failures = run_pending(domain, env)
    view = records.publish_context(domain.read(), task_id)
    return dict(result=validation_results.VALIDATION_READ, failures=failures, rounds=view["rounds"],
                position=domain.read()["tasks"][task_id]["workflowInstance"]["position"])


def cmd_validate(args):
    domain, failure = _domain(args.repository)
    label = "validate " + args.command
    if failure:
        emit(dict(command=label, **failure))
        return 2
    if args.command == "status":
        return _run(label, lambda: dict(result=validation_results.VALIDATION_READ,
                                        **records.publish_context(domain.read(), args.task_id)))
    if args.command == "run":
        return _run(label, lambda: run_changes(domain, args.task_id))
    payload = dict(taskId=args.task_id, commandId=args.command_id, authorityRef=args.authority_ref)
    if getattr(args, "port_id", None):
        payload["portId"] = args.port_id
    if args.command == "formal-authorize":
        payload["maxCalls"] = args.max_calls
    if args.command == "dispatch" and args.round_extensions:
        payload["roundExtensions"] = _json(args.round_extensions, "round-extensions")
    if args.command == "dispose":
        payload.update(decisionText=args.decision_text, findings=_json(args.findings, "findings"))
    if args.command == "decide":
        payload.update(decision="Accept With reservation", decisionText=args.decision_text, reservation=args.reservation)
        from cli.publish import binding_payload  # feature-t7: this decision is the path's Publish authorization
        payload.update(binding_payload(args))

    def apply():
        generation = domain.bind_entry()
        return domain.run("validate-" + args.command, payload, generation=generation, lock_wait=args.lock_wait)
    return _run(label, apply)


def register(sub):
    budget = sub.add_parser("budget").add_subparsers(dest="command", required=True)
    for name in ("decide", "status"):
        p = budget.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--task-id", required=True)
        if name == "decide":
            p.add_argument("--command-id", required=True)
            p.add_argument("--authority-ref", required=True)
            p.add_argument("--lock-wait", type=float, default=None)
    validate = sub.add_parser("validate").add_subparsers(dest="command", required=True)
    for name in ("configure", "formal-authorize", "dispatch", "run", "dispose", "decide", "resume", "status"):
        p = validate.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--task-id", required=True)
        if name in ("run", "status"):
            continue
        p.add_argument("--command-id", required=True)
        p.add_argument("--authority-ref", required=True)
        p.add_argument("--lock-wait", type=float, default=None)
        if name in ("formal-authorize", "dispatch"):
            p.add_argument("--port-id", default=None)
        if name == "formal-authorize":
            p.add_argument("--max-calls", type=int, required=True)
        if name == "dispatch":
            p.add_argument("--round-extensions", default=None)
        if name == "dispose":
            p.add_argument("--decision-text", required=True)
            p.add_argument("--findings", required=True)
        if name == "decide":
            p.add_argument("--decision-text", required=True)
            p.add_argument("--reservation", required=True)
            from cli.publish import binding_arguments  # feature-t7: the same binding arguments as publish authorize
            binding_arguments(p)


def dispatch(args):
    if args.group == "budget":
        return cmd_budget(args)
    return cmd_validate(args)
