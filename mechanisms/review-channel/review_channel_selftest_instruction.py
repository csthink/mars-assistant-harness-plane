"""自测声明：review_channel_instruction（第 6 类：契约文本含全部字段名与闭集、五题闭集、机读块在前、规则 14；三种指令形态各异）。"""
import review_channel_contract as C
import review_channel_instruction as N


def _ctx(delivery="tool", prev=None, stage="impl"):
    return {"task_file": "T.md", "stage": stage, "required_question_ids": C.required_question_ids(stage), "round_tag": "r2",
            "previous_finding_ids": prev, "residual_ids": ["RES-1"], "delivery": delivery}


def contract_text(e):
    text = N.review_instruction(_ctx(prev=["R1-B1"]))
    for field in C.VERDICT_FIELDS:
        e.check(field in text, "field name %s injected" % field)
    for closed in (C.ASSESSMENTS, C.SEVERITIES, C.ORIGINS, C.DISPOSITIONS):
        for v in closed:
            e.check(v in text, "closed set value %s injected" % v)
    # 五题闭集注入（V4）：task / impl 两套各恰五题、题号与题文在场、字段行题号集合恰为五题、无已退役的断言成员
    for stage in C.STAGES:
        t = N.review_instruction(_ctx(stage=stage))
        ids = C.required_question_ids(stage)
        e.check(all(("%s：%s" % (q, txt)) in t for q, txt in C.QUESTIONS_BY_STAGE[stage]), "%s round: five questions with their text injected" % stage)
        qa_line = [ln for ln in t.split("\n") if ln.startswith("- question_assessments:")][0]
        e.check(("题号集合必须恰为本 stage 的五题闭集：%s（" % ", ".join(ids)) in qa_line and "exhaust" not in t and "STD-" not in t and "常设" not in t,
                "%s round: field line names exactly the five ids; retired members and standard-question wording absent" % stage)
        other = [q for q in C.required_question_ids("impl" if stage == "task" else "task") if q not in ids]
        e.check(all(("- %s: " % q) not in t for q in other), "%s round: the other stage's ids are not in the skeleton" % stage)
    e.check("机读块在前" in text or "以机读块开头" in text, "block-first requirement")
    e.check("unchanged_region" in text and "规则 14" in text and "不得为 blocking" in text, "rule 14 and the changed-region default injected")
    e.check("R2-B<n>" in text and "R1-B1" in text and "RES-1" in text, "round grammar, previous ids and residual ids")
    e.check("raw HTML" in text and "**Verdict: PASS|FAIL**" in text and "## Question assessments" in text, "narrative conventions and HTML ban")
    e.check(C.VERDICT_SCHEMA in text and C.FENCE_INFO in text, "schema id and fence info")
    e.check("machine" not in text, "tool path does not mention the wrapper")
    inline = N.review_instruction(_ctx(delivery="inline"))
    e.check('"machine"' in inline and '"narrative"' in inline and "必须为空数组" in inline, "inline path: wrapper and empty tools_used")
    e.check(N.review_instruction(_ctx(stage="task")) != text, "task and impl injections differ")


def field_lines(e):
    """§6.4「全部字段」机械判据：每个字段各恰一条字段行、组合字段各占一行、嵌套成员名序列递归至最深层。"""
    for prev in (None, ["R1-B1"]):
        text = N.review_instruction(_ctx(prev=prev))
        e.check(N.field_line_problems(text) == [], "rendered instruction satisfies the field-line criterion (previous=%s): %s" % (prev, N.field_line_problems(text)))
    text = N.review_instruction(_ctx())
    e.check("- verdict_schema: " in text and "- subject: " in text and "- stage: " in text and "- round: " in text, "verdict_schema and the combined fields each have their own field line")
    e.check("location{file, anchor}" in text and "{bundle_name, sha256}" in text, "nested member sequences rendered to the deepest level")
    # 负例：删标题句化 / 合并组合字段 / 删嵌套成员 / 深度不足
    bad = text.replace("- verdict_schema: ", "机读块 verdict_schema: ")
    e.check(any("verdict_schema" in p for p in N.field_line_problems(bad)), "verdict_schema only in a title sentence → red")
    bad = text.replace("- stage: 与任务书状态头逐字相等。\n", "")
    e.check(any("'stage'" in p for p in N.field_line_problems(bad)), "missing combined-field line → red")
    bad = text.replace("location{file, anchor}", "location{file}")
    e.check(any("findings.location" in p for p in N.field_line_problems(bad)), "missing nested member two levels down → red")
    bad = text.replace("location{file, anchor}", "location")
    e.check(any("findings.location" in p for p in N.field_line_problems(bad)), "nested sequence collapsed to one level → red")
    bad = text.replace("{bundle_name, sha256}", "{bundle_name, sha256, extra}")
    e.check(any("candidate" in p for p in N.field_line_problems(bad)), "extra member → red")
    bad = text + "\n- verdict: duplicated line\n"
    e.check(any("'verdict'" in p for p in N.field_line_problems(bad)), "duplicated field line → red")
    e.check(N.member_sequence(C.VERDICT_MEMBER_TREE["findings"]) == "{id, severity, title, location{file, anchor}, origin, summary}", "member sequence form")


def forms_differ(e):
    review = N.review_instruction(_ctx())
    reemit = N.reemit_instruction("ORIGINAL MESSAGE")
    probe = N.probe_instruction()
    e.check(len({review, reemit, probe}) == 3, "three distinct forms")
    e.check("ORIGINAL MESSAGE" in reemit and "不得改动任何判断" in reemit and C.FENCE_INFO in reemit, "re-emission form")
    e.check(C.PROBE_PAYLOAD in probe and "不要读取任何文件" in probe, "probe form")


def skeleton_lines(e):
    """§6.4 叙述骨架注入（Amendment 2）：骨架行判据两向；往返性质；校验类补发形态；允许集合只含投递名（减重第 3 步）。"""
    import review_channel_verdict as V
    for prev in (None, ["R1-B1", "R1-N1"]):
        ctx = _ctx(prev=prev)
        text = N.review_instruction(ctx)
        probs = N.skeleton_line_problems(text, ctx["required_question_ids"], ctx["round_tag"], prev)
        e.check(probs == [], "rendered instruction satisfies the skeleton-line criterion (previous=%s): %s" % (prev, probs))
        e.check("**Verdict: <PASS|FAIL>**" in text and "### R2-<B|N|H><n> · <blocking|non_blocking|human> · <title>" in text
                and "- Q-CHANGE: <SATISFIED|NOT_SATISFIED|INDETERMINATE>" in text, "placeholder skeleton lines present")
        if prev:
            e.check("- R1-N1: <RESOLVED|UNRESOLVED|INDETERMINATE>" in text and "## Previous findings" in text, "previous ids rendered per line")
        else:
            e.check("## Previous findings" not in text, "no previous section in r1 skeleton")
    ctx = _ctx(prev=["R1-B1"])
    text = N.review_instruction(ctx)
    bad = text.replace("- Q-PREMISE: <SATISFIED|NOT_SATISFIED|INDETERMINATE>\n", "")
    e.check(any("Q-PREMISE" in p for p in N.skeleton_line_problems(bad, ctx["required_question_ids"], "r2", ["R1-B1"])), "missing question line → red")
    bad = text + "\n**Verdict: <PASS|FAIL>**\n"
    e.check(any("Verdict" in p for p in N.skeleton_line_problems(bad, ctx["required_question_ids"], "r2", ["R1-B1"])), "duplicated first line → red")
    bad = text.replace("## Question assessments", "## Question Assessments")
    e.check(any("Question assessments" in p for p in N.skeleton_line_problems(bad, ctx["required_question_ids"], "r2", ["R1-B1"])), "section name drift → red")
    # 往返性质：任一有效机读块以实际值渲染的骨架经第 13 条恢复后逐项相等
    block = {"verdict": "FAIL", "human_decision_required": True, "round": "r2",
             "findings": [{"id": "R2-B1", "severity": "blocking", "title": "bad thing"}, {"id": "R2-H1", "severity": "human", "title": "ruling"}],
             "question_assessments": [{"question_id": "Q-CHANGE", "assessment": "NOT_SATISFIED"},
                                      {"question_id": "Q-UPSTREAM", "assessment": "INDETERMINATE"},
                                      {"question_id": "Q-PREMISE", "assessment": "SATISFIED"},
                                      {"question_id": "Q-REFERENCE", "assessment": "SATISFIED"},
                                      {"question_id": "Q-BOUNDARY", "assessment": "SATISFIED"}],
             "previous_findings_disposition": [{"id": "R1-B1", "disposition": "UNRESOLVED"}]}
    lines = C.narrative_skeleton(C.skeleton_values_from_block(block, ctx["required_question_ids"], ["R1-B1"]))
    rec, probs = V.recover_narrative("\n".join(lines) + "\n")
    e.check(probs == [] and V.compare_recovered(rec, block, True) == [], "round trip: rendered narrative recovers to the block: %s %s" % (probs, V.compare_recovered(rec, block, True)))
    # 校验类补发形态
    vr = N.validation_reemit_instruction("ORIG", [("verdict_schema", '"x"'), ("authorization_disclaimer", "true")], lines, "T.md")
    e.check("ORIG" in vr and "叙述骨架如下" in vr and "- verdict_schema: \"x\"" in vr and "### R2-B1 · blocking · bad thing" in vr
            and "不得改动任何判断" in vr and vr != N.reemit_instruction("ORIG"), "validation re-emission form carries known values and the filled skeleton")
    # 减重第 3 步：锁值引用件读取许可行与字段行内的锁值路径允许集合已退役；投递名集合是唯一允许集合
    txt0 = N.review_instruction(_ctx())
    fl0 = {ln.split(":", 1)[0][2:]: ln for ln in txt0.split("\n") if ln.startswith("- ")}
    e.check("锁值引用件" not in txt0 and "locked" not in txt0 and "投递名之一；" in fl0["findings"] and "投递名子集，" in fl0["scope_files_read"],
            "no lock-value reference wording anywhere; findings and scope_files_read field lines name the delivered set only")


def cases():
    return [
        ("instruction.contract-text", contract_text),
        ("instruction.field-lines", field_lines),
        ("instruction.forms-differ", forms_differ),
        ("instruction.skeleton-lines", skeleton_lines),
    ]
