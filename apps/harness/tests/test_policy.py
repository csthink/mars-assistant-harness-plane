"""feature-t6 Policy Gate tests on synthetic product lines. Docstrings carry the AC tags.

No real model, no remote operation, no write to the live Registry or outside the temporary directory.
Facts owned by other tasks (feature-t3 author identity and formal authorization, feature-t4
registration, feature-t7 publishBinding, feature-t17 execution records) are written in the shapes
fixed by the feature-t6 design and marked synthetic; see policy_fixture.py.
"""
import asyncio
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
from domain.acceptance.results import Rejection
from domain.core import HarnessDomain
from domain.policy import inputs as policy_inputs
from domain.policy import results as policy_results
from domain.policy import rules
from domain.policy.authorize import execution_authorizer
from domain.policy.results import PolicyInputInvalid
from domain.workflow import progression
from domain.workflow.results import WorkflowRejection
from execution.host import HostExecutionPort
from execution.local import LocalExecutionPort
from execution.port import ExecutionDiscovery, ExecutionError
from policy_fixture import CLAUDE, CODEX, OWNER, TASK, World, implementer_registration, synthetic_registry
from product_line import git

APP = Path(__file__).resolve().parents[1]
PY = sys.executable


def item(outcome, name):
    return next(r for r in outcome["decision"]["items"] if r["item"] == name)


def code(outcome, name):
    row = item(outcome, name)
    return row["result"], (row["reason"] or {}).get("code")


class PolicyCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / ("policy-" + self._testMethodName)
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t6-tests-")
            self.directory = Path(self.temp.name)
        self.world = World(self.directory / "w")

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    # -- common arrangements ------------------------------------------------------------------------
    def reviewable(self, identity=None, formal=True):
        """A committed Definition with a fixed Claude authorship, mapped to Anthropic, reviewed by OpenAI."""
        w = self.world
        obj = w.commit_definition()
        w.candidate(obj, identity or dict(humanOnly=False, agents=[dict(agent=CLAUDE[0], model=CLAUDE[1])],
                                          evidenceRefs=["evidence:claude-session"]))
        w.map_author(CLAUDE[0], CLAUDE[1], "Anthropic")
        if formal:
            w.formal(obj)
        return obj

    def cli(self, *args):
        result = subprocess.run([PY, "-B", str(APP / "hp.py"), *args], capture_output=True, text=True, timeout=120)
        return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None

    # -- AC-01 --------------------------------------------------------------------------------------
    def test_allow_deny_not_determinable_and_exit_codes(self):
        """AC-01: overall conclusion follows the item results and maps to exit codes 0/1/2."""
        self.assertEqual(policy_results.conclude(["PASS", "NOT_APPLICABLE"]), "ALLOW")
        self.assertEqual(policy_results.conclude(["PASS", "FAIL", "NOT_CHECKED"]), "DENY")
        self.assertEqual(policy_results.conclude(["PASS", "NOT_CHECKED"]), "NOT_DETERMINABLE")
        self.assertEqual([policy_results.exit_code(c) for c in ("ALLOW", "DENY", "NOT_DETERMINABLE", "INPUT_INVALID")],
                         [0, 1, 2, 2])
        with self.assertRaises(ValueError):
            policy_results.conclude(["MAYBE"])
        obj = self.reviewable()
        allowed = self.world.evaluate(self.world.review_request(obj))
        self.assertEqual(allowed["conclusion"], "ALLOW", allowed["decision"]["items"])

    def test_applicability_table_is_fixed_per_subject(self):
        """AC-01: each subject has a fixed applicable item set; NOT_APPLICABLE comes only from the table."""
        w = self.world
        obj = self.reviewable()
        review = w.evaluate(w.review_request(obj))
        push = w.evaluate(w.push_request())
        for outcome, subject in ((review, rules.REVIEW_RELEASE), (push, rules.PUSH_PERMIT)):
            for row in outcome["decision"]["items"]:
                expected_na = rules.APPLICABILITY[row["item"]][subject] == rules.NA
                self.assertEqual(row["result"] == "NOT_APPLICABLE", expected_na, row)
            self.assertEqual([r["item"] for r in outcome["decision"]["items"]], list(rules.ITEMS))

    def test_closed_sets_reject_unknown_subject_and_caller_applicability(self):
        """AC-01: a subject outside the closed set or caller-chosen applicability is INPUT_INVALID, nothing recorded."""
        w = self.world
        before = len(w.inst()["facts"])
        bad = w.push_request()
        bad["subject"] = "deploy-permit"
        with self.assertRaises(PolicyInputInvalid) as ctx:
            w.evaluate(bad)
        self.assertEqual(ctx.exception.detail.get("reasonCode"), "SUBJECT_NOT_IN_CLOSED_SET")
        other = w.push_request()
        other["applicability"] = {"push-permit": "NA"}
        with self.assertRaises(PolicyInputInvalid):
            w.evaluate(other)
        self.assertEqual(len(w.inst()["facts"]), before)

    def test_unreadable_registry_or_state_is_never_allow(self):
        """AC-01: a Registry that cannot be loaded makes the dependent items NOT_CHECKED; conclusion is not ALLOW."""
        w = self.world
        obj = self.reviewable()
        request = w.review_request(obj)
        w.registry = policy_inputs.InputsUnavailable("REGISTRY_UNAVAILABLE", "synthetic unreadable Registry")
        outcome = w.evaluate(request)
        self.assertNotEqual(outcome["conclusion"], "ALLOW")
        self.assertEqual(code(outcome, rules.REVIEWER_ELIGIBILITY), ("NOT_CHECKED", "REGISTRY_UNAVAILABLE"))
        w.registry = synthetic_registry()
        w.rounds = policy_inputs.InputsUnavailable("ROUND_FACTS_UNREADABLE", "synthetic unreadable rounds")
        outcome = w.evaluate(request)
        self.assertEqual(outcome["conclusion"], "NOT_DETERMINABLE")

    def test_same_input_same_conclusion_and_same_record(self):
        """AC-01: the same input evaluates to the same conclusion and the same record identity (idempotent)."""
        w = self.world
        obj = self.reviewable()
        first = w.evaluate(w.review_request(obj))
        second = w.evaluate(w.review_request(obj))
        self.assertEqual(first["factId"], second["factId"])
        self.assertEqual(first["conclusion"], second["conclusion"])
        self.assertEqual(second["result"], "IDEMPOTENT_REPLAY")

    def test_cli_exit_codes_for_each_conclusion_and_input_invalid(self):
        """AC-01 AC-09: standalone CLI exits 0 ALLOW, 1 DENY, 2 NOT_DETERMINABLE and 2 INPUT_INVALID without a record."""
        w = self.world
        w.to_publish_gate("p")
        binding = dict(candidateCommit=w.head_commit(), sourceBranch=w.state()["tasks"][TASK]["branch"], remote="origin",
                       targetBranch="main")
        w.gate_decision_with_binding("E-V06", "Publish authorization", "pub", binding)
        base = ["policy", "evaluate", "--repository", str(w.repo), "--task-id", TASK, "--authority-ref", OWNER]
        rc, doc = self.cli(*base, "--request", json.dumps(w.push_request()))
        self.assertEqual((rc, doc["conclusion"]), (0, "ALLOW"), doc)
        rc, doc = self.cli(*base, "--request", json.dumps(w.push_request(targetBranch="release")))
        self.assertEqual((rc, doc["conclusion"]), (1, "DENY"), doc)
        facts = len(w.inst()["facts"])
        rc, doc = self.cli(*base, "--request", "{not json")
        self.assertEqual((rc, doc["result"]), (2, "INPUT_INVALID"))
        rc, doc = self.cli(*base, "--request", json.dumps(dict(w.push_request(), extra=1)))
        self.assertEqual((rc, doc["result"]), (2, "INPUT_INVALID"))
        self.assertEqual(len(w.inst()["facts"]), facts)
        rc, doc = self.cli("policy", "show", "--repository", str(w.repo), "--task-id", TASK)
        self.assertEqual(rc, 0)
        self.assertTrue(all(d["producer"] == "policy-gate" for d in doc["decisions"]))

    def test_cli_not_determinable_without_implementer_registration(self):
        """AC-01 AC-05: implement release through the CLI is NOT_DETERMINABLE (exit 2) while feature-t4's registration is absent."""
        w = self.world
        obj = w.commit_definition()
        final = w.commit_finalization(obj)
        w.to_implement("i")
        base = ["policy", "evaluate", "--repository", str(w.repo), "--task-id", TASK, "--authority-ref", OWNER]
        rc, doc = self.cli(*base, "--request", json.dumps(w.implement_request(obj, final)))
        self.assertEqual((rc, doc["conclusion"]), (2, "NOT_DETERMINABLE"), doc)
        row = next(r for r in doc["decision"]["items"] if r["item"] == rules.PROFILE_PURPOSE_ENTRY)
        self.assertEqual(row["reason"]["code"], "PORT_REGISTRATION_UNAVAILABLE")

    # -- AC-02 --------------------------------------------------------------------------------------
    def test_author_vendor_from_product_side_mapping_present_and_missing(self):
        """AC-02: the author set comes from the product-side mapping; present maps to PASS, missing is DENY."""
        w = self.world
        obj = w.commit_definition()
        w.candidate(obj, dict(humanOnly=False, agents=[dict(agent=CLAUDE[0], model=CLAUDE[1])], evidenceRefs=["e:1"]))
        w.formal(obj)
        missing = w.evaluate(w.review_request(obj))
        self.assertEqual(missing["conclusion"], "DENY")
        self.assertEqual(code(missing, rules.AUTHOR_VENDORS), ("FAIL", "AUTHOR_VENDOR_UNKNOWN"))
        w.map_author(CLAUDE[0], CLAUDE[1], "Anthropic")
        present = w.evaluate(w.review_request(obj))
        self.assertEqual(present["conclusion"], "ALLOW")
        self.assertEqual(present["decision"]["derived"]["authorVendors"], ["Anthropic"])

    def test_registry_model_mappings_are_not_an_author_source(self):
        """AC-02: the Registry maps gpt-6-sol to OpenAI, yet without a product-side entry the author vendor is unknown."""
        w = self.world
        obj = w.commit_definition()
        w.candidate(obj, dict(humanOnly=False, agents=[dict(agent=CODEX[0], model=CODEX[1])], evidenceRefs=["e:1"]))
        w.formal(obj)
        self.assertTrue(any(m["model_ref"] == CODEX[1] for m in w.registry["registry"]["model_mappings"]))
        outcome = w.evaluate(w.review_request(obj))
        self.assertEqual(code(outcome, rules.AUTHOR_VENDORS), ("FAIL", "AUTHOR_VENDOR_UNKNOWN"))

    def test_execution_record_authors_are_derived_not_declared(self):
        """AC-02: agent and actually read-back model of execution records are mapped; declared vendors do not enter the set."""
        w = self.world
        commit = w.head_commit()
        w.execution("exec:impl-1", CLAUDE[0], CLAUDE[1])
        w.map_author(CLAUDE[0], CLAUDE[1], "Anthropic")
        w.formal(dict(commit=commit), fact_id="formal-c")
        obj = dict(kind="candidate-change", commit=commit)
        request = w.review_request(obj, refs=["exec:impl-1"], declaredAuthors=dict(vendors=["DeepSeek"], humanOnly=False))
        outcome = w.evaluate(request)
        self.assertEqual(code(outcome, rules.AUTHOR_VENDORS), ("FAIL", "AUTHOR_DECLARATION_MISMATCH"))
        request = w.review_request(obj, refs=["exec:impl-1"], declaredAuthors=dict(vendors=["Anthropic"], humanOnly=False))
        outcome = w.evaluate(request)
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])
        self.assertIn("execution:exec:impl-1", outcome["decision"]["derived"]["authorEvidenceRefs"])

    def test_vendor_overlap_empty_unknown_empty_string_and_case(self):
        """AC-02: overlap, empty set, 'unknown', '' and a case-different vendor each FAIL with a distinguishable reason."""
        w = self.world
        commit = w.head_commit()
        obj = dict(kind="candidate-change", commit=commit)
        w.formal(dict(commit=commit), fact_id="formal-c")
        w.execution("exec:codex", CODEX[0], CODEX[1])
        w.map_author(CODEX[0], CODEX[1], "OpenAI")
        overlap = w.evaluate(w.review_request(obj, refs=["exec:codex"]))
        self.assertEqual(code(overlap, rules.AUTHOR_VENDORS), ("FAIL", "VENDOR_OVERLAP"))
        empty = w.evaluate(w.review_request(obj, refs=[]))
        self.assertEqual(code(empty, rules.AUTHOR_VENDORS), ("FAIL", "AUTHOR_SET_EMPTY"))
        w.execution("exec:claude", CLAUDE[0], CLAUDE[1])
        w.map_author(CLAUDE[0], CLAUDE[1], "Anthropic")
        reasons = {}
        for value in ("unknown", "", "anthropic"):
            outcome = w.evaluate(w.review_request(obj, refs=["exec:claude"],
                                                  declaredAuthors=dict(vendors=[value], humanOnly=False)))
            first = [r for r in outcome["decision"]["items"] if r["item"] == rules.AUTHOR_VENDORS][0]
            self.assertEqual(first["result"], "FAIL")
            reasons[value] = first["reason"]["code"]
        self.assertEqual(reasons, {"unknown": "AUTHOR_VENDOR_UNKNOWN", "": "VENDOR_NOT_REGISTERED",
                                   "anthropic": "VENDOR_NOT_REGISTERED"})

    def test_human_only_with_and_without_fixed_evidence(self):
        """AC-02: a human-only Definition passes with fixed evidence and fails without it."""
        w = self.world
        obj = self.reviewable(identity=dict(humanOnly=True, agents=[], evidenceRefs=["evidence:human-authored"]))
        outcome = w.evaluate(w.review_request(obj))
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])
        self.assertTrue(outcome["decision"]["derived"]["humanOnly"])
        other = World(self.directory / "w2")
        obj2 = other.commit_definition()
        other.candidate(obj2, dict(humanOnly=True, agents=[], evidenceRefs=[]))
        other.formal(obj2)
        outcome = other.evaluate(other.review_request(obj2))
        self.assertEqual(code(outcome, rules.AUTHOR_VENDORS), ("FAIL", "HUMAN_EVIDENCE_MISSING"))

    def test_author_vendor_configuration_write_rules(self):
        """AC-02: config set author-vendor needs authority-ref, a closed-set vendor and non-empty identities; history kept."""
        w = self.world
        from domain.acceptance.accept import set_configuration
        with self.assertRaises(Rejection) as ctx:
            set_configuration(w.domain.store, "author-vendor", dict(agent="a", model="m", vendor="Anthropic"), "")
        self.assertEqual(ctx.exception.code, "AUTHORITY_MISSING")
        for bad in (dict(agent="a", model="m", vendor="anthropic"), dict(agent="", model="m", vendor="Anthropic"),
                    dict(agent="a", model=" ", vendor="Anthropic")):
            with self.assertRaises(Rejection):
                set_configuration(w.domain.store, "author-vendor", bad, OWNER)
        rc, doc = self.cli("config", "set", "author-vendor", "Anthropic", "--agent", CLAUDE[0], "--model", CLAUDE[1],
                           "--repository", str(w.repo), "--authority-ref", OWNER)
        self.assertEqual((rc, doc["result"]), (0, "CONFIGURED"), doc)
        config = w.state()["configuration"]
        self.assertEqual(config["authorVendors"][CLAUDE[0]][CLAUDE[1]], "Anthropic")
        self.assertEqual(config["history"][-1]["field"], "authorVendors")
        self.assertEqual(config["history"][-1]["authorityRef"], OWNER)

    # -- AC-03 --------------------------------------------------------------------------------------
    def test_capability_admission_matrix(self):
        """AC-03: REGISTERED refused; CONFIGURED/UNVERIFIED/PROBED need formal; REVIEW_ENABLED admits; binding mismatch degrades."""
        w = self.world
        obj = self.reviewable(formal=False)
        results = {}
        for status in ("REGISTERED", "CONFIGURED", "UNVERIFIED", "PROBED", "REVIEW_ENABLED"):
            w.registry = synthetic_registry(status=status)
            results[status] = code(w.evaluate(w.review_request(obj)), rules.REVIEWER_ELIGIBILITY)
        self.assertEqual(results["REGISTERED"], ("FAIL", "CAPABILITY_NOT_CONFIGURED"))
        for status in ("CONFIGURED", "UNVERIFIED", "PROBED"):
            self.assertEqual(results[status], ("FAIL", "FORMAL_AUTHORIZATION_REQUIRED"))
        self.assertEqual(results["REVIEW_ENABLED"], ("PASS", None))
        w.registry = synthetic_registry(status="REVIEW_ENABLED")
        mismatch = w.evaluate(w.review_request(obj, intent=w.review_intent(effort="low")))
        self.assertEqual(code(mismatch, rules.REVIEWER_ELIGIBILITY), ("FAIL", "FORMAL_AUTHORIZATION_REQUIRED"))

    def test_formal_fact_admits_and_is_recorded(self):
        """AC-03 AC-06: with an Owner formal authorization fact a CONFIGURED port passes and the record cites the fact."""
        w = self.world
        obj = self.reviewable(formal=False)
        w.formal(obj, fact_id="formal-9")
        outcome = w.evaluate(w.review_request(obj))
        self.assertEqual(code(outcome, rules.REVIEWER_ELIGIBILITY), ("PASS", None))
        self.assertIn("formal-9", outcome["decision"]["authorizationRefs"])
        self.assertTrue(outcome["decision"]["derived"]["ownerFormal"])

    def test_embedded_and_standalone_do_not_substitute(self):
        """AC-03 AC-05: a request from the standalone entry against the embedded port is refused, and vice versa."""
        w = self.world
        w.registry = synthetic_registry(standalone=True)
        obj = self.reviewable()
        outcome = w.evaluate(w.review_request(obj, entry="standalone"))
        self.assertEqual(code(outcome, rules.REVIEWER_ELIGIBILITY), ("FAIL", "ENTRY_MISMATCH"))
        self.assertEqual(code(outcome, rules.PROFILE_PURPOSE_ENTRY), ("FAIL", "PORT_MODE_MISMATCH"))
        w.formal(obj, fact_id="formal-s", port="standalone")
        intent = w.review_intent(port="standalone")
        outcome = w.evaluate(w.review_request(obj, intent=intent, entry="embedded"))
        self.assertEqual(code(outcome, rules.REVIEWER_ELIGIBILITY), ("FAIL", "ENTRY_MISMATCH"))
        outcome = w.evaluate(w.review_request(obj, intent=intent, entry="standalone"))
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])

    def test_live_registry_is_only_read(self):
        """AC-03: evaluations with the production loader read the bound repository's Registry and leave it unchanged.

        feature-t3 integration (coordinator ruling): the one Registry source is the review-channel Registry in the
        product-line repository the Runtime is bound to. The synthetic product line therefore carries a copy of the
        hp live Registry whose provider capabilities are CONFIGURED (their Receipt evidence lives only in hp).
        """
        live = json.loads(policy_inputs.REGISTRY_FILE.read_text())
        for provider in live["providers"].values():
            for model in provider["models"].values():
                model["capability"] = dict(status="CONFIGURED", note="synthetic copy; evidence stays in hp")
        bound = policy_inputs.bound_registry_path(self.world.repo)
        bound.parent.mkdir(parents=True, exist_ok=True)
        bound.write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n")
        git(self.world.repo, "add", "-A")
        git(self.world.repo, "commit", "-q", "-m", "synthetic bound registry")
        before = hashlib.sha256(bound.read_bytes()).hexdigest()
        hp_before = hashlib.sha256(policy_inputs.REGISTRY_FILE.read_bytes()).hexdigest()
        w = self.world
        obj = self.reviewable()
        w.use_production_sources()
        outcome = w.evaluate(w.review_request(obj))
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])
        registry = [r for r in outcome["decision"]["inputs"] if r["role"] == "registry"][0]
        self.assertFalse(registry["synthetic"])
        self.assertEqual(Path(registry["ref"]).resolve(), bound.resolve())
        self.assertEqual(hashlib.sha256(bound.read_bytes()).hexdigest(), before)
        self.assertEqual(hashlib.sha256(policy_inputs.REGISTRY_FILE.read_bytes()).hexdigest(), hp_before)

    # -- AC-04 --------------------------------------------------------------------------------------
    def test_input_evidence_missing_digest_and_ambiguous(self):
        """AC-04: missing bytes, digest mismatch and an ambiguous author identity are each distinguishable; none is a pass."""
        w = self.world
        obj = self.reviewable()
        wrong = dict(obj, sha256="0" * 64)
        outcome = w.evaluate(w.review_request(wrong))
        self.assertEqual(code(outcome, rules.INPUT_EVIDENCE), ("FAIL", "EVIDENCE_DIGEST_MISMATCH"))
        missing = dict(obj, path="tasks/feature-t0/absent.md")
        outcome = w.evaluate(w.review_request(missing))
        self.assertEqual(code(outcome, rules.INPUT_EVIDENCE), ("FAIL", "EVIDENCE_MISSING"))
        outcome = w.evaluate(w.review_request(obj, refs=["exec:absent"]))
        self.assertEqual(outcome["conclusion"], "DENY")
        self.assertEqual(code(outcome, rules.INPUT_EVIDENCE), ("FAIL", "EVIDENCE_MISSING"))
        w.candidate(obj, dict(humanOnly=False, agents=[dict(agent=CODEX[0], model=CODEX[1])], evidenceRefs=["e:2"]))
        outcome = w.evaluate(w.review_request(obj))
        self.assertEqual(code(outcome, rules.INPUT_EVIDENCE), ("NOT_CHECKED", "EVIDENCE_AMBIGUOUS"))
        self.assertNotEqual(outcome["conclusion"], "ALLOW")

    def test_implement_and_push_evidence(self):
        """AC-04: implement release checks the Definition and its finalization pin; push checks the candidate commit."""
        w = self.world
        w.registration = implementer_registration()
        obj = w.commit_definition()
        final = w.commit_finalization(obj, pin="tasks/feature-t0/feature-t0.md · 1 bytes · SHA-256 " + "0" * 64)
        w.to_implement("i")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.INPUT_EVIDENCE), ("FAIL", "EVIDENCE_DIGEST_MISMATCH"))
        outcome = w.evaluate(w.push_request(candidateCommit="1" * 40))
        self.assertEqual(code(outcome, rules.INPUT_EVIDENCE), ("FAIL", "EVIDENCE_MISSING"))

    # -- AC-05 --------------------------------------------------------------------------------------
    def test_purpose_mode_and_digest(self):
        """AC-05: purpose, port mode and profile digest mismatches each FAIL."""
        w = self.world
        obj = self.reviewable()
        intent = w.review_intent()
        intent["profile"]["purpose"] = "coding-implementer"
        outcome = w.evaluate(w.review_request(obj, intent=intent))
        self.assertEqual(code(outcome, rules.PROFILE_PURPOSE_ENTRY), ("FAIL", "PURPOSE_MISMATCH"))
        intent = w.review_intent()
        intent["profile"]["digest"] = "9" * 64
        outcome = w.evaluate(w.review_request(obj, intent=intent))
        self.assertEqual(code(outcome, rules.PROFILE_PURPOSE_ENTRY), ("FAIL", "PROFILE_NOT_REGISTERED"))

    def test_program_identity_change_does_not_fail(self):
        """AC-05: a new programIdentity (version upgrade) with the same profile digest, purpose and operations does not FAIL."""
        w = self.world
        obj = self.reviewable()
        intent = w.review_intent()
        intent["profile"]["programIdentity"] = dict(launcher="/new/codex", binaryDigest="f" * 64, version="9.9.9")
        outcome = w.evaluate(w.review_request(obj, intent=intent))
        self.assertEqual(code(outcome, rules.PROFILE_PURPOSE_ENTRY), ("PASS", None))
        self.assertEqual(outcome["conclusion"], "ALLOW")

    def test_implementer_registration_reader(self):
        """AC-05: without feature-t4's registration the implement release is NOT_CHECKED; with a synthetic one it passes."""
        w = self.world
        obj = w.commit_definition()
        final = w.commit_finalization(obj)
        w.to_implement("i")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.PROFILE_PURPOSE_ENTRY), ("NOT_CHECKED", "PORT_REGISTRATION_UNAVAILABLE"))
        self.assertEqual(outcome["conclusion"], "NOT_DETERMINABLE")
        w.registration = implementer_registration()
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])
        w.registration = implementer_registration(mode="standalone")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.PROFILE_PURPOSE_ENTRY), ("FAIL", "PORT_MODE_MISMATCH"))

    def test_trust_boundary_is_the_profile_declaration_only(self):
        """AC-05: the record carries the profile's declared trust boundary and makes no isolation or blocking claim."""
        w = self.world
        obj = self.reviewable()
        outcome = w.evaluate(w.review_request(obj))
        boundary = outcome["decision"]["trustBoundary"]
        self.assertEqual(boundary["source"], "profile-declaration")
        self.assertEqual(boundary["trustModel"], "current-user")
        self.assertTrue(boundary["limitations"])
        text = json.dumps(outcome, ensure_ascii=False).lower()
        for claim in ("isolat", "隔离", "sandboxed", "mechanically block", "机械阻断"):
            self.assertNotIn(claim, text)

    # -- AC-06 --------------------------------------------------------------------------------------
    def test_implement_authority_after_authorize_and_freeze(self):
        """AC-06: Authorize & Freeze consumed by its own progression is the authority at the implementation position."""
        w = self.world
        w.registration = implementer_registration()
        obj = w.commit_definition()
        final = w.commit_finalization(obj)
        w.to_implement("i")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("PASS", None))
        self.assertTrue(outcome["decision"]["authorizationRefs"][0].endswith(":decision"))

    def test_implement_authority_across_continue_loop(self):
        """AC-06: a Verification escalation Continue on the path back is itself a consumed Human decision; the chain still reaches Authorize & Freeze."""
        w = self.world
        w.registration = implementer_registration()
        obj = w.commit_definition()
        final = w.commit_finalization(obj)
        w.to_implement("i")
        for edge in ("E-I01", "E-I02", "E-I03", "E-I04", "E-I07", "E-I10"):
            w.advance(edge, "l")
        w.decide("Continue", "cont")
        w.advance("E-I13", "l")
        w.advance("E-I14", "l")
        self.assertEqual(w.inst()["position"], "N-IMPL-EXECUTE")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("PASS", None))
        self.assertEqual(len(outcome["decision"]["authorizationRefs"]), 2)

    def test_gate_passed_without_decision_and_stale_position(self):
        """AC-06: a Human Gate passed by a generic advance without a decision is AUTHORITY_MISSING; a wrong position is AUTHORITY_STALE."""
        w = self.world
        w.registration = implementer_registration()
        obj = w.commit_definition()
        final = w.commit_finalization(obj)
        w.to_definition_gate("g")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("FAIL", "AUTHORITY_STALE"))
        w.advance("E-D09", "g")
        w.advance("E-D17", "g")
        outcome = w.evaluate(w.implement_request(obj, final))
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("FAIL", "AUTHORITY_MISSING"))

    def test_self_reported_formal_flag_is_not_authority(self):
        """AC-06: the intent's formal_review_authorized_by_owner=true without an Owner formal fact is not authority."""
        w = self.world
        obj = self.reviewable(formal=False)
        intent = w.review_intent(formal_review_authorized_by_owner=True)
        outcome = w.evaluate(w.review_request(obj, intent=intent))
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("FAIL", "FORMAL_AUTHORIZATION_REQUIRED"))
        w.formal(obj, fact_id="formal-other", digest="7" * 64)
        outcome = w.evaluate(w.review_request(obj, intent=intent))
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("FAIL", "FORMAL_AUTHORIZATION_REQUIRED"))

    def test_push_authority_and_stale(self):
        """AC-06: Publish authorization and Validation Accept With reservation authorize a push; at the gate itself it is stale."""
        w = self.world
        w.to_publish_gate("p")
        outcome = w.evaluate(w.push_request())
        self.assertEqual(code(outcome, rules.HUMAN_AUTHORITY), ("FAIL", "AUTHORITY_STALE"))
        binding = dict(candidateCommit=w.head_commit(), sourceBranch=w.state()["tasks"][TASK]["branch"], remote="origin",
                       targetBranch="main")
        w.gate_decision_with_binding("E-V06", "Publish authorization", "pub", binding)
        outcome = w.evaluate(w.push_request())
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])
        other = World(self.directory / "w2")
        other.to_implement("i")
        for edge in ("E-I01", "E-I02", "E-I03", "E-I05", "E-V01", "E-V03", "E-V05", "E-V09"):
            other.advance(edge, "v")
        binding2 = dict(binding, candidateCommit=other.head_commit(), sourceBranch=other.state()["tasks"][TASK]["branch"])
        other.gate_decision_with_binding("E-V12", "Accept With reservation", "res", binding2)
        other.advance("E-V14", "v")
        outcome = other.evaluate(other.push_request())
        self.assertEqual(outcome["conclusion"], "ALLOW", outcome["decision"]["items"])

    # -- AC-07 --------------------------------------------------------------------------------------
    def test_exact_push_binding(self):
        """AC-07: every push field must equal the authorized binding and the bound Task Branch; refs stay untouched."""
        w = self.world
        remote = self.directory / "remote.git"
        git(self.directory, "init", "-q", "--bare", str(remote))
        def branch_refs():
            # refs/harness/runtime is the domain state ref and changes with every record; branches and the remote must not.
            return (git(w.repo, "for-each-ref", "refs/heads", "refs/tags", "refs/remotes"), git(remote, "for-each-ref"))
        refs_before = branch_refs()
        w.to_publish_gate("p")
        task = w.state()["tasks"][TASK]
        binding = dict(candidateCommit=w.head_commit(), sourceBranch=task["branch"], remote="origin", targetBranch="main")
        w.gate_decision_with_binding("E-V06", "Publish authorization", "pub", binding)
        self.assertEqual(w.evaluate(w.push_request())["conclusion"], "ALLOW")
        for field, value in (("targetBranch", "release"), ("remote", "upstream"), ("candidateCommit", "e" * 40)):
            outcome = w.evaluate(w.push_request(**{field: value}))
            self.assertEqual(code(outcome, rules.PUSH_PERMIT_ITEM), ("FAIL", "PUSH_BINDING_MISMATCH"), field)
        outcome = w.evaluate(w.push_request(repositoryIdentity="git-root:other"))
        self.assertEqual(code(outcome, rules.PUSH_PERMIT_ITEM), ("FAIL", "TASK_BRANCH_MISMATCH"))
        self.assertEqual(branch_refs(), refs_before)

    def test_publish_without_binding_is_missing_authorization(self):
        """AC-07: a Publish authorization made through decide() carries no binding yet, so the push is refused."""
        w = self.world
        w.to_publish_gate("p")
        w.decide("Publish authorization", "pub")
        outcome = w.evaluate(w.push_request())
        self.assertEqual(code(outcome, rules.PUSH_PERMIT_ITEM), ("FAIL", "PUSH_AUTHORIZATION_MISSING"))

    # -- AC-08 --------------------------------------------------------------------------------------
    def test_budget_fields(self):
        """AC-08: missing, non-positive, over-limit, dollar-cap and maxCalls cases FAIL; no dollar cap is required."""
        w = self.world
        obj = self.reviewable()
        cases = {
            "BUDGET_MISSING": dict(maxToolCalls=20, maxRunSeconds=600),
            "BUDGET_FIELD_NOT_ALLOWED": dict(maxToolCalls=20, maxRunSeconds=600, maxOutputBytes=1, cleanupSeconds=1,
                                             costCapUsd=5),
            "BUDGET_EXCEEDS_LIMIT": dict(maxToolCalls=21, maxRunSeconds=600, maxOutputBytes=1, cleanupSeconds=1),
        }
        for expected, budget in cases.items():
            outcome = w.evaluate(w.review_request(obj, intent=w.review_intent(budget=budget)))
            self.assertEqual(code(outcome, rules.BUDGET), ("FAIL", expected), budget)
        zero = w.evaluate(w.review_request(obj, intent=w.review_intent(
            budget=dict(maxToolCalls=0, maxRunSeconds=600, maxOutputBytes=1, cleanupSeconds=1))))
        self.assertEqual(code(zero, rules.BUDGET), ("FAIL", "BUDGET_MISSING"))
        calls = w.evaluate(w.review_request(obj, maxCalls=3))
        self.assertEqual(code(calls, rules.BUDGET), ("FAIL", "BUDGET_EXCEEDS_LIMIT"))
        self.assertEqual(w.evaluate(w.review_request(obj))["conclusion"], "ALLOW")

    def test_review_rounds(self):
        """AC-08: delivered rounds reaching the allowed rounds FAIL; unreadable round facts are NOT_CHECKED."""
        w = self.world
        obj = self.reviewable()
        w.rounds = dict(submitted=2, allowed=2, exhausted=True, source="synthetic")
        self.assertEqual(code(w.evaluate(w.review_request(obj)), rules.BUDGET), ("FAIL", "ROUND_BUDGET_EXHAUSTED"))
        w.rounds = policy_inputs.InputsUnavailable("ROUND_FACTS_UNREADABLE", "synthetic")
        self.assertEqual(code(w.evaluate(w.review_request(obj)), rules.BUDGET), ("NOT_CHECKED", "ROUND_FACTS_UNREADABLE"))

    def test_call_count_reads_the_port_counter_only(self):
        """AC-08 AC-09: once the port's persisted count reaches maxCalls, a new call is refused with its own DENY record; no second counter."""
        w = self.world
        obj = self.reviewable()
        request = w.review_request(obj)
        base = w.evaluate(request)
        self.assertEqual(base["conclusion"], "ALLOW")
        import hashlib as _h
        from runtime.protocol import canonical
        key = _h.sha256(canonical(["scope:one", base["factId"]])).hexdigest()
        w.mutate(lambda s: s.setdefault("executionCallBudgets", {}).__setitem__(
            key, dict(limit=1, requests=["review-request:1"], synthetic=True)))
        again = w.evaluate(request, call=dict(executionRequestId="review-request:1", scopeRef="scope:one"))
        self.assertEqual(again["conclusion"], "ALLOW")
        second = w.review_request(obj, intent=w.review_intent(request_id="review-request:1:call:2"))
        refused = w.evaluate(second, call=dict(executionRequestId="review-request:1:call:2", scopeRef="scope:one"))
        self.assertEqual(refused["conclusion"], "DENY")
        self.assertEqual(refused["baseFactId"], base["factId"])
        self.assertEqual(refused["decision"]["items"][0]["reason"]["code"], "CALL_LIMIT_EXHAUSTED")
        self.assertEqual(list(w.state()["executionCallBudgets"]), [key])

    # -- AC-09 --------------------------------------------------------------------------------------
    def test_generic_fact_cannot_write_policy_decisions(self):
        """AC-09: the generic fact entry cannot write a policy-decision fact."""
        w = self.world
        with self.assertRaises(WorkflowRejection) as ctx:
            w.run("fact", fact=dict(factId="policy:forged", kind="policy-decision", purpose="push-permit",
                                    authorityRef=OWNER, payload=dict(conclusion="ALLOW")))
        self.assertEqual(ctx.exception.code, "TRIGGER_NOT_APPLICABLE")
        rc = subprocess.run([PY, "-B", str(APP / "hp.py"), "workflow", "fact", "--repository", str(w.repo), "--task-id",
                             TASK, "--authority-ref", OWNER, "--fact-id", "policy:forged2", "--kind", "policy-decision",
                             "--purpose", "push-permit"], capture_output=True, text=True).returncode
        self.assertEqual(rc, 1)
        self.assertNotIn("policy:forged2", w.inst()["facts"])

    def test_only_gate_produced_allow_triggers_progression(self):
        """AC-09: a DENY record or a policy-decision without the Policy Gate producer is refused as a trigger; an ALLOW record is accepted."""
        w = self.world
        w.advance("E-D01", "t")
        w.advance("E-D02", "t")
        w.settle("t")
        denied = w.evaluate(w.push_request())
        self.assertEqual(denied["conclusion"], "DENY")
        with self.assertRaises(WorkflowRejection) as ctx:
            w.run("advance", commandId="t-deny", edgeId="E-D04", triggers=[denied["factId"]], purpose="push-permit")
        self.assertEqual(ctx.exception.code, "TRIGGER_NOT_APPLICABLE")

        def forge(s):
            inst = s["tasks"][TASK]["workflowInstance"]
            inst["facts"]["policy:legacy"] = dict(factId="policy:legacy", kind="policy-decision", purpose="push-permit",
                                                  node=inst["position"], occurrence=progression.occurrence(inst, TASK),
                                                  authorityRef=OWNER, payload=dict(conclusion="ALLOW"),
                                                  recordedAt="synthetic", domainRevision=s["revision"], consumedBy=None)
        w.mutate(forge)
        with self.assertRaises(WorkflowRejection) as ctx:
            w.run("advance", commandId="t-forged", edgeId="E-D04", triggers=["policy:legacy"], purpose="push-permit")
        self.assertEqual(ctx.exception.code, "TRIGGER_NOT_APPLICABLE")

        def allow(s):
            inst = s["tasks"][TASK]["workflowInstance"]
            progression.record_fact(s, None, TASK, dict(factId="policy:gate-allow", kind="policy-decision",
                                                         purpose="push-permit", authorityRef=OWNER,
                                                         payload=dict(conclusion="ALLOW", synthetic=True)),
                                    revision=s["revision"], producer=progression.POLICY_PRODUCER)
        w.mutate(allow)
        done = w.run("advance", commandId="t-allow", edgeId="E-D04", triggers=["policy:gate-allow"], purpose="push-permit")
        self.assertEqual(done["result"], "ADVANCED")

    def test_record_is_immutable_and_workflow_does_not_move(self):
        """AC-09: evaluation leaves position, condition, lifecycle and Runtime Version unchanged; a factId cannot be rebound."""
        w = self.world
        obj = self.reviewable()
        before = {k: w.inst()[k] for k in ("position", "condition", "lifecycle", "runtimeVersion", "positionEntryRevision")}
        outcome = w.evaluate(w.review_request(obj))
        after = {k: w.inst()[k] for k in before}
        self.assertEqual(before, after)
        fact = w.inst()["facts"][outcome["factId"]]
        self.assertEqual(fact["producer"], "policy-gate")

        def rebind(s):
            progression.record_fact(s, None, TASK, dict(factId=outcome["factId"], kind="policy-decision",
                                                         purpose=rules.REVIEW_RELEASE, authorityRef=OWNER,
                                                         payload=dict(conclusion="DENY")),
                                    revision=s["revision"], producer=progression.POLICY_PRODUCER)
        with self.assertRaises(WorkflowRejection) as ctx:
            w.mutate(rebind)
        self.assertEqual(ctx.exception.code, "REQUEST_CONFLICT")

    def test_runtime_entry_and_cli_agree(self):
        """AC-09: the serve-stdio construction (entry=runtime, its control generation) via the callback and the CLI give one conclusion and one record."""
        w = self.world
        obj = self.reviewable()
        w.use_production_sources()
        request = w.review_request(obj)
        runtime = HarnessDomain(w.repo, entry="runtime")
        generation = runtime.acquire_generation()
        authorize = execution_authorizer(runtime, TASK, rules.REVIEW_RELEASE, "embedded", lambda: generation,
                                         context=lambda: {k: v for k, v in request.items()
                                                          if k not in ("schema", "subject", "taskId", "entry", "portId",
                                                                       "intent")})
        auth = asyncio.run(authorize(copy.deepcopy(request["intent"])))
        rc, doc = self.cli("policy", "evaluate", "--repository", str(w.repo), "--task-id", TASK, "--authority-ref",
                           "policy-gate:execution-authorizer", "--request", json.dumps(request))
        self.assertEqual((rc, doc["conclusion"]), (0, "ALLOW"), doc)
        self.assertEqual(doc["factId"], auth.authorization_ref)
        self.assertEqual(doc["result"], "IDEMPOTENT_REPLAY")
        self.assertEqual(auth.author_vendors, ("Anthropic",))
        self.assertTrue(auth.owner_formal)


class PortCase(unittest.IsolatedAsyncioTestCase):
    """AC-09: the production callback injected into the feature-t17 ports gates every release."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hp-t6-port-")
        self.directory = Path(self.temp.name)
        self.world = World(self.directory / "w", entry="runtime")
        w = self.world
        self.obj = w.commit_definition()
        w.candidate(self.obj, dict(humanOnly=False, agents=[dict(agent=CLAUDE[0], model=CLAUDE[1])], evidenceRefs=["e:1"]))
        w.map_author(CLAUDE[0], CLAUDE[1], "Anthropic")
        self.request = w.review_request(self.obj)
        from test_execution_port import SyntheticHost
        self.host = SyntheticHost(w.generation)

    def tearDown(self):
        self.temp.cleanup()

    def port(self, cls=HostExecutionPort, port_id="embedded"):
        w = self.world
        registry = w.registry["registry"]
        registration = copy.deepcopy(next(p for p in registry["execution_ports"] if p["id"] == port_id))
        mapping = copy.deepcopy(next(m for m in registry["model_mappings"] if m["id"] == registration["mapping_id"]))
        extra = {k: v for k, v in self.request.items() if k not in ("schema", "subject", "taskId", "entry", "portId", "intent")}
        authorize = execution_authorizer(w.domain, TASK, rules.REVIEW_RELEASE, registration["mode"], lambda: w.generation,
                                         context=lambda: extra)

        async def discover():
            return ExecutionDiscovery(copy.deepcopy(registration["profile"]), "connection:one", registration["provider"],
                                      "openai", registration["applicability"]["configurationRevision"])
        if cls is LocalExecutionPort:
            made = cls(w.domain, w.generation, w.repo, self.directory / "spool", registration, mapping, discover, authorize)
        else:
            made = cls(self.host, w.domain, registration, mapping, discover, authorize)
        made.bind_result_scanner(object(), lambda: ["synthetic-secret-never-present"])
        return made

    async def test_host_port_refuses_before_any_host_call(self):
        """AC-09: without an Owner formal fact the embedded port's preflight raises policy-denied and no Host method is called."""
        port = self.port()
        with self.assertRaises(ExecutionError) as ctx:
            await port.preflight(self.world.review_intent())
        self.assertEqual(ctx.exception.code, "policy-denied")
        self.assertEqual(self.host.methods, [])

    async def test_host_port_admits_and_rechecks(self):
        """AC-09: with the formal fact the preflight is authorized by a Policy Gate ALLOW; re-evaluation on query re-checks."""
        self.world.formal(self.obj)
        port = self.port()
        auth = await port.preflight(self.world.review_intent())
        self.assertTrue(auth.authorization_ref.startswith("policy:"))
        self.assertEqual(self.host.methods, ["host.execution.preflight"])
        fact = self.world.inst()["facts"][auth.authorization_ref]
        self.assertEqual((fact["producer"], fact["payload"]["conclusion"]), ("policy-gate", "ALLOW"))
        again = await port.authority(self.world.review_intent())
        self.assertEqual(again.authorization_ref, auth.authorization_ref)

    async def test_local_port_uses_the_same_callback(self):
        """AC-09: LocalExecutionPort reaches the same callback; a standalone release is refused without formal and admitted with it."""
        w = self.world
        w.registry = synthetic_registry(standalone=True)
        self.request = w.review_request(self.obj, intent=w.review_intent(port="standalone"), entry="standalone")
        port = self.port(LocalExecutionPort, "standalone")
        with self.assertRaises(ExecutionError) as ctx:
            await port.authority(w.review_intent(port="standalone"))
        self.assertEqual(ctx.exception.code, "policy-denied")
        w.formal(self.obj, fact_id="formal-s", port="standalone")
        auth = await port.authority(w.review_intent(port="standalone"))
        self.assertEqual(auth.author_vendors, ("Anthropic",))

    async def test_missing_context_is_not_determinable(self):
        """AC-09: a callback built without the request context cannot evaluate and refuses as not determinable."""
        w = self.world
        authorize = execution_authorizer(w.domain, TASK, rules.REVIEW_RELEASE, "embedded", lambda: w.generation)
        with self.assertRaises(ExecutionError) as ctx:
            await authorize(w.review_intent())
        self.assertEqual(ctx.exception.code, "policy-not-determinable")

    async def test_stale_generation_is_not_determinable(self):
        """AC-09: when another entry advanced the control generation, the callback refuses instead of releasing."""
        w = self.world
        w.formal(self.obj)
        stale = w.generation
        HarnessDomain(w.repo, entry="cli").bind_entry()
        extra = {k: v for k, v in self.request.items() if k not in ("schema", "subject", "taskId", "entry", "portId", "intent")}
        authorize = execution_authorizer(w.domain, TASK, rules.REVIEW_RELEASE, "embedded", lambda: stale, context=lambda: extra)
        with self.assertRaises(ExecutionError) as ctx:
            await authorize(w.review_intent())
        self.assertEqual(ctx.exception.code, "policy-not-determinable")


if __name__ == "__main__":
    unittest.main()
