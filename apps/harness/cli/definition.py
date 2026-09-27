"""harness definition <submit|revise|dispatch|query|decide|formal-authorize|status> (feature-t3).

The standalone entry calls the same Definition command functions the serve-stdio actions call. A
command that registers external work (dispatch, decide) then runs that work to completion in this
process with the same execution layer the Runtime uses (standalone ports), and `query` settles work
left running by an earlier process by querying it only, never by executing it again.

Exit codes: 0 completed, 1 determinate rejection, 2 not determinable. Output is one JSON document.
"""
import json
import sys

from domain.core import open_domain
from domain.definition import results as definition_results
from domain.definition.results import DefinitionRejection
from domain.workflow import results as workflow_results
from domain.workflow.results import WorkflowRejection

COMMANDS = ("submit", "revise", "dispatch", "query", "decide", "formal-authorize", "status")


def emit(document):
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def code_of(code):
    if code in definition_results.RESULTS:
        return definition_results.exit_code(code)
    return workflow_results.exit_code(code) if code in workflow_results.RESULTS else 2


def payload_of(args):
    payload = dict(taskId=args.task_id, commandId=args.command_id, authorityRef=args.authority_ref)
    if args.expected_runtime_version is not None:
        payload["expectedRuntimeVersion"] = args.expected_runtime_version
    if args.command in ("submit", "revise"):
        payload["commit"] = args.commit
        try:
            payload["author"] = json.loads(args.author)
        except json.JSONDecodeError as exc:
            raise DefinitionRejection(definition_results.INPUT_INVALID, "--author must be a JSON document: " + str(exc)) from exc
    if args.command == "decide":
        payload.update(decision=args.decision, decisionText=args.decision_text)
        if args.reservation is not None:
            payload["reservation"] = args.reservation
        if args.findings is not None:
            try:
                payload["findings"] = json.loads(args.findings)
            except json.JSONDecodeError as exc:
                raise DefinitionRejection(definition_results.INPUT_INVALID, "--findings must be a JSON object: " + str(exc)) from exc
    if args.command == "formal-authorize":
        payload["maxCalls"] = args.max_calls
        if args.port_id is not None:
            payload["portId"] = args.port_id
    return payload


def run_pending(domain, generation, spool):
    from runtime.executions import Environment, run_pending as run
    env = Environment("cli", domain, generation, repository_root=domain.repository, spool=spool)
    return run(domain, env)


def cmd_definition(args):
    domain = open_domain(args.repository, entry="cli")
    if not getattr(domain, "available", False):
        code = workflow_results.STORE_UNAVAILABLE
        emit(dict(command="definition " + args.command, result=code,
                  reason=dict(code=code, message=getattr(domain, "unavailable_reason", "domain unavailable"))))
        return workflow_results.exit_code(code)
    if args.command == "status":
        emit(dict(command="definition status", result="READ", **domain.definition_status(args.task_id)))
        return 0
    try:
        generation = domain.bind_entry()
        outcome = None
        if args.command != "query":
            name = "submit" if args.command == "revise" else args.command
            outcome = domain.run_definition(name, payload_of(args), generation=generation, lock_wait=args.lock_wait)
        failures = []
        if args.command in ("dispatch", "decide", "query"):
            failures = run_pending(domain, generation, args.spool)
        view = domain.definition_status(args.task_id)
    except (WorkflowRejection, DefinitionRejection) as exc:
        emit(dict(command="definition " + args.command, result=exc.code, reason=exc.reason()))
        return code_of(exc.code)
    if outcome is None:
        outcome = dict(result="READ")
    emit(dict(command="definition " + args.command, entry="cli", **outcome, executionFailures=failures,
              definition=view))
    return code_of(outcome["result"]) if outcome["result"] != "READ" else 0


def definition_parser(sub):
    group = sub.add_parser("definition").add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        p = group.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--task-id", required=True)
        p.add_argument("--lock-wait", type=float, default=None)
        if name == "status":
            continue
        p.add_argument("--spool", default=None)
        if name == "query":
            continue
        p.add_argument("--command-id", required=True)
        p.add_argument("--authority-ref", required=True)
        p.add_argument("--expected-runtime-version", default=None)
        if name in ("submit", "revise"):
            p.add_argument("--commit", required=True)
            p.add_argument("--author", required=True)
        if name == "decide":
            p.add_argument("--decision", required=True)
            p.add_argument("--decision-text", required=True)
            p.add_argument("--reservation", default=None)
            p.add_argument("--findings", default=None)
        if name == "formal-authorize":
            p.add_argument("--max-calls", type=int, required=True)
            p.add_argument("--port-id", default=None)
