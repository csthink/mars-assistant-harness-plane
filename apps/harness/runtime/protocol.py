"""Frozen wire validation. No retrieval callback can access disk or network."""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urldefrag

import rfc8785
from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT7

VERSION = "0.1.0-draft.5"
DIGEST = "9d6e6af19a39cc52d0b86f7ce610b44d4b21517feebecf5d88df05f73b83a352"
LIMITS = dict(frameBytes=1048576, depth=32, members=1000, inFlight=32,
              bufferBytes=4194304, eventWindow=128, pageObjects=100, textCharacters=65536)
CONTRACT = Path(__file__).resolve().parents[1] / "contract"
SCHEMA = json.loads((CONTRACT / "schema.json").read_text())
METHODS = json.loads((CONTRACT / "methods.json").read_text())["methods"]

class Fault(Exception):
    def __init__(self, code, message=None, *, rpc=-32000, recovery="none", absence=False):
        self.code, self.rpc, self.recovery, self.absence = code, rpc, recovery, absence
        super().__init__(message or code)

    def error(self, params=None):
        p = params if isinstance(params, dict) else {}
        return dict(code=self.rpc, message=str(self)[:1024], data=dict(
            code=self.code, scopeRef=p.get("scopeRef"), operationId=p.get("operationId"),
            recovery=self.recovery, absenceProven=self.absence))

def invalid(message="Invalid request parameters", rpc=-32602):
    return Fault("PRECONDITION_CONFLICT", message, rpc=rpc)

def canonical(value):
    try:
        return rfc8785.dumps(value)
    except (ValueError, TypeError) as exc:
        raise invalid("Value outside I-JSON domain") from exc

def evidence_key(evidence):
    """Internal immutable resource key; the wire resourceHandle stays Grant-bound."""
    return "evidence:" + hashlib.sha256(canonical(evidence)).hexdigest()

def digest(method, params):
    return hashlib.sha256(canonical(dict(method=method, **{
        k: v for k, v in params.items() if k not in ("context", "requestDigest")}))).hexdigest()

def no_retrieve(uri):
    raise NoSuchResource(ref=uri)

class Schemas:
    def __init__(self, capabilities=None):
        self.resources = {SCHEMA["$id"]: SCHEMA, **(capabilities or {})}
        # Reject unknown references at registration, including references in unused branches.
        for uri, schema in self.resources.items():
            Draft7Validator.check_schema(schema)
            self._refs(schema, uri)
        self.digests = {hashlib.sha256(canonical(schema)).hexdigest(): uri
                        for uri, schema in (capabilities or {}).items()}
        self.registry = Registry(retrieve=no_retrieve).with_resources(
            (uri, Resource.from_contents(schema, default_specification=DRAFT7))
            for uri, schema in self.resources.items())

    def _refs(self, node, base):
        if isinstance(node, dict):
            if "$id" in node and node["$id"] != base:
                raise ValueError("Nested schema identity is not registered")
            if "$ref" in node:
                ref = node["$ref"]
                target, fragment = urldefrag(ref)
                if target and (target not in self.resources or target.startswith(("http:", "https:", "file:"))):
                    raise ValueError("Unregistered or external schema reference")
                resource = self.resources[target or base]
                if fragment:
                    if not fragment.startswith("/"):
                        raise ValueError("Only registered JSON pointer references supported")
                    for part in fragment[1:].split("/"):
                        try:
                            resource = resource[part.replace("~1", "/").replace("~0", "~")]
                        except (KeyError, TypeError) as exc:
                            raise ValueError("Missing local schema reference") from exc
            for value in node.values():
                self._refs(value, base)
        elif isinstance(node, list):
            for value in node:
                self._refs(value, base)

    def validate(self, definition, value):
        schema = {"$ref": SCHEMA["$id"] + "#/definitions/" + definition}
        self._validate(schema, value)

    def resolve(self, capability, payload_digest):
        """Where an action's payload schema lives inside its negotiated capability document, or None (OD-425 R1).

        The payloadSchemaDigest must equal the capability's schemaDigest (the document root, the primary action)
        or the RFC 8785 SHA-256 of exactly one entry of that document's root `definitions`. Anything else is an
        unknown schema, which is never executed generically (Contract README line 136).
        """
        uri = self.digests.get(capability["schemaDigest"])
        if uri is None:
            return None
        if payload_digest == capability["schemaDigest"]:
            return uri
        entries = self.resources[uri].get("definitions")
        if not isinstance(entries, dict):
            return None
        names = [name for name, value in entries.items() if hashlib.sha256(canonical(value)).hexdigest() == payload_digest]
        if len(names) != 1:
            return None
        return uri + "#/definitions/" + names[0].replace("~", "~0").replace("/", "~1")

    def payload(self, uri, value):
        if urldefrag(uri)[0] not in self.resources:
            raise Fault("UNSUPPORTED_CAPABILITY")
        self._validate({"$ref": uri}, value)

    def _validate(self, schema, value):
        try:
            Draft7Validator(schema, registry=self.registry, format_checker=FormatChecker()).validate(value)
        except Exception as exc:
            raise invalid("Schema validation failed") from exc

def decode(raw, limits):
    if len(raw) > limits["frameBytes"] or not raw.endswith(b"\n"):
        raise Fault("RESOURCE_LIMIT", "Frame exceeds limit or lacks LF", rpc=-32600)
    def pairs(items):
        if len(items) > limits["members"] or len({k for k, _ in items}) != len(items):
            raise ValueError("Duplicate key or member limit")
        return dict(items)
    def constant(_):
        raise ValueError("Non-finite number")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                           parse_constant=constant)
        def visit(node, depth=1):
            if depth > limits["depth"]:
                raise ValueError("Depth limit")
            if isinstance(node, str):
                node.encode("utf-8", errors="strict")
                if len(node) > limits["textCharacters"]:
                    raise ValueError("Text limit")
            elif isinstance(node, (int, float)) and not isinstance(node, bool):
                if not math.isfinite(node) or (float(node).is_integer() and abs(node) > 9007199254740991):
                    raise ValueError("I-JSON number limit")
            elif isinstance(node, (list, dict)):
                if len(node) > limits["members"]:
                    raise ValueError("Member limit")
                if isinstance(node, dict):
                    for key in node:
                        visit(key, depth+1)
                for child in (node.values() if isinstance(node, dict) else node):
                    visit(child, depth+1)
        visit(value)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise invalid("Invalid UTF-8 JSON frame", rpc=-32700) from exc
    if not isinstance(value, dict):
        raise invalid("Batch and scalar frames are unsupported", rpc=-32600)
    return value

def encode(value, limits):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(raw) > limits["frameBytes"]:
        raise Fault("RESOURCE_LIMIT", "Outgoing frame too large")
    return raw
