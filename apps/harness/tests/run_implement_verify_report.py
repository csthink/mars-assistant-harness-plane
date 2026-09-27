"""Offline acceptance report for feature-t4: runs test_implement_verify and maps results to AC-01..AC-11.

Usage: python run_implement_verify_report.py --output <new directory> [--cases <new directory outside every worktree>]
The output directory must not exist; it receives unittest.log, report.json and report.md. Per-test synthetic
product lines (Git repositories) go to --cases when given, otherwise to a temporary directory that is removed.
PASS/FAIL derive from the recorded test results. feature-t3 (Definition path, execution layer, port factory,
RUNNING function) and feature-t6 (Policy Gate callback, author vendor mapping) are the real implementations;
feature-t5's Verification budget decision is the one synthetic stand-in. Real Host, Agent, model, J-04 and
J-05 stay NOT_RUN.
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
MODULES = ("test_implement_verify",)
SOURCES = [
    "hp.py", "requirements.lock", "domain/core.py", "domain/store.py",
    "domain/implement_verify/__init__.py", "domain/implement_verify/assessment.py",
    "domain/implement_verify/checks.py", "domain/implement_verify/commands.py",
    "domain/implement_verify/dispatch.py", "domain/implement_verify/executors.py",
    "domain/implement_verify/implement.py", "domain/implement_verify/registration.py",
    "domain/implement_verify/results.py", "domain/implement_verify/seams.py",
    "domain/implement_verify/settlement.py", "domain/implement_verify/steps.py",
    "domain/implement_verify/verify.py", "domain/implement_verify/worktree.py",
    "domain/implement_verify/projection.py", "domain/implement_verify/schema.py",
    "domain/workflow/progression.py", "domain/workflow/recovery.py", "domain/workflow/reservations.py",
    "execution/host.py", "execution/local.py", "execution/port.py", "runtime/executions.py", "runtime/dispatcher.py",
    "runtime/main.py", "domain/definition/commands.py", "domain/policy/authorize.py",
    "execution/implementer_local.py", "execution/implementer_supervisor.py",
    "cli/main.py", "cli/implement_verify.py",
    "tests/product_line.py", "tests/implement_verify_fixture.py", "tests/implement_verify_host.py",
    "tests/implement_verify_stdio.py", "tests/host_driver.py", "tests/definition_fixture.py", "tests/test_workflow_runtime.py",
    "tests/test_implement_verify.py",
    "tests/run_implement_verify_report.py",
]
INPUTS = [
    "mechanisms/delivery-method/MVP_Workflow_v5.drawio",
    "tasks/feature-t4/feature-t4.md",
    "tasks/feature-t4/rulings/RU-03-definition-refinalization.md",
    "records/diagnostics/feature-t4/2026-09-23/inputs.json",
    "records/diagnostics/feature-t4/2026-09-23/inputs/assistant/docs/design/evidence/host-execution-facts-j06/"
    "physical-execution.stopping.json",
    "records/diagnostics/feature-t4/2026-09-23/inputs/assistant/docs/design/evidence/host-execution-facts-j06/"
    "physical-execution.stopped.json",
]
CRITERIA = {
    "AC-01": "Implement 与 Verify 环按冻结拓扑推进",
    "AC-02": "实施结果与稳定引用",
    "AC-03": "Verify 三种结果与 FAIL 不可绕过",
    "AC-04": "Verify remediation 路径",
    "AC-05": "ExecutionPort 预约、放行与预算",
    "AC-06": "身份、原生批准与秘密",
    "AC-07": "J-06 停止未确认与自动解除",
    "AC-08": "实施与 Verify 节点的恢复",
    "AC-09": "单一编排入口与不同 executor",
    "AC-10": "两入口共用保护",
    "AC-11": "验收报告与后继边界",
}
# The AC's stated method needs wiring absent from this branch: the offline evidence is listed, the AC is NOT_RUN.
METHOD_NOT_RUN = {}
NOT_RUN = {
    "AC-04": ["feature-t5 的真实预算判定事实（以按 feature-t6 生产者绑定写入、明确标注的合成 policy-decision 代替）"],
    "AC-06": ["真实 Agent 程序身份与模型读回"],
    "AC-07": ["J-06 真实 Host 联调"],
    "AC-10": ["真实 Assistant Host（serve-stdio 为产品入口，Host 为合成测试驱动）"],
    "AC-11": ["真实 Agent 实施执行", "实施用途真实端口资格", "J-04", "J-05", "J-06 真实 Host 联调", "真实模型调用"],
}
DEVIATIONS = {
    "AC-10": "serve-stdio 场景中 J-06 停止样例除 requestIdentity 两字段外另把 scopeRef 换为 Host 打开的 scope（HostClient 核对应答 scope），其余字段原样",
    "AC-07": "嵌入测试返回 J-06 样例的全部字段，只把 requestIdentity.operationId 与 requestIdentity.requestDigest 换为端口按当前请求计算的值（端口核对二者）；与「原字节」措辞有此一处偏差",
}
CONSUMERS = {
    "feature-t3": "已合入并使用真实实现：implement-dispatch 登记执行描述（purpose coding-implementer，entry 按端口模式为 cli 或 runtime），执行层调用 ImplementExecutor；build_port 对 coding-implementer 构造带用途的端口、嵌入模式每次按启动配置的 launcher 重新发现程序身份、独立模式从产品侧登记取绑定；定稿经 commands.frozen_definition、RUNNING 经 progression.start_attempt",
    "feature-t5": "N-VERIFY-BUDGET-DECISION 与 remediation 消费 policy-decision 事实（purpose verification-budget，payload.outcome 为 Budget Remains / Budget Exhausted）；feature-t6 合入后该事实只能由 Policy Gate 产生、推进只消费其 ALLOW，因此两条出口都须是 conclusion ALLOW、以 outcome 区分的记录；E-V08 的触发事实与预算归 feature-t5",
    "feature-t6": "已合入并在全部测试中使用真实实现：本任务以 implement-release 调用 execution_authorizer，context 提供 definition、finalization、maxCalls=1，authority_ref 取派发授权定位；经 HarnessDomain.policy_sources 注入 implementer_registrations 读取器；预算四项齐备",
    "feature-t7": "Validate Change 通过后的发布不在本任务；本任务止于 N-VALIDATE-CONFIG",
    "feature-t15": "治理日志消费 implementVerify 台账与 Progression Commit 序列",
    "feature-t18": "bundle 与安装不在本任务",
    "feature-t19": "切片仓接入不在本任务",
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


def identity(path):
    raw = Path(path).read_bytes()
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def environment():
    git = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "apps"], capture_output=True,
                           text=True).stdout.strip()
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(), machine=platform.machine(),
                git=git, repository_head=head, apps_dirty=bool(dirty), apps_dirty_paths=dirty.splitlines())


def run(cases):
    os.environ["HP_TEST_OUTPUT"] = str(cases)
    sys.path.insert(0, str(APP / "tests"))
    sys.path.insert(0, str(APP))
    suite = unittest.TestSuite()
    for name in MODULES:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    return suite


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
        temp = tempfile.TemporaryDirectory(prefix="hp-t4-report-cases-")
        cases = Path(temp.name)
    else:
        cases = args.cases.resolve()
        cases.mkdir(parents=True)
    before = {p: identity(instance_area.locate(p, ROOT)) for p in INPUTS}
    suite = run(cases)
    with (output / "unittest.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Recorder).run(suite)
    after = {p: identity(instance_area.locate(p, ROOT)) for p in INPUTS}
    records = result.records
    criteria = {}
    for ac, subject in CRITERIA.items():
        tests = [r for r in records if ac in r["criteria"]]
        if ac == "AC-11":
            tests_ok = bool(records) and all(r["outcome"] == "PASS" for r in records)
        else:
            tests_ok = bool(tests) and all(r["outcome"] == "PASS" for r in tests)
        offline = "PASS" if tests_ok else ("NOT_RUN" if not tests else "FAIL")
        verdict = "NOT_RUN" if ac in METHOD_NOT_RUN and offline == "PASS" else offline
        criteria[ac] = dict(subject=subject, result=verdict, offline=offline, tests=[r["test"] for r in tests],
                            method_not_run=METHOD_NOT_RUN.get(ac), not_run=NOT_RUN.get(ac, []),
                            deviation=DEVIATIONS.get(ac))
    report = dict(kind="feature-t4-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  environment=environment(), sources={p: identity(APP / p) for p in SOURCES},
                  inputs=dict(before=before, after=after, unchanged=before == after),
                  standins=dict(label="SYNTHETIC feature-t5 budget decision",
                                interfaces=["feature-t5 verification-budget decision (Fixture.budget_fact)"],
                                real=["feature-t3 Definition path (submit, Authorize & Freeze, ruling write)",
                                      "feature-t3 execution layer and build_port", "feature-t3 progression.start_attempt",
                                      "feature-t6 execution_authorizer (policy-evaluate)",
                                      "feature-t6 configuration.authorVendors (config set author-vendor)",
                                      "product serve-stdio entry (runtime.main)"]),
                  cases=dict(retained=args.cases is not None, path=str(cases) if args.cases is not None else None),
                  tests=dict(total=result.testsRun, passed=sum(r["outcome"] == "PASS" for r in records),
                             failed=len(result.failures), errors=len(result.errors), records=records),
                  criteria=criteria, consumers=CONSUMERS,
                  conclusion="PASS" if result.wasSuccessful() and before == after else "FAIL",
                  limits=["合成产品线仓、合成 Agent 与合成嵌入 Host；无真实模型、真实 Agent 会话、真实 push/merge 或生产数据",
                          "feature-t3 与 feature-t6 为真实实现；feature-t5 预算判定以明确标注的合成替身代替",
                          "独立监督程序只观察登记的目标与后代进程，观察不完整时保守记为停止未确认或 unknown",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t4 offline acceptance report", "",
             f"conclusion: {report['conclusion']} · tests {report['tests']['passed']}/{report['tests']['total']} passed"
             f" · fixed inputs unchanged: {report['inputs']['unchanged']}", "",
             f"stand-ins: {report['standins']['label']}", "",
             "| AC | subject | result | offline | tests | NOT_RUN | deviation |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for ac, c in criteria.items():
        not_run = "; ".join(([c["method_not_run"]] if c["method_not_run"] else []) + c["not_run"]) or "-"
        lines.append(f"| {ac} | {c['subject']} | {c['result']} | {c['offline']} | {len(c['tests'])} | {not_run} | "
                     f"{c['deviation'] or '-'} |")
    lines += ["", "## 后继任务的消费约束", "", "| 任务 | 约束 |", "| --- | --- |"]
    lines += [f"| {task} | {note} |" for task, note in CONSUMERS.items()]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    if temp is not None:
        temp.cleanup()
    print(json.dumps(dict(conclusion=report["conclusion"], tests=report["tests"]["total"], passed=report["tests"]["passed"],
                          criteria={k: v["result"] for k, v in criteria.items()}), ensure_ascii=False))
    return 0 if report["conclusion"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
