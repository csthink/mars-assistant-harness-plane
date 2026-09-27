"""feature-t7 Publish and controlled recovery on synthetic product lines. Docstrings carry the AC tags.

The binding check, the Publish Authorization Gate entry, the feature-t5 reservation entry, the push permit
(feature-t6 Policy Gate), the dispatch, the execution layer, the push, the production GitHub adapter, the
settlement, the same-operation query and the Human-authorised reconcile are production code. The remote is a
local bare repository created in the test directory; the platform is the SYNTHETIC program of publish_fixture
that answers the `gh api` interface from a JSON file; the Agent and the impl-round reviewer output are the
feature-t4 / feature-t5 synthetic stand-ins. No real platform program, network interface, remote or model.
"""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_fixture as PF
import validation_fixture as VF
from domain.acceptance import results as A
from domain.acceptance.accept import accept_task
from domain.acceptance.results import Rejection
from domain.acceptance.terminal import in_flight
from domain.policy import rules
from domain.publish import commands as publish_commands, executor as publish_executor, projection as publish_projection
from domain.publish import results as P
from domain.publish.platform import GitHubPlatform, PlatformError
from domain.publish.results import PublishRejection
from domain.validation import results as V
from domain.validation.results import ValidationRejection
from domain.workflow import results as W, states
from domain.workflow.results import WorkflowRejection
from product_line import git

OWNER = PF.OWNER
APP = Path(__file__).resolve().parents[1]
NARROWED = W.ILLEGAL_TRANSITION


def budget(definition=1, verification=1, validation=1):
    return dict(definitionReview=definition, verification=verification, validationReview=validation)


class PublishCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("t7-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t7-publish-")
            self.directory = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, PF.GIT_ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def fixture(self, name="fx", **kw):
        return PF.PublishFixture(self.directory / name, **kw)

    def rejects(self, code, function, *args, **kwargs):
        with self.assertRaises((PublishRejection, WorkflowRejection, ValidationRejection)) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.reason())
        return caught.exception

    def permit(self, fx):
        task = fx.state()["tasks"][fx.task_id]
        bound = fx.ledger()["authorization"]["binding"]
        push = dict(candidateCommit=bound["candidateCommit"], sourceBranch=bound["sourceBranch"], remote=bound["remote"],
                    targetBranch=bound["targetBranch"], repositoryIdentity=task["repositoryIdentity"])
        return fx.run("policy-evaluate", request=dict(schema=rules.REQUEST_SCHEMA, subject="push-permit", taskId=fx.task_id,
                                                      push=push))

    def execution(self, fx, number=-1):
        return fx.ledger()["executions"][number]

    def assert_clean_platform(self, fx):
        self.assertEqual(PF.forbidden_requests(fx.platform), [])

    # -- AC-01 --------------------------------------------------------------------------------------
    def test_publish_authorization_binds_the_exact_candidate_and_target(self):
        """AC-01: the gate's Publish authorization records the full binding and the context digest, then E-V06; push permit ALLOW."""
        fx = self.fixture()
        fx.to_gate()
        proposal = fx.proposal()
        view = proposal["context"]
        self.assertEqual(view["taskBranch"]["head"], fx.task_head())
        self.assertEqual(view["candidate"]["verification"]["result"], "PASS")
        self.assertIsNotNone(view["definition"]["frozen"])
        self.assertIn("reservations", view["definition"])
        self.assertEqual(view["reviewConfiguration"]["source"], "default")
        self.assertEqual((view["reviewConfiguration"]["definitionReview"], view["reviewConfiguration"]["changeValidation"]),
                         (False, False))
        self.assertEqual(view["validateChange"]["switch"][-1]["changeValidation"], False)
        self.assertIn("budgetDecisions", view["validateChange"])
        self.assertEqual(view["publishTarget"]["remoteAddress"], os.path.realpath(fx.bare))
        refused = self.rejects(W.DECISION_NOT_LEGAL_HERE, fx.run, "decide", commandId="g0", decision="Publish authorization")
        self.assertEqual((refused.detail["publishEntryRequired"], refused.detail["reasonCode"]),
                         (True, "DECISION_REQUIRES_PUBLISH_ENTRY"))
        self.assertEqual(fx.domain.status(fx.task_id)["tasks"][0]["decisions"], [])
        out = fx.authorize()
        self.assertEqual(out["result"], P.PUBLISH_AUTHORIZED)
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH", states.ENTERED))
        fact = fx.inst()["facts"][out["authorization"]["factId"]]
        binding = fact["payload"]["publishBinding"]
        self.assertEqual((fact["payload"]["edgeId"], fact["consumedBy"], fact["payload"]["publishContextDigest"]),
                         ("E-V06", "auth-1", proposal["contextDigest"]))
        self.assertEqual(binding["candidateCommit"], fx.task_head())
        self.assertEqual(binding["verifiedCandidateCommit"], fx.task_head())
        self.assertEqual(binding["governanceCommits"], [])
        self.assertEqual(binding["platform"], dict(provider="github", host="github.com", repository=PF.REPOSITORY,
                                                   repositoryId=PF.REPOSITORY_ID))
        self.assertEqual(binding["remoteAddress"], os.path.realpath(fx.bare))
        self.assertEqual(len(binding["pullRequest"]["bodySha256"]), 64)
        self.assertEqual(fx.ledger()["operation"]["id"], "publish:%s:auth-1:decision" % fx.task_id)
        permit = self.permit(fx)
        self.assertEqual(permit["conclusion"], "ALLOW", permit["decision"]["items"])
        self.assertEqual(fx.platform.requests(), [])

    def test_authorization_refusals_name_the_field(self):
        """AC-01: every mismatch is refused with a distinguishable reason and the field path; nothing is recorded or moved."""
        fx = self.fixture()
        fx.to_gate()
        head = fx.task_head()
        cases = [
            (P.CONTEXT_STALE, "contextDigest", dict(digest="0" * 64)),
            (P.BINDING_MISMATCH, "publishBinding.candidateCommit", dict(candidateCommit=fx.head)),
            (P.BINDING_MISMATCH, "publishBinding.sourceBranch", dict(sourceBranch="harness/other")),
            (P.BINDING_MISMATCH, "publishBinding.remote", dict(remote="upstream")),
            (P.BINDING_MISMATCH, "publishBinding.targetBranch", dict(targetBranch="release")),
            (P.INPUT_INVALID, "publishBinding.pullRequest.title", dict(pullRequest=dict(title="two\nlines", body=""))),
            (P.INPUT_INVALID, "publishBinding.pullRequest.title", dict(pullRequest=dict(title="bell\x07", body=""))),
            (P.INPUT_INVALID, "publishBinding.pullRequest.body", dict(pullRequest=dict(title="t", body="x" * 60001))),
            (P.INPUT_INVALID, "publishBinding.candidateCommit", dict(candidateCommit="HEAD")),
        ]
        for code, field, overrides in cases:
            with self.subTest(field=field, code=code):
                exc = self.rejects(code, fx.authorize, "auth-x", **overrides)
                self.assertEqual(exc.detail["field"], field)
        # the remote's push address no longer matches the configured one
        git(fx.repo, "remote", "set-url", "--push", "origin", str(self.directory / "elsewhere.git"))
        exc = self.rejects(P.BINDING_MISMATCH, fx.authorize, "auth-x")
        self.assertEqual(exc.detail["field"], "publishBinding.remoteAddress")
        git(fx.repo, "remote", "set-url", "--push", "origin", str(fx.bare))
        # a commit between the verified candidate and the head that no domain ruling write recorded
        (fx.worktree / "manual.txt").write_text("manual change\n")
        git(fx.worktree, "add", "manual.txt")
        git(fx.worktree, "commit", "-q", "-m", "manual change outside the domain")
        exc = self.rejects(P.UNCONTROLLED_CHANGE, fx.authorize, "auth-x")
        self.assertEqual(exc.detail["field"], "publishBinding.governanceCommits")
        git(fx.worktree, "reset", "-q", "--hard", head)
        # SYNTHETIC tamper (test only): the routed candidate's Verify result is not PASS or not applicable
        saved = copy.deepcopy(fx.state()["tasks"][fx.task_id]["implementVerify"])

        def tamper(s):
            for v in s["tasks"][fx.task_id]["implementVerify"]["verifications"].values():
                v["result"] = "FAIL"
        fx.domain.transaction(fx.generation, tamper)
        exc = self.rejects(P.CANDIDATE_NOT_VERIFIED, fx.authorize, "auth-x")
        self.assertEqual(exc.detail["field"], "publishBinding.verifiedCandidateCommit")
        fx.domain.transaction(fx.generation, lambda s: s["tasks"][fx.task_id].update(implementVerify=copy.deepcopy(saved)))
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH-AUTH-GATE", states.AWAITING_HUMAN_ACTION))
        self.assertEqual([f for f in fx.inst()["facts"].values() if f["purpose"] == "gate-decision"
                          and f["node"] == "N-PUBLISH-AUTH-GATE"], [])
        self.assertIsNone(fx.ledger()["authorization"])
        self.assertEqual(fx.authorize()["result"], P.PUBLISH_AUTHORIZED)

    def test_publish_target_is_explicit_and_github_only(self):
        """AC-01: without publish-target the authorization is refused; the configuration is a closed, github-only set (KB-272)."""
        fx = self.fixture(configure=False)
        fx.to_gate()
        exc = self.rejects(P.PUBLISH_TARGET_NOT_CONFIGURED, fx.authorize, "auth-x", remote="origin", targetBranch="main")
        self.assertEqual(exc.detail["field"], "publishTarget")
        cases = [("publishTarget.provider", dict(provider="gitlab")),
                 ("publishTarget.remoteAddress", dict(remoteAddress="relative/path.git")),
                 ("publishTarget.remoteAddress", dict(remoteAddress="https://user:secret@github.com/o/r.git")),
                 ("publishTarget.remoteAddress", dict(remoteAddress="file:///tmp/r.git")),
                 ("publishTarget.cli", dict(cli="gh")),
                 ("publishTarget.repositoryId", dict(repositoryId="0")),
                 ("publishTarget.targetBranch", dict(targetBranch="bad..name"))]
        for field, overrides in cases:
            with self.subTest(field=field):
                exc = self.rejects(P.PUBLISH_TARGET_REJECTED, fx.configure, **overrides)
                self.assertEqual(exc.detail["field"], field)
                self.assertNotIn("secret", json.dumps(exc.reason()))
        exc = self.rejects(P.PUBLISH_TARGET_REJECTED, fx.domain.transaction, fx.generation,
                           lambda s: __import__("domain.publish.configuration", fromlist=["x"]).set_target(s, fx.target(), ""))
        self.assertEqual(exc.detail["field"], "authorityRef")
        out = fx.configure(remoteAddress="git@github.com:synthetic/product-line.git")
        self.assertEqual(out["value"]["remoteAddress"], "ssh://git@github.com/synthetic/product-line")
        out = fx.configure()
        history = [h for h in fx.state()["configuration"]["history"] if h["field"] == "publishTarget"]
        self.assertEqual((len(history), history[-1]["revision"].isdigit(), history[-1]["authorityRef"]), (2, True, OWNER))
        self.assertEqual(fx.authorize()["result"], P.PUBLISH_AUTHORIZED)

    def test_accept_with_reservation_carries_the_binding(self):
        """AC-01: at the Validation escalation Accept With reservation must carry publishBinding in the same decision (KB-265, FR-26)."""
        fx = self.fixture(change_validation=True, budget=budget(validation=0))
        fx.to_validate()
        findings = {"R1-H1": "不阻断，记入发布说明"}
        fx.review_once(VF.SyntheticImplReviewer(("valid", "FAIL", dict(human=True))), "p1")
        fx.validate("dispose", "d1", decisionText="处置", findings=findings)
        fx.run_reviews(VF.SyntheticImplReviewer())
        fx.budget_decide("b1")
        self.assertEqual(fx.inst()["position"], "N-VALIDATE-ESCALATION-GATE")
        ruling_commits = [r["commit"] for r in fx.state()["tasks"][fx.task_id]["validateChange"]["rulings"]]
        self.assertEqual(len(ruling_commits), 1)
        exc = self.rejects(V.INPUT_INVALID, fx.validate, "decide", "g1", decision="Accept With reservation",
                           decisionText="带保留接受", reservation="保留一项")
        self.assertEqual(exc.detail["publishReason"]["field"], "publishBinding")
        binding, digest = fx.human_binding()
        exc = self.rejects(V.INPUT_INVALID, fx.validate, "decide", "g1", decision="Accept With reservation",
                           decisionText="带保留接受", reservation="保留一项", publishBinding=binding, contextDigest="1" * 64)
        self.assertEqual(exc.detail["publishReason"]["code"], P.CONTEXT_STALE)
        out = fx.validate("decide", "g2", decision="Accept With reservation", decisionText="带保留接受", reservation="保留一项",
                          publishBinding=binding, contextDigest=digest)
        self.assertEqual(out["result"], V.RESERVATION_ACCEPTED)
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH", states.ENTERED))
        fact = fx.inst()["facts"][out["decision"]["factId"]]
        bound = fact["payload"]["publishBinding"]
        self.assertEqual((fact["payload"]["edgeId"], fact["payload"]["decisionContext"]["verdict"]), ("E-V12", "FAIL"))
        self.assertEqual(bound["candidateCommit"], fx.task_head())
        self.assertEqual(bound["verifiedCandidateCommit"], fx.rounds()[-1]["candidateCommit"])
        self.assertEqual([g["commit"] for g in bound["governanceCommits"]], ruling_commits)
        self.assertEqual(fx.ledger()["authorization"]["edge"], "E-V12")
        self.assertEqual(self.permit(fx)["conclusion"], "ALLOW")
        fx.dispatch_publish()
        self.assertEqual(fx.run_publish(), [])
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)
        self.assertEqual(fx.remote_ref(), fx.task_head())
        self.assert_clean_platform(fx)

    # -- AC-02 --------------------------------------------------------------------------------------
    def test_push_and_pull_request_are_created_and_read_back(self):
        """AC-02: one non-forced ref pushed, one pull request with the bound title, body and operation trailer, then Published."""
        fx = self.fixture()
        fx.to_gate()
        local_before = git(fx.repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags")
        fx.publish()
        inst = fx.inst()
        self.assertEqual((inst["lifecycle"], inst["condition"]), (states.COMPLETED, states.RESULT_RECORDED))
        self.assertEqual(fx.state()["tasks"][fx.task_id]["terminal"]["kind"], "published")
        remote, local = fx.refs()
        self.assertEqual(remote, "refs/heads/%s %s" % (fx.task["branch"], fx.task_head()))
        self.assertNotIn("refs/harness", remote)
        self.assertEqual(local, local_before)
        pulls = fx.platform.pulls()
        self.assertEqual(len(pulls), 1)
        binding = fx.ledger()["authorization"]["binding"]
        operation = fx.ledger()["operation"]["id"]
        self.assertEqual((pulls[0]["head"]["sha"], pulls[0]["base"]["ref"], pulls[0]["title"]),
                         (fx.task_head(), "main", binding["pullRequest"]["title"]))
        self.assertTrue(pulls[0]["body"].startswith(binding["pullRequest"]["body"].rstrip("\n")))
        self.assertTrue(pulls[0]["body"].rstrip().endswith("<!-- harness-publish-operation: %s -->" % operation))
        result = fx.facts("publish")[-1]["payload"]
        self.assertEqual(result["classification"], "published")
        evidence = result["evidence"]
        self.assertEqual((evidence["remoteBefore"], evidence["remoteAfter"], evidence["push"]["attempted"]),
                         (None, fx.task_head(), True))
        self.assertEqual((evidence["pullRequest"]["action"], evidence["pullRequest"]["number"]), ("created", 1))
        self.assertEqual(evidence["program"]["version"], "synthetic-platform 1.0")
        text = json.dumps(evidence)
        for secret in ("token", "password", "Authorization", "HTTP "):
            self.assertNotIn(secret, text)
        reservation = inst["reservations"][self.execution(fx)["reservationId"]]
        self.assertEqual(reservation["status"], "settled")
        self.assertEqual([a["status"] for a in inst["attempts"] if a["purpose"] == "publish"], ["COMPLETED"])
        self.assert_clean_platform(fx)

    def test_existing_remote_commit_and_pull_request_are_identified(self):
        """AC-02: the remote already at the candidate is not pushed again; the one open same-source pull request is identified."""
        fx = self.fixture()
        fx.to_gate()
        fx.authorize()
        git(fx.repo, "push", "-q", str(fx.bare), "%s:refs/heads/%s" % (fx.task_head(), fx.task["branch"]))
        fx.platform.edit(lambda s: s["pulls"].append(dict(
            number=7, html_url="https://synthetic.invalid/pull/7", state="open", merged_at=None, title="existing", body="by hand",
            head=dict(ref=fx.task["branch"], sha=fx.task_head(), repo=dict(full_name=PF.REPOSITORY)), base=dict(ref="main"))))
        fx.dispatch_publish()
        self.assertEqual(fx.run_publish(), [])
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)
        evidence = fx.facts("publish")[-1]["payload"]["evidence"]
        self.assertEqual((evidence["push"]["attempted"], evidence["push"]["alreadyPushed"]), (False, True))
        self.assertEqual((evidence["pullRequest"]["action"], evidence["pullRequest"]["number"],
                          evidence["pullRequest"]["markerPresent"]), ("identified", 7, False))
        self.assertEqual([r["method"] for r in fx.platform.requests() if r["method"] != "GET"], [])
        self.assertEqual(len(fx.platform.pulls()), 1)

    def test_push_permit_other_than_allow_calls_nothing(self):
        """AC-02: a DENY or NOT_DETERMINABLE push permit is recorded, keeps ENTERED and makes no remote or platform call."""
        fx = self.fixture()
        fx.to_gate()
        fx.authorize()
        saved = copy.deepcopy(fx.ledger()["authorization"])

        def tamper(s):  # SYNTHETIC (test only): the ledger binding no longer equals the decision fact's binding
            s["tasks"][fx.task_id]["publish"]["authorization"]["binding"]["targetBranch"] = "release"
        fx.domain.transaction(fx.generation, tamper)
        out = fx.dispatch_publish("pub-deny")
        self.assertEqual((out["result"], out["conclusion"]), (P.PUSH_NOT_PERMITTED, "DENY"))
        items = {i["item"]: i for i in out["decision"]["items"]}
        self.assertEqual(items["push-permit"]["reason"]["code"], "PUSH_BINDING_MISMATCH")
        self.assertIn(out["factId"], fx.inst()["facts"])
        fx.domain.transaction(fx.generation, lambda s: s["tasks"][fx.task_id]["publish"].update(authorization=copy.deepcopy(saved)))

        def undetermined(s):  # no Policy inputs: the Policy Gate cannot evaluate (both entries always pass them)
            inst = s["tasks"][fx.task_id]["workflowInstance"]
            return publish_commands.apply(s, fx.domain.topology, "publish-dispatch",
                                          dict(taskId=fx.task_id, commandId="pub-nd", authorityRef=OWNER),
                                          revision=s["revision"], context=fx.domain.definition_context(), inputs=None)
        out = fx.domain.transaction(fx.generation, undetermined)
        self.assertEqual(out["result"], P.PUSH_PERMIT_NOT_DETERMINABLE)
        self.assertEqual(P.exit_code(out["result"]), 2)
        self.assertEqual((fx.inst()["condition"], fx.ledger()["executions"], fx.remote_ref()), (states.ENTERED, [], None))
        self.assertEqual(fx.platform.requests(), [])
        self.assertEqual(fx.dispatch_publish()["result"], P.PUBLISH_DISPATCHED)
        self.assertEqual(fx.run_publish(), [])
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)

    # -- AC-03 --------------------------------------------------------------------------------------
    def test_not_happened_then_human_authorised_reconcile(self):
        """AC-03 AC-02: a rejected push is not-happened; query, then a single-use Human reconcile under the same operation; a new platform program version is no refusal."""
        fx = self.fixture()
        fx.to_gate()
        fx.set_remote_mode("reject")
        fx.publish()
        inst, first = fx.inst(), self.execution(fx)
        self.assertEqual((first["outcome"]["classification"], first["outcome"]["failureCode"]), ("not-happened", "push-rejected"))
        self.assertEqual((inst["lifecycle"], inst["condition"]), (states.ACTIVE, states.RECOVERY_REQUIRED))
        self.assertEqual([a["status"] for a in inst["attempts"] if a["purpose"] == "publish"], ["EXECUTION_FAILED"])
        self.assertEqual(inst["reservations"][first["reservationId"]]["status"], "settled")
        self.assertIsNone(fx.remote_ref())
        self.rejects(W.RECOVERY_REQUIRED_BLOCKS_PROGRESSION, fx.dispatch_publish, "pub-2")
        self.assertEqual(publish_projection.legal(fx.state(), fx.task_id), {publish_projection.QUERY})
        observed = fx.query("q1")
        self.assertEqual(fx.ledger()["observations"][-1]["outcome"]["classification"], "absent")
        self.assertEqual(fx.inst()["recovery"]["assessments"][fx.inst()["recovery"]["current"]]["assessment"],
                         "RECONCILIATION_REQUIRED")
        self.assertEqual(observed["result"], P.QUERY_DISPATCHED)
        self.rejects(W.RECOVERY_AUTHORIZATION_MISSING, fx.run, "publish-reconcile", commandId="r0", humanAuthorization=None)
        self.rejects(P.BINDING_MISMATCH, fx.run, "publish-reconcile", commandId="r0",
                     humanAuthorization=fx.human_authorization("a0", scope="publish-operation:other"))
        first_auth = fx.human_authorization("a1")
        fx.reconcile("r1", first_auth)
        second = self.execution(fx)
        self.assertEqual((second["kind"], second["outcome"]["classification"]), ("reconcile", "not-happened"))
        self.assertEqual(fx.inst()["recovery"]["assessments"][fx.inst()["recovery"]["current"]]["assessment"],
                         "RECONCILIATION_REQUIRED")
        reused = fx.human_authorization("a1")
        self.rejects(W.RECOVERY_AUTHORIZATION_MISSING, fx.run, "publish-reconcile", commandId="r2", humanAuthorization=reused)
        fx.set_remote_mode("")
        fx.platform.upgrade("synthetic-platform 2.0")
        fx.reconcile("r3", fx.human_authorization("a3"))
        inst = fx.inst()
        self.assertEqual((inst["lifecycle"], inst["condition"]), (states.COMPLETED, states.RESULT_RECORDED))
        executions = fx.ledger()["executions"]
        self.assertEqual({e["executionId"].rsplit(":", 1)[0] for e in executions}, {fx.ledger()["operation"]["id"]})
        versions = [e["outcome"]["evidence"]["program"]["version"] for e in executions]
        digests = {e["outcome"]["evidence"]["program"]["sha256"] for e in executions}
        self.assertEqual((versions[0], versions[-1], len(digests)), ("synthetic-platform 1.0", "synthetic-platform 2.0", 2))
        self.assertEqual(len([a for a in inst["attempts"] if a["purpose"] == "publish"]), 1)
        self.assertEqual(fx.remote_ref(), fx.task_head())
        self.assertEqual(len(fx.platform.pulls()), 1)
        self.assert_clean_platform(fx)

    def test_partial_is_remedied_without_a_second_push(self):
        """AC-03: push landed but the pull request was definitively refused: partial; the reconcile only creates the pull request."""
        fx = self.fixture()
        fx.to_gate()
        fx.platform.fault("POST", "http", suffix="/pulls", status=422)
        fx.publish()
        first = self.execution(fx)
        self.assertEqual((first["outcome"]["classification"], first["outcome"]["failureCode"]), ("partial", "pull-request-rejected"))
        self.assertEqual(fx.remote_ref(), fx.task_head())
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
        fx.query("q1")
        self.assertEqual(fx.ledger()["observations"][-1]["outcome"]["classification"], "partial")
        fx.reconcile("r1", fx.human_authorization("a1"))
        second = self.execution(fx)
        self.assertEqual((second["outcome"]["evidence"]["push"]["attempted"], second["outcome"]["evidence"]["pullRequest"]["action"]),
                         (False, "created"))
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)
        self.assertEqual(len(fx.platform.pulls()), 1)

    def test_unknown_push_keeps_the_reservation_and_only_queries(self):
        """AC-03: a push that times out is unknown: INDETERMINATE, reservation held, no new dispatch; queries decide the next step."""
        fx = self.fixture()
        fx.to_gate()
        fx.set_remote_mode("stall")
        with mock.patch.object(publish_executor, "PUSH_TIMEOUT", 1):
            fx.publish()
        inst, first = fx.inst(), self.execution(fx)
        self.assertEqual((first["outcome"]["classification"], first["outcome"]["failureCode"]), ("unknown", "push-timeout"))
        self.assertEqual([a["status"] for a in inst["attempts"] if a["purpose"] == "publish"], ["INDETERMINATE"])
        self.assertEqual(inst["reservations"][first["reservationId"]]["status"], "held")
        self.assertEqual(fx.state()["executionDescriptors"][first["executionId"]]["status"], "indeterminate")
        self.rejects(W.RECOVERY_REQUIRED_BLOCKS_PROGRESSION, fx.dispatch_publish, "runtime:new-operation-id")
        self.assertNotIn(publish_projection.DISPATCH, publish_projection.legal(fx.state(), fx.task_id))
        time.sleep(5)  # the stalled remote hook finishes (it refuses the push)
        fx.platform.fault("GET", "transport", suffix="/pulls")
        fx.query("q1")
        current = fx.inst()["recovery"]["assessments"][fx.inst()["recovery"]["current"]]
        self.assertEqual((fx.ledger()["observations"][-1]["outcome"]["classification"], current["assessment"]),
                         ("unknown", "INDETERMINATE"))
        self.assertEqual(fx.inst()["reservations"][first["reservationId"]]["status"], "held")
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
        fx.set_remote_mode("")
        fx.query("q2")
        current = fx.inst()["recovery"]["assessments"][fx.inst()["recovery"]["current"]]
        self.assertEqual((fx.ledger()["observations"][-1]["outcome"]["classification"], current["assessment"]),
                         ("absent", "RECONCILIATION_REQUIRED"))
        self.assertEqual(fx.inst()["reservations"][first["reservationId"]]["status"], "settled")
        fx.reconcile("r1", fx.human_authorization("a1"))
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)

    def test_confirmed_by_query_restores_without_new_effects(self):
        """AC-03: the create answer is lost and the re-listing fails (unknown); a later query confirms and finalises (D-05 S11)."""
        fx = self.fixture()
        fx.to_gate()
        fx.platform.fault("POST", "lost", suffix="/pulls")
        fx.platform.fault("GET", "transport", suffix="/pulls", skip=2)
        fx.publish()
        first = self.execution(fx)
        self.assertEqual((first["outcome"]["classification"], first["outcome"]["failureCode"]),
                         ("unknown", "pull-request-create-unknown"))
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
        before = len(fx.platform.requests())
        fx.query("q1")
        inst = fx.inst()
        self.assertEqual((inst["lifecycle"], inst["condition"]), (states.COMPLETED, states.RESULT_RECORDED))
        after = fx.platform.requests()[before:]
        self.assertEqual({r["method"] for r in after}, {"GET"})
        self.assertEqual(len(fx.platform.pulls()), 1)
        self.assertEqual(len([a for a in inst["attempts"] if a["purpose"] == "publish"]), 1)
        actions = [a["action"] for a in inst["recovery"].get("actions", [])]
        self.assertEqual(actions, ["RESTORE_PUBLISH_FINALIZATION"])
        self.assertEqual(inst["reservations"][first["reservationId"]]["status"], "settled")

    def test_lost_create_answer_is_identified_by_the_same_operation(self):
        """AC-03: a create whose answer is lost is followed by a listing for the same operation, never a second create."""
        fx = self.fixture()
        fx.to_gate()
        fx.platform.fault("POST", "lost", suffix="/pulls")
        fx.publish()
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)
        evidence = fx.facts("publish")[-1]["payload"]["evidence"]
        self.assertEqual((evidence["pullRequest"]["action"], evidence["pullRequest"]["markerPresent"]),
                         ("created-after-uncertain-answer", True))
        self.assertEqual(len([r for r in fx.platform.requests() if r["method"] == "POST"]), 1)
        self.assertEqual(len(fx.platform.pulls()), 1)

    def test_entry_process_death_is_resolved_by_querying_only(self):
        """AC-03: the entry dies during the platform call; the restarted entry only queries the same operation, never re-executes."""
        fx = self.fixture()
        fx.to_gate()
        fx.authorize()
        fx.dispatch_publish()
        fx.platform.fault("POST", "hang", suffix="/pulls", seconds=60)
        env = dict(os.environ, **PF.GIT_ENV)
        child = subprocess.Popen([sys.executable, "-B", str(APP / "hp.py"), "publish", "run", "--repository", str(fx.repo),
                                  "--task-id", fx.task_id], cwd=APP, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not any(r["method"] == "POST" for r in fx.platform.requests()):
            time.sleep(0.2)
        self.assertTrue(any(r["method"] == "POST" for r in fx.platform.requests()), child.stderr.read1() if child.poll() else "")
        os.killpg(child.pid, signal.SIGKILL)
        child.communicate(timeout=30)
        fx.generation = fx.domain.bind_entry()
        inst, first = fx.inst(), self.execution(fx)
        self.assertEqual((inst["condition"], first["status"]), (states.EXECUTING, "running"))
        self.assertEqual(fx.state()["executionDescriptors"][first["executionId"]]["status"], "running")
        self.assertEqual(inst["reservations"][first["reservationId"]]["status"], "held")
        pushes = fx.remote_ref()
        before = len(fx.platform.requests())
        self.assertEqual(fx.run_publish(), [])
        first = self.execution(fx)
        self.assertEqual((first["outcome"]["via"], first["outcome"]["classification"]), ("query", "partial"))
        self.assertEqual({r["method"] for r in fx.platform.requests()[before:]}, {"GET"})
        self.assertEqual((fx.remote_ref(), fx.inst()["condition"]), (pushes, states.RECOVERY_REQUIRED))
        fx.query("q1")
        fx.reconcile("r1", fx.human_authorization("a1"))
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)
        self.assertEqual(len(fx.platform.pulls()), 1)

    # -- AC-04 --------------------------------------------------------------------------------------
    def test_uncontrolled_changes_stop_without_force_or_rollback(self):
        """AC-04: remote diverged, branch moved, address changed, closed or duplicate pull request, platform id mismatch: stop."""
        def diverged(fx):
            scratch, commit = fx.third_party_commit()
            git(scratch, "push", "-q", str(fx.bare), "%s:refs/heads/%s" % (commit, fx.task["branch"]))
            return "remote-branch-diverged"

        def moved(fx):
            (fx.worktree / "late.txt").write_text("late\n")
            git(fx.worktree, "add", "late.txt")
            git(fx.worktree, "commit", "-q", "-m", "late change after the authorization")
            return "local-branch-moved"

        def address(fx):
            git(fx.root, "init", "-q", "--bare", str(fx.root / "other.git"))
            git(fx.repo, "remote", "set-url", "--push", "origin", str(fx.root / "other.git"))
            return "remote-address-changed"

        def pull(state_name, count=1):
            def change(fx):
                def add(s):
                    for n in range(count):
                        s["pulls"].append(dict(number=20 + n, html_url="x", state=state_name, merged_at=None, title="t", body="b",
                                               head=dict(ref=fx.task["branch"], sha="0" * 40, repo=dict(full_name=PF.REPOSITORY)),
                                               base=dict(ref="main")))
                fx.platform.edit(add)
                return "pull-request-closed" if state_name == "closed" else "pull-request-multiple"
            return change

        def repository_id(fx):
            fx.platform.edit(lambda s: s["repository"].update(id=999))
            return "platform-repository-mismatch"

        for name, change in (("diverged", diverged), ("moved", moved), ("address", address), ("closed", pull("closed")),
                             ("multiple", pull("open", 2)), ("repository", repository_id)):
            with self.subTest(case=name):
                fx = self.fixture("fx-" + name)
                fx.to_gate()
                fx.authorize()
                code = change(fx)
                refs_before = fx.refs()
                pulls_before = copy.deepcopy(fx.platform.pulls())
                fx.dispatch_publish()
                self.assertEqual(fx.run_publish(), [])
                done = self.execution(fx)
                self.assertEqual((done["outcome"]["classification"], done["outcome"]["failureCode"]), ("uncontrolled-change", code))
                self.assertEqual(fx.refs(), refs_before)
                self.assertEqual(fx.platform.pulls(), pulls_before)
                self.assertEqual([r for r in fx.platform.requests() if r["method"] != "GET"], [])
                inst = fx.inst()
                self.assertEqual(inst["condition"], states.RECOVERY_REQUIRED)
                self.assertEqual(inst["reservations"][done["reservationId"]]["status"], "held")
                self.assertEqual(fx.facts("publish")[-1]["payload"]["evidence"]["stop"]["code"], code)
                if name == "diverged":
                    fx.query("q1")
                    self.assertEqual(fx.ledger()["observations"][-1]["outcome"]["classification"], "uncontrolled-change")
                    self.assertIsNone(fx.inst()["recovery"]["current"])
                    closed = fx.run("close", commandId="c1", reasonCategory="human-initiated")
                    self.assertEqual((closed["result"], fx.inst()["lifecycle"]), (W.FINALIZED, states.CLOSED))
                    self.assertTrue(fx.ledger()["executions"] and fx.facts("publish"))

    # -- AC-05 --------------------------------------------------------------------------------------
    def test_no_merge_close_or_delete_and_publish_authorization_cannot_be_skipped(self):
        """AC-05: no merge/close/delete; both Review switches off still stop at the gate; generic walks are narrowed; Published is final."""
        for name in ("merge", "merge_pull_request", "close", "close_pull_request", "update_pull_request", "edit_pull_request",
                     "delete_branch", "delete"):
            self.assertFalse(hasattr(GitHubPlatform, name), name)
        fx = self.fixture()
        fx.to_validate()
        self.assertEqual((fx.inst()["reviewConfiguration"]["definitionReview"], fx.inst()["reviewConfiguration"]["changeValidation"]),
                         (False, False))
        fx.validate("configure", "cfg-1")
        self.assertEqual((fx.inst()["position"], fx.inst()["condition"]), ("N-PUBLISH-AUTH-GATE", states.AWAITING_HUMAN_ACTION))
        for name, payload in (("advance", dict(edgeId="E-V06")), ("condition", dict(condition=states.RESULT_RECORDED)),
                              ("fact", dict(fact=dict(factId="forged", kind="human-decision", purpose="gate-decision",
                                                      authorityRef=OWNER,
                                                      payload=dict(decision="Publish authorization", edgeId="E-V06"))))):
            with self.subTest(node="gate", command=name):
                exc = self.rejects(NARROWED, fx.run, name, commandId="g-" + name, **payload)
                self.assertEqual(exc.detail["reasonCode"], "GENERIC_COMMAND_NARROWED")
        fx.authorize()
        forged = dict(fact=dict(factId="p1", kind="execution-result", purpose="publish", authorityRef=OWNER))
        for name, payload in (("fact", forged), ("condition", dict(condition=states.EXECUTING)),
                              ("publish-finalize", dict(triggers=["p1"], purpose="publish")),
                              ("recover-assess", dict(assessmentId="as1", assessment="RESULT_CONFIRMED")),
                              ("recover", dict(action="RESTORE_PUBLISH_FINALIZATION")), ("attempt-open", dict(attemptId="x")),
                              ("reserve", dict(reservationId="x"))):
            with self.subTest(node="publish", command=name):
                exc = self.rejects(NARROWED, fx.run, name, commandId="n-" + name, **payload)
                self.assertEqual(exc.detail["reasonCode"], "GENERIC_COMMAND_NARROWED")
        fx.dispatch_publish()
        self.assertEqual(fx.run_publish(), [])
        self.assertEqual(fx.inst()["lifecycle"], states.COMPLETED)
        self.rejects(W.PUBLISHED_NOT_CLOSEABLE, fx.run, "close", commandId="c1", reasonCategory="human-initiated")
        terminal = copy.deepcopy(fx.state()["tasks"][fx.task_id]["terminal"])
        count = in_flight(fx.state(), fx.domain.repo, fx.head)["count"]
        fx.platform.edit(lambda s: s["pulls"][0].update(state="closed", merged_at="2026-09-23T00:00:00Z"))
        self.assertEqual((fx.state()["tasks"][fx.task_id]["terminal"], in_flight(fx.state(), fx.domain.repo, fx.head)["count"]),
                         (terminal, count))
        self.assertEqual(fx.refs()[0], "refs/heads/%s %s" % (fx.task["branch"], fx.task_head()))
        self.assertEqual(fx.task_head(), git(fx.repo, "rev-parse", "refs/heads/" + fx.task["branch"]))
        self.assert_clean_platform(fx)

    def test_platform_adapter_allows_four_endpoints_and_classifies_without_echo(self):
        """AC-05 AC-02: the adapter refuses any other endpoint before a call and classifies failures without echoing raw output."""
        target = dict(provider="github", host="github.com", repository=PF.REPOSITORY, repositoryId=PF.REPOSITORY_ID,
                      cli="/nonexistent/synthetic-platform")
        calls = []

        class Answer:
            def __init__(self, code, out=b"", err=b""):
                self.returncode, self.stdout, self.stderr = code, out, err

        def runner(args, **kw):
            calls.append(args)
            path = args[args.index("--method") + 2]
            if path.endswith("/pulls/1"):
                return Answer(1, err=b"HTTP 403: token=ghp_secret denied")
            if path.endswith("/pulls/2"):
                raise subprocess.TimeoutExpired(args, 1)
            if path.endswith("/pulls/3"):
                return Answer(0, out=b"<html>")
            return Answer(1, err=b"HTTP 422: Validation Failed")
        platform = GitHubPlatform(target, runner=runner)
        for method, path in (("DELETE", "/repos/%s/git/refs/heads/x" % PF.REPOSITORY), ("PUT", "/repos/%s/pulls/1/merge" % PF.REPOSITORY),
                             ("PATCH", "/repos/%s/pulls/1" % PF.REPOSITORY), ("GET", "/repos/other/repo")):
            with self.assertRaises(PlatformError) as caught:
                platform.api(method, path)
            self.assertEqual(caught.exception.status, "endpoint-not-allowed")
        self.assertEqual(calls, [])
        for number, kind in ((1, "forbidden"), (2, "transport"), (3, "output-invalid")):
            with self.assertRaises(PlatformError) as caught:
                platform.pull_request(number)
            self.assertEqual(caught.exception.kind, kind)
            self.assertNotIn("secret", str(caught.exception) + json.dumps(caught.exception.detail()))
        with self.assertRaises(PlatformError) as caught:
            platform.create_pull_request("harness/x", "main", "t", "b")
        self.assertEqual((caught.exception.kind, caught.exception.definite), ("invalid", True))
        self.assertTrue(all(a[0] == target["cli"] and a[1] == "api" for a in calls))

    # -- AC-06 --------------------------------------------------------------------------------------
    def test_published_releases_capacity_and_satisfies_dependencies(self):
        """AC-06: with limit 1 a new acceptance waits for Published; recovery does not release; dependants become satisfiable."""
        fx = self.fixture()
        fx.to_gate()

        def request(request_id, task_id):
            return dict(requestId=request_id, repository=str(fx.repo), taskType="feature", taskId=task_id, baseRef="main",
                        worktreeRoot=str(fx.root / "worktrees"), authorityRef=OWNER)

        def refused(code, request_id, task_id, dry_run=False):
            with self.assertRaises(Rejection) as caught:
                accept_task(fx.domain.store, request(request_id, task_id), dry_run=dry_run)
            self.assertEqual(caught.exception.code, code)
        refused(A.CONCURRENCY_LIMIT_REACHED, "req-2", "gov-t0")
        refused(A.DEPENDENCY_UNMET, "req-3", "feature-t1", dry_run=True)
        fx.set_remote_mode("reject")
        fx.publish()
        self.assertEqual(fx.inst()["condition"], states.RECOVERY_REQUIRED)
        refused(A.CONCURRENCY_LIMIT_REACHED, "req-2", "gov-t0")
        fx.set_remote_mode("")
        fx.query("q1")
        fx.reconcile("r1", fx.human_authorization("a1"))
        self.assertEqual(fx.state()["tasks"][fx.task_id]["terminal"]["kind"], "published")
        ready = accept_task(fx.domain.store, request("req-3", "feature-t1"), dry_run=True)
        self.assertEqual(ready["result"], "READY")
        self.assertEqual(accept_task(fx.domain.store, request("req-2", "gov-t0"))["result"], A.ACCEPTED)

    # -- AC-07 --------------------------------------------------------------------------------------
    def test_real_serve_stdio_matches_the_cli(self):
        """AC-07: through the product Runtime, authorize, dispatch, query and reconcile match the CLI twin; idempotency, tombstone, fences."""
        from publish_stdio import PublishHost, launch_files
        fx, twin = self.fixture("stdio"), self.fixture("cli")
        for f in (fx, twin):
            f.to_gate()
            f.set_remote_mode("reject")
        start_fx, start_twin = len(fx.edges()), len(twin.edges())
        self.assertEqual(publish_projection.legal(fx.state(), fx.task_id), publish_projection.legal(twin.state(), twin.task_id))
        # CLI twin
        twin.publish()
        twin.query("q1")
        twin.set_remote_mode("")
        twin.reconcile("r1", twin.human_authorization("a1"))
        # Runtime
        case = self.directory / "stdio-case"
        case.mkdir()
        launch_files(case, fx)
        host = PublishHost(case, dict(PF.GIT_ENV), output=case / "frames.jsonl")
        try:
            host.initialize()
            host.activate()
            version = lambda: fx.inst()["runtimeVersion"]
            binding, digest = fx.human_binding()
            accepted, auth_p = host.invoke(publish_projection.AUTHORIZE, dict(taskId=fx.task_id, expectedRuntimeVersion=version(),
                                                                              decisionText="发布", contextDigest=digest,
                                                                              publishBinding=binding))
            op = host.wait_operation(auth_p["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "PUBLISH-AUTHORIZED"))
            replay = host.call("runtime.action.invoke", auth_p)
            self.assertEqual(replay["operationId"], auth_p["operationId"])
            conflict = dict(auth_p, payload=dict(auth_p["payload"], decisionText="另一句"))
            from host_driver import request_digest
            conflict["requestDigest"] = request_digest("runtime.action.invoke", conflict)
            host.call("runtime.action.invoke", conflict, error="IDEMPOTENCY_CONFLICT")
            accepted, p = host.invoke(publish_projection.DISPATCH, dict(taskId=fx.task_id, expectedRuntimeVersion=version()))
            op = host.wait_operation(p["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("failed", "EXECUTION-SETTLED"))
            host.invoke(publish_projection.DISPATCH, dict(taskId=fx.task_id, expectedRuntimeVersion=version()),
                        error="PRECONDITION_CONFLICT")

            def tombstone(s):  # SYNTHETIC retention (test only), the shape feature-t16's tests use
                s["operations"][p["operationId"]]["tombstone"] = True
            fx.domain.store.transaction(None, tombstone)
            host.call("runtime.operation.get", dict(scopeRef=host.template["scopeRef"], operationId=p["operationId"]),
                      error="RESULT_UNKNOWN")
            accepted, q = host.invoke(publish_projection.QUERY, dict(taskId=fx.task_id, expectedRuntimeVersion=version()))
            op = host.wait_operation(q["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "PUBLISH-OBSERVED"))
            fx.set_remote_mode("")
            accepted, r = host.invoke(publish_projection.RECONCILE, dict(taskId=fx.task_id, expectedRuntimeVersion=version(),
                                                                         assessmentId=fx.inst()["recovery"]["current"]))
            op = host.wait_operation(r["operationId"])
            self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "PUBLISHED"))
        finally:
            host.close()
        self.rejects(W.STALE_CONTROL_GENERATION, fx.run, "publish-dispatch", commandId="late")
        for f in (fx, twin):
            self.assertEqual((f.inst()["lifecycle"], f.inst()["condition"]), (states.COMPLETED, states.RESULT_RECORDED))
            self.assertEqual(f.remote_ref(), f.task_head())
        self.assertEqual(fx.edges()[start_fx:], twin.edges()[start_twin:])
        shape = lambda f: [(e["kind"], e["outcome"]["classification"]) for e in f.ledger()["executions"]]
        self.assertEqual(shape(fx), shape(twin))
        self.assertEqual([o["outcome"]["classification"] for o in fx.ledger()["observations"]],
                         [o["outcome"]["classification"] for o in twin.ledger()["observations"]])

    # -- AC-08 --------------------------------------------------------------------------------------
    def test_j03_minimal_path_from_acceptance_to_published(self):
        """AC-08: the minimal path from acceptance to Published through the production entries; the publish segment via hp.py."""
        fx = self.fixture("j03", configure=False)
        before = in_flight(fx.state(), fx.domain.repo, fx.head)["count"]
        fx.to_validate()
        fx.validate("configure", "cfg-1")
        env = dict(os.environ, **PF.GIT_ENV)

        def cli(*args):
            proc = subprocess.run([sys.executable, "-B", str(APP / "hp.py"), *args], cwd=APP, env=env, capture_output=True, text=True)
            return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr
        code, out, err = cli("config", "set", "publish-target", json.dumps(fx.target()), "--repository", str(fx.repo),
                             "--authority-ref", OWNER)
        self.assertEqual((code, out["result"]), (0, P.PUBLISH_TARGET_CONFIGURED), err)
        code, out, err = cli("publish", "context", "--repository", str(fx.repo), "--task-id", fx.task_id)
        self.assertEqual((code, out["result"]), (0, P.PUBLISH_CONTEXT_READ), err)
        proposed = out["publishBinding"]
        body = self.directory / "body.md"
        body.write_text(proposed["pullRequest"]["body"], encoding="utf-8")
        code, out, err = cli("publish", "authorize", "--repository", str(fx.repo), "--task-id", fx.task_id, "--command-id", "auth-1",
                             "--authority-ref", OWNER, "--decision-text", "发布 feature-t0",
                             "--candidate-commit", proposed["candidateCommit"], "--source-branch", proposed["sourceBranch"],
                             "--remote", proposed["remote"], "--target-branch", proposed["targetBranch"],
                             "--title", proposed["pullRequest"]["title"], "--body-file", str(body),
                             "--context-digest", out["contextDigest"])
        self.assertEqual((code, out["result"]), (0, P.PUBLISH_AUTHORIZED), err)
        code, out, err = cli("publish", "dispatch", "--repository", str(fx.repo), "--task-id", fx.task_id, "--command-id", "pub-1",
                             "--authority-ref", OWNER)
        self.assertEqual((code, out["result"]), (0, P.PUBLISH_DISPATCHED), err)
        code, out, err = cli("publish", "run", "--repository", str(fx.repo), "--task-id", fx.task_id)
        self.assertEqual((code, out["lifecycle"], out["terminal"]["kind"]), (0, states.COMPLETED, "published"), err)
        code, out, err = cli("publish", "status", "--repository", str(fx.repo), "--task-id", fx.task_id)
        self.assertEqual((code, out["legal"]), (0, []), err)
        fx.generation = fx.domain.bind_entry()
        edges = fx.edges()
        for edge in ("E-D17", "E-V02", "E-V06"):
            self.assertIn(edge, edges)
        self.assertEqual(edges[-1], "E-V06")
        self.assertEqual(fx.remote_ref(), fx.task_head())
        self.assertEqual(len(fx.platform.pulls()), 1)
        after = in_flight(fx.state(), fx.domain.repo, fx.head)["count"]
        self.assertEqual((before, after), (1, 0))
        self.assert_clean_platform(fx)


if __name__ == "__main__":
    unittest.main()
