"""Prescribed deterministic checks: authorised declarations, Definition requirements and execution.

Declarations live in the product-line domain configuration (`configuration.verifyChecks`), written
only through an authorised command, with an append-only history and a monotonically increasing
revision. An applicability decision binds the revision it used, so a later change cannot rewrite an
earlier decision or Verification Result (spec FR-23, NFR-02).

A finalized Definition may declare the checks it requires in a `## Extension: Prescribed Checks`
section (first line `Maps to: Acceptance Criteria`, then one "- `check-id`" line per check). When a
declared check is not registered, Verify is a check-execution failure that enters recovery; it is
never "not applicable" (Assistant KB-259, Owner-adopted option A).
"""
import copy
import hashlib
import os
import re
import subprocess
import time

from domain.workflow.progression import now
from domain.implement_verify.results import CHECKS_INVALID, ImplementVerifyRejection

FIELD = "verifyChecks"
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SECTION = "## Extension: Prescribed Checks"
ITEM = re.compile(r"^- `([a-z0-9][a-z0-9._-]{0,63})`\s*$")
DEFAULT_MAP = {"0": "PASS", "1": "FAIL"}
OUTCOMES = ("PASS", "FAIL")
# The domain state keeps an excerpt plus the full-output digest, so state growth stays bounded (feature-t2:KB-02).
EXCERPT_BYTES = 16384


def _fail(message, **detail):
    raise ImplementVerifyRejection(CHECKS_INVALID, message, **detail)


def validate(check):
    if not isinstance(check, dict):
        _fail("a check declaration is a JSON object")
    allowed = {"id", "argv", "timeoutSeconds", "resultMap", "paths"}
    if set(check) - allowed or not {"id", "argv", "timeoutSeconds"} <= set(check):
        _fail("check declaration fields do not match the closed set", allowed=sorted(allowed))
    if not isinstance(check["id"], str) or not ID.match(check["id"]):
        _fail("check id must be a stable lowercase identifier", id=check.get("id"))
    argv = check["argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        _fail("argv is a non-empty list of strings; checks never run through a shell", id=check["id"])
    timeout = check["timeoutSeconds"]
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        _fail("timeoutSeconds is an integer from 1 to 3600", id=check["id"])
    result_map = check.get("resultMap", DEFAULT_MAP)
    if not isinstance(result_map, dict) or not result_map or \
            not all(k.isdigit() and v in OUTCOMES for k, v in result_map.items()):
        _fail("resultMap maps decimal exit codes to PASS or FAIL", id=check["id"])
    paths = check.get("paths")
    if paths is not None and (not isinstance(paths, list) or not all(isinstance(p, str) and p and not p.startswith("/")
                                                                      and ".." not in p.split("/") for p in paths)):
        _fail("paths is a list of repository-relative prefixes", id=check["id"])
    return dict(id=check["id"], argv=list(argv), timeoutSeconds=timeout, resultMap=dict(result_map),
                paths=None if paths is None else list(paths))


def declared(state):
    record = state.get("configuration", {}).get(FIELD)
    return copy.deepcopy(record) if record else dict(revision=0, checks=[])


def set_checks(state, value, authority_ref):
    if not isinstance(authority_ref, str) or not authority_ref:
        _fail("authorityRef is required to change the prescribed checks")
    if not isinstance(value, list):
        _fail("checks take a JSON list of declarations")
    normalised = [validate(c) for c in value]
    ids = [c["id"] for c in normalised]
    if len(set(ids)) != len(ids):
        _fail("check ids are unique", ids=ids)
    configuration = state.setdefault("configuration", {})
    previous = copy.deepcopy(configuration.get(FIELD))
    revision = (previous or {}).get("revision", 0) + 1
    configuration[FIELD] = dict(revision=revision, checks=normalised)
    configuration.setdefault("history", []).append(dict(at=now(), field=FIELD, previous=previous,
                                                        value=copy.deepcopy(configuration[FIELD]),
                                                        authorityRef=authority_ref))
    return dict(revision=revision, checks=copy.deepcopy(normalised))


def prescribed(definition_bytes):
    """Check ids the Definition requires; an absent section declares none (visible at finalization)."""
    lines = definition_bytes.decode("utf-8").split("\n")
    if SECTION not in lines:
        return []
    start = lines.index(SECTION) + 1
    ids = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        match = ITEM.match(line)
        if match:
            ids.append(match.group(1))
    return ids


def applicable(check, changed):
    if check["paths"] is None:
        return True
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for path in changed for prefix in check["paths"])


def run(check, worktree):
    """Execute one declared check in the task worktree; an unmapped exit or timeout is an execution failure."""
    started = time.monotonic()
    try:
        completed = subprocess.run(check["argv"], cwd=str(worktree), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=check["timeoutSeconds"],
                                   env={k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if k in os.environ})
    except OSError as exc:
        return dict(id=check["id"], outcome=None, failure="not-startable", detail=str(exc)[:512],
                    seconds=round(time.monotonic() - started, 3))
    except subprocess.TimeoutExpired as exc:
        return dict(id=check["id"], outcome=None, failure="timeout", timeoutSeconds=check["timeoutSeconds"],
                    stdout=_evidence(exc.stdout or b""), stderr=_evidence(exc.stderr or b""),
                    seconds=round(time.monotonic() - started, 3))
    outcome = check["resultMap"].get(str(completed.returncode))
    record = dict(id=check["id"], argv=list(check["argv"]), exitCode=completed.returncode, outcome=outcome,
                  failure=None if outcome else "unmapped-exit-code", stdout=_evidence(completed.stdout),
                  stderr=_evidence(completed.stderr), seconds=round(time.monotonic() - started, 3))
    return record


def _evidence(raw):
    kept = raw[:EXCERPT_BYTES]
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), excerptBytes=len(kept),
                excerpt=kept.decode("utf-8", "replace"))
