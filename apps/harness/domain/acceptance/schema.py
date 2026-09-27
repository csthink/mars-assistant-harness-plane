"""Payload schema of the Runtime action task.accept; installed into the local Registry by the composition root."""
import hashlib

import rfc8785

SCHEMA_ID = "urn:hp:harness:task-acceptance:v1"
PAYLOAD_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": SCHEMA_ID,
    "type": "object",
    "properties": {
        "taskType": {"enum": ["feature", "hotfix"]},
        "taskId": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "baseRef": {"type": "string", "minLength": 1, "maxLength": 256},
        "worktreeRoot": {"type": "string", "minLength": 1, "maxLength": 4096},
    },
    "required": ["taskType", "taskId", "baseRef", "worktreeRoot"],
    "additionalProperties": False,
}
DIGEST = hashlib.sha256(rfc8785.dumps(PAYLOAD_SCHEMA)).hexdigest()
