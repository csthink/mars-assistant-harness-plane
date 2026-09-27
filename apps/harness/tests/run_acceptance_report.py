"""Offline acceptance report for feature-t0: runs the acceptance test modules and maps results to AC-01..AC-08.

Usage: python run_acceptance_report.py --output <new directory>
The directory must not exist. It receives per-test artifacts (HP_TEST_OUTPUT), report.json and report.md.
PASS/FAIL derive from the recorded test results; production wiring, J-03 and J-07 stay NOT_RUN.
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
MODULES = ("test_acceptance", "test_acceptance_runtime")
SOURCES = ["hp.py", "requirements.lock", "domain/port.py", "domain/store.py", "domain/acceptance/__init__.py", "domain/acceptance/accept.py",
           "domain/acceptance/gitrepo.py", "domain/acceptance/projection.py", "domain/acceptance/results.py", "domain/acceptance/runtime_binding.py",
           "domain/acceptance/schema.py", "domain/acceptance/sources.py", "domain/acceptance/terminal.py", "cli/__init__.py", "cli/main.py",
           "runtime/dispatcher.py", "runtime/host.py", "runtime/main.py", "runtime/protocol.py", "runtime/transport.py",
           "contract/schema.json", "contract/methods.json", "tests/product_line.py", "tests/acceptance_fixture.py", "tests/serve_acceptance.py",
           "tests/accept_with_fault.py", "tests/host_driver.py", "tests/test_acceptance.py", "tests/test_acceptance_runtime.py",
           "tests/run_acceptance_report.py"]
CRITERIA = {
    "AC-01": "正常接纳与两入口同一结果", "AC-02": "来源核验三态与 anchor 可复现", "AC-03": "幂等重试与跨请求去重",
    "AC-04": "并发上限拒绝", "AC-05": "原子性与断点恢复", "AC-06": "依赖、授权与拒绝闭集", "AC-07": "Runtime action 路径",
    "AC-08": "验收报告与后继边界",
}
NOT_RUN = {
    "AC-07": ["生产 serve-stdio 到正式 Domain Core 的接线（feature-t2）"],
    "AC-08": ["J-03 bundle 组装（feature-t18）", "J-07 真实仓干跑（feature-t19）", "真实任务与真实模型"],
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
        self.records.append(dict(test=test.id(), criteria=tags, doc=doc, outcome=outcome, seconds=round(time.monotonic() - self.started[test.id()], 3), detail=detail))

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
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(), machine=platform.machine(), git=git,
                repository_head=head, apps_dirty=bool(dirty), apps_dirty_paths=dirty.splitlines())

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
        if ac == "AC-08":
            verdict = "PASS" if records and all(r["outcome"] == "PASS" for r in records) else "FAIL"
        elif not tests:
            verdict = "NOT_RUN"
        else:
            verdict = "PASS" if all(r["outcome"] == "PASS" for r in tests) else "FAIL"
        criteria[ac] = dict(subject=subject, result=verdict, tests=[r["test"] for r in tests], not_run=NOT_RUN.get(ac, []))
    sources = {p: dict(bytes=(APP / p).stat().st_size, sha256=sha256(APP / p)) for p in SOURCES}
    report = dict(kind="feature-t0-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), environment=environment(),
                  sources=sources, tests=dict(total=result.testsRun, passed=sum(r["outcome"] == "PASS" for r in records),
                                              failed=len(result.failures), errors=len(result.errors), records=records),
                  criteria=criteria, conclusion="PASS" if result.wasSuccessful() else "FAIL",
                  limits=["合成产品线仓与合成 Host；无真实模型、真实 push/merge 或生产数据", "生产 Runtime 接线、J-03、J-07 与真实任务保持 NOT_RUN",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t0 offline acceptance report", "", f"conclusion: {report['conclusion']} · tests {report['tests']['passed']}/{report['tests']['total']} passed", ""]
    lines += ["| AC | subject | result | tests | NOT_RUN |", "| --- | --- | --- | --- | --- |"]
    for ac, c in criteria.items():
        lines.append(f"| {ac} | {c['subject']} | {c['result']} | {len(c['tests'])} | {'; '.join(c['not_run']) or '-'} |")
    (output / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(conclusion=report["conclusion"], tests=report["tests"]["total"], passed=report["tests"]["passed"],
                          criteria={k: v["result"] for k, v in criteria.items()}), ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())
