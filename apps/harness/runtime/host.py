"""Typed reverse RPC client. Transport handles correlation and deadlines.

These methods do not implement or qualify a physical ExecutionPort.
"""
import base64
import binascii
import hashlib

from runtime.protocol import METHODS, Fault, digest

class HostClient:
    def __init__(self, transport, schemas, context):
        self.transport, self.schemas, self.context = transport, schemas, context

    async def call(self, method, params, timeout=5):
        if method not in METHODS or METHODS[method]["direction"] != "runtime-to-host":
            raise ValueError("Not a Host method")
        request = dict(context=self.context, **params)
        if method == "host.resource.read" and params.get("evidence", {}).get("authority") != "host":
            raise Fault("INVALID_SOURCE")
        self.schemas.validate(METHODS[method]["params"], request)
        if "requestDigest" in params and params["requestDigest"] != digest(method, request):
            raise Fault("INTEGRITY_MISMATCH", "Host request digest mismatch")
        result = await self.transport.call_host(method, request, timeout)
        self.schemas.validate(METHODS[method]["result"], result)
        if result["context"] != self.context:
            raise Fault("WRITER_CONFLICT", "Host reply context mismatch", recovery="reconnect")
        for field in ("scopeRef", "operationId", "requestDigest", "executionRef", "profileDigest", "decisionRef", "domainOperationId"):
            if field in params and field in result and result[field] != params[field]:
                raise Fault("INTEGRITY_MISMATCH", "Host result identity mismatch")
        if method == "host.resource.read":
            evidence = params["evidence"]
            if evidence["authority"] != "host":
                raise Fault("INVALID_SOURCE")
            for field in ("resourceHandle", "revision", "digest"):
                if result[field] != evidence[field]:
                    raise Fault("INTEGRITY_MISMATCH", "Host evidence identity mismatch")
            if result["offset"] != params["offset"]:
                raise Fault("INTEGRITY_MISMATCH", "Host chunk offset mismatch")
            try:
                raw = base64.b64decode(result["dataBase64"], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise Fault("INTEGRITY_MISMATCH", "Invalid Host chunk encoding") from exc
            end = params["offset"] + len(raw)
            if len(raw) > params["length"] or end > evidence["bytes"]:
                raise Fault("INTEGRITY_MISMATCH", "Host chunk exceeds authorized byte range")
            if result["eof"] != (end == evidence["bytes"]) or (not raw and not result["eof"]):
                raise Fault("INTEGRITY_MISMATCH", "Host chunk EOF or progress mismatch")
            if params["offset"] == 0 and result["eof"] and hashlib.sha256(raw).hexdigest() != evidence["digest"]:
                raise Fault("INTEGRITY_MISMATCH", "Complete Host resource digest mismatch")
        if method == "host.context.capture" and result["status"] == "succeeded":
            sources = [item["source"] for item in result["snapshots"]]
            if len(sources) != len(params["sources"]) or any(source not in sources for source in params["sources"]):
                raise Fault("INTEGRITY_MISMATCH", "Context capture source coverage mismatch")
        return result
