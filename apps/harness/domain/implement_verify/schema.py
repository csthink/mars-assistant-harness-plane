"""Payload schemas of the Implement and Verify Runtime actions; installed into the local Registry by the root.

The Runtime never fetches a schema from a request; the registered digest is the RFC 8785 canonical
SHA-256 of the installed bytes below. The worktree, role and purpose are not wire fields: the domain
takes the worktree bound at acceptance and the fixed implementer role and coding-implementer purpose.
"""
import hashlib

import rfc8785

TASK = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"}
VERSION = {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"}
LIMIT = {"type": "integer", "minimum": 1}
BUDGET = {"type": "object", "properties": {"maxToolCalls": LIMIT, "maxRunSeconds": LIMIT, "maxOutputBytes": LIMIT,
                                           "cleanupSeconds": LIMIT},
          "required": ["maxToolCalls", "maxRunSeconds", "maxOutputBytes", "cleanupSeconds"], "additionalProperties": False}


def _schema(identifier, properties, required):
    return {"$schema": "http://json-schema.org/draft-07/schema#", "$id": identifier, "type": "object",
            "properties": properties, "required": required, "additionalProperties": False}


DISPATCH_ID = "urn:hp:harness:implement-dispatch:v1"
VERIFY_ID = "urn:hp:harness:verify-run:v1"
DISPATCH_SCHEMA = _schema(DISPATCH_ID, {"taskId": TASK, "portId": {"type": "string", "minLength": 1, "maxLength": 256},
                                        "finalizationRef": {"type": "string", "pattern": "^RU-[0-9]{2,}$"},
                                        "budget": BUDGET, "expectedRuntimeVersion": VERSION},
                          ["taskId", "portId", "finalizationRef", "budget", "expectedRuntimeVersion"])
VERIFY_SCHEMA = _schema(VERIFY_ID, {"taskId": TASK, "expectedRuntimeVersion": VERSION}, ["taskId", "expectedRuntimeVersion"])

SCHEMAS = {DISPATCH_ID: DISPATCH_SCHEMA, VERIFY_ID: VERIFY_SCHEMA}
DIGESTS = {hashlib.sha256(rfc8785.dumps(schema)).hexdigest(): identifier for identifier, schema in SCHEMAS.items()}
DIGEST_OF = {identifier: digest for digest, identifier in DIGESTS.items()}
