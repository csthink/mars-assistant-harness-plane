"""New draft.5 Host-call examples, synthetic facts only."""
import base64
import hashlib
import copy
import rfc8785

def samples(context,scope,evidence):
    operation=dict(operationId="hostop:one",scopeRef=scope,requestDigest="d"*64,status="accepted",
        resultRef=None,executionRef=None,reason="Synthetic accepted",resultCode=None,revision="1")
    profile="a"*64
    binding=dict(profileDigest=profile,agent="synthetic",model="synthetic",modelVendor="synthetic",routeVendor=None,
                 credentialRef="credential:synthetic",configurationRevision="1")
    mutation=dict(operationId="hostop:one",idempotencyKey="hostkey:one",requestDigest="d"*64)
    capture=dict(**mutation,scopeRef=scope,domainOperationId="op:parent",sources=[evidence],grantRefs=[])
    receipt=dict(operationId="hostop:one",scopeRef=scope,domainOperationId="op:parent",requestDigest="d"*64,
                 status="succeeded",snapshots=[dict(source=evidence,snapshot=dict(evidence,authority="host",resourceHandle="host:evidence"))],reason="")
    start=dict(**mutation,scopeRef=scope,profileId="profile:synthetic",profileDigest=profile,domainOperationId="op:parent",
        domainNodeRef="node:one",roleIntent="synthetic",resourceHandle="resource:one",targetBinding=None,connectionRef="provider:synthetic",
        configurationRevision="1",model="synthetic",executionBinding=binding,constraints=[],contextRefs=[],grantRefs=[],decisionRef=None,
        budget=dict(maxToolCalls=1,maxRunSeconds=1))
    physical=dict(executionRef="execution:one",scopeRef=scope,state="unknown",connectionRef="provider:synthetic",
        configurationRevision="1",model="synthetic",requestIdentity=dict(operationId="hostop:one",requestDigest="d"*64,profileDigest=profile),
        supervisor=None,approvalDecisionRefs=[],actualBinding=None,stopReason=None,accounting=None,exit=None,
        observationCompleteness="unknown",resultRef=None,reason="Synthetic broker, no physical execution")
    cases = {
      "host.grants.get":({"grantRefs":[]},{"grants":[]}),
      "host.decision.get":(dict(scopeRef=scope,decisionRef="decision:one"),dict(decisionRef="decision:one",scopeRef=scope,
         domainOperationId="op:parent",method="runtime.action.invoke",requestDigest="d"*64,actionId="action:one",objectRef="object:one",
         candidateRef=None,expectedRevision="1",evidence=[],actorRef="human:synthetic",source="host-trusted-ui",recordedAt="2026-09-21T00:00:00Z",status="valid")),
      "host.context.capture":(capture,receipt),
      "host.context.get":(dict(scopeRef=scope,operationId="hostop:one"),receipt),
      "host.resource.read":(dict(scopeRef=scope,evidence=dict(evidence,authority="host"),grantRefs=[],offset=0,length=4),
         dict(resourceHandle=evidence["resourceHandle"],revision="1",offset=0,dataBase64=base64.b64encode(b"Synt").decode(),eof=False,digest=evidence["digest"])),
      "host.execution.preflight":(dict(scopeRef=scope,profileId="profile:synthetic",profileDigest=profile,connectionRef="provider:synthetic",
         configurationRevision="1",executionBinding=binding,constraints=[]),dict(status="unsupported",profileDigest=profile,checks=[],reason="Synthetic transport only")),
      "host.execution.start":(start,operation),
      "host.operation.get":(dict(scopeRef=scope,operationId="hostop:one"),operation),
      "host.execution.get":(dict(scopeRef=scope,executionRef="execution:one"),physical),
      "host.execution.cancel":(dict(**mutation,scopeRef=scope,executionRef="execution:one"),dict(operation,executionRef="execution:one"))
    }

    cases = {key: copy.deepcopy(value) for key, value in cases.items()}
    for method, (params, result) in cases.items():
        if "requestDigest" in params:
            params["requestDigest"] = hashlib.sha256(rfc8785.dumps({"method": method, **{k:v for k,v in params.items() if k != "requestDigest"}})).hexdigest()
            result["requestDigest"] = params["requestDigest"]
    return cases
