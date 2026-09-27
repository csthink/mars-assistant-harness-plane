"""自测声明：review_channel_inputs（第 4 类被审输入、第 18 类引用解析三分、现行修订号标注、禁名、封存、基线恢复）。"""
import json
import os

import review_channel_base as base
import review_channel_inputs as I


def closure_from_catalog(e):
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    e.check("mechanisms" in cl["dirs"] and "AGENTS.md" in cl["files"], "closure from rules_catalog.json")
    catalog = json.loads(repo.read("mechanisms/gates/rules_catalog.json"))
    boot = catalog["profiles"]["bootstrap"]
    # 治理 CI 退出后，解析仍从保留的两个成员键取仓根闭集。
    boot["root_tracked_members"]["values"] = [
        value for value in boot["root_tracked_members"]["values"] if value != ".gitlab-ci.yml"]
    repo.write("mechanisms/gates/rules_catalog.json", json.dumps(catalog))
    without_ci = I.root_closure(repo.root)
    e.check(without_ci["dirs"] == cl["dirs"] and without_ci["files"] == cl["files"] - {".gitlab-ci.yml"},
            "closure remains available after governance CI member retirement")
    for missing in ("top_level_members", "root_tracked_members"):
        incomplete = json.loads(json.dumps(catalog))
        del incomplete["profiles"]["bootstrap"][missing]
        repo.write("mechanisms/gates/rules_catalog.json", json.dumps(incomplete))
        e.expect_error(lambda: I.root_closure(repo.root), code="root-closure-unavailable", message="missing " + missing)
    os.unlink(repo.path("mechanisms/gates/rules_catalog.json"))
    e.expect_error(lambda: I.root_closure(repo.root), code="root-closure-unavailable", message="missing catalog")


def reference_three_way(e):
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    repo.write("mechanisms/demo/notes.md", "n")
    repo.write("records/notes.md", "n")
    repo.write("decisions/D-01-x.md", "d")
    repo.commit("more files")
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    text = ("# Demo\n\n> Depends on:\n> `AGENTS.md`\n> `D-01-x.md@r1`\n>\n\n"
            "Path `decisions/D-01-x.md`, bare `notes.md@r1`, absent `mechanisms/nope.md`, planned `mechanisms/demo/future.py`, "
            "template `mechanisms/<x>/y.md`, schema `review-channel-request/v2`, home `~/.zshrc`, dir `mechanisms/gates/`, "
            "outside `docs/archive.md` and self `%s`.\n\n```text\n`mechanisms/inside-fence.md`\n```\n" % cand)
    refs = I.extract_candidate_references(text, cl)
    tokens = [r["token"] for r in refs]
    e.check("mechanisms/inside-fence.md" not in tokens and "mechanisms/<x>/y.md" not in tokens and "~/.zshrc" not in tokens
            and "review-channel-request/v2" not in tokens and "docs/archive.md" not in tokens, "exclusions: %s" % tokens)
    e.check({"AGENTS.md", "D-01-x.md", "decisions/D-01-x.md", "notes.md", "mechanisms/nope.md", "mechanisms/demo/future.py",
             "mechanisms/gates"} <= set(tokens), "three forms extracted: %s" % tokens)
    forms = {r["token"]: (r["form"], r["revision"]) for r in refs}
    e.check(forms["D-01-x.md"] == ("at-round", 1) and forms["notes.md"] == ("at-round", 1) and forms["AGENTS.md"] == ("path", None),
            "at-round form carries its revision number: %s" % forms)
    res, fail = I.resolve_references(repo.root, [(cand, text)], [], [], cl)
    st = {r["token"]: r["status"] for r in res}
    e.check(st["AGENTS.md"] == "missing" and st["decisions/D-01-x.md"] == "missing", "existing but undelivered → missing")
    e.check(st["notes.md"] == "ambiguous", "bare name with two hits in domain three → ambiguous")
    e.check(st["mechanisms/nope.md"] == "unresolved", "absent path → unresolved")
    e.check(st["mechanisms/demo/future.py"] == "planned" and st["mechanisms/gates"] == "directory" and st[cand] == "self", "planned / directory / self")
    e.check(fail[0] == "reference-missing", "first failure in scan order is the AGENTS.md missing: %s" % (fail,))
    res, fail = I.resolve_references(repo.root, [(cand, text)], ["AGENTS.md", "decisions/D-01-x.md"], [], cl)
    e.check(fail[0] == "reference-ambiguous", "next failure ambiguous")
    # R1-B2：域内多命中不以 inputs.references 消解——交集恰一件仍判 ambiguous
    res, fail = I.resolve_references(repo.root, [(cand, text)], ["AGENTS.md", "decisions/D-01-x.md", "records/notes.md"], [], cl)
    e.check(fail[0] == "reference-ambiguous", "intersection with inputs.references does not disambiguate")
    text2 = text.replace("bare `notes.md@r1`, ", "")
    res, fail = I.resolve_references(repo.root, [(cand, text2)], ["AGENTS.md", "decisions/D-01-x.md"], [], cl)
    e.check(fail[0] == "reference-unresolved", "then unresolved")
    res, fail = I.resolve_references(repo.root, [(cand, text2)], ["AGENTS.md", "decisions/D-01-x.md"],
                                     [{"reference": "mechanisms/nope.md", "reason": "archive file"}], cl)
    e.check(fail is None and {r["token"]: r["status"] for r in res}["mechanisms/nope.md"] == "exempt", "out-of-repo exemption accepted (kind defaults to exemption)")
    res, fail = I.resolve_references(repo.root, [(cand, text2)], ["decisions/D-01-x.md"],
                                     [{"reference": "AGENTS.md", "reason": "skip"}, {"reference": "mechanisms/nope.md", "reason": "a"}], cl)
    e.check(fail[0] == "reference-missing", "in-repo master cannot be exempted")


def reference_domains(e):
    """S14 其一、其二、其四至其六：三域匹配集、零命中相对选定域、目录名绑定闭集、域一现行修订号标注、域二完整基数与深度。"""
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    repo.write("sdd/spec.md", "s"); repo.write("sdd/proposal.md", "p"); repo.write("sdd/milestones.md", "m")
    repo.write("records/lineage/proposal.md", "old proposal")                     # 域三同名件，不在域一
    repo.write("mechanisms/alpha/HarnessPlane_Alpha_Design_v1.md", "a")
    repo.write("mechanisms/beta/HarnessPlane_Beta_Design_v1.md", "b")
    repo.write("mechanisms/beta/HarnessPlane_Alpha_Design_v1.md", "b2")            # 域二两个单元同名 → ambiguous
    repo.write("mechanisms/gamma/deep/HarnessPlane_Gamma_Design_v1.md", "g")       # 深度两层：不计入域二
    repo.write("records/HarnessPlane_Gamma_Design_v1.md", "g-out")                 # 域外同名件：只进诊断
    repo.write("records/governance/spec/freeze-records.jsonl", _fact(4, "freeze", "sdd/spec.md") + _fact(5, "re-freeze", "sdd/spec.md"))
    repo.write("records/governance/proposal/HarnessPlane_Proposal_Freeze_Record_r2.md", "# HarnessPlane · proposal · Freeze Record r2\n")
    repo.commit("domains")
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    header = "# Demo\n\n> Depends on:\n> `spec.md@r5 FR-1`\n>\n\n"
    # 其一：域一恰一命中而域三多命中 → 放行、投递的是域一那件；其五：域一只核路径，任务书并列标注现行修订号（jsonl 与 .md 各一例）
    text = header + "Body cites `proposal.md@r2`.\n"
    res, fail = I.resolve_references(repo.root, [(cand, text)], ["sdd/spec.md", "sdd/proposal.md"], [], cl)
    by = {r["token"]: r for r in res}
    e.check(fail is None, "domain one resolves: %s" % (fail,))
    e.check(by["spec.md"]["domain"] == "one" and by["spec.md"]["path"] == "sdd/spec.md" and by["spec.md"]["current_revision"] == 5, "spec.md@r5 → domain one, current r5: %s" % by["spec.md"])
    e.check(by["proposal.md"]["domain"] == "one" and by["proposal.md"]["path"] == "sdd/proposal.md" and by["proposal.md"]["out_of_domain"] == ["records/lineage/proposal.md"]
            and by["proposal.md"]["current_revision"] == 2, "planning-baseline name with a repo-wide namesake resolves in domain one only (current revision via the .md fallback): %s" % by["proposal.md"])
    # 域二：页首裸机制设计正本名；两个不同单元目录下同名各一命中 → ambiguous
    header_a = "# Demo\n\n> Depends on:\n> `HarnessPlane_Alpha_Design_v1.md`\n>\n\n"
    res2, fail2 = I.resolve_references(repo.root, [(cand, header_a)], ["mechanisms/alpha/HarnessPlane_Alpha_Design_v1.md"], [], cl)
    e.check(res2[0]["domain"] == "two" and res2[0]["status"] == "ambiguous" and fail2[0] == "reference-ambiguous" and "domain two" in fail2[1],
            "domain two: same name under two unit directories → ambiguous: %s" % (fail2,))
    # 其六：域二恰一命中、零命中；深度负例：两层以上的命中不计入域二
    header_b = "# Demo\n\n> Depends on:\n> `HarnessPlane_Beta_Design_v1.md`\n> `HarnessPlane_Gamma_Design_v1.md`\n>\n\n"
    res3, fail3 = I.resolve_references(repo.root, [(cand, header_b)], ["mechanisms/beta/HarnessPlane_Beta_Design_v1.md"], [], cl)
    by3 = {r["token"]: r for r in res3}
    e.check(by3["HarnessPlane_Beta_Design_v1.md"]["status"] == "delivered" and by3["HarnessPlane_Beta_Design_v1.md"]["path"] == "mechanisms/beta/HarnessPlane_Beta_Design_v1.md", "domain two exactly one hit → delivered")
    e.check(by3["HarnessPlane_Gamma_Design_v1.md"]["status"] == "unresolved" and fail3[0] == "reference-unresolved"
            and set(by3["HarnessPlane_Gamma_Design_v1.md"]["out_of_domain"]) == {"mechanisms/gamma/deep/HarnessPlane_Gamma_Design_v1.md", "records/HarnessPlane_Gamma_Design_v1.md"}
            and "outside the selected domain" in fail3[1],
            "其二：zero hits in domain two (deep hit not counted, out-of-domain namesake only diagnosed) → unresolved: %s" % (fail3,))
    # 其五：域一引用的修订号不再核对（减重第 3 步，F3 甲）：无对应记录的修订号照样放行，只标注现行修订号
    res4, fail4 = I.resolve_references(repo.root, [(cand, "# D\n\n> Depends on:\n> `spec.md@r9`\n>\n")], ["sdd/spec.md"], [], cl)
    e.check(fail4 is None and res4[0]["status"] == "delivered" and res4[0]["revision"] == 9 and res4[0]["current_revision"] == 5,
            "a revision with no record is delivered with the current revision annotated, never rejected: %s" % (res4[0],))
    res5, fail5 = I.resolve_references(repo.root, [(cand, "# D\n\n> Depends on:\n> `spec.md@r4`\n>\n")], ["sdd/spec.md"], [], cl)
    e.check(fail5 is None and res5[0]["status"] == "delivered" and res5[0]["revision"] == 4 and res5[0]["current_revision"] == 5, "existing non-current revision → delivered with annotation")
    # 页首非设计正本裸名（Task Definition 一类）→ 域三；非规划基线裸名带修订号 → 域三
    repo.write("tasks/gov-t1/gov-t1.md", "task def"); repo.commit("task def")
    res7, fail7 = I.resolve_references(repo.root, [(cand, "# D\n\n> Depends on:\n> `gov-t1.md`\n>\n")], ["tasks/gov-t1/gov-t1.md"], [], cl)
    e.check(fail7 is None and res7[0]["domain"] == "three" and res7[0]["status"] == "delivered", "header bare name outside the design-master grammar → domain three: %s" % res7[0])
    repo.write("elsewhere/other.md", "o"); repo.commit("other")
    res6, fail6 = I.resolve_references(repo.root, [(cand, "Cites `other.md@r1`.\n")], ["elsewhere/other.md"], [], cl)
    e.check(fail6 is None and res6[0]["domain"] == "three" and res6[0]["status"] == "delivered", "non-planning-baseline name with @rN → domain three")
    # 其四：缺域一、域二两个目录名之任一 → root-closure-unavailable（两名各一负例），不回退全仓匹配
    import json as _json
    cat = _json.loads(repo.read("mechanisms/gates/rules_catalog.json"))
    for gone in ("sdd", "mechanisms"):
        c2 = _json.loads(_json.dumps(cat))
        c2["profiles"]["bootstrap"]["top_level_members"]["values"] = [v for v in c2["profiles"]["bootstrap"]["top_level_members"]["values"] if v != gone]
        repo.write("mechanisms/gates/rules_catalog.json", _json.dumps(c2))
        e.expect_error(lambda: I.root_closure(repo.root), code="root-closure-unavailable", message="domain directory %r missing from the closure" % gone)
    repo.write("mechanisms/gates/rules_catalog.json", _json.dumps(cat))


def decision_form_excluded(e):
    """S14 其八：`D-<NN>@rN` 不进入提取集（明示排除，Owner 2026-09-04「域四删」）；变异「纳入提取集」后本例红。"""
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    text = "# D\n\n> Depends on:\n> `D-09@r1`\n>\n\nBody cites `D-42@r3` and `D-09@r1` again.\n"
    refs = I.extract_candidate_references(text, cl)
    e.check(refs == [], "Decision reference form is not a filename and is not extracted: %s" % refs)
    res, fail = I.resolve_references(repo.root, [(cand, text)], [], [], cl)
    e.check(fail is None and res == [], "no failure code and nothing listed, whether or not any Decision file is delivered")
    e.check(not I.is_bare_filename("D-09") and I.is_bare_filename("spec.md"), "bare filename predicate requires an extension")


def planned_location(e):
    """S14 其七：规定落点须经 evidence_limits 以 kind = planned-location 声明，通道再校验两项；非声明项按豁免处置。"""
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    e.check("apps" in cl["dirs"] and not any(f.startswith("apps") for f in I._repo_files(repo.root)), "fixture: apps is a closure member not yet created")
    text = "Layout cites `apps/web/README.md` and `records/nope.md` and `mechanisms/gates/`.\n"
    lim = [{"reference": "apps/web/README.md", "reason": "on-demand directory", "kind": "planned-location"}]
    res, fail = I.resolve_references(repo.root, [(cand, text)], [], lim, cl)
    by = {r["token"]: r for r in res}
    e.check(by["apps/web/README.md"]["status"] == "planned-location" and by["apps/web/README.md"]["reason"] == "on-demand directory",
            "declared planned location with both checks satisfied → planned-location")
    e.check(by["records/nope.md"]["status"] == "unresolved" and fail[0] == "reference-unresolved", "undeclared missing path under an existing top-level member → unresolved")
    e.check(by["mechanisms/gates"]["status"] == "directory", "existing directory needs no declaration")
    # 已声明但顶层成员已存在 → 声明无效、普通缺件
    res, fail = I.resolve_references(repo.root, [(cand, "Cites `records/nope.md`.\n")], [], [{"reference": "records/nope.md", "reason": "x", "kind": "planned-location"}], cl)
    e.check(fail[0] == "reference-unresolved" and "already exists" in res[0]["reason"], "declared but top-level member exists → invalid declaration → unresolved: %s" % res[0])
    # 未经声明的同形态路径 → unresolved（自动放行已取消）
    res, fail = I.resolve_references(repo.root, [(cand, "Cites `apps/web/README.md`.\n")], [], [], cl)
    e.check(fail[0] == "reference-unresolved", "undeclared planned-location-shaped path → unresolved")
    # kind 缺省 / exemption → 不构成规定落点声明，按豁免处置
    res, fail = I.resolve_references(repo.root, [(cand, "Cites `apps/web/README.md`.\n")], [], [{"reference": "apps/web/README.md", "reason": "r"}], cl)
    e.check(fail is None and res[0]["status"] == "exempt", "kind absent → exemption branch, not planned-location")
    res, fail = I.resolve_references(repo.root, [(cand, "Cites `apps/web/README.md`.\n")], [], [{"reference": "apps/web/README.md", "reason": "r", "kind": "exemption"}], cl)
    e.check(fail is None and res[0]["status"] == "exempt", "kind exemption → exemption branch")
    # 首段不在闭集：校验函数直接判定（提取规则不会产生此类路径）
    ok, detail = I.planned_location_check("zzz/x.md", {"kind": "planned-location", "reason": "r"}, I._repo_files(repo.root), cl)
    e.check(not ok and "root-closure" in detail, "first segment outside the closure → declaration invalid")
    ok, _d = I.planned_location_check("notes.md", {"kind": "planned-location", "reason": "r"}, I._repo_files(repo.root), cl)
    e.check(not ok, "bare name cannot be a planned location")


def planned_deliverable_boundary(e):
    """S14 其九：计划交付文件的边界四例——比较取完整单元目录加 `/` 为前缀。"""
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    repo.write("mechanisms/demo-x/HarnessPlane_X_Design_v1.md", "x"); repo.write("records/keep.md", "k"); repo.commit("sibling")
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    text = "`mechanisms/demo/sub/future.py` `mechanisms/demo-x/future.py` `mechanisms/other/future.py` `records/future.md`\n"
    res, _f = I.resolve_references(repo.root, [(cand, text)], [], [], cl)
    st = {r["token"]: r["status"] for r in res}
    e.check(st["mechanisms/demo/sub/future.py"] == "planned", "beneath the candidate's unit directory (any depth) → planned")
    e.check(st["mechanisms/demo-x/future.py"] == "unresolved", "sibling directory sharing the name prefix → unresolved (prefix is unit dir plus '/')")
    e.check(st["mechanisms/other/future.py"] == "unresolved", "same first segment, other unit → unresolved")
    e.check(st["records/future.md"] == "unresolved", "other existing top-level member → unresolved")
    res, _f = I.resolve_references(repo.root, [("AGENTS.md", "`mechanisms/nope.py`\n")], [], [], cl)
    e.check(res[0]["status"] == "unresolved", "candidate at the repository root has no unit directory → nothing is planned")


def bundle_names(e):
    """S17 投递名整束全局唯一；S19 送审形态（受锁件为 candidate，清单 role 与哈希）。"""
    D = I.derive_bundle_names
    task = "HarnessPlane_Demo_Review_Task_R2.md"
    prev = ["previous--candidate-baseline--x.md", "previous--verdict.md", "previous--bundle_manifest.json", "previous--receipt.json"]
    srcs = ["mechanisms/demo/HarnessPlane_Demo_Design_v1.md", "a/notes.md", "b/notes.md", "x/AGENTS.md", "docs/" + task, "a--b/c/x--y.md", "a/b--c/x--y.md",
            "p/previous--notes.md", "q/source--notes.md"]
    names = D(srcs, [task] + prev)
    vals = list(names.values())
    e.check(len(set(vals)) == len(vals) and task not in vals and not (set(vals) & set(prev)), "all bundle names distinct and none equals a fixed name: %s" % names)
    e.check(names["a/notes.md"] == "notes.md" and names["b/notes.md"] == "b--notes.md", "same basename: lexicographic first keeps the basename, next extends one segment")
    e.check(names["x/AGENTS.md"] == "source--AGENTS.md", "forbidden name renamed with the rename prefix")
    e.check(names["docs/" + task] == "docs--" + task, "basename equal to the task book name is extended")
    e.check(names["p/previous--notes.md"] == "p--previous--notes.md" and names["q/source--notes.md"] == "q--source--notes.md",
            "initial basename carrying a reserved prefix is treated as a conflict even without an exact clash: %s" % names)
    e.check(sorted(vals) == sorted(D(list(reversed(srcs)), [task] + prev).values()) and names == D(list(reversed(srcs)), [task] + prev),
            "derivation is byte-identical regardless of the caller's list order")
    e.check(names["a--b/c/x--y.md"] != names["a/b--c/x--y.md"], "segments containing '--' still distinguished while segments remain")
    e.check(D(["AGENTS.md"], [task]) == {"AGENTS.md": "source--AGENTS.md"}, "root-level forbidden-name file keeps the generated source-- name (ban not applied to it)")
    e.expect_error(lambda: D(["a.md", "b.md", "a.md"], []), code="duplicate-reference-source", message="same source listed twice is refused before derivation")
    e.expect_error(lambda: D([task], [task]), code="bundle-name-collision", message="root-level file equal to a fixed name has no segments left")
    e.expect_error(lambda: D(["AGENTS.md", "source--AGENTS.md"], []), code="bundle-name-collision",
                   message="root-level rename result clashing with an earlier root-level name: segments exhausted")
    # S19：受锁设计正本自任 candidate，清单 role 为 candidate 的成员哈希 = 该字节（C1 可成立）；Changelog 作 candidate 则不成立
    repo = e.iso_repo()
    repo.write("changelog/CL-1.md", "changelog"); repo.commit("cl")
    design = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    _sd, pre = I.seal_inputs(repo.root, e.tmpdir("s19a"), design, ["changelog/CL-1.md"], fixed_names=["T.md"])
    cands = [p for p in pre if p["role"] == "candidate"]
    e.check(len(cands) == 1 and cands[0]["sha256"] == base.sha256_bytes(repo.read(design)) and cands[0]["source"] == design, "locked master as candidate: reviewed candidate hash equals the frozen bytes")
    _sd, pre = I.seal_inputs(repo.root, e.tmpdir("s19b"), "changelog/CL-1.md", [design], fixed_names=["T.md"])
    e.check(all(p["sha256"] != base.sha256_bytes(repo.read(design)) for p in pre if p["role"] == "candidate"), "Changelog as candidate: the locked bytes never enter the candidate role (C1 would fail)")


def sealing(e):
    repo = e.iso_repo()
    att = e.tmpdir("att")
    repo.write("AGENTS.md", "agents-v1\n")
    seal_dir, pre = I.seal_inputs(repo.root, att, "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["AGENTS.md"])
    names = [p["bundle_name"] for p in pre]
    e.check(names == ["HarnessPlane_Demo_Design_v1.md", "source--AGENTS.md"], "forbidden name renamed: %s" % names)
    e.check(oct(os.stat(os.path.join(seal_dir, "source--AGENTS.md")).st_mode)[-3:] == "444", "sealed copy read-only")
    repo.write("AGENTS.md", "agents-v2\n")
    e.check(base.read_bytes(os.path.join(seal_dir, "source--AGENTS.md")) == b"agents-v1\n", "source change after sealing does not affect the copy")
    e.check(pre[1]["sha256"] == base.sha256_bytes(b"agents-v1\n"), "manifest records the sealed bytes")
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att2"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["ghost.md"]),
                   code="reference-unreadable", message="unreadable reference")
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att3"), "nope.md", []), code="candidate-unreadable", message="unreadable candidate")
    # R2-B1：符号链接不得把仓外字节带入被审输入
    outside = os.path.join(e.tmpdir("outside"), "secret.md")
    open(outside, "w").write("outside")
    os.symlink(outside, repo.path("mechanisms/demo/link.md"))
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att5"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["mechanisms/demo/link.md"]),
                   code="reference-unreadable", message="symlink to an outside file refused")
    os.symlink(repo.path("AGENTS.md"), repo.path("mechanisms/demo/inlink.md"))
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att6"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["mechanisms/demo/inlink.md"]),
                   code="reference-unreadable", message="any symlink segment refused")
    os.symlink(e.tmpdir("outdir"), repo.path("mechanisms/linkdir"))
    open(os.path.join(os.readlink(repo.path("mechanisms/linkdir")), "f.md"), "w").write("x")
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att7"), "mechanisms/linkdir/f.md", []), code="candidate-unreadable",
                   message="symlinked directory segment refused for the candidate")
    repo.write("x/AGENTS.md", "a")
    _sd4, pre4 = I.seal_inputs(repo.root, e.tmpdir("att4"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["AGENTS.md", "x/AGENTS.md"])
    e.check([p["bundle_name"] for p in pre4] == ["HarnessPlane_Demo_Design_v1.md", "source--AGENTS.md", "x--AGENTS.md"],
            "two forbidden-name sources: root keeps source--, the other extends a segment: %s" % [p["bundle_name"] for p in pre4])
    repo.write("HarnessPlane_Demo_Design_v1.md", "root twin")
    _sd4b, pre4b = I.seal_inputs(repo.root, e.tmpdir("att4b"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["HarnessPlane_Demo_Design_v1.md"])
    e.check([p["bundle_name"] for p in pre4b] == ["demo--HarnessPlane_Demo_Design_v1.md", "HarnessPlane_Demo_Design_v1.md"],
            "root-level twin of the candidate basename: lexicographic order gives the root file the basename, the candidate extends: %s" % [p["bundle_name"] for p in pre4b])
    repo.write("HarnessPlane_Demo_Review_Task_R1.md", "task twin")
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att4c"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["HarnessPlane_Demo_Review_Task_R1.md"],
                                         fixed_names=["HarnessPlane_Demo_Review_Task_R1.md"]),
                   code="bundle-name-collision", message="root-level file equal to the task book name exhausts its segments")
    # R3-B1：仓界前置读取原语是唯一读取路径——符号链接 / 目录 / 越界一律在打开时刻拒绝
    e.check(I.read_repo_file(repo.root, "AGENTS.md", "reference") == b"agents-v2\n", "primitive reads bytes")
    e.expect_error(lambda: I.read_repo_file(repo.root, "mechanisms/demo/link.md", "candidate"), code="candidate-unreadable", message="symlink refused by the primitive")
    e.expect_error(lambda: I.read_repo_file(repo.root, "mechanisms/demo", "reference"), code="reference-unreadable", message="directory is not a regular file")
    e.expect_error(lambda: I.read_repo_file(repo.root, "mechanisms/linkdir/f.md", "reference"), code="reference-unreadable", message="symlinked segment")
    # R4-B1：引用解析所用字节与封存字节绑定
    e.expect_error(lambda: I.seal_inputs(repo.root, e.tmpdir("att8"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", [], candidate_bytes=b"stale"),
                   code="seal-mismatch", message="candidate changed between reference resolution and sealing")
    I.seal_inputs(repo.root, e.tmpdir("att9"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", [],
                  candidate_bytes=base.read_bytes(repo.path("mechanisms/demo/HarnessPlane_Demo_Design_v1.md")))
    # R6-B3：秘密扫描先于写入
    att10 = e.tmpdir("att10")
    e.expect_error(lambda: I.seal_inputs(repo.root, att10, "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", ["AGENTS.md"], scan_set=[b"agents-v2"]),
                   code="secret-in-input", message="reference carrying a secret refused")
    e.check(not os.path.exists(os.path.join(att10, "inputs", "source--AGENTS.md")), "nothing written for the refused reference")
    seal11, pre11 = I.seal_inputs(repo.root, e.tmpdir("att11"), "mechanisms/demo/HarnessPlane_Demo_Design_v1.md", [], scan_set=[b"nope"])
    e.expect_error(lambda: I.add_sealed_bytes(seal11, pre11, "T.md", b"task with sk-x", "review-task", "(x)", scan_set=[b"sk-x"]),
                   code="secret-in-input", message="generated bundle member carrying a secret refused")
    e.check(not os.path.exists(os.path.join(seal11, "T.md")), "nothing written for the refused task book")
    src = open(os.path.join(e.unit_dir, "review_channel_inputs.py"), encoding="utf-8").read()
    prim = src.split("def read_repo_file(")[1].split("def seal_inputs(")[0]
    e.check(prim.count("dir_fd=fds[-1]") == 2 and "os.O_DIRECTORY" in prim and "islink(" not in prim, "static: ancestors opened by descriptor chain, not checked by path (R4-B1)")
    body = src.split("def seal_inputs(")[1].split("def add_sealed_bytes(")[0]
    e.check("read_bytes(" not in body and "open(" not in body and "filecmp" not in src and body.count("read_repo_file(") == 2,
            "static: sealing reads the source only through the boundary primitive (twice: copy and cmp)")
    entry = open(os.path.join(e.unit_dir, "review_channel.py"), encoding="utf-8").read().split("    def run(self):")[1].split("    def _last_round_blocking")[0]
    e.check("read_bytes(" not in entry and "read_repo_file(" in entry, "static: the preflight checklist reads the candidate only through the primitive")
    man = I.manifest_document("demo", "impl", "r1", "T.md", pre)
    e.check(man["manifest_sha256"] == base.sha256_bytes(base.canonical_json(pre)) and man["task_file"] == "T.md", "manifest hash over canonical inputs")
    e.check(I.taskbook_filename("gov-t8-task", "r3") == "HarnessPlane_Gov_T8_Review_Task_R3.md"
            and I.verdict_filename("review-channel", "r12") == "HarnessPlane_Review_Channel_Review_R12.md", "file names")


def baseline_recovery(e):
    repo = e.iso_repo()
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    v1 = repo.read(cand)
    repo.write(cand, v1.decode() + "\nchanged\n")
    repo.commit("v2")
    got = I.recover_baseline(repo.root, cand, base.sha256_bytes(v1), os.path.join(repo.root, "tasks/gov-t1/attempts/impl-r1"))
    e.check(got == v1, "baseline from git history")
    att = os.path.join(repo.root, "tasks/gov-t1/attempts/impl-r1/A1/inputs")
    os.makedirs(att)
    open(os.path.join(att, "HarnessPlane_Demo_Design_v1.md"), "wb").write(b"sealed-copy")
    got = I.recover_baseline(repo.root, cand, base.sha256_bytes(b"sealed-copy"), os.path.join(repo.root, "tasks/gov-t1/attempts/impl-r1"))
    e.check(got == b"sealed-copy", "baseline from attempts sealed copy preferred")
    e.check(I.recover_baseline(repo.root, cand, "0" * 64, None) is None, "unrecoverable returns None")
    seal_dir = e.tmpdir("seal")
    pre = []
    previous = {"manifest": {"inputs": [{"role": "candidate", "source": cand, "sha256": "0" * 64, "bundle_name": "x.md"}]},
                "verdict_bytes": b"v", "verdict_path": "p", "receipt_bytes": b"r", "receipt_path": "q", "manifest_bytes": b"m", "manifest_path": "m"}
    e.expect_error(lambda: I.add_previous_round_inputs(repo.root, seal_dir, pre, previous, None, current_candidate_sources=[cand]), code="baseline-unrecoverable", message="unrecoverable")
    previous["manifest"]["inputs"][0]["sha256"] = base.sha256_bytes(v1)
    # Amendment 2：候选集合与上一轮不等 → inherit-unanchored
    e.expect_error(lambda: I.add_previous_round_inputs(repo.root, seal_dir, pre, previous, None, current_candidate_sources=["other.md"]), code="inherit-unanchored", message="candidate set changed")
    got = I.add_previous_round_inputs(repo.root, seal_dir, pre, previous, None, current_candidate_sources=[cand])
    e.check(got == {cand: v1}, "per-candidate baselines returned")
    e.check([p["bundle_name"] for p in pre] == ["previous--candidate-baseline--x.md", "previous--verdict.md", "previous--bundle_manifest.json", "previous--receipt.json"],
            "previous-- four members")


def multi_candidate(e):
    """Amendment 2 多候选：候选互引记 co-candidate、逐候选基线固定名、封存保持清单候选次序。"""
    repo = e.iso_repo()
    cl = I.root_closure(repo.root)
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    res, fail = I.resolve_references(repo.root, [(cand, "Cites `AGENTS.md`.\n"), ("AGENTS.md", "Cites `%s`.\n" % cand)], [], [], cl)
    e.check(fail is None and [r["status"] for r in res] == ["co-candidate", "co-candidate"] and [r["candidate"] for r in res] == [cand, "AGENTS.md"],
            "candidates citing each other resolve as co-candidate: %s" % [(r["candidate"], r["status"]) for r in res])
    man = {"inputs": [{"role": "candidate", "bundle_name": "a.md"}, {"role": "candidate", "bundle_name": "b.md"}, {"role": "reference", "bundle_name": "r.md"}]}
    e.check(I.previous_bundle_names(man) == ["previous--candidate-baseline--a.md", "previous--candidate-baseline--b.md", "previous--verdict.md",
                                              "previous--bundle_manifest.json", "previous--receipt.json"], "3 + candidate count fixed names")
    seal_dir, pre = I.seal_inputs(repo.root, e.tmpdir("mc"), ["AGENTS.md", cand], [])
    e.check([p["source"] for p in pre if p["role"] == "candidate"] == ["AGENTS.md", cand], "candidate order preserved in the pre-manifest")


def _fact(revision, event, *paths):
    return json.dumps({"revision": revision, "event": event, "objects": [{"path": p, "bytes": 1, "sha256": "0" * 64} for p in paths]}) + "\n"


def current_revision_annotation(e):
    """§6.2 第 2 条（减重第 3 步，F3 甲）：现行修订号只作标注、恒不判失败码；读取次序按 freeze-record 设计 §4.3——
    其一 `freeze-records.jsonl` 最后一行 freeze / re-freeze（retire 行不改变现行修订号，其 objects[] 自该行起不在冻结面内）、
    其二无该文件时取编号最大的 `.md` 记录文件名；subject 由引用路径反查（机制正本 = 单元目录名；规划基线件 = 各 subject 的
    objects[].path 命中，无命中再按文件名去扩展名）。"""
    repo = e.iso_repo()
    gov = "records/governance/"
    e.check(I.current_revision(repo.root, "sdd/spec.md") is None, "no governance record at all → unobtainable, no exception")
    # 其一：最后一行 freeze / re-freeze 决定现行修订号；retire 行不改变它，但其 objects[] 自该行起不在冻结面内
    repo.write(gov + "spec/freeze-records.jsonl", _fact(1, "freeze", "sdd/spec.md") + _fact(2, "re-freeze", "sdd/spec.md", "sdd/other.md")
               + _fact(2, "retire", "sdd/other.md"))
    e.check(I.current_revision(repo.root, "sdd/spec.md") == 2, "last freeze / re-freeze row wins (not the first)")
    e.check(I.current_revision(repo.root, "sdd/other.md") is None, "a path retired after the current fact has no current revision")
    repo.write(gov + "spec/freeze-records.jsonl", _fact(1, "freeze", "sdd/spec.md") + _fact(2, "retire", "sdd/spec.md") + _fact(3, "re-freeze", "sdd/spec.md"))
    e.check(I.current_revision(repo.root, "sdd/spec.md") == 3, "a re-freeze after a retire row re-establishes the path")
    # 其一优先于其二：该 subject 已有 jsonl 时不回退到编号更大的 .md 记录
    repo.write(gov + "spec/HarnessPlane_Spec_Freeze_Record_r7.md", "# r7\n")
    e.check(I.current_revision(repo.root, "sdd/spec.md") == 3, "the jsonl fact is not overridden by a larger-numbered .md record")
    # 规划基线件经其他 subject 的 objects[].path 命中（milestones.md 的记录住 milestones-fused）
    repo.write(gov + "milestones-fused/freeze-records.jsonl", _fact(11, "re-freeze", "sdd/milestones.md"))
    e.check(I.current_revision(repo.root, "sdd/milestones.md") == 11, "planning baseline found through another subject's objects[].path")
    # 其二：无 jsonl 时取编号最大的 .md（数值比较，非字典序）；不合 §4.1 文法的名字不计入
    repo.write(gov + "proposal/HarnessPlane_Proposal_Freeze_Record_r3.md", "# r3\n")
    repo.write(gov + "proposal/HarnessPlane_Proposal_Freeze_Record_r10.md", "# r10\n")
    repo.write(gov + "proposal/HarnessPlane_Proposal_Freeze_Record_r011.md", "# bad\n")
    repo.write(gov + "proposal/HarnessPlane_Other_Freeze_Record_r99.md", "# stray\n")
    e.check(I.current_revision(repo.root, "sdd/proposal.md") == 10, ".md fallback takes the numerically largest well-formed record name")
    # 机制正本：subject = 单元目录名
    repo.write(gov + "demo/HarnessPlane_Demo_Freeze_Record_r2.md", "# r2\n")
    e.check(I.current_revision(repo.root, "mechanisms/demo/HarnessPlane_Demo_Design_v1.md") == 2, "mechanism master: subject is its unit directory name")
    repo.write(gov + "demo/freeze-records.jsonl", _fact(4, "re-freeze", "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"))
    e.check(I.current_revision(repo.root, "mechanisms/demo/HarnessPlane_Demo_Design_v1.md") == 4, "mechanism master: jsonl fact preferred once present")
    # 形态问题恒不判失败码：不可严格解析、revision 非整数、无 freeze / re-freeze 行
    repo.write(gov + "spec/freeze-records.jsonl", "{not json}\n")
    e.check(I.current_revision(repo.root, "sdd/spec.md") is None, "unparseable jsonl → unobtainable, no exception")
    repo.write(gov + "spec/freeze-records.jsonl", json.dumps({"revision": "5", "event": "freeze", "objects": [{"path": "sdd/spec.md"}]}) + "\n")
    e.check(I.current_revision(repo.root, "sdd/spec.md") is None, "non-integer revision → unobtainable")
    repo.write(gov + "spec/freeze-records.jsonl", _fact(5, "retire", "sdd/spec.md"))
    e.check(I.current_revision(repo.root, "sdd/spec.md") is None, "retire-only file → unobtainable (the .md fallback is not consulted while the jsonl exists)")
    # 解析面：域一引用带任何修订号都放行，条目携带现行修订号标注；无记录时标注 None
    repo.write("sdd/spec.md", "s")
    repo.write(gov + "spec/freeze-records.jsonl", _fact(5, "re-freeze", "sdd/spec.md"))
    repo.commit("spec")
    cl = I.root_closure(repo.root)
    cand = "mechanisms/demo/HarnessPlane_Demo_Design_v1.md"
    for cited in (1, 5, 9):
        res, fail = I.resolve_references(repo.root, [(cand, "Cites `spec.md@r%d`.\n" % cited)], ["sdd/spec.md"], [], cl)
        e.check(fail is None and res[0]["status"] == "delivered" and res[0]["revision"] == cited and res[0]["current_revision"] == 5
                and "earliest_revision" not in res[0] and "archive_reason" not in res[0],
                "spec.md@r%d resolves on path alone with the current revision annotated: %s" % (cited, res[0]))
    src = open(os.path.join(e.unit_dir, "review_channel_inputs.py"), encoding="utf-8").read()
    e.check("PreflightError" not in src.split("def _object_paths(")[1].split("def planned_location_check(")[0],
            "static: the current-revision reader raises no failure code")
    # r1 基线身份（§6.2 第 6 条，Amendment 4）：jsonl 行 objects[].sha256；.md 记录取 fenced JSON 的 frozen_objects[].sha256；
    # 雏形记录（无围栏）身份不可得（sha256 None、修订号仍在场）；任何冻结事实内无该路径 → None（首冻）
    fact = I.current_freeze_fact(repo.root, "sdd/spec.md")
    e.check(fact == {"revision": 5, "sha256": "0" * 64, "subject": "spec"}, "jsonl fact carries the object sha256: %s" % fact)
    e.check(I.current_freeze_fact(repo.root, "sdd/proposal.md") == {"revision": 10, "sha256": None, "subject": "proposal"}, "prototype .md record: revision without an identity")
    fence = "# r3\n\n```freeze-record\n" + json.dumps({"record_schema": "freeze-record/v1", "subject": "other", "revision": 3, "event": "re-freeze",
                                                          "frozen_objects": [{"path": "sdd/other.md", "bytes": 1, "sha256": "a" * 64}]}, indent=1) + "\n```\n"
    repo.write(gov + "other/HarnessPlane_Other_Freeze_Record_r3.md", fence)
    e.check(I.current_freeze_fact(repo.root, "sdd/other.md") == {"revision": 3, "sha256": "a" * 64, "subject": "other"}, ".md record with a fenced machine master: identity from frozen_objects[]")
    e.check(I.current_freeze_fact(repo.root, "sdd/stranger.md") is None and I.current_revision(repo.root, "sdd/stranger.md") is None, "no freeze fact anywhere → None (first freeze)")
    repo.write(gov + "other/HarnessPlane_Other_Freeze_Record_r4.md", "# r4\n\n```freeze-record\n{\"frozen_objects\": [{\"path\": \"sdd/elsewhere.md\", \"sha256\": \"%s\"}]}\n```\n" % ("b" * 64))
    e.check(I.current_freeze_fact(repo.root, "sdd/other.md") is None, "a fenced record whose frozen_objects[] lacks the path is not that path's record")
    repo.write(gov + "other/HarnessPlane_Other_Freeze_Record_r5.md", "# r5\n\n```freeze-record\n{not json\n```\n")
    e.check(I.current_freeze_fact(repo.root, "sdd/other.md") == {"revision": 5, "sha256": None, "subject": "other"}, "unparseable fenced block → identity unobtainable, no exception")


def cases():
    return [
        ("inputs.closure-from-catalog", closure_from_catalog),
        ("inputs.reference-three-way", reference_three_way),
        ("inputs.reference-domains", reference_domains),
        ("inputs.current-revision-annotation", current_revision_annotation),
        ("inputs.decision-form-excluded", decision_form_excluded),
        ("inputs.planned-location", planned_location),
        ("inputs.planned-deliverable-boundary", planned_deliverable_boundary),
        ("inputs.bundle-names", bundle_names),
        ("inputs.sealing", sealing),
        ("inputs.baseline-recovery", baseline_recovery),
        ("inputs.multi-candidate", multi_candidate),
    ]
