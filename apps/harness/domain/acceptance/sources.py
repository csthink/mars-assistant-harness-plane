"""Source Resolution: read-only qualification of the four feature sources (spec FR-17 / FR-18).

Outcome is one of RESOLVED / UNRESOLVED / INDETERMINATE. UNRESOLVED only follows determinate
facts about the sources; INDETERMINATE only follows failures to read. Nothing is written,
repaired or searched for. RESOLVED carries a reproducible Canonical Source Anchor.
"""
import hashlib
import json
import re

import rfc8785

from domain.acceptance.gitrepo import GitAbsent, GitUnavailable, Repository
from domain.channel_contract import CONTRACT

RESOLVED, UNRESOLVED, INDETERMINATE = "RESOLVED", "UNRESOLVED", "INDETERMINATE"
TASK_TYPES = ("feature", "hotfix")
FEATURE_COMPONENTS = (("proposal", "sdd/proposal.md"), ("spec", "sdd/spec.md"), ("milestones", "sdd/milestones.md"))
FREEZE_EXITS = ("freeze", "freeze-with-reservation")
RE_SUBJECT = re.compile(r"^> 权威状态: subject `([A-Za-z0-9][A-Za-z0-9._-]*)`")
RE_MILESTONE_H3 = re.compile(r"^### (M-([0-9]+)) (\S.*?)(?: · Supersedes：(\S.*?))?(?: · WITHDRAWN in milestones\.md@r[1-9][0-9]*)?$")
RE_TASK_LINE = re.compile(r"^  - (\S+) (.+?) · 类型：(\S+) · Spec 引用：(.+?) · 依赖：(.+?)"
                          r"(?: · Supersedes：(\S.*?))?(?: · WITHDRAWN in milestones\.md@r[1-9][0-9]*)?$")
# The milestones task-id grammar is the review channel's TASK_ID_RE: one definition for acceptance and review routing.
RE_TASK_ID = CONTRACT.TASK_ID_RE
RE_WITHDRAWN = re.compile(r" · WITHDRAWN in milestones\.md@r[1-9][0-9]*$")

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def component(role, path, outcome, reason=None, **identity):
    return dict(role=role, path=path, outcome=outcome, reason=reason, identity=identity or None)

class Resolution(Exception):
    """Internal: stop resolution with a determinate (UNRESOLVED) or indeterminate outcome."""
    def __init__(self, outcome, reason, components):
        self.outcome, self.reason, self.components = outcome, reason, components
        super().__init__(reason)

def parse_task_rows(text):
    """Return every task row in the milestones list with its milestone identity and withdrawn flag."""
    rows, milestone, in_list = [], None, False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            milestone, in_list = None, False
        elif line.startswith("### "):
            m = RE_MILESTONE_H3.match(line)
            milestone = dict(id=m.group(1), withdrawn=bool(RE_WITHDRAWN.search(line))) if m else None
            in_list = False
        elif line.startswith("- 任务清单："):
            in_list = milestone is not None
        elif in_list and line.startswith("  - "):
            m = RE_TASK_LINE.match(line)
            if m:
                deps = [] if m.group(5) == "无" else m.group(5).split("、")
                rows.append(dict(taskId=m.group(1), line=number, milestone=milestone["id"], text=line, kind=m.group(3),
                                 specReferences=m.group(4), dependencies=deps,
                                 withdrawn=milestone["withdrawn"] or bool(RE_WITHDRAWN.search(line))))
        elif in_list and line.startswith("- "):
            in_list = False
    return rows

def frozen_identity(repo, commit, path, raw, components):
    """Check the header subject and the last freeze record row; return identity or raise Resolution."""
    role = path
    subject = None
    for line in raw.decode("utf-8", errors="replace").splitlines()[:8]:
        m = RE_SUBJECT.match(line)
        if m:
            subject = m.group(1)
            break
    if subject is None:
        raise Resolution(UNRESOLVED, f"{path}: header declares no subject", components)
    record_path = f"records/governance/{subject}/freeze-records.jsonl"
    try:
        record_raw = repo.read(commit, record_path)
    except GitAbsent:
        raise Resolution(UNRESOLVED, f"{path}: no freeze record for subject {subject}", components) from None
    rows = [line for line in record_raw.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not rows:
        raise Resolution(UNRESOLVED, f"{record_path}: empty freeze record", components)
    try:
        last = json.loads(rows[-1])
        objects = last["objects"]
        exit_value, revision = last["exit"], last["revision"]
    except (ValueError, KeyError, TypeError):
        raise Resolution(UNRESOLVED, f"{record_path}: last row is not a freeze record", components) from None
    if exit_value not in FREEZE_EXITS:
        raise Resolution(UNRESOLVED, f"{record_path}: last row exit is {exit_value!r}", components)
    match = [o for o in objects if isinstance(o, dict) and o.get("path") == path]
    if len(match) != 1 or match[0].get("bytes") != len(raw) or match[0].get("sha256") != sha256(raw):
        raise Resolution(UNRESOLVED, f"{path}: bytes differ from the frozen object in {record_path}", components)
    return dict(subject=subject, freezeRevision=revision, freezeRecord=record_path)

def resolve_feature(repository, task_id, base_ref):
    """Feature lane. Returns a Source Resolution Result dict; never raises for outcome reasons."""
    repo = Repository(repository)
    components = []
    checked = dict(taskType="feature", repository=str(repository), taskId=task_id, baseRef=base_ref)
    try:
        if not RE_TASK_ID.match(task_id or ""):
            raise Resolution(UNRESOLVED, "task id does not match the milestones task-id grammar", components)
        try:
            repo.common_dir()
        except GitAbsent as exc:
            raise Resolution(UNRESOLVED, "repository is not a git repository: " + str(exc), components) from None
        try:
            commit = repo.resolve(base_ref)
        except GitAbsent:
            raise Resolution(UNRESOLVED, f"base ref {base_ref!r} does not resolve to a commit", components) from None
        roots = repo.root_commits(commit)
        repository_identity = "git-root:" + "+".join(roots)
        documents = {}
        for role, path in FEATURE_COMPONENTS:
            try:
                blob = repo.blob_id(commit, path)
            except GitAbsent:
                components.append(component(role, path, UNRESOLVED, "missing at the source revision"))
                raise Resolution(UNRESOLVED, f"{path}: missing at {commit}", components) from None
            raw = repo.read(commit, path)
            try:
                frozen = frozen_identity(repo, commit, path, raw, components)
            except Resolution as exc:
                components.append(component(role, path, UNRESOLVED, exc.reason))
                raise
            identity = dict(blob=blob, bytes=len(raw), sha256=sha256(raw), **frozen)
            components.append(component(role, path, RESOLVED, None, **identity))
            documents[role] = (raw, identity)
        rows = parse_task_rows(documents["milestones"][0].decode("utf-8", errors="replace"))
        hits = [r for r in rows if r["taskId"] == task_id]
        if len(hits) != 1:
            reason = "task id not present in the milestones task list" if not hits else "task id matched more than one row"
            components.append(component("task", "sdd/milestones.md", UNRESOLVED, reason, matches=len(hits)))
            raise Resolution(UNRESOLVED, reason, components)
        row = hits[0]
        if row["withdrawn"]:
            components.append(component("task", "sdd/milestones.md", UNRESOLVED, "task row or its milestone is WITHDRAWN", line=row["line"]))
            raise Resolution(UNRESOLVED, "task row is WITHDRAWN", components)
        components.append(component("task", "sdd/milestones.md", RESOLVED, None, line=row["line"], milestone=row["milestone"]))
        anchor = dict(repositoryIdentity=repository_identity, sourceRevision=commit, taskType="feature", taskId=task_id,
                      milestone=row["milestone"], taskRow=row["text"], taskRowLine=row["line"], dependencies=row["dependencies"],
                      components={role: documents[role][1] for role, _ in FEATURE_COMPONENTS})
        anchor["digest"] = sha256(rfc8785.dumps(anchor))
        return dict(outcome=RESOLVED, reason=None, anchor=anchor, components=components, checked=checked)
    except Resolution as exc:
        return dict(outcome=exc.outcome, reason=exc.reason, anchor=None, components=exc.components, checked=checked)
    except GitUnavailable as exc:
        return dict(outcome=INDETERMINATE, reason="source repository could not be read: " + str(exc), anchor=None,
                    components=components, checked=checked)
    except (OSError, UnicodeError) as exc:
        return dict(outcome=INDETERMINATE, reason="source read failed: " + repr(exc), anchor=None,
                    components=components, checked=checked)

def resolve(repository, task_type, task_id, base_ref):
    """Dispatch on task type. Only the feature lane exists in feature-t0; hotfix is feature-t1."""
    if task_type == "feature":
        return resolve_feature(repository, task_id, base_ref)
    raise ValueError("unsupported task type: " + str(task_type))
