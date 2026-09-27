"""Offline acceptance report for feature-t2: runs the workflow test modules and maps results to AC-01..AC-09.

Usage: python run_workflow_report.py --output <new directory>
The directory must not exist. It receives per-test artifacts (HP_TEST_OUTPUT), report.json and report.md.
PASS/FAIL derive from the recorded test results; J-03, J-04, J-05, J-07 and any real model stay NOT_RUN.
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
MODULES = ("test_workflow", "test_workflow_runtime")
SOURCES = [
    "hp.py", "requirements.lock", "domain/port.py", "domain/store.py", "domain/core.py",
    "domain/workflow/__init__.py", "domain/workflow/topology.py", "domain/workflow/states.py",
    "domain/workflow/results.py", "domain/workflow/progression.py", "domain/workflow/recovery.py",
    "domain/workflow/reservations.py", "domain/workflow/projection.py", "domain/workflow/schema.py",
    "domain/acceptance/accept.py", "domain/acceptance/gitrepo.py", "domain/acceptance/projection.py",
    "domain/acceptance/runtime_binding.py", "domain/acceptance/terminal.py", "cli/main.py",
    "runtime/dispatcher.py", "runtime/main.py", "runtime/protocol.py", "runtime/transport.py",
    "contract/schema.json", "contract/methods.json", "tests/product_line.py", "tests/workflow_fixture.py",
    "tests/serve_workflow.py", "tests/host_driver.py", "tests/test_workflow.py",
    "tests/test_workflow_runtime.py", "tests/test_host_driver.py", "tests/run_workflow_report.py",
]
TOPOLOGY = "mechanisms/delivery-method/MVP_Workflow_v5.drawio"
CRITERIA = {
    "AC-01": "分层正式状态与合法组合矩阵",
    "AC-02": "单一领域写者与两入口等价",
    "AC-03": "writer.lock、bootstrap/binding 与控制代次",
    "AC-04": "外部漂移拒绝",
    "AC-05": "Human Gate 合法决策集与任意时点终止",
    "AC-06": "停止未确认、预约保留与恢复",
    "AC-07": "幂等契约、operation 与生产接线",
    "AC-08": "不可变治理事实与本地形态",
    "AC-09": "验收报告与后继边界",
}
NOT_RUN = {
    "AC-02": ["真实 Assistant Host 与真实 Agent 会话（J-03 / J-05）"],
    "AC-06": ["真实物理执行观察与真实取消（feature-t4 / feature-t17 的真实 J-04）"],
    "AC-09": ["J-03 bundle 组装（feature-t18）", "J-04 真实端口资格", "J-05 真实任务", "J-07 切片仓接入（feature-t19）",
              "真实模型调用"],
}
CONSUMERS = {
    "feature-t1": "hotfix 登记与来源解析；本任务只推进已接纳 Task 的状态",
    "feature-t3": "Define Task 与 Review Definition 环的业务内容，消费本任务的位置推进与合法决策集",
    "feature-t4": "ExecutionPort 放行与 Implement / Verify 环，消费本任务的预约与 attempt 面",
    "feature-t5": "三处 autonomous budget 循环",
    "feature-t6": "Policy Gate 最小闭集",
    "feature-t7": "真实 push / PR 与外部发布结果，消费本任务的发布终态与恢复接缝",
    "feature-t15": "实际治理日志与统一时间线，消费本任务的 Progression Commit 序列",
    "feature-t18": "开发 bundle 与 J-03",
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
        if ac == "AC-09":
            verdict = "PASS" if records and all(r["outcome"] == "PASS" for r in records) else "FAIL"
        elif not tests:
            verdict = "NOT_RUN"
        else:
            verdict = "PASS" if all(r["outcome"] == "PASS" for r in tests) else "FAIL"
        criteria[ac] = dict(subject=subject, result=verdict, tests=[r["test"] for r in tests], not_run=NOT_RUN.get(ac, []))
    sources = {p: dict(bytes=(APP / p).stat().st_size, sha256=sha256(APP / p)) for p in SOURCES}
    sources[TOPOLOGY] = dict(bytes=(ROOT / TOPOLOGY).stat().st_size, sha256=sha256(ROOT / TOPOLOGY),
                             note="bound Workflow topology master; read only, never modified")
    report = dict(kind="feature-t2-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  environment=environment(), sources=sources,
                  tests=dict(total=result.testsRun, passed=sum(r["outcome"] == "PASS" for r in records),
                             failed=len(result.failures), errors=len(result.errors), records=records),
                  criteria=criteria, consumers=CONSUMERS,
                  conclusion="PASS" if result.wasSuccessful() else "FAIL",
                  limits=["合成产品线仓与合成 Host；无真实模型、真实 Agent 会话、真实 push/merge 或生产数据",
                          "J-03、J-04、J-05、J-07 与真实任务保持 NOT_RUN",
                          "写者锁是合作入口协议，不阻止同账户外部程序直改仓库；漂移判定只固定事实并停报",
                          "首期不承诺断电耐久、同账户恶意进程强隔离或远端一致性",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t2 offline acceptance report", "",
             f"conclusion: {report['conclusion']} · tests {report['tests']['passed']}/{report['tests']['total']} passed", "",
             "| AC | subject | result | tests | NOT_RUN |", "| --- | --- | --- | --- | --- |"]
    for ac, c in criteria.items():
        lines.append(f"| {ac} | {c['subject']} | {c['result']} | {len(c['tests'])} | {'; '.join(c['not_run']) or '-'} |")
    lines += ["", "## 后继任务的消费约束", "", "| 任务 | 约束 |", "| --- | --- |"]
    lines += [f"| {task} | {note} |" for task, note in CONSUMERS.items()]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(conclusion=report["conclusion"], tests=report["tests"]["total"], passed=report["tests"]["passed"],
                          criteria={k: v["result"] for k, v in criteria.items()}), ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
