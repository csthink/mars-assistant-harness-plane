"""Platform adapter for Publish (feature-t7 design, Publish 执行与平台适配器).

The interface has exactly four operations: read the repository identity, list pull requests by source and
target, create one pull request, read one pull request. There is no merge, close, edit, update or branch
deletion anywhere: Publish authorization never implies those powers (FR-29, C-07), and this is where that is
structural.

GitHubPlatform calls the configured platform command-line program's `api` subcommand (the `gh api` interface)
with the program's own native login; no token is read, stored or passed by the domain. Only the four endpoints
of the configured repository are allowed. Failures are classified (not-found, forbidden, invalid, transport,
output-invalid) and never echo the program's raw output, the address or headers. The program's identity
(resolved path, binary SHA-256, `--version` first line) is rediscovered on every execution and recorded; it is
never compared or used as an allow-list (Assistant OD-399). Tests configure a SYNTHETIC program path; no test
calls a real platform program or a network interface.
"""
import hashlib
import json
import os
import re
import subprocess
from urllib.parse import urlencode

API_TIMEOUT = 60
NOT_FOUND, FORBIDDEN, INVALID, TRANSPORT, OUTPUT_INVALID = "not-found", "forbidden", "invalid", "transport", "output-invalid"
# A definite write failure is one the platform answered; transport and unparseable answers leave a write unknown.
DEFINITE = (NOT_FOUND, FORBIDDEN, INVALID)


class PlatformError(Exception):
    def __init__(self, kind, method, status=None):
        self.kind, self.method, self.status = kind, method, status
        super().__init__("platform %s %s (%s)" % (method, kind, status or "-"))

    @property
    def definite(self):
        return self.kind in DEFINITE

    def detail(self):
        return dict(kind=self.kind, method=self.method, status=self.status)


def program_identity(path):
    """Rediscovered on every execution; recorded, never compared (OD-399)."""
    identity = dict(configured=path, resolved=None, sha256=None, version=None)
    try:
        resolved = os.path.realpath(path)
        identity["resolved"] = resolved
        with open(resolved, "rb") as handle:
            identity["sha256"] = hashlib.sha256(handle.read()).hexdigest()
        result = subprocess.run([path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        first = result.stdout.decode("utf-8", "replace").splitlines()[:1]
        identity["version"] = first[0][:200] if first else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return identity


def _pull(value):
    head, base = value.get("head") or {}, value.get("base") or {}
    return dict(number=value.get("number"), url=value.get("html_url"), state=value.get("state"),
                merged=bool(value.get("merged_at")), headRef=head.get("ref"), headSha=head.get("sha"),
                headRepository=(head.get("repo") or {}).get("full_name"), base=base.get("ref"),
                body=value.get("body") or "", title=value.get("title"))


class GitHubPlatform:
    provider = "github"

    def __init__(self, target, runner=None):
        self.target = dict(target)
        self.cli = target["cli"]
        self.endpoint = "/repos/" + target["repository"]
        self.runner = runner or subprocess.run
        self.requests = []

    def _allowed(self, method, path):
        if method == "GET" and (path == self.endpoint or path.startswith(self.endpoint + "/pulls?")
                                or re.fullmatch(re.escape(self.endpoint) + r"/pulls/[0-9]+", path)):
            return True
        return method == "POST" and path == self.endpoint + "/pulls"

    def api(self, method, path, body=None):
        if not self._allowed(method, path):
            raise PlatformError(INVALID, method, "endpoint-not-allowed")
        args = [self.cli, "api", "--method", method, path, "--hostname", self.target["host"]]
        if body is not None:
            args += ["--input", "-"]
        self.requests.append(dict(method=method, path=path))
        try:
            result = self.runner(args, input=None if body is None else json.dumps(body).encode("utf-8"),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=API_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PlatformError(TRANSPORT, method, exc.__class__.__name__) from exc
        if result.returncode != 0:
            text = (result.stderr + result.stdout).decode("utf-8", "replace")
            match = re.search(r"HTTP (\d{3})", text)
            status = int(match.group(1)) if match else None
            kind = {404: NOT_FOUND, 401: FORBIDDEN, 403: FORBIDDEN, 409: INVALID, 422: INVALID}.get(status, TRANSPORT)
            raise PlatformError(kind, method, status)
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlatformError(OUTPUT_INVALID, method) from exc

    def repository(self):
        value = self.api("GET", self.endpoint)
        if not isinstance(value, dict):
            raise PlatformError(OUTPUT_INVALID, "GET")
        return dict(fullName=value.get("full_name"), id=str(value.get("id")) if value.get("id") is not None else None)

    def pull_requests(self, head_branch, base):
        owner = self.target["repository"].split("/")[0]
        rows = []
        for page in range(1, 51):
            query = urlencode(dict(head="%s:%s" % (owner, head_branch), base=base, state="all", per_page=100, page=page))
            value = self.api("GET", self.endpoint + "/pulls?" + query)
            if not isinstance(value, list):
                raise PlatformError(OUTPUT_INVALID, "GET")
            rows.extend(_pull(v) for v in value if isinstance(v, dict))
            if len(value) < 100:
                return rows
        raise PlatformError(OUTPUT_INVALID, "GET", "pagination-not-exhausted")

    def create_pull_request(self, head_branch, base, title, body):
        value = self.api("POST", self.endpoint + "/pulls", dict(head=head_branch, base=base, title=title, body=body))
        if not isinstance(value, dict):
            raise PlatformError(OUTPUT_INVALID, "POST")
        return _pull(value)

    def pull_request(self, number):
        value = self.api("GET", "%s/pulls/%d" % (self.endpoint, int(number)))
        if not isinstance(value, dict):
            raise PlatformError(OUTPUT_INVALID, "GET")
        return _pull(value)

    def identity(self):
        return program_identity(self.cli)


def production(target):
    """The production factory behind HarnessDomain.publish_platform: GitHub only in this phase (Assistant KB-272)."""
    if target.get("provider") != "github":
        raise PlatformError(INVALID, "configure", "provider-not-supported")
    return GitHubPlatform(target)
