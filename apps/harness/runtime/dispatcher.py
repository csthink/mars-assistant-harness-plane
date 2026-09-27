"""Connection protocol adapter over the shared DomainPort transaction seam."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

from domain.port import DomainUnavailable
from runtime.host import HostClient
from runtime.protocol import DIGEST, LIMITS, METHODS, VERSION, Fault, Schemas, digest, invalid, evidence_key

def now():
    return datetime.now(timezone.utc)

def future(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) > now()
    except (ValueError, TypeError):
        return False

def ident(prefix):
    return prefix + ":" + uuid.uuid4().hex

class Dispatcher:
    def __init__(self, domain, configuration, transport):
        self.domain, self.config, self.transport = domain, configuration, transport
        self.schemas = Schemas(domain.schemas)
        if any(cap["schemaDigest"] not in self.schemas.digests for cap in domain.capabilities):
            raise ValueError("Capability schemaDigest does not match a preinstalled schema")
        self.context = None
        self.limits = dict(LIMITS)
        self.ready = False
        self.grants, self.grant_revisions, self.authorization_serial = {}, {}, {}
        self.snapshots, self.subscriptions = {}, {}
        self.capabilities = []
        self.shutdown = False
        # feature-t3: purpose-agnostic execution layer for accepted work with an external effect.
        self.executions = None

    async def dispatch(self, method, p):
        if method not in METHODS or METHODS[method]["direction"] != "host-to-runtime":
            raise invalid("Unknown Runtime method", rpc=-32601)
        self.schemas.validate(METHODS[method]["params"], p)
        if method == "runtime.initialize":
            result = self.initialize(p)
        else:
            self.check_context(p)
            if not self.ready and method not in ("runtime.ready", "runtime.health", "runtime.quiesce", "runtime.shutdown"):
                raise Fault("PRECONDITION_CONFLICT", "Runtime is not ready")
            name = method.removeprefix("runtime.").replace(".", "_")
            handler = getattr(self, name + "_" if name in ("ready", "shutdown") else name)
            result = await handler(p)
            result = dict(context=self.context, **result)
        self.schemas.validate(METHODS[method]["result"], result)
        return result

    def initialize(self, p):
        if self.context is not None:
            raise Fault("PRECONDITION_CONFLICT", "Already initialized")
        for key in ("installationId", "instanceId", "incarnationId", "connectionId", "bundleDigest"):
            if p[key] != self.config[key]:
                raise Fault("PERMISSION_DENIED", "Launch identity mismatch")
        auth = p["launchAuthorization"]
        if (auth != self.config["launchAuthorization"] or auth["bundleDigest"] != self.config["bundleDigest"]
                or not future(auth["expiresAt"])):
            raise Fault("PERMISSION_DENIED", "Invalid launch authorization")
        protocol = {"version": VERSION, "contractDigest": DIGEST}
        if protocol not in p["protocols"]:
            raise Fault("UNSUPPORTED_VERSION")
        key = lambda cap: (cap["id"], cap["version"], cap["schemaDigest"])
        offered = {key(cap): cap for cap in p["capabilities"]}
        supported = {key(cap): cap for cap in self.domain.capabilities}
        if len(offered) != len(p["capabilities"]) or len({c["id"] for c in p["capabilities"]}) != len(offered):
            raise invalid("Duplicate capability identity")
        for cap in p["capabilities"]:
            if cap["required"] and key(cap) not in supported:
                raise Fault("UNSUPPORTED_CAPABILITY")
        for cap in supported.values():
            if cap["required"] and key(cap) not in offered:
                raise Fault("UNSUPPORTED_CAPABILITY")
        selected = [copy.deepcopy(cap) for k, cap in supported.items() if k in offered]
        profiles = {(v["id"], v["version"], v["digest"]): v for v in p["executionProfiles"]}
        selected_profiles = []
        for requirement in self.config.get("executionProfileRequirements", []):
            profile = requirement["profile"]
            found = (profile["id"], profile["version"], profile["digest"]) in profiles
            matching = [c for c in selected if c["id"] == requirement["capabilityId"]]
            if not found:
                if any(c["required"] or offered[key(c)]["required"] for c in matching):
                    raise Fault("UNSUPPORTED_CAPABILITY", "Required execution profile missing")
                selected = [c for c in selected if c["id"] != requirement["capabilityId"]]
            elif matching and profile not in selected_profiles:
                selected_profiles.append(profile)
        negotiated = {k: min(v, p["limits"][k]) for k, v in LIMITS.items()}
        minimum = dict(frameBytes=2048, bufferBytes=2048, depth=8, members=32, textCharacters=256)
        if any(negotiated[key] < value for key, value in minimum.items()):
            raise Fault("RESOURCE_LIMIT", "Negotiated limits cannot carry the supported control profile", recovery="retry-later")
        generation = self.domain.acquire_generation()
        self.context = dict(protocolVersion=VERSION, contractDigest=DIGEST, controlGeneration=generation,
                            **{k: self.config[k] for k in ("installationId", "instanceId", "incarnationId", "connectionId")})
        self.host = HostClient(self.transport, self.schemas, self.context)
        self.start_executions()
        self.capabilities = selected
        self.limits = negotiated
        return dict(context=self.context, selectedProtocol=protocol, capabilities=selected,
                    limits=self.limits, executionProfiles=selected_profiles, recovery="snapshot-and-operation-query")

    def execution_executors(self):
        """Production executors by purpose (runtime/executions.py); None selects them."""
        return None

    def start_executions(self):
        """Create the execution layer once the Host client exists and resume unsettled work (query only)."""
        if self.executions is not None or not hasattr(self.domain, "executions"):
            return
        from runtime.executions import Environment, ExecutionLayer
        env = Environment("runtime", self.domain, lambda: self.context["controlGeneration"], host=self.host,
                          config=self.config, repository_root=getattr(self.domain, "repository", None))
        self.executions = ExecutionLayer(self.domain, env, self.execution_executors())
        self.executions.schedule(resume=True)

    def check_context(self, p):
        if self.context is None or p["context"] != self.context:
            raise Fault("WRITER_CONFLICT", "Connection context mismatch", recovery="reconnect")
        if self.domain.read()["generation"] != self.context["controlGeneration"]:
            raise Fault("WRITER_CONFLICT", "Stale control generation", recovery="reconnect")

    def transact(self, callback):
        try:
            return self.domain.transaction(self.context["controlGeneration"], callback, intent="control")
        except DomainUnavailable as exc:
            raise Fault("UNSUPPORTED_CAPABILITY", str(exc)) from exc

    async def ready_(self, p):
        self.ready = True
        return {"ready": True}

    async def health(self, p):
        # A degraded port states its own reason when it has one; silence would hide why.
        reason = getattr(self.domain, "unavailable_reason", "Production DomainPort is not installed")
        return dict(health="ready" if self.domain.available else "degraded",
                    reason="" if self.domain.available else reason)

    async def scope_open(self, p):
        binding = p["binding"]
        if not future(binding["expiresAt"]):
            raise Fault("PERMISSION_DENIED", "Scope binding expired")
        def commit(s):
            existing = s["bindings"].get(binding["bindingRef"])
            if existing:
                if existing["resourceHandle"] != binding["resourceHandle"]:
                    raise Fault("PRECONDITION_CONFLICT", "Binding identity changed")
                return existing["scopeRef"]
            scope = "scope:" + hashlib.sha256(binding["bindingRef"].encode()).hexdigest()[:24]
            s["bindings"][binding["bindingRef"]] = dict(resourceHandle=binding["resourceHandle"], scopeRef=scope)
            # Binding allocates identity only. No target resource is opened here.
            s["scopes"].setdefault(scope, dict(resourceHandle=binding["resourceHandle"], objects=[], actions=[],
                pendingItems=[], events=[], streamId=ident("stream"), epoch="1", seq="0", logFloor="0"))
            return scope
        scope = self.transact(commit)
        self.grants.pop(scope, None)
        self.authorization_serial[scope] = self.authorization_serial.get(scope, 0) + 1
        return dict(scopeRef=scope, bindingRef=binding["bindingRef"], state="inactive")

    def scope(self, state, scope):
        if scope not in state["scopes"]:
            raise Fault("PERMISSION_DENIED", "Unknown or inaccessible scope")
        return state["scopes"][scope]

    async def resolve_grants(self, scope, refs, method=None, capability=None):
        source = self.scope(self.domain.read(), scope)
        if not refs:
            raise Fault("PERMISSION_DENIED", recovery="reauthorize")
        response = await self.host.call("host.grants.get", {"grantRefs": refs})
        grants = response["grants"]
        if len(grants) != len(refs) or len({r["id"] for r in refs}) != len(refs):
            raise Fault("PERMISSION_DENIED", "Grant set incomplete")
        for ref in refs:
            found = [g for g in grants if g["ref"] == ref]
            if len(found) != 1:
                raise Fault("PERMISSION_REVOKED", "Grant revision is no longer current", recovery="reauthorize")
            g = found[0]
            if (g["installationId"] != self.context["installationId"] or g["instanceId"] != self.context["instanceId"]
                    or g["scopeRef"] != scope or g["resourceHandle"] != source["resourceHandle"]
                    or g["bundleDigest"] != self.config["bundleDigest"] or g["executionRef"] is not None):
                raise Fault("PERMISSION_DENIED", "Grant identity mismatch")
            if g["status"] != "active" or not future(g["expiresAt"]):
                raise Fault("PERMISSION_REVOKED", recovery="reauthorize")
            if int(ref["revision"]) < self.grant_revisions.get(ref["id"], -1):
                raise Fault("PERMISSION_REVOKED", "Stale grant revision", recovery="reauthorize")
            self.grant_revisions[ref["id"]] = int(ref["revision"])
        if method and not any(g["operation"] == method and (capability is None or g["capability"] == capability) for g in grants):
            raise Fault("PERMISSION_DENIED", "Grant does not cover this operation")
        return grants

    async def scope_authorize(self, p):
        self.scope(self.domain.read(), p["scopeRef"])
        # A failed replacement also cannot retain an earlier usable set.
        serial = self.authorization_serial.get(p["scopeRef"], 0) + 1
        self.authorization_serial[p["scopeRef"]] = serial
        self.grants[p["scopeRef"]] = []
        if p["grantRefs"]:
            await self.resolve_grants(p["scopeRef"], p["grantRefs"])
        self.check_context(p)
        if self.authorization_serial[p["scopeRef"]] != serial:
            raise Fault("PERMISSION_REVOKED", "Authorization superseded", recovery="reauthorize")
        self.grants[p["scopeRef"]] = copy.deepcopy(p["grantRefs"])
        return dict(scopeRef=p["scopeRef"], state="active" if p["grantRefs"] else "inactive")

    async def authorize(self, p, method, capability=None):
        scope = p.get("scopeRef", "instance")
        if scope == "instance":
            if method not in ("runtime.operation.get", "runtime.operation.cancel"):
                raise Fault("PERMISSION_DENIED", "Reserved instance scope")
            return []
        serial = self.authorization_serial.get(scope, 0)
        active = copy.deepcopy(self.grants.get(scope, []))
        refs = p.get("grantRefs", active)
        if not active or any(r not in active for r in refs):
            raise Fault("PERMISSION_DENIED", "Scope inactive", recovery="reauthorize")
        grants = await self.resolve_grants(scope, refs, method, capability)
        self.check_context(p)
        if self.authorization_serial.get(scope, 0) != serial or self.grants.get(scope, []) != active:
            raise Fault("PERMISSION_REVOKED", "Scope authorization changed during request", recovery="reauthorize")
        return grants

    async def snapshot_open(self, p):
        await self.authorize(p, "runtime.snapshot.open")
        self.snapshots = {k: v for k, v in self.snapshots.items() if future(v["expires"])}
        if len(self.snapshots) >= 8:
            raise Fault("RESOURCE_LIMIT", "Active snapshot lease limit", recovery="retry-later")
        s = self.domain.read()
        scope = self.scope(s, p["scopeRef"])
        snapshot_id = ident("snapshot")
        entries = [(k, v) for k in ("objects", "actions", "pendingItems") for v in scope[k]]
        pages, limit = [], self.limits["pageObjects"]
        expires = (now() + timedelta(seconds=60)).isoformat()
        chunks = [entries[i:i+limit] for i in range(0, len(entries), limit)] or [[]]
        tokens = [ident("page") for _ in chunks]
        for index, chunk in enumerate(chunks):
            page = dict(scopeRef=p["scopeRef"], snapshotId=snapshot_id, revision=s["revision"],
                streamId=scope["streamId"], epoch=scope["epoch"], throughSeq=scope["seq"], expiresAt=expires,
                objects=[], actions=[], pendingItems=[], nextPageToken=tokens[index+1] if index+1 < len(chunks) else None)
            for kind, item in chunk:
                page[kind].append(copy.deepcopy(item))
            pages.append(page)
        import json
        size = len(json.dumps(pages, ensure_ascii=False).encode())
        if size + sum(v["bytes"] for v in self.snapshots.values()) > 32 * 1024 * 1024:
            raise Fault("RESOURCE_LIMIT", "Snapshot byte budget", recovery="retry-later")
        self.snapshots[snapshot_id] = dict(pages=pages, tokens=tokens, expires=expires, bytes=size)
        return pages[0]

    def snapshot(self, p):
        snap = self.snapshots.get(p["snapshotId"])
        if not snap or not future(snap["expires"]) or snap["pages"][0]["scopeRef"] != p["scopeRef"]:
            raise Fault("RESYNC_REQUIRED", recovery="resync")
        return snap

    async def snapshot_next(self, p):
        await self.authorize(p, "runtime.snapshot.next")
        snap = self.snapshot(p)
        if p["pageToken"] not in snap["tokens"][1:]:
            raise Fault("RESYNC_REQUIRED", recovery="resync")
        return snap["pages"][snap["tokens"].index(p["pageToken"])]

    async def events_subscribe(self, p):
        await self.authorize(p, "runtime.events.subscribe")
        snap = self.snapshot(p)["pages"][0]
        s = self.scope(self.domain.read(), p["scopeRef"])
        if (p["streamId"] != snap["streamId"] or p["epoch"] != snap["epoch"] or p["epoch"] != s["epoch"]
                or p["streamId"] != s["streamId"] or p["afterSeq"] != snap["throughSeq"]
                or int(p["afterSeq"]) < int(s["logFloor"])):
            raise Fault("RESYNC_REQUIRED", recovery="resync")
        previous = self.subscriptions.get(p["scopeRef"])
        subscription_id = ident("subscription")
        self.subscriptions[p["scopeRef"]] = dict(id=subscription_id, scope=p["scopeRef"], stream=s["streamId"],
            epoch=s["epoch"], sent=int(p["afterSeq"]), ack=int(p["afterSeq"]), outstanding=[], caught=None, enabled=False)
        return dict(subscriptionId=subscription_id, replacedSubscriptionId=previous["id"] if previous else None)

    async def events_ack(self, p):
        sub = next((s for s in self.subscriptions.values() if s["id"] == p["subscriptionId"]), None)
        if sub is None or p["streamId"] != sub["stream"] or p["epoch"] != sub["epoch"]:
            raise Fault("RESYNC_REQUIRED", recovery="resync")
        await self.authorize(dict(p, scopeRef=sub["scope"]), "runtime.events.ack")
        seq = int(p["seq"])
        if seq > sub["sent"]:
            raise Fault("PRECONDITION_CONFLICT", "ACK exceeds delivered contiguous sequence")
        sub["ack"] = max(seq, sub["ack"])
        sub["outstanding"] = [(n, b) for n, b in sub["outstanding"] if n > sub["ack"]]
        return dict(acknowledgedSeq=str(sub["ack"]))

    def replay(self, s, method, p):
        if p["requestDigest"] != digest(method, p):
            raise Fault("INTEGRITY_MISMATCH", "Request digest mismatch")
        scope = p.get("scopeRef", "instance")
        key = json_key([self.context["installationId"], self.context["instanceId"], scope, method, p["idempotencyKey"]])
        old_id = s["keys"].get(key)
        old = s["operations"].get(p["operationId"])
        if old_id or old:
            if old_id != p["operationId"] or old is None or old["requestDigest"] != p["requestDigest"]:
                raise Fault("IDEMPOTENCY_CONFLICT")
            value = copy.deepcopy(old["value"])
            if old["tombstone"]:
                value.update(status="unknown", reason="Result retained as tombstone")
                if "resultRef" in value:
                    value.update(resultRef=None, executionRef=None, resultCode=None)
            return value
        if not s["indexComplete"]:
            raise Fault("RESULT_UNKNOWN", recovery="query")
        return None

    def mutation(self, method, p, callback, capability=None):
        scope = p.get("scopeRef", "instance")
        key = json_key([self.context["installationId"], self.context["instanceId"], scope, method, p["idempotencyKey"]])
        def commit(s):
            previous = self.replay(s, method, p)
            if previous is not None:
                return previous
            value = callback(s)
            s["keys"][key] = p["operationId"]
            s["operations"][p["operationId"]] = dict(requestDigest=p["requestDigest"], scope=scope,
                method=method, value=copy.deepcopy(value), tombstone=False, capability=capability)
            return value
        return self.transact(commit)

    def operation(self, s, p, status="succeeded", reason=""):
        return dict(operationId=p["operationId"], scopeRef=p.get("scopeRef", "instance"), requestDigest=p["requestDigest"],
            status=status, resultRef=None, executionRef=None, reason=reason, resultCode=None, revision=s["revision"])

    def emit(self, s, scope, kind, payload, cause=None):
        view = s["scopes"][scope]
        view["seq"] = str(int(view["seq"]) + 1)
        view["events"].append(dict(eventId=ident("event"), scopeRef=scope, streamId=view["streamId"], epoch=view["epoch"],
            seq=view["seq"], domainRevision=s["revision"], causationId=cause, kind=kind, payload=copy.deepcopy(payload)))

    async def action_invoke(self, p):
        # Permission is checked before inspecting idempotency or exposing prior results.
        await self.authorize(p, "runtime.action.invoke")
        state = self.domain.read()
        record = state["operations"].get(p["operationId"])
        if record and record.get("capability"):
            await self.authorize(p, "runtime.action.invoke", record["capability"])
        previous = self.replay(state, "runtime.action.invoke", p)
        if previous is not None:
            return previous
        action = self.domain.action(state, p["scopeRef"], p["actionId"])
        await self.authorize(p, "runtime.action.invoke", action["capability"]["id"])
        decision = None
        if action["requiresHumanDecision"]:
            if not p["decisionRef"]:
                raise Fault("PERMISSION_DENIED", "Trusted Human decision required")
            decision = await self.host.call("host.decision.get", dict(scopeRef=p["scopeRef"], decisionRef=p["decisionRef"]))
        # Recheck after an awaited trusted decision, immediately before durable acceptance.
        checked_grants = await self.authorize(p, "runtime.action.invoke", action["capability"]["id"])
        def commit(s):
            if any(g["status"] != "active" or not future(g["expiresAt"]) for g in checked_grants):
                raise Fault("PERMISSION_REVOKED", recovery="reauthorize")
            if s["quiesced"] or s["barrier"]:
                raise Fault("BUSY", "Domain writes paused", recovery="retry-later")
            current = self.domain.action(s, p["scopeRef"], p["actionId"])
            if current != action or not current["enabled"]:
                raise Fault("PRECONDITION_CONFLICT", "Domain action changed or disabled")
            for field in ("objectRef", "expectedRevision", "candidateRef"):
                if p[field] != current[field]:
                    raise Fault("PRECONDITION_CONFLICT", "Stale action binding")
            if current["capability"] not in self.capabilities:
                raise Fault("UNSUPPORTED_CAPABILITY")
            # The payload schema must resolve inside this action's negotiated capability document (OD-425 R1, R4;
            # Contract README line 136); a digest that is merely installed, or negotiated for another capability, is
            # an unknown schema.
            target = self.schemas.resolve(current["capability"], current["payloadSchemaDigest"])
            if target is None:
                raise Fault("UNSUPPORTED_CAPABILITY", "Payload schema is not in the action's negotiated capability")
            self.schemas.payload(target, p["payload"])
            if current["requiresHumanDecision"]:
                expected = dict(decisionRef=p["decisionRef"], scopeRef=p["scopeRef"], domainOperationId=p["operationId"],
                    method="runtime.action.invoke", requestDigest=p["requestDigest"], actionId=p["actionId"],
                    objectRef=p["objectRef"], candidateRef=p["candidateRef"], expectedRevision=p["expectedRevision"],
                    source="host-trusted-ui", status="valid")
                if not decision or any(decision[k] != v for k, v in expected.items()):
                    raise Fault("PERMISSION_DENIED", "Decision binding mismatch")
                required = s.get("decisionEvidence", {}).get(p["actionId"], [])
                if any(e not in decision["evidence"] for e in required):
                    raise Fault("PERMISSION_DENIED", "Viewed evidence missing")
            op = self.operation(s, p, "accepted")
            self.domain.accept_action(s, op, p)
            self.emit(s, p["scopeRef"], "operation.changed", op, p["operationId"])
            return op
        result = self.mutation("runtime.action.invoke", p, commit, action["capability"]["id"])
        if self.executions is not None:
            self.executions.schedule()
        return result

    def lookup(self, s, operation_id, scope=None):
        record = s["operations"].get(operation_id)
        if record is None:
            if s["indexComplete"]:
                raise Fault("NOT_FOUND", "Operation was never accepted", absence=True)
            raise Fault("RESULT_UNKNOWN", recovery="query")
        if scope is not None and record["scope"] != scope:
            raise Fault("PERMISSION_DENIED")
        if record["tombstone"]:
            raise Fault("RESULT_UNKNOWN", recovery="query")
        return record

    async def operation_get(self, p):
        await self.authorize(p, "runtime.operation.get")
        record = self.lookup(self.domain.read(), p["operationId"], p["scopeRef"])
        if record.get("capability"):
            await self.authorize(p, "runtime.operation.get", record["capability"])
        if record["method"] == "runtime.upgrade.prepare":
            raise Fault("PRECONDITION_CONFLICT", "Use runtime.upgrade.get")
        return record["value"]

    async def operation_cancel(self, p):
        await self.authorize(p, "runtime.operation.cancel")
        def commit(s):
            target = self.lookup(s, p["targetOperationId"], p["scopeRef"])["value"]
            if target["status"] in ("accepted", "running"):
                # No physical state is inferred. Execution-owned work stays pending settlement.
                if target["executionRef"] is None:
                    target.update(status="cancelled", reason="Cancelled before further domain work", revision=s["revision"])
                    self.emit(s, p["scopeRef"], "operation.changed", target, p["operationId"])
                else:
                    if self.executions is not None:
                        self.executions.cancel(target["executionRef"])
                    return self.operation(s, p, "accepted", "Physical stop and domain settlement required")
            return self.operation(s, p, reason="Target " + target["status"])
        return self.mutation("runtime.operation.cancel", p, commit)

    async def quiesce(self, p):
        if self.executions is not None:
            self.executions.accepting = False
        def commit(s):
            s["quiesced"] = True
            return self.operation(s, p)
        return self.mutation("runtime.quiesce", p, commit)

    async def shutdown_(self, p):
        def commit(s):
            s["quiesced"] = True
            s["shutdown"] = True
            return self.operation(s, p)
        op = self.mutation("runtime.shutdown", p, commit)
        self.shutdown = True
        if self.executions is not None:
            self.executions.stop()
        return op

    async def upgrade_prepare(self, p):
        def commit(s):
            if p["sourceBundleDigest"] != self.config["bundleDigest"] or p["sourceDataFormat"] != s["dataFormat"]:
                raise Fault("PRECONDITION_CONFLICT", "Upgrade source identity mismatch")
            if s["barrier"]:
                raise Fault("BUSY", "Upgrade barrier already exists", recovery="retry-later")
            protected = copy.deepcopy(s["protectedReferences"])
            if len(protected) > self.limits["pageObjects"]:
                raise Fault("RESOURCE_LIMIT", "Complete protected set exceeds limit", recovery="retry-later")
            barrier = None if protected else ident("barrier")
            result = dict(operationId=p["operationId"], requestDigest=p["requestDigest"],
                **{k: p[k] for k in ("sourceBundleDigest", "targetBundleDigest", "sourceDataFormat", "targetDataFormat")},
                status="blocked" if protected else "prepared", barrierRef=barrier, domainRevision=s["revision"],
                preparedGeneration=s["generation"], protectedReferences=protected, reason="Protected references" if protected else "",
                releasedDomainRevision=None)
            s["upgrades"][p["operationId"]] = result
            s["barrier"] = barrier
            return result
        return self.mutation("runtime.upgrade.prepare", p, commit)

    async def upgrade_get(self, p):
        s = self.domain.read()
        record = self.lookup(s, p["operationId"], "instance")
        if record["method"] != "runtime.upgrade.prepare":
            raise Fault("PRECONDITION_CONFLICT")
        return s["upgrades"][p["operationId"]]

    async def upgrade_release(self, p):
        def commit(s):
            self.lookup(s, p["prepareOperationId"], "instance")
            upgrade = s["upgrades"].get(p["prepareOperationId"])
            if not upgrade or upgrade["status"] != "prepared" or s["barrier"] != p["barrierRef"] or upgrade["barrierRef"] != p["barrierRef"]:
                raise Fault("PRECONDITION_CONFLICT", "Persistent barrier mismatch")
            prefix = "target" if p["disposition"] == "activated" else "source"
            if (p["runningBundleDigest"] != self.config["bundleDigest"] or p["runningBundleDigest"] != upgrade[prefix+"BundleDigest"]
                    or p["dataFormat"] != s["dataFormat"] or p["dataFormat"] != self.config["dataFormat"]
                    or p["dataFormat"] != upgrade[prefix+"DataFormat"]):
                raise Fault("INTEGRITY_MISMATCH", "Running bundle or data format mismatch")
            upgrade.update(status="released", releasedDomainRevision=s["revision"])
            s["barrier"] = None
            s["quiesced"] = False
            s["shutdown"] = False
            return self.operation(s, p)
        return self.mutation("runtime.upgrade.release", p, commit)

    async def resource_read(self, p):
        await self.authorize(p, "runtime.resource.read")
        evidence = p["evidence"]
        if evidence["authority"] != "runtime" or evidence["scopeRef"] != p["scopeRef"]:
            raise Fault("INVALID_SOURCE", "Evidence authority or scope mismatch")
        s = self.domain.read()
        resource = s["resources"].get(evidence_key(evidence))
        if resource is None:resource = s["resources"].get(evidence["resourceHandle"])
        if not resource or resource["evidence"] != evidence:
            raise Fault("INTEGRITY_MISMATCH", "Evidence identity mismatch")
        for record in s["operations"].values():
            op = record["value"]
            if op.get("resultRef") == evidence and op["status"] in ("failed", "cancelled"):
                raise Fault("EXECUTION_FAILED" if op["status"] == "failed" else "CANCELLED")
        raw = base64.b64decode(resource["dataBase64"], validate=True)
        if len(raw) != evidence["bytes"] or hashlib.sha256(raw).hexdigest() != evidence["digest"]:
            raise Fault("INTEGRITY_MISMATCH")
        if p["offset"] > len(raw):
            raise Fault("PRECONDITION_CONFLICT", "Offset exceeds resource")
        end = min(len(raw), p["offset"] + p["length"])
        return dict(resourceHandle=evidence["resourceHandle"], revision=evidence["revision"], offset=p["offset"],
                    dataBase64=base64.b64encode(raw[p["offset"]:end]).decode(), eof=end==len(raw), digest=evidence["digest"])

def json_key(value):
    import json
    return json.dumps(value, separators=(",", ":"))
