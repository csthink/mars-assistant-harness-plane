"""One pure function per judgement item (feature-t6 design, 评估请求形态与逐项读取).

Every function reads the domain state, the validated request and PolicyInputs, and returns an item
result with a reason; none of them writes anything. An input that cannot be read raises
InputsUnavailable and the caller turns it into NOT_CHECKED. Within one item a determinate FAIL
outranks a NOT_CHECKED, and only a clean pass is PASS.
"""
import copy

from domain.policy import rules
from domain.policy.inputs import InputsUnavailable, identity, vendors
from domain.policy.results import FAIL, NOT_CHECKED, PASS, reason
from domain.workflow.progression import occurrence

HUMAN_DECISION = "human-decision"
CAPABILITY_STATES = ("REGISTERED", "CONFIGURED", "UNVERIFIED", "PROBED", "REVIEW_ENABLED")


class Context:
    """Everything one evaluation reads, plus what it derives for the record and the callback."""

    def __init__(self, state, topology, task_id, request, inputs):
        self.state, self.topology, self.task_id, self.request, self.inputs = state, topology, task_id, request, inputs
        self.subject = request["subject"]
        self.task = state["tasks"][task_id]
        self.inst = self.task["workflowInstance"]
        self.intent = request.get("intent") or {}
        self.read = []            # identities of what was read, recorded as the decision's inputs
        self.derived = dict(authorVendors=[], authorEvidenceRefs=[], humanOnly=False, ownerFormal=False,
                            reviewerVendor=None)
        self.authorization_refs = []
        self.trust_boundary = None
        self.publish_decision = None
        self._chain = None
        self._formal = None

    def note(self, role, ref, **ident):
        row = dict(role=role, ref=ref, **ident)
        if row not in self.read:
            self.read.append(row)

    # -- Registry reads with identity ---------------------------------------------------------------
    def reviewer_port(self):
        port, loaded = self.inputs.reviewer_port(self.request["portId"])
        self.note("registry", loaded["path"], sha256=loaded["sha256"], revision=loaded["revision"],
                  synthetic=bool(loaded.get("synthetic")))
        return port

    def registration(self):
        """The port registration this subject is checked against, or None when it cannot be read."""
        if self.subject == rules.REVIEW_RELEASE:
            return self.reviewer_port()
        found = self.inputs.implementer_registration(self.state, self.request["portId"])
        if found is not None:
            self.note("implementer-registration", self.request["portId"], sha256=rules.digest(found),
                      synthetic=bool(found.get("synthetic")))
        return found

    # -- Owner formal authorization fact (written by feature-t3, read here) ------------------------
    def formal_fact(self):
        if self._formal is None:
            obj = {k: v for k, v in self.request["object"].items() if k != "kind"}
            profile_digest = (self.intent.get("profile") or {}).get("digest")
            hits = []
            for fact in self.inst["facts"].values():
                body = fact.get("payload") or {}
                if fact.get("kind") != HUMAN_DECISION or fact.get("purpose") != rules.FORMAL_PURPOSE:
                    continue
                bound = body.get("object") or {}
                if not isinstance(bound, dict) or not bound or not ("sha256" in bound or "commit" in bound):
                    continue
                if body.get("taskId") != self.task_id or any(obj.get(k) != v for k, v in bound.items()):
                    continue
                if body.get("portId") != self.request["portId"] or body.get("profileDigest") != profile_digest:
                    continue
                if any(k in self.request and k in body and body[k] != self.request[k] for k in ("round", "attemptId")):
                    continue
                hits.append(fact)
            self._formal = sorted(hits, key=lambda f: f["factId"])
        return self._formal

    # -- Human Gate chain back from the current occurrence ------------------------------------------
    def chain(self):
        """Walk POSITION_ADVANCE records back from the current occurrence.

        Returns (steps, broken): steps are the advances that reached the current occurrence, newest
        first; broken names the first Human Gate advance that consumed no matching human-decision fact.
        """
        if self._chain is not None:
            return self._chain
        advances = [c for c in self.inst["commits"] if c["transitionKind"] == "POSITION_ADVANCE"]
        expected = (self.inst["position"], str(self.inst["positionEntryRevision"]))
        steps, broken = [], None
        for commit in reversed(advances):
            nxt = commit["nextSnapshot"]
            if (nxt["position"], str(nxt["positionEntryRuntimeVersion"])) != expected:
                continue
            prev = commit["previousSnapshot"]
            gate = self.topology.semantic_type(prev["position"]) == "HUMAN_GATE"
            decision = None
            if gate:
                for fact_id in commit.get("triggers", []):
                    fact = self.inst["facts"].get(fact_id) or {}
                    if (fact.get("kind") == HUMAN_DECISION and fact.get("purpose") == rules.GATE_DECISION_PURPOSE
                            and fact.get("node") == prev["position"]
                            and str(fact["occurrence"]["positionEntryRuntimeVersion"]) == str(prev["positionEntryRuntimeVersion"])
                            and (fact.get("payload") or {}).get("edgeId") == commit["selectedEdge"]
                            and fact.get("consumedBy") == commit["commandId"]):
                        decision = fact
                if decision is None and broken is None:
                    broken = commit
            steps.append(dict(commit=commit, gate=gate, decision=decision))
            expected = (prev["position"], str(prev["positionEntryRuntimeVersion"]))
        self._chain = (steps, broken)
        return self._chain


def _worst(findings):
    """findings: list of (result, reason). FAIL outranks NOT_CHECKED; empty means PASS."""
    for wanted in (FAIL, NOT_CHECKED):
        for result, why in findings:
            if result == wanted:
                return result, why, [w for r, w in findings]
    return PASS, None, []


# -- author vendor set ---------------------------------------------------------------------------------
def _execution_authors(ctx, refs):
    pairs, findings = [], []
    records = ctx.state.get("executionReservations", {})
    for ref in refs:
        record = records.get(ref)
        if record is None:
            findings.append((FAIL, reason("AUTHOR_EXECUTION_UNREADABLE", "no execution record for this reference", ref=ref)))
            continue
        observations = record.get("observations") or []
        actual = (observations[-1].get("physical_execution") or {}).get("actualBinding") if observations else None
        agent = ((record.get("intent") or {}).get("executionBinding") or {}).get("agent")
        if record.get("result") is None or not actual or not actual.get("model") or not agent:
            findings.append((NOT_CHECKED, reason("AUTHOR_EXECUTION_UNREADABLE",
                                                 "the execution record has no completed actual binding", ref=ref)))
            continue
        ctx.note("execution-record", ref, sha256=rules.digest(record),
                 programIdentity=copy.deepcopy(((record.get("intent") or {}).get("profile") or {}).get("programIdentity")))
        for model in [actual["model"], *actual.get("observedModels", [])]:
            if (agent, model) not in pairs:
                pairs.append((agent, model))
    return pairs, findings


def _definition_evidence(ctx):
    """feature-t3's fixed author identity for the reviewed Definition (taskDefinition.candidates)."""
    obj = ctx.request["object"]
    candidates = ((ctx.task.get("taskDefinition") or {}).get("candidates")) or []
    hits = [c for c in candidates if c.get("path") == obj["path"] and c.get("bytes") == obj.get("bytes")
            and c.get("sha256") == obj.get("sha256")]
    if not hits:
        return None, (NOT_CHECKED, reason("AUTHOR_EVIDENCE_UNAVAILABLE", "no fixed author identity for this Definition"))
    identities = {rules.digest(c.get("authorIdentity")) for c in hits}
    if len(identities) > 1:
        return None, (NOT_CHECKED, reason("EVIDENCE_AMBIGUOUS", "the Definition resolves to several author identities",
                                          candidates=len(hits)))
    return copy.deepcopy(hits[0].get("authorIdentity")), None


def author_vendors(ctx):
    closed = vendors()
    findings = []
    port = ctx.reviewer_port()
    mapping = ctx.inputs.reviewer_mapping(port["mapping_id"]) if port else None
    reviewer = mapping.get("model_vendor") if mapping else None
    binding_vendor = (ctx.intent.get("executionBinding") or {}).get("modelVendor")
    if reviewer is None or reviewer not in closed:
        findings.append((FAIL, reason("VENDOR_NOT_REGISTERED", "the Reviewer port has no registered model vendor",
                                      portId=ctx.request["portId"])))
    elif binding_vendor != reviewer:
        findings.append((FAIL, reason("BINDING_MISMATCH", "intent modelVendor differs from the Registry mapping",
                                      intent=binding_vendor, registry=reviewer)))
    ctx.derived["reviewerVendor"] = reviewer
    human_only, evidence_refs, pairs = False, [], []
    if ctx.request["object"]["kind"] == "definition":
        found, problem = _definition_evidence(ctx)
        if problem:
            findings.append(problem)
        elif not isinstance(found, dict) or set(found) != {"humanOnly", "agents", "evidenceRefs"} \
                or not isinstance(found["humanOnly"], bool) or not isinstance(found["agents"], list) \
                or not isinstance(found["evidenceRefs"], list):
            findings.append((FAIL, reason("AUTHOR_EVIDENCE_UNAVAILABLE", "fixed author identity has an unexpected shape")))
        else:
            evidence_refs = [r for r in found["evidenceRefs"] if isinstance(r, str) and r]
            if found["humanOnly"]:
                human_only = True
                if found["agents"]:
                    findings.append((FAIL, reason("AUTHOR_DECLARATION_MISMATCH", "a human-only identity lists agents")))
            for agent in found["agents"]:
                if not isinstance(agent, dict) or not agent.get("agent") or not agent.get("model"):
                    findings.append((FAIL, reason("AUTHOR_EVIDENCE_UNAVAILABLE", "an author agent lacks agent or model")))
                    continue
                pairs.append((agent["agent"], agent["model"]))
            if not evidence_refs:
                findings.append((FAIL, reason("HUMAN_EVIDENCE_MISSING", "the fixed author identity cites no evidence")))
            ctx.note("author-evidence", ctx.request["object"]["path"], sha256=rules.digest(found))
    more, problems = _execution_authors(ctx, ctx.request["authorExecutionRefs"])
    findings.extend(problems)
    pairs.extend(p for p in more if p not in pairs)
    evidence_refs.extend("execution:" + ref for ref in ctx.request["authorExecutionRefs"])
    if pairs:
        human_only = False
    table = ctx.state.get("configuration", {}).get("authorVendors") or {}
    derived = []
    for agent, model in pairs:
        vendor = (table.get(agent) or {}).get(model)
        if vendor is None:
            findings.append((FAIL, reason("AUTHOR_VENDOR_UNKNOWN", "no product-side author vendor mapping",
                                          agent=agent, model=model)))
        elif vendor not in closed:
            findings.append((FAIL, reason("VENDOR_NOT_REGISTERED", "mapped vendor is outside the closed set",
                                          agent=agent, model=model, vendor=vendor)))
        elif vendor not in derived:
            derived.append(vendor)
    ctx.note("author-vendor-configuration", "configuration.authorVendors", sha256=rules.digest(table))
    if not derived and not human_only and not any(r == FAIL for r, _ in findings):
        findings.append((FAIL, reason("AUTHOR_SET_EMPTY", "the author vendor set is empty and not human-only")))
    declared = ctx.request.get("declaredAuthors")
    if declared is not None:
        for value in declared["vendors"]:
            if value == "":
                findings.append((FAIL, reason("VENDOR_NOT_REGISTERED", "declared vendor is an empty string", value=value)))
            elif value == "unknown":
                findings.append((FAIL, reason("AUTHOR_VENDOR_UNKNOWN", "declared vendor is unknown", value=value)))
            elif value not in closed:
                findings.append((FAIL, reason("VENDOR_NOT_REGISTERED", "declared vendor outside the closed set "
                                              "(comparison is case-sensitive)", value=value)))
        if sorted(set(declared["vendors"])) != sorted(derived) or declared["humanOnly"] != human_only:
            findings.append((FAIL, reason("AUTHOR_DECLARATION_MISMATCH", "declared authors differ from the derived set",
                                          declared=declared, derived=sorted(derived), humanOnly=human_only)))
    if reviewer is not None and reviewer in derived:
        findings.append((FAIL, reason("VENDOR_OVERLAP", "the Reviewer vendor is in the author vendor set",
                                      reviewer=reviewer, authors=sorted(derived))))
    ctx.derived.update(authorVendors=sorted(derived), authorEvidenceRefs=evidence_refs, humanOnly=human_only)
    return _worst(findings)[:2]


# -- Reviewer eligibility ----------------------------------------------------------------------------
def _formal_required(ctx, port):
    """Admission matrix (review-channel §6.11): only REVIEW_ENABLED within its binding admits without formal."""
    status = (port.get("capability") or {}).get("status")
    bound = (ctx.intent.get("executionBinding") or {}).get("model") == port.get("model_ref") \
        and ctx.intent.get("transport") == port.get("transport") and ctx.intent.get("effort") == port.get("effort")
    effective = "UNVERIFIED" if status in ("PROBED", "REVIEW_ENABLED") and not bound else status
    return status, effective, effective != "REVIEW_ENABLED"


def reviewer_eligibility(ctx):
    port = ctx.reviewer_port()
    if port is None:
        return FAIL, reason("PROFILE_NOT_REGISTERED", "no Registry execution port with this id", portId=ctx.request["portId"])
    if port.get("mode") != ctx.request["entry"]:
        return FAIL, reason("ENTRY_MISMATCH", "embedded and standalone qualifications are not interchangeable",
                            portMode=port.get("mode"), entry=ctx.request["entry"])
    if ctx.intent.get("portId") != ctx.request["portId"]:
        return FAIL, reason("BINDING_MISMATCH", "intent portId differs from the evaluated port")
    status, effective, formal = _formal_required(ctx, port)
    if status not in CAPABILITY_STATES or status == "REGISTERED":
        return FAIL, reason("CAPABILITY_NOT_CONFIGURED", "the port capability does not admit any attempt", status=status)
    if not formal:
        return PASS, None
    facts = ctx.formal_fact()
    if not facts:
        return FAIL, reason("FORMAL_AUTHORIZATION_REQUIRED", "capability below REVIEW_ENABLED needs an Owner formal "
                            "authorization fact", status=status, effective=effective)
    ctx.derived["ownerFormal"] = True
    for fact in facts:
        if fact["factId"] not in ctx.authorization_refs:
            ctx.authorization_refs.append(fact["factId"])
    return PASS, None


# -- input evidence ------------------------------------------------------------------------------------
def input_evidence(ctx):
    findings = []
    request = ctx.request
    if ctx.subject == rules.REVIEW_RELEASE:
        obj = request["object"]
        if obj["kind"] == "definition":
            raw = ctx.inputs.blob(obj["commit"], obj["path"])
            if raw is None:
                findings.append((FAIL, reason("EVIDENCE_MISSING", "reviewed Definition bytes are not at that commit",
                                              path=obj["path"], commit=obj["commit"])))
            elif identity(raw) != dict(bytes=obj["bytes"], sha256=obj["sha256"]):
                findings.append((FAIL, reason("EVIDENCE_DIGEST_MISMATCH", "reviewed Definition identity differs",
                                              expected=dict(bytes=obj["bytes"], sha256=obj["sha256"]), actual=identity(raw))))
            else:
                ctx.note("reviewed-object", obj["commit"] + ":" + obj["path"], **identity(raw))
            _, problem = _definition_evidence(ctx)
            if problem and problem[1]["code"] == "EVIDENCE_AMBIGUOUS":
                findings.append(problem)
        elif not ctx.inputs.commit_exists(obj["commit"]):
            findings.append((FAIL, reason("EVIDENCE_MISSING", "candidate change commit does not exist", commit=obj["commit"])))
        else:
            ctx.note("reviewed-object", obj["commit"])
        records = ctx.state.get("executionReservations", {})
        for ref in request["authorExecutionRefs"]:
            if ref not in records:
                findings.append((FAIL, reason("EVIDENCE_MISSING", "author execution record is missing", ref=ref)))
    elif ctx.subject == rules.IMPLEMENT_RELEASE:
        definition, final = request["definition"], request["finalization"]
        raw = ctx.inputs.blob(definition["commit"], definition["path"])
        pinned = None
        if raw is None:
            findings.append((FAIL, reason("EVIDENCE_MISSING", "finalized Definition bytes are not at that commit")))
        elif identity(raw) != dict(bytes=definition["bytes"], sha256=definition["sha256"]):
            findings.append((FAIL, reason("EVIDENCE_DIGEST_MISMATCH", "finalized Definition identity differs")))
        else:
            ctx.note("definition", definition["commit"] + ":" + definition["path"], **identity(raw))
            pinned = "> Object: %s · %d bytes · SHA-256 %s" % (definition["path"], len(raw), identity(raw)["sha256"])
        ruling = ctx.inputs.blob(final["commit"], final["path"])
        if ruling is None:
            findings.append((FAIL, reason("EVIDENCE_MISSING", "finalization ruling is not at that commit")))
        else:
            head = ruling.decode("utf-8", "replace").splitlines()[:6]
            if len(head) < 4 or head[2] != "> Type: finalization":
                findings.append((FAIL, reason("EVIDENCE_MISSING", "the ruling is not a finalization ruling")))
            elif pinned is not None and head[3] != pinned:
                findings.append((FAIL, reason("EVIDENCE_DIGEST_MISMATCH", "the finalization does not pin this Definition")))
            else:
                ctx.note("finalization", final["commit"] + ":" + final["path"], **identity(ruling))
    else:
        commit = request["push"]["candidateCommit"]
        if not ctx.inputs.commit_exists(commit):
            findings.append((FAIL, reason("EVIDENCE_MISSING", "candidate commit does not exist", commit=commit)))
        else:
            ctx.note("candidate-commit", commit)
    return _worst(findings)[:2]


# -- profile purpose and entry -----------------------------------------------------------------------
def profile_purpose_entry(ctx):
    registration = ctx.registration()
    if registration is None:
        if ctx.subject == rules.IMPLEMENT_RELEASE:
            return NOT_CHECKED, reason("PORT_REGISTRATION_UNAVAILABLE", "no product-side Implementer registration "
                                       "is readable (feature-t4)", portId=ctx.request["portId"])
        return FAIL, reason("PROFILE_NOT_REGISTERED", "no Registry execution port with this id", portId=ctx.request["portId"])
    purpose, operation = rules.PURPOSE[ctx.subject]
    registered = registration.get("profile") or {}
    offered = ctx.intent.get("profile") or {}
    ctx.trust_boundary = dict(source="profile-declaration", profileId=registered.get("id"),
                              profileDigest=registered.get("digest"), trustModel=registered.get("trustModel"),
                              limitations=copy.deepcopy(registered.get("limitations")))
    findings = []
    if registered.get("purpose") != purpose or offered.get("purpose") != purpose \
            or operation not in (registered.get("operations") or []):
        findings.append((FAIL, reason("PURPOSE_MISMATCH", "profile purpose or operations do not fit this subject",
                                      required=dict(purpose=purpose, operation=operation),
                                      registered=registered.get("purpose"), offered=offered.get("purpose"))))
    if registration.get("mode") != ctx.request["entry"]:
        findings.append((FAIL, reason("PORT_MODE_MISMATCH", "port mode differs from the entry",
                                      portMode=registration.get("mode"), entry=ctx.request["entry"])))
    # Version independence (OD-399): programIdentity is never compared, only the digest, purpose and operations.
    if not registered.get("digest") or offered.get("digest") != registered.get("digest"):
        findings.append((FAIL, reason("PROFILE_NOT_REGISTERED", "offered profile digest is not the registered one",
                                      offered=offered.get("digest"), registered=registered.get("digest"))))
    elif (ctx.intent.get("executionBinding") or {}).get("profileDigest") != registered.get("digest"):
        findings.append((FAIL, reason("BINDING_MISMATCH", "executionBinding.profileDigest differs from the profile")))
    return _worst(findings)[:2]


# -- Human authority -----------------------------------------------------------------------------------
def human_authority(ctx):
    if ctx.subject == rules.REVIEW_RELEASE:
        port = ctx.reviewer_port()
        if port is None:
            return FAIL, reason("PROFILE_NOT_REGISTERED", "no Registry execution port with this id")
        _, _, formal = _formal_required(ctx, port)
        if not formal:
            return PASS, None
        facts = ctx.formal_fact()
        if not facts:
            return FAIL, reason("FORMAL_AUTHORIZATION_REQUIRED", "no Owner formal authorization fact for this review")
        ctx.derived["ownerFormal"] = True
        for fact in facts:
            if fact["factId"] not in ctx.authorization_refs:
                ctx.authorization_refs.append(fact["factId"])
        return PASS, None
    position = ctx.inst["position"]
    if ctx.subject == rules.PUSH_PERMIT and position != rules.PUSH_POSITION:
        return FAIL, reason("AUTHORITY_STALE", "a push is permitted only at the Publish position", position=position)
    if ctx.subject == rules.IMPLEMENT_RELEASE and position not in rules.IMPLEMENT_POSITIONS:
        return FAIL, reason("AUTHORITY_STALE", "the current position is not an implementation position", position=position)
    steps, broken = ctx.chain()
    for step in steps:
        if not step["gate"]:
            continue
        edge = step["commit"]["selectedEdge"]
        if step["decision"] is None:
            return FAIL, reason("AUTHORITY_MISSING", "a Human Gate was passed without a consumed human-decision fact",
                                edgeId=edge, commandId=step["commit"]["commandId"])
        if ctx.subject == rules.PUSH_PERMIT:
            if edge not in rules.PUSH_DECISION_EDGES:
                return FAIL, reason("AUTHORITY_MISSING", "the latest Human Gate decision is not a Publish authorization",
                                    edgeId=edge)
            ctx.publish_decision = step["decision"]
            ctx.authorization_refs.append(step["decision"]["factId"])
            return PASS, None
        if edge in rules.IMPLEMENT_DECISION_EDGES:
            ctx.authorization_refs.append(step["decision"]["factId"])
            return PASS, None
        if edge not in rules.IMPLEMENT_CONTINUE_EDGES:
            return FAIL, reason("AUTHORITY_MISSING", "a Human Gate decision on the path is not a continuation", edgeId=edge)
        ctx.authorization_refs.append(step["decision"]["factId"])
    return FAIL, reason("AUTHORITY_MISSING", "no required Human decision on the path to the current occurrence",
                        position=position, occurrence=occurrence(ctx.inst, ctx.task_id))


# -- exact push permit ---------------------------------------------------------------------------------
def push_permit(ctx):
    decision = ctx.publish_decision
    if decision is None:
        return FAIL, reason("PUSH_AUTHORIZATION_MISSING", "no Publish authorization decision reaches this position")
    binding = (decision.get("payload") or {}).get("publishBinding")
    if not isinstance(binding, dict):
        return FAIL, reason("PUSH_AUTHORIZATION_MISSING", "the Publish authorization binds no candidate and target",
                            factId=decision["factId"])
    push = ctx.request["push"]
    differ = [k for k in ("candidateCommit", "sourceBranch", "remote", "targetBranch") if binding.get(k) != push[k]]
    if differ:
        return FAIL, reason("PUSH_BINDING_MISMATCH", "the push differs from the authorized binding", fields=differ)
    if push["sourceBranch"] != ctx.task.get("branch") or push["repositoryIdentity"] != ctx.task.get("repositoryIdentity"):
        return FAIL, reason("TASK_BRANCH_MISMATCH", "the push source is not the Task Branch bound at acceptance",
                            bound=dict(branch=ctx.task.get("branch"), repositoryIdentity=ctx.task.get("repositoryIdentity")))
    return PASS, None


# -- budget --------------------------------------------------------------------------------------------
def budget(ctx):
    findings = []
    offered = ctx.intent.get("budget")
    if not isinstance(offered, dict):
        return FAIL, reason("BUDGET_MISSING", "the intent carries no budget")
    extra = sorted(set(offered) - set(rules.BUDGET_FIELDS))
    if extra:
        findings.append((FAIL, reason("BUDGET_FIELD_NOT_ALLOWED", "budget fields outside the closed set (no US-dollar cap)",
                                      fields=extra)))
    missing = [k for k in rules.BUDGET_FIELDS if not (type(offered.get(k)) is int and offered[k] > 0)]
    if missing:
        findings.append((FAIL, reason("BUDGET_MISSING", "budget fields missing or not positive integers", fields=missing)))
    calls = ctx.request["maxCalls"]
    if not (type(calls) is int and 0 < calls <= rules.MAX_CALLS[ctx.subject]):
        findings.append((FAIL, reason("BUDGET_EXCEEDS_LIMIT", "maxCalls outside the rule table",
                                      maxCalls=calls, limit=rules.MAX_CALLS[ctx.subject])))
    registration = ctx.registration()
    if registration is None:
        code = "PORT_REGISTRATION_UNAVAILABLE" if ctx.subject == rules.IMPLEMENT_RELEASE else "PROFILE_NOT_REGISTERED"
        findings.append((NOT_CHECKED if ctx.subject == rules.IMPLEMENT_RELEASE else FAIL,
                         reason(code, "no registration to take the profile limits from")))
    elif not missing:
        profile = registration.get("profile") or {}
        limits = dict(maxToolCalls=profile.get("maxToolCalls"), maxRunSeconds=profile.get("maxRunSeconds"),
                      maxOutputBytes=rules.MAX_OUTPUT_BYTES)
        over = [k for k, limit in limits.items() if not (type(limit) is int and offered[k] <= limit)]
        if over:
            findings.append((FAIL, reason("BUDGET_EXCEEDS_LIMIT", "budget exceeds the profile or port limits",
                                          fields=over, limits=limits)))
    if ctx.subject == rules.REVIEW_RELEASE:
        review = ctx.request["review"]
        try:
            rounds = ctx.inputs.rounds(ctx.task_id, review["stage"], review)
        except InputsUnavailable as exc:
            findings.append((NOT_CHECKED, reason("ROUND_FACTS_UNREADABLE", str(exc))))
        else:
            ctx.note("review-rounds", "tasks/%s/reviews" % ctx.task_id, **{k: rounds[k] for k in ("submitted", "allowed")})
            if rounds["exhausted"]:
                findings.append((FAIL, reason("ROUND_BUDGET_EXHAUSTED", "delivered review rounds reached the allowed rounds",
                                              submitted=rounds["submitted"], allowed=rounds["allowed"])))
    return _worst(findings)[:2]


FUNCTIONS = {
    rules.AUTHOR_VENDORS: author_vendors,
    rules.REVIEWER_ELIGIBILITY: reviewer_eligibility,
    rules.INPUT_EVIDENCE: input_evidence,
    rules.PROFILE_PURPOSE_ENTRY: profile_purpose_entry,
    rules.HUMAN_AUTHORITY: human_authority,
    rules.PUSH_PERMIT_ITEM: push_permit,
    rules.BUDGET: budget,
}


# -- feature-t5: judgement items of the autonomous budget subjects ----------------------------------
def budget_input_evidence(ctx):
    """The current budget occurrence was entered through the loop's FAIL edge after a business FAIL."""
    from domain.budget import ledger
    try:
        found = ledger.arrival(ctx.state, ctx.task_id, ctx.subject)
    except ledger.BudgetBroken as exc:
        return FAIL, reason(exc.code, str(exc), **exc.detail)
    ctx.note("business-fail", found.get("ref") or found["commit"], kind=found["kind"], commit=found["commit"])
    return PASS, None


def autonomous_budget(ctx):
    """Window, grant and consumption from the recorded commits and configuration history; derives `outcome`."""
    from domain.budget import configuration, ledger
    try:
        derived = ledger.derive(ctx.state, ctx.task_id, ctx.subject)
    except ledger.BudgetUnavailable as exc:
        return NOT_CHECKED, reason(exc.code, str(exc), **exc.detail)
    except ledger.BudgetBroken as exc:
        return FAIL, reason(exc.code, str(exc), **exc.detail)
    rows = dict(configuration.history(ctx.state))
    row = rows[derived["grant"]["historyIndex"]]
    ctx.note("autonomous-budget-configuration", "configuration.history[%d]" % derived["grant"]["historyIndex"],
             revision=row.get("revision"), sha256=rules.digest(row.get("value")))
    if derived["window"]["continueDecisionFact"]:
        ctx.authorization_refs.append(derived["window"]["continueDecisionFact"])
    ctx.derived["budget"] = derived
    return PASS, None


BUDGET_FUNCTIONS = {rules.INPUT_EVIDENCE: budget_input_evidence, rules.AUTONOMOUS_BUDGET: autonomous_budget}
