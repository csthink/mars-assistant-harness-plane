"""Payload schemas of the Definition Runtime actions; installed into the local Registry by the root.

The Runtime never fetches a schema from a request; the registered digest is the RFC 8785 canonical
SHA-256 of the installed bytes below.
"""
import hashlib

import rfc8785

TASK = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"}
VERSION = {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
NAME = {"type": ["string", "null"], "maxLength": 256}
EVIDENCE = {"type": "object", "properties": {"commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                             "path": {"type": "string", "minLength": 1, "maxLength": 1024}},
            "required": ["commit", "path"], "additionalProperties": False}
AUTHOR = {"type": "object", "properties": {"tool": NAME, "model": NAME, "vendor": NAME, "humanOnly": {"type": "boolean"},
                                           "evidenceRefs": {"type": "array", "minItems": 1, "maxItems": 16, "items": EVIDENCE}},
          "required": ["tool", "model", "vendor", "humanOnly", "evidenceRefs"], "additionalProperties": False}


def _schema(identifier, properties, required):
    return {"$schema": "http://json-schema.org/draft-07/schema#", "$id": identifier, "type": "object",
            "properties": properties, "required": required, "additionalProperties": False}


SUBMIT_ID = "urn:hp:harness:definition-submit:v1"
DISPATCH_ID = "urn:hp:harness:definition-dispatch:v1"
DECIDE_ID = "urn:hp:harness:definition-decide:v1"
FORMAL_ID = "urn:hp:harness:definition-formal-authorize:v1"
SUBMIT_SCHEMA = _schema(SUBMIT_ID, {"taskId": TASK, "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                    "author": AUTHOR, "expectedRuntimeVersion": VERSION},
                        ["taskId", "commit", "author", "expectedRuntimeVersion"])
DISPATCH_SCHEMA = _schema(DISPATCH_ID, {"taskId": TASK, "expectedRuntimeVersion": VERSION}, ["taskId", "expectedRuntimeVersion"])
DECIDE_SCHEMA = _schema(DECIDE_ID, {"taskId": TASK, "decision": {"enum": ["Authorize & Freeze", "Accept With reservation",
                                                                         "Dispose findings"]},
                                    "decisionText": TEXT, "reservation": TEXT,
                                    "findings": {"type": "object", "maxProperties": 64,
                                                 "additionalProperties": TEXT},
                                    "expectedRuntimeVersion": VERSION},
                        ["taskId", "decision", "decisionText", "expectedRuntimeVersion"])
FORMAL_SCHEMA = _schema(FORMAL_ID, {"taskId": TASK, "portId": {"type": "string", "minLength": 1, "maxLength": 256},
                                    "maxCalls": {"type": "integer", "minimum": 1, "maximum": 64},
                                    "expectedRuntimeVersion": VERSION},
                        ["taskId", "maxCalls", "expectedRuntimeVersion"])

SCHEMAS = {SUBMIT_ID: SUBMIT_SCHEMA, DISPATCH_ID: DISPATCH_SCHEMA, DECIDE_ID: DECIDE_SCHEMA, FORMAL_ID: FORMAL_SCHEMA}
DIGESTS = {hashlib.sha256(rfc8785.dumps(schema)).hexdigest(): identifier for identifier, schema in SCHEMAS.items()}
DIGEST_OF = {identifier: digest for digest, identifier in DIGESTS.items()}
