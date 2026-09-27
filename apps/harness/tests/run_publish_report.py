"""Offline acceptance report for feature-t7: runs test_publish and maps results to AC-01..AC-09.

Usage: python run_publish_report.py --output <new directory> [--cases <new directory outside every worktree>]
The output directory must not exist; it receives unittest.log, report.json and report.md. Per-test synthetic
product lines, local bare remotes and SYNTHETIC platform states go to --cases when given, otherwise to a temporary
directory that is removed after their persistent state has been read into the report.

PASS/FAIL derive from the recorded test results. A unittest ERROR (the test could not reach its assertion) is never
counted as product PASS or FAIL: the erroring test is re-run once in a fresh directory, both runs are recorded with
their durations, and the criterion takes the re-run's outcome; an ERROR that persists leaves the criterion NOT_RUN.
feature-t2 (progression and recovery contract), feature-t3 (execution layer), feature-t4 (Implement and Verify),
feature-t5 (Validate Change) and feature-t6 (Policy Gate push permit) are the real implementations; the remote is a
local bare repository and the platform, the Agent program and the impl-round reviewer output are SYNTHETIC. Real
GitHub push and pull request, the real platform program, GitLab, real model, J-03 bundle, J-04, J-05, J-06 real Host
and J-07 stay NOT_RUN.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import unittest

import instance_area

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
MODULES = ("test_publish",)
SOURCES = [
    "hp.py", "requirements.lock", "domain/core.py", "domain/store.py",
    "domain/publish/__init__.py", "domain/publish/binding.py", "domain/publish/commands.py", "domain/publish/configuration.py",
    "domain/publish/context.py", "domain/publish/dispatch.py", "domain/publish/executor.py", "domain/publish/gate.py",
    "domain/publish/platform.py", "domain/publish/projection.py", "domain/publish/records.py", "domain/publish/recovery.py",
    "domain/publish/results.py", "domain/publish/schema.py", "domain/publish/settle.py",
    "domain/validation/gate.py", "domain/validation/commands.py", "domain/validation/schema.py", "domain/validation/records.py",
    "domain/validation/dispatch.py", "domain/policy/rules.py", "domain/policy/items.py", "domain/policy/evaluate.py",
    "domain/workflow/progression.py", "domain/workflow/recovery.py", "domain/workflow/reservations.py",
    "domain/workflow/states.py", "domain/acceptance/terminal.py", "domain/acceptance/accept.py",
    "runtime/executions.py", "runtime/dispatcher.py", "runtime/main.py",
    "cli/main.py", "cli/publish.py", "cli/validation.py",
    "tests/product_line.py", "tests/definition_fixture.py", "tests/implement_verify_fixture.py",
    "tests/validation_fixture.py", "tests/validation_stdio.py", "tests/publish_fixture.py", "tests/publish_stdio.py",
    "tests/host_driver.py", "tests/test_publish.py", "tests/run_publish_report.py",
]
INPUTS = [
    "mechanisms/delivery-method/MVP_Workflow_v5.drawio",
    "mechanisms/artifact-templates/artifact_lint.py",
    "mechanisms/review-channel/review_channel_registry.json",
    "tasks/feature-t7/feature-t7.md",
    "tasks/feature-t7/rulings/RU-01-definition-review-skip.md",
    "tasks/feature-t7/rulings/RU-02-definition-finalization.md",
    "records/diagnostics/feature-t7/2026-09-23/inputs.json",
]
TOPOLOGY = "mechanisms/delivery-method/MVP_Workflow_v5.drawio"
CRITERIA = {
    "AC-01": "精确 Human 授权（FR-29、FR-26）",
    "AC-02": "push 与 Pull Request 创建或识别（FR-29、C-07）",
    "AC-03": "成功、未发生、未知的证据与同一 operation 查询（FR-29、FR-30）",
    "AC-04": "非受控变更停报（FR-29、FR-31）",
    "AC-05": "合并与关闭权限独立，Publish 授权不可跳过（FR-29、FR-42、C-07）",
    "AC-06": "有界并发（FR-32）",
    "AC-07": "两入口、幂等与 operation（FR-31、FR-63、NFR-01）",
    "AC-08": "J-03 最小路径证据",
    "AC-09": "验收报告与后继边界",
}
NOT_RUN = {
    "AC-02": ["真实 GitHub 上的 push 与 Pull Request 创建（远端为本机 bare 仓库，平台为合成程序；Assistant KB-273）",
              "真实平台命令行程序的运行"],
    "AC-07": ["真实 Assistant Host（serve-stdio 为产品入口真实进程，Host 为合成测试驱动）"],
    "AC-08": ["J-03 bundle、Manifest、启动方法与 Assistant supervisor 接收（feature-t18）"],
    "AC-09": ["真实 GitHub 推送与 Pull Request", "真实平台命令行程序", "GitLab Merge Request（Assistant KB-272）", "真实模型调用",
              "J-03 bundle", "J-04 真实资格", "J-05", "J-06 真实 Host 联调", "J-07"],
}
CONSUMERS = {
    "feature-t18": "J-03 bundle 固定本任务交付的最小路径；本报告 AC-08 的演练与测试标识是「hp 最小路径完成并有自身验收证据」的输入；"
                   "bundle 的精确产物、Manifest、启动方法与 Assistant supervisor 接收不在本任务",
    "feature-t19": "切片仓接入时配置 publish-target（provider github、平台仓库全名与 id、远端名与推送地址、目标分支、平台程序路径）；"
                   "真实 Publish 探针另行授权（Assistant KB-273）",
    "feature-t15": "治理日志消费 publish 台账（授权、operation、各次执行、观察、恢复）、Publish 授权决定事实与 Progression Commit 序列",
    "M-04 收口": "GitLab Merge Request 适配无后继任务承载（Assistant KB-272）；feature-t2 restartable 排除 N-PUBLISH 的观察供 "
                "repo:OD-13 重立 D-05 时核对（feature-t7:KB-01）",
}
UNDELIVERED = [
    "GitLab Merge Request 适配（provider 闭集只含 github，gitlab 配置 fail-closed 拒绝；Assistant KB-272）",
    "真实 GitHub 与真实平台命令行程序的运行（Assistant KB-273）",
    "合并、关闭、编辑 Pull Request、删除分支、目标分支同步与例行整理（C-07：不属于产品 Publish）",
    "hp 自身人工期的发布面（交接协议 publish 入口）不由本任务接管",
]


class Recorder(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.records = []
        self.started = {}

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)

    def record(self, test, outcome, detail=None):
        doc = (getattr(test, "_testMethodDoc", None) or "").strip()
        tags = sorted(set(re.findall(r"AC-\d\d", doc)))
        started = self.started.get(test.id(), time.monotonic())
        self.records.append(dict(test=test.id(), criteria=tags, doc=doc, outcome=outcome,
                                 seconds=round(time.monotonic() - started, 3), detail=detail))

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "ERROR", self._exc_info_to_string(err, test))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            outcome = "FAIL" if issubclass(err[0], test.failureException) else "ERROR"
            self.record(test, outcome, "subtest %s: %s" % (subtest._subDescription(), self._exc_info_to_string(err, test)))


def identity(path):
    raw = Path(path).read_bytes()
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def environment():
    dirty = git("-C", str(ROOT), "status", "--porcelain", "--", "apps") or ""
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(), machine=platform.machine(),
                git=git("--version"), repository_head=git("-C", str(ROOT), "rev-parse", "HEAD"),
                apps_dirty=bool(dirty), apps_dirty_paths=dirty.splitlines(),
                dependencies=dict(lock="apps/harness/requirements.lock", **identity(APP / "requirements.lock")))


def load(names, cases):
    os.environ["HP_TEST_OUTPUT"] = str(cases)
    for path in (APP, APP / "tests"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    return suite


def run(names, cases, log):
    return unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Recorder).run(load(names, cases))


def state_at(repo, commit):
    raw = git("-C", str(repo), "show", commit + ":state.json")
    if raw is None:
        return None
    state = json.loads(raw)
    tasks = {}
    for task_id, task in sorted((state.get("tasks") or {}).items()):
        inst = task.get("workflowInstance") or {}
        ledger = task.get("publish") or {}
        tasks[task_id] = dict(lifecycle=inst.get("lifecycle"), position=inst.get("position"), condition=inst.get("condition"),
                              runtimeVersion=inst.get("runtimeVersion"), commits=len(inst.get("commits") or []),
                              terminal=(task.get("terminal") or {}).get("kind"),
                              publishOperation=(ledger.get("operation") or {}).get("id"),
                              publishExecutions=[dict(kind=e.get("kind"), classification=(e.get("outcome") or {}).get("classification"),
                                                      failureCode=(e.get("outcome") or {}).get("failureCode"))
                                                 for e in ledger.get("executions") or []],
                              publishObservations=[(o.get("outcome") or {}).get("classification")
                                                   for o in ledger.get("observations") or []],
                              recoveryActions=[a.get("action") for a in (inst.get("recovery") or {}).get("actions") or []])
    return dict(commit=commit, domainRevision=state.get("revision"), sha256=hashlib.sha256(raw.encode()).hexdigest(),
                tasks=tasks)


def product_lines(directory):
    """Every synthetic product line, local bare remote and SYNTHETIC platform state under one test directory."""
    found = []
    for gitdir in sorted(Path(directory).rglob(".git")):
        if not gitdir.is_dir():
            continue  # a task worktree shares its product line's refs
        repo = gitdir.parent
        chain = (git("-C", str(repo), "rev-list", "--reverse", "refs/harness/runtime") or "").split()
        if not chain:
            continue
        raw = git("-C", str(repo), "show", chain[-1] + ":state.json")
        edges = {}
        for task_id, task in sorted((json.loads(raw).get("tasks") or {}).items()):
            commits = (task.get("workflowInstance") or {}).get("commits") or []
            edges[task_id] = [c["selectedEdge"] for c in commits if c.get("selectedEdge")]
        entry = dict(repository=str(repo.relative_to(directory)), runtimeRefCommits=len(chain),
                     before=state_at(repo, chain[0]), after=state_at(repo, chain[-1]), process=dict(selectedEdges=edges))
        bare = repo.parent / "remote.git"
        if bare.is_dir():
            entry["remote"] = (git("--git-dir", str(bare), "for-each-ref", "--format=%(refname) %(objectname)") or "").splitlines()
        platform_state = repo.parent / "platform" / "platform-state.json"
        if platform_state.is_file():
            data = json.loads(platform_state.read_text())
            entry["platform"] = dict(pulls=[dict(number=p["number"], state=p["state"], headSha=p["head"]["sha"],
                                                 base=p["base"]["ref"]) for p in data["pulls"]],
                                     requests=[r["method"] + " " + r["path"].split("?")[0] for r in data["requests"]])
        found.append(entry)
    return found


def states_by_test(cases, records):
    out = {}
    for record in records:
        name = record["test"].rsplit(".", 1)[-1]
        directory = Path(cases) / ("t7-" + name)
        out[record["test"]] = product_lines(directory) if directory.is_dir() else []
    return out


def alignment():
    design = instance_area.path("tasks/feature-t7/design.md").read_text(encoding="utf-8")
    marker = "### 施工对齐记录"
    if marker not in design:
        return []
    section = design.split(marker, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
    return [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cases", type=Path, default=None)
    args = parser.parse_args()
    instance_area.require()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("output must not exist: " + str(output))
    if args.cases is not None and args.cases.resolve().exists():
        raise SystemExit("cases must not exist: " + str(args.cases))
    output.mkdir(parents=True)
    temp = None
    if args.cases is None:
        temp = tempfile.TemporaryDirectory(prefix="hp-t7-report-cases-")
        cases = Path(temp.name)
    else:
        cases = args.cases.resolve()
        cases.mkdir(parents=True)
    before = {p: identity(instance_area.locate(p, ROOT)) for p in INPUTS}
    started = time.monotonic()
    with (output / "unittest.log").open("w") as log:
        log.write("## run 1\n")
        log.flush()
        result = run(MODULES, cases / "run-1", log)
        records = result.records
        states = states_by_test(cases / "run-1", records)
        reruns = []
        for record in [r for r in records if r["outcome"] == "ERROR"]:
            log.write("\n## re-run of %s (ERROR in run 1; ERROR is never product PASS or FAIL)\n" % record["test"])
            log.flush()
            again = run([record["test"]], cases / ("rerun-" + record["test"].rsplit(".", 1)[-1]), log)
            reruns.extend(dict(r, rerunOf=record["test"]) for r in again.records)
    total_seconds = round(time.monotonic() - started, 3)
    after = {p: identity(instance_area.locate(p, ROOT)) for p in INPUTS}
    final = {}
    for r in records:
        prior = final.get(r["test"])
        if prior is None or prior["outcome"] == "PASS":
            final[r["test"]] = r  # a failing subtest record outranks the test's own PASS
    for r in reruns:
        final[r["test"]] = r
    finals = list(final.values())
    criteria = {}
    for ac, subject in CRITERIA.items():
        if ac == "AC-09":
            continue
        tests = [r for r in finals if ac in r["criteria"]]
        outcomes = {r["outcome"] for r in tests}
        if not tests:
            result_ac = "NOT_RUN"
        elif "FAIL" in outcomes:
            result_ac = "FAIL"
        elif "ERROR" in outcomes:
            result_ac = "NOT_RUN"
        else:
            result_ac = "PASS"
        if ac == "AC-05" and before[TOPOLOGY] != after[TOPOLOGY]:
            result_ac = "FAIL"
        criteria[ac] = dict(subject=subject, result=result_ac, tests=[dict(test=r["test"], outcome=r["outcome"],
                                                                          seconds=r["seconds"]) for r in tests],
                            failed=[r["test"] for r in tests if r["outcome"] == "FAIL"],
                            errors=[r["test"] for r in tests if r["outcome"] == "ERROR"],
                            not_run=NOT_RUN.get(ac, []))
    complete = all(c["tests"] for c in criteria.values()) and before == after and all(r["test"] in states for r in records)
    criteria["AC-09"] = dict(subject=CRITERIA["AC-09"], result="PASS" if complete else "FAIL", tests=[], failed=[], errors=[],
                             not_run=NOT_RUN["AC-09"],
                             basis="本报告逐条列出 AC-01 至 AC-08 的结论与测试标识、固定输入前后身份、每个测试的合成产品线持久状态前后与"
                                   "推进边序列、本机 bare 远端 ref 与合成平台请求记录、源码与依赖与环境身份、ERROR 与 FAIL 分列及复跑、"
                                   "后继任务消费约束、未交付范围与 NOT_RUN 项")
    report = dict(kind="feature-t7-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  environment=environment(), sources={p: identity(APP / p) for p in SOURCES},
                  inputs=dict(before=before, after=after, unchanged=before == after),
                  standins=dict(label="local bare remote, SYNTHETIC platform program, Host, Agent program and reviewer output",
                                synthetic=["publish_fixture.SyntheticPlatform (the gh api interface over a JSON state file)",
                                           "publish_fixture local bare remote with a pre-receive hook (reject / stall)",
                                           "publish_stdio.PublishHost (Host side of the real serve-stdio process)",
                                           "implement_verify_fixture.SyntheticAgent (implementation commits)",
                                           "validation_fixture.SyntheticImplReviewer (impl-round verdicts)"],
                                real=["feature-t7 domain/publish (binding, gate, dispatch, executor, GitHub adapter, settle, recovery)",
                                      "feature-t6 Policy Gate push permit", "feature-t2 progression, recovery contract and reservations",
                                      "feature-t3 execution layer", "feature-t4 Implement / Verify loop",
                                      "feature-t5 Validate Change entry (Accept With reservation with binding)",
                                      "product serve-stdio entry (runtime.main) and standalone CLI (hp.py)"]),
                  cases=dict(retained=args.cases is not None, path=str(cases) if args.cases is not None else None),
                  tests=dict(total=len(finals), passed=sum(r["outcome"] == "PASS" for r in finals),
                             failed=sum(r["outcome"] == "FAIL" for r in finals),
                             errors=sum(r["outcome"] == "ERROR" for r in finals),
                             run1=dict(total=result.testsRun, failed=len(result.failures), errors=len(result.errors)),
                             seconds=total_seconds, records=records, reruns=reruns),
                  persistentState=states, criteria=criteria, alignment=alignment(), consumers=CONSUMERS,
                  undelivered=UNDELIVERED,
                  conclusion="PASS" if all(c["result"] == "PASS" for c in criteria.values()) else "FAIL",
                  limits=["合成产品线仓、本机临时 bare 远端、合成平台程序、合成 Host 与合成 Agent；无真实模型、真实平台、真实远端或生产数据",
                          "feature-t2 至 feature-t6 为真实实现",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t7 offline acceptance report", "",
             f"conclusion: {report['conclusion']} · tests {report['tests']['passed']}/{report['tests']['total']} passed"
             f" (FAIL {report['tests']['failed']}, ERROR {report['tests']['errors']}, re-runs {len(reruns)})"
             f" · {total_seconds}s · fixed inputs unchanged: {report['inputs']['unchanged']}", "",
             f"stand-ins: {report['standins']['label']}", "",
             "| AC | subject | result | tests | FAIL | ERROR | NOT_RUN |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for ac, c in criteria.items():
        lines.append(f"| {ac} | {c['subject']} | {c['result']} | {len(c['tests'])} | {len(c['failed'])} | {len(c['errors'])} | "
                     f"{'; '.join(c['not_run']) or '-'} |")
    lines += ["", "## 测试", "", "| test | AC | outcome | seconds |", "| --- | --- | --- | --- |"]
    lines += [f"| {r['test']} | {' '.join(r['criteria'])} | {r['outcome']} | {r['seconds']} |" for r in records]
    lines += [f"| {r['test']} (re-run) | {' '.join(r['criteria'])} | {r['outcome']} | {r['seconds']} |" for r in reruns]
    lines += ["", "## 施工对齐（见 design「施工对齐记录」）", ""] + ["- " + a for a in report["alignment"]]
    lines += ["", "## 后继任务的消费约束", "", "| 任务 | 约束 |", "| --- | --- |"]
    lines += [f"| {task} | {note} |" for task, note in CONSUMERS.items()]
    lines += ["", "## 未交付范围", ""] + ["- " + u for u in UNDELIVERED]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    if temp is not None:
        temp.cleanup()
    print(json.dumps(dict(conclusion=report["conclusion"], tests=report["tests"]["total"], passed=report["tests"]["passed"],
                          failed=report["tests"]["failed"], errors=report["tests"]["errors"],
                          criteria={k: v["result"] for k, v in criteria.items()}), ensure_ascii=False))
    return 0 if report["conclusion"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
