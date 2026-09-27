"""harness task resolve | task accept [--dry-run] | config set | workflow <command> | definition <command> | policy evaluate | policy show | implement | verify <command> (两个入口之一).

The standalone entry calls the very same Domain Core functions the delegated serve-stdio Runtime
calls; it holds no separate rule set and no separate state. Every state-changing workflow command
takes the control generation first, so a Runtime still holding an older generation is fenced out.

Exit codes: resolve 0 = determinate (RESOLVED or UNRESOLVED), 2 = INDETERMINATE;
accept 0 = ACCEPTED / IDEMPOTENT_REPLAY (or dry-run READY), 1 = determinate rejection,
2 = INDETERMINATE / PARTIAL_EFFECT_UNRESOLVED; workflow 0 = committed, 1 = determinate rejection,
2 = not determinable; policy evaluate 0 = ALLOW, 1 = DENY, 2 = NOT_DETERMINABLE or INPUT_INVALID (the
`result` field tells them apart; INPUT_INVALID records nothing). Output is one JSON document on stdout.
"""
import argparse
import json
import sys

from domain.acceptance import results
from domain.acceptance.accept import accept_task, set_configuration
from domain.acceptance.results import Rejection
from domain.acceptance.schema import DIGEST, SCHEMA_ID
from domain.acceptance.sources import INDETERMINATE, TASK_TYPES, resolve
from domain.core import open_domain
from domain.store import RuntimeStore, StoreUnavailable
from domain.workflow import results as workflow_results
from domain.workflow.results import WorkflowRejection
from cli.definition import cmd_definition, definition_parser
from cli import implement_verify
from cli import validation
from cli import publish

def emit(document):
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()

def store_for(repository):
    return RuntimeStore(repository, payload_schemas={DIGEST: SCHEMA_ID})

def cmd_resolve(args):
    if args.type != "feature":
        emit(dict(command="task resolve", result=results.SOURCE_LANE_UNAVAILABLE, reason=dict(code=results.SOURCE_LANE_UNAVAILABLE,
                  message="no source resolver for task type " + args.type)))
        return 1
    resolution = resolve(args.repository, args.type, args.task_id, args.base_ref)
    emit(dict(command="task resolve", result=resolution["outcome"], **{k: v for k, v in resolution.items() if k != "outcome"}))
    return 2 if resolution["outcome"] == INDETERMINATE else 0

def cmd_accept(args):
    request = dict(requestId=args.request_id, repository=args.repository, taskType=args.type, taskId=args.task_id,
                   baseRef=args.base_ref, worktreeRoot=args.worktree_root, authorityRef=args.authority_ref)
    try:
        outcome = accept_task(store_for(args.repository), request, dry_run=args.dry_run)
    except Rejection as exc:
        emit(dict(command="task accept", dryRun=args.dry_run, result=exc.code, reason=exc.reason()))
        return results.exit_code(exc.code)
    except StoreUnavailable as exc:
        code = results.UNRESOLVED if exc.determinate else results.INDETERMINATE
        emit(dict(command="task accept", dryRun=args.dry_run, result=code,
                  reason=dict(code=code, message="domain store unavailable: " + str(exc),
                              components=[dict(role="repository", path=args.repository, outcome=code, reason=str(exc), identity=None)])))
        return results.exit_code(code)
    emit(dict(command="task accept", **outcome))
    return 0

def cmd_config_set(args):
    key = args.key
    if key == "implementer-ports":
        return implement_verify.set_implementer_ports(args.repository, args.value, args.authority_ref)
    if key == "autonomous-budget":
        return validation.set_autonomous_budget(args.repository, args.value, args.authority_ref)
    if key == "publish-target":
        return publish.set_publish_target(args.repository, args.value, args.authority_ref)
    if key == "author-vendor":
        value = dict(agent=args.agent, model=args.model, vendor=args.value)
    elif key == "concurrency-limit":
        try:
            value = int(args.value)
        except ValueError:
            emit(dict(command="config set", result=results.WORKSPACE_ERROR, reason=dict(code=results.WORKSPACE_ERROR, message="value must be an integer")))
            return 1
    else:
        if args.value not in ("true", "false"):
            emit(dict(command="config set", result=results.WORKSPACE_ERROR, reason=dict(code=results.WORKSPACE_ERROR, message="value must be true or false")))
            return 1
        value = args.value == "true"
    try:
        outcome = set_configuration(store_for(args.repository), key, value, args.authority_ref)
    except Rejection as exc:
        emit(dict(command="config set", result=exc.code, reason=exc.reason()))
        return results.exit_code(exc.code)
    except StoreUnavailable as exc:
        code = results.UNRESOLVED if exc.determinate else results.INDETERMINATE
        emit(dict(command="config set", result=code, reason=dict(code=code, message=str(exc))))
        return results.exit_code(code)
    emit(dict(command="config set", result="CONFIGURED", key=key, **outcome))
    return 0

def json_option(value, field):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--{field} must be a JSON document: {exc}")

def workflow_payload(args):
    """Build the command payload; the Runtime action builds the same one from its wire payload."""
    payload = dict(taskId=args.task_id)
    for source, field in (("command_id", "commandId"), ("authority_ref", "authorityRef"),
                          ("expected_runtime_version", "expectedRuntimeVersion"), ("purpose", "purpose"),
                          ("decision", "decision"), ("reason_category", "reasonCategory"), ("edge", "edgeId"),
                          ("condition", "condition"), ("attempt_id", "attemptId"), ("status", "status"),
                          ("reservation_id", "reservationId"), ("execution_ref", "executionRef"),
                          ("assessment_id", "assessmentId"), ("assessment", "assessment"), ("action", "action")):
        value = getattr(args, source, None)
        if value is not None:
            payload[field] = value
    if getattr(args, "trigger", None):
        payload["triggers"] = list(args.trigger)
    if getattr(args, "mutates_external_state", False):
        payload["mutatesExternalState"] = True
    for source, field in (("fact", "fact"), ("evidence", "evidence"), ("settlement", "settlement"),
                          ("human_authorization", "humanAuthorization"), ("protects", "protects"),
                          ("checked", "checked"), ("scope", "scope")):
        value = json_option(getattr(args, source, None), source.replace("_", "-"))
        if value is not None:
            payload[field] = value
    if args.command == "fact":
        fact = payload.get("fact") or {}
        fact.setdefault("factId", args.fact_id)
        fact.setdefault("kind", args.kind)
        fact.setdefault("purpose", args.purpose)
        fact.setdefault("authorityRef", args.authority_ref)
        payload["fact"] = fact
    return payload

def cmd_workflow(args):
    domain = open_domain(args.repository, entry="cli")
    if not getattr(domain, "available", False):
        code = workflow_results.STORE_UNAVAILABLE
        emit(dict(command="workflow " + args.command, result=code,
                  reason=dict(code=code, message=getattr(domain, "unavailable_reason", "domain unavailable"))))
        return workflow_results.exit_code(code)
    if args.command == "status":
        emit(dict(command="workflow status", result="READ", **domain.status(args.task_id)))
        return 0
    try:
        generation = domain.bind_entry()
        outcome = domain.run(args.command, workflow_payload(args), generation=generation, lock_wait=args.lock_wait)
    except WorkflowRejection as exc:
        emit(dict(command="workflow " + args.command, result=exc.code, reason=exc.reason()))
        return workflow_results.exit_code(exc.code)
    emit(dict(command="workflow " + args.command, entry="cli", **outcome))
    return workflow_results.exit_code(outcome["result"])

def cmd_policy(args):
    """feature-t6 Policy Gate: evaluate and record one Policy Decision, or read recorded ones."""
    from domain.policy import results as policy_results
    from domain.policy.evaluate import decisions
    from domain.policy.results import PolicyInputInvalid
    domain = open_domain(args.repository, entry="cli")
    if not getattr(domain, "available", False):
        code = workflow_results.STORE_UNAVAILABLE
        emit(dict(command="policy " + args.command, result=code,
                  reason=dict(code=code, message=getattr(domain, "unavailable_reason", "domain unavailable"))))
        return workflow_results.exit_code(code)
    if args.command == "show":
        try:
            rows = decisions(domain.store.read(), args.task_id, args.fact_id)
        except WorkflowRejection as exc:
            emit(dict(command="policy show", result=exc.code, reason=exc.reason()))
            return workflow_results.exit_code(exc.code)
        emit(dict(command="policy show", result="READ", taskId=args.task_id, decisions=rows))
        return 0
    try:
        text = args.request
        if text.startswith("@"):
            with open(text[1:], encoding="utf-8") as handle:
                text = handle.read()
        request = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        emit(dict(command="policy evaluate", result=policy_results.INPUT_INVALID,
                  reason=dict(code=policy_results.INPUT_INVALID, message="request is not readable JSON: " + str(exc))))
        return policy_results.exit_code(policy_results.INPUT_INVALID)
    payload = dict(taskId=args.task_id, authorityRef=args.authority_ref, request=request)
    try:
        generation = domain.bind_entry()
        outcome = domain.run("policy-evaluate", payload, generation=generation, lock_wait=args.lock_wait)
    except PolicyInputInvalid as exc:
        emit(dict(command="policy evaluate", result=policy_results.INPUT_INVALID, reason=exc.reason()))
        return policy_results.exit_code(policy_results.INPUT_INVALID)
    except WorkflowRejection as exc:
        emit(dict(command="policy evaluate", result=exc.code, reason=exc.reason()))
        return workflow_results.exit_code(exc.code)
    emit(dict(command="policy evaluate", entry="cli", **outcome))
    return policy_results.exit_code(outcome["conclusion"])

# command -> (required options, optional options); triggers and flags are added separately below.
WORKFLOW_COMMANDS = {
    "status": ((), ()),
    "decide": (("decision",), ("reason-category",)),
    "close": ((), ("reason-category",)),
    "advance": (("edge",), ()),
    "condition": (("condition",), ()),
    "fact": (("fact-id", "kind"), ("fact",)),
    "publish-finalize": ((), ()),
    "attempt-open": (("attempt-id",), ()),
    "attempt-settle": (("attempt-id", "status"), ("evidence",)),
    "attempt-start": (("attempt-id",), ("execution-ref",)),
    "reserve": (("reservation-id",), ("execution-ref", "protects")),
    "reservation-settle": (("reservation-id",), ("settlement",)),
    "recover-assess": (("assessment-id", "assessment"), ("checked", "evidence")),
    "recover": (("action",), ("assessment-id", "human-authorization", "scope", "evidence")),
}
WORKFLOW_TRIGGERS = ("advance", "condition", "publish-finalize", "close")
# Commands whose identity is their own field rather than a Progression Command Identity.
WORKFLOW_NO_COMMAND_ID = ("fact", "attempt-open", "attempt-settle", "attempt-start", "reserve", "reservation-settle", "recover-assess")

def workflow_parser(sub):
    group = sub.add_parser("workflow").add_subparsers(dest="command", required=True)
    for name, (required, optional) in WORKFLOW_COMMANDS.items():
        p = group.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--lock-wait", type=float, default=None)
        if name == "status":
            p.add_argument("--task-id", default=None)
            continue
        p.add_argument("--task-id", required=True)
        p.add_argument("--authority-ref", required=True)
        p.add_argument("--expected-runtime-version", default=None)
        p.add_argument("--purpose", default=None)
        if name not in WORKFLOW_NO_COMMAND_ID:
            p.add_argument("--command-id", required=True)
        for field in required:
            p.add_argument("--" + field, required=True)
        for field in optional:
            p.add_argument("--" + field, default=None)
        if name in WORKFLOW_TRIGGERS:
            p.add_argument("--trigger", action="append", default=[])
        if name == "recover":
            p.add_argument("--mutates-external-state", action="store_true")

def policy_parser(sub):
    group = sub.add_parser("policy").add_subparsers(dest="command", required=True)
    evaluate = group.add_parser("evaluate")
    evaluate.add_argument("--repository", required=True)
    evaluate.add_argument("--task-id", required=True)
    evaluate.add_argument("--request", required=True, help="hp-policy-request/v1 JSON text, or @<file>")
    evaluate.add_argument("--authority-ref", required=True)
    evaluate.add_argument("--lock-wait", type=float, default=None)
    show = group.add_parser("show")
    show.add_argument("--repository", required=True)
    show.add_argument("--task-id", required=True)
    show.add_argument("--fact-id", default=None)

def parser():
    top = argparse.ArgumentParser(prog="harness")
    sub = top.add_subparsers(dest="group", required=True)
    workflow_parser(sub)
    definition_parser(sub)
    policy_parser(sub)
    implement_verify.register(sub)
    validation.register(sub)
    publish.register(sub)
    task = sub.add_parser("task").add_subparsers(dest="command", required=True)
    for name in ("resolve", "accept"):
        p = task.add_parser(name)
        p.add_argument("--repository", required=True)
        p.add_argument("--type", required=True, choices=TASK_TYPES)
        p.add_argument("--task-id", required=True)
        p.add_argument("--base-ref", required=True)
        if name == "accept":
            p.add_argument("--request-id", required=True)
            p.add_argument("--authority-ref", required=True)
            p.add_argument("--worktree-root", required=True)
            p.add_argument("--dry-run", action="store_true")
    config = sub.add_parser("config").add_subparsers(dest="command", required=True)
    setter = config.add_parser("set")
    setter.add_argument("key", choices=("concurrency-limit", "definition-review", "change-validation", "author-vendor",
                                        "implementer-ports", "autonomous-budget", "publish-target"))
    setter.add_argument("value")
    setter.add_argument("--repository", required=True)
    setter.add_argument("--authority-ref", required=True)
    setter.add_argument("--agent", default=None, help="author-vendor: agent identity as in execution records")
    setter.add_argument("--model", default=None, help="author-vendor: model identity as in execution records")
    return top

def main(argv=None):
    args = parser().parse_args(argv)
    if args.group in ("implement", "verify"):
        return implement_verify.dispatch(args)
    if args.group in ("budget", "validate"):
        return validation.dispatch(args)
    if args.group == "publish":
        return publish.dispatch(args)
    if args.group == "workflow":
        return cmd_workflow(args)
    if args.group == "definition":
        return cmd_definition(args)
    if args.group == "policy":
        return cmd_policy(args)
    if args.group == "task" and args.command == "resolve":
        return cmd_resolve(args)
    if args.group == "task" and args.command == "accept":
        return cmd_accept(args)
    return cmd_config_set(args)

if __name__ == "__main__":
    raise SystemExit(main())
