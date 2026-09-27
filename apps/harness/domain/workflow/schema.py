"""Payload schemas of the Workflow Runtime actions; installed into the local Registry by the root.

The Runtime never fetches a schema from a request. The digest registered with a capability or an
action is the RFC 8785 canonical SHA-256 of the installed bytes below.
"""
import hashlib

import rfc8785

DECIDE_ID = "urn:hp:harness:workflow-decision:v1"
CLOSE_ID = "urn:hp:harness:workflow-close:v1"

DECIDE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": DECIDE_ID,
    "type": "object",
    "properties": {
        "taskId": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "decision": {"type": "string", "minLength": 1, "maxLength": 128},
        "expectedRuntimeVersion": {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"},
    },
    "required": ["taskId", "decision", "expectedRuntimeVersion"],
    "additionalProperties": False,
}
CLOSE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": CLOSE_ID,
    "type": "object",
    "properties": {
        "taskId": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "reasonCategory": {"enum": ["human-initiated", "blocked-escalation"]},
        "expectedRuntimeVersion": {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"},
    },
    "required": ["taskId", "reasonCategory", "expectedRuntimeVersion"],
    "additionalProperties": False,
}

DECIDE_DIGEST = hashlib.sha256(rfc8785.dumps(DECIDE_SCHEMA)).hexdigest()
CLOSE_DIGEST = hashlib.sha256(rfc8785.dumps(CLOSE_SCHEMA)).hexdigest()
SCHEMAS = {DECIDE_ID: DECIDE_SCHEMA, CLOSE_ID: CLOSE_SCHEMA}
DIGESTS = {DECIDE_DIGEST: DECIDE_ID, CLOSE_DIGEST: CLOSE_ID}
