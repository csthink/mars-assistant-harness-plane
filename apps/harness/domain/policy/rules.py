"""The fixed rule tables of the Policy Gate (feature-t6 design, 判定项、评估对象与适用表).

Nothing here is chosen by a caller: applicability, required purposes, budget fields and call limits
are constants whose canonical bytes form the rule-set identity recorded in every Policy Decision.
"""
import hashlib
import json

from domain.workflow.progression import POLICY_DECISION, POLICY_PRODUCER  # noqa: F401  (re-exported)

AUTHOR_VENDORS = "author-vendors"
REVIEWER_ELIGIBILITY = "reviewer-eligibility"
INPUT_EVIDENCE = "input-evidence"
PROFILE_PURPOSE_ENTRY = "profile-purpose-entry"
HUMAN_AUTHORITY = "human-authority"
PUSH_PERMIT_ITEM = "push-permit"
BUDGET = "budget"
ITEMS = (AUTHOR_VENDORS, REVIEWER_ELIGIBILITY, INPUT_EVIDENCE, PROFILE_PURPOSE_ENTRY, HUMAN_AUTHORITY, PUSH_PERMIT_ITEM,
         BUDGET)

REVIEW_RELEASE, IMPLEMENT_RELEASE, PUSH_PERMIT = "review-release", "implement-release", "push-permit"
SUBJECTS = (REVIEW_RELEASE, IMPLEMENT_RELEASE, PUSH_PERMIT)

A, NA = "A", "NA"
APPLICABILITY = {
    AUTHOR_VENDORS: {REVIEW_RELEASE: A, IMPLEMENT_RELEASE: NA, PUSH_PERMIT: NA},
    REVIEWER_ELIGIBILITY: {REVIEW_RELEASE: A, IMPLEMENT_RELEASE: NA, PUSH_PERMIT: NA},
    INPUT_EVIDENCE: {REVIEW_RELEASE: A, IMPLEMENT_RELEASE: A, PUSH_PERMIT: A},
    PROFILE_PURPOSE_ENTRY: {REVIEW_RELEASE: A, IMPLEMENT_RELEASE: A, PUSH_PERMIT: NA},
    HUMAN_AUTHORITY: {REVIEW_RELEASE: A, IMPLEMENT_RELEASE: A, PUSH_PERMIT: A},
    PUSH_PERMIT_ITEM: {REVIEW_RELEASE: NA, IMPLEMENT_RELEASE: NA, PUSH_PERMIT: A},
    BUDGET: {REVIEW_RELEASE: A, IMPLEMENT_RELEASE: A, PUSH_PERMIT: NA},
}
# D-04 §7 limits what Policy produces to Applicability / Budget Decision Facts.
CATEGORY = {item: ("Budget" if item == BUDGET else "Applicability") for item in ITEMS}

PURPOSE = {REVIEW_RELEASE: ("review", "review"), IMPLEMENT_RELEASE: ("coding-implementer", "implement")}
ENTRIES = ("embedded", "standalone")
BUDGET_FIELDS = ("maxToolCalls", "maxRunSeconds", "maxOutputBytes", "cleanupSeconds")
MAX_OUTPUT_BYTES = 16777216
MAX_CALLS = {REVIEW_RELEASE: 2, IMPLEMENT_RELEASE: 1}
# Intent fields that change on every call of one attempt; excluded from the request's stable core.
PER_CALL_INTENT_FIELDS = ("executionRequestId", "inputManifestSha256", "instructionSha256")

FORMAL_PURPOSE = "owner-formal-review-authorization"
GATE_DECISION_PURPOSE = "gate-decision"
# Human authority chains (design, Human authority 判据).
PUSH_DECISION_EDGES = ("E-V06", "E-V12")
IMPLEMENT_DECISION_EDGES = ("E-D09", "E-D14")
IMPLEMENT_CONTINUE_EDGES = ("E-I11", "E-V10")
PUSH_POSITION = "N-PUBLISH"
IMPLEMENT_POSITIONS = ("N-IMPL-DISPATCH", "N-IMPL-EXECUTE", "N-VERIFY-AUTONOMOUS-REMEDIATION",
                       "N-VERIFY-HUMAN-REMEDIATION", "N-VALIDATE-REMEDIATION-DISPATCH")

REQUEST_SCHEMA = "hp-policy-request/v1"
DECISION_SCHEMA = "hp-policy-decision/v1"
REQUEST_KEYS = {
    REVIEW_RELEASE: dict(required=("schema", "subject", "taskId", "entry", "portId", "intent", "object",
                                   "authorExecutionRefs", "review", "maxCalls"),
                         optional=("declaredAuthors", "round", "attemptId")),
    IMPLEMENT_RELEASE: dict(required=("schema", "subject", "taskId", "entry", "portId", "intent", "definition",
                                      "finalization", "maxCalls"), optional=()),
    PUSH_PERMIT: dict(required=("schema", "subject", "taskId", "push"), optional=()),
}
PUSH_KEYS = ("candidateCommit", "sourceBranch", "remote", "targetBranch", "repositoryIdentity")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


RULE_SET = dict(items=ITEMS, subjects=SUBJECTS, applicability=APPLICABILITY, category=CATEGORY, purpose=PURPOSE,
                entries=ENTRIES, budgetFields=BUDGET_FIELDS, maxOutputBytes=MAX_OUTPUT_BYTES, maxCalls=MAX_CALLS,
                perCallIntentFields=PER_CALL_INTENT_FIELDS, formalPurpose=FORMAL_PURPOSE,
                pushDecisionEdges=PUSH_DECISION_EDGES, implementDecisionEdges=IMPLEMENT_DECISION_EDGES,
                implementContinueEdges=IMPLEMENT_CONTINUE_EDGES, pushPosition=PUSH_POSITION,
                implementPositions=IMPLEMENT_POSITIONS, requestSchema=REQUEST_SCHEMA, decisionSchema=DECISION_SCHEMA)
RULE_SET_DIGEST = digest(RULE_SET)

# -- feature-t5: the three autonomous budget subjects (Assistant KB-264) ----------------------------
# A separate rule table with its own identity: the bytes and the digest of RULE_SET above stay unchanged,
# so decisions (and the port call counts keyed by their factId) of the three execution and push subjects
# recompute to the same identity after feature-t5. A budget decision is ALLOW when it can be made on sound
# records; its `outcome` field (the topology edge label) says Budget Remains or Budget Exhausted.
from domain.budget import ledger as budget_ledger  # noqa: E402  (budget.ledger never imports domain.policy)

AUTONOMOUS_BUDGET = "autonomous-budget"
DEFINITION_BUDGET, VERIFICATION_BUDGET, VALIDATION_BUDGET = (budget_ledger.DEFINITION, budget_ledger.VERIFICATION,
                                                             budget_ledger.VALIDATION)
BUDGET_SUBJECTS = budget_ledger.SUBJECTS
BUDGET_ITEMS = (INPUT_EVIDENCE, AUTONOMOUS_BUDGET)
BUDGET_CATEGORY = {INPUT_EVIDENCE: "Applicability", AUTONOMOUS_BUDGET: "Budget"}
BUDGET_OUTCOMES = budget_ledger.OUTCOMES
BUDGET_REQUEST_KEYS = dict(required=("schema", "subject", "taskId"), optional=())
BUDGET_RULE_SET = dict(items=BUDGET_ITEMS, subjects=BUDGET_SUBJECTS, category=BUDGET_CATEGORY, outcomes=BUDGET_OUTCOMES,
                       loops=budget_ledger.LOOPS, requestKeys=BUDGET_REQUEST_KEYS, requestSchema=REQUEST_SCHEMA,
                       decisionSchema=DECISION_SCHEMA, configurationKey="autonomous-budget",
                       window="latest Continue at the loop's escalation gate, else the first FAIL arrival",
                       grant="configuration in force at the window start, else the first configuration after it",
                       consumption="Budget Remains progressions after the window start, each bound to a Remains decision")
BUDGET_RULE_SET_DIGEST = digest(BUDGET_RULE_SET)
