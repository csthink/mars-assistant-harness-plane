"""Product-side Implementer execution port registration (Owner ruling OD-399).

The review purpose keeps its registration in the review-channel live Registry; the implementer purpose
is registered here, in the product-line domain configuration, and never in that Registry. Entries are
keyed by (portId, purpose) and identified by agent plus profile digest. programIdentity (launcher,
binary digest, version) is deliberately absent: it is rediscovered on every execution and recorded
with it, so an Agent upgrade never invalidates a registration (version-independence principle).

Written through `harness config set implementer-ports <JSON> --authority-ref <locator>` in one domain
transaction; every write appends a history entry and never rewrites an earlier one.
"""
import copy

from domain.workflow.progression import now
from domain.implement_verify.results import REGISTRATION_INVALID, ImplementVerifyRejection

KEY = "implementer-ports"
FIELD = "implementerPorts"
PURPOSE = "coding-implementer"
MODES = ("embedded", "standalone")
# J-06 r2 Appendix A r1 Implementer digest; withdrawn by OD-331 and never registrable.
WITHDRAWN_DIGESTS = ("5bb506537410fc36347f5b66c6cf4b6d3d4dbe1dc14b60580bf4cd25898e9062",)
PROFILE_FIELDS = ("id", "version", "digest", "trustModel", "purpose", "nativeApprovalPolicy", "configurationDigest",
                  "capabilities", "limitations", "operations", "maxContextBytes", "maxToolCalls", "maxRunSeconds")
ENTRY_FIELDS = ("id", "purpose", "mode", "agent", "profile", "approval_policy", "provider", "model_ref",
                "actual_models", "allowed_sources", "transport", "effort", "configurationRevision",
                "credentialRevision", "budget")
OPTIONAL_FIELDS = ("standalone",)
BUDGET_FIELDS = ("maxToolCalls", "maxRunSeconds", "maxOutputBytes", "cleanupSeconds")
# Runtime Contract 0.1.0 ExecutionStart.budget upper bounds.
CONTRACT_BUDGET_MAX = dict(maxToolCalls=20, maxRunSeconds=600, maxOutputBytes=16777216, cleanupSeconds=60)
SOURCES = ("protocol-init", "protocol-result", "adapter-report")
HEX = set("0123456789abcdef")


def _fail(message, **detail):
    raise ImplementVerifyRejection(REGISTRATION_INVALID, message, **detail)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def validate(entry):
    """Structural validation of one entry; returns a normalised copy or raises REGISTRATION_INVALID."""
    if not isinstance(entry, dict):
        _fail("an implementer port entry must be a JSON object")
    unknown = sorted(set(entry) - set(ENTRY_FIELDS) - set(OPTIONAL_FIELDS))
    missing = [f for f in ENTRY_FIELDS if f not in entry]
    if unknown or missing:
        _fail("implementer port entry fields do not match the closed set", unknown=unknown, missing=missing)
    if entry["purpose"] != PURPOSE:
        _fail("this registration carries only the coding-implementer purpose", purpose=entry["purpose"])
    if entry["mode"] not in MODES:
        _fail("mode must be embedded or standalone", mode=entry["mode"])
    for field in ("id", "agent", "provider", "model_ref", "transport", "effort", "approval_policy"):
        if not _text(entry[field]):
            _fail("field must be a non-empty string", field=field)
    for field in ("configurationRevision", "credentialRevision"):
        if not (isinstance(entry[field], str) and entry[field].isdigit()):
            _fail("revision fields are decimal strings", field=field)
    profile = entry["profile"]
    if not isinstance(profile, dict) or set(profile) != set(PROFILE_FIELDS):
        _fail("profile must carry exactly the registered profile fields and no programIdentity",
              expected=list(PROFILE_FIELDS), actual=sorted(profile) if isinstance(profile, dict) else None)
    if profile["purpose"] != PURPOSE or entry["approval_policy"] != profile["nativeApprovalPolicy"]:
        _fail("profile purpose and approval policy must match the entry",
              profilePurpose=profile["purpose"], approval=entry["approval_policy"])
    if not _digest(profile["digest"]) or not _digest(profile["configurationDigest"]):
        _fail("profile digests must be 64 lowercase hex characters")
    if profile["digest"] in WITHDRAWN_DIGESTS:
        _fail("this Implementer profile digest was withdrawn and is not registrable", digest=profile["digest"])
    for field in ("capabilities", "limitations", "operations"):
        if not isinstance(profile[field], list) or not all(_text(v) for v in profile[field]):
            _fail("profile list fields hold non-empty strings", field=field)
    if "implement" not in profile["operations"]:
        _fail("an implementer profile must offer the implement operation", operations=profile["operations"])
    for field in ("maxContextBytes", "maxToolCalls", "maxRunSeconds"):
        if type(profile[field]) is not int or profile[field] < 1:
            _fail("profile limits are positive integers", field=field)
    actual = entry["actual_models"]
    if not isinstance(actual, list) or not actual or not all(_text(v) for v in actual):
        _fail("actual_models lists the accepted actual model readbacks")
    sources = entry["allowed_sources"]
    if not isinstance(sources, list) or not sources or not set(sources) <= set(SOURCES):
        _fail("allowed_sources is a non-empty subset of the Contract readback sources", allowed=list(SOURCES))
    budget = entry["budget"]
    if not isinstance(budget, dict) or set(budget) != set(BUDGET_FIELDS):
        _fail("budget carries exactly the four limits", expected=list(BUDGET_FIELDS))
    for field in BUDGET_FIELDS:
        value = budget[field]
        if type(value) is not int or not 1 <= value <= CONTRACT_BUDGET_MAX[field]:
            _fail("budget limit outside the Contract range", field=field, value=value, maximum=CONTRACT_BUDGET_MAX[field])
    if budget["maxToolCalls"] > profile["maxToolCalls"] or budget["maxRunSeconds"] > profile["maxRunSeconds"]:
        _fail("budget limits cannot exceed the profile limits")
    standalone = entry.get("standalone")
    if entry["mode"] == "standalone":
        if not isinstance(standalone, dict) or set(standalone) != {"command", "argv"}:
            _fail("a standalone entry names the Agent command and its argv template", fields=["command", "argv"])
        if not _text(standalone["command"]) or not isinstance(standalone["argv"], list) or \
                not all(isinstance(v, str) for v in standalone["argv"]):
            _fail("standalone command is a string and argv a list of strings")
    elif standalone is not None:
        _fail("only standalone entries carry a command template")
    return copy.deepcopy(entry)


def entries(state):
    return copy.deepcopy(state.get("configuration", {}).get(FIELD, []))


def set_registration(state, value, authority_ref):
    """Replace the entry list in one transaction and append the history record (no Registry write)."""
    if not isinstance(authority_ref, str) or not authority_ref:
        _fail("authorityRef is required to change the implementer port registration")
    if not isinstance(value, list):
        _fail("implementer-ports takes a JSON list of entries")
    normalised = [validate(e) for e in value]
    keys = [(e["id"], e["purpose"]) for e in normalised]
    if len(set(keys)) != len(keys):
        _fail("(portId, purpose) must be unique", keys=[list(k) for k in keys])
    identities = [(e["agent"], e["profile"]["digest"], e["mode"]) for e in normalised]
    if len(set(identities)) != len(identities):
        _fail("one agent and profile digest are registered once per mode")
    configuration = state.setdefault("configuration", {})
    previous = copy.deepcopy(configuration.get(FIELD))
    configuration[FIELD] = normalised
    configuration.setdefault("history", []).append(dict(at=now(), field=FIELD, previous=previous,
                                                        value=copy.deepcopy(normalised), authorityRef=authority_ref))
    return dict(key=KEY, entries=copy.deepcopy(normalised), previous=previous)


def resolve(state, port_id, purpose=PURPOSE):
    """The registered entry for (portId, purpose), or None when absent or withdrawn."""
    for entry in state.get("configuration", {}).get(FIELD, []):
        if entry["id"] == port_id and entry["purpose"] == purpose:
            return copy.deepcopy(entry)
    return None


def mapping(entry):
    """The mapping-shaped view HostExecutionPort consumes for readback checks (no vendor: feature-t6 owns it)."""
    return dict(id="implementer:" + entry["id"], revision=1, provider=entry["provider"], model_ref=entry["model_ref"],
                actual_models=list(entry["actual_models"]), model_vendor=None, route_vendor=None,
                allowed_sources=list(entry["allowed_sources"]))
