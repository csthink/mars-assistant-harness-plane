"""Payload schemas of the Validate Change Runtime actions; installed into the local Registry by the root.

The worktree, the candidate and the materials are never wire fields: the domain takes the worktree bound
at acceptance and the candidate feature-t4 routed and Verify passed.
"""
import hashlib

import rfc8785

from domain.publish.schema import BINDING as PUBLISH_BINDING, DIGEST as PUBLISH_DIGEST

TASK = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"}
VERSION = {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
PORT = {"type": "string", "minLength": 1, "maxLength": 256}
EXTENSION = {"type": "object", "properties": {"authorized_by": TEXT, "at": TEXT, "added_rounds": {"type": "integer", "minimum": 1},
                                               "note": TEXT},
             "required": ["authorized_by", "at", "added_rounds", "note"], "additionalProperties": False}


def _schema(identifier, properties, required):
    return {"$schema": "http://json-schema.org/draft-07/schema#", "$id": identifier, "type": "object",
            "properties": properties, "required": required, "additionalProperties": False}


CONFIGURE_ID = "urn:hp:harness:validate-configure:v1"
DISPATCH_ID = "urn:hp:harness:validate-dispatch:v1"
FORMAL_ID = "urn:hp:harness:validate-formal-authorize:v1"
DISPOSE_ID = "urn:hp:harness:validate-dispose:v1"
DECIDE_ID = "urn:hp:harness:validate-decide:v2"
RESUME_ID = "urn:hp:harness:validate-resume:v1"
BASE = {"taskId": TASK, "expectedRuntimeVersion": VERSION}
SCHEMAS = {
    CONFIGURE_ID: _schema(CONFIGURE_ID, dict(BASE), ["taskId", "expectedRuntimeVersion"]),
    DISPATCH_ID: _schema(DISPATCH_ID, dict(BASE, portId=PORT, roundExtensions={"type": "array", "items": EXTENSION, "maxItems": 16}),
                         ["taskId", "expectedRuntimeVersion"]),
    FORMAL_ID: _schema(FORMAL_ID, dict(BASE, portId=PORT, maxCalls={"type": "integer", "minimum": 1, "maximum": 2}),
                       ["taskId", "expectedRuntimeVersion", "maxCalls"]),
    # Assistant KB-302: findings are bounded like the Definition disposition map (definition.decide, 64 entries).
    DISPOSE_ID: _schema(DISPOSE_ID, dict(BASE, decisionText=TEXT, findings={"type": "object", "minProperties": 1,
                                                                            "maxProperties": 64,
                                                                            "additionalProperties": TEXT}),
                        ["taskId", "expectedRuntimeVersion", "decisionText", "findings"]),
    # feature-t7: the Validation escalation Accept With reservation is that path's Publish authorization (FR-26) and
    # carries the exact binding and the Publish authorization context digest (v2; the content changed, so the id did).
    DECIDE_ID: _schema(DECIDE_ID, dict(BASE, decisionText=TEXT, reservation=TEXT, publishBinding=PUBLISH_BINDING,
                                       contextDigest=PUBLISH_DIGEST),
                       ["taskId", "expectedRuntimeVersion", "decisionText", "reservation", "publishBinding", "contextDigest"]),
    RESUME_ID: _schema(RESUME_ID, dict(BASE), ["taskId", "expectedRuntimeVersion"]),
}
DIGESTS = {hashlib.sha256(rfc8785.dumps(schema)).hexdigest(): identifier for identifier, schema in SCHEMAS.items()}
DIGEST_OF = {identifier: digest for digest, identifier in DIGESTS.items()}
