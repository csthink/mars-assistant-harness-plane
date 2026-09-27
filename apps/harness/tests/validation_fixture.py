"""Test-only fixtures for feature-t5: synthetic product lines, a SYNTHETIC impl-round reviewer and helpers.

ValidationFixture extends feature-t4's Fixture: the synthetic product line additionally carries the hp live
review-channel Registry as a product-line Registry (provider capabilities CONFIGURED, a standalone copy of
the embedded review port), a `.gitignore` for the task attempts area, the change-validation switch set
before acceptance when a case needs it, and an explicit autonomous-budget configuration. The Definition,
Implement and Verify paths, the execution layer, the port factory and the feature-t6 Policy Gate callback
are production code. SyntheticImplReviewer stands in for the reviewer's output only; it is never available
to product code. No real model, Host, Agent or remote operation.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance.accept import accept_task, set_configuration
from domain.budget import configuration
from domain.core import HarnessDomain
from domain.definition import dispatch as definition_dispatch
from domain.implement_verify import executors as implement_executors
from domain.validation import records, review as validation_review
from domain.workflow import states
from execution.port import ExecutionError
from product_line import create_product_line, git, write
from runtime.executions import Environment, build_port, run_pending
import definition_fixture as DF
import implement_verify_fixture as IF

OWNER = IF.OWNER
IMPL_QUESTIONS = validation_review.QUESTIONS


def check(check_id="unit", prefix="good"):
    """A deterministic synthetic check: PASS when feature.txt starts with the prefix (remediations change the suffix)."""
    code = ("import pathlib,sys; p=pathlib.Path('feature.txt'); "
            "sys.exit(0 if p.exists() and p.read_text().startswith(%r) else 1)" % prefix)
    return dict(id=check_id, argv=[sys.executable, "-c", code], timeoutSeconds=30)


class ValidationFixture(IF.Fixture):
    """feature-t4's Fixture plus the Registry, the attempts ignore rule, the change-validation switch and a budget."""

    def __init__(self, root, *, change_validation=False, budget=None, task_id="feature-t0", declared=None, agent=None):
        self.root = Path(root)
        self.task_id = task_id
        self.repo, self.head = create_product_line(self.root / "repo")
        git(self.repo, "config", "user.name", "Synthetic")
        git(self.repo, "config", "user.email", "synthetic@invalid")
        write(self.repo, DF.VALIDATOR, (DF.HP / DF.VALIDATOR).read_bytes())
        write(self.repo, DF.EVIDENCE, "Synthetic author evidence: human declaration fixture.\n")
        write(self.repo, DF.REGISTRY, json.dumps(DF.live_registry_copy(standalone=True), indent=1) + "\n")
        write(self.repo, ".gitignore", "tasks/*/attempts/\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "synthetic validator, registry, author evidence and ignore rule")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.domain = HarnessDomain(self.repo, entry="cli")
        self.generation = self.domain.bind_entry()
        if change_validation:
            set_configuration(self.domain.store, "change-validation", True, OWNER)
        outcome = accept_task(self.domain.store, dict(requestId="req-1", repository=str(self.repo), taskType="feature",
                                                      taskId=task_id, baseRef="main",
                                                      worktreeRoot=str(self.root / "worktrees"), authorityRef=OWNER))
        assert outcome["result"] == "ACCEPTED", outcome
        self.task = self.domain.read()["tasks"][task_id]
        self.worktree = Path(self.task["worktree"])
        self.agent = agent or IF.SyntheticAgent(self.root / "agent")
        self.definition_path = "tasks/%s/%s.md" % (task_id, task_id)
        self.definition_commit = DF.commit_candidate(self.worktree, IF.definition_text(task_id), task_id=task_id)
        self.freeze()
        self.set_registration([IF.entry(agent_path=self.agent.path)])
        self.set_checks(declared if declared is not None else [check()])
        for model, vendor in IF.VENDORS.items():
            self.set_vendor(model, vendor)
        if budget is not None:
            self.set_budget(budget)

    # -- configuration -----------------------------------------------------------------------------
    def set_budget(self, value, authority=OWNER):
        return self.domain.transaction(self.generation, lambda s: configuration.set_budget(s, value, authority))

    # -- the feature-t4 lane -----------------------------------------------------------------------
    def run_implement(self, execution_id):
        env = Environment("cli", self.domain, self.generation, repository_root=str(self.repo))
        return run_pending(self.domain, env, {"coding-implementer": implement_executors.ImplementExecutor(build_port)})

    def implement(self, content=None, command_id=None):
        command_id = command_id or "d%d" % (len(self.executions()) + 1)
        content = content or "good-%d" % (len(self.executions()) + 1)
        self.agent.set(mode="commit", content=content)
        out = self.dispatch(command_id=command_id)
        failures = self.run_implement(out["execution"]["executionRequestId"])
        assert not failures, failures
        return out

    def verify(self, command_id=None):
        command_id = command_id or "v%d" % (len(self.verifications()) + 1)
        return implement_executors.run_verify(self.domain, self.generation, self.task_id,
                                              dict(commandId=command_id, authorityRef=OWNER))

    def executions(self):
        return (self.state()["tasks"][self.task_id].get("implementVerify") or {}).get("executions", {})

    def verifications(self):
        return (self.state()["tasks"][self.task_id].get("implementVerify") or {}).get("verifications", {})

    def to_validate(self, content=None):
        """Implement and Verify PASS: the task reaches Validate Change · Enabled?."""
        self.implement(content)
        verified = self.verify()
        assert verified["result"] == "VERIFY_PASS", verified
        assert self.inst()["position"] == "N-VALIDATE-CONFIG", self.inst()["position"]
        return verified

    # -- feature-t5 entries ------------------------------------------------------------------------
    def budget_decide(self, command_id):
        return self.run("budget-decide", commandId=command_id)

    def validate(self, name, command_id, **payload):
        return self.run("validate-" + name, commandId=command_id, **payload)

    def run_reviews(self, reviewer, authorizer=None):
        env = Environment("cli", self.domain, self.generation, repository_root=str(self.repo))
        return run_pending(self.domain, env, executors(reviewer, authorizer))

    def restart(self, node="N-VALIDATE-REVIEWER"):
        """Human-authorised RESTART_CURRENT_NODE after a failed review attempt (feature-t2 recovery, D-05)."""
        assessment_id = "as-%d" % len(self.inst()["commits"])
        self.run("recover-assess", assessmentId=assessment_id, assessment="RESTART_SAFE",
                 evidence=dict(note="synthetic: the review attempt failed; nothing external to keep"))
        occurrence = dict(workflowInstance=self.task_id, node=node, positionEntryRuntimeVersion=self.inst()["positionEntryRevision"])
        self.run("recover", commandId="rs-" + assessment_id, action="RESTART_CURRENT_NODE", assessmentId=assessment_id,
                 humanAuthorization=dict(workflowInstance=self.task_id, occurrence=occurrence,
                                         expectedRuntimeVersion=self.inst()["runtimeVersion"], assessmentId=assessment_id,
                                         action="RESTART_CURRENT_NODE", effectScope="re-dispatch the change review",
                                         authorizationRef="human:synthetic:restart:" + assessment_id))

    def rounds(self):
        return records.view_of(self.state(), self.task_id)["rounds"]

    def edges(self):
        return [c["selectedEdge"] for c in self.inst()["commits"] if c["transitionKind"] == states.POSITION_ADVANCE]

    def budget_facts(self):
        return [f for f in self.inst()["facts"].values() if f["kind"] == "policy-decision" and f["purpose"].endswith("-budget")]

    def review_once(self, reviewer, command_id, formal=True):
        """configure (when at the config node), formal authorization (CONFIGURED port), dispatch and run."""
        if self.inst()["position"] == "N-VALIDATE-CONFIG":
            self.validate("configure", command_id + "-cfg")
        if formal:
            self.validate("formal-authorize", command_id + "-f", maxCalls=1)
        out = self.validate("dispatch", command_id)
        failures = self.run_reviews(reviewer)
        assert not failures, failures
        return out


# -- SYNTHETIC impl-round reviewer output --------------------------------------------------------------
def verdict_block(round_record, verdict="PASS", *, human=False, non_blocking=False, questions=IMPL_QUESTIONS,
                  stage="impl", candidate_sha=None, schema="review-channel-verdict/v4", round_label=None):
    label = round_label or round_record["round"]
    findings = []
    assessments = [dict(question_id=q, assessment="SATISFIED", evidence_refs=["candidate-change.md#Verify"], finding_ids=[])
                   for q in questions]
    if verdict == "FAIL":
        findings.append(dict(id=label.upper() + "-B1", severity="blocking", title="synthetic goal condition not met",
                             location=dict(file="candidate-change.md", anchor="Unified diff"), origin="changed_region",
                             summary="synthetic"))
        assessments[0].update(assessment="NOT_SATISFIED", finding_ids=[findings[-1]["id"]])
    if non_blocking:
        findings.append(dict(id=label.upper() + "-N1", severity="non_blocking", title="synthetic recommendation",
                             location=dict(file="candidate-change.md", anchor="Verify"), origin="changed_region",
                             summary="synthetic"))
        assessments[1]["finding_ids"] = [findings[-1]["id"]]
    if human:
        findings.append(dict(id=label.upper() + "-H1", severity="human", title="synthetic human question",
                             location=dict(file="candidate-change.md", anchor="Verify"), origin="changed_region",
                             summary="synthetic"))
        assessments[2].update(assessment="INDETERMINATE", finding_ids=[findings[-1]["id"]])
    bundle = dict(bundle_name="candidate-change.md", sha256=candidate_sha or round_record["document"]["sha256"])
    return dict(verdict_schema=schema, verdict=verdict, human_decision_required=human, subject="feature-t0-task", stage=stage,
                round=label, candidate=bundle, candidates=[bundle], question_assessments=assessments, findings=findings,
                previous_findings_disposition=[], accepted_residuals_acknowledged=[],
                scope_files_read=["candidate-change.md", "definition.md"], tools_used=["read"], authorization_disclaimer=True)


def valid_outcome(round_record, block):
    raw = ("```review-channel-verdict\n" + json.dumps(block, ensure_ascii=False) + "\n```\n\n**Verdict: %s**\n" % block["verdict"]).encode()
    digest = hashlib.sha256(raw).hexdigest()
    receipt = dict(classification="completed_with_valid_verdict", verdict_validation="VALID", verdict_published=True,
                   verdict_sha256=digest, failure_code=None, reviewer=dict(tool="codex", model="gpt-6-sol", vendor="OpenAI"),
                   cross_vendor="PASS")
    ref = dict(kind="synthetic", path="synthetic/impl-receipt-%s.json" % round_record["round"], sha256="d" * 64)
    return dict(classification="completed_with_valid_verdict", receipt=receipt, verdict=block, verdictSha256=digest,
                evidenceRef=dict(kind="synthetic", path="synthetic/impl-verdict-%s.md" % round_record["round"], sha256=digest),
                receiptRef=ref, published=dict(verdict_path="synthetic/impl-verdict.md", receipt_path=ref["path"]))


class SyntheticImplReviewer:
    """SYNTHETIC reviewer: scripted outcomes after the real port preflight (standalone) or the real callback (Runtime)."""

    def __init__(self, *scripts, mode="preflight"):
        self.scripts = list(scripts)
        self.mode = mode
        self.calls = 0
        self.requests = []
        self.intents = []
        self.query_answer = None

    async def __call__(self, descriptor, env, port, binding, registration, mapping, *, built, round_record):
        state = env.domain.read()
        request = validation_review.request_document(state, descriptor, round_record,
                                                     "tasks/%s/attempts/validation/%s/candidate-change.md"
                                                     % (descriptor["taskId"], round_record["round"]),
                                                     [r["name"] for r in built["references"]])
        self.requests.append(request)
        intent = validation_review.intent_document(descriptor, env, registration, mapping, binding, request)
        self.intents.append(intent)
        try:
            if self.mode == "preflight":
                port.bind_result_scanner(self, lambda: [])
                await port.preflight(intent)
            else:
                await port.authority(intent)
        except ExecutionError as exc:
            return dict(classification="preflight_failed", failureCode=exc.code)
        self.calls += 1
        script = self.scripts.pop(0) if self.scripts else ("valid", "PASS")
        if callable(script):
            return script(round_record)
        kind = script[0]
        if kind == "valid":
            return valid_outcome(round_record, verdict_block(round_record, script[1], **(script[2] if len(script) > 2 else {})))
        if kind == "stopping":
            return dict(classification="unknown", failureCode="synthetic-stop", physicalExecution=copy.deepcopy(script[1]))
        return DF.failed_outcome(*script[1:])

    async def query(self, descriptor, env):
        return self.query_answer or dict(classification="unknown", failureCode="synthetic-query-unknown")


def executors(reviewer, authorizer=None):
    """Production executors with the SYNTHETIC reviewer output only (real port factory; real Policy callback unless a
    test passes an explicitly synthetic authorizer to exercise a refusal the real callback cannot reach offline)."""
    import functools
    factory = build_port if authorizer is None else functools.partial(build_port, authorizer=authorizer)
    return {"change-review": validation_review.ChangeReviewExecutor(reviewer, factory),
            "validation-ruling-write": definition_dispatch.ruling_executor}
