"""feature-t2 Workflow domain tests on synthetic product lines. Docstrings carry the AC tags.

Every case uses a synthetic product-line repository carrying the product topology master byte for
byte. No real model, no remote operation, no write outside the temporary directory.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance.accept import accept_task
from domain.core import HarnessDomain, open_domain
from domain.workflow import recovery, results, states
from domain.workflow import topology as topology_module
from domain.workflow.results import WorkflowRejection
from product_line import TOPOLOGY, create_product_line, git
import guarded_walk  # feature-t5: SYNTHETIC direct walk through the budget node it narrows (test only)

APP = Path(__file__).resolve().parents[1]
PY = sys.executable
OWNER = "owner:synthetic"


class WorkflowCase(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-t2-tests-")
            self.directory = Path(self.temp.name)
        self.worktrees = self.directory / "worktrees"

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    # -- fixtures -------------------------------------------------------------------------------
    def accepted(self, name="repo", task_id="feature-t0", **kw):
        """A synthetic product line with one accepted Task and a bound Domain Core."""
        repo, head = create_product_line(self.directory / name, **kw)
        domain = HarnessDomain(repo, entry="cli")
        generation = domain.bind_entry()
        outcome = accept_task(domain.store, dict(requestId="req-1", repository=str(repo), taskType="feature",
                                                 taskId=task_id, baseRef="main", worktreeRoot=str(self.worktrees / name),
                                                 authorityRef=OWNER))
        self.assertEqual(outcome["result"], "ACCEPTED")
        return repo, head, domain, generation

    def run_command(self, domain, generation, name, **payload):
        payload.setdefault("taskId", "feature-t0")
        payload.setdefault("authorityRef", OWNER)
        return domain.run(name, payload, generation=generation)

    def reject(self, domain, generation, name, code, **payload):
        with self.assertRaises(WorkflowRejection) as ctx:
            self.run_command(domain, generation, name, **payload)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception

    def facts(self, domain):
        return domain.status("feature-t0")["tasks"][0]

    def walk_to_gate(self, domain, generation, tag="w"):
        """Drive the definition lane from the initial position to the Definition authorization gate."""
        self.run_command(domain, generation, "condition", commandId=tag + "1", condition=states.RESULT_RECORDED)
        self.run_command(domain, generation, "advance", commandId=tag + "2", edgeId="E-D01")
        self.run_command(domain, generation, "advance", commandId=tag + "3", edgeId="E-D02")
        self.run_command(domain, generation, "condition", commandId=tag + "4", condition=states.EXECUTING)
        self.run_command(domain, generation, "condition", commandId=tag + "5", condition=states.RESULT_RECORDED)
        self.run_command(domain, generation, "advance", commandId=tag + "6", edgeId="E-D04")
        self.run_command(domain, generation, "condition", commandId=tag + "7", condition=states.AWAITING_HUMAN_ACTION)
        return self.facts(domain)

    # -- AC-01 ----------------------------------------------------------------------------------
    def test_bound_topology_registers_nodes_edges_and_semantic_types(self):
        """AC-01: the bound topology is read from the master and every edge connects registered nodes."""
        bound = topology_module.parse(TOPOLOGY.read_bytes())
        counts = bound.counts()
        self.assertEqual(counts["nodes"], 35)
        self.assertEqual(counts["edges"], 45)
        for node in bound.nodes.values():
            self.assertIn(node["semanticType"], topology_module.SEMANTIC_TYPES)
        for edge in bound.edges.values():
            self.assertTrue(bound.has_node(edge["source"]) and bound.has_node(edge["target"]), edge)
        self.assertEqual(bound.semantic_type("N-DEF-HUMAN"), "HUMAN_ACTION")
        self.assertEqual(bound.semantic_type(states.PUBLISH_NODE), "ENGINEERING_MODULE")

    def test_unreadable_topology_is_reported_not_guessed(self):
        """AC-01: a Workflow Instance whose bound topology cannot be read stops instead of guessing."""
        repo, head, domain, generation = self.accepted(workflow="stub")
        self.reject(domain, generation, "condition", results.TOPOLOGY_UNREADABLE, commandId="c1",
                    condition=states.RESULT_RECORDED)
        self.assertEqual(domain.status("feature-t0")["tasks"][0]["topology"], "unreadable")

    def test_initial_layered_state_and_occurrence(self):
        """AC-01: acceptance leaves ACTIVE, N-DEF-HUMAN, AWAITING_HUMAN_ACTION with a readable occurrence."""
        repo, head, domain, generation = self.accepted()
        facts = self.facts(domain)
        self.assertEqual((facts["lifecycle"], facts["position"], facts["condition"]),
                         (states.ACTIVE, "N-DEF-HUMAN", states.AWAITING_HUMAN_ACTION))
        self.assertEqual(facts["semanticType"], "HUMAN_ACTION")
        self.assertEqual(facts["occurrence"]["workflowInstance"], "feature-t0")
        self.assertEqual(facts["occurrence"]["node"], "N-DEF-HUMAN")
        self.assertEqual(facts["runtimeVersion"], "1")
        self.assertEqual(facts["attempt"], None)

    def test_illegal_combination_and_illegal_edge_are_refused(self):
        """AC-01: a combination outside the matrix and an edge that does not leave the node are refused."""
        repo, head, domain, generation = self.accepted()
        # HUMAN_ACTION has no EXECUTING row, and the standard path does not offer it either.
        self.reject(domain, generation, "condition", results.ILLEGAL_TRANSITION, commandId="c1", condition=states.EXECUTING)
        self.reject(domain, generation, "advance", results.ILLEGAL_TRANSITION, commandId="c2", edgeId="E-V06")
        self.assertFalse(states.legal(states.ACTIVE, "N-DEF-HUMAN", "HUMAN_ACTION", states.EXECUTING))
        self.assertFalse(states.legal(states.ACTIVE, "N-DEF-CANDIDATE", "ARTIFACT", states.ENTERED))
        self.assertFalse(states.legal(states.ACTIVE, states.PUBLISH_NODE, "ENGINEERING_MODULE", states.RESULT_RECORDED))
        self.assertFalse(states.legal(states.ACTIVE, "N-DEF-CLOSE", states.TERMINAL_DECISION, states.RESULT_RECORDED))
        self.assertTrue(states.legal(states.CLOSED, "N-DEF-CLOSE", states.TERMINAL_DECISION, states.RESULT_RECORDED))

    def test_loop_re_entry_forms_a_new_occurrence_and_old_triggers_do_not_carry(self):
        """AC-01: returning to the same node forms a new occurrence; the earlier trigger is not consumable there."""
        # The definition review loop re-enters N-DEF-REVIEW-DISPATCH through E-D11.
        repo2, head2, d2, g2 = self.accepted()
        self.run_command(d2, g2, "condition", commandId="a1", condition=states.RESULT_RECORDED)
        self.run_command(d2, g2, "advance", commandId="a2", edgeId="E-D01")
        self.run_command(d2, g2, "advance", commandId="a3", edgeId="E-D02")
        self.run_command(d2, g2, "condition", commandId="a4", condition=states.EXECUTING)
        self.run_command(d2, g2, "condition", commandId="a5", condition=states.RESULT_RECORDED)
        self.run_command(d2, g2, "advance", commandId="a6", edgeId="E-D03")
        first = self.facts(d2)["occurrence"]
        self.run_command(d2, g2, "fact", fact=dict(factId="f1", kind="configuration-decision", purpose="dispatch",
                                                   authorityRef=OWNER))
        self.run_command(d2, g2, "condition", commandId="a7", condition=states.EXECUTING)
        self.run_command(d2, g2, "condition", commandId="a8", condition=states.RESULT_RECORDED)
        self.run_command(d2, g2, "advance", commandId="a9", edgeId="E-D05", triggers=["f1"], purpose="dispatch")
        for command, edge in (("a10", "E-D06"),):
            self.run_command(d2, g2, "condition", commandId=command + "c1", condition=states.EXECUTING)
            self.run_command(d2, g2, "condition", commandId=command + "c2", condition=states.RESULT_RECORDED)
            self.run_command(d2, g2, "advance", commandId=command, edgeId=edge)
        self.run_command(d2, g2, "condition", commandId="a11", condition=states.EXECUTING)
        self.run_command(d2, g2, "condition", commandId="a12", condition=states.RESULT_RECORDED)
        self.run_command(d2, g2, "advance", commandId="a13", edgeId="E-D08")
        guarded_walk.settle_and_advance(d2, g2, "feature-t0", "a16", "E-D11", OWNER)
        second = self.facts(d2)["occurrence"]
        self.assertEqual(first["node"], second["node"])
        self.assertNotEqual(first["positionEntryRuntimeVersion"], second["positionEntryRuntimeVersion"])
        self.run_command(d2, g2, "condition", commandId="a17", condition=states.EXECUTING)
        self.run_command(d2, g2, "condition", commandId="a18", condition=states.RESULT_RECORDED)
        self.reject(d2, g2, "advance", results.TRIGGER_NOT_APPLICABLE, commandId="a19", edgeId="E-D05",
                    triggers=["f1"], purpose="dispatch")

    # -- AC-03 ----------------------------------------------------------------------------------
    def test_bootstrap_and_binding_are_shared_common_dir_members(self):
        """AC-03: bootstrap and binding live under the common dir and name the current control generation."""
        repo, head, domain, generation = self.accepted()
        common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        self.assertTrue((common / "harness" / "writer.lock").is_file())
        bootstrap = json.loads((common / "harness" / "bootstrap.json").read_text())
        self.assertEqual(bootstrap["ref"], "refs/harness/runtime")
        self.assertEqual(bootstrap["repositoryIdentity"], sorted(git(repo, "rev-list", "--max-parents=0", "HEAD").split()))
        binding = json.loads((common / "harness" / "binding.json").read_text())
        self.assertEqual((binding["entry"], binding["controlGeneration"]), ("cli", generation))
        # Nothing was added to the working tree: the coordination surface is inside the common dir.
        self.assertEqual(git(repo, "status", "--porcelain"), "")

    def test_stale_control_generation_may_not_commit(self):
        """AC-03: after another entry takes the control generation, the older one is refused, distinguishably."""
        repo, head, domain, generation = self.accepted()
        other = HarnessDomain(repo, entry="runtime")
        newer = other.bind_entry()
        self.assertNotEqual(newer, generation)
        self.reject(domain, generation, "condition", results.STALE_CONTROL_GENERATION, commandId="c1",
                    condition=states.RESULT_RECORDED)
        # The current generation still commits, and the refusal is not a version conflict.
        outcome = other.run("condition", dict(taskId="feature-t0", authorityRef=OWNER, commandId="c2",
                                              condition=states.RESULT_RECORDED), generation=newer)
        self.assertEqual(outcome["result"], results.CONDITION_UPDATED)
        self.reject(other, newer, "condition", results.VERSION_CONFLICT, commandId="c3",
                    condition=states.RESULT_RECORDED, expectedRuntimeVersion="1")

    def test_writer_lock_serialises_and_reports_an_unavailable_lock(self):
        """AC-03: one writer lock; a second writer waits, and with a bounded wait reports LOCK_UNAVAILABLE."""
        repo, head, domain, generation = self.accepted()
        holder = domain.store._locked()
        try:
            with self.assertRaises(WorkflowRejection) as ctx:
                domain.run("condition", dict(taskId="feature-t0", authorityRef=OWNER, commandId="c1",
                                             condition=states.RESULT_RECORDED), generation=generation, lock_wait=0.2)
            self.assertEqual(ctx.exception.code, results.LOCK_UNAVAILABLE)
        finally:
            holder.close()
        released = self.run_command(domain, generation, "condition", commandId="c2", condition=states.RESULT_RECORDED)
        self.assertEqual(released["result"], results.CONDITION_UPDATED)

    def test_lock_and_generation_rebuild_from_the_repository_after_a_kill(self):
        """AC-03: the coordination facts survive a killed writer; a fresh process reads them from the repository."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RESULT_RECORDED)
        script = ("import sys; sys.path.insert(0, %r);\n"
                  "from domain.core import HarnessDomain\n"
                  "d = HarnessDomain(%r, entry='cli')\n"
                  "print(d.store.read()['generation'], d.store.binding()['controlGeneration'],"
                  " d.status('feature-t0')['tasks'][0]['runtimeVersion'])\n" % (str(APP), str(repo)))
        out = subprocess.run([PY, "-B", "-c", script], capture_output=True, text=True, cwd=APP)
        self.assertEqual(out.returncode, 0, out.stderr)
        stored, bound, version = out.stdout.split()
        self.assertEqual(stored, generation)
        self.assertEqual(bound, generation)
        self.assertEqual(version, "2")

    # -- AC-04 ----------------------------------------------------------------------------------
    def test_domain_ref_moved_inside_the_lock_is_reported_as_drift(self):
        """AC-04: a non-cooperating change to the domain ref inside a held lock stops the writer as drift."""
        repo, head, domain, generation = self.accepted()
        moved = []

        def observer(phase, detail=None):
            if phase == "before-commit" and not moved:
                moved.append(git(repo, "commit-tree", git(repo, "rev-parse", "HEAD^{tree}"), "-m", "external"))
                git(repo, "update-ref", "refs/harness/runtime", moved[0])
        domain.store.observer = observer
        exc = self.reject(domain, generation, "condition", results.EXTERNAL_DRIFT, commandId="c1",
                          condition=states.RESULT_RECORDED)
        self.assertEqual(exc.detail["surface"], "refs/harness/runtime")
        self.assertEqual(exc.detail["observed"], moved[0])
        self.assertNotEqual(exc.detail["expected"], exc.detail["observed"])
        # Nothing was rolled back or synthesised: the ref still holds what the external writer left.
        self.assertEqual(git(repo, "rev-parse", "refs/harness/runtime"), moved[0])

    def test_coordination_surface_drift_is_distinct_from_a_version_conflict(self):
        """AC-04: bootstrap and binding drift stop the writer, with codes distinct from VERSION_CONFLICT."""
        repo, head, domain, generation = self.accepted()
        common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "harness"
        bootstrap = json.loads((common / "bootstrap.json").read_text())
        (common / "bootstrap.json").write_text(json.dumps(dict(bootstrap, ref="refs/harness/other")))
        exc = self.reject(domain, generation, "condition", results.EXTERNAL_DRIFT, commandId="c1",
                          condition=states.RESULT_RECORDED)
        self.assertEqual(exc.detail["surface"], "bootstrap.ref")
        (common / "bootstrap.json").write_text(json.dumps(bootstrap))
        (common / "binding.json").unlink()
        exc = self.reject(domain, generation, "condition", results.EXTERNAL_DRIFT, commandId="c2",
                          condition=states.RESULT_RECORDED)
        self.assertEqual(exc.detail["surface"], "binding")
        self.assertNotEqual(results.EXTERNAL_DRIFT, results.VERSION_CONFLICT)
        self.assertEqual(results.exit_code(results.EXTERNAL_DRIFT), 2)
        self.assertEqual(results.exit_code(results.VERSION_CONFLICT), 1)

    # -- AC-05 ----------------------------------------------------------------------------------
    def test_legal_decision_sets_are_derived_from_the_gate_position(self):
        """AC-05: each Human Gate offers exactly the decisions spec FR-26 names; other positions offer none."""
        bound = topology_module.parse(TOPOLOGY.read_bytes())
        expected = {
            "N-DEF-AUTH-GATE": {"Authorize & Freeze"},
            "N-DEF-ESCALATION-GATE": {"Continue", "Close Task", "Accept With reservation"},
            "N-VERIFY-ESCALATION-GATE": {"Continue", "Close Task"},
            "N-VALIDATE-ESCALATION-GATE": {"Continue", "Close Task", "Accept With reservation"},
            "N-PUBLISH-AUTH-GATE": {"Publish authorization"},
        }
        gates = {n for n, v in bound.nodes.items() if v["semanticType"] == "HUMAN_GATE"}
        self.assertEqual(gates, set(expected))
        for node, decisions in expected.items():
            self.assertEqual({d["decision"] for d in topology_module.decision_set(bound, node)}, decisions)
        for node in ("N-DEF-HUMAN", "N-DEF-CANDIDATE", states.PUBLISH_NODE):
            self.assertEqual(topology_module.decision_set(bound, node), [])

    def test_decision_outside_the_legal_set_is_refused(self):
        """AC-05: a decision the current position does not offer is refused by the domain."""
        repo, head, domain, generation = self.accepted()
        self.reject(domain, generation, "decide", results.DECISION_NOT_LEGAL_HERE, commandId="c1",
                    decision="Authorize & Freeze")
        self.walk_to_gate(domain, generation)
        self.reject(domain, generation, "decide", results.DECISION_NOT_LEGAL_HERE, commandId="c2",
                    decision="Publish authorization")
        # feature-t3 narrows the generic decide: Authorize & Freeze freezes the Definition and must come
        # with a finalization ruling, so the generic entry refuses it with a distinguishable reason.
        refused = self.reject(domain, generation, "decide", results.DECISION_NOT_LEGAL_HERE, commandId="c3",
                              decision="Authorize & Freeze")
        self.assertTrue(refused.detail["definitionEntryRequired"])
        self.assertEqual(self.facts(domain)["position"], "N-DEF-AUTH-GATE")
        self.assertEqual(self.facts(domain)["decisions"], [])

    def test_close_at_any_time_is_one_atomic_commit_and_stops_progression(self):
        """AC-05: closing anywhere lands CLOSED + RESULT_RECORDED in one commit and blocks any further progression."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "attempt-open", attemptId="att-1", purpose="node-work")
        before = self.facts(domain)["commits"]
        outcome = self.run_command(domain, generation, "close", commandId="c1", reasonCategory="human-initiated")
        self.assertEqual(outcome["result"], results.FINALIZED)
        facts = self.facts(domain)
        self.assertEqual((facts["lifecycle"], facts["condition"]), (states.CLOSED, states.RESULT_RECORDED))
        self.assertEqual(facts["position"], "N-DEF-HUMAN")
        self.assertEqual(facts["commits"], before + 1)
        self.assertEqual(outcome["commit"]["transitionKind"], states.LIFECYCLE_FINALIZATION)
        self.assertEqual(facts["closure"]["reasonCategory"], "human-initiated")
        self.assertEqual(facts["closure"]["kind"], "power-action")
        state = domain.store.read()
        self.assertEqual(state["tasks"]["feature-t0"]["terminal"]["kind"], "closed")
        attempt = state["tasks"]["feature-t0"]["workflowInstance"]["attempts"][0]
        self.assertEqual(attempt["status"], "TERMINATED_BY_CLOSE")
        self.reject(domain, generation, "condition", results.TASK_TERMINAL, commandId="c2", condition=states.RESULT_RECORDED)
        self.reject(domain, generation, "advance", results.TASK_TERMINAL, commandId="c3", edgeId="E-D01")

    def test_close_through_an_escalation_gate_lands_on_the_close_node(self):
        """AC-05: the gate path selects the Close Task edge and forms CLOSED at the registered Close node."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="b1", condition=states.RESULT_RECORDED)
        self.run_command(domain, generation, "advance", commandId="b2", edgeId="E-D01")
        self.run_command(domain, generation, "advance", commandId="b3", edgeId="E-D02")
        for command, condition in (("b4", states.EXECUTING), ("b5", states.RESULT_RECORDED)):
            self.run_command(domain, generation, "condition", commandId=command, condition=condition)
        self.run_command(domain, generation, "advance", commandId="b6", edgeId="E-D03")
        for command, condition in (("b7", states.EXECUTING), ("b8", states.RESULT_RECORDED)):
            self.run_command(domain, generation, "condition", commandId=command, condition=condition)
        self.run_command(domain, generation, "advance", commandId="b9", edgeId="E-D05")
        for command, condition in (("b10", states.EXECUTING), ("b11", states.RESULT_RECORDED)):
            self.run_command(domain, generation, "condition", commandId=command, condition=condition)
        self.run_command(domain, generation, "advance", commandId="b12", edgeId="E-D06")
        for command, condition in (("b13", states.EXECUTING), ("b14", states.RESULT_RECORDED)):
            self.run_command(domain, generation, "condition", commandId=command, condition=condition)
        self.run_command(domain, generation, "advance", commandId="b15", edgeId="E-D08")
        guarded_walk.settle_and_advance(domain, generation, "feature-t0", "b18", "E-D10", OWNER)
        self.run_command(domain, generation, "condition", commandId="b19", condition=states.AWAITING_HUMAN_ACTION)
        # feature-t3: Accept With reservation is offered only on the Definition entry, not the generic one.
        self.assertEqual({d["decision"] for d in self.facts(domain)["decisions"]}, {"Continue", "Close Task"})
        outcome = self.run_command(domain, generation, "decide", commandId="b20", decision="Close Task")
        facts = self.facts(domain)
        self.assertEqual(outcome["result"], results.FINALIZED)
        self.assertEqual((facts["lifecycle"], facts["position"], facts["condition"]),
                         (states.CLOSED, "N-DEF-CLOSE", states.RESULT_RECORDED))
        self.assertEqual(facts["closure"]["kind"], "topology-edge")
        self.assertEqual(facts["closure"]["reasonCategory"], "blocked-escalation")

    def test_published_task_cannot_be_closed(self):
        """AC-05: a task whose publish was finalised is terminal and refuses a close request."""
        repo, head, domain, generation = self.accepted()
        def force(s):
            inst = s["tasks"]["feature-t0"]["workflowInstance"]
            inst.update(lifecycle=states.ACTIVE, position=states.PUBLISH_NODE, condition=states.EXECUTING)
            return None
        domain.store.transaction(generation, force)
        # feature-t7 narrows the generic fact and publish-finalize commands at the Publish node: the same progression
        # functions are applied directly here (SYNTHETIC, test only), as the forced state above already is.
        def finalize(s):
            from domain.workflow import progression
            inst = s["tasks"]["feature-t0"]["workflowInstance"]
            bound = domain.topology(inst)
            progression.record_fact(s, bound, "feature-t0", dict(factId="p1", kind="execution-result", purpose="publish",
                                                                 authorityRef=OWNER), revision=s["revision"])
            return progression.finalize_publish(s, bound, "feature-t0", dict(commandId="c1", triggers=["p1"], purpose="publish",
                                                                            authorityRef=OWNER), revision=s["revision"])
        domain.transaction(generation, finalize)
        facts = self.facts(domain)
        self.assertEqual((facts["lifecycle"], facts["condition"]), (states.COMPLETED, states.RESULT_RECORDED))
        self.assertEqual(domain.store.read()["tasks"]["feature-t0"]["terminal"]["kind"], "published")
        self.reject(domain, generation, "close", results.PUBLISHED_NOT_CLOSEABLE, commandId="c2",
                    reasonCategory="human-initiated")

    # -- AC-06 ----------------------------------------------------------------------------------
    def test_execution_failure_and_unknown_result_enter_recovery_and_block_progression(self):
        """AC-06: a failed or unconfirmable attempt stops the business edge; a business FAIL does not."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "attempt-open", attemptId="att-1")
        settled = self.run_command(domain, generation, "attempt-settle", attemptId="att-1", status="EXECUTION_FAILED")
        self.assertTrue(settled["entersRecovery"])
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        self.reject(domain, generation, "advance", results.RECOVERY_REQUIRED_BLOCKS_PROGRESSION, commandId="c2",
                    edgeId="E-D01")
        # A COMPLETED attempt is not a business PASS, and a business FAIL is a consumable result.
        repo2, head2, d2, g2 = self.accepted(name="repo2")
        d2.run("attempt-open", dict(taskId="feature-t0", authorityRef=OWNER, attemptId="att-2"), generation=g2)
        done = d2.run("attempt-settle", dict(taskId="feature-t0", authorityRef=OWNER, attemptId="att-2",
                                             status="COMPLETED"), generation=g2)
        self.assertFalse(done["entersRecovery"])
        d2.run("condition", dict(taskId="feature-t0", authorityRef=OWNER, commandId="c3",
                                 condition=states.RESULT_RECORDED), generation=g2)
        self.assertEqual(d2.run("advance", dict(taskId="feature-t0", authorityRef=OWNER, commandId="c4",
                                                edgeId="E-D01"), generation=g2)["result"], results.ADVANCED)

    def test_four_assessment_results_map_to_one_action_each(self):
        """AC-06: every assessment result has exactly one legal action and the map is closed."""
        self.assertEqual(set(recovery.ASSESSMENT_RESULTS),
                         {"RESULT_CONFIRMED", "RESTART_SAFE", "RECONCILIATION_REQUIRED", "INDETERMINATE"})
        self.assertEqual(recovery.LEGAL_ACTION["INDETERMINATE"], ())
        self.assertEqual(recovery.LEGAL_ACTION["RESTART_SAFE"], ("RESTART_CURRENT_NODE",))
        self.assertEqual(recovery.LEGAL_ACTION["RECONCILIATION_REQUIRED"], ("RECONCILE_CURRENT_NODE",))
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        assessed = self.run_command(domain, generation, "recover-assess", assessmentId="a1",
                                    assessment="RESULT_CONFIRMED", evidence=["evidence:one"])
        self.assertEqual(assessed["legalActions"], ["RECORD_CONFIRMED_RESULT"])
        self.reject(domain, generation, "recover", results.ILLEGAL_TRANSITION, commandId="c2",
                    action="RESTART_CURRENT_NODE", assessmentId="a1")
        outcome = self.run_command(domain, generation, "recover", commandId="c3", action="RECORD_CONFIRMED_RESULT",
                                   assessmentId="a1")
        self.assertEqual(outcome["result"], results.CONDITION_UPDATED)
        facts = self.facts(domain)
        self.assertEqual(facts["condition"], states.RESULT_RECORDED)
        self.assertEqual(facts["occurrence"]["node"], "N-DEF-HUMAN")
        self.assertIsNone(outcome["commit"]["selectedEdge"])

    def test_assessment_is_single_use_and_goes_stale_with_the_runtime_version(self):
        """AC-06: an assessment is consumed once and a later Runtime Version invalidates it."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        self.run_command(domain, generation, "recover-assess", assessmentId="a1", assessment="RESULT_CONFIRMED")
        self.run_command(domain, generation, "recover", commandId="c2", action="RECORD_CONFIRMED_RESULT", assessmentId="a1")
        self.reject(domain, generation, "recover", results.ASSESSMENT_ALREADY_CONSUMED, commandId="c3",
                    action="RECORD_CONFIRMED_RESULT", assessmentId="a1")
        # Two assessments taken at the same version: consuming one advances the Runtime Version, which
        # makes the other stale even though the position and the occurrence did not change.
        self.run_command(domain, generation, "condition", commandId="c4", condition=states.RECOVERY_REQUIRED)
        self.run_command(domain, generation, "recover-assess", assessmentId="a2", assessment="RESULT_CONFIRMED")
        self.run_command(domain, generation, "recover-assess", assessmentId="a3", assessment="RESULT_CONFIRMED")
        self.run_command(domain, generation, "recover", commandId="c5", action="RECORD_CONFIRMED_RESULT", assessmentId="a3")
        self.reject(domain, generation, "recover", results.ASSESSMENT_STALE, commandId="c6",
                    action="RECORD_CONFIRMED_RESULT", assessmentId="a2")

    def test_restart_and_mutating_reconciliation_need_a_single_use_human_authorization(self):
        """AC-06: restarting a node and a mutating reconciliation each need a bound, single-use Human authorization."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        self.run_command(domain, generation, "recover-assess", assessmentId="a1", assessment="RESTART_SAFE")
        self.reject(domain, generation, "recover", results.RECOVERY_AUTHORIZATION_MISSING, commandId="c2",
                    action="RESTART_CURRENT_NODE", assessmentId="a1")
        facts = self.facts(domain)
        wrong = dict(workflowInstance="feature-t0", occurrence=facts["occurrence"],
                     expectedRuntimeVersion=facts["runtimeVersion"], assessmentId="a1",
                     action="RECONCILE_CURRENT_NODE", effectScope="repository", authorizationRef="owner:auth-1")
        self.reject(domain, generation, "recover", results.RECOVERY_AUTHORIZATION_MISSING, commandId="c3",
                    action="RESTART_CURRENT_NODE", assessmentId="a1", humanAuthorization=wrong)
        good = dict(wrong, action="RESTART_CURRENT_NODE")
        outcome = self.run_command(domain, generation, "recover", commandId="c4", action="RESTART_CURRENT_NODE",
                                   assessmentId="a1", humanAuthorization=good)
        self.assertEqual(outcome["authorizationRef"], "owner:auth-1")
        after = self.facts(domain)
        self.assertEqual(after["condition"], states.ENTERED)
        self.assertEqual(after["occurrence"]["node"], facts["occurrence"]["node"])
        self.assertEqual(after["occurrence"]["positionEntryRuntimeVersion"],
                         facts["occurrence"]["positionEntryRuntimeVersion"])
        # The same authorization cannot be consumed twice.
        self.run_command(domain, generation, "condition", commandId="c5", condition=states.RECOVERY_REQUIRED)
        self.run_command(domain, generation, "recover-assess", assessmentId="a2", assessment="RESTART_SAFE")
        replayed = dict(good, assessmentId="a2", occurrence=self.facts(domain)["occurrence"],
                        expectedRuntimeVersion=self.facts(domain)["runtimeVersion"])
        self.reject(domain, generation, "recover", results.RECOVERY_AUTHORIZATION_MISSING, commandId="c6",
                    action="RESTART_CURRENT_NODE", assessmentId="a2", humanAuthorization=replayed)

    def test_indeterminate_authorises_no_state_change(self):
        """AC-06: an INDETERMINATE assessment cannot be turned into a state change by any path."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        assessed = self.run_command(domain, generation, "recover-assess", assessmentId="a1", assessment="INDETERMINATE")
        self.assertEqual(assessed["legalActions"], [])
        before = self.facts(domain)
        for action in recovery.ACTIONS:
            self.reject(domain, generation, "recover", results.ILLEGAL_TRANSITION, commandId="c-" + action,
                        action=action, assessmentId="a1")
        self.assertEqual(self.facts(domain), before)

    def test_reconciliation_keeps_the_state_and_requires_a_new_assessment(self):
        """AC-06: reconciliation changes no layer and the next step needs a fresh assessment."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        self.run_command(domain, generation, "recover-assess", assessmentId="a1", assessment="RECONCILIATION_REQUIRED")
        before = self.facts(domain)
        outcome = self.run_command(domain, generation, "recover", commandId="c2", action="RECONCILE_CURRENT_NODE",
                                   assessmentId="a1", scope=dict(probe="read-only"))
        self.assertTrue(outcome["reassessmentRequired"])
        after = self.facts(domain)
        self.assertEqual((after["lifecycle"], after["position"], after["condition"], after["runtimeVersion"]),
                         (before["lifecycle"], before["position"], before["condition"], before["runtimeVersion"]))
        self.reject(domain, generation, "recover", results.ASSESSMENT_ALREADY_CONSUMED, commandId="c3",
                    action="RECONCILE_CURRENT_NODE", assessmentId="a1")

    def test_reservation_is_not_released_by_completion_timeout_or_cancellation(self):
        """AC-06: a reservation survives an attempt settling and is released only against the execution fact."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "attempt-open", attemptId="att-1")
        self.run_command(domain, generation, "reserve", reservationId="res-1", executionRef="execution:one",
                         protects=["harness/executions/one"])
        self.run_command(domain, generation, "attempt-settle", attemptId="att-1", status="COMPLETED")
        self.reject(domain, generation, "reservation-settle", results.RESERVATION_HELD, reservationId="res-1",
                    settlement=dict(note="process exited"))
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RESULT_RECORDED)
        self.reject(domain, generation, "advance", results.RESERVATION_HELD, commandId="c2", edgeId="E-D01")
        settled = self.run_command(domain, generation, "reservation-settle", reservationId="res-1",
                                   settlement=dict(executionFact="execution:one exited 0", attemptId="att-1"))
        self.assertEqual(settled["reservation"]["status"], "settled")
        self.assertEqual(self.run_command(domain, generation, "advance", commandId="c3", edgeId="E-D01")["result"],
                         results.ADVANCED)

    # -- AC-07 ----------------------------------------------------------------------------------
    def test_same_command_identity_replays_and_a_different_intent_conflicts(self):
        """AC-07: the same Progression Command Identity replays; a fact identity bound twice conflicts."""
        repo, head, domain, generation = self.accepted()
        first = self.run_command(domain, generation, "condition", commandId="c1", condition=states.RESULT_RECORDED)
        replay = self.run_command(domain, generation, "condition", commandId="c1", condition=states.RESULT_RECORDED)
        self.assertEqual(replay["result"], results.IDEMPOTENT_REPLAY)
        self.assertEqual(replay["commit"]["nextRuntimeVersion"], first["commit"]["nextRuntimeVersion"])
        self.assertEqual(self.facts(domain)["commits"], 1)
        self.run_command(domain, generation, "fact", fact=dict(factId="f1", kind="human-decision", purpose="p",
                                                               authorityRef=OWNER))
        self.reject(domain, generation, "fact", results.REQUEST_CONFLICT,
                    fact=dict(factId="f1", kind="verify-result", purpose="p", authorityRef=OWNER))

    def test_authority_reference_is_required_for_every_progression(self):
        """AC-07: no progression is committed without an authorising reference."""
        repo, head, domain, generation = self.accepted()
        with self.assertRaises(WorkflowRejection) as ctx:
            domain.run("condition", dict(taskId="feature-t0", commandId="c1", condition=states.RESULT_RECORDED,
                                         authorityRef=""), generation=generation)
        self.assertEqual(ctx.exception.code, results.AUTHORITY_MISSING)

    def test_result_closed_set_and_exit_codes(self):
        """AC-07: the result set is closed and its exit codes follow the repository convention."""
        self.assertEqual(len(set(results.RESULTS)), len(results.RESULTS))
        for code in results.SUCCESS:
            self.assertEqual(results.exit_code(code), 0)
        for code in results.NOT_DETERMINABLE:
            self.assertEqual(results.exit_code(code), 2)
        self.assertEqual(results.exit_code(results.ILLEGAL_TRANSITION), 1)
        with self.assertRaises(ValueError):
            WorkflowRejection("NOT_A_CODE", "x")

    # -- AC-08 ----------------------------------------------------------------------------------
    def test_recorded_facts_are_append_only_and_never_overwritten(self):
        """AC-08: commits, attempts and facts only ever grow; a correction is a new record."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "attempt-open", attemptId="att-1")
        self.run_command(domain, generation, "attempt-settle", attemptId="att-1", status="EXECUTION_FAILED")
        with self.assertRaises(WorkflowRejection) as ctx:
            self.run_command(domain, generation, "attempt-settle", attemptId="att-1", status="COMPLETED")
        self.assertEqual(ctx.exception.code, results.REQUEST_CONFLICT)
        self.run_command(domain, generation, "condition", commandId="c1", condition=states.RECOVERY_REQUIRED)
        self.run_command(domain, generation, "recover-assess", assessmentId="a1", assessment="RESULT_CONFIRMED")
        self.run_command(domain, generation, "recover", commandId="c2", action="RECORD_CONFIRMED_RESULT", assessmentId="a1")
        instance = domain.store.read()["tasks"]["feature-t0"]["workflowInstance"]
        self.assertEqual([c["transitionKind"] for c in instance["commits"]],
                         [states.CONDITION_UPDATE, states.CONDITION_UPDATE])
        self.assertEqual([a["status"] for a in instance["attempts"]], ["EXECUTION_FAILED"])
        self.assertEqual(instance["recovery"]["assessments"]["a1"]["assessment"], "RESULT_CONFIRMED")
        versions = [c["nextRuntimeVersion"] for c in instance["commits"]]
        self.assertEqual(versions, sorted(versions, key=int))

    def test_no_server_or_second_database_and_a_missing_observation_proves_nothing(self):
        """AC-08: state lives in the repository only; a missing execution observation does not release anything."""
        repo, head, domain, generation = self.accepted()
        self.run_command(domain, generation, "reserve", reservationId="res-1", executionRef="execution:one")
        common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "harness"
        executions = common / "executions" / "one"
        self.assertFalse(executions.exists())
        self.reject(domain, generation, "reservation-settle", results.RESERVATION_HELD, reservationId="res-1",
                    settlement=dict(note="no observation directory"))
        fresh = open_domain(repo, entry="cli")
        self.assertTrue(fresh.available)
        self.assertEqual(fresh.status("feature-t0")["tasks"][0]["reservations"]["res-1"]["status"], "held")
        self.assertEqual(sorted(p.name for p in common.iterdir()),
                         ["binding.json", "bootstrap.json", "writer.lock"])

    def test_degraded_domain_reports_why_it_is_unusable(self):
        """AC-08: an unusable repository yields a port that states the reason instead of pretending."""
        domain = open_domain(self.directory / "not-a-repository", entry="runtime")
        self.assertFalse(domain.available)
        self.assertIn("not usable", domain.unavailable_reason)


if __name__ == "__main__":
    unittest.main()
