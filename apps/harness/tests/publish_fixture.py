"""Test-only fixtures for feature-t7: a synthetic product line, a local bare remote and a SYNTHETIC platform program.

PublishFixture extends feature-t5's ValidationFixture (feature-t0 acceptance, feature-t3 Definition freeze,
feature-t4 Implement and Verify with the synthetic Agent and checks, feature-t5 Validate Change): it creates a
local bare repository as the product line's `origin` remote (a pre-receive hook can be told to reject or to stall
and reject), writes a SYNTHETIC platform program that answers the `gh api` interface from a JSON state file in
the test directory, and configures `publish-target` to point at both. The domain, the executors, the push, the
production GitHub adapter and the feature-t6 Policy Gate are production code; only the remote and the platform
are synthetic. No real platform program, network interface, remote or model is ever used.
"""
from collections.abc import Mapping
import copy
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.publish import binding as publish_binding, configuration, records as publish_records
from domain.workflow import progression, states
from product_line import git
from runtime.executions import Environment, run_pending
import validation_fixture as VF

OWNER = VF.OWNER
REPOSITORY = "synthetic/product-line"
REPOSITORY_ID = "424242"
# The Git environment every test in this module runs product git under: no user or system configuration.
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}

PLATFORM = r'''#!{python}
"""SYNTHETIC platform program for feature-t7 tests: the `gh api` interface over a JSON state file. Never a real platform."""
import fcntl, json, subprocess, sys, time
from urllib.parse import parse_qs, urlsplit
STATE = {state!r}
def load(f):
    f.seek(0); return json.load(f)
def save(f, s):
    f.seek(0); f.truncate(); json.dump(s, f, indent=1); f.flush()
if "--version" in sys.argv:
    s = json.load(open(STATE)); print(s.get("version", "synthetic-platform 1.0")); sys.exit(0)
args = sys.argv[1:]
method = args[args.index("--method") + 1]
path = next(a for a in args[1:] if a.startswith("/"))
body = json.loads(sys.stdin.read()) if "--input" in args else None
with open(STATE, "r+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    s = load(f)
    s["requests"].append(dict(method=method, path=path, argv=args))
    fault = None
    for i, candidate in enumerate(s["faults"]):
        if candidate["method"] == method and path.split("?")[0].endswith(candidate.get("suffix", "")):
            if candidate.get("skip", 0) > 0:
                candidate["skip"] -= 1; break
            fault = s["faults"].pop(i); break
    save(f, s)
if fault and fault["mode"] == "hang":
    time.sleep(fault.get("seconds", 30)); sys.stderr.write("error connecting to api.synthetic\n"); sys.exit(1)
if fault and fault["mode"] == "http":
    sys.stderr.write("HTTP %d: synthetic refusal\n" % fault["status"]); sys.exit(1)
if fault and fault["mode"] == "transport":
    sys.stderr.write("error connecting to api.synthetic\n"); sys.exit(1)
if fault and fault["mode"] == "garbage":
    print("not json"); sys.exit(0)
repo = "/repos/" + s["repository"]["full_name"]
def pull_json(p):
    return p
with open(STATE, "r+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    s = load(f)
    parts = urlsplit(path)
    if method == "GET" and parts.path == repo:
        out = dict(id=s["repository"]["id"], full_name=s["repository"]["full_name"])
    elif method == "GET" and parts.path == repo + "/pulls":
        q = parse_qs(parts.query)
        owner, _, branch = q["head"][0].partition(":")
        rows = [p for p in s["pulls"] if p["head"]["ref"] == branch and p["base"]["ref"] == q["base"][0]]
        page, per = int(q.get("page", ["1"])[0]), int(q.get("per_page", ["30"])[0])
        out = rows[(page - 1) * per: page * per]
    elif method == "GET" and parts.path.startswith(repo + "/pulls/"):
        number = int(parts.path.rsplit("/", 1)[1])
        found = [p for p in s["pulls"] if p["number"] == number]
        if not found:
            sys.stderr.write("HTTP 404: Not Found\n"); sys.exit(1)
        out = found[0]
    elif method == "POST" and parts.path == repo + "/pulls":
        head = subprocess.run(["git", "--git-dir", s["bare"], "rev-parse", "--verify", "--quiet", "refs/heads/" + body["head"]],
                              capture_output=True, text=True).stdout.strip()
        if not head:
            sys.stderr.write("HTTP 422: Validation Failed\n"); sys.exit(1)
        number = max([p["number"] for p in s["pulls"]] + [0]) + 1
        out = dict(number=number, html_url="https://synthetic.invalid/%s/pull/%d" % (s["repository"]["full_name"], number),
                   state="open", merged_at=None, title=body["title"], body=body["body"],
                   head=dict(ref=body["head"], sha=head, repo=dict(full_name=s["repository"]["full_name"])),
                   base=dict(ref=body["base"]))
        s["pulls"].append(out)
        save(f, s)
        if fault and fault["mode"] == "lost":
            sys.stderr.write("error connecting to api.synthetic (answer lost)\n"); sys.exit(1)
        if fault and fault["mode"] == "created-then-hang":
            time.sleep(fault.get("seconds", 30)); sys.exit(1)
    else:
        sys.stderr.write("HTTP 404: Not Found\n"); sys.exit(1)
print(json.dumps(out))
'''

HOOK = r'''#!/bin/sh
# SYNTHETIC pre-receive hook of the local bare remote: reject, or stall and reject, when told to.
mode=$(cat "{mode}" 2>/dev/null)
case "$mode" in
  reject) echo "synthetic remote refuses the push" >&2; exit 1 ;;
  stall) sleep {stall}; echo "synthetic remote refuses the push after stalling" >&2; exit 1 ;;
esac
exit 0
'''


class SyntheticPlatform:
    """The state file and the program; each request is appended to `requests`."""

    def __init__(self, directory, bare, version="synthetic-platform 1.0"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path = self.directory / "platform-state.json"
        self.path = self.directory / "bin" / "synthetic-platform"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(dict(repository=dict(id=int(REPOSITORY_ID), full_name=REPOSITORY), pulls=[],
                                                   requests=[], faults=[], bare=str(bare), version=version), indent=1))
        self.write()

    def write(self, extra=""):
        self.path.write_text(PLATFORM.format(python=sys.executable, state=str(self.state_path)) + extra)
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)

    def state(self):
        return json.loads(self.state_path.read_text())

    def edit(self, change):
        with open(self.state_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            s = json.load(f)
            change(s)
            f.seek(0)
            f.truncate()
            json.dump(s, f, indent=1)

    def fault(self, method, mode, suffix="", **extra):
        self.edit(lambda s: s["faults"].append(dict(method=method, mode=mode, suffix=suffix, **extra)))

    def requests(self):
        return self.state()["requests"]

    def pulls(self):
        return self.state()["pulls"]

    def upgrade(self, version):
        """A new program version with different bytes (OD-399: never a reason to refuse)."""
        self.edit(lambda s: s.update(version=version))
        self.write("# %s\n" % version)


class PublishFixture(VF.ValidationFixture):
    def __init__(self, root, *, configure=True, **kwargs):
        super().__init__(root, **kwargs)
        self.bare = self.root / "remote.git"
        git(self.root, "init", "-q", "--bare", str(self.bare))
        self.remote_mode = self.root / "remote-mode"
        hook = self.bare / "hooks" / "pre-receive"
        hook.write_text(HOOK.format(mode=str(self.remote_mode), stall=4))
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        git(self.repo, "remote", "add", "origin", str(self.bare))
        self.platform = SyntheticPlatform(self.root / "platform", self.bare)
        if configure:
            self.configure()

    def target(self, **overrides):
        value = dict(provider="github", host="github.com", repository=REPOSITORY, repositoryId=REPOSITORY_ID, remote="origin",
                     remoteAddress=str(self.bare), targetBranch="main", cli=str(self.platform.path))
        value.update(overrides)
        return value

    def configure(self, **overrides):
        return self.domain.transaction(self.generation, lambda s: configuration.set_target(s, self.target(**overrides), OWNER))

    def set_remote_mode(self, mode):
        self.remote_mode.write_text(mode or "")

    # -- walking to the gates ----------------------------------------------------------------------
    def to_gate(self):
        """Implement, Verify PASS, Validate Change disabled: the task waits at the Publish Authorization Gate."""
        self.to_validate()
        self.validate("configure", "cfg-1")
        assert (self.inst()["position"], self.inst()["condition"]) == ("N-PUBLISH-AUTH-GATE", states.AWAITING_HUMAN_ACTION)

    def proposal(self):
        return publish_binding.proposal(self.state(), self.repo, self.task_id)

    def human_binding(self, **overrides):
        proposal = self.proposal()
        binding = copy.deepcopy(proposal["publishBinding"])
        pull = overrides.pop("pullRequest", None)
        binding.update(overrides)
        if pull is not None:
            binding["pullRequest"] = pull
        return binding, proposal["contextDigest"]

    def authorize(self, command_id="auth-1", digest=None, text="发布 feature-t0", **overrides):
        binding, current = self.human_binding(**overrides)
        return self.run("publish-authorize", commandId=command_id, decisionText=text, publishBinding=binding,
                        contextDigest=digest or current)

    def dispatch_publish(self, command_id="pub-1"):
        return self.run("publish-dispatch", commandId=command_id)

    def run_publish(self):
        env = Environment("cli", self.domain, self.generation, repository_root=str(self.repo))
        return run_pending(self.domain, env)

    def query(self, command_id):
        out = self.run("publish-query", commandId=command_id)
        failures = self.run_publish()
        assert not failures, failures
        return out

    def human_authorization(self, reference, assessment_id=None, scope=None):
        inst = self.inst()
        assessment_id = assessment_id or inst["recovery"]["current"]
        return dict(workflowInstance=self.task_id, occurrence=progression.occurrence(inst, self.task_id),
                    expectedRuntimeVersion=inst["runtimeVersion"], assessmentId=assessment_id, action="RECONCILE_CURRENT_NODE",
                    effectScope=scope or "publish-operation:" + self.ledger()["operation"]["id"],
                    authorizationRef="human:synthetic:" + reference)

    def reconcile(self, command_id, authorization):
        out = self.run("publish-reconcile", commandId=command_id, humanAuthorization=authorization)
        failures = self.run_publish()
        assert not failures, failures
        return out

    def publish(self):
        """Authorize, dispatch and run: the ordinary path."""
        self.authorize()
        self.dispatch_publish()
        failures = self.run_publish()
        assert not failures, failures

    # -- reads -------------------------------------------------------------------------------------
    def ledger(self):
        return publish_records.view_of(self.state(), self.task_id)

    def task_head(self):
        return git(self.repo, "rev-parse", "refs/heads/" + self.task["branch"])

    def remote_ref(self):
        out = git(self.bare, "for-each-ref", "--format=%(objectname)", "refs/heads/" + self.task["branch"])
        return out or None

    def refs(self):
        """Branch and tag refs of the remote and of the product line (the domain state ref excluded)."""
        return (git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)"),
                git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags", "refs/remotes"))

    def facts(self, purpose):
        return [f for f in self.inst()["facts"].values() if f["purpose"] == purpose]

    def third_party_commit(self, content="third party"):
        """A commit made outside the domain on a scratch branch (not the task branch)."""
        scratch = self.root / "third-party"
        if not scratch.exists():
            git(self.root, "clone", "-q", str(self.repo), str(scratch))
            git(scratch, "config", "user.name", "Synthetic")
            git(scratch, "config", "user.email", "synthetic@invalid")
        (scratch / "other.txt").write_text(content + "\n")
        git(scratch, "add", "other.txt")
        git(scratch, "commit", "-q", "-m", "synthetic third-party change")
        return scratch, git(scratch, "rev-parse", "HEAD")


def forbidden_requests(platform):
    """Requests outside the adapter's four endpoints (merge, close, edit, delete never appear)."""
    allowed = ("/repos/%s" % REPOSITORY, "/repos/%s/pulls" % REPOSITORY)
    out = []
    for r in platform.requests():
        path = r["path"].split("?")[0]
        ok = (r["method"] == "GET" and (path in allowed or path.startswith("/repos/%s/pulls/" % REPOSITORY))) or \
             (r["method"] == "POST" and path == allowed[1])
        if not ok or path.endswith("/merge"):
            out.append(r)
    return out


# -- helpers for other tasks' tests that now need a Publish binding (feature-t5 Accept With reservation) --------------
def attach(fx, directory=None):
    """Give an existing ValidationFixture a local bare remote, a SYNTHETIC platform and publish-target (feature-t7)."""
    root = Path(directory or fx.root)
    bare = root / "remote.git"
    git(root, "init", "-q", "--bare", str(bare))
    git(fx.repo, "remote", "add", "origin", str(bare))
    platform = SyntheticPlatform(root / "platform", bare)
    target = dict(provider="github", host="github.com", repository=REPOSITORY, repositoryId=REPOSITORY_ID, remote="origin",
                  remoteAddress=str(bare), targetBranch="main", cli=str(platform.path))
    fx.domain.transaction(fx.generation, lambda s: configuration.set_target(s, target, OWNER))
    return platform


def binding_for(fx):
    """publishBinding and contextDigest exactly as `harness publish context` proposes them for the task's current state."""
    proposal = publish_binding.proposal(fx.state(), fx.repo, fx.task_id)
    return dict(publishBinding=proposal["publishBinding"], contextDigest=proposal["contextDigest"])


class LazyBinding(Mapping):
    """A payload mapping whose binding and digest are read at the moment the payload is expanded (test only)."""

    def __init__(self, fx, **fields):
        self.fx, self.fields = fx, fields

    def _value(self):
        return dict(self.fields, **binding_for(self.fx))

    def __getitem__(self, key):
        return self._value()[key]

    def __iter__(self):
        return iter(self._value())

    def __len__(self):
        return len(self._value())
