"""feature-t5 autonomous budget on synthetic product lines. Docstrings carry the AC tags.

The Policy Gate, the budget derivation and routing, feature-t3's Definition loop, feature-t4's Implement and
Verify loop and the execution layer are production code. The Definition-round reviewer, the Validate Change
reviewer and (for the Definition loop only) the review authorization callback are explicitly SYNTHETIC
(definition_fixture, validation_fixture). No real model, no remote operation, no write outside temp dirs.
"""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import definition_fixture as DF
import guarded_walk
import validation_fixture as VF
from domain.budget import configuration, ledger, results as B
from domain.budget.results import BudgetRejection
from domain.implement_verify.results import ImplementVerifyRejection
from domain.policy import rules
from domain.policy.results import PolicyInputInvalid
from domain.workflow import results as W, states
from domain.workflow.results import WorkflowRejection
from product_line import TOPOLOGY
from runtime.executions import Environment, run_pending

OWNER = VF.OWNER
BASE_RULE_SET_DIGEST = "a7fb4f62f955d9dc39c335ca52a7874913cd7fbb1d3ad10c2e383dac1e8f309c"  # feature-t6 at c4a0559


def budget(definition=1, verification=1, validation=1):
    return dict(definitionReview=definition, verification=verification, validationReview=validation)


class BudgetCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("t5-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t5-budget-")
            self.directory = Path(self.temp.name)

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def fixture(self, name="fx", **kw):
        return VF.ValidationFixture(self.directory / name, **kw)

    def rejects(self, codes, function, *args, **kw):
        with self.assertRaises((BudgetRejection, WorkflowRejection, PolicyInputInvalid)) as ctx:
            function(*args, **kw)
        code = getattr(ctx.exception, "code", None) or ctx.exception.reason().get("code")
        self.assertIn(code, codes if isinstance(codes, tuple) else (codes,), str(ctx.exception))
        return ctx.exception

    def verify_fail(self, fx):
        fx.implement("bad-%d" % (len(fx.executions()) + 1))
        try:
            out = fx.verify()
        except ImplementVerifyRejection as exc:  # a product refusal is a product assertion failure, not a test error
            self.fail("Verify refused the routed candidate after implementation %d: %s" % (len(fx.executions()), exc.reason()))
        self.assertEqual(out["result"], "VERIFY_FAIL")
        self.assertEqual(fx.inst()["position"], "N-VERIFY-BUDGET-DECISION")

    @staticmethod
    def recount(fx, subject):
        """Independent recount from the commits: window start, Remains progressions after it (test-side reconstruction)."""
        spec = ledger.LOOPS[subject]
        commits = fx.inst()["commits"]
        advances = [(i, c) for i, c in enumerate(commits) if c["transitionKind"] == states.POSITION_ADVANCE]
        conts = [i for i, c in advances if c["selectedEdge"] == spec["continueEdge"]]
        fails = [i for i, c in advances if c["selectedEdge"] == spec["failEdge"]]
        start = conts[-1] if conts else fails[0]
        return len([1 for i, c in advances if i > start and c["selectedEdge"] == spec["remainsEdge"]])


class BudgetDecisionShape(BudgetCase):
    # -- AC-02 ------------------------------------------------------------------------------------------
    def test_remains_and_exhausted_are_allow_records_consumed_by_feature_t4(self):
        """AC-02: Verification budget decisions are Policy Gate ALLOW records with outcome; feature-t4's remediate routes E-I08 / E-I10."""
        fx = self.fixture(budget=budget(verification=1))
        self.verify_fail(fx)
        first = fx.budget_decide("b1")
        self.assertEqual((first["result"], first["outcome"], first["edge"]), (B.BUDGET_ROUTED, ledger.REMAINS, "E-I08"))
        fact = fx.inst()["facts"][first["factId"]]
        self.assertEqual((fact["kind"], fact["purpose"], fact["producer"]), ("policy-decision", "verification-budget", "policy-gate"))
        self.assertEqual((fact["payload"]["conclusion"], fact["payload"]["outcome"]), ("ALLOW", ledger.REMAINS))
        self.assertEqual(fact["payload"]["ruleSetDigest"], rules.BUDGET_RULE_SET_DIGEST)
        self.assertEqual(fact["consumedBy"], "b1:E-I08")
        self.assertEqual(fx.inst()["position"], "N-VERIFY-AUTONOMOUS-REMEDIATION")
        self.verify_fail(fx)
        second = fx.budget_decide("b2")
        self.assertEqual((second["outcome"], second["edge"]), (ledger.EXHAUSTED, "E-I10"))
        fact = fx.inst()["facts"][second["factId"]]
        self.assertEqual((fact["payload"]["conclusion"], fact["payload"]["outcome"]), ("ALLOW", ledger.EXHAUSTED))
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-VERIFY-ESCALATION-GATE", states.AWAITING_HUMAN_ACTION))

    def test_deny_and_not_determinable_record_and_do_not_move(self):
        """AC-02 AC-03: missing configuration is NOT_DETERMINABLE, an unbound Remains history is DENY; neither moves; no generic write."""
        fx = self.fixture()
        self.verify_fail(fx)
        before = (fx.inst()["position"], fx.inst()["condition"], fx.inst()["runtimeVersion"])
        missing = fx.budget_decide("b1")
        self.assertEqual(missing["result"], B.BUDGET_NOT_DETERMINABLE)
        self.assertEqual(B.exit_code(missing["result"]), 2)
        codes = {i["item"]: (i["result"], (i.get("reason") or {}).get("code")) for i in missing["decision"]["items"]}
        self.assertEqual(codes["autonomous-budget"], ("NOT_CHECKED", "BUDGET_NOT_CONFIGURED"))
        self.assertNotIn("outcome", missing["decision"])
        after = (fx.inst()["position"], fx.inst()["condition"])
        self.assertEqual(after, before[:2])
        # the generic fact entry cannot write a budget decision (feature-t6 producer binding) nor move the node
        self.rejects(W.ILLEGAL_TRANSITION, fx.run, "fact", fact=dict(factId="forged", kind="policy-decision",
                                                                     purpose="verification-budget", authorityRef=OWNER,
                                                                     payload=dict(conclusion="ALLOW", outcome=ledger.REMAINS)))
        # configuring afterwards lets the same window proceed (first configuration after the window start)
        fx.set_budget(budget(verification=1))
        routed = fx.budget_decide("b2")
        self.assertEqual((routed["result"], routed["outcome"]), (B.BUDGET_ROUTED, ledger.REMAINS))
        self.assertEqual(routed["budget"]["grant"]["selection"], "first-configured-after-window-start")
        # DENY: a Remains progression that consumed no budget decision (a SYNTHETIC direct walk) breaks the history.
        other = self.fixture("deny", budget=budget(verification=3))
        self.verify_fail(other)
        guarded_walk.settle_and_advance(other.domain, other.generation, other.task_id, "synthetic-remains", "E-I08", OWNER)
        other.implement("bad-again", command_id="d2")
        self.assertEqual(other.verify()["result"], "VERIFY_FAIL")
        denied = other.budget_decide("b1")
        self.assertEqual(denied["result"], B.BUDGET_DENIED)
        self.assertEqual(B.exit_code(denied["result"]), 1)
        codes = {i["item"]: (i["result"], (i.get("reason") or {}).get("code")) for i in denied["decision"]["items"]}
        self.assertEqual(codes["autonomous-budget"], ("FAIL", "BUDGET_HISTORY_UNBOUND"))
        self.assertEqual(other.inst()["position"], "N-VERIFY-BUDGET-DECISION")
        self.assertEqual(other.inst()["facts"][denied["factId"]]["payload"]["conclusion"], "DENY")

    def test_existing_rule_set_identity_is_unchanged_and_position_is_checked(self):
        """AC-02: review-release, implement-release and push-permit keep feature-t6's rule set identity; a budget subject is evaluated only at its node."""
        self.assertEqual(rules.RULE_SET_DIGEST, BASE_RULE_SET_DIGEST)
        self.assertNotEqual(rules.BUDGET_RULE_SET_DIGEST, rules.RULE_SET_DIGEST)
        self.assertEqual(set(rules.SUBJECTS), {"review-release", "implement-release", "push-permit"})
        fx = self.fixture(budget=budget())
        request = dict(schema=rules.REQUEST_SCHEMA, subject="verification-budget", taskId=fx.task_id)
        error = self.rejects("INPUT_INVALID", fx.run, "policy-evaluate", request=request, commandId="e1")
        self.assertEqual(error.detail.get("reasonCode"), "BUDGET_POSITION_MISMATCH")
        self.rejects(B.POSITION_NOT_APPLICABLE, fx.budget_decide, "b0")

    # -- AC-03 ------------------------------------------------------------------------------------------
    def test_configuration_is_explicit_validated_and_historied(self):
        """AC-03: config set autonomous-budget needs authority and exactly three non-negative integers; history carries the revision."""
        fx = self.fixture()
        for bad in (dict(definitionReview=1, verification=1), dict(budget(), extra=1), budget(definition=-1),
                    dict(budget(), verification=1.5), dict(budget(), validationReview=True), "3"):
            with self.subTest(value=bad):
                self.rejects(B.BUDGET_CONFIGURATION_REJECTED, fx.set_budget, bad)
        self.rejects(B.BUDGET_CONFIGURATION_REJECTED, fx.set_budget, budget(), authority="")
        written = fx.set_budget(budget(definition=0, verification=2, validation=3))
        rows = configuration.history(fx.state())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["revision"], written["revision"])
        self.assertEqual(rows[0][1]["value"], budget(definition=0, verification=2, validation=3))
        self.assertEqual(rows[0][1]["authorityRef"], OWNER)

    def test_same_state_same_decision_identity(self):
        """AC-03: re-evaluating the same state is an idempotent replay with the same record identity; a replayed command routes nothing twice."""
        fx = self.fixture(budget=budget(verification=2))
        self.verify_fail(fx)
        request = dict(schema=rules.REQUEST_SCHEMA, subject="verification-budget", taskId=fx.task_id)
        one = fx.run("policy-evaluate", request=request)
        two = fx.run("policy-evaluate", request=request)
        self.assertEqual(one["factId"], two["factId"])
        self.assertEqual(two["result"], "IDEMPOTENT_REPLAY")
        routed = fx.budget_decide("b1")
        self.assertEqual(routed["factId"], one["factId"])
        self.assertEqual(fx.budget_decide("b1")["result"], B.IDEMPOTENT_REPLAY)

    # -- AC-01 ------------------------------------------------------------------------------------------
    def test_generic_commands_are_narrowed_at_budget_nodes_for_any_task(self):
        """AC-01: at a budget node the generic fact / condition / advance / attempt / reserve commands are refused for every task; close stays."""
        fx = self.fixture(budget=budget())
        self.verify_fail(fx)
        for name, payload in (("fact", dict(fact=dict(factId="f", kind="configuration-decision", purpose="x", authorityRef=OWNER))),
                              ("condition", dict(commandId="c1", condition=states.EXECUTING)),
                              ("advance", dict(commandId="a1", edgeId="E-I08")),
                              ("attempt-open", dict(attemptId="x1", purpose="node-work")),
                              ("reserve", dict(reservationId="r1", purpose="x", protects=["x"]))):
            with self.subTest(command=name):
                error = self.rejects(W.ILLEGAL_TRANSITION, fx.run, name, **payload)
                self.assertEqual(error.detail["reasonCode"], B.GENERIC_COMMAND_NARROWED)
        closed = fx.run("close", commandId="close-1", reasonCategory="human-initiated")
        self.assertEqual(closed["result"], W.FINALIZED)

    def test_topology_master_is_untouched(self):
        """AC-01: the six budget edges and the Validate Change edges used here are registered in the unchanged topology master."""
        raw = TOPOLOGY.read_bytes()
        before = hashlib.sha256(raw).hexdigest()
        for spec in ledger.LOOPS.values():
            for key in ("failEdge", "remainsEdge", "exhaustedEdge", "continueEdge"):
                self.assertIn('topologyEdgeId="%s"' % spec[key], raw.decode())
            self.assertIn('topologyNodeId="%s"' % spec["node"], raw.decode())
        self.assertEqual(hashlib.sha256(TOPOLOGY.read_bytes()).hexdigest(), before)


class RevisionOrder(BudgetCase):
    # -- AC-04 (feature-t5:KB-02 regression, fix authorized by feature-t5:OD-04) ------------------------
    def test_feature_t4_picks_the_latest_record_across_a_digit_boundary(self):
        """AC-04: feature-t4 selects the latest execution and Verification by integer domain revision ("100" after "99")."""
        from domain.implement_verify import assessment, dispatch as implement_dispatch, verify
        self.assertEqual(max("99", "100"), "99")  # the string order this regression guards against
        fx = self.fixture(budget=budget())
        state = fx.state()
        task_id = fx.task_id
        inst = state["tasks"][task_id]["workflowInstance"]
        occurrence = dict(workflowInstance=task_id, node=inst["position"], positionEntryRuntimeVersion=inst["positionEntryRevision"])
        ledger_ = state["tasks"][task_id].setdefault("implementVerify", dict(executions={}, verifications={}, assessments={}))
        for name, revision in (("earlier", "99"), ("later", "100")):
            # SYNTHETIC records: only the fields the four selection points read.
            ledger_["executions"][name] = dict(executionRequestId=name, status="settled", settlement=dict(kind="completed"),
                                              dispatchedRevision=revision, occurrence=occurrence)
            ledger_["verifications"][name] = dict(verificationId=name, result="FAIL", status="execution-failed",
                                                 recordedRevision=revision, occurrence=occurrence, findings=[name],
                                                 candidateCommit=fx.head, failure=None)
        self.assertEqual(verify.routed_candidate(state, task_id)["executionRequestId"], "later")
        self.assertEqual(assessment._current_execution(state, task_id, inst)["executionRequestId"], "later")
        self.assertEqual(assessment._verify(state, task_id, inst)[1]["verificationId"], "later")
        self.assertEqual(implement_dispatch._remediation(state, task_id)["verificationId"], "later")


class BudgetDrills(BudgetCase):
    # -- AC-04 ------------------------------------------------------------------------------------------
    def test_verification_loop_remains_exhausts_and_continue_grants_a_new_window(self):
        """AC-04: Verify remediation: Remains twice, Exhausted, Human Continue -> new window at the Continue revision's amount."""
        fx = self.fixture(budget=budget(verification=2))
        outcomes = []
        for n in range(3):
            self.verify_fail(fx)
            if n == 1:
                fx.set_budget(budget(verification=5))  # a change mid-window does not change this window's amount
            decided = fx.budget_decide("b%d" % n)
            outcomes.append(decided["outcome"])
            self.assertEqual(decided["budget"]["grant"]["amount"], 2)
            self.assertEqual(decided["budget"]["consumed"], self.recount(fx, "verification-budget") - (1 if decided["outcome"] == ledger.REMAINS else 0))
        self.assertEqual(outcomes, [ledger.REMAINS, ledger.REMAINS, ledger.EXHAUSTED])
        self.assertEqual(fx.inst()["position"], "N-VERIFY-ESCALATION-GATE")
        fx.set_budget(budget(verification=1))
        fx.run("decide", commandId="g1", decision="Continue")
        continued = [c for c in fx.inst()["commits"] if c["selectedEdge"] == "E-I11"][-1]
        self.verify_fail(fx)
        again = fx.budget_decide("b3")
        self.assertEqual((again["outcome"], again["budget"]["window"]["basis"]), (ledger.REMAINS, "continue"))
        self.assertEqual(again["budget"]["window"]["continueDecisionFact"], continued["triggers"][0])
        self.assertEqual(again["budget"]["grant"]["amount"], 1)
        self.assertIn(continued["triggers"][0], fx.inst()["facts"][again["factId"]]["payload"]["authorizationRefs"])
        self.verify_fail(fx)
        self.assertEqual(fx.budget_decide("b4")["outcome"], ledger.EXHAUSTED)
        # every decision is reconstructible from the facts and commits
        for fact in fx.budget_facts():
            derived = fact["payload"]["derived"]["budget"]
            self.assertEqual(derived["remaining"], max(derived["grant"]["amount"] - derived["consumed"], 0))

    def test_zero_budget_exhausts_at_once(self):
        """AC-04: a zero budget is exhausted on the first decision."""
        fx = self.fixture(budget=budget(verification=0))
        self.verify_fail(fx)
        decided = fx.budget_decide("b1")
        self.assertEqual((decided["outcome"], decided["budget"]["grant"]["amount"], decided["budget"]["consumed"]),
                         (ledger.EXHAUSTED, 0, 0))

    def test_validation_loop_drill_and_independent_counts(self):
        """AC-04: Validate Change remediation: Remains, Exhausted, Continue new window; the Verification count is untouched; failures consume nothing."""
        fx = self.fixture(change_validation=True, budget=budget(verification=0, validation=1))
        fx.to_validate()
        fx.review_once(VF.SyntheticImplReviewer(("failed", "cancelled_by_host", "host-cancel")), "p0")
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
        self.assertFalse(fx.budget_facts())
        self._restart(fx, "N-VALIDATE-REVIEWER")
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p1")
        self.assertEqual(fx.inst()["position"], "N-VALIDATE-BUDGET-DECISION")
        first = fx.budget_decide("b1")
        self.assertEqual((first["outcome"], first["edge"]), (ledger.REMAINS, "E-V07"))
        fx.implement()
        self.assertEqual(fx.verify()["result"], "VERIFY_PASS")
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p2")
        second = fx.budget_decide("b2")
        self.assertEqual((second["outcome"], second["edge"]), (ledger.EXHAUSTED, "E-V09"))
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]),
                         ("N-VALIDATE-ESCALATION-GATE", states.AWAITING_HUMAN_ACTION))
        self.assertEqual(ledger.derive(fx.state(), fx.task_id, "validation-review-budget")["consumed"], 1)
        with self.assertRaises(ledger.BudgetBroken):  # the Verification loop never reached its budget node
            ledger.derive(fx.state(), fx.task_id, "verification-budget")
        fx.run("decide", commandId="g1", decision="Continue")
        fx.validate("resume", "r1")
        fx.implement()
        fx.verify()
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL")), "p3")
        third = fx.budget_decide("b3")
        self.assertEqual((third["outcome"], third["budget"]["window"]["basis"]), (ledger.REMAINS, "continue"))

    def _restart(self, fx, node):
        assessed = fx.run("recover-assess", assessmentId="as-%d" % len(fx.inst()["commits"]), assessment="RESTART_SAFE",
                          evidence=dict(note="synthetic: the review attempt failed before any provider call"))
        occurrence = dict(workflowInstance=fx.task_id, node=node, positionEntryRuntimeVersion=fx.inst()["positionEntryRevision"])
        fx.run("recover", commandId="rs-%s" % assessed["assessment"]["assessmentId"], action="RESTART_CURRENT_NODE",
               assessmentId=assessed["assessment"]["assessmentId"],
               humanAuthorization=dict(workflowInstance=fx.task_id, occurrence=occurrence,
                                       expectedRuntimeVersion=fx.inst()["runtimeVersion"],
                                       assessmentId=assessed["assessment"]["assessmentId"], action="RESTART_CURRENT_NODE",
                                       effectScope="re-dispatch the change review",
                                       authorizationRef="human:synthetic:restart:" + assessed["assessment"]["assessmentId"]))
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), (node, states.ENTERED))

    def test_definition_loop_drill(self):
        """AC-04: Definition Review re-review: FAIL -> Remains -> FAIL -> Exhausted -> Continue -> new window (feature-t3's real loop)."""
        fx = DF.create(self.directory / "def", definition_review=True)
        domain = DF.TestHarnessDomain(fx["repo"], entry="cli")
        generation = domain.bind_entry()
        domain.transaction(generation, lambda s: configuration.set_budget(s, budget(definition=1), OWNER))
        reviewer = DF.SyntheticReviewer(("valid", "FAIL"), ("valid", "FAIL"), ("valid", "FAIL"))

        def cmd(name, **payload):
            payload.update(taskId="feature-t0", authorityRef=OWNER)
            return domain.run_definition(name, payload, generation=generation)

        def execute():
            env = Environment("cli", domain, generation, repository_root=str(fx["repo"]))
            return run_pending(domain, env, DF.executors(reviewer))

        def position():
            return domain.read()["tasks"]["feature-t0"]["workflowInstance"]["position"]
        cmd("submit", commandId="s1", commit=DF.commit_candidate(fx["worktree"], DF.definition_text()), author=DF.author(fx["head"]))
        outcomes = []
        for n in range(2):
            cmd("formal-authorize", commandId="f%d" % n, maxCalls=1)
            cmd("dispatch", commandId="p%d" % n)
            execute()
            self.assertEqual(position(), "N-DEF-BUDGET-DECISION")
            outcomes.append(domain.run("budget-decide", dict(taskId="feature-t0", commandId="b%d" % n, authorityRef=OWNER),
                                       generation=generation)["outcome"])
        self.assertEqual(outcomes, [ledger.REMAINS, ledger.EXHAUSTED])
        self.assertEqual(position(), "N-DEF-ESCALATION-GATE")
        domain.run("decide", dict(taskId="feature-t0", commandId="g1", decision="Continue", authorityRef=OWNER), generation=generation)
        cmd("formal-authorize", commandId="f2", maxCalls=1)
        cmd("dispatch", commandId="p2")
        execute()
        third = domain.run("budget-decide", dict(taskId="feature-t0", commandId="b2", authorityRef=OWNER), generation=generation)
        self.assertEqual((third["outcome"], third["budget"]["window"]["basis"]), (ledger.REMAINS, "continue"))
        self.assertEqual(position(), "N-DEF-REVIEW-DISPATCH")
        edges = [c["selectedEdge"] for c in domain.read()["tasks"]["feature-t0"]["workflowInstance"]["commits"]
                 if c["transitionKind"] == states.POSITION_ADVANCE]
        self.assertEqual([e for e in edges if e in ("E-D08", "E-D10", "E-D11", "E-D12")],
                         ["E-D08", "E-D11", "E-D08", "E-D10", "E-D12", "E-D08", "E-D11"])


if __name__ == "__main__":
    unittest.main()
