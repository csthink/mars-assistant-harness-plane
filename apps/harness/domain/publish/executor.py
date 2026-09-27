"""Publish execution and the same-operation query, outside any domain transaction.

The publish executor starts its execution in its own transaction (attempt RUNNING and the Publish node
EXECUTING, triggered by the push permit ALLOW), then, in order: rediscovers the platform program identity;
checks the task branch still equals the authorized commit, the remote's single push address still normalises
to the authorized one and the platform repository name and id still match; reads the remote task-branch value
for this operation; pushes exactly `<candidate>:refs/heads/<branch>` to the verified address (no `+`, no other
ref, never the domain state ref, no remote-tracking update) when the remote is absent or an ancestor, skips the
push when it already equals the candidate and stops otherwise; reads the remote back; then identifies the one
open or merged pull request of the same source, target and head commit, or creates one with the bound title,
body and the operation trailer and reads it back. A create whose answer is lost is followed by a listing for
the same operation, never by a blind second create.

Outcome classifications (results.EXECUTION_OUTCOMES): published, not-happened (nothing was written by this
operation), partial (the push landed and the pull request is proven not created), uncontrolled-change (a
change this operation did not make; nothing is forced, rolled back or approved) and unknown. The query
classifies the same facts as confirmed, absent, partial, uncontrolled-change or unknown. Evidence never
carries credentials, raw platform output or credential-bearing addresses.
"""
import asyncio
import copy

from domain.publish import binding as publish_binding, configuration, dispatch, records
from domain.publish.platform import PlatformError
from domain.publish.results import (
    ABSENT, CONFIRMED, NOT_HAPPENED, PARTIAL, PUBLISHED_OUTCOME, UNCONTROLLED, UNKNOWN, PublishRejection,
)
from domain.workflow.results import WorkflowRejection

PUSH_TIMEOUT = 300
LS_REMOTE_TIMEOUT = 60


class Stop(Exception):
    def __init__(self, classification, code, **detail):
        self.classification, self.code, self.detail = classification, code, detail
        super().__init__(code)


def _ls_remote(repository, address, branch):
    try:
        result = publish_binding.git(repository, "ls-remote", address, "refs/heads/" + branch, timeout=LS_REMOTE_TIMEOUT)
    except publish_binding.GitFailed:
        return None, False
    if result.returncode != 0:
        return None, False
    lines = [l.split("\t") for l in result.stdout.decode().splitlines() if l.strip()]
    values = [l[0] for l in lines if len(l) == 2 and l[1] == "refs/heads/" + branch]
    return (values[0] if values else None), True


def _summary(pull):
    return {k: pull.get(k) for k in ("number", "url", "state", "merged", "headRef", "headSha", "headRepository", "base")}


def _matching(pulls, binding):
    repository = binding["platform"]["repository"]
    return [p for p in pulls if p["headRef"] == binding["sourceBranch"] and p["base"] == binding["targetBranch"]
            and (p["headRepository"] in (None, repository))]


def _judge_pulls(pulls, binding, trailer):
    """(verdict, pull) with verdict in identified / none / uncontrolled code."""
    same = _matching(pulls, binding)
    if len(same) > 1:
        return "pull-request-multiple", None
    if not same:
        return "none", None
    pull = same[0]
    if pull["state"] == "closed" and not pull["merged"]:
        return "pull-request-closed", pull
    if pull["headSha"] != binding["candidateCommit"]:
        return "pull-request-head", pull
    return "identified", pull


def _local_checks(repository, binding, platform, evidence):
    head = publish_binding.git(repository, "rev-parse", "--verify", "--quiet", "refs/heads/%s^{commit}" % binding["sourceBranch"])
    value = head.stdout.decode().strip() if head.returncode == 0 else None
    evidence["localBranch"] = value
    if value != binding["candidateCommit"]:
        raise Stop(UNCONTROLLED, "local-branch-moved", expected=binding["candidateCommit"], actual=value)
    raw, address = publish_binding.remote_address(repository, binding["remote"])
    evidence["remoteAddress"] = address if raw is not None else None
    if raw is None or address != binding["remoteAddress"]:
        raise Stop(UNCONTROLLED, "remote-address-changed", expected=binding["remoteAddress"],
                   actual=address if raw is not None else None)
    try:
        found = platform.repository()
    except PlatformError as exc:
        raise Stop(NOT_HAPPENED, "platform-unavailable", platform=exc.detail())
    evidence["platformRepository"] = found
    if found.get("fullName") != binding["platform"]["repository"] or found.get("id") != binding["platform"]["repositoryId"]:
        raise Stop(UNCONTROLLED, "platform-repository-mismatch", expected=binding["platform"], actual=found)
    return raw


def perform(repository, binding, operation, platform):
    """The whole publish operation; returns the outcome (classification, failureCode, evidence)."""
    evidence = dict(operation=operation, program=platform.identity(), push=dict(attempted=False), pullRequest=dict(action="none"))
    wrote = False
    try:
        raw = _local_checks(repository, binding, platform, evidence)
        branch, candidate = binding["sourceBranch"], binding["candidateCommit"]
        before, ok = _ls_remote(repository, raw, branch)
        evidence["remoteBefore"] = before
        if not ok:
            raise Stop(NOT_HAPPENED, "remote-unavailable")
        trailer = records.trailer(operation)
        # Before any write: a closed-unmerged or duplicated pull request of this source and target is not this
        # operation's state; stop without pushing.
        try:
            existing = platform.pull_requests(branch, binding["targetBranch"])
        except PlatformError as exc:
            raise Stop(NOT_HAPPENED, "pull-request-list-unavailable", platform=exc.detail())
        verdict, pull = _judge_pulls(existing, binding, trailer)
        evidence["pullRequest"]["before"] = [_summary(p) for p in _matching(existing, binding)]
        if verdict in ("pull-request-multiple", "pull-request-closed"):
            raise Stop(UNCONTROLLED, verdict, pull=_summary(pull) if pull else None)
        if before != candidate:
            if before is not None and not publish_binding.is_ancestor(repository, before, candidate):
                raise Stop(UNCONTROLLED, "remote-branch-diverged", expected="absent or an ancestor of the candidate", actual=before)
            evidence["push"] = dict(attempted=True)
            pushed, timed_out = None, False
            try:
                pushed = publish_binding.git(repository, "push", raw, "%s:refs/heads/%s" % (candidate, branch),
                                             timeout=PUSH_TIMEOUT)
                evidence["push"].update(returncode=pushed.returncode, timedOut=False)
            except publish_binding.GitFailed:
                timed_out = True
                evidence["push"].update(returncode=None, timedOut=True)
            after, ok = _ls_remote(repository, raw, branch)
            evidence["remoteAfter"] = after
            if ok and after == candidate:
                wrote = True
            elif not ok:
                raise Stop(UNKNOWN, "push-readback-unavailable")
            elif timed_out:
                # The push process was stopped; the remote may still apply it later. Never read as not happened.
                raise Stop(UNKNOWN, "push-timeout")
            elif pushed.returncode != 0 and after == before:
                raise Stop(NOT_HAPPENED, "push-rejected")
            else:
                raise Stop(UNKNOWN, "push-readback-mismatch", expected=candidate, actual=after)
        else:
            evidence["remoteAfter"] = before
            evidence["push"] = dict(attempted=False, alreadyPushed=True)
        try:
            pulls = platform.pull_requests(branch, binding["targetBranch"])
        except PlatformError as exc:
            raise Stop(PARTIAL, "pull-request-list-unavailable", platform=exc.detail())
        verdict, pull = _judge_pulls(pulls, binding, trailer)
        evidence["pullRequest"]["lookup"] = [_summary(p) for p in _matching(pulls, binding)]
        if verdict not in ("identified", "none"):
            raise Stop(UNCONTROLLED, verdict, pull=_summary(pull) if pull else None)
        if verdict == "identified":
            evidence["pullRequest"].update(action="identified", markerPresent=pull["body"].rstrip().endswith(trailer),
                                           **_summary(pull))
            return dict(classification=PUBLISHED_OUTCOME, failureCode=None, evidence=evidence)
        body = binding["pullRequest"]["body"].rstrip("\n") + "\n\n" + trailer + "\n"
        try:
            created = platform.create_pull_request(branch, binding["targetBranch"], binding["pullRequest"]["title"], body)
        except PlatformError as exc:
            evidence["pullRequest"]["create"] = exc.detail()
            try:
                again = platform.pull_requests(branch, binding["targetBranch"])
            except PlatformError:
                raise Stop(UNKNOWN, "pull-request-create-unknown", platform=exc.detail())
            verdict, pull = _judge_pulls(again, binding, trailer)
            if verdict == "identified":
                evidence["pullRequest"].update(action="created-after-uncertain-answer",
                                               markerPresent=pull["body"].rstrip().endswith(trailer), **_summary(pull))
                return dict(classification=PUBLISHED_OUTCOME, failureCode=None, evidence=evidence)
            if verdict == "none" and exc.definite:
                raise Stop(PARTIAL, "pull-request-rejected", platform=exc.detail())
            if verdict == "none":
                raise Stop(UNKNOWN, "pull-request-create-unknown", platform=exc.detail())
            raise Stop(UNCONTROLLED, verdict)
        try:
            readback = platform.pull_request(created["number"])
        except PlatformError as exc:
            raise Stop(UNKNOWN, "pull-request-readback-unavailable", platform=exc.detail(), created=_summary(created))
        if readback["headSha"] != candidate or readback["base"] != binding["targetBranch"] or readback["headRef"] != branch:
            raise Stop(UNKNOWN, "pull-request-readback-mismatch", created=_summary(readback))
        evidence["pullRequest"].update(action="created", markerPresent=True, **_summary(readback))
        return dict(classification=PUBLISHED_OUTCOME, failureCode=None, evidence=evidence)
    except Stop as stop:
        evidence["stop"] = dict(code=stop.code, **copy.deepcopy(stop.detail))
        return dict(classification=stop.classification, failureCode=stop.code, evidence=evidence)
    except publish_binding.GitFailed as exc:
        return dict(classification=UNKNOWN if wrote or evidence["push"].get("attempted") else NOT_HAPPENED,
                    failureCode="git-unavailable", evidence=dict(evidence, error=str(exc)))


def observe(repository, binding, operation, platform):
    """The same-operation query: read the remote branch and the pull requests; nothing is written."""
    evidence = dict(operation=operation, program=platform.identity())
    try:
        raw = _local_checks(repository, binding, platform, evidence)
    except Stop as stop:
        evidence["stop"] = dict(code=stop.code, **copy.deepcopy(stop.detail))
        return dict(classification=UNKNOWN if stop.classification == NOT_HAPPENED else stop.classification,
                    failureCode=stop.code, evidence=evidence)
    except publish_binding.GitFailed:
        return dict(classification=UNKNOWN, failureCode="git-unavailable", evidence=evidence)
    branch, candidate = binding["sourceBranch"], binding["candidateCommit"]
    value, ok = _ls_remote(repository, raw, branch)
    evidence["remote"] = value
    if not ok:
        return dict(classification=UNKNOWN, failureCode="remote-unavailable", evidence=evidence)
    if value is not None and value != candidate and not publish_binding.is_ancestor(repository, value, candidate):
        evidence["stop"] = dict(code="remote-branch-diverged", actual=value)
        return dict(classification=UNCONTROLLED, failureCode="remote-branch-diverged", evidence=evidence)
    try:
        pulls = platform.pull_requests(branch, binding["targetBranch"])
    except PlatformError as exc:
        return dict(classification=UNKNOWN, failureCode="pull-request-list-unavailable", evidence=dict(evidence, platform=exc.detail()))
    verdict, pull = _judge_pulls(pulls, binding, records.trailer(operation))
    evidence["pullRequests"] = [_summary(p) for p in _matching(pulls, binding)]
    if verdict not in ("identified", "none"):
        evidence["stop"] = dict(code=verdict)
        return dict(classification=UNCONTROLLED, failureCode=verdict, evidence=evidence)
    if value == candidate and verdict == "identified":
        evidence["pullRequest"] = _summary(pull)
        return dict(classification=CONFIRMED, failureCode=None, evidence=evidence)
    if verdict == "identified":
        # A pull request of this head exists while the remote branch is not the candidate: not this operation's state.
        evidence["stop"] = dict(code="pull-request-without-branch")
        return dict(classification=UNCONTROLLED, failureCode="pull-request-without-branch", evidence=evidence)
    if value == candidate:
        return dict(classification=PARTIAL, failureCode="pull-request-absent", evidence=evidence)
    return dict(classification=ABSENT, failureCode="remote-branch-absent", evidence=evidence)


QUERY_TO_EXECUTION = {CONFIRMED: PUBLISHED_OUTCOME, ABSENT: NOT_HAPPENED, PARTIAL: PARTIAL, UNCONTROLLED: UNCONTROLLED,
                      UNKNOWN: UNKNOWN}


def _inputs(env, descriptor):
    state = env.domain.read()
    record = records.ledger(state, descriptor["taskId"])
    authorization = record["authorization"]
    target = configuration.current(state) or {}
    platform = env.domain.publish_platform(dict(authorization["binding"]["platform"], cli=target.get("cli", "")))
    return authorization["binding"], authorization["operation"], platform


class PublishExecutor:
    """publish purpose: start (own transaction), then the whole operation; query-only on resume."""

    async def __call__(self, descriptor, env):
        task_id = descriptor["taskId"]

        def begin(state):
            inst = state["tasks"][task_id]["workflowInstance"]
            return dispatch.start(state, env.domain.topology(inst), task_id, descriptor["executionId"])
        try:
            await asyncio.to_thread(env.domain.transaction, env.generation(), begin)
        except (PublishRejection, WorkflowRejection) as exc:
            return dict(classification=NOT_HAPPENED, failureCode="refused-before-release",
                        evidence=dict(reason=exc.reason()))
        binding, operation, platform = _inputs(env, descriptor)
        return await asyncio.to_thread(perform, descriptor["input"]["repository"], binding, operation, platform)

    async def query(self, descriptor, env):
        """Resume of a running execution after a restart: never execute again, only query the same operation."""
        binding, operation, platform = _inputs(env, descriptor)
        seen = await asyncio.to_thread(observe, descriptor["input"]["repository"], binding, operation, platform)
        return dict(seen, classification=QUERY_TO_EXECUTION[seen["classification"]], via="query",
                    queryClassification=seen["classification"])


class QueryExecutor:
    """publish-query purpose: the same-operation query only; resuming it is the same query."""

    async def __call__(self, descriptor, env):
        binding, operation, platform = _inputs(env, descriptor)
        return await asyncio.to_thread(observe, descriptor["input"]["repository"], binding, operation, platform)

    async def query(self, descriptor, env):
        return await self(descriptor, env)
