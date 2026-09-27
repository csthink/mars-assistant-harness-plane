"""Fixture for the Runtime path of Workflow progression: synthetic product line with one accepted Task."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance import projection as acceptance_projection
from domain.acceptance.accept import accept_task
from domain.core import HarnessDomain
from domain.workflow import projection
from product_line import create_product_line

VERSION = "0.1.0-draft.5"
CONTRACT_DIGEST = "9d6e6af19a39cc52d0b86f7ce610b44d4b21517feebecf5d88df05f73b83a352"
LIMITS = dict(frameBytes=1048576, depth=32, members=1000, inFlight=32,
              bufferBytes=4194304, eventWindow=128, pageObjects=100, textCharacters=65536)


def create(directory, *, task_id="feature-t0", accept=True, **product_line):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    repo, head = create_product_line(directory / "repo", **product_line)
    worktrees = directory / "worktrees"
    domain = HarnessDomain(repo, entry="cli")
    generation = domain.bind_entry()
    if accept:
        accept_task(domain.store, dict(requestId="fixture-1", repository=str(repo), taskType="feature",
                                       taskId=task_id, baseRef="main", worktreeRoot=str(worktrees),
                                       authorityRef="owner:fixture"))
    scope = "scope:" + hashlib.sha256(b"binding:one").hexdigest()[:24]
    capabilities = [acceptance_projection.capability(), projection.capability()]
    auth = dict(authorizationRef="launch:one", bundleDigest="b" * 64, permissionProfileDigest="c" * 64,
                expiresAt="2099-01-01T00:00:00Z")
    config = dict(installationId="installation:test", instanceId="instance:test", incarnationId="incarnation:one",
                  connectionId="connection:one", bundleDigest="b" * 64, dataFormat="hp-domain-v1",
                  launchAuthorization=auth, executionProfileRequirements=[], repository=str(repo))
    initialize = {k: v for k, v in config.items() if k not in ("dataFormat", "executionProfileRequirements", "repository")}
    initialize.update(protocols=[dict(version=VERSION, contractDigest=CONTRACT_DIGEST)], capabilities=capabilities,
                      executionProfiles=[], limits=LIMITS)
    state = domain.store.read()
    rows = projection.instance_rows(state, domain.topology)
    cap = projection.capability()
    template = dict(scopeRef=scope, binding=dict(bindingRef="binding:one", resourceHandle="resource:one",
                                                 expiresAt="2099-01-01T00:00:00Z"),
                    action=projection.decide_action(scope, rows, cap),
                    closeAction=projection.close_action(scope, rows, cap),
                    acceptAction=acceptance_projection.accept_action(scope, acceptance_projection.capability()),
                    initialize=initialize, repository=str(repo), head=head, worktreeRoot=str(worktrees),
                    capability=cap, capabilities=capabilities, taskId=task_id,
                    controlGeneration=generation)
    template["humanAction"] = template["action"]
    for name, data in [("launch.json", config), ("host-template.json", template)]:
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return template
