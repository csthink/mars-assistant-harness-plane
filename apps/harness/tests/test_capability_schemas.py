"""Every action payload schema lives inside its capability's negotiated document (Assistant KB-301, OD-425 R1, R2, R4).

Runtime Contract README line 136: a domain payload schema must be in the negotiated set with an exact digest, and an
unknown schema is never executed generically. Under the Owner's ruling OD-425 an action's payloadSchemaDigest is the
digest of its capability's document (the primary action) or of exactly one entry of that document's root
`definitions`; digests are SHA-256 over RFC 8785 canonical JSON. The production cases read the capability documents
the Domain Core registers (the bytes the bundle builder packages, see test_bundle); the synthetic cases drive the
Runtime refusal path through a real serve-stdio process with seeded actions.
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

import rfc8785

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance import schema as acceptance_schema
from domain.budget import schema as budget_schema
from domain.core import HarnessDomain
from domain.definition import projection as definition_projection, schema as definition_schema
from domain.implement_verify import projection as implement_verify_projection, schema as implement_verify_schema
from domain.publish import projection as publish_projection, schema as publish_schema
from domain.validation import projection as validation_projection, schema as validation_schema
from domain.workflow import projection as workflow_projection, schema as workflow_schema
from host_driver import Host
from make_fixture import create as create_synthetic
from runtime.protocol import Schemas
from test_workflow_runtime import WorkflowHost
from workflow_fixture import create as create_workflow


# The standalone payload schemas each module defines, and the projection owning each multi-action capability.
STANDALONE = {acceptance_schema.SCHEMA_ID: acceptance_schema.PAYLOAD_SCHEMA, **budget_schema.SCHEMAS, **workflow_schema.SCHEMAS,
              **definition_schema.SCHEMAS, **implement_verify_schema.SCHEMAS, **validation_schema.SCHEMAS,
              **publish_schema.SCHEMAS}
PROJECTIONS = {m.CAPABILITY_ID: m for m in (workflow_projection, definition_projection, implement_verify_projection,
                                            validation_projection, publish_projection)}


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def offered_actions(repository):
    """Every action the production Runtime can offer: the projection of one open scope (enabled or not)."""
    domain = HarnessDomain(repository, entry="runtime")
    state = domain.store.read()
    state["scopes"]["scope:probe"] = dict(resourceHandle="resource:probe", objects=[], actions=[], pendingItems=[], events=[],
                                          streamId="stream:probe", epoch="1", seq="0", logFloor="0")
    domain.build_projections(state)
    return domain, state["scopes"]["scope:probe"]["actions"]


class ProductionDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="hp-od425-")
        subprocess.run(["git", "init", "-q", cls.temp.name], check=True)
        cls.domain, cls.actions = offered_actions(cls.temp.name)
        cls.capabilities = {c["id"]: c for c in cls.domain.capabilities}
        cls.documents = {digest(schema): schema for schema in cls.domain.schemas.values()}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_offered_action_resolves_inside_its_own_negotiated_capability(self):
        """R1, R4: each action's capability is a declared one and its payload digest is that document or one of its entries."""
        self.assertEqual(len(self.actions), 20)
        self.assertEqual(len(self.capabilities), 7)
        unresolved, located = [], {}
        for action in self.actions:
            capability = action["capability"]
            self.assertEqual(self.capabilities[capability["id"]], capability, action["actionId"])
            document = self.documents[capability["schemaDigest"]]
            if action["payloadSchemaDigest"] == capability["schemaDigest"]:
                located[action["actionId"]] = ""
                continue
            names = [n for n, e in document.get("definitions", {}).items() if digest(e) == action["payloadSchemaDigest"]]
            if names != [action["actionId"]]:
                unresolved.append(action["actionId"])
            else:
                located[action["actionId"]] = "/definitions/" + names[0]
        self.assertEqual(unresolved, [])
        # The Runtime's own resolution agrees with this independent reading of R1.
        schemas = Schemas(self.domain.schemas)
        for action in self.actions:
            target = schemas.resolve(action["capability"], action["payloadSchemaDigest"])
            self.assertEqual(target.partition("#")[2], located[action["actionId"]], action["actionId"])

    def test_documents_follow_r2(self):
        """R2: entries are named by the capability's other actionIds, self-contained, unique and unlike the root."""
        by_capability = {}
        for action in self.actions:
            by_capability.setdefault(action["capability"]["id"], []).append(action)
        for capability_id, actions in by_capability.items():
            capability = self.capabilities[capability_id]
            document = self.documents[capability["schemaDigest"]]
            primary = [a["actionId"] for a in actions if a["payloadSchemaDigest"] == capability["schemaDigest"]]
            self.assertEqual(len(primary), 1, capability_id)
            entries = document.get("definitions", {})
            self.assertEqual(sorted(entries), sorted(a["actionId"] for a in actions if a["actionId"] not in primary), capability_id)
            digests = {name: digest(entry) for name, entry in entries.items()}
            self.assertEqual(len(set(digests.values())), len(digests))
            self.assertNotIn(capability["schemaDigest"], digests.values())
            module = PROJECTIONS.get(capability_id)
            for name, entry in entries.items():
                text = json.dumps(entry)
                for keyword in ('"$ref"', '"$id"', '"$schema"'):
                    self.assertNotIn(keyword, text, capability_id + " " + name)
                # An entry is the action's standalone payload schema without its identity keywords, content unchanged,
                # titled by its actionId (coordinator ruling within OD-425).
                standalone = STANDALONE[module.ACTIONS[name]]
                expected = {k: v for k, v in standalone.items() if k not in ("$schema", "$id")}
                expected["title"] = name
                self.assertEqual(entry, expected, name)
            # The document root still is the primary action's payload schema.
            self.assertEqual({k: v for k, v in document.items() if k != "definitions"}, STANDALONE[document["$id"]], capability_id)

    def test_structurally_identical_payloads_have_distinct_entry_digests(self):
        """R2 with titles: entries whose payload structure is identical still have distinct digests, across all documents."""
        digests = {}
        for capability in self.capabilities.values():
            for name, entry in self.documents[capability["schemaDigest"]].get("definitions", {}).items():
                digests.setdefault(digest(entry), []).append(name)
        self.assertEqual({d: n for d, n in digests.items() if len(n) > 1}, {})

    def test_versions_follow_the_document_change(self):
        """Multi-action capabilities changed their document and bumped their version; single-action ones did not."""
        versions = {c["id"]: c["version"] for c in self.domain.capabilities}
        self.assertEqual(versions, {"harness.task-acceptance": "1", "harness.autonomous-budget": "1", "harness.workflow": "2",
                                    "harness.definition": "2", "harness.implement-verify": "2", "harness.validate-change": "2",
                                    "harness.publish": "2"})

    def test_a_digest_of_another_capability_or_an_unknown_one_does_not_resolve(self):
        """R1, R4: resolution is confined to the action's own capability document."""
        schemas = Schemas(self.domain.schemas)
        workflow = self.capabilities[workflow_projection.CAPABILITY_ID]
        validation = self.capabilities[validation_projection.CAPABILITY_ID]
        foreign = validation_projection.DOCUMENT.payload_digest(validation_projection.DISPOSE)
        self.assertIsNone(schemas.resolve(workflow, foreign))
        self.assertIsNone(schemas.resolve(workflow, validation["schemaDigest"]))
        self.assertIsNone(schemas.resolve(workflow, "0" * 64))
        self.assertIsNone(schemas.resolve(dict(workflow, schemaDigest="1" * 64), workflow["schemaDigest"]))

    def test_validate_dispose_findings_are_bounded(self):
        """Assistant KB-302: the findings disposition map of validate.dispose has an upper bound, like definition.decide."""
        entry = validation_projection.DOCUMENT.schema["definitions"][validation_projection.DISPOSE]
        self.assertEqual(entry["properties"]["findings"]["maxProperties"], 64)


class SyntheticRefusal(unittest.TestCase):
    """R4 through a real serve-stdio process: the seeded synthetic domain offers any action shape the case needs."""

    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-od425-stdio-")
            self.directory = Path(self.temp.name) / "case"
        template = create_synthetic(self.directory)
        seed = json.loads((self.directory / "seed.json").read_text())
        root_schema = next(iter(seed["schemas"].values()))
        sub = {"type": "object", "properties": {"note": {"type": "string", "maxLength": 8}}, "required": ["note"],
               "additionalProperties": False}
        other = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": "urn:hp:test:other", "type": "object",
                 "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False}
        document = dict(copy.deepcopy(root_schema), definitions={"action:sub": sub})
        capability = dict(seed["capabilities"][0], schemaDigest=digest(document))
        seed["capabilities"] = [capability]
        seed["schemas"] = {document["$id"]: document, other["$id"]: other}
        seed["state"]["payloadSchemas"] = {digest(document): document["$id"], digest(other): other["$id"]}
        view = seed["state"]["scopes"][template["scopeRef"]]
        base = dict(view["actions"][0], capability=capability)
        view["actions"] = [dict(base, actionId="action:root", payloadSchemaDigest=capability["schemaDigest"]),
                           dict(base, actionId="action:sub", payloadSchemaDigest=digest(sub)),
                           dict(base, actionId="action:foreign", payloadSchemaDigest=digest(other)),
                           dict(base, actionId="action:unknown", payloadSchemaDigest="0" * 64)]
        view["objects"] = [dict(o, capability=capability) for o in view["objects"]]
        view["pendingItems"] = [dict(i, capability=capability, actionIds=["action:root"]) for i in view["pendingItems"]]
        seed["state"]["decisionEvidence"] = {}
        (self.directory / "seed.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n")
        template["initialize"]["capabilities"] = [capability]
        (self.directory / "host-template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n")
        self.h = Host(self.directory, output=self.directory / "frames.jsonl")
        self.h.initialize()
        self.h.activate()

    def tearDown(self):
        self.h.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def invoke(self, action_id, payload, error=None):
        return self.h.call("runtime.action.invoke", self.h.invoke_params(actionId=action_id, payload=payload), error=error)

    def test_root_and_definitions_entry_are_accepted_and_validated(self):
        """R1: the document root and one definitions entry both resolve; the entry validates its own payload."""
        self.assertEqual(self.invoke("action:root", {"value": "x"})["status"], "accepted")
        self.assertEqual(self.invoke("action:sub", {"note": "short"})["status"], "accepted")
        self.invoke("action:sub", {"note": "far too long"}, error="PRECONDITION_CONFLICT")
        self.invoke("action:sub", {"value": "x"}, error="PRECONDITION_CONFLICT")

    def test_installed_but_not_negotiated_and_unknown_schemas_are_refused(self):
        """R4: a digest merely installed, or unknown, is not in the action's negotiated capability and is refused."""
        self.invoke("action:foreign", {"value": "x"}, error="UNSUPPORTED_CAPABILITY")
        self.invoke("action:unknown", {"value": "x"}, error="UNSUPPORTED_CAPABILITY")


class ProductionEntry(unittest.TestCase):
    """A definitions entry through the production Domain Core: workflow.close validates against its own entry."""

    def setUp(self):
        root = os.environ.get("HP_TEST_OUTPUT")
        if root:
            self.directory = Path(root) / self._testMethodName
            self.directory.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="hp-od425-close-")
            self.directory = Path(self.temp.name) / "case"
        self.template = create_workflow(self.directory)
        self.host = WorkflowHost(self.directory, output=self.directory / "frames.jsonl")
        self.host.initialize()
        self.scope = self.host.activate()

    def tearDown(self):
        self.host.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_a_definitions_entry_action_validates_and_succeeds(self):
        """R1: workflow.close names its entry; an out-of-enum reason is refused by the entry, a valid one closes the task."""
        page = self.host.call("runtime.snapshot.open", dict(scopeRef=self.scope))
        close = next(a for a in page["actions"] if a["actionId"] == workflow_projection.ACTION_CLOSE)
        self.assertEqual(close["payloadSchemaDigest"], workflow_projection.DOCUMENT.payload_digest(workflow_projection.ACTION_CLOSE))
        self.assertNotEqual(close["payloadSchemaDigest"], close["capability"]["schemaDigest"])
        version = HarnessDomain(self.template["repository"]).status("feature-t0")["tasks"][0]["runtimeVersion"]
        bad = self.host.decided(close, dict(taskId="feature-t0", reasonCategory="not-a-category", expectedRuntimeVersion=version))
        self.host.call("runtime.action.invoke", bad, error="PRECONDITION_CONFLICT")
        good = self.host.decided(close, dict(taskId="feature-t0", reasonCategory="human-initiated", expectedRuntimeVersion=version))
        op = self.host.call("runtime.action.invoke", good)
        self.assertEqual((op["status"], op["resultCode"]), ("succeeded", "FINALIZED"))


if __name__ == "__main__":
    unittest.main()
