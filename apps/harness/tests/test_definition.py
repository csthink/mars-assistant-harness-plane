"""feature-t3 Define Task / Review Definition tests on synthetic product lines. Docstrings carry AC tags.

Reviewer output, Host and the feature-t6 authorization callback are explicitly synthetic test doubles
(definition_fixture); the structure gate, rulings, progression, ports' preflight and git effects are the
production code. No real model, no remote operation, no write outside the temporary directory.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import definition_fixture as F
from domain.definition import candidate as candidate_module, gate, results as R
from domain.definition.results import DefinitionRejection
from domain.workflow import results as W, states
from domain.workflow.results import WorkflowRejection
from product_line import git, write
from runtime.executions import Environment, run_pending

HP = Path(__file__).resolve().parents[3]
APP = Path(__file__).resolve().parents[1]
OWNER = F.OWNER


class DefinitionCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("t3-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=False)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t3-tests-")
            self.directory = Path(self.temp.name)

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    # -- helpers ---------------------------------------------------------------------------------
    def fixture(self, **kw):
        self.fx = F.create(self.directory / "case", **kw)
        self.domain = F.TestHarnessDomain(self.fx["repo"], entry="cli")
        self.generation = self.domain.bind_entry()
        self.reviewer = F.SyntheticReviewer()
        self.calls = []
        self.authorizer = F.synthetic_authorizer(calls=self.calls)
        return self.fx

    def facts(self):
        return self.domain.status("feature-t0")["tasks"][0]

    def definition(self):
        return self.domain.definition_status("feature-t0")

    def cmd(self, name, **payload):
        payload.setdefault("taskId", "feature-t0")
        payload.setdefault("authorityRef", OWNER)
        return self.domain.run_definition(name, payload, generation=self.generation)

    def refuse(self, code, name, **payload):
        with self.assertRaises((DefinitionRejection, WorkflowRejection)) as ctx:
            self.cmd(name, **payload)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception.reason()))
        return ctx.exception

    def execute(self):
        env = Environment("cli", self.domain, self.generation, repository_root=str(self.fx["repo"]))
        return run_pending(self.domain, env, F.executors(self.reviewer, self.authorizer))

    def commit(self, text=None, raw=None, message="synthetic candidate"):
        return F.commit_candidate(self.fx["worktree"], text or F.definition_text(), raw=raw, message=message)

    def submit(self, commit=None, cid="s1", **kw):
        return self.cmd("submit", commandId=cid, commit=commit or self.commit(), author=F.author(self.fx["head"]), **kw)

    def unchanged(self, before):
        after = self.facts()
        self.assertEqual((after["position"], after["condition"], after["runtimeVersion"]),
                         (before["position"], before["condition"], before["runtimeVersion"]))

    # -- AC-01 -----------------------------------------------------------------------------------
    def test_valid_candidate_is_recorded_from_the_commit_and_routed(self):
        """AC-01: a conforming candidate is recorded by commit identity and reaches Review Definition Enabled?."""
        self.fixture()
        text = F.definition_text()
        commit = self.commit(text)
        outcome = self.submit(commit)
        self.assertEqual(outcome["result"], R.CANDIDATE_RECORDED)
        candidate = outcome["candidate"]
        self.assertEqual((candidate["commit"], candidate["path"], candidate["bytes"], candidate["sha256"]),
                         (commit, "tasks/feature-t0/feature-t0.md", len(text.encode()), candidate_module.sha256(text.encode())))
        self.assertEqual(candidate["author"]["evidence"][0]["path"], F.EVIDENCE)
        commits = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]["commits"]
        self.assertIn(("E-D01", "N-DEF-CANDIDATE"), [(c["selectedEdge"], c["nextSnapshot"]["position"]) for c in commits])
        self.assertIn(("E-D02", "N-DEF-REVIEW-CONFIG"), [(c["selectedEdge"], c["nextSnapshot"]["position"]) for c in commits])
        # A later change in the worktree does not move the recorded identity.
        write(self.fx["worktree"], "tasks/feature-t0/feature-t0.md", text + "\nedited after submission\n")
        self.assertEqual(self.definition()["candidates"][0]["sha256"], candidate["sha256"])
        self.assertEqual(self.reviewer.calls, 0)

    def test_structure_gate_and_identity_chain_rejections_are_distinguishable(self):
        """AC-01: each broken candidate is refused with a distinguishable reason, no state change, no provider call."""
        self.fixture()
        base = self.fx["head"]
        before = self.facts()
        swapped = F.definition_text().replace("## Goal\n\nSynthetic goal.\n\n## Goal Conditions\n\n- Synthetic condition.",
                                              "## Goal Conditions\n\n- Synthetic condition.\n\n## Goal\n\nSynthetic goal.")
        cases = [
            ("missing-h2", dict(text=F.definition_text(drop="Goal")), R.TEMPLATE_STRUCTURE_INVALID),
            ("duplicate-h2", dict(text=F.definition_text(duplicate="Goal")), R.TEMPLATE_STRUCTURE_INVALID),
            ("misordered-h2", dict(text=swapped), R.TEMPLATE_STRUCTURE_INVALID),
            ("guide-left", dict(text=F.definition_text(guide=True)), R.TEMPLATE_STRUCTURE_INVALID),
            ("identity-field", dict(text=F.definition_text(subject="feature-t9-task")), R.TEMPLATE_STRUCTURE_INVALID),
            ("anchor-revision", dict(text=F.definition_text(revision=2)), R.SOURCE_ANCHOR_MISMATCH),
            ("non-utf8", dict(raw=b"\xff\xfe not utf-8\n"), R.TEMPLATE_STRUCTURE_INVALID),
        ]
        seen = {}
        for n, (name, content, code) in enumerate(cases):
            commit = self.commit(content.get("text"), raw=content.get("raw"), message=name)
            error = self.refuse(code, "submit", commandId="bad-%d" % n, commit=commit, author=F.author(base))
            seen[name] = error.reason()
            self.unchanged(before)
        self.assertEqual(seen["non-utf8"]["validatorState"], "NOT_CHECKED")
        self.assertIn("headings", {c["check"] for c in seen["missing-h2"]["checks"]})
        self.assertIn("ids", {c["check"] for c in seen["identity-field"]["checks"]})
        self.assertEqual(seen["anchor-revision"]["anchorMilestonesRevision"], 1)
        # The commit carries no Definition file.
        self.refuse(R.CANDIDATE_NOT_IN_COMMIT, "submit", commandId="bad-nofile", commit=base, author=F.author(base))
        # A commit that is not on the task branch.
        write(self.fx["repo"], "records/synthetic/other.md", "other\n")
        git(self.fx["repo"], "add", "-A")
        git(self.fx["repo"], "commit", "-q", "-m", "main only")
        self.refuse(R.CANDIDATE_NOT_ON_TASK_BRANCH, "submit", commandId="bad-branch", commit=git(self.fx["repo"], "rev-parse", "HEAD"),
                    author=F.author(base))
        # Unreadable author evidence.
        good = self.commit(F.definition_text(), message="good")
        bad_author = dict(F.author(base), evidenceRefs=[dict(commit=base, path="records/synthetic/missing.md")])
        self.refuse(R.AUTHOR_EVIDENCE_UNREADABLE, "submit", commandId="bad-author", commit=good, author=bad_author)
        # The validator itself is unavailable: fail closed.
        (self.fx["repo"] / F.VALIDATOR).unlink()
        self.refuse(R.TEMPLATE_VALIDATOR_UNAVAILABLE, "submit", commandId="bad-validator", commit=good, author=F.author(base))
        self.unchanged(before)
        self.assertEqual(self.reviewer.calls, 0)
        self.assertEqual(R.exit_code(R.TEMPLATE_VALIDATOR_UNAVAILABLE), 2)
        self.assertEqual(R.exit_code(R.TEMPLATE_STRUCTURE_INVALID), 1)

    def test_domain_gate_and_review_channel_definition_check_are_one_validator(self):
        """AC-01: the domain structure gate and the channel's Definition check load the same validator and agree."""
        self.fixture()
        sys.path.insert(0, str(HP / "mechanisms/review-channel"))
        import review_channel_base as B
        import review_channel_execution as X
        target = "tasks/feature-t0/feature-t0.md"
        for text, passes in ((F.definition_text(), True), (F.definition_text(drop="Goal"), False)):
            raw = text.encode()
            try:
                candidate_module.structure_gate(str(self.fx["repo"]), "feature-t0", raw)
                domain_pass = True
            except DefinitionRejection:
                domain_pass = False
            request = dict(stage="task", task_record="feature-t0", inputs=dict(candidates=[target]))
            try:
                X.check_definition(str(self.fx["repo"]), request, {target: raw})
                channel_pass = True
            except B.PreflightError:
                channel_pass = False
            self.assertEqual((domain_pass, channel_pass), (passes, passes))
        module, identity = candidate_module.load_validator(str(self.fx["repo"]))
        self.assertEqual(identity["sha256"], candidate_module.sha256((HP / F.VALIDATOR).read_bytes()))

    # -- AC-02 and AC-06: review off, review-skip and finalization ---------------------------------
    def test_review_disabled_path_writes_review_skip_and_finalization(self):
        """AC-02 / AC-06: switch off records the switch, skips the reviewer, and freezes with RU-01 + RU-02."""
        self.fixture()
        outcome = self.submit()
        self.assertEqual(outcome["route"], dict(edge="E-D04", definitionReview=False, source="default",
                                                switchFact="s1:review-switch"))
        facts = self.facts()
        self.assertEqual((facts["position"], facts["condition"]), (gate.AUTH_GATE, states.AWAITING_HUMAN_ACTION))
        self.assertEqual(facts["attempts"], 0)
        candidate = outcome["candidate"]
        registered = self.cmd("decide", commandId="d1", decision=gate.AUTHORIZE, decisionText="定稿 feature-t0")
        self.assertEqual(registered["result"], R.RULING_REGISTERED)
        self.assertEqual([r["path"].rsplit("/", 1)[1] for r in registered["rulings"]],
                         ["RU-01-definition-review-skip.md", "RU-02-definition-finalization.md"])
        self.execute()
        facts = self.facts()
        self.assertEqual(facts["position"], "N-DEF-FROZEN")
        frozen = self.definition()["frozen"]
        self.assertEqual((frozen["path"], frozen["bytes"], frozen["sha256"]),
                         (candidate["path"], candidate["bytes"], candidate["sha256"]))
        worktree = self.fx["worktree"]
        lint = subprocess.run([sys.executable, "-B", str(HP / F.VALIDATOR), "ruling",
                               "tasks/feature-t0/rulings/RU-01-definition-review-skip.md",
                               "tasks/feature-t0/rulings/RU-02-definition-finalization.md"], cwd=worktree, capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        ru01 = (worktree / "tasks/feature-t0/rulings/RU-01-definition-review-skip.md").read_text()
        ru02 = (worktree / "tasks/feature-t0/rulings/RU-02-definition-finalization.md").read_text()
        object_line = f"> Object: {candidate['path']} · {candidate['bytes']} bytes · SHA-256 {candidate['sha256']}"
        self.assertIn(object_line, ru01)
        self.assertIn(object_line, ru02)
        self.assertIn("RU-01-definition-review-skip.md", ru02.splitlines()[4])
        # Zero-byte change of the candidate between recording and finalization.
        self.assertEqual(candidate_module.sha256(git(worktree, "show", "HEAD:tasks/feature-t0/feature-t0.md").encode() + b"\n"),
                         candidate["sha256"])
        # Read-only downstream view of the frozen identity.
        from domain.definition.commands import frozen_definition
        self.assertEqual(frozen_definition(self.domain.store.read(), "feature-t0")["sha256"], candidate["sha256"])

    def test_finalization_basis_and_candidate_identity_are_enforced(self):
        """AC-02 / AC-06: a changed candidate, a non-gate position and a generic decide are refused; nothing freezes."""
        self.fixture()
        self.refuse(R.POSITION_NOT_APPLICABLE, "decide", commandId="d0", decision=gate.AUTHORIZE, decisionText="定稿")
        self.submit()
        before = self.facts()
        # The candidate bytes on the task branch changed after recording: the review-skip object would not match.
        self.commit(F.definition_text().replace("Synthetic goal.", "Changed goal."), message="changed")
        self.refuse(R.CANDIDATE_BYTES_CHANGED, "decide", commandId="d1", decision=gate.AUTHORIZE, decisionText="定稿")
        self.unchanged(before)
        # The generic entry refuses the freezing decision with a distinguishable reason.
        with self.assertRaises(WorkflowRejection) as ctx:
            self.domain.run("decide", dict(taskId="feature-t0", commandId="g1", decision=gate.AUTHORIZE, authorityRef=OWNER),
                            generation=self.generation)
        self.assertEqual(ctx.exception.code, W.DECISION_NOT_LEGAL_HERE)
        self.assertTrue(ctx.exception.detail["definitionEntryRequired"])
        self.assertEqual(self.facts()["decisions"], [])
        self.assertNotEqual(self.facts()["position"], "N-DEF-FROZEN")

    def test_ruling_write_interruption_completes_or_stops_without_duplicates(self):
        """AC-08: a ruling write interrupted before, during or after commit never duplicates or overwrites."""
        self.fixture()
        self.submit()
        # Precondition failure: uncommitted change in the task record directory blocks, leaves nothing half-written.
        write(self.fx["worktree"], "tasks/feature-t0/scratch.md", "uncommitted\n")
        self.cmd("decide", commandId="d1", decision=gate.AUTHORIZE, decisionText="定稿")
        self.execute()
        self.assertEqual(self.facts()["position"], gate.AUTH_GATE)
        self.assertFalse((self.fx["worktree"] / "tasks/feature-t0/rulings").exists())
        (self.fx["worktree"] / "tasks/feature-t0/scratch.md").unlink()
        # Interrupted after the commit: the branch carries the exact bytes; the replayed decision completes it.
        registered = self.cmd("decide", commandId="d1", decision=gate.AUTHORIZE, decisionText="定稿")
        self.assertEqual(registered["result"], R.IDEMPOTENT_REPLAY)
        state = self.domain.store.read()
        items = state["executionDescriptors"][registered["executionId"]]["input"]["items"]
        from domain.definition import rulings
        rulings.write(self.fx["worktree"], self.fx["branch"], state["executionDescriptors"][registered["executionId"]]["input"]["base"],
                      "feature-t0", items, "simulated interrupted write")
        head = git(self.fx["worktree"], "rev-parse", "HEAD")
        self.execute()
        self.assertEqual(self.facts()["position"], "N-DEF-FROZEN")
        self.assertEqual(git(self.fx["worktree"], "rev-parse", "HEAD"), head)  # no second commit
        self.assertEqual(sorted(p.name for p in (self.fx["worktree"] / "tasks/feature-t0/rulings").iterdir()),
                         ["RU-01-definition-review-skip.md", "RU-02-definition-finalization.md"])

    def test_ruling_write_with_different_bytes_on_the_branch_is_indeterminate(self):
        """AC-08: different bytes already at a ruling path are never overwritten; the write stops as indeterminate."""
        self.fixture()
        self.submit()
        registered = self.cmd("decide", commandId="d1", decision=gate.AUTHORIZE, decisionText="定稿")
        path = registered["rulings"][0]["path"]
        write(self.fx["worktree"], path, "> Ruling: RU-01\nsomething else\n")
        git(self.fx["worktree"], "add", "-A")
        git(self.fx["worktree"], "commit", "-q", "-m", "foreign bytes")
        self.execute()
        view = self.definition()
        self.assertEqual({r["status"] for r in view["rulings"]}, {"indeterminate"})
        self.assertEqual(self.facts()["position"], gate.AUTH_GATE)
        self.assertEqual((self.fx["worktree"] / path).read_text(), "> Ruling: RU-01\nsomething else\n")

    # -- AC-03 ----------------------------------------------------------------------------------------
    def test_dispatch_request_binds_the_candidate_the_anchor_sources_and_the_fixed_author(self):
        """AC-03: the request names the bound candidate and anchor-revision sources; the callback sees the fixed author."""
        self.fixture(definition_review=True)
        outcome = self.submit()
        self.assertEqual(self.facts()["position"], "N-DEF-REVIEW-DISPATCH")
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        dispatched = self.cmd("dispatch", commandId="p1")
        self.assertEqual(dispatched["result"], R.REVIEW_DISPATCHED)
        self.execute()
        request = self.reviewer.requests[0]
        self.assertEqual(request["inputs"], dict(candidates=["tasks/feature-t0/feature-t0.md"],
                                                 references=["sdd/proposal.md", "sdd/spec.md", "sdd/milestones.md"]))
        self.assertEqual(request["artifact_author"], dict(human_only=False, authors=[dict(tool="claude-code",
                                                                                          model="claude-opus-5", vendor="Anthropic")]))
        self.assertTrue(request["formal_review_authorized_by_owner"])
        self.assertEqual((request["stage"], request["round"], request["task_record"]), ("task", "r1", "feature-t0"))
        intent = self.reviewer.intents[0]
        self.assertEqual((intent["portId"], intent["executionRequestId"]), ("standalone", "review:feature-t0:r1"))
        # feature-t6's callback signature: subject review-release, entry named by port mode, request context keys.
        call = self.calls[0]
        self.assertEqual((call["subject"], call["entry"]), ("review-release", "standalone"))
        self.assertEqual(call["context"]["object"], dict(kind="definition", path=outcome["candidate"]["path"],
                                                         commit=outcome["candidate"]["commit"], bytes=outcome["candidate"]["bytes"],
                                                         sha256=outcome["candidate"]["sha256"]))
        self.assertEqual((call["context"]["round"], call["context"]["attemptId"], call["context"]["maxCalls"]),
                         (1, "feature-t0:review:r1", 1))
        self.assertEqual(call["context"]["declaredAuthors"], dict(vendors=["Anthropic"], humanOnly=False))
        self.assertEqual(set(intent["budget"]), {"maxToolCalls", "maxRunSeconds", "maxOutputBytes", "cleanupSeconds"})
        self.assertEqual(outcome["candidate"]["authorIdentity"]["agents"], [dict(agent="claude-code", model="claude-opus-5")])
        self.assertEqual(self.definition()["rounds"][0]["candidateId"], outcome["candidate"]["candidateId"])
        self.assertEqual(self.facts()["position"], gate.AUTH_GATE)

    def test_dispatch_refusals_make_no_provider_call_and_no_reviewer_fail(self):
        """AC-03: unregistered port, entry mismatch, missing mapping, missing callback, DENY and missing formal fact."""
        self.fixture(definition_review=True, registry_doc=F.registry(standalone=None))
        self.submit()
        before = self.facts()
        self.refuse(R.PORT_NOT_REGISTERED, "dispatch", commandId="p0")
        self.refuse(R.PORT_ENTRY_MISMATCH, "formal-authorize", commandId="f0", maxCalls=1, portId="embedded")
        self.unchanged(before)
        # Registry with a standalone port but its mapping missing.
        doc = F.registry()
        doc["model_mappings"] = []
        write(self.fx["repo"], F.REGISTRY, json.dumps(doc))
        self.refuse(R.PORT_NOT_REGISTERED, "dispatch", commandId="p1")
        write(self.fx["repo"], F.REGISTRY, json.dumps(F.registry()))
        # The feature-t6 callback is not installed (simulated: the module cannot be found).
        import importlib.util
        from unittest import mock
        real_find = importlib.util.find_spec
        self.domain.authorizer_present = False
        with mock.patch("importlib.util.find_spec",
                        side_effect=lambda name, *a: None if name == "domain.policy.authorize" else real_find(name, *a)):
            self.refuse(R.AUTHORIZER_UNAVAILABLE, "dispatch", commandId="p2")
        self.domain.authorizer_present = True
        self.unchanged(before)
        self.assertEqual(self.reviewer.calls, 0)
        # Worktree registry must also carry the port for the review repository.
        write(self.fx["worktree"], F.REGISTRY, json.dumps(F.registry()))
        # CONFIGURED port without an Owner formal authorization fact: the real port preflight refuses.
        self.cmd("dispatch", commandId="p3")
        self.execute()
        round_one = self.definition()["rounds"][-1]
        self.assertEqual(round_one["status"], "execution-failed")
        self.assertEqual(round_one["failure"]["failureCode"], "execution-port-capability-unverified")
        self.assertEqual(self.facts()["condition"], states.RECOVERY_REQUIRED)
        self.assertEqual(self.reviewer.calls, 0)
        self.assertIsNone(round_one["verdict"])

    def test_authorization_callback_refusal_is_not_a_reviewer_fail(self):
        """AC-03 / AC-05: callback DENY and NOT_DETERMINABLE settle as execution failure, never as FAIL."""
        for decision, code in (("DENY", "policy-denied"), ("UNKNOWN", "policy-not-determinable")):
            with self.subTest(decision=decision):
                self.fx = F.create(self.directory / ("deny-" + decision), definition_review=True)
                self.domain = F.TestHarnessDomain(self.fx["repo"], entry="cli")
                self.generation = self.domain.bind_entry()
                self.reviewer = F.SyntheticReviewer()
                self.authorizer = F.synthetic_authorizer(decision=decision)
                self.submit()
                self.cmd("dispatch", commandId="p1")
                self.execute()
                facts, rnd = self.facts(), self.definition()["rounds"][-1]
                self.assertEqual((facts["position"], facts["condition"]), ("N-DEF-REVIEWER", states.RECOVERY_REQUIRED))
                self.assertEqual(rnd["failure"]["failureCode"], code)
                self.assertEqual(self.reviewer.calls, 0)

    def test_formal_authorization_entry_records_the_fact_feature_t6_reads(self):
        """AC-03: the Owner formal authorization entry binds instance, review object, round and port; not for REVIEW_ENABLED."""
        self.fixture(definition_review=True)
        self.submit()
        recorded = self.cmd("formal-authorize", commandId="f1", maxCalls=2)
        formal = recorded["formal"]
        candidate = self.definition()["candidates"][-1]
        self.assertEqual((formal["workflowInstance"], formal["round"], formal["roundLabel"], formal["attemptId"], formal["portId"],
                          formal["entry"]), ("feature-t0", 1, "r1", "feature-t0:review:r1", "standalone", "cli"))
        self.assertEqual(formal["reviewObject"]["sha256"], candidate["sha256"])
        fact = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]["facts"][formal["factId"]]
        self.assertEqual((fact["kind"], fact["purpose"]), ("human-decision", "owner-formal-review-authorization"))
        # Field names as feature-t6's finalized design reads them: taskId, object{path,bytes,sha256}, portId, profileDigest.
        payload = fact["payload"]
        self.assertEqual(payload["taskId"], "feature-t0")
        self.assertEqual(payload["object"], dict(path=candidate["path"], bytes=candidate["bytes"], sha256=candidate["sha256"]))
        self.assertEqual((payload["portId"], payload["profileDigest"]), ("standalone", F.DIGEST))
        self.assertEqual(set(candidate["authorIdentity"]), {"humanOnly", "agents", "evidenceRefs"})
        self.assertEqual(self.cmd("formal-authorize", commandId="f1", maxCalls=2)["result"], R.IDEMPOTENT_REPLAY)
        self.refuse(R.INPUT_INVALID, "formal-authorize", commandId="f2", maxCalls=0)
        write(self.fx["repo"], F.REGISTRY, json.dumps(F.registry(standalone="REVIEW_ENABLED")))
        self.refuse(R.FORMAL_AUTHORIZATION_NOT_APPLICABLE, "formal-authorize", commandId="f3", maxCalls=1)

    def test_host_and_cli_review_qualification_is_not_mutual(self):
        """AC-03: the embedded registration never serves the CLI entry and the standalone one never serves Runtime."""
        from domain.definition import review
        self.fixture()
        root = str(self.fx["repo"])
        self.assertEqual(review.select_port(root, "cli")[0]["id"], "standalone")
        self.assertEqual(review.select_port(root, "runtime")[0]["id"], "embedded")
        write(self.fx["repo"], F.REGISTRY, json.dumps(F.registry(embedded=None)))
        with self.assertRaises(DefinitionRejection) as ctx:
            review.select_port(root, "runtime")
        self.assertEqual(ctx.exception.code, R.PORT_NOT_REGISTERED)

    # -- AC-03 with the real feature-t6 callback -----------------------------------------------------------
    def real_fixture(self, **kw):
        self.fx = F.create(self.directory / "real", definition_review=True, registry_doc=F.live_registry_copy(),
                           author_vendor=True, **kw)
        self.domain = F.TestHarnessDomain(self.fx["repo"], entry="cli")
        self.domain.authorizer_present = False  # production availability check: feature-t6 is installed
        self.generation = self.domain.bind_entry()
        self.reviewer = F.SyntheticReviewer()

    def real_execute(self):
        env = Environment("cli", self.domain, self.generation, repository_root=str(self.fx["repo"]))
        return run_pending(self.domain, env, F.real_executors(self.reviewer))

    def policy_facts(self):
        inst = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]
        return [f for f in inst["facts"].values() if f["kind"] == "policy-decision"]

    def test_real_callback_denies_without_the_owner_formal_fact_and_allows_with_it(self):
        """AC-03: the real feature-t6 callback reads the fixed author identity and the Owner formal fact this task records."""
        self.real_fixture()
        outcome = self.submit()
        self.cmd("dispatch", commandId="p1")
        self.real_execute()
        rnd = self.definition()["rounds"][-1]
        self.assertEqual((rnd["status"], rnd["failure"]["failureCode"]), ("execution-failed", "policy-denied"))
        self.assertEqual(self.reviewer.calls, 0)
        self.assertIsNone(rnd["verdict"])
        denied = self.policy_facts()[-1]["payload"]
        codes = {i["item"]: (i["result"], (i.get("reason") or {}).get("code")) for i in denied["items"]}
        self.assertEqual(codes["reviewer-eligibility"], ("FAIL", "FORMAL_AUTHORIZATION_REQUIRED"))
        self.assertEqual(codes["author-vendors"][0], "PASS")
        self.assertEqual(denied["derived"]["authorVendors"], ["Anthropic"])
        # A second task on a fresh line: with the Owner formal fact the same real callback allows the review.
        other = F.create(self.directory / "real-2", definition_review=True, registry_doc=F.live_registry_copy(), author_vendor=True)
        self.fx, self.domain = other, F.TestHarnessDomain(other["repo"], entry="cli")
        self.domain.authorizer_present = False
        self.generation = self.domain.bind_entry()
        self.reviewer = F.SyntheticReviewer()
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.real_execute()
        allowed = self.policy_facts()[-1]["payload"]
        self.assertEqual(allowed["conclusion"], "ALLOW")
        self.assertTrue(allowed["derived"]["ownerFormal"])
        formal = self.definition()["formal"][0]["factId"]
        self.assertIn(formal, allowed.get("authorizationRefs", []))
        self.assertEqual(self.reviewer.calls, 1)
        self.assertEqual(self.facts()["position"], gate.AUTH_GATE)
        self.assertEqual(outcome["candidate"]["authorIdentity"]["agents"], [dict(agent="claude-code", model="claude-opus-5")])

    def test_real_callback_denies_an_author_vendor_equal_to_the_reviewer_vendor(self):
        """AC-03: with the real callback, an OpenAI-authored Definition is refused for an OpenAI reviewer; no provider call."""
        self.real_fixture()
        from domain.acceptance.accept import set_configuration
        set_configuration(self.domain.store, "author-vendor", dict(agent="codex", model="gpt-6-sol", vendor="OpenAI"), OWNER)
        author = dict(tool="codex", model="gpt-6-sol", vendor="OpenAI", humanOnly=False,
                      evidenceRefs=[dict(commit=self.fx["head"], path=F.EVIDENCE)])
        self.cmd("submit", commandId="s1", commit=self.commit(), author=author)
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.real_execute()
        rnd = self.definition()["rounds"][-1]
        self.assertEqual(rnd["failure"]["failureCode"], "policy-denied")
        codes = {i["item"]: (i.get("reason") or {}).get("code") for i in self.policy_facts()[-1]["payload"]["items"]}
        self.assertEqual(codes["author-vendors"], "VENDOR_OVERLAP")
        self.assertEqual(self.reviewer.calls, 0)
        self.assertEqual(self.facts()["condition"], states.RECOVERY_REQUIRED)

    # -- AC-04 -------------------------------------------------------------------------------------------
    def test_valid_pass_and_fail_verdicts_route_and_keep_their_bytes(self):
        """AC-04: PASS reaches the authorization gate, FAIL reaches the budget decision; verdict identity kept."""
        self.fixture(definition_review=True)
        self.reviewer = F.SyntheticReviewer(("valid", "FAIL"), ("valid", "PASS"))
        outcome = self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.execute()
        rnd = self.definition()["rounds"][0]
        self.assertEqual(rnd["verdict"]["verdict"], "FAIL")
        self.assertEqual(self.facts()["position"], "N-DEF-BUDGET-DECISION")
        fact = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]["facts"][rnd["verdictFact"]]
        self.assertEqual((fact["kind"], fact["payload"]["verdictSha256"]), ("reviewer-verdict", rnd["verdict"]["verdictSha256"]))
        # The reviewer never modifies the candidate.
        raw = (self.fx["worktree"] / "tasks/feature-t0/feature-t0.md").read_bytes()
        self.assertEqual(candidate_module.sha256(raw), outcome["candidate"]["sha256"])

    def test_verdicts_that_do_not_fit_the_round_never_enter(self):
        """AC-04: wrong schema, stage, question set or candidate identity cannot become a verdict fact."""
        broken = [dict(schema="review-channel-verdict/v3"), dict(stage="impl"),
                  dict(questions=F.QUESTIONS[:4]), dict(candidate_sha="0" * 64)]
        for n, kw in enumerate(broken):
            with self.subTest(case=n):
                self.fx = F.create(self.directory / ("v%d" % n), definition_review=True)
                self.domain = F.TestHarnessDomain(self.fx["repo"], entry="cli")
                self.generation = self.domain.bind_entry()
                self.reviewer = F.SyntheticReviewer(("valid", "PASS", kw))
                self.authorizer = F.synthetic_authorizer()
                self.submit()
                self.cmd("formal-authorize", commandId="f1", maxCalls=1)
                self.cmd("dispatch", commandId="p1")
                self.execute()
                rnd = self.definition()["rounds"][-1]
                self.assertIsNone(rnd["verdict"])
                self.assertEqual(rnd["failure"]["classification"], "verdict-not-acceptable")
                self.assertEqual(self.facts()["condition"], states.RECOVERY_REQUIRED)

    def test_human_findings_hold_the_verdict_until_disposed(self):
        """AC-04: a verdict with a human finding does not advance until a finding-disposition ruling is written."""
        self.fixture(definition_review=True)
        self.reviewer = F.SyntheticReviewer(("valid", "PASS", dict(human=True)))
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.execute()
        self.assertEqual((self.facts()["position"], self.facts()["condition"]), (gate.VERDICT_DECISION, states.RESULT_RECORDED))
        self.assertEqual(self.definition()["rounds"][0]["status"], "awaiting-human-disposition")
        self.refuse(R.INPUT_INVALID, "decide", commandId="x1", decision=gate.DISPOSE, decisionText="处置", findings={})
        registered = self.cmd("decide", commandId="x2", decision=gate.DISPOSE, decisionText="按保留处置",
                              findings={"R1-H1": "接受，作为已知取舍"})
        self.assertEqual(registered["result"], R.RULING_REGISTERED)
        self.execute()
        self.assertEqual(self.facts()["position"], gate.AUTH_GATE)
        path = self.fx["worktree"] / "tasks/feature-t0/rulings/RU-01-definition-finding-disposition.md"
        self.assertIn("> Type: finding-disposition", path.read_text())

    # -- AC-05 -------------------------------------------------------------------------------------------
    def test_execution_failures_and_unknown_results_enter_recovery_not_fail(self):
        """AC-05: cancel, port failure, timeout, provider unavailable, invalid output and unknown never take E-D08."""
        classes = [("cancelled_by_host", "cancelled_by_host"), ("execution_port_failure", "execution-port-failure"),
                   ("timeout_or_transport_failure", "timeout"), ("provider_unavailable", "provider-unavailable"),
                   ("reviewer_output_invalid", "verdict-invalid"), ("preflight_failed", "round_budget_exhausted")]
        for n, (classification, code) in enumerate(classes + [("unknown", "result-unknown")]):
            with self.subTest(classification=classification):
                self.fx = F.create(self.directory / ("f%d" % n), definition_review=True)
                self.domain = F.TestHarnessDomain(self.fx["repo"], entry="cli")
                self.generation = self.domain.bind_entry()
                receipt = classification != "unknown"
                self.reviewer = F.SyntheticReviewer(("failed", classification, code, receipt))
                self.authorizer = F.synthetic_authorizer()
                self.submit()
                self.cmd("formal-authorize", commandId="f1", maxCalls=1)
                self.cmd("dispatch", commandId="p1")
                self.execute()
                facts = self.facts()
                state = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]
                self.assertEqual((facts["position"], facts["condition"]), ("N-DEF-REVIEWER", states.RECOVERY_REQUIRED))
                self.assertNotIn("E-D08", [c["selectedEdge"] for c in state["commits"]])
                attempt = state["attempts"][-1]
                reservation = state["reservations"]["review:feature-t0:r1"]
                if classification == "unknown":
                    self.assertEqual(attempt["status"], "INDETERMINATE")
                    self.assertEqual(reservation["status"], "held")
                else:
                    self.assertEqual(attempt["status"], "EXECUTION_FAILED")
                if classification == "preflight_failed":
                    # The channel's own round budget is not the v5 Definition Review budget decision.
                    self.assertNotEqual(facts["position"], "N-DEF-BUDGET-DECISION")

    def test_running_review_is_only_queried_after_a_restart(self):
        """AC-05 / AC-09: a review left running is never dispatched again; the query result settles it."""
        self.fixture(definition_review=True)
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        dispatched = self.cmd("dispatch", commandId="p1")
        self.domain.start_execution(dispatched["executionId"], self.generation)  # the process died after starting
        attempt = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]["attempts"][-1]
        self.assertEqual(attempt["status"], "RUNNING")
        self.execute()
        self.assertEqual(self.reviewer.calls, 0)  # queried, not executed
        state = self.domain.store.read()
        self.assertEqual(state["executionDescriptors"][dispatched["executionId"]]["status"], "indeterminate")
        self.assertEqual(state["tasks"]["feature-t0"]["workflowInstance"]["reservations"]["review:feature-t0:r1"]["status"], "held")

    # -- AC-06 / AC-07 -----------------------------------------------------------------------------------
    def test_authorize_after_pass_uses_the_final_verdict_as_basis(self):
        """AC-06: after a PASS the finalization basis is that verdict; a revised candidate needs a new round."""
        self.fixture(definition_review=True)
        self.reviewer = F.SyntheticReviewer(("valid", "FAIL"), ("valid", "PASS"))
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.execute()
        self.assertEqual(self.facts()["position"], "N-DEF-BUDGET-DECISION")
        self.escalate_budget("remains")
        # Revision only here, after FAIL; not at the authorization gate.
        revised = self.cmd("submit", commandId="s2", commit=self.commit(F.definition_text().replace("Synthetic goal.", "Revised goal.")),
                           author=F.author(self.fx["head"]))
        self.assertEqual(revised["candidate"]["kind"], "revision")
        self.cmd("formal-authorize", commandId="f2", maxCalls=1)
        self.cmd("dispatch", commandId="p2")
        self.execute()
        self.assertEqual(self.facts()["position"], gate.AUTH_GATE)
        registered = self.cmd("decide", commandId="d1", decision=gate.AUTHORIZE, decisionText="定稿")
        self.assertEqual([r["type"] for r in registered["rulings"]], ["finalization"])
        self.execute()
        ru = (self.fx["worktree"] / registered["rulings"][0]["path"]).read_text()
        self.assertIn(revised["candidate"]["sha256"], ru.splitlines()[3])
        self.assertIn("synthetic/verdict.md", ru.splitlines()[4])
        self.assertEqual(self.facts()["position"], "N-DEF-FROZEN")

    def escalate_budget(self, outcome):
        """feature-t5's real budget decision at the budget node, with an explicitly configured Definition budget.

        feature-t5 narrows the generic commands at the budget nodes, so the former synthetic walk is replaced by
        its Domain Core entry: the Policy Gate records the decision and the edge follows (1 remains, 0 exhausts).
        """
        from domain.budget import configuration
        amount = 1 if outcome == "remains" else 0
        self.domain.transaction(self.generation, lambda s: configuration.set_budget(
            s, dict(definitionReview=amount, verification=0, validationReview=0), OWNER))
        decided = self.domain.run("budget-decide", dict(taskId="feature-t0", authorityRef="synthetic:budget",
                                                        commandId="budget-" + outcome), generation=self.generation)
        self.assertEqual(decided["edge"], "E-D11" if outcome == "remains" else "E-D10")

    def test_escalation_decisions_and_reservation_acceptance(self):
        """AC-07: at the Definition escalation gate, Continue / Close Task / Accept With reservation behave as specified."""
        self.fixture(definition_review=True)
        self.reviewer = F.SyntheticReviewer(("valid", "FAIL"))
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.execute()
        # Without a budget fact the task stays at the budget decision.
        self.assertEqual(self.facts()["position"], "N-DEF-BUDGET-DECISION")
        self.escalate_budget("exhausted")
        facts = self.facts()
        self.assertEqual(facts["position"], gate.ESCALATION_GATE)
        from domain.workflow import progression
        inst = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]
        legal = {d["decision"] for d in progression.decisions(inst, self.domain.topology(inst))}
        self.assertEqual({d["decision"] for d in facts["decisions"]}, {"Continue", "Close Task"})  # generic entry view
        self.assertEqual(legal, {"Continue", "Close Task", "Accept With reservation"})
        self.refuse(R.RESERVATION_REQUIRED, "decide", commandId="d0", decision=gate.ACCEPT_RESERVATION, decisionText="带保留接受")
        registered = self.cmd("decide", commandId="d1", decision=gate.ACCEPT_RESERVATION, decisionText="带保留接受",
                              reservation="目标条件 2 留待施工核实")
        self.execute()
        self.assertEqual(self.facts()["position"], "N-DEF-FROZEN")
        view = self.definition()
        self.assertEqual(view["reservations"][0]["verdict"]["verdict"], "FAIL")
        self.assertTrue(view["reservations"][0]["verdict"]["findings"])
        ru = (self.fx["worktree"] / registered["rulings"][0]["path"]).read_text()
        self.assertIn("目标条件 2 留待施工核实", ru)
        commits = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]["commits"]
        self.assertEqual([c["selectedEdge"] for c in commits][-2:], ["E-D14", "E-D16"])

    def test_escalation_continue_and_close(self):
        """AC-07: Continue returns to the dispatch position; Close Task closes atomically as blocked escalation."""
        self.fixture(definition_review=True)
        self.reviewer = F.SyntheticReviewer(("valid", "FAIL"), ("valid", "FAIL"))
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.execute()
        self.escalate_budget("exhausted")
        self.domain.run("decide", dict(taskId="feature-t0", commandId="c1", decision="Continue", authorityRef=OWNER),
                        generation=self.generation)
        self.assertEqual(self.facts()["position"], "N-DEF-CONTINUE")
        self.cmd("formal-authorize", commandId="f2", maxCalls=1)
        self.assertEqual(self.facts()["position"], "N-DEF-REVIEW-DISPATCH")
        self.cmd("dispatch", commandId="p2")
        self.execute()
        self.run_close()

    def run_close(self):
        run = lambda name, **p: self.domain.run(name, dict(taskId="feature-t0", authorityRef=OWNER, **p), generation=self.generation)
        # feature-t5: the second window (opened by Continue) uses the Definition budget configured at 0 and exhausts.
        self.assertEqual(run("budget-decide", commandId="b2")["edge"], "E-D10")
        outcome = run("decide", commandId="c2", decision="Close Task")
        facts = self.facts()
        self.assertEqual((facts["lifecycle"], facts["position"]), (states.CLOSED, "N-DEF-CLOSE"))
        self.assertEqual(facts["closure"]["reasonCategory"], "blocked-escalation")
        self.assertEqual(outcome["result"], W.FINALIZED)

    # -- AC-10 immutability ---------------------------------------------------------------------------------
    def test_recorded_facts_and_rulings_are_never_rewritten(self):
        """AC-10: verdict facts, Human decisions and written rulings keep their bytes through later steps and replays."""
        self.fixture(definition_review=True)
        self.reviewer = F.SyntheticReviewer(("valid", "FAIL", dict(human=True)))
        self.submit()
        self.cmd("formal-authorize", commandId="f1", maxCalls=1)
        self.cmd("dispatch", commandId="p1")
        self.execute()
        state = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]
        verdict_fact = json.dumps(state["facts"]["settle:review:feature-t0:r1:verdict"], sort_keys=True)
        self.cmd("decide", commandId="x1", decision=gate.DISPOSE, decisionText="处置", findings={"R1-H1": "接受"})
        self.execute()
        disposition = (self.fx["worktree"] / "tasks/feature-t0/rulings/RU-01-definition-finding-disposition.md").read_bytes()
        self.escalate_budget("exhausted")
        self.cmd("decide", commandId="d1", decision=gate.ACCEPT_RESERVATION, decisionText="带保留接受", reservation="保留一项")
        self.execute()
        # Replaying the same commands returns the recorded results and writes nothing new.
        head = git(self.fx["worktree"], "rev-parse", "HEAD")
        self.assertEqual(self.cmd("decide", commandId="d1", decision=gate.ACCEPT_RESERVATION, decisionText="带保留接受",
                                  reservation="保留一项")["result"], R.IDEMPOTENT_REPLAY)
        self.execute()
        self.assertEqual(git(self.fx["worktree"], "rev-parse", "HEAD"), head)
        state = self.domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]
        self.assertEqual(json.dumps(state["facts"]["settle:review:feature-t0:r1:verdict"], sort_keys=True), verdict_fact)
        self.assertEqual((self.fx["worktree"] / "tasks/feature-t0/rulings/RU-01-definition-finding-disposition.md").read_bytes(),
                         disposition)
        view = self.definition()
        self.assertEqual(view["reservations"][0]["verdict"]["verdict"], "FAIL")
        self.assertEqual(self.facts()["position"], "N-DEF-FROZEN")

    # -- AC-08 standalone CLI -----------------------------------------------------------------------------
    def test_cli_definition_commands_use_the_same_functions(self):
        """AC-08: `harness definition` status, submit and generic-decide refusal through the product CLI."""
        self.fixture()
        commit = self.commit()
        cli = lambda *a: subprocess.run([sys.executable, "-B", str(APP / "hp.py"), *a], capture_output=True, text=True, cwd=APP)
        proc = cli("definition", "status", "--repository", str(self.fx["repo"]), "--task-id", "feature-t0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = cli("definition", "submit", "--repository", str(self.fx["repo"]), "--task-id", "feature-t0", "--command-id", "cli-1",
                   "--authority-ref", OWNER, "--commit", commit, "--author", json.dumps(F.author(self.fx["head"])))
        # The product CLI uses the production availability check; the candidate itself needs no callback.
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        document = json.loads(proc.stdout)
        self.assertEqual((document["result"], document["entry"]), (R.CANDIDATE_RECORDED, "cli"))
        proc = cli("workflow", "decide", "--repository", str(self.fx["repo"]), "--task-id", "feature-t0", "--command-id", "g1",
                   "--authority-ref", OWNER, "--decision", gate.AUTHORIZE)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(json.loads(proc.stdout)["reason"]["definitionEntryRequired"])
        proc = cli("definition", "dispatch", "--repository", str(self.fx["repo"]), "--task-id", "feature-t0", "--command-id", "p1",
                   "--authority-ref", OWNER)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["result"], R.POSITION_NOT_APPLICABLE)


if __name__ == "__main__":
    unittest.main()
