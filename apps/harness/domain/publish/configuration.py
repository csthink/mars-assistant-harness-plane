"""Configuration key `publish-target`: where a Publish goes (feature-t7 design, Publish 目标配置).

The value is exactly eight keys: provider (closed set `github` in this phase; `gitlab` is refused, Assistant
KB-272), host, repository (owner/name), repositoryId (the immutable numeric platform id), remote (the Git
remote name in the product line), remoteAddress (the normalised push address of that remote), targetBranch
and cli (the absolute path of the platform command-line program; it only locates the program, whose identity
is rediscovered on every execution and never compared, Assistant OD-399). There is no default: an
unconfigured product line cannot authorize or dispatch a Publish. Writes happen in one Domain Core
transaction with an authority reference and append a history row carrying the domain revision; a change
never rewrites an authorization already bound.
"""
import copy
from datetime import datetime, timezone
import os
import re
from urllib.parse import urlsplit

from domain.publish.results import PUBLISH_TARGET_CONFIGURED, PUBLISH_TARGET_REJECTED, PublishRejection

KEY = "publish-target"
FIELD = "publishTarget"
KEYS = ("provider", "host", "repository", "repositoryId", "remote", "remoteAddress", "targetBranch", "cli")
PROVIDERS = ("github",)
RE_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
RE_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
RE_ID = re.compile(r"^[1-9][0-9]{0,19}$")
RE_REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
RE_SCP = re.compile(r"^([A-Za-z0-9._-]+)@([A-Za-z0-9.-]+):([^\s]+)$")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AddressInvalid(ValueError):
    """The address cannot be put in the normalised form (credential-bearing or unsupported)."""


def normalize_address(value):
    """Normalised push address: https / ssh (user git only) URLs without credentials, query or fragment and without a
    trailing `.git`; `git@host:path` becomes `ssh://git@host/path`; an absolute local path (test bare remotes) is
    resolved. Anything else, including relative paths and `file://`, is refused."""
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise AddressInvalid("the address must be a non-empty single-line string")
    if "://" in value:
        parts = urlsplit(value)
        if parts.scheme not in ("https", "ssh"):
            raise AddressInvalid("only https and ssh URLs are accepted")
        if parts.password is not None or (parts.username is not None and not (parts.scheme == "ssh" and parts.username == "git")):
            raise AddressInvalid("credential-bearing or unsupported user in the address")
        if parts.query or parts.fragment or not parts.hostname:
            raise AddressInvalid("the address carries a query, a fragment or no host")
        path = parts.path.lstrip("/").removesuffix(".git").rstrip("/")
        if not path:
            raise AddressInvalid("the address has no repository path")
        user = "git@" if parts.scheme == "ssh" else ""
        port = ":%d" % parts.port if parts.port else ""
        return "%s://%s%s%s/%s" % (parts.scheme, user, parts.hostname.lower(), port, path)
    scp = RE_SCP.match(value)
    if scp:
        if scp.group(1) != "git":
            raise AddressInvalid("only the git user is accepted in an scp-like address")
        path = scp.group(3).lstrip("/").removesuffix(".git").rstrip("/")
        return "ssh://git@%s/%s" % (scp.group(2).lower(), path)
    if os.path.isabs(value):
        return os.path.realpath(value)
    raise AddressInvalid("relative paths and other address forms are refused")


def _reject(field, message, **detail):
    raise PublishRejection(PUBLISH_TARGET_REJECTED, message, field="publishTarget." + field if field else "publishTarget", **detail)


def validate(value):
    if not isinstance(value, dict) or set(value) != set(KEYS):
        _reject(None, "publish-target takes exactly the keys " + ", ".join(KEYS), keys=list(KEYS),
                offered=sorted(value) if isinstance(value, dict) else None)
    bad = [k for k in KEYS if not isinstance(value[k], str) or not value[k]]
    if bad:
        _reject(bad[0], "every publish-target value is a non-empty string")
    if value["provider"] not in PROVIDERS:
        _reject("provider", "the platform closed set in this phase is github only (Assistant KB-272)",
                provider=value["provider"], providers=list(PROVIDERS))
    checks = (("host", RE_HOST), ("repository", RE_REPOSITORY), ("repositoryId", RE_ID), ("remote", RE_REMOTE),
              ("targetBranch", RE_BRANCH))
    for key, pattern in checks:
        if not pattern.match(value[key]):
            _reject(key, "publish-target %s does not have the required form" % key, pattern=pattern.pattern)
    branch = value["targetBranch"]
    if ".." in branch or branch.endswith(("/", ".lock", ".")) or "//" in branch:
        _reject("targetBranch", "targetBranch is not a valid short branch name")
    try:
        address = normalize_address(value["remoteAddress"])
    except AddressInvalid as exc:
        _reject("remoteAddress", str(exc))
    if not os.path.isabs(value["cli"]):
        _reject("cli", "cli is the absolute path of the platform command-line program")
    normalised = {k: value[k] for k in KEYS}
    normalised["host"] = value["host"].lower()
    normalised["remoteAddress"] = address
    return normalised


def set_target(state, value, authority_ref):
    """Write the value and append the history row (field, previous, value, authority, domain revision)."""
    if not isinstance(authority_ref, str) or not authority_ref:
        raise PublishRejection(PUBLISH_TARGET_REJECTED, "authorityRef is required to change the publish target",
                               field="authorityRef")
    normalised = validate(value)
    configuration = state.setdefault("configuration", {})
    previous = copy.deepcopy(configuration.get(FIELD))
    configuration[FIELD] = normalised
    configuration.setdefault("history", []).append(dict(at=now(), field=FIELD, previous=previous,
                                                        value=copy.deepcopy(normalised), authorityRef=authority_ref,
                                                        revision=str(state["revision"])))
    return dict(result=PUBLISH_TARGET_CONFIGURED, key=KEY, value=copy.deepcopy(normalised), previous=previous,
                revision=str(state["revision"]))


def current(state):
    return copy.deepcopy((state.get("configuration") or {}).get(FIELD))
