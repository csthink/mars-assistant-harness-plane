"""layout 可选核对。规则 ID、布局权威关联及实际判定均在本模块声明。"""
import fnmatch
import re

import gates_base as base


# ---------------------------------------------------------------- top-level-members

def applies_top_level_members(ctx):
    return True


def precondition_top_level_members(ctx):
    if ctx.profile.top_level_members is None:
        return "安装形态的合法顶层集合尚未出生（gov-t13）"
    return None


def check_top_level_members(ctx):
    allowed = ctx.profile.top_level_members
    return [base.Finding(name + "/", "top-level-members", "计划外顶层目录")
            for name in sorted(base.top_level_dirs(ctx)) if name not in allowed]


# ---------------------------------------------------------------- required-instance-dirs

def applies_required_instance_dirs(ctx):
    return True


def precondition_required_instance_dirs(ctx):
    return None


def check_required_instance_dirs(ctx):
    present = base.top_level_dirs(ctx)
    return [base.Finding(name + "/", "required-instance-dirs", "必备目录缺失")
            for name in ("sdd", "tasks", "records") if name not in present]


# ---------------------------------------------------------------- on-demand-dirs-common

def applies_on_demand_dirs_common(ctx):
    names = ctx.profile.on_demand_dirs_common
    tops = base.top_level_dirs(ctx) | {n for (n, _e) in base.root_entries(ctx)}
    return bool(names & tops)


def precondition_on_demand_dirs_common(ctx):
    return None


def check_on_demand_dirs_common(ctx):
    findings = []
    tops = base.top_level_dirs(ctx)
    root_names = {n for (n, _e) in base.root_entries(ctx)}
    for name in sorted(ctx.profile.on_demand_dirs_common):
        if name in root_names and name not in tops:
            findings.append(base.Finding(
                name, "on-demand-dirs-common", "按需目录的出生形态须为目录，实为文件条目"))
    return findings


# ---------------------------------------------------------------- on-demand-dirs-local

def applies_on_demand_dirs_local(ctx):
    names = ctx.profile.on_demand_dirs_local
    if not names:
        return False
    tops = base.top_level_dirs(ctx) | {n for (n, _e) in base.root_entries(ctx)}
    return bool(names & tops)


def precondition_on_demand_dirs_local(ctx):
    return None


def check_on_demand_dirs_local(ctx):
    findings = []
    tops = base.top_level_dirs(ctx)
    root_names = {n for (n, _e) in base.root_entries(ctx)}
    for name in sorted(ctx.profile.on_demand_dirs_local):
        if name in root_names and name not in tops:
            findings.append(base.Finding(
                name, "on-demand-dirs-local", "按需目录的出生形态须为目录，实为文件条目"))
    return findings


# ---------------------------------------------------------------- root-tracked-closure

def applies_root_tracked_closure(ctx):
    return True


def precondition_root_tracked_closure(ctx):
    if ctx.profile.root_tracked_members is None:
        return "安装形态的仓根闭集尚未出生（gov-t13）"
    return None


def check_root_tracked_closure(ctx):
    # 工作树中存在的受跟踪仓根文件须属于声明集合。
    allowed = ctx.profile.root_tracked_members
    tracked = ctx.tracked_paths()
    return [base.Finding(name, "root-tracked-closure", "仓根计划外受跟踪文件")
            for (name, _e) in sorted(base.root_entries(ctx))
            if name in tracked and name not in allowed]


# ---------------------------------------------------------------- sdd-members

def applies_sdd_members(ctx):
    return True


def precondition_sdd_members(ctx):
    return None


def check_sdd_members(ctx):
    required = {"proposal.md", "spec.md", "milestones.md"}
    allowed = required | {"architecture.md"}
    if "sdd" not in base.top_level_dirs(ctx):
        return [base.Finding("sdd/", "sdd-members", "sdd/ 缺失")]
    findings = []
    files = base.dir_files(ctx, "sdd")
    names = {n for (n, _e) in files}
    for name, entry in files:
        if name in allowed and entry.type != "file":
            findings.append(base.Finding("sdd/" + name, "sdd-members", "sdd/ 成员须为普通文件"))
    for extra in sorted(names - allowed):
        findings.append(base.Finding("sdd/" + extra, "sdd-members", "sdd/ 允许集合之外的成员"))
    for missing in sorted(required - names):
        findings.append(base.Finding("sdd/" + missing, "sdd-members", "规格链件缺失"))
    for sub in sorted(base.dir_subdirs(ctx, "sdd")):
        findings.append(base.Finding("sdd/" + sub + "/", "sdd-members", "sdd/ 不得含子目录"))
    return findings


# ---------------------------------------------------------------- unit-dir-grammar

def applies_unit_dir_grammar(ctx):
    return ctx.profile.kind == "bootstrap"


def precondition_unit_dir_grammar(ctx):
    return None


def check_unit_dir_grammar(ctx):
    findings = []
    if "mechanisms" not in base.top_level_dirs(ctx):
        return findings
    for (name, _e) in sorted(base.dir_files(ctx, "mechanisms")):
        if name != "MECHANISMS.md":
            findings.append(base.Finding(
                "mechanisms/" + name, "unit-dir-grammar",
                "mechanisms/ 直下只允许 MECHANISMS.md 与单元目录"))
    # 单元内部成员与子目录一律不判：布局权威 §5.1 末槽为开放槽位、单元内部形态由各单元
    # 权威自定（Amendment 10 删除 r11 的 hooks/ 与 fixtures/ 子目录闭集，gov-t8:KB-02）。
    return findings


# ---------------------------------------------------------------- design-master-header

def applies_design_master_header(ctx):
    if ctx.profile.kind != "bootstrap":
        return False
    if "mechanisms" not in base.top_level_dirs(ctx):
        return False
    for unit in base.dir_subdirs(ctx, "mechanisms"):
        for (name, _e) in base.dir_files(ctx, "mechanisms/" + unit):
            if fnmatch.fnmatch(name, "HarnessPlane_*_Design_v*.md"):
                return True
    return False


def precondition_design_master_header(ctx):
    return None


def check_design_master_header(ctx):
    # 布局权威 §5.1 冻结的页首文法逐项落实（impl-r17 R17-B4）：
    # H1 → 恰一空行 → 引用块（首行「> Depends on:」、依赖一行一件、空引用行、
    # 末行为冻结形态的「> 权威状态」且 subject = 单元名）→ 空行。页首不得有额外标题。
    dep_re = re.compile(r"^> `([^`]+)`( [^`]+)?$")
    # 反引号之外的后缀须确为条目 ID 列表（impl-r18 R18-B3）：ID 形如 FR-35 / gov-t0 /
    # M-01--字母起始、可含连字符、至少含一位数字；以顿号或空格分隔。散文后缀不合法。
    id_re = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
    findings = []
    for unit in sorted(base.dir_subdirs(ctx, "mechanisms")):
        for (name, _e) in sorted(base.dir_files(ctx, "mechanisms/" + unit)):
            if not fnmatch.fnmatch(name, "HarnessPlane_*_Design_v*.md"):
                continue
            path = "mechanisms/%s/%s" % (unit, name)
            try:
                text = ctx.read(path).decode("utf-8")
            except Exception:
                findings.append(base.Finding(path, "design-master-header", "正文不可读或非 UTF-8"))
                continue
            lines = text.split("\n")
            problems = []
            if len(lines) < 6 or not lines[0].startswith("# "):
                problems.append("首行须为 H1 标题")
            elif lines[1] != "":
                problems.append("H1 之后须恰一空行，随后直接接页首引用块")
            elif lines[2] != "> Depends on:":
                problems.append("页首第一项须为「> Depends on:」，其间不得有额外内容")
            else:
                i = 2
                block = []
                while i < len(lines) and lines[i].startswith(">"):
                    block.append(lines[i])
                    i += 1
                if i >= len(lines) or lines[i] != "":
                    problems.append("页首引用块之后须为空行")
                status_expected = ("> 权威状态: subject `%s`"
                                   "（治理记录目录按所在仓的布局规则解析；唯一状态正本）" % unit)
                if len(block) < 4:
                    problems.append("页首引用块须含依赖行、空引用行与权威状态行")
                else:
                    if block[-1] != status_expected:
                        problems.append(
                            "页首第二项（末行）须为冻结形态的权威状态行且 subject 为单元名")
                    if block[-2] != ">":
                        problems.append("Depends on 与权威状态之间须为一行空引用行")
                    deps = block[1:-2]
                    if not deps:
                        problems.append("Depends on 之下须有依赖行（无依赖时单行写「> 无」）")
                    for ln in deps:
                        if ln == "> 无":
                            if len(deps) != 1:
                                problems.append("「> 无」只允许单独成行")
                            continue
                        m = dep_re.match(ln)
                        if not m:
                            problems.append("依赖行须为「> `<裸文件名>`[ <条目 ID 列表>]」：%r" % ln)
                            continue
                        token, extra = m.group(1), m.group(2) or ""
                        if "/" in token or "/" in extra:
                            problems.append("依赖须用裸文件名、不写路径：%r" % ln)
                        if "§" in ln:
                            problems.append("依赖行不得写章节号或章节名：%r" % ln)
                        if "FROZEN" in ln or "FINALIZED" in ln:
                            problems.append("依赖行不得写被依赖件冻结状态：%r" % ln)
                        for tok in re.split(r"[、 ]+", extra.strip()):
                            if tok and not (id_re.match(tok)
                                            and any(c.isdigit() for c in tok)):
                                problems.append(
                                    "依赖行后缀须为条目 ID 列表，非 ID 记号：%r" % tok)
            for prob in problems:
                findings.append(base.Finding(path, "design-master-header", prob))
    return findings


# ---------------------------------------------------------------- task-id-grammar

def applies_task_id_grammar(ctx):
    return "tasks" in base.top_level_dirs(ctx)


def precondition_task_id_grammar(ctx):
    return None


def check_task_id_grammar(ctx):
    pattern = re.compile(r"^(feature|design|gov)-t\d+$")
    return [base.Finding("tasks/" + name + "/", "task-id-grammar",
                         "任务目录名须匹配 feature-t<N> | design-t<N> | gov-t<N>")
            for name in sorted(base.dir_subdirs(ctx, "tasks"))
            if not pattern.match(name)]


# ---------------------------------------------------------------- evidence-shape

def applies_evidence_shape(ctx):
    dirs = base.scan(ctx)["dirs"]
    return "reviews" in dirs or "records/governance" in dirs


def precondition_evidence_shape(ctx):
    return None


def check_evidence_shape(ctx):
    findings = []
    dirs = base.scan(ctx)["dirs"]
    if "reviews" in dirs:
        for (name, _e) in sorted(base.dir_files(ctx, "reviews")):
            findings.append(base.Finding(
                "reviews/" + name, "evidence-shape",
                "reviews/ 直下须为 subject 目录，不得直接放文件"))
        for subject in sorted(base.dir_subdirs(ctx, "reviews")):
            for (name, _e) in sorted(base.dir_files(ctx, "reviews/" + subject)):
                findings.append(base.Finding(
                    "reviews/%s/%s" % (subject, name), "evidence-shape",
                    "评审证据须为 reviews/<subject>/<round>/ 两级"))
    if "records/governance" in dirs:
        for (name, _e) in sorted(base.dir_files(ctx, "records/governance")):
            findings.append(base.Finding(
                "records/governance/" + name, "evidence-shape",
                "治理记录须住 records/governance/<subject>/，目录名由单元名派生"))
    return findings


# ---------------------------------------------------------------- staging-not-tracked

def applies_staging_not_tracked(ctx):
    return True


def precondition_staging_not_tracked(ctx):
    # .gitignore 缺失是违规（由 check 报）；存在却不可读或非 UTF-8 是前置不可得
    # → NOT_CHECKED，不得伪装成违规（impl-r17 R17-B6）。
    try:
        raw = ctx.read(".gitignore")
    except FileNotFoundError:
        ctx.cache["gitignore_lines"] = None
        return None
    except Exception as exc:
        return ".gitignore 存在却不可读（%s）" % type(exc).__name__
    try:
        ctx.cache["gitignore_lines"] = raw.decode("utf-8", "strict").split("\n")
    except UnicodeDecodeError:
        return ".gitignore 不是合法 UTF-8，排除行无从判定"
    return None


def check_staging_not_tracked(ctx):
    findings = []
    staging_re = re.compile(r"^(review-attempts/|tasks/[^/]+/attempts/)")
    for p in sorted(ctx.tracked_paths()):
        if staging_re.match(p):
            findings.append(base.Finding(p, "staging-not-tracked", "本地暂存层出现受跟踪文件"))
    lines = ctx.cache.get("gitignore_lines")
    if lines is None:
        findings.append(base.Finding(
            ".gitignore", "staging-not-tracked", ".gitignore 缺失，两条暂存层排除不存在"))
        return findings
    # 排除行逐字比对；不重实现 Git 通配语义。跟踪查询另检查实际入 Git 的暂存文件。
    for required in ("review-attempts/", "tasks/*/attempts/"):
        if required not in lines:
            findings.append(base.Finding(
                ".gitignore", "staging-not-tracked", "缺少暂存层排除行：%s" % required))
    return findings


# ---------------------------------------------------------------- 门声明

RULES = [
    base.Rule("top-level-members", "repo-layout §4", "分层",
              applies_top_level_members, precondition_top_level_members,
              check_top_level_members),
    base.Rule("required-instance-dirs", "repo-layout §4 / §6.1 / §6.2 / §6.6", "必备",
              applies_required_instance_dirs, precondition_required_instance_dirs,
              check_required_instance_dirs),
    base.Rule("on-demand-dirs-common", "repo-layout §6.3", "按需",
              applies_on_demand_dirs_common, precondition_on_demand_dirs_common,
              check_on_demand_dirs_common),
    base.Rule("on-demand-dirs-local", "repo-layout §6.3 / §6.4 / §6.5 / §6.7", "本仓自举形态",
              applies_on_demand_dirs_local, precondition_on_demand_dirs_local,
              check_on_demand_dirs_local),
    base.Rule("root-tracked-closure", "repo-layout §8", "分层",
              applies_root_tracked_closure, precondition_root_tracked_closure,
              check_root_tracked_closure),
    base.Rule("sdd-members", "repo-layout §6.1", "必备",
              applies_sdd_members, precondition_sdd_members,
              check_sdd_members),
    base.Rule("unit-dir-grammar", "repo-layout §5.1", "本仓自举形态",
              applies_unit_dir_grammar, precondition_unit_dir_grammar,
              check_unit_dir_grammar),
    base.Rule("design-master-header", "repo-layout §5.1", "本仓自举形态",
              applies_design_master_header, precondition_design_master_header,
              check_design_master_header),
    base.Rule("task-id-grammar", "repo-layout §6.2", "恒适用",
              applies_task_id_grammar, precondition_task_id_grammar,
              check_task_id_grammar),
    base.Rule("evidence-shape", "repo-layout §7", "按需",
              applies_evidence_shape, precondition_evidence_shape,
              check_evidence_shape),
    base.Rule("staging-not-tracked", "repo-layout §7", "恒适用",
              applies_staging_not_tracked, precondition_staging_not_tracked,
              check_staging_not_tracked),
]

GATE = base.Gate("layout", tuple(RULES))
