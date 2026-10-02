"""feature-t5 Validate Change loop on synthetic product lines. Docstrings carry the AC tags.

The switch decision, dispatch, materials, execution layer, port factory, feature-t17 port preflight, the
feature-t6 Policy Gate callback, verdict settlement, rulings and routing are production code. The impl-round
reviewer output is explicitly SYNTHETIC (validation_fixture.SyntheticImplReviewer); one refusal case uses an
explicitly synthetic NOT_DETERMINABLE callback. No real model, no remote operation, no write outside temp dirs.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import definition_fixture as DF
import validation_fixture as VF
from domain.budget import ledger
from domain.core import HarnessDomain
from domain.definition.results import DefinitionRejection
from domain.policy import rules
from domain.validation import records, results as V
from domain.validation.results import ValidationRejection
from domain.workflow import results as W, states
from domain.workflow.results import WorkflowRejection
from product_line import git, write
import instance_area

OWNER = VF.OWNER
HP = Path(__file__).resolve().parents[3]
J06 = "records/diagnostics/feature-t4/2026-09-23/inputs/assistant/docs/design/evidence/host-execution-facts-j06"
FAILURES = (("cancelled_by_host", "host-cancel"), ("execution_port_failure", "port-fault"),
            ("provider_unavailable", "provider-down"), ("authentication_failed", "auth"),
            ("timeout_or_transport_failure", "timeout"), ("reviewer_output_invalid", "reemit-unparseable"),
            ("preflight_failed", "round_budget_exhausted"), ("interrupted", "interrupted"))


def budget(definition=1, verification=1, validation=1):
    return dict(definitionReview=definition, verification=verification, validationReview=validation)


class ValidationCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("t5v-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t5-validate-")
            self.directory = Path(self.temp.name)

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def fixture(self, name="fx", **kw):
        kw.setdefault("change_validation", True)
        kw.setdefault("budget", budget())
        fx = VF.ValidationFixture(self.directory / name, **kw)
        fx.to_validate()
        return fx

    def rejects(self, code, function, *args, **kw):
        with self.assertRaises((ValidationRejection, WorkflowRejection, DefinitionRejection)) as ctx:
            function(*args, **kw)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception

    def review_facts(self, fx, conclusion=None):
        return [f for f in fx.inst()["facts"].values() if f["kind"] == "policy-decision" and f["purpose"] == "review-release"
                and (conclusion is None or f["payload"]["conclusion"] == conclusion)]

    def failed(self, fx, classification):
        rnd = fx.rounds()[-1]
        self.assertEqual(rnd["status"], "execution-failed", rnd.get("failure"))
        self.assertEqual(rnd["failure"]["classification"], classification)
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-VALIDATE-REVIEWER", states.RECOVERY_REQUIRED))
        self.assertNotIn("E-V05", fx.edges())
        self.assertFalse(fx.budget_facts())
        attempt = [a for a in fx.inst()["attempts"] if a["attemptId"] == rnd["attemptId"]][0]
        self.assertEqual(attempt["status"], states.EXECUTION_FAILED)


class ValidateChangeLoop(ValidationCase):
    # -- AC-05 ------------------------------------------------------------------------------------------
    def test_switch_disabled_by_default_and_enabled_by_configuration(self):
        """AC-05: the default-off switch is recorded and takes Disabled to the Publish Authorization Gate; configured on takes Enabled."""
        off = self.fixture("off", change_validation=False)
        out = off.validate("configure", "c1")
        self.assertEqual((out["configuration"]["changeValidation"], out["configuration"]["source"], out["configuration"]["edge"]),
                         (False, "default", "E-V02"))
        self.assertEqual((off.inst()["position"], off.inst()["condition"]), ("N-PUBLISH-AUTH-GATE", states.AWAITING_HUMAN_ACTION))
        self.assertFalse([a for a in off.inst()["attempts"] if a["node"] == "N-VALIDATE-REVIEWER"])
        fact = off.inst()["facts"][out["configuration"]["factId"]]
        self.assertEqual((fact["kind"], fact["purpose"]), ("configuration-decision", "change-validation-config"))
        self.assertEqual(fact["consumedBy"], "c1:E-V02")
        self.assertEqual(records.publish_context(off.state(), off.task_id)["switch"][0]["changeValidation"], False)
        on = self.fixture("on")
        out = on.validate("configure", "c1")
        self.assertEqual((out["configuration"]["changeValidation"], out["configuration"]["source"], out["configuration"]["edge"]),
                         (True, "configuration", "E-V01"))
        self.assertEqual(on.inst()["position"], "N-VALIDATE-REVIEWER")
        self.assertEqual(on.validate("configure", "c1")["result"], V.IDEMPOTENT_REPLAY)

    # -- AC-06 ------------------------------------------------------------------------------------------
    def test_dispatch_binds_materials_and_the_real_callback_needs_the_formal_fact(self):
        """AC-06: materials match the candidate, Definition and anchor; without the Owner formal fact the real callback denies; with it, allows."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        out = fx.validate("dispatch", "p1")
        rnd = out["round"]
        head = git(fx.worktree, "rev-parse", "HEAD")
        self.assertEqual(rnd["candidateCommit"], head)
        roles = {r["role"]: r for r in rnd["references"]}
        self.assertEqual(set(roles), {"definition", "proposal", "spec", "milestones"})
        final = fx.frozen
        self.assertEqual((roles["definition"]["sourceCommit"], roles["definition"]["sha256"]), (final["commit"], final["sha256"]))
        reviewer = VF.SyntheticImplReviewer(("valid", "PASS"))
        self.assertFalse(fx.run_reviews(reviewer))
        self.assertEqual(reviewer.calls, 0)
        self.failed(fx, "preflight_failed")
        denied = self.review_facts(fx, "DENY")[-1]["payload"]
        codes = {i["item"]: (i["result"], (i.get("reason") or {}).get("code")) for i in denied["items"]}
        self.assertEqual(codes["reviewer-eligibility"], ("FAIL", "FORMAL_AUTHORIZATION_REQUIRED"))
        self.assertEqual(codes["author-vendors"][0], "PASS")
        fx.restart()
        formal = fx.validate("formal-authorize", "f1", maxCalls=1)
        self.assertEqual(formal["formal"]["round"], 1)
        again = fx.validate("dispatch", "p2")
        self.assertEqual((again["round"]["round"], again["round"]["attempt"]), ("r1", 2))
        reviewer = VF.SyntheticImplReviewer(("valid", "PASS"))
        self.assertFalse(fx.run_reviews(reviewer))
        self.assertEqual(reviewer.calls, 1)
        allowed = self.review_facts(fx, "ALLOW")[-1]["payload"]
        self.assertIn(formal["formal"]["factId"], allowed["authorizationRefs"])
        self.assertEqual(allowed["derived"]["authorVendors"], ["Anthropic"])
        self.assertTrue(allowed["derived"]["ownerFormal"])
        intent = reviewer.intents[-1]
        self.assertEqual(set(intent["budget"]), {"maxToolCalls", "maxRunSeconds", "maxOutputBytes", "cleanupSeconds"})
        self.assertFalse([k for k in json.dumps(intent).split('"') if "cost" in k.lower() or "usd" in k.lower() or "dollar" in k.lower()])
        request = reviewer.requests[-1]
        self.assertEqual((request["stage"], request["task_record"], request["round"]), ("impl", fx.task_id, "r1"))
        self.assertEqual(request["artifact_author"]["authors"], [dict(tool="claude-code", model="claude-synthetic", vendor="Anthropic")])
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH-AUTH-GATE", states.AWAITING_HUMAN_ACTION))

    def test_dispatch_refusals_make_no_provider_call_and_no_fail(self):
        """AC-06: unregistered port, entry mismatch, wrong purpose, material mismatch and a not-determinable callback are refused distinctly."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        before = fx.inst()["runtimeVersion"]
        self.rejects("PORT_NOT_REGISTERED", fx.validate, "dispatch", "x1", portId="nope")
        self.rejects("PORT_ENTRY_MISMATCH", fx.validate, "dispatch", "x2", portId="embedded")
        registry = json.loads((fx.repo / DF.REGISTRY).read_text())
        wrong = copy.deepcopy(registry)
        next(p for p in wrong["execution_ports"] if p["id"] == "standalone")["profile"]["purpose"] = "coding-implementer"
        write(fx.repo, DF.REGISTRY, json.dumps(wrong, indent=1) + "\n")
        self.rejects("PORT_NOT_REGISTERED", fx.validate, "dispatch", "x3", portId="standalone")
        write(fx.repo, DF.REGISTRY, json.dumps(registry, indent=1) + "\n")
        self.assertEqual(fx.inst()["runtimeVersion"], before)
        # material mismatch: the fixed identity no longer matches what the Git objects produce
        fx.validate("formal-authorize", "f1", maxCalls=1)
        fx.validate("dispatch", "p1")

        def tamper(state):
            state["tasks"][fx.task_id]["validateChange"]["rounds"][-1]["document"]["sha256"] = "0" * 64
        fx.domain.transaction(fx.generation, tamper)
        reviewer = VF.SyntheticImplReviewer(("valid", "PASS"))
        fx.run_reviews(reviewer)
        self.assertEqual(reviewer.calls, 0)
        self.failed(fx, "preflight_failed")
        self.assertEqual(fx.rounds()[-1]["failure"]["failureCode"], "review-material-mismatch")
        # a not-determinable authorization (explicitly synthetic callback) is refused before any provider call
        fx.restart()
        fx.validate("formal-authorize", "f2", maxCalls=1)
        fx.validate("dispatch", "p2")
        reviewer = VF.SyntheticImplReviewer(("valid", "PASS"))
        fx.run_reviews(reviewer, authorizer=DF.synthetic_authorizer(decision="NOT_DETERMINABLE"))
        self.assertEqual(reviewer.calls, 0)
        self.failed(fx, "preflight_failed")
        self.assertEqual(fx.rounds()[-1]["failure"]["failureCode"], "policy-not-determinable")

    def test_program_identity_change_between_executions_is_not_a_refusal(self):
        """AC-06 (Assistant OD-399): a new reviewer program version and binary digest between two executions is recorded, not refused."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        fx.validate("formal-authorize", "f1", maxCalls=1)
        fx.validate("dispatch", "p1")
        fx.run_reviews(VF.SyntheticImplReviewer(("failed", "cancelled_by_host", "host-cancel")))
        self.failed(fx, "cancelled_by_host")
        registry = json.loads((fx.repo / DF.REGISTRY).read_text())
        port = next(p for p in registry["execution_ports"] if p["id"] == "standalone")
        port["profile"]["programIdentity"].update(version="99.0.0-synthetic", binaryDigest="f" * 64)
        write(fx.repo, DF.REGISTRY, json.dumps(registry, indent=1) + "\n")
        fx.restart()
        fx.validate("formal-authorize", "f2", maxCalls=1)
        fx.validate("dispatch", "p2")
        reviewer = VF.SyntheticImplReviewer(("valid", "PASS"))
        self.assertFalse(fx.run_reviews(reviewer))
        self.assertEqual(reviewer.calls, 1)
        self.assertEqual(reviewer.intents[-1]["profile"]["programIdentity"]["version"], "99.0.0-synthetic")
        self.assertEqual(fx.inst()["position"], "N-PUBLISH-AUTH-GATE")

    # -- AC-07 ------------------------------------------------------------------------------------------
    def test_valid_verdicts_map_the_seven_classes_and_keep_bytes(self):
        """AC-07: PASS and FAIL verdicts are recorded by EvidenceRef with FR-24's seven classes; HEAD moving later changes nothing."""
        fx = self.fixture()
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL", dict(non_blocking=True))), "p1")
        rnd = fx.rounds()[-1]
        self.assertEqual(rnd["verdict"]["verdict"], "FAIL")
        self.assertEqual(fx.inst()["position"], "N-VALIDATE-BUDGET-DECISION")
        seven = rnd["semantics"]
        self.assertEqual(set(seven), {"Verdict", "Review Scope & Basis", "Goal Conditions Assessment", "Findings",
                                      "Non-blocking Recommendations", "Validation Evidence", "Provenance"})
        self.assertEqual(seven["Verdict"]["value"], "FAIL")
        self.assertEqual([f["severity"] for f in seven["Findings"]["items"]], ["blocking"])
        self.assertEqual([f["severity"] for f in seven["Non-blocking Recommendations"]["items"]], ["non_blocking"])
        self.assertEqual(len(seven["Goal Conditions Assessment"]["questionAssessments"]), 5)
        self.assertEqual(seven["Validation Evidence"]["verification"]["result"], "PASS")
        self.assertTrue(seven["Provenance"]["policyDecisions"])
        self.assertEqual(seven["Review Scope & Basis"]["candidateCommit"], rnd["candidateCommit"])
        fact = fx.inst()["facts"][rnd["verdictFact"]]
        self.assertEqual((fact["kind"], fact["purpose"], fact["consumedBy"]), ("reviewer-verdict", "change-validation",
                                                                                 "settle:%s:e-v03" % rnd["executionId"]))
        self.assertEqual(fact["payload"]["evidenceRef"]["sha256"], rnd["verdict"]["verdictSha256"])
        write(fx.worktree, "later.txt", "later\n")
        git(fx.worktree, "add", "later.txt")
        git(fx.worktree, "commit", "-q", "-m", "later")
        self.assertNotEqual(git(fx.worktree, "rev-parse", "HEAD"), rnd["candidateCommit"])
        self.assertEqual(fx.rounds()[-1]["candidateCommit"], rnd["candidateCommit"])
        self.assertEqual(fx.inst()["facts"][rnd["verdictFact"]], fact)

    def test_invalid_verdicts_never_enter_the_domain(self):
        """AC-07 AC-08: wrong schema, stage, question set or candidate identity is an execution failure, never FAIL."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        cases = [dict(schema="review-channel-verdict/v3"), dict(stage="task"), dict(questions=DF.QUESTIONS),
                 dict(candidate_sha="e" * 64)]
        for n, change in enumerate(cases):
            with self.subTest(case=change):
                fx.validate("formal-authorize", "f%d" % n, maxCalls=1)
                fx.validate("dispatch", "p%d" % n)
                script = (lambda rnd, change=change: VF.valid_outcome(rnd, VF.verdict_block(rnd, "FAIL", **change)))
                fx.run_reviews(VF.SyntheticImplReviewer(script))
                self.failed(fx, "verdict-not-acceptable")
                self.assertIsNone(fx.rounds()[-1]["verdict"])
                fx.restart()
        self.assertEqual({r["round"] for r in fx.rounds()}, {"r1"})
        self.assertEqual([r["attempt"] for r in fx.rounds()], [1, 2, 3, 4])

    def test_human_findings_wait_for_a_disposition_ruling(self):
        """AC-07: a verdict with a human finding stops until the Human disposes it; a finding-disposition ruling is written first."""
        fx = self.fixture()
        fx.review_once(VF.SyntheticImplReviewer(("valid", "PASS", dict(human=True))), "p1")
        rnd = fx.rounds()[-1]
        self.assertEqual(rnd["status"], "awaiting-human-disposition")
        self.assertEqual(fx.inst()["position"], "N-VALIDATE-VERDICT-DECISION")
        self.rejects(V.INPUT_INVALID, fx.validate, "dispose", "x1", decisionText="处置", findings={"R9-H1": "x"})
        out = fx.validate("dispose", "d1", decisionText="接受该问题，留待发布说明", findings={"R1-H1": "不阻断，发布说明写明"})
        self.assertEqual(out["result"], V.RULING_REGISTERED)
        self.assertEqual(fx.inst()["position"], "N-VALIDATE-VERDICT-DECISION")
        self.assertFalse(fx.run_reviews(VF.SyntheticImplReviewer()))
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH-AUTH-GATE", states.AWAITING_HUMAN_ACTION))
        ruling = records.view_of(fx.state(), fx.task_id)["rulings"][-1]
        self.assertEqual((ruling["type"], ruling["status"]), ("finding-disposition", "written"))
        raw = subprocess.run(["git", "-C", str(fx.worktree), "show", "HEAD:" + ruling["path"]], capture_output=True).stdout
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ruling["sha256"])
        self.assertIn(b"> Type: finding-disposition", raw)
        lint = subprocess.run([sys.executable, str(HP / DF.VALIDATOR), "ruling", str(fx.worktree / ruling["path"])],
                              capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    # -- AC-08 ------------------------------------------------------------------------------------------
    def test_host_cancel_and_infrastructure_failures_are_not_reviewer_fail(self):
        """AC-08: every non-verdict classification fails the attempt into recovery, never E-V05, never a budget decision."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        for n, (classification, code) in enumerate(FAILURES):
            with self.subTest(classification=classification):
                fx.validate("formal-authorize", "f%d" % n, maxCalls=1)
                fx.validate("dispatch", "p%d" % n)
                fx.run_reviews(VF.SyntheticImplReviewer(("failed", classification, code)))
                self.failed(fx, classification)
                fx.restart()
        self.assertEqual({r["round"] for r in fx.rounds()}, {"r1"})

    def test_channel_refusal_before_attempt_keeps_its_reason(self):
        """A channel refusal before any attempt settles the round as an execution failure that keeps the channel's code and text, and releases the reservation as refused before release."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        fx.validate("formal-authorize", "f0", maxCalls=1)
        out = fx.validate("dispatch", "p0")
        refused = dict(classification="preflight_failed", failureCode="request-unrouteable",
                       problems=["task_record present but malformed"], runnerCode=1)
        fx.run_reviews(VF.SyntheticImplReviewer(lambda _round: dict(refused)))
        self.failed(fx, "preflight_failed")
        self.assertEqual(fx.rounds()[-1]["failure"], dict(status="EXECUTION_FAILED", classification="preflight_failed",
                                                          failureCode="request-unrouteable",
                                                          problems=["task_record present but malformed"]))
        self.assertEqual(fx.inst()["reservations"][out["executionId"]]["status"], "settled")

    @instance_area.needed
    def test_unknown_and_stop_unconfirmed_keep_the_reservation_and_only_query(self):
        """AC-08: unknown and the J-06 stop-unconfirmed projection are INDETERMINATE; reservation held; nothing is dispatched again."""
        sample = json.loads((instance_area.path(J06) / "physical-execution.stopping.json").read_text())
        for name, script in (("unknown", ("failed", "unknown", "result-unknown", False)), ("stopping", ("stopping", sample))):
            with self.subTest(case=name):
                fx = self.fixture(name)
                fx.validate("configure", "c1")
                fx.validate("formal-authorize", "f1", maxCalls=1)
                out = fx.validate("dispatch", "p1")
                reviewer = VF.SyntheticImplReviewer(script)
                fx.run_reviews(reviewer)
                rnd = fx.rounds()[-1]
                self.assertEqual(rnd["status"], "indeterminate")
                self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
                self.assertEqual(fx.inst()["reservations"][out["executionId"]]["status"], "held")
                self.assertEqual(fx.state()["executionDescriptors"][out["executionId"]]["status"], "indeterminate")
                if name == "stopping":
                    self.assertEqual(rnd["failure"]["failureCode"], "stop-unconfirmed")
                fx.run_reviews(reviewer)
                self.assertEqual(reviewer.calls, 1)
                self.rejects(W.RECOVERY_REQUIRED_BLOCKS_PROGRESSION, fx.validate, "dispatch", "p2")
                self.assertFalse(fx.budget_facts())

    # -- AC-09 ------------------------------------------------------------------------------------------
    def test_validation_escalation_accept_with_reservation(self):
        """AC-09: at the Validation escalation the three decisions are legal; Accept With reservation needs the entry and keeps the context."""
        fx = self.fixture(budget=budget(validation=0))
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p1")
        decided = fx.budget_decide("b1")
        self.assertEqual((decided["outcome"], fx.inst()["position"]), (ledger.EXHAUSTED, "N-VALIDATE-ESCALATION-GATE"))
        from domain.workflow import progression
        legal = {d["decision"] for d in progression.decisions(fx.inst(), fx.domain.topology(fx.inst()))}
        self.assertEqual(legal, {"Continue", "Close Task", "Accept With reservation"})
        self.assertEqual({d["decision"] for d in fx.domain.status(fx.task_id)["tasks"][0]["decisions"]}, {"Continue", "Close Task"})
        refused = self.rejects(W.DECISION_NOT_LEGAL_HERE, fx.run, "decide", commandId="g0", decision="Accept With reservation",
                               reservation="x")
        self.assertTrue(refused.detail["validationEntryRequired"])
        self.rejects(V.RESERVATION_REQUIRED, fx.validate, "decide", "g1", decision="Accept With reservation", decisionText="带保留接受")
        # feature-t7: this decision is the path's Publish authorization and must carry the exact binding (FR-26, KB-265).
        import publish_fixture as PFX
        PFX.attach(fx)
        missing = self.rejects(V.INPUT_INVALID, fx.validate, "decide", "g1b", decision="Accept With reservation",
                               decisionText="带保留接受", reservation="目标条件 1 留待发布说明")
        self.assertEqual(missing.detail["publishReason"]["field"], "publishBinding")
        out = fx.validate("decide", "g2", decision="Accept With reservation", decisionText="带保留接受",
                          reservation="目标条件 1 留待发布说明", **PFX.binding_for(fx))
        self.assertEqual(out["result"], V.RESERVATION_ACCEPTED)
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH", states.ENTERED))
        fact = fx.inst()["facts"][out["decision"]["factId"]]
        self.assertEqual((fact["payload"]["edgeId"], fact["consumedBy"]), ("E-V12", "g2"))
        context = fact["payload"]["decisionContext"]
        self.assertEqual((context["verdict"], [f["severity"] for f in context["findings"]]), ("FAIL", ["blocking"]))
        view = records.publish_context(fx.state(), fx.task_id)
        self.assertEqual(view["reservations"][0]["reservation"], "目标条件 1 留待发布说明")
        self.assertEqual(view["reservations"][0]["verdict"]["verdict"], "FAIL")
        # feature-t7 seam closed: this Publish authorization carries the exact binding, so the push permit is ALLOW.
        push = dict(candidateCommit=fx.rounds()[-1]["candidateCommit"], sourceBranch=fx.task["branch"], remote="origin",
                    targetBranch="main", repositoryIdentity=fx.task["anchor"]["repositoryIdentity"])
        permit = fx.run("policy-evaluate", request=dict(schema=rules.REQUEST_SCHEMA, subject="push-permit", taskId=fx.task_id,
                                                        push=push))
        codes = {i["item"]: (i["result"], (i.get("reason") or {}).get("code")) for i in permit["decision"]["items"]}
        self.assertEqual(codes["human-authority"][0], "PASS")
        self.assertEqual((codes["push-permit"], permit["conclusion"]), (("PASS", None), "ALLOW"))

    def test_validation_escalation_continue_and_close(self):
        """AC-09: Continue returns through feature-t4's dispatch with the last Validation verdict as remediation input; Close Task terminates."""
        fx = self.fixture(budget=budget(validation=0))
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p1")
        fx.budget_decide("b1")
        fx.run("decide", commandId="g1", decision="Continue")
        self.assertEqual(fx.inst()["position"], "N-VALIDATE-CONTINUE")
        self.rejects(W.ILLEGAL_TRANSITION, fx.run, "advance", commandId="x", edgeId="E-V13")
        out = fx.implement()
        remediation = out["execution"]["remediation"]
        self.assertEqual((remediation["kind"], remediation["verdict"], remediation["round"]), ("validation", "FAIL", "r1"))
        self.assertEqual([e for e in fx.edges() if e in ("E-V10", "E-V13", "E-V08")], ["E-V10", "E-V13", "E-V08"])
        other = self.fixture("close", budget=budget(validation=0))
        other.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p1")
        other.budget_decide("b1")
        other.run("decide", commandId="g1", decision="Close Task")
        inst = other.inst()
        self.assertEqual((inst["lifecycle"], inst["position"], inst["closure"]["reasonCategory"]),
                         (states.CLOSED, "N-VALIDATE-CLOSE", "blocked-escalation"))

    # -- AC-01 ------------------------------------------------------------------------------------------
    def test_generic_commands_are_narrowed_at_validate_nodes_for_any_task(self):
        """AC-01: generic commands cannot record facts or move Validate Change nodes, even on a task no feature-t5 entry drove."""
        fx = self.fixture()
        self.rejects(W.ILLEGAL_TRANSITION, fx.run, "advance", commandId="a1", edgeId="E-V02")
        fx.validate("configure", "c1")
        for name, payload in (("fact", dict(fact=dict(factId="forged", kind="reviewer-verdict", purpose="change-validation",
                                                      authorityRef=OWNER, payload=dict(verdict="PASS")))),
                              ("condition", dict(commandId="c2", condition=states.EXECUTING)),
                              ("attempt-open", dict(attemptId="x", purpose="node-work"))):
            with self.subTest(command=name):
                error = self.rejects(W.ILLEGAL_TRANSITION, fx.run, name, **payload)
                self.assertEqual(error.detail["reasonCode"], "GENERIC_COMMAND_NARROWED")
        # a task walked to the node without any feature-t5 entry (SYNTHETIC direct walk) is narrowed the same way
        raw = self.fixture("raw", change_validation=False)
        self.assertEqual(raw.inst()["position"], "N-VALIDATE-CONFIG")
        self.rejects(W.ILLEGAL_TRANSITION, raw.run, "advance", commandId="a1", edgeId="E-V02")
        self.assertEqual(raw.run("close", commandId="close", reasonCategory="human-initiated")["result"], W.FINALIZED)

    # -- AC-10 (Domain Core level) ----------------------------------------------------------------------
    def test_runtime_entry_shares_the_state_and_fences_the_older_generation(self):
        """AC-10: the Runtime-entry Domain Core sees the CLI's dispatched review; the older CLI generation is refused."""
        fx = self.fixture()
        fx.validate("configure", "c1")
        fx.validate("formal-authorize", "f1", maxCalls=1)
        fx.validate("dispatch", "p1")
        runtime = HarnessDomain(fx.repo, entry="runtime")
        generation = runtime.acquire_generation()
        with self.assertRaises(ValidationRejection) as ctx:
            runtime.run("validate-dispatch", dict(taskId=fx.task_id, commandId="rt-p", authorityRef=OWNER), generation=generation)
        self.assertEqual(ctx.exception.code, V.EXECUTION_IN_FLIGHT)
        with self.assertRaises(WorkflowRejection) as stale:
            fx.validate("dispose", "d-stale", decisionText="x", findings={})
        self.assertEqual(stale.exception.code, W.STALE_CONTROL_GENERATION)


if __name__ == "__main__":
    unittest.main()


class ValidateChangeRuntime(ValidationCase):
    # -- AC-10 (real serve-stdio process) -----------------------------------------------------------------
    def test_real_serve_stdio_and_cli_reach_the_same_results(self):
        """AC-10: the product Runtime actions (configure, formal authorization, dispatch, budget decision, reservation) and the CLI
        give the same edges, facts and budget values on twin synthetic lines; stale generations and illegal actions are refused."""
        from validation_stdio import ValidationHost, launch_files
        inputs = dict(budget=budget(validation=1))
        fx = self.fixture("stdio", **inputs)
        twin = self.fixture("cli", **inputs)
        start_fx, start_twin = len(fx.edges()), len(twin.edges())
        # CLI twin
        twin.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p1")
        twin.budget_decide("b1")
        # Runtime
        case = self.directory / "stdio-case"
        case.mkdir()
        launch_files(case, fx)
        host = ValidationHost(case, dict(HP_T5_VERDICT="FAIL"), output=case / "frames.jsonl")
        try:
            host.initialize()
            host.activate()
            self.assertTrue(host.action("validate.configure")["enabled"])
            self.assertFalse(host.action("validate.dispatch")["enabled"])
            host.invoke("validate.dispatch", dict(taskId=fx.task_id, expectedRuntimeVersion=fx.inst()["runtimeVersion"]),
                        error="PRECONDITION_CONFLICT")
            results = []
            for action_id, extra in (("validate.configure", {}), ("validate.formal-authorize", dict(maxCalls=1)),
                                     ("validate.dispatch", {})):
                accepted, p = host.invoke(action_id, dict(taskId=fx.task_id, expectedRuntimeVersion=fx.inst()["runtimeVersion"], **extra))
                op = host.wait_operation(p["operationId"])
                results.append((op["status"], op["resultCode"]))
            self.assertEqual(results, [("succeeded", "VALIDATION-CONFIGURED"), ("succeeded", "FORMAL-AUTHORIZATION-RECORDED"),
                                       ("succeeded", "VERDICT-RECORDED")])
            self.assertEqual(fx.inst()["position"], "N-VALIDATE-BUDGET-DECISION")
            self.assertTrue(host.action("budget.decide")["enabled"])
            accepted, p = host.invoke("budget.decide", dict(taskId=fx.task_id, expectedRuntimeVersion=fx.inst()["runtimeVersion"]))
            op = host.wait_operation(p["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "BUDGET-ROUTED"))
            # the CLI entry holding an older control generation is fenced out
            with self.assertRaises(WorkflowRejection) as stale:
                fx.budget_decide("b-stale")
            self.assertEqual(stale.exception.code, W.STALE_CONTROL_GENERATION)
        finally:
            host.close()
        self.assertEqual(fx.edges()[start_fx:], twin.edges()[start_twin:])
        self.assertEqual(fx.edges()[-1], "E-V07")

        def shape(f):
            payload = f["payload"] or {}
            return (f["kind"], f["purpose"], f["node"], payload.get("conclusion"), payload.get("outcome"),
                    payload.get("verdict"), payload.get("changeValidation"))
        mine = sorted(shape(f) for f in fx.inst()["facts"].values() if f["node"].startswith("N-VALIDATE"))
        theirs = sorted(shape(f) for f in twin.inst()["facts"].values() if f["node"].startswith("N-VALIDATE"))
        self.assertEqual(mine, theirs)
        a = fx.budget_facts()[-1]["payload"]["derived"]["budget"]
        b = twin.budget_facts()[-1]["payload"]["derived"]["budget"]
        self.assertEqual((a["grant"]["amount"], a["consumed"], a["outcome"]), (b["grant"]["amount"], b["consumed"], b["outcome"]))
        from domain.validation import projection as validation_projection
        from domain.budget import projection as budget_projection
        self.assertEqual((validation_projection.legal(fx.state(), fx.task_id), budget_projection.legal(fx.state(), fx.task_id)),
                         (validation_projection.legal(twin.state(), twin.task_id), budget_projection.legal(twin.state(), twin.task_id)))

    def test_real_serve_stdio_disposition_and_reservation(self):
        """AC-10: through the product Runtime a human finding is disposed (ruling written by the Runtime's execution layer), the
        exhausted budget reaches the escalation gate and Accept With reservation reaches Publish, as on the CLI twin."""
        from validation_stdio import ValidationHost, launch_files
        inputs = dict(budget=budget(validation=0))
        fx = self.fixture("stdio", **inputs)
        twin = self.fixture("cli", **inputs)
        start_fx, start_twin = len(fx.edges()), len(twin.edges())
        findings = {"R1-H1": "不阻断，记入发布说明"}
        twin.review_once(VF.SyntheticImplReviewer(("valid", "FAIL", dict(human=True))), "p1")
        twin.validate("dispose", "d1", decisionText="处置", findings=findings)
        twin.run_reviews(VF.SyntheticImplReviewer())
        twin.budget_decide("b1")
        import publish_fixture as PFX  # feature-t7: both entries carry the Publish binding on this decision
        PFX.attach(fx), PFX.attach(twin)
        twin.validate("decide", "g1", decision="Accept With reservation", decisionText="带保留接受", reservation="保留一项",
                      **PFX.binding_for(twin))
        case = self.directory / "stdio-case"
        case.mkdir()
        launch_files(case, fx)
        host = ValidationHost(case, dict(HP_T5_VERDICT="FAIL", HP_T5_HUMAN="1"), output=case / "frames.jsonl")
        try:
            host.initialize()
            host.activate()
            steps = (("validate.configure", {}), ("validate.formal-authorize", dict(maxCalls=1)), ("validate.dispatch", {}),
                     ("validate.dispose", dict(decisionText="处置", findings=findings)), ("budget.decide", {}),
                     ("validate.decide", PFX.LazyBinding(fx, decisionText="带保留接受", reservation="保留一项")))
            codes = []
            for action_id, extra in steps:
                accepted, p = host.invoke(action_id, dict(taskId=fx.task_id, expectedRuntimeVersion=fx.inst()["runtimeVersion"], **extra))
                op = host.wait_operation(p["operationId"])
                codes.append((op["status"], op["resultCode"]))
            self.assertEqual(codes, [("succeeded", "VALIDATION-CONFIGURED"), ("succeeded", "FORMAL-AUTHORIZATION-RECORDED"),
                                     ("succeeded", "VERDICT-RECORDED"), ("succeeded", "FINDING-DISPOSED"),
                                     ("succeeded", "BUDGET-ROUTED"), ("succeeded", "RESERVATION-ACCEPTED")])
        finally:
            host.close()
        self.assertEqual((fx.inst()["position"], twin.inst()["position"]), ("N-PUBLISH", "N-PUBLISH"))
        self.assertEqual(fx.edges()[start_fx:], twin.edges()[start_twin:])
        mine, theirs = records.view_of(fx.state(), fx.task_id), records.view_of(twin.state(), twin.task_id)
        self.assertEqual([(r["type"], r["status"]) for r in mine["rulings"]], [(r["type"], r["status"]) for r in theirs["rulings"]])
        self.assertEqual([r["reservation"] for r in mine["reservations"]], [r["reservation"] for r in theirs["reservations"]])
