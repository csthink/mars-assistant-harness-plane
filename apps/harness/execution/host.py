"""Host-backed physical execution with durable reservation before any side effect.

No local Agent spawn or arbitrary result path is used. Unknown calls are queried
under their original identities, including after process restart.
"""
import asyncio
import base64
import copy
from datetime import datetime, timezone
import json
from runtime.protocol import Schemas, Fault, digest, evidence_key
from domain.port import DomainUnavailable
from .port import ExecutionAuthorization, ExecutionDiscovery, ExecutionError, require, sha, identity
from .materials import sealed_materials, export_resources


# Purposes a port instance serves and the Capability Contract roleIntent each maps to (feature-t4).
ROLE_INTENT = {"review": "review", "coding-implementer": "implement"}


def without_program(profile):
    """Profile fields a registration binds; programIdentity is rediscovered per execution (OD-399)."""
    return {k: v for k, v in profile.items() if k != "programIdentity"}


class HostExecutionPort:
    mode = "embedded"
    purpose = "review"

    def __init__(self, host, domain, registration, mapping, discover, authorize, purpose=None):
        self.host, self.domain = host, domain
        if purpose is not None:
            self.purpose = purpose
        require(self.purpose in ROLE_INTENT, "execution-port-purpose-mismatch")
        self.registration, self.mapping = copy.deepcopy(registration), copy.deepcopy(mapping)
        self.discover, self.authorize = discover, authorize
        self.schemas = Schemas()
        self._result_scanner = None
        self._review_owner = None
        self.program_identity = None

    def bind_result_scanner(self, owner, scanner):
        """One trusted execution context owns this port for its entire lifetime."""
        require(owner is not None and callable(scanner), "execution-port-capability-unverified")
        require(self._review_owner is None, "execution-port-capability-unverified")
        self._review_owner, self._result_scanner = owner, scanner

    def check_secrets(self, value, raw=b''):
        require(callable(self._result_scanner), "execution-port-capability-unverified")
        secrets=self._result_scanner()
        require(isinstance(secrets,(list,tuple)) and all(isinstance(v,(str,bytes)) and v for v in secrets),"execution-port-capability-unverified")
        secrets=[v.encode() if isinstance(v,str) else v for v in secrets]
        def scan(v):
            if isinstance(v,str):
                encoded=v.encode('utf-8','strict')
                require(not any(s in encoded for s in secrets),"secret-leak")
            elif isinstance(v,dict):
                for k,item in v.items():scan(k);scan(item)
            elif isinstance(v,(list,tuple)):
                for item in v:scan(item)
        require(not any(s in raw for s in secrets),"secret-leak")
        scan(value)

    def transact(self, generation, callback):
        if not self.domain.available:
            raise ExecutionError("execution-port-capability-unverified")
        try:
            return self.domain.transaction(generation, callback)
        except DomainUnavailable as exc:
            raise ExecutionError("execution-port-capability-unverified") from exc

    async def exchange(self, rec, method, params):
        """Only explicit backpressure is retried under the same key and digest."""
        for attempt in range(3):
            try:
                result=await self.host.call(method,params)
                self.check_secrets(result)
                return result
            except Fault as exc:
                rec=self.update(rec,lambda r:r.update(last_fault=dict(method=method,code=exc.code,absence_proven=exc.absence,recovery=exc.recovery)))
                if exc.code in ("BUSY","RESOURCE_LIMIT") and exc.recovery=="retry-later" and attempt<2:
                    await asyncio.sleep(0.05 * (attempt+1));continue
                if exc.code=="RESULT_UNKNOWN":raise
                code="execution-port-integrity-mismatch" if exc.code=="INTEGRITY_MISMATCH" else "execution-port-capability-unverified" if exc.code in ("PERMISSION_DENIED","PERMISSION_REVOKED") else "execution_port_failure"
                raise ExecutionError(code) from exc
            except (TimeoutError,ConnectionError):
                self.update(rec,lambda r:r.update(last_fault=dict(method=method,code="RESULT_UNKNOWN",absence_proven=False,recovery="query-original")))
                raise

    async def authority(self, intent):
        auth = await self.authorize(copy.deepcopy(intent))
        require(isinstance(auth, ExecutionAuthorization), "execution-port-capability-unverified")
        require(auth.intent_digest == identity(intent) and auth.invocation_sha256 == sha(intent["invocation_authorization"].encode()) and auth.caller == intent["caller"] and isinstance(auth.authorization_ref,str) and bool(auth.authorization_ref) and type(auth.max_calls) is int and auth.max_calls >= 1, "execution-port-capability-unverified")
        require(isinstance(auth.author_vendors, tuple) and type(auth.human_only) is bool and auth.human_only == (not auth.author_vendors) and all(v in ("Anthropic", "OpenAI", "DeepSeek", "Zhipu") for v in auth.author_vendors) and len(set(auth.author_vendors)) == len(auth.author_vendors) and isinstance(auth.author_evidence_refs, tuple) and bool(auth.author_evidence_refs) and all(isinstance(v,str) and v for v in auth.author_evidence_refs) and type(auth.owner_formal) is bool, "eligibility")
        # Reviewer eligibility: the executing vendor must be outside the author set. An Implementer is
        # the author, so this cross-vendor rule applies to the review purpose only.
        require(self.purpose != "review" or intent["executionBinding"]["modelVendor"] not in auth.author_vendors, "eligibility")
        return auth

    async def discovery(self, intent):
        found = await self.discover()
        require(isinstance(found, ExecutionDiscovery), "execution-port-identity-unverified")
        require(found.connection_ref == intent["connectionRef"] and found.registry_provider == self.registration["provider"] and found.configuration_revision == intent["executionBinding"]["configurationRevision"] and (bool(found.protocol_provider) or self.mode=="standalone"), "execution-port-binding-mismatch")
        if self.purpose == "review":
            require(found.profile == self.registration["profile"] == intent["profile"], "execution-port-profile-mismatch")
        else:
            # Version independence: the registration and the request bind every profile field except
            # programIdentity, which must be present, is schema-checked and is recorded per execution.
            require(isinstance(found.profile, dict) and isinstance(found.profile.get("programIdentity"), dict), "execution-port-identity-unverified")
            require(without_program(found.profile) == self.registration["profile"] == intent["profile"], "execution-port-profile-mismatch")
        return found

    async def preflight(self, intent):
        require(self.domain.available,"execution-port-capability-unverified")
        self.check_secrets(intent)
        if self.purpose != "review":
            return await self.implementer_preflight(intent)
        r, m = self.registration, self.mapping
        discovered = await self.discovery(intent)
        profile = discovered.profile
        self.schemas.validate("ExecutionProfile", profile)
        self.schemas.validate("ExecutionBinding", intent["executionBinding"])
        self.schemas.validate("ReviewerApplicability", r["applicability"])
        require(r["mode"] == self.mode and intent["portId"] == r["id"], "execution-port-unregistered")
        require(profile["purpose"] == "review", "execution-port-purpose-mismatch")
        require(profile == r["profile"] == intent["profile"], "execution-port-profile-mismatch")
        require(r["applicability"]["executionPort"] == self.mode and r["applicability"]["profileDigest"] == profile["digest"], "execution-port-profile-mismatch")
        require(r["approval_policy"] == profile["nativeApprovalPolicy"] and r["applicability"]["trustModel"] == profile["trustModel"], "execution-port-profile-mismatch")
        binding = intent["executionBinding"]
        require(binding["profileDigest"] == profile["digest"] and binding["model"] == r["model_ref"] and binding["configurationRevision"] == r["applicability"]["configurationRevision"], "execution-port-binding-mismatch")
        require(m["id"] == r["mapping_id"] and m["provider"] == r["provider"] and m["model_ref"] == binding["model"] and m["model_vendor"] == binding["modelVendor"] and m["route_vendor"] == binding["routeVendor"], "execution-port-binding-mismatch")
        require(intent["credentialRevision"] == r["applicability"]["credentialRevision"] and intent["transport"] == r["transport"] and intent["effort"] == r["effort"], "execution-port-binding-mismatch")
        require(0 < intent["budget"]["maxToolCalls"] <= profile["maxToolCalls"] and 0 < intent["budget"]["maxRunSeconds"] <= profile["maxRunSeconds"], "execution-port-profile-mismatch")
        for field, limit in (("caller", 256), ("invocation_authorization", 4096)):
            value = intent.get(field)
            require(isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= limit, "request-invalid")
        auth = await self.authority(intent)
        if r["capability"]["status"] != "REVIEW_ENABLED":
            require(auth.owner_formal and intent.get("formal_review_authorized_by_owner") is True, "execution-port-capability-unverified")
        p = dict(scopeRef=intent["scopeRef"], profileId=profile["id"], profileDigest=profile["digest"], connectionRef=intent["connectionRef"], configurationRevision=binding["configurationRevision"], executionBinding=binding, constraints=intent["constraints"])
        result = await self.host.call("host.execution.preflight", p)
        require(result["status"] == "supported" and all(c["passed"] for c in result["checks"]), "execution-port-profile-mismatch")
        return auth

    async def implementer_preflight(self, intent):
        """coding-implementer purpose: the registration is the product-side one resolved by (portId, purpose).

        The review-channel Registry, its ReviewerApplicability and its capability gate are review
        semantics and are not applied here; bridge.py is unchanged (Owner ruling OD-399).
        """
        from domain.implement_verify import registration as product_registration
        current = product_registration.resolve(self.domain.read(), intent["portId"], self.purpose)
        # Design row host.py ⑦: re-resolve on every preflight; a withdrawn or changed registration stops release.
        require(current is not None and current == self.registration and current["mode"] == self.mode and intent["portId"] == current["id"], "execution-port-unregistered")
        discovered = await self.discovery(intent)
        profile = discovered.profile
        self.schemas.validate("ExecutionProfile", profile)
        self.schemas.validate("ExecutionBinding", intent["executionBinding"])
        r = self.registration
        require(profile["purpose"] == self.purpose, "execution-port-purpose-mismatch")
        require(r["approval_policy"] == profile["nativeApprovalPolicy"], "execution-port-profile-mismatch")
        binding = intent["executionBinding"]
        require(binding["profileDigest"] == profile["digest"] and binding["agent"] == r["agent"] and binding["model"] == r["model_ref"] and binding["configurationRevision"] == r["configurationRevision"], "execution-port-binding-mismatch")
        require(intent["credentialRevision"] == r["credentialRevision"] and intent["transport"] == r["transport"] and intent["effort"] == r["effort"], "execution-port-binding-mismatch")
        budget = intent["budget"]
        require(isinstance(budget, dict) and set(budget) == set(r["budget"]) and all(type(budget[k]) is int and 0 < budget[k] <= r["budget"][k] for k in r["budget"]) and budget["maxToolCalls"] <= profile["maxToolCalls"] and budget["maxRunSeconds"] <= profile["maxRunSeconds"], "execution-port-profile-mismatch")
        for field, limit in (("caller", 256), ("invocation_authorization", 4096)):
            value = intent.get(field)
            require(isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= limit, "request-invalid")
        auth = await self.authority(intent)
        p = dict(scopeRef=intent["scopeRef"], profileId=profile["id"], profileDigest=profile["digest"], connectionRef=intent["connectionRef"], configurationRevision=binding["configurationRevision"], executionBinding=binding, constraints=intent["constraints"])
        result = await self.host.call("host.execution.preflight", p)
        require(result["status"] == "supported" and all(c["passed"] for c in result["checks"]), "execution-port-profile-mismatch")
        self.program_identity = copy.deepcopy(profile["programIdentity"])
        return auth

    def reserve(self, intent, seal_dir, instruction, manifest):
        """Called only after preflight. The exact intent is reauthorized on execute."""
        self.check_secrets(intent)
        materials = sealed_materials(seal_dir, manifest, instruction, intent["profile"])
        for _, _, raw in materials:self.check_secrets(None,raw)
        request_id = intent["executionRequestId"]
        bound = dict(intent=intent, manifest=manifest, instruction_sha256=sha(materials[0][2]), materials=[(role, n, sha(b)) for role,n,b in materials])
        require(intent.get("inputManifestSha256",manifest["manifest_sha256"])==manifest["manifest_sha256"])
        require(intent.get("instructionSha256",sha(materials[0][2]))==sha(materials[0][2]))
        key = identity(bound)
        def commit(s):
            records = s.setdefault("executionReservations", {})
            old = records.get(request_id)
            if old is not None:
                require(old["identity"] == key, "execution-port-binding-mismatch")
                return copy.deepcopy(old)
            # Domain ordinary transaction enforces the shared writer/barrier.
            sources = export_resources(s, intent, materials)
            token = sha(request_id.encode())
            capture = dict(scopeRef=intent["scopeRef"], domainOperationId=intent["domainOperationId"], sources=sources, grantRefs=intent["grantRefs"], operationId="capture:"+token, idempotencyKey="capture:"+token)
            capture["requestDigest"] = digest("host.context.capture", capture)
            rec = dict(identity=key, request_id=request_id, intent=copy.deepcopy(intent), capture=capture, start=None, execution_ref=None, phase="reserved", observations=[], instruction_sha256=sha(materials[0][2]), cancel_requested=False, start_dispatched=False, manifest_sha256=manifest["manifest_sha256"], reservation_ref="reservation:"+token, protected=True, result=None)
            records[request_id] = rec
            refs=s.setdefault("protectedReferences", [])
            if rec["reservation_ref"] not in refs: refs.append(rec["reservation_ref"])
            return copy.deepcopy(rec)
        return self.transact(self.host.context["controlGeneration"], commit)

    def current(self, reservation):
        record = self.domain.read().get("executionReservations", {}).get(reservation["request_id"])
        require(record is not None and record["identity"] == reservation["identity"], "execution-port-binding-mismatch")
        return copy.deepcopy(record)

    def update(self, reservation, change):
        def commit(s):
            record = s["executionReservations"][reservation["request_id"]]
            require(record["identity"] == reservation["identity"], "execution-port-binding-mismatch")
            change(record)
            return copy.deepcopy(record)
        return self.transact(self.host.context["controlGeneration"], commit)

    async def execute(self, reservation, seal_dir=None, instruction=None):
        rec = self.current(reservation)
        await self.preflight(rec["intent"])
        if self.purpose != "review" and rec.get("program_identity") is None:
            # Recorded once per physical execution; never a registration precondition (OD-399).
            program = self.program_identity
            rec = self.update(rec, lambda r: r.setdefault("program_identity", program))
        if rec.get("cancel_requested"):
            return await self.cancel(rec)
        if rec["phase"] != "reserved":
            return await self.query(rec)
        claimed = False
        def claim(r):
            nonlocal claimed
            if r["phase"] == "reserved" and not r.get("cancel_requested"): r["phase"]="capturing"; claimed=True
        rec = self.update(rec, claim)
        if not claimed: return await self.query(rec)
        try:
            result = await self.exchange(rec,"host.context.capture", rec["capture"])
        except (Fault, TimeoutError, ConnectionError):
            # Persisted capturing phase forbids re-execution after an unknown response.
            return await self.query(rec)
        return await self._captured(rec, result, allow_start=True)

    async def _captured(self, rec, result, allow_start=False):
        rec=self.current(rec)
        if rec.get("cancel_requested"):
            raise ExecutionError("cancelled_by_host", "cancelled_by_host")
        p=rec["capture"]
        for k in ("scopeRef", "domainOperationId", "operationId", "requestDigest"):
            require(result[k]==p[k])
        if result["status"] != "succeeded":
            require(not result["snapshots"])
            return dict(state="unknown", reservation=rec)
        require(len(result["snapshots"]) == len(p["sources"]))
        snapshots=[]
        for source, pair in zip(p["sources"], result["snapshots"]):
            snapshot=pair["snapshot"]
            require(pair["source"]==source and snapshot["authority"]=="host")
            for k in ("scopeRef", "bytes", "digest", "mediaType", "objectRef", "revision"):
                require(snapshot[k]==source[k])
            snapshots.append(snapshot)
        i=rec["intent"]; binding=i["executionBinding"]
        start=dict(operationId="start:"+sha(rec["request_id"].encode()), idempotencyKey="start:"+sha(rec["request_id"].encode()), scopeRef=i["scopeRef"], profileId=i["profile"]["id"], profileDigest=i["profile"]["digest"], domainOperationId=i["domainOperationId"], domainNodeRef=i["domainNodeRef"], roleIntent=ROLE_INTENT[self.purpose], resourceHandle=i["resourceHandle"], targetBinding=i.get("targetBinding"), connectionRef=i["connectionRef"], configurationRevision=binding["configurationRevision"], model=binding["model"], executionBinding=binding, constraints=i["constraints"], contextRefs=snapshots, grantRefs=i["grantRefs"], decisionRef=i.get("decisionRef"), budget=i["budget"])
        start["requestDigest"]=digest("host.execution.start", start)
        claimed=False
        def save(r):
            nonlocal claimed
            require(r["start"] is None or r["start"]==start)
            if r["phase"]=="capturing" and not r.get("cancel_requested"):
                r["start"]=start; r["phase"]="starting"; claimed=True
        rec=self.update(rec,save)
        # Recovery of a succeeded capture may start once: start was never attempted
        # until this atomic transition. A persisted starting record is query-only.
        if not claimed: return await self.query(rec)
        auth=await self.preflight(i)
        dispatched=False
        def dispatch(r):
            nonlocal dispatched
            if not r.get("cancel_requested") and not r.get("start_dispatched"):
                r["start_dispatched"]=True; dispatched=True
        def claim_budget(state):
            record=state["executionReservations"][rec["request_id"]]
            require(record["identity"]==rec["identity"])
            if not record.get("cancel_requested") and not record.get("start_dispatched"):
                key=identity([i["scopeRef"],auth.authorization_ref])
                budget=state.setdefault("executionCallBudgets",{}).setdefault(key,dict(limit=auth.max_calls,requests=[]))
                require(budget["limit"]==auth.max_calls and len(budget["requests"])<auth.max_calls,"execution-port-capability-unverified")
                budget["requests"].append(record["request_id"])
                record["authorization_ref"]=auth.authorization_ref
                dispatch(record)
            return copy.deepcopy(record)
        rec=self.transact(self.host.context["controlGeneration"],claim_budget)
        if not dispatched: return await self.query(rec)
        try: op=await self.exchange(rec,"host.execution.start",start)
        except (Fault,TimeoutError,ConnectionError): return dict(state="unknown",reservation=rec)
        return await self._operation(rec,op)

    async def _operation(self, rec, op):
        start=rec["start"]
        for k in ("scopeRef", "operationId", "requestDigest"):
            require(op[k]==start[k])
        ref=op["executionRef"]
        require(rec["execution_ref"] is None or ref==rec["execution_ref"])
        if ref is None: return dict(state="unknown",reservation=rec)
        def bind(r):
            require(r["execution_ref"] is None or r["execution_ref"] == ref)
            r.update(execution_ref=ref, phase="observing")
        rec=self.update(rec,bind)
        if rec.get("cancel_requested"): return await self.cancel(rec)
        return await self.query(rec)

    async def query(self, reservation):
        rec=self.current(reservation); i=rec["intent"]
        # Policy checks remain required when consuming results, not only at launch.
        await self.authority(i)
        discovered=await self.discovery(i)
        if rec.get("cancel_requested") and not rec.get("start_dispatched"):
            raise ExecutionError("cancelled_by_host", "cancelled_by_host")
        if rec["result"] is not None:
            answer=base64.b64decode(rec["result"],validate=True)
            self.check_secrets(answer.decode(),base64.b64decode(rec["result_envelope"],validate=True))
            return dict(state="completed",answer=answer,reservation=rec)
        try:
            if rec["phase"]=="capturing":
                result=await self.exchange(rec,"host.context.get",dict(scopeRef=i["scopeRef"],operationId=rec["capture"]["operationId"]))
                return await self._captured(rec,result)
            if rec["start"] is None: return dict(state="unknown",reservation=rec)
            if rec["execution_ref"] is None:
                op=await self.exchange(rec,"host.operation.get",dict(scopeRef=i["scopeRef"],operationId=rec["start"]["operationId"]))
                return await self._operation(rec,op)
            physical=await self.exchange(rec,"host.execution.get",dict(scopeRef=i["scopeRef"],executionRef=rec["execution_ref"]))
        except (Fault,TimeoutError,ConnectionError): return dict(state="unknown",reservation=rec)
        physical={k:v for k,v in physical.items() if k!="context"}
        self.schemas.validate("PhysicalExecution",physical)
        for k in ("scopeRef","connectionRef","model","configurationRevision"):
            require(physical[k]==rec["start"][k])
        require(physical["executionRef"]==rec["execution_ref"] and physical["requestIdentity"]=={k:rec["start"][k] for k in ("operationId","requestDigest","profileDigest")})
        observation=dict(observed_at=datetime.now(timezone.utc).isoformat(),physical_execution=physical,evidence_ref=physical["resultRef"],sha256=sha(json.dumps(physical,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()))
        def observe(r):
            if r["observations"] and r["observations"][-1]["physical_execution"] == physical:
                return
            require(len(r["observations"])<256,"execution-port-observation-incomplete")
            r["observations"].append(observation)
        rec=self.update(rec,observe)
        if physical["stopReason"]=="cancelled": raise ExecutionError("cancelled_by_host","cancelled_by_host")
        if physical["state"]=="failed" or physical["stopReason"] is not None: raise ExecutionError("execution_port_failure")
        if rec.get("cancel_requested"):
            return dict(state="unknown",reservation=rec)
        if physical["state"]!="completed": return dict(state=physical["state"],reservation=rec)
        exit=physical["exit"]
        require(exit is not None and exit["code"]==0 and exit["signal"] is None,"execution_port_failure")
        if self.purpose != "review" and i["profile"]["nativeApprovalPolicy"] == "auto-deny":
            # auto-deny admits no native approval request; any accepted decision is outside the policy.
            require(not physical["approvalDecisionRefs"], "execution-port-approval-out-of-policy")
        actual=physical["actualBinding"]
        require(actual is not None and actual["source"] in self.mapping["allowed_sources"] and actual["model"] in self.mapping["actual_models"] and bool(actual["observedModels"]) and all(m in self.mapping["actual_models"] for m in actual["observedModels"]),"execution-port-identity-unverified")
        evidence=physical["resultRef"]
        require(evidence is not None and evidence["authority"]=="host" and evidence["scopeRef"]==i["scopeRef"] and evidence["resourceHandle"]==i["resourceHandle"])
        raw=await self.read_result(rec,evidence)
        def pairs(items):
            require(len(dict(items))==len(items));return dict(items)
        doc=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,parse_constant=lambda x:require(False))
        for k in ("operationId","profileId","profileDigest"):
            require(doc[k]==rec["start"][k])
        require(doc["executionRef"]==rec["execution_ref"] and doc["actualBinding"]==actual and doc["outcome"]=="completed")
        e=doc["evidence"]; require(isinstance(e["answer"],str));answer=e["answer"].encode()
        require(len(answer)==e["answerBytes"] and sha(answer)==e["answerDigest"])
        self.verify_readback(e,i,discovered,actual)
        self.check_secrets(doc,raw)
        rec=self.update(rec,lambda r:r.update(result=base64.b64encode(answer).decode(),result_envelope=base64.b64encode(raw).decode(),phase="completed"))
        # Result completion is never domain settlement or proof all processes exited.
        return dict(state="completed",answer=answer,reservation=rec)

    def verify_readback(self,e,intent,discovered,actual):
        if self.purpose != "review":
            # Implementer readback is the protocol's own model report; it must equal the actual binding.
            require(e.get('readback')==dict(source=actual['source'],model=actual['model']),'execution-port-identity-unverified')
            return
        if intent['executionBinding']['agent'] in ('agent:codex','codex'):
            require(e.get('readback',{}).get('modelProvider')==discovered.protocol_provider,'execution-port-binding-mismatch')

    async def read_result(self,rec,evidence):
        intent=rec["intent"]
        require(evidence["bytes"]<=intent["budget"].get("maxOutputBytes",16777216))
        data=bytearray()
        while len(data)<evidence["bytes"]:
            n=len(data)
            r=await self.exchange(rec,"host.resource.read",dict(scopeRef=intent["scopeRef"],evidence=evidence,grantRefs=intent["grantRefs"],offset=n,length=min(65536,evidence["bytes"]-n)))
            chunk=base64.b64decode(r["dataBase64"],validate=True)
            require(r["offset"]==n and bool(chunk) and len(data)+len(chunk)<=evidence["bytes"])
            data.extend(chunk);require(r["eof"]==(len(data)==evidence["bytes"]))
        raw=bytes(data);require(len(raw)==evidence["bytes"] and sha(raw)==evidence["digest"])
        return raw

    async def checkpoint_observations(self,reservation):
        """Explicit recovery checkpoint; never starts or releases physical execution."""
        rec=self.current(reservation)
        await self.authority(rec['intent']);await self.discovery(rec['intent'])
        self.check_secrets(rec['observations'])
        def checkpoint(state):
            record=state['executionReservations'][rec['request_id']]
            require(record['identity']==rec['identity'],'execution-port-binding-mismatch')
            require(record['result'] is None and len(record['observations'])==256,'execution-port-observation-incomplete')
            self.check_secrets(record['observations'])
            raw=json.dumps(record['observations'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            token=sha(raw);ref=dict(authority='runtime',resourceHandle=rec['intent']['resourceHandle'],scopeRef=rec['intent']['scopeRef'],objectRef='execution-observations:'+sha(rec['request_id'].encode()),revision=str(len(record.get('observation_history',[]))+1),mediaType='application/json',bytes=len(raw),digest=token)
            value=dict(evidence=ref,dataBase64=base64.b64encode(raw).decode())
            key=evidence_key(ref);old=state.setdefault('resources',{}).get(key);require(old is None or old==value)
            state['resources'][key]=value
            state.setdefault('protectedReferences',[]).append(key)
            record.setdefault('observation_history',[]).append(ref)
            record['observations']=[]
            return copy.deepcopy(record)
        return self.transact(self.host.context['controlGeneration'],checkpoint)

    def historical_observations(self,reservation):
        rec=self.current(reservation);state=self.domain.read();result=[]
        for ref in rec.get('observation_history',[]):
            value=state['resources'][evidence_key(ref)];require(value['evidence']==ref)
            raw=base64.b64decode(value['dataBase64'],validate=True)
            require(len(raw)==ref['bytes'] and sha(raw)==ref['digest'])
            observations=json.loads(raw);self.check_secrets(observations,raw)
            result.append(dict(evidence=ref,observations=observations))
        return result

    async def cancel(self,reservation):
        rec=self.current(reservation); i=rec["intent"]
        await self.authority(i)
        # Persist before any query. Capture recovery must never launch after cancel.
        rec=self.update(rec,lambda r:r.update(cancel_requested=True))
        if not rec.get("start_dispatched"):
            raise ExecutionError("cancelled_by_host", "cancelled_by_host")
        if rec["execution_ref"] is None:
            try:
                op=await self.exchange(rec,"host.operation.get",dict(scopeRef=i["scopeRef"],operationId=rec["start"]["operationId"]))
            except (Fault,TimeoutError,ConnectionError):
                return dict(state="unknown", reservation=rec)
            return await self._operation(rec,op)
        p=dict(scopeRef=i["scopeRef"],executionRef=rec["execution_ref"],operationId="cancel:"+sha(rec["request_id"].encode()),idempotencyKey="cancel:"+sha(rec["request_id"].encode()))
        p["requestDigest"]=digest("host.execution.cancel",p)
        claimed=False
        def claim(r):
            nonlocal claimed
            require(r["execution_ref"]==p["executionRef"])
            require(r.get("cancel") is None or r["cancel"]==p)
            if r.get("cancel") is None: r["cancel"]=p; claimed=True
        rec=self.update(rec,claim)
        # Unknown cancel response is not resent. Observe the original execution.
        if claimed:
            try: await self.exchange(rec,"host.execution.cancel",p)
            except (Fault,TimeoutError,ConnectionError): return dict(state="unknown",reservation=rec)
        return await self.query(rec)
