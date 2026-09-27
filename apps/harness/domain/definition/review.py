"""Review Definition: switch routing, port registration checks, Verdict acceptance and failure mapping.

Only a published, valid five-dimension task-round Verdict enters the domain (FR-21, review channel
r10 §6.4/§6.5). Host cancel, port failure, infrastructure failure, invalid output, preflight refusal
(including the feature-t6 authorization callback's refusal) and an unknown result never become a
Reviewer FAIL: they settle the attempt as EXECUTION_FAILED or INDETERMINATE and put the reviewer node
into RECOVERY_REQUIRED (D-04 §14 scenario 3, D-05). Eligibility rules themselves are not restated
here: the channel, the port and the feature-t6 callback own them.
"""
import copy
import json
from pathlib import Path

from domain.definition.results import (
    AUTHORIZER_UNAVAILABLE, PORT_ENTRY_MISMATCH, PORT_NOT_REGISTERED, VERDICT_NOT_ACCEPTABLE, DefinitionRejection,
)

REGISTRY = "mechanisms/review-channel/review_channel_registry.json"
VERDICT_SCHEMA = "review-channel-verdict/v4"
TASK_QUESTIONS = ("Q-FIDELITY", "Q-GOAL", "Q-BOUNDARY", "Q-ACCEPT", "Q-EXEC")
VALID = "completed_with_valid_verdict"
ENTRY_MODE = {"runtime": "embedded", "cli": "standalone"}
# Classifications that can never be a Reviewer verdict (review channel r10 §6.7).
FAILED = ("preflight_failed", "provider_unavailable", "authentication_failed", "runtime_rejected_config",
          "timeout_or_transport_failure", "reviewer_output_invalid", "interrupted", "cancelled_by_host",
          "execution_port_failure")
UNKNOWN = "unknown"


def read_registry(repository_root):
    path = Path(repository_root) / REGISTRY
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DefinitionRejection(PORT_NOT_REGISTERED, "review channel registry unavailable", path=REGISTRY,
                                  error=type(exc).__name__) from exc


def select_port(repository_root, entry, port_id=None):
    """The one registered review port for this entry; embedded and standalone never stand in for each other."""
    registry = read_registry(repository_root)
    mode = ENTRY_MODE.get(entry)
    ports = [p for p in registry.get("execution_ports", []) if p.get("profile", {}).get("purpose") == "review"]
    if port_id is not None:
        ports = [p for p in ports if p.get("id") == port_id]
        if not ports:
            raise DefinitionRejection(PORT_NOT_REGISTERED, "no registered review port with this id", portId=port_id)
        if ports[0].get("mode") != mode:
            raise DefinitionRejection(PORT_ENTRY_MISMATCH, "the port's execution mode does not serve this entry",
                                      portId=port_id, portMode=ports[0].get("mode"), entry=entry)
    ports = [p for p in ports if p.get("mode") == mode]
    if len(ports) != 1:
        raise DefinitionRejection(PORT_NOT_REGISTERED, "no unique registered review port for this entry",
                                  entry=entry, mode=mode, matches=len(ports))
    port = copy.deepcopy(ports[0])
    mappings = [m for m in registry.get("model_mappings", []) if m.get("id") == port.get("mapping_id")]
    if len(mappings) != 1:
        raise DefinitionRejection(PORT_NOT_REGISTERED, "the port's model mapping is not registered",
                                  portId=port["id"], mappingId=port.get("mapping_id"))
    return port, copy.deepcopy(mappings[0]), registry.get("registry_revision")


def authorizer_available():
    """The production callback is feature-t6's; without it no review may be released (fail closed)."""
    import importlib.util
    try:
        found = importlib.util.find_spec("domain.policy.authorize")
    except (ImportError, ValueError):
        found = None
    if found is None:
        raise DefinitionRejection(AUTHORIZER_UNAVAILABLE,
                                  "the feature-t6 execution authorization callback is not installed; no review is released",
                                  module="domain.policy.authorize")
    return True


def accept_verdict(outcome, round_record, candidate):
    """Check a channel outcome is a published valid task-round Verdict for exactly the bound candidate."""
    problems = []
    receipt = outcome.get("receipt") or {}
    block = outcome.get("verdict") or {}
    if outcome.get("classification") != VALID or receipt.get("classification") != VALID:
        problems.append("classification is not completed_with_valid_verdict")
    if receipt.get("verdict_validation") != "VALID" or receipt.get("verdict_published") is not True:
        problems.append("receipt does not record a published valid verdict")
    if block.get("verdict_schema") != VERDICT_SCHEMA:
        problems.append("verdict schema is not " + VERDICT_SCHEMA)
    if block.get("stage") != "task" or block.get("round") != round_record["round"]:
        problems.append("verdict stage or round differs from the dispatched round")
    ids = [q.get("question_id") for q in block.get("question_assessments", []) if isinstance(q, dict)]
    if sorted(ids) != sorted(TASK_QUESTIONS) or len(ids) != len(set(ids)):
        problems.append("question set is not exactly the task-round five questions")
    bundle = (block.get("candidate") or {})
    if bundle.get("sha256") != candidate["sha256"]:
        problems.append("verdict candidate identity differs from the bound candidate")
    if block.get("verdict") not in ("PASS", "FAIL"):
        problems.append("verdict value outside PASS / FAIL")
    if outcome.get("verdictSha256") is None or receipt.get("verdict_sha256") != outcome.get("verdictSha256"):
        problems.append("receipt verdict_sha256 does not bind the verdict bytes")
    if problems:
        raise DefinitionRejection(VERDICT_NOT_ACCEPTABLE, "channel result is not a valid verdict for this round",
                                  problems=problems, classification=outcome.get("classification"))
    findings = [dict(id=f["id"], severity=f["severity"], title=f.get("title")) for f in block.get("findings", [])
                if isinstance(f, dict)]
    return dict(verdict=block["verdict"], humanDecisionRequired=bool(block.get("human_decision_required")),
                findings=findings, humanFindings=[f["id"] for f in findings if f["severity"] == "human"],
                verdictSha256=outcome["verdictSha256"], evidenceRef=copy.deepcopy(outcome.get("evidenceRef")),
                receiptRef=copy.deepcopy(outcome.get("receiptRef")))


def failure_of(outcome):
    """Map a non-verdict outcome to (attempt status, reason); never to a business FAIL."""
    classification = outcome.get("classification")
    if classification == UNKNOWN:
        return "INDETERMINATE", dict(classification=UNKNOWN, failureCode=outcome.get("failureCode"))
    if classification in FAILED:
        return "EXECUTION_FAILED", dict(classification=classification, failureCode=outcome.get("failureCode"))
    return "EXECUTION_FAILED", dict(classification=classification or "missing", failureCode=outcome.get("failureCode"),
                                    note="unrecognised channel classification treated as execution failure")
