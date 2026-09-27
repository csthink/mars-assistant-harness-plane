"""Create only an explicitly marked, new synthetic repository and launch data."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

VERSION = "0.1.0-draft.5"
DIGEST = "9d6e6af19a39cc52d0b86f7ce610b44d4b21517feebecf5d88df05f73b83a352"
LIMITS = dict(frameBytes=1048576, depth=32, members=1000, inFlight=32,
              bufferBytes=4194304, eventWindow=128, pageObjects=100, textCharacters=65536)

def create(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    repo = directory / "domain"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".synthetic-hp-domain").write_text("Synthetic feature-t16 test data only\n")
    scope = "scope:" + hashlib.sha256(b"binding:one").hexdigest()[:24]
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": "urn:hp:test:payload",
              "type": "object", "properties": {"value": {"type": "string", "maxLength": 100}},
              "required": ["value"], "additionalProperties": False}
    payload_digest = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    cap = dict(id="hp.synthetic", version="1", schemaDigest=payload_digest, required=False)
    content = b"Synthetic immutable evidence\n"
    evidence = dict(authority="runtime", resourceHandle="evidence:one", scopeRef=scope,
                    objectRef="object:one", revision="1", mediaType="text/plain", bytes=len(content),
                    digest=hashlib.sha256(content).hexdigest())
    obj = dict(scopeRef=scope, objectRef="object:one", revision="1", title="Synthetic object",
               stateLabel="synthetic", capability=cap, view=dict(kind="list", rows=[]), evidence=[evidence])
    action = dict(scopeRef=scope, actionId="action:one", objectRef="object:one", capability=cap, label="Synthetic accept",
                  expectedRevision="1", candidateRef="candidate:one", payloadSchemaDigest=payload_digest,
                  enabled=True, disabledReason="", disabledCode=None, requiresHumanDecision=False)
    human = dict(action, actionId="action:human", requiresHumanDecision=True)
    disabled = dict(action, actionId="action:disabled", enabled=False, disabledReason="Synthetic policy", disabledCode="SYNTHETIC_DISABLED")
    pending = dict(scopeRef=scope, itemRef="pending:one", revision="1", objectRef="object:one", capability=cap,
        title="Synthetic pending", typeId="synthetic", typeLabel="Synthetic", status="pending",
        pendingSince="2026-09-21T00:00:00Z", updatedAt="2026-09-21T00:00:00Z", processedAt=None,
        blocking=True, actionIds=["action:human"], evidence=[evidence])
    seed = dict(capabilities=[cap], schemas={schema["$id"]: schema}, state=dict(generation="0", revision="0",
        scopes={scope: dict(resourceHandle="resource:one", objects=[obj], actions=[action,human,disabled], pendingItems=[pending],
                           events=[], streamId="stream:one", epoch="1", seq="0", logFloor="0")},
        bindings={}, operations={}, keys={}, indexComplete=True, acceptedCount=0, quiesced=False, shutdown=False,
        barrier=None, upgrades={}, protectedReferences=[], dataFormat="synthetic-v1",
        payloadSchemas={payload_digest: schema["$id"]}, decisionEvidence={"action:human": [evidence]},
        resources={"evidence:one": dict(evidence=evidence, dataBase64=base64.b64encode(content).decode())}))
    auth = dict(authorizationRef="launch:one", bundleDigest="b"*64, permissionProfileDigest="c"*64, expiresAt="2099-01-01T00:00:00Z")
    config = dict(installationId="installation:test", instanceId="instance:test", incarnationId="incarnation:one",
        connectionId="connection:one", bundleDigest="b"*64, dataFormat="synthetic-v1", launchAuthorization=auth,
        executionProfileRequirements=[])
    initialize = {k: v for k, v in config.items() if k not in ("dataFormat", "executionProfileRequirements")}
    initialize.update(protocols=[dict(version=VERSION,contractDigest=DIGEST)],capabilities=[cap],executionProfiles=[],limits=LIMITS)
    template = dict(scopeRef=scope, binding=dict(bindingRef="binding:one", resourceHandle="resource:one", expiresAt="2099-01-01T00:00:00Z"),
                    evidence=evidence, action=action, humanAction=human, initialize=initialize)
    for name, data in [("seed.json",seed),("launch.json",config),("host-template.json",template)]:
        (directory/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    return template

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    args=parser.parse_args()
    create(args.directory)
