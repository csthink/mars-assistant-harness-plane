"""Payload schema of the `budget.decide` Runtime action; installed into the local Registry by the root."""
import hashlib

import rfc8785

TASK = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"}
VERSION = {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"}
DECIDE_ID = "urn:hp:harness:budget-decide:v1"
DECIDE_SCHEMA = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": DECIDE_ID, "type": "object",
                 "properties": {"taskId": TASK, "expectedRuntimeVersion": VERSION},
                 "required": ["taskId", "expectedRuntimeVersion"], "additionalProperties": False}
SCHEMAS = {DECIDE_ID: DECIDE_SCHEMA}
DIGESTS = {hashlib.sha256(rfc8785.dumps(schema)).hexdigest(): identifier for identifier, schema in SCHEMAS.items()}
DIGEST_OF = {identifier: digest for digest, identifier in DIGESTS.items()}
