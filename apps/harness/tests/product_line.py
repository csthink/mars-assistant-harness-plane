"""Synthetic product-line repository for the acceptance and workflow tests. Never a real repository.

The repository carries the four feature sources (finalized proposal, frozen spec, frozen milestones,
task list), their freeze records, the workflow topology file and optional done rulings, plus the
.synthetic-hp-domain marker required by the test launcher.

workflow=True copies the product topology master byte for byte so the state machine runs against the
registered 35 nodes and 45 edges; workflow="stub" writes an unreadable topology for the negative
case; workflow=False leaves it out entirely. The master itself is only read, never modified.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

WORKFLOW_TOPOLOGY = "mechanisms/delivery-method/MVP_Workflow_v5.drawio"
TOPOLOGY = Path(__file__).resolve().parents[3] / WORKFLOW_TOPOLOGY
ENV = {"GIT_AUTHOR_NAME": "Synthetic", "GIT_AUTHOR_EMAIL": "synthetic@invalid", "GIT_COMMITTER_NAME": "Synthetic",
       "GIT_COMMITTER_EMAIL": "synthetic@invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
HEADER = "# Synthetic {name}\n\n> Depends on:\n> {dep}\n>\n> 权威状态: subject `{subject}`（治理记录目录按所在仓的布局规则解析；唯一状态正本）\n\n"
TASK_ROWS = [
    "  - feature-t0 任务接纳 · 类型：后端 · Spec 引用：spec.md@r1 FR-15、FR-16 · 依赖：无",
    "  - feature-t1 hotfix 登记 · 类型：后端 · Spec 引用：spec.md@r1 FR-19 · 依赖：feature-t0",
    "  - gov-t0 治理基座 · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01 · 依赖：无",
    "  - gov-t1 第二治理 · 类型：治理机制 · Spec 引用：spec.md@r1 FR-02 · 依赖：无",
]

def git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, **ENV})
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout.decode().strip()

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def milestones_text(rows=None, withdrawn_rows=(), extra=""):
    rows = TASK_ROWS if rows is None else rows
    body = HEADER.format(name="milestones", dep="`spec.md@r1`", subject="milestones")
    body += "## 1. 规划基线\n\n合成计划。\n\n## 2. Milestone 条目\n\n### M-01 合成里程碑\n\n- 阶段目标：合成\n- UI 变更：无\n- UI lineage：不适用\n- 任务清单：\n"
    body += "\n".join(rows) + "\n- 验收条件：\n  - 合成验收\n\n"
    if withdrawn_rows:
        body += "### M-02 已撤回 · WITHDRAWN in milestones.md@r2\n\n- 阶段目标：历史\n- UI 变更：无\n- UI lineage：不适用\n- 任务清单：\n"
        body += "\n".join(withdrawn_rows) + "\n- 验收条件：\n  - 无\n\n"
    body += extra + "## 3. 跨 Milestone 依赖与调度\n\n无。\n\n## 4. 反思\n\n### 必须现在定\n\n无。\n\n### 同类潜在 bug 一并防止\n\n无。\n\n### 可接受残留（分级）\n\n无。\n"
    return body

def freeze_row(path, raw, revision=1, exit_value="freeze"):
    return json.dumps(dict(revision=revision, event="freeze", date="2026-09-22", objects=[dict(path=path, bytes=len(raw), sha256=sha256(raw))],
                           previous=[], changelog="changelog/CL-synthetic.md", check=dict(kind="owner-review", ref="records/governance/synthetic"),
                           instruction="synthetic freeze", exit=exit_value, reservation=None), ensure_ascii=False)

def write(repo, path, content):
    target = Path(repo) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if isinstance(content, bytes) else content.encode())

def without_auto_maintenance(repo):
    """No automatic maintenance or gc in a synthetic repository. A commit otherwise starts a detached
    `git maintenance run --auto` that can still be repacking (writing objects/pack and objects/info/packs) while the
    test removes its temporary directory, failing the cleanup with Directory not empty (feature-t18:KB-04). The
    repository configuration also covers linked worktrees and git processes that do not inherit the test environment."""
    git(repo, "config", "maintenance.auto", "false")
    git(repo, "config", "gc.auto", "0")

def create_product_line(directory, *, rows=None, withdrawn_rows=(), done=("gov-t1",), freeze=("proposal", "spec", "milestones"),
                        include=("sdd/proposal.md", "sdd/spec.md", "sdd/milestones.md"), workflow=True, subjects=None):
    """Create and commit a synthetic product-line repository; returns (path, head commit)."""
    repo = Path(directory)
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    without_auto_maintenance(repo)
    write(repo, ".synthetic-hp-domain", "Synthetic feature-t0 test product line only\n")
    subjects = dict({"sdd/proposal.md": "proposal", "sdd/spec.md": "spec", "sdd/milestones.md": "milestones"}, **(subjects or {}))
    documents = {
        "sdd/proposal.md": HEADER.format(name="proposal", dep="无", subject=subjects["sdd/proposal.md"]) + "## 1. 目标\n\n合成提案。\n",
        "sdd/spec.md": HEADER.format(name="spec", dep="`proposal.md@r1`", subject=subjects["sdd/spec.md"]) + "## 1. 目标\n\n- **FR-15** 合成需求。\n",
        "sdd/milestones.md": milestones_text(rows, withdrawn_rows).replace("subject `milestones`", "subject `%s`" % subjects["sdd/milestones.md"]),
    }
    for path, text in documents.items():
        if path in include:
            write(repo, path, text)
            subject = subjects[path]
            if subject in freeze or path.split("/")[-1].split(".")[0] in freeze:
                write(repo, f"records/governance/{subject}/freeze-records.jsonl", freeze_row(path, text.encode()) + "\n")
    if workflow:
        raw = TOPOLOGY.read_bytes() if workflow is True else b"<mxfile>unreadable synthetic topology</mxfile>\n"
        write(repo, WORKFLOW_TOPOLOGY, raw)
    for task in done:
        write(repo, f"tasks/{task}/rulings/RU-01-done.md", f"> Ruling: RU-01\n> Date: 2026-09-22\n> Type: done\n> Object: {task}\n> Basis: synthetic\n> Decision: synthetic done\n\n# done\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "synthetic product line")
    return repo, git(repo, "rev-parse", "HEAD")

def commit_change(repo, path, content, message="synthetic change", refreeze=True, revision=2):
    """Commit an upstream change; with refreeze, append a new freeze record row for the document."""
    write(repo, path, content)
    if refreeze:
        raw = (Path(repo) / path).read_bytes()
        subject = None
        for line in raw.decode().splitlines()[:8]:
            if line.startswith("> 权威状态: subject `"):
                subject = line.split("`")[1]
        record = Path(repo) / f"records/governance/{subject}/freeze-records.jsonl"
        with record.open("a") as f:
            f.write(freeze_row(path, raw, revision=revision) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")

def add_done_ruling(repo, task, message="synthetic done"):
    write(repo, f"tasks/{task}/rulings/RU-01-done.md", f"> Ruling: RU-01\n> Date: 2026-09-22\n> Type: done\n> Object: {task}\n> Basis: synthetic\n> Decision: synthetic done\n\n# done\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")
