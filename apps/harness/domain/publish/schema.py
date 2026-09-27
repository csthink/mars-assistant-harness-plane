"""Payload schemas of the Publish Runtime actions; installed into the local Registry by the root.

BINDING is also the `publishBinding` sub-schema of feature-t5's `validate.decide` (v2). The wire carries only
what the Human decides; every derived field of the binding is computed by the domain from the recorded facts.
"""
import hashlib

import rfc8785

TASK = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-z0-9][a-z0-9-]*$"}
VERSION = {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[0-9]+$"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
NAME = {"type": "string", "minLength": 1, "maxLength": 255}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
BINDING = {"type": "object",
           "properties": {"candidateCommit": {"type": "string", "pattern": "^[0-9a-f]{40}$"}, "sourceBranch": NAME, "remote": NAME,
                          "targetBranch": NAME,
                          "pullRequest": {"type": "object", "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 256},
                                                                           "body": {"type": "string", "maxLength": 60000}},
                                          "required": ["title", "body"], "additionalProperties": False}},
           "required": ["candidateCommit", "sourceBranch", "remote", "targetBranch", "pullRequest"], "additionalProperties": False}


def _schema(identifier, properties, required):
    return {"$schema": "http://json-schema.org/draft-07/schema#", "$id": identifier, "type": "object",
            "properties": properties, "required": required, "additionalProperties": False}


AUTHORIZE_ID = "urn:hp:harness:publish-authorize:v1"
DISPATCH_ID = "urn:hp:harness:publish-dispatch:v1"
QUERY_ID = "urn:hp:harness:publish-query:v1"
RECONCILE_ID = "urn:hp:harness:publish-reconcile:v1"
BASE = {"taskId": TASK, "expectedRuntimeVersion": VERSION}
SCHEMAS = {
    AUTHORIZE_ID: _schema(AUTHORIZE_ID, dict(BASE, decisionText=TEXT, contextDigest=DIGEST, publishBinding=BINDING),
                          ["taskId", "expectedRuntimeVersion", "decisionText", "contextDigest", "publishBinding"]),
    DISPATCH_ID: _schema(DISPATCH_ID, dict(BASE), ["taskId", "expectedRuntimeVersion"]),
    QUERY_ID: _schema(QUERY_ID, dict(BASE), ["taskId", "expectedRuntimeVersion"]),
    RECONCILE_ID: _schema(RECONCILE_ID, dict(BASE, assessmentId={"type": "string", "minLength": 1, "maxLength": 512}),
                          ["taskId", "expectedRuntimeVersion", "assessmentId"]),
}
DIGESTS = {hashlib.sha256(rfc8785.dumps(schema)).hexdigest(): identifier for identifier, schema in SCHEMAS.items()}
DIGEST_OF = {identifier: digest for digest, identifier in DIGESTS.items()}
