"""自测声明：review_channel_taskbook（第 5 类：确定性、十节、r1 改动区、差异统计、上一轮 finding 与决定摘要、任务书行不列哈希）。"""
import review_channel_contract as C
import review_channel_taskbook as T


def _ctx(previous=None, stage="impl", changed_region=None):
    req = {"subject": "demo", "stage": stage, "round": "r2" if previous else "r1", "task_record": "gov-t1",
           "review_brief": {"background": "BG", "check_surfaces": "CS", "evidence_limits": [{"reference": "x", "reason": "r"}],
                            "accepted_residuals": [{"id": "RES-1", "text": "ok"}],
                            "remediation_statement": "fixed" if previous else None}}
    pre = [{"bundle_name": "c.md", "role": "candidate", "bytes": 3, "sha256": "a" * 64, "source": "c.md"},
           {"bundle_name": "r.md", "role": "reference", "bytes": 4, "sha256": "b" * 64, "source": "r.md"}]
    return {"request": req, "routing": {}, "pre_manifest": pre, "candidate": pre[0],
            "eligibility": {"author_vendors": ["Anthropic"], "reviewer_vendor": "DeepSeek"},
            "profile": {"provider": "p", "model": "m", "transport": "chat", "runtime": "fake", "effort": "high",
                        "effort_source": "registry-default", "selection_source": "system-default", "changed_from_previous": None, "previous": None},
            "verdict_path": "reviews/demo/r1/v.md", "channel": {"id": C.CHANNEL_ID, "design_sha256": "d" * 64},
            "previous": previous, "references": [{"token": "x", "status": "exempt", "reason": "r", "path": None}],
            "budget": {"round_index": 1, "allowed_rounds": 2, "max_rounds": 2, "source": "default", "extensions_added": 0, "submitted_rounds": 0},
            "authorization": "t:OD-01", "task_file": "T.md",
            "changed_region": changed_region if changed_region is not None else [{"bundle_name": "c.md", "baseline": None, "diff": None, "note": None}]}


def deterministic_and_sections(e):
    ctx = _ctx()
    a = T.render(ctx)
    b = T.render(ctx)
    e.check(a == b, "byte-identical re-render")
    text = a.decode("utf-8")
    for n in range(1, 11):
        e.check("## %d. " % n in text, "section %d present" % n)
    e.check("| review-task | `T.md` | — | — |" in text, "task file row has no bytes / hash")
    e.check("`c.md` | 3 | `aaaaaaaaaaaa` |" in text, "candidate row lists bytes and 12-char prefix")
    # 第 8 节 = 该 stage 五题闭集（§6.4，Amendment 4），题号与题文由常量渲染、次序即常量次序
    sec8 = text.split("## 8. 问题集")[1].split("## 9.")[0]
    e.check(all(("- **%s**：%s" % (q, t)) in sec8 for q, t in C.IMPL_QUESTIONS) and "STD-" not in text and "Q1" not in sec8,
            "impl round: five fixed questions, no caller questions, no standard-question wording")
    idx = [sec8.index("**%s**" % q) for q, _t in C.IMPL_QUESTIONS]
    e.check(idx == sorted(idx), "questions rendered in the constant order")
    t_task = T.render(_ctx(stage="task")).decode("utf-8").split("## 8. 问题集")[1].split("## 9.")[0]
    e.check(all(("**%s**" % q) in t_task for q, _t in C.TASK_QUESTIONS) and "Q-CHANGE" not in t_task, "task round: FR-21 five questions")
    e.check("RES-1" in text and "评审方 ∉ 作者集合" in text, "r1 sections")
    e.check("verdict_schema" not in text and "机读块字段" not in text and "question_assessments" not in text, "verdict format contract absent from the task book")
    # 第 3 节 r1 改动区（§6.2 第 6 条，Amendment 4）：首冻 → 整件为改动区；在案 → 基线修订号、SHA-256 与差异块；记录无机械正本 → note
    sec3 = text.split("## 3. 改动区、整改声明与决定摘要")[1].split("## 4.")[0]
    e.check("### 改动区（通道算）" in sec3 and "无现行冻结事实（首冻）：整件为改动区" in sec3 and "整改声明" not in sec3 and "决定摘要" not in sec3
            and "unchanged_region" in sec3, "r1 first-freeze: whole file is the changed region; no remediation / decisions subsections")
    diff = T.diff_summary("a\nb\n", "a\nB\n")
    t_base = T.render(_ctx(changed_region=[{"bundle_name": "c.md", "baseline": {"revision": 4, "sha256": "f" * 64}, "diff": diff, "note": None}])).decode("utf-8")
    e.check("现行冻结事实 r4 · SHA-256 `%s`" % ("f" * 64) in t_base and "+1 / -1 行" in t_base and "replace: baseline lines 2-2 -> candidate lines 2-2" in t_base,
            "r1 baseline from the current freeze fact with hunks: %s" % t_base.split("## 3.")[1].split("## 4.")[0])
    t_note = T.render(_ctx(changed_region=[{"bundle_name": "c.md", "baseline": None, "diff": None, "note": "现行冻结事实 r5 的记录不含机械正本（雏形形制），基线身份不可得"}])).decode("utf-8")
    e.check("现行冻结事实 r5 的记录不含机械正本（雏形形制），基线身份不可得：整件为改动区" in t_note, "r1 prototype record: note rendered, whole file is the changed region")
    two = _ctx(changed_region=[{"bundle_name": "c.md", "baseline": None, "diff": None, "note": None}, {"bundle_name": "d.md", "baseline": {"revision": None, "sha256": "e" * 64}, "diff": diff, "note": None}])
    t_two = T.render(two).decode("utf-8")
    e.check("#### 候选 `c.md`" in t_two and "#### 候选 `d.md`" in t_two and "现行冻结事实 （修订号不可得） · SHA-256" in t_two, "multi-candidate r1: one subsection per candidate")


def current_revision_annotation(e):
    """§6.3 第 5 节：域一引用并列标注引用修订号与该件现行修订号（freeze-record 设计 §4.3 读取；只标注、不判失败码）；
    现行修订号不可得时标「不可得」；已退役的档案库时代修订指称与锁值引用件分类不再渲染。"""
    ctx = _ctx()
    ctx["references"] = [{"token": "spec.md", "status": "delivered", "domain": "one", "path": "sdd/spec.md",
                          "revision": 4, "current_revision": 5, "reason": None},
                         {"token": "milestones.md", "status": "delivered", "domain": "one", "path": "sdd/milestones.md",
                          "revision": 11, "current_revision": 11, "reason": None},
                         {"token": "proposal.md", "status": "delivered", "domain": "one", "path": "sdd/proposal.md",
                          "revision": 2, "current_revision": None, "reason": None}]
    text = T.render(ctx).decode("utf-8")
    lines = {ln.split("`")[1]: ln for ln in text.splitlines() if ln.startswith("- `")}
    e.check("引用修订号 r4" in lines["spec.md"] and "该件现行修订号 r5" in lines["spec.md"] and "引用修订号非现行" in lines["spec.md"],
            "non-current cited revision: both revisions listed and the staleness note present: %s" % lines["spec.md"])
    e.check("引用修订号 r11" in lines["milestones.md"] and "该件现行修订号 r11" in lines["milestones.md"] and "非现行" not in lines["milestones.md"],
            "current cited revision: no staleness note: %s" % lines["milestones.md"])
    e.check("该件现行修订号 不可得" in lines["proposal.md"] and "引用修订号 r2" in lines["proposal.md"],
            "unobtainable current revision is annotated, never a failure: %s" % lines["proposal.md"])
    e.check("档案库时代修订指称" not in text and "锁值引用件" not in text and "最早在案修订号" not in text,
            "retired classifications are not rendered")


def previous_round_sections(e):
    diff = T.diff_summary("a\nb\nc\n", "a\nB\nc\nd\n")
    e.check(diff["added"] == 2 and diff["removed"] == 1 and len(diff["hunks"]) == 2, "diff statistics: %s" % diff)
    prev = {"findings": [{"id": "R1-B1", "severity": "blocking", "title": "t1"}, {"id": "R1-N1", "severity": "non_blocking", "title": "t2"}],
            "verdict": "FAIL", "diff": diff, "profile_same": False,
            "decisions": [("R1-B1", "blocking", "t1", "fix", "do this", ""), ("R1-N1", "non_blocking", "t2", "skip", "", "repo:KB-09")]}
    text = T.render(_ctx(prev)).decode("utf-8")
    e.check("### 整改声明" in text and "fixed" in text, "remediation statement")
    e.check("+2 / -1 行" in text and "`R1-B1` · blocking · t1" in text and "`R1-N1`" in text and "基线: 上一轮候选" in text, "diff and previous findings listed")
    e.check("### 上一轮决定摘要" in text and "- `R1-B1` · blocking · t1 → fix · do this" in text and "- `R1-N1` · non_blocking · t2 → skip · repo:KB-09" in text,
            "decision summary rows rendered from decisions.json (§6.12)")
    e.check("不同（显式改选）" in text, "profile change noted")
    e.check("首冻" not in text, "r2 has no first-freeze declaration")


def cases():
    return [
        ("taskbook.deterministic-sections", deterministic_and_sections),
        ("taskbook.current-revision-annotation", current_revision_annotation),
        ("taskbook.previous-round", previous_round_sections),
    ]
