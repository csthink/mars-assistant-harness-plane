"""Bundle descriptors: manifest.json (frozen Contract Manifest), launch.json (the trusted local launch
configuration bound by permissionProfileDigest), capabilities/<id>.json and bundle.json (hp's own
self-description and self-check list).

Values satisfy the frozen Contract 0.1.0 schema and the stricter receiver formats at once (feature-t18
design, field table). No value names an Agent or platform program version: program identity is
rediscovered at every execution and never an admission precondition.
"""
import json
import re

from bundle.layout import BuildRefusal, sha256

CONTRACT_VERSION = "0.1.0-draft.5"
CONTRACT_DIGEST = "9d6e6af19a39cc52d0b86f7ce610b44d4b21517feebecf5d88df05f73b83a352"
PLATFORM = "darwin-arm64"
MINIMUM_OS = "26.6.2"
DATA_FORMAT = "hp-domain-v1"
ENTRYPOINT = "python/bin/python3.12"
ARGV = ["-I", "-B", "-m", "hp", "serve-stdio", "--bundle", "--runtime-root", "${runtimeRoot}",
        "--instance-dir", "${instanceDir}", "--contract-digest", "${contractDigest}"]
ENVIRONMENT = ["HOME", "PATH", "PYTHONDONTWRITEBYTECODE"]
LAUNCH_SCHEMA = "csthink-runtime-launch/v1"
BUNDLE_SCHEMA = "hp-runtime-bundle/v1"
# Receiver identifier format (strictest of the frozen schema and the receiver implementation).
IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
RUNTIME_ID = re.compile(r"^runtime:[A-Za-z0-9._-]{1,120}$")
PUBLISHER_ID = re.compile(r"^publisher:[A-Za-z0-9._-]{1,120}$")
MISSING = ["complete installation, upgrade and uninstall (M-05 feature-t8)", "harness check / init / fix (feature-t12, feature-t13, feature-t14)",
           "mechanism payload and instance template skeleton (M-05)", "signed installer productisation, Developer ID and notarisation (feature-t8, gov-t13)",
           "maintenance entrypoint (release record maintenance is null)"]
CLI_GROUPS = ["task", "config", "workflow", "definition", "policy", "implement", "verify", "budget", "validate", "publish", "binding"]


def dumps(value):
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def version_of(commit):
    return "0.1.0-dev." + commit[:12]


def check_identity(runtime_id, publisher_id, version):
    if not RUNTIME_ID.fullmatch(runtime_id or ""):
        raise BuildRefusal("runtime-id", "must match runtime:[A-Za-z0-9._-]{1,120}")
    if not PUBLISHER_ID.fullmatch(publisher_id or ""):
        raise BuildRefusal("publisher-id", "must match publisher:[A-Za-z0-9._-]{1,120}")
    if not IDENTIFIER.fullmatch(version):
        raise BuildRefusal("version", "derived version is not a receiver identifier: " + version)


def capability_members(probe):
    """capabilities/<id>.json holds the RFC 8785 bytes of the schema whose digest the capability declares."""
    members, capabilities = [], []
    for item in probe["capabilities"]:
        data = bytes.fromhex(item["canonicalSchemaHex"])
        if sha256(data) != item["schemaDigest"]:
            raise BuildRefusal("capabilities", "schema bytes do not match schemaDigest for " + item["id"])
        if item["nonLocalRefs"]:
            raise BuildRefusal("capabilities", "capability schema uses a non-local $ref: " + item["id"])
        capabilities.append(dict(id=item["id"], version=item["version"], schemaDigest=item["schemaDigest"],
                                 required=item["required"]))
        members.append(("capabilities/%s.json" % item["id"], data, "0644"))
    return capabilities, members


def launch_bytes():
    return dumps(dict(schema=LAUNCH_SCHEMA, entrypoint=ENTRYPOINT, argv=ARGV, environmentAllowList=ENVIRONMENT,
                      dependencies=[], launcher="direct", trustModel="current-user"))


def manifest_bytes(runtime_id, publisher_id, version, capabilities, permission_profile_digest):
    return dumps(dict(manifestVersion=CONTRACT_VERSION, runtimeId=runtime_id, publisher=publisher_id, version=version,
                      entrypoint=ENTRYPOINT, argv=ARGV, platform=PLATFORM, minimumOs=MINIMUM_OS,
                      protocols=[dict(version=CONTRACT_VERSION, contractDigest=CONTRACT_DIGEST)],
                      capabilities=capabilities, permissionProfileDigest=permission_profile_digest,
                      executionProfileRequirements=[], dataFormat=DATA_FORMAT, dependencies=[]))


def bundle_bytes(*, runtime_id, version, commit, source_reference, inputs, capabilities, members):
    """members: the archive-ordered (path, data, mode) list without bundle.json, which is position 0."""
    return dumps(dict(
        schema=BUNDLE_SCHEMA, runtimeId=runtime_id, version=version, sourceCommit=commit, sourceReference=source_reference,
        statement="Runtime development bundle: it declares the delivered subset, its sources and the missing capabilities, "
                  "and it is not the complete public installation package (spec FR-05).",
        delivered=dict(capabilities=[c["id"] for c in capabilities], cliGroups=CLI_GROUPS,
                       entrypoints=["serve-stdio --bundle (Runtime Contract 0.1.0)", "-m hp <group> (standalone CLI)"]),
        missing=MISSING,
        buildInputs=dict(interpreter=dict(project=inputs["lock"]["interpreter"]["project"],
                                          releaseTag=inputs["lock"]["interpreter"]["releaseTag"],
                                          asset=inputs["lock"]["interpreter"]["asset"],
                                          sha256=inputs["interpreter"]["sha256"], bytes=inputs["interpreter"]["bytes"],
                                          pythonVersion=inputs["lock"]["interpreter"]["pythonVersion"]),
                         wheels=[dict(name=w["name"], version=w["version"], file=w["file"], sha256=w["sha256"])
                                 for w in inputs["wheels"]]),
        selfPosition=0,
        members=[dict(path=p, bytes=len(d), sha256=sha256(d), mode=m) for p, d, m in members]))
