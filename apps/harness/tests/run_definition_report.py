"""Offline acceptance report for feature-t3: runs the Definition test modules and maps results to AC-01..AC-10.

Usage: python run_definition_report.py --output <new directory>
The directory must not exist. It receives per-test artifacts (HP_TEST_OUTPUT), report.json and report.md.
PASS/FAIL derive from the recorded test results. AC-03 and AC-09 include runs through feature-t6's real
authorization callback (integrated from main); REAL_CALLBACK stays as the switch to hold them at NOT_RUN if
that callback is ever absent. J-03, J-04 real qualification, J-05, J-07 and any real model stay NOT_RUN.
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
import time
import unittest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
MODULES = ("test_definition", "test_definition_runtime")
SOURCES = [
    "hp.py", "requirements.lock", "domain/core.py", "domain/store.py", "domain/workflow/progression.py",
    "domain/workflow/projection.py", "domain/workflow/states.py", "domain/workflow/topology.py",
    "domain/definition/__init__.py", "domain/definition/results.py", "domain/definition/candidate.py",
    "domain/definition/review.py", "domain/definition/gate.py", "domain/definition/rulings.py",
    "domain/definition/commands.py", "domain/definition/dispatch.py", "domain/definition/projection.py",
    "domain/definition/schema.py", "runtime/executions.py", "runtime/dispatcher.py", "runtime/main.py",
    "execution/host.py", "execution/local.py", "execution/bridge.py", "execution/port.py", "cli/main.py",
    "cli/definition.py", "contract/schema.json", "tests/product_line.py", "tests/definition_fixture.py",
    "tests/serve_definition.py", "tests/host_driver.py", "tests/test_definition.py", "tests/test_definition_runtime.py",
    "tests/run_definition_report.py",
]
MECHANISMS = ["mechanisms/delivery-method/MVP_Workflow_v5.drawio", "mechanisms/artifact-templates/artifact_lint.py",
              "mechanisms/review-channel/review_channel_execution.py"]
CRITERIA = {
    "AC-01": "模板结构门与候选身份",
    "AC-02": "评审开关与 review-skip",
    "AC-03": "派发前置与授权消费",
    "AC-04": "五维 Verdict 消费",
    "AC-05": "失败与不确定不伪装 FAIL",
    "AC-06": "Human 定稿",
    "AC-07": "Definition escalation",
    "AC-08": "通用决定收窄、裁定写入与两入口等价",
    "AC-09": "执行层与生产接线",
    "AC-10": "验收报告与后继边界",
}
REAL_CALLBACK = set()  # feature-t6 integrated at main 5fe21e03; the real callback runs in AC-03 / AC-09 tests
NOT_RUN = {
    "AC-03": ["真实 embedded Host 的 host.execution.preflight 与真实评审方（J-04）"],
    "AC-04": ["真实评审通道 runner 发布的判词回读（legacy-git 回读已实现，未经真实评审验证；archive-v1 回读未实现，记为结果不确定）"],
    "AC-07": ["feature-t5 的真实 Definition Review 预算判定（测试以明确标注的合成判定事实驱动）"],
    "AC-09": ["真实 Assistant Host 的执行绑定来源（本实现读取可信启动配置 executionBindings，J-03 核对）"],
    "AC-10": ["J-03 bundle 组装（feature-t18）", "J-04 真实端口资格", "J-05 真实任务", "J-07 切片仓接入（feature-t19）", "真实模型调用"],
}
CONSUMERS = {
    "feature-t4": "复用 runtime/executions.py 的用途无关执行层与 progression.start_attempt；实施用途登记经 build_port 的 registration/mapping 关键字传入；施工派发以 commands.frozen_definition 读取定稿身份与 finalization 裁定件",
    "feature-t5": "在 N-DEF-BUDGET-DECISION 产生预算判定事实并沿 E-D10/E-D11 推进；本任务不自行判定",
    "feature-t6": "已合入：execution_authorizer(domain, task_id, subject, entry, generation, *, context, authority_ref) 读取 Define Task 固定的 authorIdentity 与 owner-formal-review-authorization 事实；Registry 读取已对齐为绑定产品线仓路径",
    "feature-t7": "Publish 与发布终态；Validation 与 Publish 位置的 Human 决定前置不在本任务",
    "feature-t18": "开发 bundle 与 J-03；launch 配置的 executionBindings 来源须与 Assistant Host 对齐",
    "feature-t19": "切片仓接入与 J-07",
}

class Recorder(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.records = []
        self.started = {}

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)

    def record(self, test, outcome, detail=None):
        doc = (test._testMethodDoc or "").strip()
        tags = sorted(set(re.findall(r"AC-\d\d", doc)))
        self.records.append(dict(test=test.id(), criteria=tags, doc=doc, outcome=outcome,
                                 seconds=round(time.monotonic() - self.started[test.id()], 3), detail=detail))

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "ERROR", self._exc_info_to_string(err, test))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment():
    git = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "apps"], capture_output=True, text=True).stdout.strip()
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(), machine=platform.machine(),
                git=git, repository_head=head, apps_dirty=bool(dirty), apps_dirty_paths=dirty.splitlines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("output must not exist: " + str(output))
    output.mkdir(parents=True)
    os.environ["HP_TEST_OUTPUT"] = str(output / "cases")
    sys.path.insert(0, str(APP / "tests"))
    sys.path.insert(0, str(APP))
    suite = unittest.TestSuite()
    for name in MODULES:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    with (output / "unittest.log").open("w") as log:
        runner = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Recorder)
        result = runner.run(suite)
    records = result.records
    criteria = {}
    for ac, subject in CRITERIA.items():
        tests = [r for r in records if ac in r["criteria"]]
        if ac == "AC-10":
            offline = "PASS" if records and all(r["outcome"] == "PASS" for r in records) else "FAIL"
        elif not tests:
            offline = "NOT_RUN"
        else:
            offline = "PASS" if all(r["outcome"] == "PASS" for r in tests) else "FAIL"
        verdict = "NOT_RUN" if ac in REAL_CALLBACK and offline == "PASS" else offline
        criteria[ac] = dict(subject=subject, result=verdict, offline_result=offline, tests=[r["test"] for r in tests],
                            not_run=NOT_RUN.get(ac, []))
    sources = {p: dict(bytes=(APP / p).stat().st_size, sha256=sha256(APP / p)) for p in SOURCES}
    for p in MECHANISMS:
        sources[p] = dict(bytes=(ROOT / p).stat().st_size, sha256=sha256(ROOT / p), note="read only, never modified")
    report = dict(kind="feature-t3-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  environment=environment(), sources=sources,
                  tests=dict(total=result.testsRun, passed=sum(r["outcome"] == "PASS" for r in records),
                             failed=len(result.failures), errors=len(result.errors), records=records),
                  criteria=criteria, consumers=CONSUMERS,
                  conclusion="PASS" if result.wasSuccessful() else "FAIL",
                  limits=["合成产品线仓、合成 Host 与合成评审方输出；授权回调在 AC-03/AC-09 的真实回调用例中为 feature-t6 生产实现，其余用例为合成替身；无真实模型、真实 Agent 会话、真实 push/merge 或生产数据",
                          "J-03、J-04 真实资格、J-05、J-07 与真实任务保持 NOT_RUN",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t3 offline acceptance report", "",
             f"conclusion: {report['conclusion']} · tests {report['tests']['passed']}/{report['tests']['total']} passed", "",
             "| AC | subject | result | offline | tests | NOT_RUN |", "| --- | --- | --- | --- | --- | --- |"]
    for ac, c in criteria.items():
        lines.append(f"| {ac} | {c['subject']} | {c['result']} | {c['offline_result']} | {len(c['tests'])} | {'; '.join(c['not_run']) or '-'} |")
    lines += ["", "## 后继任务的消费约束", "", "| 任务 | 约束 |", "| --- | --- |"]
    lines += [f"| {task} | {note} |" for task, note in CONSUMERS.items()]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(conclusion=report["conclusion"], tests=report["tests"]["total"], passed=report["tests"]["passed"],
                          criteria={k: v["result"] for k, v in criteria.items()}), ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
