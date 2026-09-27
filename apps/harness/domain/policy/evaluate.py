"""One Policy Gate evaluation: validate the request, judge every item, record one policy-decision fact.

Runs inside the Domain Core unit of work (apply_command "policy-evaluate"), under the same writer lock
and control generation as every other command. It writes exactly one immutable policy-decision fact
through progression.record_fact with the Policy Gate as producer (plus, for a refused call of an
already allowed attempt, one per-call DENY fact). It never moves the Workflow: position, condition,
lifecycle and Runtime Version are untouched.
"""
import copy
import hashlib
import re

from domain.policy import items, rules
from domain.policy.inputs import InputsUnavailable
from domain.policy.results import (
    ALLOW, DENY, FAIL, NOT_APPLICABLE, NOT_CHECKED, NOT_DETERMINABLE, PolicyInputInvalid, conclude, reason,
)
from domain.workflow import progression
from runtime.protocol import canonical as runtime_canonical

HEX64 = re.compile(r"[0-9a-f]{64}")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
INTENT_REQUIRED = ("portId", "scopeRef", "profile", "executionBinding", "caller", "invocation_authorization")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _posint(value):
    return type(value) is int and value > 0


def validate_request(request, task_id):
    """Closed-set request validation; any problem is INPUT_INVALID and nothing is evaluated."""
    if not isinstance(request, dict):
        raise PolicyInputInvalid("the request must be a JSON object")
    if request.get("schema") != rules.REQUEST_SCHEMA:
        raise PolicyInputInvalid("unknown request schema", schema=request.get("schema"))
    subject = request.get("subject")
    if subject not in rules.SUBJECTS and subject not in rules.BUDGET_SUBJECTS:
        raise PolicyInputInvalid("evaluation subject outside the closed set", reasonCode="SUBJECT_NOT_IN_CLOSED_SET",
                                 subject=subject, subjects=list(rules.SUBJECTS) + list(rules.BUDGET_SUBJECTS))
    # feature-t5: the budget subjects carry only the common keys; their inputs are the recorded state.
    keys = rules.BUDGET_REQUEST_KEYS if subject in rules.BUDGET_SUBJECTS else rules.REQUEST_KEYS[subject]
    missing = [k for k in keys["required"] if k not in request]
    unknown = sorted(set(request) - set(keys["required"]) - set(keys["optional"]))
    if missing or unknown:
        raise PolicyInputInvalid("request keys outside the closed set", missing=missing, unknown=unknown)
    if request["taskId"] != task_id:
        raise PolicyInputInvalid("request taskId differs from the command taskId")
    if subject in (rules.REVIEW_RELEASE, rules.IMPLEMENT_RELEASE):
        if request["entry"] not in rules.ENTRIES or not _text(request["portId"]):
            raise PolicyInputInvalid("entry or portId invalid")
        intent = request["intent"]
        if not isinstance(intent, dict) or any(k not in intent for k in INTENT_REQUIRED):
            raise PolicyInputInvalid("intent lacks required fields", required=list(INTENT_REQUIRED))
        if not isinstance(intent["profile"], dict) or not isinstance(intent["executionBinding"], dict):
            raise PolicyInputInvalid("intent profile and executionBinding must be objects")
        if type(request["maxCalls"]) is not int:
            raise PolicyInputInvalid("maxCalls must be an integer")
    if subject == rules.REVIEW_RELEASE:
        obj = request["object"]
        if not isinstance(obj, dict) or obj.get("kind") not in ("definition", "candidate-change"):
            raise PolicyInputInvalid("object.kind must be definition or candidate-change")
        allowed = {"kind", "path", "commit", "bytes", "sha256"} if obj["kind"] == "definition" else {"kind", "path", "commit"}
        if set(obj) != allowed and not (obj["kind"] == "candidate-change" and set(obj) == {"kind", "commit"}):
            raise PolicyInputInvalid("object keys outside the closed set", allowed=sorted(allowed))
        if not FULL_SHA.fullmatch(str(obj["commit"])) or ("path" in obj and not _text(obj["path"])):
            raise PolicyInputInvalid("object commit must be a full lowercase SHA and path non-empty")
        if obj["kind"] == "definition" and not (_posint(obj["bytes"]) and HEX64.fullmatch(str(obj["sha256"]))):
            raise PolicyInputInvalid("definition object needs bytes and SHA-256")
        refs = request["authorExecutionRefs"]
        if not isinstance(refs, list) or not all(_text(r) for r in refs) or len(set(refs)) != len(refs):
            raise PolicyInputInvalid("authorExecutionRefs must be a list of distinct non-empty strings")
        declared = request.get("declaredAuthors")
        if declared is not None and (not isinstance(declared, dict) or set(declared) != {"vendors", "humanOnly"}
                                     or not isinstance(declared["vendors"], list)
                                     or not all(isinstance(v, str) for v in declared["vendors"])
                                     or type(declared["humanOnly"]) is not bool):
            raise PolicyInputInvalid("declaredAuthors must be {vendors: [str], humanOnly: bool}")
        review = request["review"]
        if not isinstance(review, dict) or set(review) != {"stage", "maxRounds", "roundExtensions"} \
                or review["stage"] not in ("task", "impl") \
                or not (review["maxRounds"] is None or _posint(review["maxRounds"])) \
                or not isinstance(review["roundExtensions"], list):
            raise PolicyInputInvalid("review must be {stage: task|impl, maxRounds: int|null, roundExtensions: []}")
        for ext in review["roundExtensions"]:
            if not isinstance(ext, dict) or set(ext) != {"authorized_by", "at", "added_rounds", "note"} \
                    or not _posint(ext["added_rounds"]) or not all(_text(ext[k]) for k in ("authorized_by", "at", "note")):
                raise PolicyInputInvalid("round extension must be a Human authorization record")
        if "round" in request and not _posint(request["round"]):
            raise PolicyInputInvalid("round must be a positive integer")
        if "attemptId" in request and not _text(request["attemptId"]):
            raise PolicyInputInvalid("attemptId must be a non-empty string")
    if subject == rules.IMPLEMENT_RELEASE:
        definition, final = request["definition"], request["finalization"]
        if not isinstance(definition, dict) or set(definition) != {"path", "commit", "bytes", "sha256"} \
                or not FULL_SHA.fullmatch(str(definition["commit"])) or not _text(definition["path"]) \
                or not _posint(definition["bytes"]) or not HEX64.fullmatch(str(definition["sha256"])):
            raise PolicyInputInvalid("definition must be {path, commit, bytes, sha256}")
        if not isinstance(final, dict) or set(final) != {"path", "commit"} or not FULL_SHA.fullmatch(str(final["commit"])) \
                or not _text(final["path"]):
            raise PolicyInputInvalid("finalization must be {path, commit}")
    if subject == rules.PUSH_PERMIT:
        push = request["push"]
        if not isinstance(push, dict) or set(push) != set(rules.PUSH_KEYS) \
                or not all(_text(push[k]) for k in rules.PUSH_KEYS) or not FULL_SHA.fullmatch(push["candidateCommit"]):
            raise PolicyInputInvalid("push must be {candidateCommit, sourceBranch, remote, targetBranch, repositoryIdentity}")
    return request


def stable_core(request):
    """The request without the intent fields that change on every call of one attempt."""
    core = copy.deepcopy(request)
    if isinstance(core.get("intent"), dict):
        for field in rules.PER_CALL_INTENT_FIELDS:
            core["intent"].pop(field, None)
    return core


def _judge(ctx):
    rows = []
    budget = ctx.subject in rules.BUDGET_SUBJECTS
    table = rules.BUDGET_ITEMS if budget else rules.ITEMS
    category = rules.BUDGET_CATEGORY if budget else rules.CATEGORY
    functions = items.BUDGET_FUNCTIONS if budget else items.FUNCTIONS
    for item in table:
        if not budget and rules.APPLICABILITY[item][ctx.subject] == rules.NA:
            rows.append(dict(item=item, category=category[item], result=NOT_APPLICABLE, reason=None))
            continue
        try:
            result, why = functions[item](ctx)
        except InputsUnavailable as exc:
            result, why = NOT_CHECKED, reason(exc.code if exc.code in ("REGISTRY_UNAVAILABLE", "ROUND_FACTS_UNREADABLE")
                                              else "INPUTS_UNAVAILABLE", str(exc), **exc.detail)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            # Malformed stored data is never a pass: fail closed as not checked.
            result, why = NOT_CHECKED, reason("INPUTS_UNAVAILABLE", "input could not be interpreted: "
                                              + type(exc).__name__ + ": " + str(exc)[:256])
        rows.append(dict(item=item, category=category[item], result=result, reason=why))
    return rows


def evaluate(state, topology, task_id, payload, *, revision, inputs):
    request = validate_request(payload.get("request"), task_id)
    inst = progression.instance(state, task_id)
    if request["subject"] in rules.BUDGET_SUBJECTS:
        node = rules.budget_ledger.LOOPS[request["subject"]]["node"]
        if inst["position"] != node:
            raise PolicyInputInvalid("a budget decision is evaluated only at its own budget node",
                                     reasonCode="BUDGET_POSITION_MISMATCH", subject=request["subject"], node=node,
                                     position=inst["position"])
    if inputs is None:
        return dict(result="NOT_RECORDED", conclusion=NOT_DETERMINABLE, factId=None,
                    reason=reason("INPUTS_UNAVAILABLE", "this entry provides no Policy inputs; nothing was evaluated"))
    ctx = items.Context(state, topology, task_id, request, inputs)
    rows = _judge(ctx)
    conclusion = conclude([r["result"] for r in rows])
    core = stable_core(request)
    request_digest = rules.digest(core)
    where = progression.occurrence(inst, task_id)
    budget = request["subject"] in rules.BUDGET_SUBJECTS
    decision = dict(schema=rules.DECISION_SCHEMA, subject=request["subject"],
                    ruleSetDigest=rules.BUDGET_RULE_SET_DIGEST if budget else rules.RULE_SET_DIGEST,
                    requestDigest=request_digest, occurrence=where, inputs=ctx.read, items=rows, conclusion=conclusion,
                    trustBoundary=ctx.trust_boundary, authorizationRefs=ctx.authorization_refs,
                    derived=dict(ctx.derived, maxCalls=request.get("maxCalls")))
    if budget and conclusion == ALLOW:
        # feature-t5 (Assistant KB-264): both Budget Remains and Budget Exhausted are ALLOW records.
        decision["outcome"] = ctx.derived["budget"]["outcome"]
    # The record identity is the digest of the whole decision content (subject, task, occurrence, stable
    # request, inputs read, item results, authorization references, conclusion): the same content is an
    # idempotent replay, any difference is a new record, and no identity is ever bound to two contents.
    fact_id = "policy:" + rules.digest(dict(taskId=task_id, decision=decision))
    recorded = progression.record_fact(state, topology, task_id,
                                       dict(factId=fact_id, kind=progression.POLICY_DECISION, purpose=request["subject"],
                                            authorityRef=payload.get("authorityRef"), payload=decision),
                                       revision=revision, producer=progression.POLICY_PRODUCER)
    outcome = dict(result="POLICY_RECORDED" if recorded["result"] == "RECORDED" else recorded["result"],
                   conclusion=conclusion, factId=fact_id, decision=copy.deepcopy(decision))
    call = payload.get("call")
    if conclusion == ALLOW and isinstance(call, dict):
        refused = _per_call(state, topology, task_id, payload, fact_id, request, call, revision)
        if refused is not None:
            outcome.update(conclusion=DENY, factId=refused["factId"], baseFactId=fact_id, decision=refused["payload"])
    return outcome


def _per_call(state, topology, task_id, payload, fact_id, request, call, revision):
    """Per-call checks of an allowed attempt; a refusal is its own recorded DENY."""
    request_id, scope = call.get("executionRequestId"), call.get("scopeRef")
    why = None
    manifest = request["intent"].get("inputManifestSha256")
    reservation = state.get("executionReservations", {}).get(request_id) if request_id else None
    if manifest is not None and not HEX64.fullmatch(str(manifest)):
        why = reason("INPUT_INVALID", "per-call inputManifestSha256 is not a SHA-256", value=manifest)
    elif reservation is not None and reservation.get("authorization_ref") not in (None, fact_id):
        why = reason("CALL_STABLE_CORE_MISMATCH", "this call's stable request differs from the one its reservation "
                     "was authorized under", authorized=reservation.get("authorization_ref"), recomputed=fact_id)
    else:
        key = hashlib.sha256(runtime_canonical([scope, fact_id])).hexdigest()
        counted = state.get("executionCallBudgets", {}).get(key)
        if counted and len(counted.get("requests", [])) >= counted.get("limit", 0) and request_id not in counted["requests"]:
            why = reason("CALL_LIMIT_EXHAUSTED", "the port's persisted call count reached the authorized maximum",
                         limit=counted.get("limit"), counted=len(counted["requests"]))
    if why is None:
        return None
    item = rules.BUDGET if why["code"] == "CALL_LIMIT_EXHAUSTED" else rules.INPUT_EVIDENCE
    call_id = fact_id + ":call:" + hashlib.sha256(str(request_id).encode()).hexdigest()
    decision = dict(schema=rules.DECISION_SCHEMA, subject=request["subject"], ruleSetDigest=rules.RULE_SET_DIGEST,
                    callOf=fact_id, executionRequestId=request_id,
                    items=[dict(item=item, category=rules.CATEGORY[item], result=FAIL, reason=why)],
                    conclusion=DENY, authorizationRefs=[], derived={})
    return progression.record_fact(state, topology, task_id,
                                   dict(factId=call_id, kind=progression.POLICY_DECISION, purpose=request["subject"],
                                        authorityRef=payload.get("authorityRef"), payload=decision),
                                   revision=revision, producer=progression.POLICY_PRODUCER)["fact"]


def decisions(state, task_id, fact_id=None):
    """Read recorded Policy Decisions of one task (read only)."""
    inst = progression.instance(state, task_id)
    rows = [copy.deepcopy(f) for f in inst["facts"].values()
            if f.get("kind") == progression.POLICY_DECISION and (fact_id is None or f["factId"] == fact_id)]
    return sorted(rows, key=lambda f: (f["domainRevision"], f["factId"]))
