"""Offline acceptance report for feature-t6: runs the Policy Gate tests and maps results to AC-01..AC-10.

Usage: python run_policy_report.py --output <new directory>
The directory must not exist. It receives per-test artifacts (HP_TEST_OUTPUT), report.json and report.md.
PASS/FAIL derive from the recorded test results; J-04, J-05 and any real model stay NOT_RUN.
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
MODULES = ("test_policy",)
SOURCES = [
    "hp.py", "requirements.lock", "domain/core.py", "domain/store.py", "domain/policy/__init__.py",
    "domain/policy/results.py", "domain/policy/rules.py", "domain/policy/inputs.py", "domain/policy/items.py",
    "domain/policy/evaluate.py", "domain/policy/authorize.py", "domain/workflow/progression.py",
    "domain/workflow/states.py", "domain/workflow/topology.py", "domain/acceptance/accept.py",
    "domain/acceptance/gitrepo.py", "execution/port.py", "execution/host.py", "execution/local.py", "cli/main.py",
    "runtime/protocol.py", "tests/product_line.py", "tests/policy_fixture.py", "tests/test_policy.py",
    "tests/test_execution_port.py", "tests/run_policy_report.py",
]
MECHANISM_SOURCES = [
    "mechanisms/delivery-method/MVP_Workflow_v5.drawio",
    "mechanisms/review-channel/review_channel_registry.json",
    "mechanisms/review-channel/review_channel_contract.py",
    "mechanisms/review-channel/review_channel_registry.py",
    "mechanisms/review-channel/review_channel_selection.py",
]
CRITERIA = {
    "AC-01": "判定项闭集、总体结论与退出码",
    "AC-02": "作者实际厂商集合与跨模型提供方（产品侧作者厂商映射）",
    "AC-03": "Reviewer 资格",
    "AC-04": "输入证据",
    "AC-05": "profile 用途与执行端",
    "AC-06": "Human authority",
    "AC-07": "精确 push 许可",
    "AC-08": "预算",
    "AC-09": "Policy Decision 记录、产生者绑定与执行授权",
    "AC-10": "验收报告与后继边界",
}
NOT_RUN = {
    "AC-03": ["真实评审端口资格与 REVIEW_ENABLED 提升（J-04，另行授权）"],
    "AC-05": ["feature-t4 的产品侧 Implementer 登记（以合成登记代替；生产读取器未注入时为 NOT_CHECKED）"],
    "AC-06": ["feature-t3 写入 Owner formal 授权事实的真实入口（以同形合成事实代替）"],
    "AC-07": ["feature-t7 在 Publish 授权时写入 publishBinding（以同形合成事实代替）"],
    "AC-09": ["feature-t3 的生产端口构造与回调注入接线（S-03）", "真实 Host 与真实 Agent 会话"],
    "AC-10": ["J-04 真实端口资格", "J-05 真实任务", "真实模型调用"],
}
CONSUMERS = {
    "feature-t3": "在 execution/host.py HostExecutionPort.authority() 的回调调用点注入 domain/policy/authorize.py 的 "
                  "execution_authorizer(domain, task_id, 'review-release', entry, generation, context=...)；生产端口构造接线归 t3（S-03）；"
                  "按本任务 design 的字段写 taskDefinition.candidates[].authorIdentity 与 purpose 为 owner-formal-review-authorization 的 human-decision 事实",
    "feature-t4": "同一回调，评估对象 implement-release；向 PolicyInputs 注入产品侧 Implementer 登记读取器（implementer_registrations）；"
                  "执行意图 budget 须齐备 maxToolCalls、maxRunSeconds、maxOutputBytes、cleanupSeconds",
    "feature-t5": "可复用 policy-decision 记录形态表达 budget 节点判定；FR-25 的计数与数值不在本任务",
    "feature-t7": "push 前经 apply_command('policy-evaluate') 取 push-permit 结论，只有 ALLOW 才 push；"
                  "在 Publish 授权决定事实 payload 写 publishBinding {candidateCommit, sourceBranch, remote, targetBranch}",
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
    registry = ROOT / "mechanisms/review-channel/review_channel_registry.json"
    registry_before = sha256(registry)
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
            verdict = "PASS" if records and all(r["outcome"] == "PASS" for r in records) else "FAIL"
        elif not tests:
            verdict = "NOT_RUN"
        else:
            verdict = "PASS" if all(r["outcome"] == "PASS" for r in tests) else "FAIL"
        criteria[ac] = dict(subject=subject, result=verdict, tests=[r["test"] for r in tests], not_run=NOT_RUN.get(ac, []))
    sources = {p: dict(bytes=(APP / p).stat().st_size, sha256=sha256(APP / p)) for p in SOURCES}
    for p in MECHANISM_SOURCES:
        sources[p] = dict(bytes=(ROOT / p).stat().st_size, sha256=sha256(ROOT / p), note="read only, never modified")
    report = dict(kind="feature-t6-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  environment=environment(), sources=sources,
                  live_registry=dict(before=registry_before, after=sha256(registry), unchanged=registry_before == sha256(registry)),
                  tests=dict(total=result.testsRun, passed=sum(r["outcome"] == "PASS" for r in records),
                             failed=len(result.failures), errors=len(result.errors), records=records),
                  criteria=criteria, consumers=CONSUMERS,
                  conclusion="PASS" if result.wasSuccessful() else "FAIL",
                  limits=["合成产品线仓、合成 Host 与同形合成的他任务事实；无真实模型、真实 Agent 会话、真实 push/merge 或生产数据",
                          "J-04、J-05 与真实模型保持 NOT_RUN；活体 Registry 只读",
                          "执行边界按 profile 声明呈现；当前 macOS 账户内的受信任本地执行，不声称强隔离或机械阻断任意 Agent 操作",
                          "human-decision 事实可经通用 fact 入口写入的缺口不在本任务（Assistant KB-258）",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t6 offline acceptance report", "",
             f"conclusion: {report['conclusion']} · tests {report['tests']['passed']}/{report['tests']['total']} passed · "
             f"live Registry unchanged: {report['live_registry']['unchanged']}", "",
             "| AC | subject | result | tests | NOT_RUN |", "| --- | --- | --- | --- | --- |"]
    for ac, c in criteria.items():
        lines.append(f"| {ac} | {c['subject']} | {c['result']} | {len(c['tests'])} | {'; '.join(c['not_run']) or '-'} |")
    lines += ["", "## 后继任务的消费调用点", "", "| 任务 | 调用点与约束 |", "| --- | --- |"]
    lines += [f"| {task} | {note} |" for task, note in CONSUMERS.items()]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(conclusion=report["conclusion"], tests=report["tests"]["total"], passed=report["tests"]["passed"],
                          criteria={k: v["result"] for k, v in criteria.items()}), ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
