"""manifest 可选核对：两份整文件 freshness 与清单数据完整性。"""
import gates_base as base
import gates_generate as gen


def applies_mechanisms_generated(ctx):
    return ctx.profile.kind == "bootstrap"


def precondition_mechanisms_generated(ctx):
    return gen.generation_precondition(ctx, "mechanisms/MECHANISMS.md")


def check_mechanisms_generated(ctx):
    return gen.compare(ctx, "mechanisms/MECHANISMS.md")


# ---------------------------------------------------------------- readme-generated

def applies_readme_generated(ctx):
    return True


def precondition_readme_generated(ctx):
    if ctx.profile.kind == "installed":
        return "下游安装形态的根 README 形态尚未出生（gov-t13）"
    return gen.generation_precondition(ctx, "README.md")


def check_readme_generated(ctx):
    return gen.compare(ctx, "README.md")


# ---------------------------------------------------------------- readme-data-complete

def applies_readme_data_complete(ctx):
    return True


def precondition_readme_data_complete(ctx):
    if ctx.profile.kind == "installed":
        return "下游安装形态的根 README 形态尚未出生（gov-t13）"
    entry = gen.generated_entry(ctx.catalog, "README.md")
    try:
        gen.load_readme_data(ctx, entry["data"])
    except gen.GenerationFailure as exc:
        return "数据文件前置不可得：%s" % exc
    return None


def check_readme_data_complete(ctx):
    entry = gen.generated_entry(ctx.catalog, "README.md")
    data = gen.load_readme_data(ctx, entry["data"])
    top = data.get("top_level")
    if not isinstance(top, dict):
        return [base.Finding(entry["data"], "readme-data-complete", "缺 top_level 对象")]
    findings = []
    for name in sorted(base.top_level_dirs(ctx)):
        if name not in top:
            findings.append(base.Finding(
                name + "/", "readme-data-complete",
                "磁盘发现的顶层条目未登记于 readme_data.json（清单过期）"))
    return findings


# ---------------------------------------------------------------- 门声明

RULES = [
    base.Rule("mechanisms-generated", "repo-layout §3.2 / §5.1", "本仓自举形态",
              applies_mechanisms_generated, precondition_mechanisms_generated,
              check_mechanisms_generated),
    base.Rule("readme-generated", "repo-layout §3.2 / §8", "分层",
              applies_readme_generated, precondition_readme_generated,
              check_readme_generated),
    base.Rule("readme-data-complete", "repo-layout §3.2 / §8", "分层",
              applies_readme_data_complete, precondition_readme_data_complete,
              check_readme_data_complete),
]

GATE = base.Gate("manifest", tuple(RULES))
