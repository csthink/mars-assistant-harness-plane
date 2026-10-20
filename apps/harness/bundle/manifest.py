"""Bundle descriptors: manifest.json (frozen Contract Manifest), launch.json (the trusted local launch
configuration bound by permissionProfileDigest), capabilities/<id>.json and bundle.json (hp's own
self-description and self-check list).

Values satisfy the frozen Contract 0.1.0 schema and the stricter receiver formats at once (feature-t18
design, field table). No value names an Agent or platform program version: program identity is
rediscovered at every execution and never an admission precondition.

executionProfileRequirements names, per capability, the execution profile its Agent executions need
(Contract 0.1.0 ProfileRequirement): a Host that does not offer that exact id, version and digest
loses the capability at negotiation, and one that does gets the profile selected, which is what lets a
client keep a role's model and effort. The Reviewer profile is the one embedded review port of the
Registry at the source commit; the Implementer profile is the J-04 tuple of review channel design §7.5
(its registration is product-line configuration, not an hp file).
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
# Contract 0.1.0 identifier and digest formats of an ExecutionProfileRef.
PROFILE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}$")
PROFILE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
REGISTRY = "mechanisms/review-channel/review_channel_registry.json"
J04_IMPLEMENTER_PROFILE = dict(id="coding-implementer/claude-print-restricted", version="1",
                               digest="2c9583da0f4101cc04e86251d85ba15c3a2bc9d6fda024f8d79081566744f16c")
REVIEWER_CAPABILITIES = ("harness.definition", "harness.validate-change")
IMPLEMENTER_CAPABILITIES = ("harness.implement-verify",)
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


def profile_ref(profile, source):
    ref = {key: profile.get(key) if isinstance(profile, dict) else None for key in ("id", "version", "digest")}
    if not (isinstance(ref["id"], str) and PROFILE_IDENTIFIER.fullmatch(ref["id"]) and isinstance(ref["version"], str)
            and PROFILE_IDENTIFIER.fullmatch(ref["version"]) and isinstance(ref["digest"], str) and PROFILE_DIGEST.fullmatch(ref["digest"])):
        raise BuildRefusal("execution-profile", "not a Contract execution profile reference: " + source)
    return ref


def reviewer_profile(registry_bytes):
    """The profile reference of the Registry's one embedded review port at the source commit."""
    try:
        registry = json.loads(registry_bytes)
    except ValueError as exc:
        raise BuildRefusal("registry", "the review channel Registry at the source commit is not JSON") from exc
    ports = registry.get("execution_ports") if isinstance(registry, dict) else None
    reviewers = [p for p in ports if isinstance(p, dict) and p.get("mode") == "embedded" and isinstance(p.get("profile"), dict)
                 and p["profile"].get("purpose") == "review"] if isinstance(ports, list) else []
    if len(reviewers) != 1:
        raise BuildRefusal("registry", "exactly one embedded review port must be registered, found %d" % len(reviewers))
    return profile_ref(reviewers[0]["profile"], "Registry embedded review port")


def profile_requirements(registry_bytes, capabilities):
    """ProfileRequirement list, ordered by capability id; every named capability must be one the bundle declares."""
    profiles = {**{c: reviewer_profile(registry_bytes) for c in REVIEWER_CAPABILITIES},
                **{c: profile_ref(J04_IMPLEMENTER_PROFILE, "J-04 Implementer") for c in IMPLEMENTER_CAPABILITIES}}
    declared = {c["id"] for c in capabilities}
    missing = sorted(set(profiles) - declared)
    if missing:
        raise BuildRefusal("capabilities", "profile requirement for a capability the bundle does not declare: " + ", ".join(missing))
    return [dict(capabilityId=capability, profile=profiles[capability]) for capability in sorted(profiles)]


def launch_bytes():
    return dumps(dict(schema=LAUNCH_SCHEMA, entrypoint=ENTRYPOINT, argv=ARGV, environmentAllowList=ENVIRONMENT,
                      dependencies=[], launcher="direct", trustModel="current-user"))


def manifest_bytes(runtime_id, publisher_id, version, capabilities, permission_profile_digest, requirements):
    return dumps(dict(manifestVersion=CONTRACT_VERSION, runtimeId=runtime_id, publisher=publisher_id, version=version,
                      entrypoint=ENTRYPOINT, argv=ARGV, platform=PLATFORM, minimumOs=MINIMUM_OS,
                      protocols=[dict(version=CONTRACT_VERSION, contractDigest=CONTRACT_DIGEST)],
                      capabilities=capabilities, permissionProfileDigest=permission_profile_digest,
                      executionProfileRequirements=requirements, dataFormat=DATA_FORMAT, dependencies=[]))


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
