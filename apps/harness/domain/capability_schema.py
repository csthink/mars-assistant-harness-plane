"""Capability documents: every action payload schema inside its capability's negotiated schema (OD-425 rules R1, R2).

The Runtime Contract binds a capability to one schemaDigest and requires every domain payload schema to be in the
negotiated set with an exact digest (README line 136). Under the Owner's ruling (Assistant OD-425) the document a
capability declares is the payload schema of its primary action, and the payload schema of each of its other
actions is one entry of that document's root `definitions`, named by the actionId:

- R1: an action's payloadSchemaDigest is the digest of the whole document (the primary action) or the digest of
  exactly one `definitions` entry value; any other value is an unknown schema. A digest is the SHA-256 of the
  RFC 8785 canonical JSON of the value.
- R2: entries are self-contained, with no `$ref` and no nested `$id` (and no nested `$schema`); their digests are
  unique and differ from the document digest. Each entry carries `"title": "<actionId>"` (coordinator ruling within
  OD-425), so entries of structurally identical payloads still differ and one document can hold several of them.

`definitions` does not take part in validation, so validating against the document validates the primary payload.
"""
import copy
import hashlib

import rfc8785

DEFINITIONS = "definitions"
IDENTITY_KEYWORDS = ("$schema", "$id")


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def entry(action_id, schema):
    """A standalone payload schema as a definitions entry: identity keywords dropped, content kept, titled by the actionId."""
    value = {k: copy.deepcopy(v) for k, v in schema.items() if k not in IDENTITY_KEYWORDS}
    value["title"] = action_id
    return value


def _forbidden(node, path):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("$ref", "$id", "$schema"):
                raise ValueError("definitions entry %s carries %s" % (path, key))
            _forbidden(value, path + "/" + key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _forbidden(value, "%s/%d" % (path, index))


def check(document):
    """Refuse a document that breaks R2; return {name: digest} of its definitions entries."""
    entries = document.get(DEFINITIONS, {})
    if not isinstance(entries, dict):
        raise ValueError("definitions must be an object")
    root = digest(document)
    digests = {}
    for name, value in entries.items():
        _forbidden(value, name)
        if not isinstance(value, dict) or value.get("title") != name:
            raise ValueError("definitions entry %s must carry its actionId as title" % name)
        digests[name] = digest(value)
    if len(set(digests.values())) != len(digests) or root in digests.values():
        raise ValueError("definitions entry digests must be unique and differ from the document digest")
    return digests


class CapabilityDocument:
    """The negotiated schema of one capability and the payload schema digest of each of its actions."""

    def __init__(self, primary, actions, schemas):
        """primary: the primary actionId; actions: {actionId: schema id}; schemas: {schema id: standalone schema}."""
        self.id = actions[primary]
        self.schema = copy.deepcopy(schemas[self.id])
        others = {action: schemas[identifier] for action, identifier in actions.items() if action != primary}
        if others:
            self.schema[DEFINITIONS] = {action: entry(action, schema) for action, schema in sorted(others.items())}
        entries = check(self.schema)
        self.digest = digest(self.schema)
        self.payload = {primary: self.digest, **entries}

    def payload_digest(self, action_id):
        return self.payload[action_id]
