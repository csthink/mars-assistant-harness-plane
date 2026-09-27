"""Fixture for the Runtime path of task acceptance: synthetic product line + launch data + Host template."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance import projection
from domain.acceptance.schema import DIGEST
from product_line import create_product_line

VERSION = "0.1.0-draft.5"
CONTRACT_DIGEST = "9d6e6af19a39cc52d0b86f7ce610b44d4b21517feebecf5d88df05f73b83a352"
LIMITS = dict(frameBytes=1048576, depth=32, members=1000, inFlight=32,
              bufferBytes=4194304, eventWindow=128, pageObjects=100, textCharacters=65536)

def create(directory, **product_line):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    repo, head = create_product_line(directory / "repo", **product_line)
    scope = "scope:" + hashlib.sha256(b"binding:one").hexdigest()[:24]
    cap = projection.capability()
    auth = dict(authorizationRef="launch:one", bundleDigest="b"*64, permissionProfileDigest="c"*64, expiresAt="2099-01-01T00:00:00Z")
    config = dict(installationId="installation:test", instanceId="instance:test", incarnationId="incarnation:one",
                  connectionId="connection:one", bundleDigest="b"*64, dataFormat="hp-domain-v1", launchAuthorization=auth,
                  executionProfileRequirements=[])
    initialize = {k: v for k, v in config.items() if k not in ("dataFormat", "executionProfileRequirements")}
    initialize.update(protocols=[dict(version=VERSION, contractDigest=CONTRACT_DIGEST)], capabilities=[cap], executionProfiles=[], limits=LIMITS)
    action = projection.accept_action(scope, cap)
    template = dict(scopeRef=scope, binding=dict(bindingRef="binding:one", resourceHandle="resource:one", expiresAt="2099-01-01T00:00:00Z"),
                    action=action, humanAction=action, initialize=initialize, repository=str(repo), head=head,
                    worktreeRoot=str(directory / "worktrees"), capability=cap, schemaDigest=DIGEST)
    for name, data in [("launch.json", config), ("host-template.json", template)]:
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return template
