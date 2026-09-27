#!/usr/bin/env python3
"""artifact_lint.py 的 selftest：每类判定各有正例与负例，三态退出码各有用例；不在工作树留副产物。

调用：python3 mechanisms/artifact-templates/artifact_lint_selftest.py
退出码：0 = 全部用例通过；1 = 至少一条用例失败；2 = selftest 自身无法运行。
正例来源：本单元 proposal/spec/milestones/task/ruling 模板（--template 模式；不覆盖 design）、产品线仓实例区 sdd/ 三件与 tasks/gov-t11/ 现物（实例模式）、
以及本文件内自构的最小实例；负例 = 对最小实例逐项变异，期望恰在指定检查项判红。
实例区由环境变量 HARNESS_INSTANCE_ROOT 指向（含 sdd/ 与 tasks/ 的目录）；未设置时现物正例逐条记为跳过并写明原因，其余用例照常。
"""
import base64
import hashlib
import importlib.util
import os
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.environ.get("HARNESS_INSTANCE_ROOT")
SKIP_REASON = "HARNESS_INSTANCE_ROOT 未设置：现物正例读取产品线仓实例区，本仓不含实例区"


def load():
    spec = importlib.util.spec_from_file_location("artifact_lint", os.path.join(HERE, "artifact_lint.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = load()
TAIL = L.SUBJECT_TAIL

PROPOSAL_MIN = """# X 产品提案（proposal）

> Depends on:
> 无
>
> 权威状态: subject `proposal`%s

## 产品是什么

一句定位。

## 目标用户与问题

## MVP 边界

## MVP 成功条件

## 本提案不决定的事

无

## 反思

### 必须现在定

### 同类潜在 bug 一并封住

### 可接受残留（分级）

无
""" % TAIL

SPEC_MIN = """# X MVP Spec（示例线）

> Depends on:
> `proposal.md@r1`
>
> 权威状态: subject `spec`%s

## 1. 产品目标与用户问题

目标。

## 2. In Scope

- **S-01** 能力甲

## 3. Out of Scope

- **O-01** 情境乙

## 4. Functional Requirements

### 4.1 分组

- **FR-01** 结果可观察

## 5. Non-functional Requirements

- **NFR-01** 同一输入同一结论

## 6. 核心旅程与产品约束

旅程叙述。

- **C-01** 约束

## 7. MVP 整体成功条件

- **SC-1** 条件

## 8. 扩展节

引用 FR-01。

## 9. 本 spec 不决定的事

无

## 10. 反思

### 必须现在定

### 同类潜在 bug 一并防止

### 可接受残留（分级）
""" % TAIL

MILESTONES_MIN = """# X MVP Milestones

> Depends on:
> `spec.md@r1`
>
> 权威状态: subject `milestones-x`%s

## 规划基线

基线。

## Milestone 条目

### M-01 基座

- 阶段目标：形成基座。
- UI 变更：无
- UI lineage：不适用
- 任务清单：
  - gov-t0 布局设计 · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01、NFR-01 · 依赖：无
  - gov-t1 骨架落地 · 类型：治理机制 · Spec 引用：spec.md@r1 FR-01；spec.md@r2 SC-1 · 依赖：gov-t0
  - feature-t0 前端最小页 · 类型：前端 · Spec 引用：spec.md@r1 FR-01 · 依赖：gov-t1 · WITHDRAWN in milestones.md@r2
- 验收条件：
  - 基座可用。

### M-02 后继 · Supersedes：M-01

- 阶段目标：后继。
- UI 变更：有
- UI lineage：ui/x
- 任务清单：
  - design-t0 低保真稿 · 类型：低保真 · Spec 引用：spec.md@r1 S-01 · 依赖：无 · Supersedes：feature-t0
- 验收条件：
  - 稿件在案。

## 跨 Milestone 依赖与调度

M-02 后于 M-01。

## 反思

### 必须现在定

### 同类潜在 bug 一并防止

### 可接受残留（分级）
""" % TAIL

TASK_MIN = """# gov-t3 · 示例任务

> Depends on:
> `milestones.md@r2 gov-t3`
>
> 权威状态: subject `gov-t3-task`%s

## Identity

- Task record ID: `gov-t3`
- Task kind: `governance`
- Definition subject: `gov-t3-task`
- Product line: `x-line`

## 通俗说明（给人读）

本节只帮助人建立心智模型，不是任务契约的权威取值；冲突时以其余正式章节为准。

说明。

## Goal

一个目标。

## Goal Conditions

- 条件一。

## Scope In

- 面甲。

## Scope Out

- 面乙，权威 = spec。

## Constraints

- 上游决定不变。

## Acceptance Criteria

- 结果与证据在案。

## Source References

- Primary source: `milestones.md@r2 gov-t3`
- Spec: `spec.md@r1 FR-01、NFR-01`
- Decision: `D-08@r2`

## Extension: 出生程序

Maps to: Constraints

细化。
""" % TAIL

RULING_MIN = """> Ruling: RU-02
> Date: 2026-09-07
> Type: done
> Object: gov-t3
> Basis: 验收证据 · 定稿 Definition RU-01
> Decision: Owner 指令「判 done」

## 沿革

正文。
"""


def hotfix_task():
    raw = "REG-0001".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    rid = "hotfix-h" + digest
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    text = TASK_MIN.replace("gov-t3", rid).replace("> `milestones.md@r2 %s`" % rid, "> `无`")
    text = text.replace("- Task kind: `governance`", "- Task kind: `hotfix`")
    text = text.replace("- Primary source: `milestones.md@r2 %s`\n- Spec: `spec.md@r1 FR-01、NFR-01`\n- Decision: `D-08@r2`" % rid,
                        "- Primary source: hotfix-registration `%s`\n- Registration byte length: `%d`\n"
                        "- Registration SHA-256: `%s`" % (b64, len(raw), digest))
    return rid, text


class Suite(object):
    def __init__(self, tmp):
        self.tmp, self.failures, self.count, self.skipped = tmp, [], 0, []

    def run(self, label, kind, text, name, expect_state, expect_check=None, template=False, raw=None):
        self.count += 1
        d = tempfile.mkdtemp(dir=self.tmp)
        path = os.path.join(d, name)
        with open(path, "wb") as fh:
            fh.write(raw if raw is not None else text.encode("utf-8"))
        rec = L.lint_file(kind, path, template)
        bad = [c["check"] for c in rec["checks"] if c["state"] != L.PASS]
        ok = rec["state"] == expect_state
        if ok and expect_state == L.PASS and bad:
            ok = False
        if ok and expect_check is not None:
            ok = any(c["check"] == expect_check and c["state"] == expect_state for c in rec["checks"])
        if not ok:
            self.failures.append("%s：期望 %s%s，实际 %s，非通过项 %s" % (
                label, expect_state, ("/" + expect_check) if expect_check else "", rec["state"], bad))

    def skip(self, label, reason):
        self.skipped.append("%s：%s" % (label, reason))

    def run_path(self, label, kind, path, expect_state, template=False):
        self.count += 1
        rec = L.lint_file(kind, path, template)
        bad = [(c["check"], c["findings"]) for c in rec["checks"] if c["state"] != L.PASS]
        if rec["state"] != expect_state or (expect_state == L.PASS and bad):
            self.failures.append("%s：期望 %s，实际 %s，%s" % (label, expect_state, rec["state"], bad))


def main():
    P, V, N = L.PASS, L.VIOLATION, L.NOT_CHECKED
    with tempfile.TemporaryDirectory() as tmp:
        s = Suite(tmp)
        # ---- 正例：既有生命周期模板、本仓现物、最小实例
        for k in L.KINDS:
            s.run_path("模板 %s" % k, k, os.path.join(HERE, "%s.template.md" % k), P, template=True)
        for k, rel in (("proposal", "sdd/proposal.md"), ("spec", "sdd/spec.md"), ("milestones", "sdd/milestones.md"),
                       ("task", "tasks/gov-t11/gov-t11.md"),
                       ("ruling", "tasks/gov-t11/rulings/RU-01-task-definition-finalization.md"),
                       ("ruling", "tasks/gov-t11/rulings/RU-02-close.md")):
            if INSTANCE:
                s.run_path("现物 %s" % rel, k, os.path.join(INSTANCE, rel), P)
            else:
                s.skip("现物 %s" % rel, SKIP_REASON)
        s.run("最小 proposal", "proposal", PROPOSAL_MIN, "proposal.md", P)
        s.run("最小 spec", "spec", SPEC_MIN, "spec.md", P)
        s.run("最小 milestones", "milestones", MILESTONES_MIN, "milestones.md", P)
        s.run("最小 task", "task", TASK_MIN, "gov-t3.md", P)
        hid, htext = hotfix_task()
        s.run("最小 hotfix task", "task", htext, hid + ".md", P)
        s.run("最小 ruling", "ruling", RULING_MIN, "RU-02-done.md", P)
        s.run("proposal 不编号 + 扩展 H2", "proposal",
              PROPOSAL_MIN.replace("## MVP 边界", "## 背景\n\n## MVP 边界"), "proposal.md", P)

        # ---- 负例：physical
        s.run("proposal CRLF", "proposal", None, "proposal.md", V, "physical", raw=PROPOSAL_MIN.replace("\n", "\r\n").encode("utf-8"))
        s.run("spec 末尾无 LF", "spec", SPEC_MIN.rstrip("\n"), "spec.md", V, "physical")
        s.run("task 残留引导块", "task", TASK_MIN.replace("## Goal\n", "## Goal\n\n<!-- template:guide\n x\n-->\n"), "gov-t3.md", V, "physical")
        s.run("milestones 残留占位", "milestones", MILESTONES_MIN.replace("gov-t1 骨架落地", "gov-t1 <非空规划目标>"), "milestones.md", V, "physical")
        # ---- 负例：header
        s.run("proposal Depends on 非 无", "proposal", PROPOSAL_MIN.replace("> 无", "> `spec.md@r1`"), "proposal.md", V, "header")
        s.run("proposal 页首插入状态行", "proposal", PROPOSAL_MIN.replace("%s\n" % TAIL, "%s\n> Status: FROZEN\n" % TAIL), "proposal.md", V, "header")
        s.run("spec Depends on 缺 @rN", "spec", SPEC_MIN.replace("`proposal.md@r1`", "`proposal.md`"), "spec.md", V, "header")
        s.run("spec subject 错", "spec", SPEC_MIN.replace("subject `spec`", "subject `spec-fused`"), "spec.md", V, "header")
        s.run("milestones subject 非法", "milestones", MILESTONES_MIN.replace("`milestones-x`", "`Milestones_X`"), "milestones.md", V, "header")
        s.run("task H1 ID 非法", "task", TASK_MIN.replace("# gov-t3 ·", "# gov-t03 ·"), "gov-t03.md", V, "header")
        s.run("task 依赖 task-id 不等 H1", "task", TASK_MIN.replace("`milestones.md@r2 gov-t3`", "`milestones.md@r2 gov-t4`", 1), "gov-t3.md", V, "header")
        s.run("ruling Type 越闭集", "ruling", RULING_MIN.replace("> Type: done", "> Type: approved"), "RU-02-done.md", V, "header")
        s.run("ruling Date 非法", "ruling", RULING_MIN.replace("2026-09-07", "2026-13-01"), "RU-02-done.md", V, "header")
        s.run("ruling 缺 Basis 行", "ruling", RULING_MIN.replace("> Basis: 验收证据 · 定稿 Definition RU-01\n", ""), "RU-02-done.md", V, "header")
        # ---- 负例：headings
        s.run("proposal 缺核心 H2", "proposal", PROPOSAL_MIN.replace("## MVP 成功条件\n\n", ""), "proposal.md", V, "headings")
        s.run("proposal 编号不一致", "proposal", PROPOSAL_MIN.replace("## 产品是什么", "## 1. 产品是什么"), "proposal.md", V, "headings")
        s.run("proposal 缺反思 H3", "proposal", PROPOSAL_MIN.replace("### 同类潜在 bug 一并封住\n\n", ""), "proposal.md", V, "headings")
        s.run("spec 核心 H2 乱序", "spec", SPEC_MIN.replace("## 2. In Scope\n\n- **S-01** 能力甲\n\n## 3. Out of Scope\n\n- **O-01** 情境乙",
                                                     "## 2. Out of Scope\n\n- **O-01** 情境乙\n\n## 3. In Scope\n\n- **S-01** 能力甲"), "spec.md", V, "headings")
        s.run("spec 扩展 H2 冒充核心", "spec", SPEC_MIN.replace("## 8. 扩展节", "## 8. In Scope（补充）"), "spec.md", V, "headings")
        s.run("milestones 扩展 H2", "milestones", MILESTONES_MIN.replace("## 反思", "## 任务总览\n\n## 反思"), "milestones.md", V, "headings")
        s.run("milestones 规划基线内 H3", "milestones", MILESTONES_MIN.replace("基线。", "### 子节\n\n基线。"), "milestones.md", V, "headings")
        s.run("task H2 缺一", "task", TASK_MIN.replace("## Constraints\n\n- 上游决定不变。\n\n", ""), "gov-t3.md", V, "headings")
        s.run("task 通俗说明首段不逐字", "task", TASK_MIN.replace("本节只帮助人建立心智模型", "本节帮助人建立心智模型"), "gov-t3.md", V, "headings")
        s.run("task Scope Out 空", "task", TASK_MIN.replace("- 面乙，权威 = spec。\n", ""), "gov-t3.md", V, "headings")
        s.run("task Extension 缺 Maps to", "task", TASK_MIN.replace("Maps to: Constraints\n\n", ""), "gov-t3.md", V, "headings")
        # ---- 负例：ids
        s.run("spec FR 定义在 In Scope", "spec", SPEC_MIN.replace("- **S-01** 能力甲", "- **S-01** 能力甲\n- **FR-09** 越域"), "spec.md", V, "ids")
        s.run("spec ID 重复", "spec", SPEC_MIN.replace("- **FR-01** 结果可观察", "- **FR-01** 结果可观察\n- **FR-01** 重复"), "spec.md", V, "ids")
        s.run("spec 同族同值", "spec", SPEC_MIN.replace("- **FR-01** 结果可观察", "- **FR-01** 结果可观察\n- **FR-1** 冲突"), "spec.md", V, "ids")
        s.run("spec In Scope 顶层条目无 ID", "spec", SPEC_MIN.replace("- **S-01** 能力甲", "- **S-01** 能力甲\n- 无 ID 条目"), "spec.md", V, "ids")
        s.run("milestones 类型前缀不配", "milestones", MILESTONES_MIN.replace("gov-t0 布局设计 · 类型：治理机制", "gov-t0 布局设计 · 类型：前端"), "milestones.md", V, "ids")
        s.run("milestones 依赖未定义", "milestones", MILESTONES_MIN.replace("· 依赖：gov-t0\n", "· 依赖：gov-t9\n"), "milestones.md", V, "ids")
        s.run("milestones 族编号空洞", "milestones", MILESTONES_MIN.replace("gov-t1 骨架落地", "gov-t2 骨架落地"), "milestones.md", V, "ids")
        s.run("milestones 缺固定字段", "milestones", MILESTONES_MIN.replace("- UI lineage：不适用\n", "", 1), "milestones.md", V, "ids")
        s.run("milestones Spec 引用裸 ID", "milestones", MILESTONES_MIN.replace("Spec 引用：spec.md@r1 S-01", "Spec 引用：S-01"), "milestones.md", V, "ids")
        s.run("milestones M-ID 数值冲突", "milestones", MILESTONES_MIN.replace("### M-02 后继", "### M-1 后继"), "milestones.md", V, "ids")
        s.run("task 文件名 stem 不等 ID", "task", TASK_MIN, "gov-t4.md", V, "ids")
        s.run("task kind 与前缀不配", "task", TASK_MIN.replace("- Task kind: `governance`", "- Task kind: `feature`"), "gov-t3.md", V, "ids")
        s.run("task Primary source 不等页首", "task", TASK_MIN.replace("- Primary source: `milestones.md@r2 gov-t3`", "- Primary source: `milestones.md@r3 gov-t3`"), "gov-t3.md", V, "ids")
        s.run("hotfix SHA 不符", "task", htext.replace("- Registration byte length: `8`", "- Registration byte length: `9`"), hid + ".md", V, "ids")
        s.run("ruling 文件名编号不等页首", "ruling", RULING_MIN, "RU-03-done.md", V, "ids")
        s.run("ruling slug 非法", "ruling", RULING_MIN, "RU-02-Done.md", V, "ids")
        # ---- 负例：lifecycle
        s.run("proposal 正文状态行", "proposal", PROPOSAL_MIN.replace("一句定位。", "一句定位。\n\n> Status: DRAFT"), "proposal.md", V, "lifecycle")
        s.run("spec 正文 Revision 行", "spec", SPEC_MIN.replace("目标。", "目标。\n\n> Revision: r2"), "spec.md", V, "lifecycle")
        s.run("milestones 正文 Freeze 行", "milestones", MILESTONES_MIN.replace("基线。", "基线。\n\n> Freeze: 2026-01-01"), "milestones.md", V, "lifecycle")
        s.run("task 正文 Branch 行", "task", TASK_MIN.replace("说明。", "说明。\n\n> Branch: main"), "gov-t3.md", V, "lifecycle")
        # ---- 负例：模板剥离等式
        for k in L.KINDS:
            with open(os.path.join(HERE, "%s.template.md" % k), encoding="utf-8") as fh:
                t = fh.read()
            head = "\n## " if k != "ruling" else "> Object:"  # 行首匹配，避免命中引导块内的文字
            s.run("模板 %s 骨架漂移" % k, k, t.replace(head, head + "X", 1), "%s.template.md" % k, V, "strip", template=True)
            s.run("模板 %s 状态 token" % k, k, t.replace("-->", "Status\n-->", 1), "%s.template.md" % k, V, "lifecycle", template=True)
        # ---- 未查成
        s.run("围栏未闭合", "spec", SPEC_MIN.replace("目标。", "目标。\n\n```text\n未闭合"), "spec.md", N)
        s.run("非 UTF-8", "proposal", None, "proposal.md", N, raw=b"# \xff\xfe\n")
        s.run_path("文件不存在", "ruling", os.path.join(tmp, "missing", "RU-01-x.md"), N)
        # ---- 无副产物
        leftovers = [n for n in os.listdir(HERE) if n == "__pycache__"]
        if leftovers:
            s.failures.append("工作树副产物：%s" % leftovers)
    for line in s.failures:
        sys.stdout.write("FAIL %s\n" % line)
    for line in s.skipped:
        sys.stdout.write("SKIP %s\n" % line)
    sys.stdout.write("[artifact-lint selftest] %d 条用例，%d 条失败，%d 条跳过\n" % (s.count, len(s.failures), len(s.skipped)))
    return 1 if s.failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        sys.stderr.write("[artifact-lint selftest] NOT_CHECKED：%s：%s\n" % (type(exc).__name__, exc))
        sys.exit(2)
