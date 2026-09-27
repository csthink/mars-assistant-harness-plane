"""Offline acceptance report for feature-t5: runs test_budget and test_validation and maps results to AC-01..AC-11.

Usage: python run_validation_report.py --output <new directory> [--cases <new directory outside every worktree>]
The output directory must not exist; it receives unittest.log, report.json and report.md. Per-test synthetic
product lines (Git repositories) go to --cases when given, otherwise to a temporary directory that is removed
after the persistent state of every product line has been read into the report.

PASS/FAIL derive from the recorded test results. A unittest ERROR (the test could not reach its assertion) is
never counted as product PASS or FAIL: the erroring test is re-run once in a fresh directory, both runs are
recorded with their durations, and the criterion takes the re-run's outcome; an ERROR that persists leaves the
criterion NOT_RUN. feature-t3 (Definition loop, execution layer, port factory), feature-t4 (Implement and
Verify loop) and feature-t6 (Policy Gate and its execution callback) are the real implementations. The
reviewer output, the Definition-loop review callback, the Host and the Agent program are explicitly
SYNTHETIC. Real model, real reviewer, J-03, J-04 real qualification, J-05, J-06 real Host and J-07 stay NOT_RUN.
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
MODULES = ("test_budget", "test_validation")
SOURCES = [
    "hp.py", "requirements.lock", "domain/core.py", "domain/store.py",
    "domain/budget/__init__.py", "domain/budget/commands.py", "domain/budget/configuration.py",
    "domain/budget/ledger.py", "domain/budget/projection.py", "domain/budget/results.py", "domain/budget/schema.py",
    "domain/validation/__init__.py", "domain/validation/commands.py", "domain/validation/config.py",
    "domain/validation/dispatch.py", "domain/validation/gate.py", "domain/validation/materials.py",
    "domain/validation/projection.py", "domain/validation/records.py", "domain/validation/results.py",
    "domain/validation/review.py", "domain/validation/schema.py", "domain/validation/verdict.py",
    "domain/policy/rules.py", "domain/policy/results.py", "domain/policy/items.py", "domain/policy/evaluate.py",
    "domain/policy/authorize.py", "domain/policy/inputs.py",
    "domain/implement_verify/dispatch.py", "domain/implement_verify/commands.py", "domain/implement_verify/executors.py",
    "domain/implement_verify/verify.py", "domain/implement_verify/assessment.py",
    "domain/definition/dispatch.py", "domain/definition/commands.py", "domain/definition/rulings.py",
    "domain/workflow/progression.py", "domain/workflow/recovery.py", "domain/workflow/reservations.py",
    "runtime/executions.py", "runtime/dispatcher.py", "runtime/main.py",
    "execution/host.py", "execution/local.py", "execution/port.py", "execution/bridge.py",
    "cli/main.py", "cli/validation.py",
    "tests/product_line.py", "tests/definition_fixture.py", "tests/implement_verify_fixture.py",
    "tests/validation_fixture.py", "tests/validation_stdio.py", "tests/guarded_walk.py", "tests/host_driver.py",
    "tests/test_budget.py", "tests/test_validation.py", "tests/run_validation_report.py",
]
INPUTS = [
    "mechanisms/delivery-method/MVP_Workflow_v5.drawio",
    "mechanisms/review-channel/review_channel_registry.json",
    "mechanisms/artifact-templates/artifact_lint.py",
    "tasks/feature-t5/feature-t5.md",
    "tasks/feature-t5/rulings/RU-01-definition-review-skip.md",
    "tasks/feature-t5/rulings/RU-02-definition-finalization.md",
    "records/diagnostics/feature-t5/2026-09-23/inputs.json",
    "records/diagnostics/feature-t4/2026-09-23/inputs/assistant/docs/design/evidence/host-execution-facts-j06/"
    "physical-execution.stopping.json",
]
TOPOLOGY = "mechanisms/delivery-method/MVP_Workflow_v5.drawio"
CRITERIA = {
    "AC-01": "拓扑与推进（通用命令收窄，拓扑正本不变）",
    "AC-02": "预算判定事实形状（Assistant KB-264）",
    "AC-03": "显式配置与机械可判",
    "AC-04": "三处额度的机械演练",
    "AC-05": "Validate Change 配置判定",
    "AC-06": "变更评审派发与授权（FR-62）",
    "AC-07": "evidence-backed Verdict（FR-24）",
    "AC-08": "Host 取消与基础设施失败不伪装 Reviewer FAIL",
    "AC-09": "Validation escalation（FR-26）",
    "AC-10": "两入口等价",
    "AC-11": "验收报告与后继边界",
}
NOT_RUN = {
    "AC-06": ["真实评审方与真实提供方调用（impl 轮判词由明确标注的合成评审方给出）", "嵌入端口 J-04 真实资格"],
    "AC-08": ["J-06 真实 Host 联调（停止未确认形态取 feature-t4 固定的 J-06 样例）"],
    "AC-10": ["真实 Assistant Host（serve-stdio 为产品入口真实进程，Host 为合成测试驱动）"],
    "AC-11": ["真实模型调用", "真实评审方的 impl 轮跨模型提供方评审", "J-03", "J-04 真实资格", "J-05", "J-06 真实 Host 联调",
              "J-07"],
}
ALIGNMENT = [
    "额度取窗口起点生效的配置；窗口起点时尚无配置时取窗口起点之后首次写入的配置（grant.selection 记 "
    "first-configured-after-window-start），使「补齐配置后重新判定可推进」（AC-03）成立，窗口进行中的再次改配置仍不改变该窗口额度",
    "Continue 之后：CLI 经 feature-t4 implement dispatch 在 N-VALIDATE-CONTINUE 取 E-V13 与 E-V08；Runtime 入口另有本任务 "
    "validate.resume（仅取 E-V13），因为 feature-t4 的 Runtime 投影只在 N-VERIFY-CONTINUE 列出 implement.dispatch",
    "评审在提供方调用前被拒（preflight_failed：被审材料字节不符、执行授权拒绝或不可判定、评审通道 preflight 拒绝）时执行已确定结束，"
    "以 refused-before-release 执行事实结算预约；其余执行失败有 Receipt 时以 Receipt 结算，无 Receipt 的执行失败与不确定保持预约",
    "impl 轮号只随已交付判词前进：执行失败后重派沿用同一轮号、attempt 序号递增（评审通道 r2 起要求 previous_round）",
]
CONSUMERS = {
    "feature-t3": "已合入并使用真实实现：Definition 环经本任务 budget-decide 在 N-DEF-BUDGET-DECISION 推进 E-D11 / E-D10；"
                  "评审执行层、build_port 与 ruling_executor 复用；read_published 以 stage=\"impl\" 读取 impl 轮判词与 Receipt",
    "feature-t4": "已合入并使用真实实现：verification-budget 的 Policy Gate ALLOW 记录由 commands.remediate 消费并沿 E-I08 / E-I10 推进；"
                  "实施派发接受 N-VALIDATE-REMEDIATION-DISPATCH（E-V08）与 N-VALIDATE-CONTINUE（E-V13），remediation 输入取上一轮 "
                  "Validation 判词与 Findings",
    "feature-t6": "已合入并使用真实实现：三类预算评估对象以独立规则表评估（BUDGET_RULE_SET_DIGEST），既有 RULE_SET_DIGEST 不变；"
                  "评审放行以 review-release、对象 kind candidate-change 调用 execution_authorizer",
    "feature-t7": "经 E-V12 到达 Publish 的带保留接受决定不含 publishBinding，push-permit 判定为 PUSH_AUTHORIZATION_MISSING（fail-closed）；"
                  "Publish 绑定取判词绑定的候选提交还是含裁定提交的分支 HEAD 由 feature-t7 决定，本任务两者都记录；"
                  "Publish 授权语境视图为 domain/validation/records.publish_context(state, task_id)",
    "feature-t15": "治理日志消费 validateChange 台账、预算判定记录与 Progression Commit 序列",
    "feature-t18": "bundle 与安装不在本任务",
    "feature-t19": "切片仓接入不在本任务",
}
UNDELIVERED = [
    "Validate Change 开关的缺省值与运行中改开关的入口（缺省关，Assistant OD-388）",
    "archive-v1 评审证据模式的判词回读（沿用 feature-t3 限制，结算为不确定）",
    "逐条 Goal Conditions 的结构化评估字段（须评审通道 amendment）",
    "Publish 授权与 publishBinding（feature-t7）",
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
        facts = (inst.get("facts") or {}).values()
        tasks[task_id] = dict(lifecycle=inst.get("lifecycle"), position=inst.get("position"), condition=inst.get("condition"),
                              runtimeVersion=inst.get("runtimeVersion"), commits=len(inst.get("commits") or []),
                              budgetDecisions=[dict(subject=f["purpose"], conclusion=f["payload"].get("conclusion"),
                                                    outcome=f["payload"].get("outcome"))
                                               for f in facts if f.get("kind") == "policy-decision"
                                               and f.get("purpose", "").endswith("-budget")],
                              validationRounds=len(((task.get("validateChange") or {}).get("rounds")) or []))
    return dict(commit=commit, domainRevision=state.get("revision"), sha256=hashlib.sha256(raw.encode()).hexdigest(),
                tasks=tasks)


def product_lines(directory):
    """Every synthetic product line under one test directory with its runtime ref: state before and after, edges."""
    found = []
    for gitdir in sorted(Path(directory).rglob(".git")):
        if not gitdir.is_dir():
            continue  # a task worktree shares its product line's refs
        repo = gitdir.parent
        chain = (git("-C", str(repo), "rev-list", "--reverse", "refs/harness/runtime") or "").split()
        if not chain:
            continue
        after = state_at(repo, chain[-1])
        raw = git("-C", str(repo), "show", chain[-1] + ":state.json")
        edges = {}
        for task_id, task in sorted((json.loads(raw).get("tasks") or {}).items()):
            commits = (task.get("workflowInstance") or {}).get("commits") or []
            edges[task_id] = [c["selectedEdge"] for c in commits if c.get("selectedEdge")]
        found.append(dict(repository=str(repo.relative_to(directory)), runtimeRefCommits=len(chain),
                          before=state_at(repo, chain[0]), after=after, process=dict(selectedEdges=edges)))
    return found


def states_by_test(cases, records):
    out = {}
    for record in records:
        name = record["test"].rsplit(".", 1)[-1]
        module = record["test"].split(".", 1)[0]
        prefix = "t5-" if module == "test_budget" else "t5v-"
        directory = Path(cases) / (prefix + name)
        out[record["test"]] = product_lines(directory) if directory.is_dir() else []
    return out


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
        temp = tempfile.TemporaryDirectory(prefix="hp-t5-report-cases-")
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
    final = {r["test"]: r for r in records}
    for r in reruns:
        final[r["test"]] = r
    finals = list(final.values())
    criteria = {}
    for ac, subject in CRITERIA.items():
        if ac == "AC-11":
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
        if ac == "AC-01" and before[TOPOLOGY] != after[TOPOLOGY]:
            result_ac = "FAIL"
        criteria[ac] = dict(subject=subject, result=result_ac, tests=[dict(test=r["test"], outcome=r["outcome"],
                                                                          seconds=r["seconds"]) for r in tests],
                            failed=[r["test"] for r in tests if r["outcome"] == "FAIL"],
                            errors=[r["test"] for r in tests if r["outcome"] == "ERROR"],
                            not_run=NOT_RUN.get(ac, []))
    # A test that builds no product line has an empty list; every test must still have been looked up.
    complete = all(c["tests"] for c in criteria.values()) and before == after and all(r["test"] in states for r in records)
    criteria["AC-11"] = dict(subject=CRITERIA["AC-11"], result="PASS" if complete else "FAIL", tests=[], failed=[], errors=[],
                             not_run=NOT_RUN["AC-11"],
                             basis="本报告逐条列出 AC-01 至 AC-10 的结论与测试标识、固定输入前后身份、每个测试的合成产品线"
                                   "持久状态前后与推进边序列、源码与依赖与环境身份、后继任务消费约束、未交付范围与 NOT_RUN 项")
    report = dict(kind="feature-t5-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  environment=environment(), sources={p: identity(APP / p) for p in SOURCES},
                  inputs=dict(before=before, after=after, unchanged=before == after),
                  standins=dict(label="SYNTHETIC reviewer output, Definition-loop review callback, Host and Agent program",
                                synthetic=["validation_fixture.SyntheticImplReviewer (impl-round verdicts and failure classes)",
                                           "definition_fixture.SyntheticReviewer and synthetic_authorizer (Definition loop "
                                           "drill; one not-determinable review callback case)",
                                           "implement_verify_fixture.SyntheticAgent (implementation commits)",
                                           "validation_stdio.ValidationHost (Host side of the real serve-stdio process)",
                                           "guarded_walk (other-task tests walking the narrowed nodes directly)"],
                                real=["feature-t6 Policy Gate (budget subjects and review-release) and execution_authorizer",
                                      "feature-t4 Implement / Verify loop and commands.remediate",
                                      "feature-t3 Definition loop, execution layer, build_port and ruling_executor",
                                      "feature-t17 execution port preflight and ProductReview",
                                      "product serve-stdio entry (runtime.main)"]),
                  cases=dict(retained=args.cases is not None, path=str(cases) if args.cases is not None else None),
                  tests=dict(total=len(finals), passed=sum(r["outcome"] == "PASS" for r in finals),
                             failed=sum(r["outcome"] == "FAIL" for r in finals),
                             errors=sum(r["outcome"] == "ERROR" for r in finals),
                             run1=dict(total=result.testsRun, failed=len(result.failures), errors=len(result.errors)),
                             seconds=total_seconds, records=records, reruns=reruns),
                  persistentState=states, criteria=criteria, alignment=ALIGNMENT, consumers=CONSUMERS,
                  undelivered=UNDELIVERED,
                  conclusion="PASS" if all(c["result"] == "PASS" for c in criteria.values()) else "FAIL",
                  limits=["合成产品线仓、合成评审方输出、合成 Host 与合成 Agent 程序；无真实模型、真实评审方、真实 push/merge 或生产数据",
                          "feature-t3、feature-t4、feature-t6 与 feature-t17 为真实实现",
                          "产品测试通过不产生 Human done、发布或双方接收决定"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# feature-t5 offline acceptance report", "",
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
    lines += ["", "## 施工对齐（见 design「施工对齐记录」）", ""] + ["- " + a for a in ALIGNMENT]
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
