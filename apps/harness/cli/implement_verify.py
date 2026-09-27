"""harness implement <command> | harness verify <command> | config set implementer-ports (feature-t4).

The standalone entry calls the same Domain Core command point (apply_command) and runs executions on
feature-t3's execution layer with the same executors serve-stdio uses; no second rule set lives here. Every state
changing command takes the control generation first, so the other entry holding an older generation
is fenced out. Exit codes: 0 completed, 1 determinate rejection, 2 not determinable. Output is one JSON
document on stdout.
"""
import asyncio
import json
from pathlib import Path
import sys

from domain.core import open_domain
from domain.store import StoreUnavailable
from domain.workflow import results as workflow_results
from domain.workflow.results import WorkflowRejection
from domain.implement_verify import checks, executors, registration, results, steps
from domain.implement_verify.results import ImplementVerifyRejection


def emit(document):
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def _json(value, field):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--{field} must be a JSON document: {exc}")


def _domain(repository):
    domain = open_domain(repository, entry="cli")
    if not getattr(domain, "available", False):
        return None, dict(result=workflow_results.STORE_UNAVAILABLE,
                          reason=dict(code=workflow_results.STORE_UNAVAILABLE,
                                      message=getattr(domain, "unavailable_reason", "domain unavailable")))
    return domain, None


def _code(code):
    if code in results.RESULTS:
        return results.exit_code(code)
    return workflow_results.exit_code(code)


def _run(label, function):
    try:
        outcome = function()
    except ImplementVerifyRejection as exc:
        emit(dict(command=label, result=exc.code, reason=exc.reason()))
        return results.exit_code(exc.code)
    except WorkflowRejection as exc:
        emit(dict(command=label, result=exc.code, reason=exc.reason()))
        return workflow_results.exit_code(exc.code)
    except StoreUnavailable as exc:
        emit(dict(command=label, result=workflow_results.STORE_UNAVAILABLE,
                  reason=dict(code=workflow_results.STORE_UNAVAILABLE, message=str(exc))))
        return 2
    emit(dict(command=label, entry="cli", **outcome))
    return _code(outcome["result"])


def set_implementer_ports(repository, value, authority_ref):
    """`config set implementer-ports`: one fenced transaction on the product-side registration."""
    domain, failure = _domain(repository)
    if failure:
        emit(dict(command="config set", **failure))
        return 2
    entries = _json(value, "value")

    def apply():
        generation = domain.bind_entry()
        written = domain.transaction(generation, lambda s: registration.set_registration(s, entries, authority_ref))
        return dict(result=results.REGISTRATION_CONFIGURED, **written)
    return _run("config set", apply)


def cmd_implement(args):
    domain, failure = _domain(args.repository)
    if failure:
        emit(dict(command="implement " + args.command, **failure))
        return 2
    label = "implement " + args.command
    if args.command == "status":
        state = domain.read()
        task = state.get("tasks", {}).get(args.task_id)
        emit(dict(command=label, result="READ", taskId=args.task_id,
                  implementVerify=(task or {}).get("implementVerify"),
                  registration=registration.entries(state), checks=checks.declared(state)))
        return 0
    if args.command in ("dispatch", "remediate", "assess", "route"):
        name = "implement-" + args.command
        payload = dict(taskId=args.task_id, commandId=args.command_id, authorityRef=args.authority_ref)
        if args.command == "dispatch":
            payload.update(portId=args.port_id, worktree=args.worktree, finalizationRef=args.finalization_ref,
                           budget=_json(args.budget, "budget"), role=args.role, purpose=args.purpose)
        if args.command == "remediate":
            payload["budgetFact"] = args.budget_fact
        if args.command == "assess":
            payload["assessmentId"] = args.assessment_id

        def apply():
            generation = domain.bind_entry()
            return domain.run(name, payload, generation=generation, lock_wait=args.lock_wait)
        return _run(label, apply)
    if args.command == "run":
        return _run(label, lambda: run_standalone(domain, args))
    raise SystemExit("unknown implement command")


def run_standalone(domain, args):
    """Run a dispatched standalone execution on feature-t3's execution layer (the production executors).

    A pending descriptor is executed; a running one (an earlier entry stopped mid-run) or a settled one
    whose physical fact was unresolved (stop unconfirmed, unknown) is only queried. Nothing is re-executed.
    """
    from runtime.executions import Environment, build_port, run_pending
    from domain.implement_verify.executors import ImplementExecutor
    state = domain.read()
    record = steps.ledger(state, args.task_id)["executions"].get(args.execution_id)
    if record is None:
        raise ImplementVerifyRejection(results.POSITION_NOT_APPLICABLE, "no such execution on this task",
                                       executionRequestId=args.execution_id)
    if record["mode"] != "standalone":
        raise ImplementVerifyRejection(results.REGISTRY_ENTRY_MISSING, "a standalone run needs a standalone "
                                       "implementer registration; embedded executions run in serve-stdio",
                                       portId=record["portId"])
    generation = domain.bind_entry()
    env = Environment("cli", domain, generation, repository_root=str(domain.repository))
    descriptor = domain.read().get("executionDescriptors", {}).get(args.execution_id)
    refreshed = False
    if descriptor is not None and descriptor["status"] in ("pending", "running"):
        failures = run_pending(domain, env)
        if failures:
            raise ImplementVerifyRejection(results.INDETERMINATE, "the execution layer reported a failure",
                                           failures=failures)
    elif (record.get("settlement") or {}).get("reason") in (results.STOP_UNCONFIRMED, results.RESULT_UNKNOWN):
        asyncio.run(ImplementExecutor(build_port).query(dict(descriptor or {}, taskId=args.task_id,
                                                             executionId=args.execution_id), env))
        refreshed = True
    state = domain.read()
    record = steps.ledger(state, args.task_id)["executions"][args.execution_id]
    settlement = record.get("settlement") or {}
    if record["status"] != "settled":
        result = results.PENDING
    elif settlement.get("kind") == "completed":
        result = results.IMPLEMENT_COMPLETED
    else:
        result = results.SETTLED
    return dict(result=result, reason=settlement.get("reason"), refreshed=refreshed, execution=record,
                descriptor=state.get("executionDescriptors", {}).get(args.execution_id))


def cmd_verify(args):
    domain, failure = _domain(args.repository)
    if failure:
        emit(dict(command="verify " + args.command, **failure))
        return 2
    label = "verify " + args.command
    if args.command == "checks-list":
        emit(dict(command=label, result="READ", checks=checks.declared(domain.read())))
        return 0
    if args.command == "checks-set":
        value = _json(args.checks, "checks")

        def apply():
            generation = domain.bind_entry()
            written = domain.transaction(generation, lambda s: checks.set_checks(s, value, args.authority_ref))
            return dict(result=results.CHECKS_CONFIGURED, **written)
        return _run(label, apply)
    if args.command == "run":
        def apply():
            generation = domain.bind_entry()
            return executors.run_verify(domain, generation, args.task_id,
                                        dict(commandId=args.command_id, authorityRef=args.authority_ref))
        return _run(label, apply)
    raise SystemExit("unknown verify command")


def register(sub):
    implement = sub.add_parser("implement").add_subparsers(dest="command", required=True)
    for name in ("status", "dispatch", "run", "remediate", "assess", "route"):
        p = implement.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--task-id", required=True)
        p.add_argument("--lock-wait", type=float, default=None)
        if name == "status":
            continue
        if name == "run":
            p.add_argument("--execution-id", required=True)
            continue
        p.add_argument("--command-id", required=True)
        p.add_argument("--authority-ref", required=True)
        if name == "dispatch":
            p.add_argument("--port-id", required=True)
            p.add_argument("--worktree", required=True)
            p.add_argument("--finalization-ref", required=True)
            p.add_argument("--budget", required=True)
            p.add_argument("--role", default="implementer")
            p.add_argument("--purpose", default=registration.PURPOSE)
        if name == "remediate":
            p.add_argument("--budget-fact", required=True)
        if name == "assess":
            p.add_argument("--assessment-id", required=True)
    verify = sub.add_parser("verify").add_subparsers(dest="command", required=True)
    p = verify.add_parser("run")
    for option in ("--repository", "--task-id", "--command-id", "--authority-ref"):
        p.add_argument(option, required=True)
    p = verify.add_parser("checks-set")
    for option in ("--repository", "--checks", "--authority-ref"):
        p.add_argument(option, required=True)
    p = verify.add_parser("checks-list")
    p.add_argument("--repository", required=True)


def dispatch(args):
    if args.group == "implement":
        return cmd_implement(args)
    return cmd_verify(args)
