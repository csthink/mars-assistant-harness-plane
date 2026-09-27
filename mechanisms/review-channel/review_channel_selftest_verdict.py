"""自测声明：review_channel_verdict（第 7 类十四条规则、第 20 类严格发布文法与分离、第 23 类 wrapper、叙述恢复与不变性）。"""
import copy
import json

import review_channel_contract as C
import review_channel_verdict as V


IMPL_IDS = ["Q-CHANGE", "Q-UPSTREAM", "Q-PREMISE", "Q-REFERENCE", "Q-BOUNDARY"]   # impl 轮五题闭集（§6.4）


def block(verdict="FAIL", human=False, r2=False):
    b = {"verdict_schema": C.VERDICT_SCHEMA, "verdict": verdict, "human_decision_required": human, "subject": "s", "stage": "impl",
         "round": "r2" if r2 else "r1", "candidate": {"bundle_name": "c.md", "sha256": "a" * 64},
         "candidates": [{"bundle_name": "c.md", "sha256": "a" * 64}],
         "question_assessments": [{"question_id": q, "assessment": "SATISFIED", "evidence_refs": [], "finding_ids": []} for q in IMPL_IDS],
         "findings": [], "previous_findings_disposition": [], "accepted_residuals_acknowledged": ["RES-1"],
         "scope_files_read": ["T.md", "c.md"], "tools_used": ["read"], "authorization_disclaimer": True}
    rt = "R2" if r2 else "R1"
    if verdict == "FAIL":
        b["findings"].append({"id": rt + "-B1", "severity": "blocking", "title": "bad thing", "location": {"file": "c.md", "anchor": "1"},
                              "origin": "changed_region", "summary": "s"})
        b["question_assessments"][0].update(assessment="NOT_SATISFIED", finding_ids=[rt + "-B1"])
    if human:
        b["findings"].append({"id": rt + "-H1", "severity": "human", "title": "ruling", "location": {"file": "c.md", "anchor": "2"},
                              "origin": "unchanged_region", "summary": "s"})
        b["question_assessments"][1].update(assessment="INDETERMINATE", finding_ids=[rt + "-H1"])
    if r2:
        b["previous_findings_disposition"] = [{"id": "R1-B1", "disposition": "RESOLVED", "evidence_refs": []}]
    return b


def narrative(b):
    lines = ["**Verdict: %s**" % b["verdict"], "**Human decision required: %s**" % ("yes" if b["human_decision_required"] else "no"), ""]
    for f in b["findings"]:
        lines += ["### %s · %s · %s" % (f["id"], f["severity"], f["title"]), "text", ""]
    lines.append("## Question assessments")
    for q in b["question_assessments"]:
        lines.append("- %s: %s" % (q["question_id"], q["assessment"]))
    if b["previous_findings_disposition"]:
        lines += ["", "## Previous findings"] + ["- %s: %s" % (p["id"], p["disposition"]) for p in b["previous_findings_disposition"]]
    return "\n".join(lines) + "\n"


def ctx(b, narr, r2=False, delivery="tool"):
    return {"subject": "s", "stage": "impl", "round": b["round"], "candidate": {"bundle_name": "c.md", "sha256": "a" * 64},
            "required_question_ids": list(IMPL_IDS), "previous_finding_ids": ["R1-B1"] if r2 else None, "residual_ids": ["RES-1"],
            "bundle_names": ["T.md", "c.md"], "task_file": "T.md", "delivery": delivery, "narrative": narr, "secret_hit": False}


def _problems(b, mutate=None, narr=None, r2=False, delivery="tool", secret=False):
    b = copy.deepcopy(b)
    if mutate:
        mutate(b)
    n = narr if narr is not None else narrative(b)
    c = ctx(b, n, r2, delivery)
    c["secret_hit"] = secret
    return V.validate_machine(b, c)


def derived_bundle_names(e):
    """S18：投递名经去重派生而不等于基名时，判词 location.file 与 scope_files_read 取派生后的投递名即通过；取来源路径或基名即 INVALID。"""
    b = block()
    b["candidate"] = {"bundle_name": "demo--c.md", "sha256": "a" * 64}
    b["candidates"] = [b["candidate"]]
    b["findings"][0]["location"]["file"] = "x--notes.md"
    b["scope_files_read"] = ["T.md", "demo--c.md", "x--notes.md"]
    c = ctx(b, narrative(b))
    c["candidate"] = {"bundle_name": "demo--c.md", "sha256": "a" * 64}
    c["bundle_names"] = ["T.md", "demo--c.md", "x--notes.md"]
    e.check(V.validate_machine(b, c) == [], "derived names accepted: %s" % V.validate_machine(b, c))
    for bad in ("notes.md", "x/notes.md"):
        b2 = copy.deepcopy(b); b2["findings"][0]["location"]["file"] = bad
        e.check(any("location.file" in p for p in V.validate_machine(b2, c)), "basename or source path in location.file → INVALID (%s)" % bad)
    b3 = copy.deepcopy(b); b3["scope_files_read"] = ["T.md", "c.md"]
    e.check(any("scope_files_read" in p for p in V.validate_machine(b3, c)), "undelivered basename in scope_files_read → INVALID")


def fourteen_rules(e):
    e.check(_problems(block()) == [], "FAIL block valid: %s" % _problems(block()))
    e.check(_problems(block("PASS")) == [], "PASS block valid")
    e.check(_problems(block("PASS", human=True)) == [], "PASS with INDETERMINATE referencing only human findings is valid: %s" % _problems(block("PASS", human=True)))
    e.check(_problems(block(r2=True), r2=True) == [], "r2 block valid: %s" % _problems(block(r2=True), r2=True))

    def has(problems, needle):
        return any(needle in p for p in problems)
    e.check(has(_problems(block(), lambda b: b.update(verdict="PASS")), "PASS with blocking"), "rule 1 PASS/blocking")
    e.check(has(_problems(block("PASS"), lambda b: b.update(verdict="FAIL")), "FAIL requires"), "rule 1 FAIL without blocking")
    e.check(has(_problems(block(), lambda b: b.update(human_decision_required=True)), "human_decision_required"), "rule 1 human flag")
    e.check(has(_problems(block(), lambda b: b["question_assessments"].pop()), "multiset"), "rule 2 missing question")
    e.check(has(_problems(block(), lambda b: b["question_assessments"].append(dict(b["question_assessments"][1]))), "multiset"), "rule 2 duplicate question")
    # Amendment 4：题号集合 = stage 五题闭集；多出旧题 Q1、取另一 stage 的套、缺题各判 INVALID 且属判断字段缺陷（other、不补发）
    for label, mut in (("extra Q1", lambda b: b["question_assessments"].append({"question_id": "Q1", "assessment": "SATISFIED", "evidence_refs": [], "finding_ids": []})),
                       ("task set on impl", lambda b: [q.update(question_id=t) for q, t in zip(b["question_assessments"], C.required_question_ids("task"))]),
                       ("missing Q-REFERENCE", lambda b: b["question_assessments"].pop(3))):
        b2 = copy.deepcopy(block()); mut(b2)
        cl = V.validate_machine_classified(b2, ctx(b2, narrative(b2)))
        e.check(any("five-question" in m for _c, m in cl) and all(c == "other" for c, _m in cl) and not V.deterministically_remediable(cl),
                "rule 2 (%s): INVALID as a judgment defect, never re-emitted: %s" % (label, cl))
    # 规则 14（Amendment 4）：origin = unchanged_region 的 finding 不得 blocking；non_blocking / human 放行；changed_region 阻断放行
    e.check(has(_problems(block(), lambda b: b["findings"][0].update(origin="unchanged_region")), "rule-14:R1-B1"), "rule 14 unchanged_region blocking → INVALID with rule-14:<id>")
    b14 = block()
    b14["findings"][0]["origin"] = "unchanged_region"
    cl14 = V.validate_machine_classified(b14, ctx(b14, narrative(b14)))
    e.check(cl14 and all(c == "other" for c, _m in cl14) and not V.deterministically_remediable(cl14), "rule 14 is a judgment defect: not re-emitted: %s" % cl14)
    for origin in ("changed_region", "introduced_by_remediation", "carried_over"):
        e.check(not has(_problems(block(), lambda b, o=origin: b["findings"][0].update(origin=o)), "rule-14"), "rule 14 does not restrict %s" % origin)
    e.check(not has(_problems(block("PASS", human=True)), "rule-14"), "rule 14 allows unchanged_region human findings")
    b_n = block("PASS"); b_n["findings"].append({"id": "R1-N1", "severity": "non_blocking", "title": "note", "location": {"file": "c.md", "anchor": "3"}, "origin": "unchanged_region", "summary": "s"})
    b_n["question_assessments"][1]["finding_ids"] = ["R1-N1"]
    e.check(_problems(b_n) == [], "rule 14 allows unchanged_region non_blocking findings: %s" % _problems(b_n))
    e.check(has(_problems(block("PASS"), lambda b: b["question_assessments"][0].update(assessment="NOT_SATISFIED", finding_ids=[])), "non-SATISFIED"), "rule 3 non-SATISFIED needs finding")
    e.check(has(_problems(block(), lambda b: b["question_assessments"][0].update(finding_ids=["R1-B9"])), "undeclared"), "rule 4 undeclared reference")
    e.check(has(_problems(block(), lambda b: b["question_assessments"][0].update(assessment="SATISFIED", finding_ids=[])), "not referenced"), "rule 4 orphan finding")
    e.check(has(_problems(block(), lambda b: b["findings"][0].update(id="R1-N1")), "letter"), "rule 5 letter/severity")
    e.check(has(_problems(block(), lambda b: (b["findings"].append(dict(b["findings"][0], id="R1-B3")), b["question_assessments"][0]["finding_ids"].append("R1-B3"))), "consecutively"), "rule 5 gaps")
    e.check(has(_problems(block(), lambda b: b["findings"][0].update(id="R2-B1")), "round prefix"), "rule 5 round prefix")
    e.check(has(_problems(block(r2=True), lambda b: b.update(previous_findings_disposition=[]), r2=True), "previous round finding set"), "rule 6 equal set")
    e.check(has(_problems(block(), lambda b: b.update(previous_findings_disposition=[{"id": "R0-B1", "disposition": "RESOLVED", "evidence_refs": []}])), "empty in r1"), "rule 6 r1 empty")
    e.check(has(_problems(block(), lambda b: b.update(accepted_residuals_acknowledged=[])), "residual"), "rule 7 residual set")
    e.check(has(_problems(block(), lambda b: b["candidate"].update(sha256="b" * 64)), "candidate.sha256"), "rule 8 candidate binding")
    e.check(has(_problems(block(), lambda b: b.update(scope_files_read=["c.md"])), "task file"), "rule 9 scope includes task file")
    e.check(has(_problems(block(), lambda b: b.update(scope_files_read=["T.md", "zzz"])), "outside"), "rule 9 scope subset")
    e.check(has(_problems(block(), delivery="inline"), "tools_used must be empty"), "rule 9 inline tools empty")
    e.check(has(_problems(block(), lambda b: b.update(tools_used=[])), "non-empty"), "rule 9 tool path tools non-empty")
    e.check(has(_problems(block(), lambda b: b.update(authorization_disclaimer=False)), "authorization_disclaimer"), "rule 9 disclaimer")
    e.check(has(_problems(block(), lambda b: b["findings"][0]["location"].update(file="nope")), "location.file"), "rule 10 location file")
    e.check(has(_problems(block(), secret=True), "secret"), "rule 11 secret hit")
    e.check(V.validate_machine("nope", ctx(block(), "")) == ["machine block must be a JSON object"], "rule 12 total closure non-dict")
    e.check(len(V.validate_machine({"findings": 5, "question_assessments": None, "candidate": 1}, ctx(block(), ""))) > 3, "rule 12 total closure garbage shape")
    e.check(has(_problems(block(), narr=narrative(block()).replace("**Verdict: FAIL**", "**Verdict: PASS**")), "mismatch: verdict"), "rule 13 verdict line")
    e.check(has(_problems(block(), narr=narrative(block()).replace("### R1-B1 · blocking · bad thing", "### R1-B1 · blocking · other")), "mismatch: findings"), "rule 13 finding title")
    e.check(has(_problems(block(), narr=narrative(block()).replace("Q-UPSTREAM: SATISFIED", "Q-UPSTREAM: INDETERMINATE", 1)), "mismatch: question_assessments"), "rule 13 assessment line")
    e.check(has(_problems(block(), narr=narrative(block()).replace("Q-UPSTREAM: SATISFIED", "Q-UPSTREAM: SATISFIED · extra: true", 1)), "mismatch: question_assessments"),
            "rule 13: a question line with a trailing segment is not the frozen line form")
    e.check(has(_problems(block(r2=True), narr=narrative(block(r2=True)).replace("R1-B1: RESOLVED", "R1-B1: UNRESOLVED"), r2=True), "mismatch: previous"), "rule 13 disposition")
    e.check(has(_problems(block(), narr=narrative(block()) + "\n<div>raw</div>\n"), "raw HTML"), "raw HTML forbidden")
    # R1-B6 整改：严格 schema
    e.check(has(_problems(block(), lambda b: b["findings"][0].update(extra="x")), "unknown field"), "unknown finding field rejected")
    e.check(has(_problems(block(), lambda b: b["question_assessments"][0].update(extra="x")), "unknown field"), "unknown assessment field rejected")
    e.check(has(_problems(block(), lambda b: b["question_assessments"][1].update(extra_member="x")), "unknown field"), "retired assessment members are unknown fields (v4)")
    e.check(has(_problems(block(), narr=narrative(block()).replace("### R1-B1", "## R1-B1")), "heading-level section"), "heading must be level three")
    e.check(has(_problems(block(), lambda b: b["findings"][0]["location"].update(anchor=5)), "location must be"), "non-string anchor rejected (R2-B6)")
    e.check(has(_problems(block(), lambda b: b["question_assessments"][0].update(evidence_refs=[1])), "array of strings"), "non-string evidence_refs rejected (R2-B6)")
    e.check(has(_problems(block(), narr="\n\n" + narrative(block())), "leading blank"), "leading blank lines rejected (R2-B6)")
    e.check(has(_problems(block(), narr=narrative(block()).replace("**\n**Human", "**\n\n**Human", 1)), "physical line 2"),
            "blank physical line between Verdict and Human decision rejected (R3-B6)")
    e.check(has(_problems(block(), narr="**Human decision required: no**\n" + narrative(block())), "line 1 must be"), "swapped first lines rejected")
    e.check(has(_problems(block(), narr="```\nfence first\n```\n" + narrative(block())), "line 1 must be"), "a fence before the Verdict line fails the physical-line check (R9-B3)")
    dup = narrative(block()).replace("## Question assessments\n", "## Question assessments\n## Question assessments\n", 1)
    e.check(has(_problems(block(), narr=dup), "more than once"), "duplicated required section rejected (R4-B3)")
    e.check(not has(_problems(block(), narr=narrative(block()) + "\n```\n<div>in fence</div>\n```\n"), "raw HTML"), "HTML inside a closed fence allowed")
    e.check(has(_problems(block(), narr=narrative(block()) + "\n```\n<div>never closed</div>\n"), "raw HTML"), "HTML after an unclosed fence is not exempt (R11-B2)")
    e.check(has(_problems(block(), narr=narrative(block()) + "\n```review-channel-verdict\n{}\n```\n"), "must not contain a review-channel-verdict fence"),
            "a second verdict fence inside the narrative is rejected (R11-B3)")
    e.check(has(_problems(block(), narr=narrative(block()) + "\n```review-channel-verdict\r\n{}\r\n```\r\n"), "must not contain a review-channel-verdict fence"),
            "CRLF second verdict fence is rejected too (R12-B1)")
    e.check(has(_problems(block(), narr=narrative(block()) + "\n``` not`a`fence\n<div>hidden</div>\n```\n"), "raw HTML"),
            "a backtick-bearing info string is not a code fence; HTML behind it is not exempt (R12-B2)")
    e.check(has(_problems(block(), narr=narrative(block()) + "\n```\r\n<div>in crlf fence</div>\r\n```\r\n"), "raw HTML") is False,
            "CRLF closed fence still exempts its HTML")
    # R13-B1：孤立 CR 作为行分隔同样规范化
    e.check(has(_problems(block(), narr=narrative(block()) + "\rtext\r<div>lone-cr html</div>\r"), "raw HTML"), "raw HTML behind lone CR separators is caught (R13-B1)")
    e.check(has(_problems(block(), narr=narrative(block()) + "\r```review-channel-verdict\r{}\r```\r"), "must not contain a review-channel-verdict fence"),
            "lone-CR second verdict fence is caught (R13-B1)")


def envelope_tiers(e):
    b = block()
    jb = json.dumps(b, indent=1)
    narr = narrative(b)
    strict = "```review-channel-verdict\n%s\n```\n\n%s" % (jb, narr)
    r = V.classify(strict)
    e.check(r["tier"] == "strict" and r["json_bytes"] == jb and r["narrative"].strip() == narr.strip(), "tier 1 strict")
    r_crlf = V.classify(strict.replace("\n", "\r\n"))
    r_cr = V.classify(strict.replace("\n", "\r"))
    e.check(r_crlf["tier"] == "strict" and r_cr["tier"] == "strict", "CRLF and lone-CR envelopes still classify as strict (R13-B1)")
    e.check(r_crlf["json_bytes"] == jb.replace("\n", "\r\n") and r_cr["json_bytes"] == jb.replace("\n", "\r"),
            "JSON value segment keeps the reviewer's CR / CRLF whitespace byte for byte (R14-B1)")
    e.check(V.render_published(r_crlf["json_bytes"], r_crlf["narrative"]).split(b"\n```\n")[0] == b"```review-channel-verdict\n" + jb.replace("\n", "\r\n").encode(),
            "published block carries the verbatim segment; only the narrative is normalized")
    e.check(r_crlf["raw_block"].endswith("```") and "\r" not in r_crlf["narrative"] and "\r" not in r_cr["narrative"], "raw block bounded by the closer; narrative normalized")
    pub = V.render_published(r["json_bytes"], r["narrative"])
    obj, jb2, narr2 = V.parse_published(pub)
    e.check(jb2 == jb and obj["verdict"] == "FAIL" and pub.startswith(b"```review-channel-verdict\n{"), "strict publication grammar round-trips")
    e.check(V.render_published(jb, narr) == V.render_published(jb, narr), "deterministic rendering")
    middle = "%s\n```review-channel-verdict\n%s\n```\n" % (narr, jb)
    tail = "%s\n```review-channel-verdict\n%s\n```" % (narr, jb)
    for name, m in (("middle", middle), ("tail", tail)):
        r = V.classify(m)
        e.check(r["tier"] == "repaired" and "block-relocated" in r["repairs"] and r["json_bytes"] == jb, "%s block relocated" % name)
        e.check(V.render_published(r["json_bytes"], r["narrative"]) == pub, "%s publishes the same document" % name)
    r = V.classify("  ````REVIEW-CHANNEL-VERDICT\n%s\nthanks\n%s" % (jb, narr))
    e.check(sorted(r["repairs"]) == sorted(["missing-closing-fence", "opener-indent", "fence-length", "info-string-case", "trailing-content"])
            and r["json_bytes"] == jb and "thanks" in r["narrative"], "six repairs minus relocation: %s" % r["repairs"])
    r = V.classify("```review-channel-verdict\n%s\n```\n```review-channel-verdict\n%s\n```\n" % (jb, jb))
    e.check(r["tier"] == "invalid" and r["candidates"] == 2, "two blocks are tier 3")
    r = V.classify(narr)
    e.check(r["tier"] == "invalid" and r["candidates"] == 0, "zero blocks are tier 3")
    r = V.classify("```review-channel-verdict\n%s\n```\n%s" % (jb[:-20], narr))
    e.check(r["tier"] == "invalid" and "raw_decode" in r["reason"] and narr.strip() in r["narrative"], "truncated JSON is tier 3 and the narrative survives")
    r = V.classify("```review-channel-verdict\nnote: {\"a\": 1}\n```\n%s" % narr)
    e.check(r["tier"] == "invalid" and "prefix" in r["reason"], "prefix bytes are not tolerated")
    tricky = json.dumps({"a": "line\nbreak ``` and ```review-channel-verdict inside", "b": 1})
    r = V.classify("```review-channel-verdict\n%s\n```\n%s" % (tricky, narr))
    e.check(r["tier"] == "strict" and r["json_bytes"] == tricky, "newline and backticks inside a JSON string do not close the block")
    r = V.classify("```review-channel-verdict\n%s\n```\n%s" % (jb + " ", narr))
    e.check(r["tier"] == "strict" and r["json_bytes"] == jb, "whitespace after the value is not trailing content")
    r = V.classify("```review-channel-verdict\n%s\n```\n%s" % (jb + " (see above)", narr))
    e.check(r["tier"] == "repaired" and r["repairs"] == ["trailing-content"] and "(see above)" in r["narrative"], "trailing prose recorded and moved to the narrative")
    r = V.classify("\n\n" + strict)
    e.check(r["tier"] == "repaired" and r["repairs"] == ["block-relocated"] and V.render_published(r["json_bytes"], r["narrative"]) == pub,
            "leading blank lines before the opener are a relocation (R5-N1)")
    # R3-B6 / R10-B2：闭栏须行首恰三反引号；不合形态的闭栏不是闭栏 → 六种 repair 之内（缺闭栏 + 尾随内容），不得判 strict
    r = V.classify("```review-channel-verdict\n%s\n  ```\n\n%s" % (jb, narr))
    e.check(r["tier"] == "repaired" and set(r["repairs"]) == {"missing-closing-fence", "trailing-content"} and r["json_bytes"] == jb,
            "indented closer is not a closer: %s" % r["repairs"])
    r = V.classify("```review-channel-verdict\n%s\n`````\n\n%s" % (jb, narr))
    e.check(r["tier"] == "repaired" and set(r["repairs"]) == {"missing-closing-fence", "trailing-content"}, "longer closer is not a closer: %s" % r["repairs"])
    e.check("`````" in r["narrative"], "the non-closer line is trailing content and stays in the narrative")
    e.check(len(C.REPAIRS) == 6 and set(r["repairs"]) <= set(C.REPAIRS), "exactly six repairs (§6.5.3)")


def wrapper_spans(e):
    b = block()
    narr = narrative(b)
    m = json.dumps(b, indent=2)
    wrapper = '{"narrative": %s, "machine": %s}' % (json.dumps(narr), m)
    machine, n = V.extract_wrapper(wrapper)
    e.check(machine == m and n == narr, "machine span verbatim and narrative decoded")
    e.check(V.extract_wrapper('{"narrative": "x"}')[0] is None, "machine missing")
    e.check(V.extract_wrapper('{"machine": {}, "machine": {}, "narrative": "x"}')[0] is None, "machine duplicated")
    e.check(V.extract_wrapper('[1]')[0] is None and V.extract_wrapper('{"machine": {"a": 1}, "narrative": 5}')[0] is None, "shape negatives")
    e.check(V.extract_wrapper('{"machine": {"a": 1}, "narrative": "n", "extra": 1}')[0] is None, "extra wrapper member rejected (R1-B6)")
    e.check(V.extract_wrapper('{"machine": {"a": 1}, "narrative": "n"} trailing')[0] is None, "trailing bytes after the wrapper rejected (R2-B6)")
    e.check(V.extract_wrapper('  {"machine": {"a": 1}, "narrative": "n"}\n')[0] == '{"a": 1}', "surrounding whitespace tolerated")
    e.check(V.validate_machine(json.loads(machine), ctx(b, n, delivery="inline")) == ["tools_used must be empty under inline delivery"], "inline rule 9")
    e.check(any("fence block" in x for x in V.validate_machine(json.loads(machine), ctx(b, n + "\n```review-channel-verdict\n{}\n```\n", delivery="inline"))),
            "inline narrative carrying a verdict fence is INVALID (R11-B3)")


def recovery_and_invariance(e):
    b = block(r2=True)
    rec, problems = V.recover_narrative(narrative(b))
    e.check(problems == [] and rec["verdict"] == "FAIL" and rec["findings"] == {"R2-B1": ("blocking", "bad thing")}
            and rec["questions"]["Q-CHANGE"] == "NOT_SATISFIED" and rec["previous"] == {"R1-B1": "RESOLVED"}, "recovered fields")
    e.check(V.compare_recovered(rec, b, True) == [], "invariance passes on the same block")
    for mutate, field in ((lambda x: x.update(verdict="PASS"), "verdict"), (lambda x: x.update(human_decision_required=True), "human_decision_required"),
                          (lambda x: x["findings"][0].update(title="other"), "findings"),
                          (lambda x: x["question_assessments"][1].update(assessment="INDETERMINATE"), "question_assessments"),
                          (lambda x: x["previous_findings_disposition"][0].update(disposition="UNRESOLVED"), "previous_findings_disposition")):
        b2 = copy.deepcopy(b)
        mutate(b2)
        e.check(field in V.compare_recovered(rec, b2, True), "invariance catches %s" % field)
    rec2, problems2 = V.recover_narrative("some prose\n")
    e.check(len(problems2) >= 2 and rec2["verdict"] is None, "unrecoverable narrative reports problems")
    e.check(sorted(C.REEMIT_UNVERIFIABLE_FIELDS) == sorted(["location", "origin", "summary", "evidence_refs", "finding_ids",
                                                             "accepted_residuals_acknowledged", "scope_files_read", "tools_used", "candidate", "candidates"]), "unverifiable closed set")


def classification(e):
    """§6.5.2 末段两类可确定性整改项与判断字段（Amendment 2）；规则 8 candidates 等集；第 9 / 10 条允许集合只含投递名。"""
    b = block()
    c = ctx(b, narrative(b))
    e.check(V.validate_machine_classified(b, c) == [], "valid block has no classified problems")
    def classes(mut, **kw):
        b2 = copy.deepcopy(b)
        mut(b2)
        cc = dict(c, narrative=kw.get("narr", narrative(b)))   # 叙述取自未变异块：判断字段被删时仍可渲染
        cc.update({k: v for k, v in kw.items() if k != "narr"})
        return V.validate_machine_classified(b2, cc)
    # 已知值缺陷
    for mut in (lambda x: x.pop("verdict_schema"), lambda x: x.update(verdict_schema="v0"), lambda x: x.update(authorization_disclaimer=False),
                lambda x: x.update(subject="other"), lambda x: x.update(round="r9"), lambda x: x.update(accepted_residuals_acknowledged=[]),
                lambda x: x.update(candidate={"bundle_name": "c.md", "sha256": "b" * 64}), lambda x: x.pop("candidates")):
        cl = classes(mut)
        e.check(cl and all(k == "known" for k, _m in cl) and V.deterministically_remediable(cl), "known-value defect classified known: %s" % cl)
    # 叙述缺陷
    bad_narr = narrative(b).replace("### R1-B1 · blocking · bad thing", "### R1-B1 - blocking - bad thing")
    cl = classes(lambda x: None, narr=bad_narr)
    e.check(cl and all(k == "narrative" for k, _m in cl) and V.deterministically_remediable(cl), "heading drift classified narrative: %s" % cl)
    cl = classes(lambda x: None, narr="\n" + narrative(b))
    e.check(cl and all(k == "narrative" for k, _m in cl), "leading blank line classified narrative: %s" % cl)
    cl = classes(lambda x: None, narr=narrative(b) + "<div>x</div>\n")
    e.check(cl and all(k == "narrative" for k, _m in cl), "raw HTML classified narrative: %s" % cl)
    # 判断字段缺陷与其他失败 → other，不触发校验类补发
    for mut in (lambda x: x.pop("question_assessments"), lambda x: x.update(verdict="PASS"), lambda x: x["findings"][0].update(id="R1-B7"),
                lambda x: x.update(scope_files_read=["T.md", "zzz.md"]), lambda x: x.update(tools_used=[])):
        cl = classes(mut)
        e.check(cl and any(k == "other" for k, _m in cl) and not V.deterministically_remediable(cl), "judgment defect classified other: %s" % cl)
    cl = classes(lambda x: x.pop("verdict_schema"), secret_hit=True)
    e.check(not V.deterministically_remediable(cl), "secret hit blocks the validation trigger")
    # 判断字段逐字节相等
    b2 = copy.deepcopy(b)
    e.check(V.judgment_mismatches(b, b2) == [], "identical judgment fields")
    b2["verdict"] = "PASS"
    b2["findings"][0]["summary"] = "changed"
    b2["verdict_schema"] = "other"
    e.check(V.judgment_mismatches(b, b2) == ["verdict", "findings"], "verdict and findings differ, known-value field ignored: %s" % V.judgment_mismatches(b, b2))
    for f in C.JUDGMENT_FIELDS:
        b3 = copy.deepcopy(b)
        b3[f] = "x"
        e.check(V.judgment_mismatches(b, b3) == [f], "each judgment field compared byte-wise: %s" % f)
    e.check(set(C.KNOWN_VALUE_FIELDS) | set(C.JUDGMENT_FIELDS) == set(C.VERDICT_FIELDS) and not set(C.KNOWN_VALUE_FIELDS) & set(C.JUDGMENT_FIELDS), "two field sets partition the block")
    kv = dict(V.known_value_literals(c))
    e.check(kv["verdict_schema"] == json.dumps(C.VERDICT_SCHEMA) and json.loads(kv["candidates"]) == [{"bundle_name": "c.md", "sha256": "a" * 64}]
            and kv["authorization_disclaimer"] == "true", "known value literals: %s" % kv)
    # 规则 8：candidates 精确等集、次序、首项
    two = [{"bundle_name": "c.md", "sha256": "a" * 64}, {"bundle_name": "d.md", "sha256": "e" * 64}]
    c2 = dict(c, candidates=two, bundle_names=["T.md", "c.md", "d.md"])
    b4 = copy.deepcopy(b); b4["candidates"] = list(two)
    e.check(V.validate_machine(b4, dict(c2, narrative=narrative(b4))) == [], "two candidates exact set valid")
    for bad, label in (([two[0]], "subset"), (two + [{"bundle_name": "x.md", "sha256": "f" * 64}], "superset"), (two + [two[0]], "duplicate"),
                       ([two[1], two[0]], "order (candidates[0] != candidate)")):
        b5 = copy.deepcopy(b); b5["candidates"] = bad
        e.check(any("candidates" in m for m in V.validate_machine(b5, dict(c2, narrative=narrative(b5)))), "candidates %s → INVALID" % label)
    # R32-B2：三候选保持首项而交换后续项 → INVALID（逐项同序相等）
    three = two + [{"bundle_name": "x.md", "sha256": "f" * 64}]
    c3 = dict(c, candidates=three, bundle_names=["T.md", "c.md", "d.md", "x.md"])
    b8 = copy.deepcopy(b); b8["candidates"] = [three[0], three[2], three[1]]
    e.check(any("candidates" in m for m in V.validate_machine(b8, dict(c3, narrative=narrative(b8)))), "later candidates swapped → INVALID (order)")
    b9 = copy.deepcopy(b); b9["candidates"] = list(three)
    e.check(V.validate_machine(b9, dict(c3, narrative=narrative(b9))) == [], "three candidates in manifest order valid")
    b6 = copy.deepcopy(b); b6["candidates"] = list(two); b6["candidate"] = two[1]
    e.check(any("candidate" in m for m in V.validate_machine(b6, dict(c2, narrative=narrative(b6)))), "candidate must be the first candidate")
    # 第 9 / 10 条：允许集合 = 投递名集合（锁值引用件的允许集合随减重第 3 步退役）；未投递的仓内路径在两处一律拒绝
    b7 = copy.deepcopy(b); b7["scope_files_read"] = ["T.md", "c.md", "mechanisms/x/Y.md"]; b7["findings"][0]["location"]["file"] = "mechanisms/x/Y.md"
    probs = V.validate_machine(b7, dict(c, narrative=narrative(b7)))
    e.check(any("scope_files_read" in m for m in probs) and any("location.file" in m for m in probs), "undelivered repository path rejected in both: %s" % probs)


def cases():
    return [
        ("verdict.classification", classification),
        ("verdict.fourteen-rules", fourteen_rules),
        ("verdict.derived-bundle-names", derived_bundle_names),
        ("verdict.envelope-tiers", envelope_tiers),
        ("verdict.wrapper-spans", wrapper_spans),
        ("verdict.recovery-invariance", recovery_and_invariance),
    ]
