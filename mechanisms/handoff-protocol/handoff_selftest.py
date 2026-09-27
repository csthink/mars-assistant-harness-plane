#!/usr/bin/env python3
"""handoff_lint.py 与 handoff_status.py 的 selftest：每条文法规则各有正例与负例，三态退出码各有用例，
并含并发写场景（两个任务各自追加自己的进度文件、其一闭合另一铸造的项、git merge 零冲突、现算判 closed）。

调用：python3 mechanisms/handoff-protocol/handoff_selftest.py
退出码：0 = 全部用例通过；1 = 至少一条用例失败；2 = selftest 自身无法运行（git 不可用等）。
全部用例在临时目录内运行，不在工作树留副产物。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import handoff_lint as lint  # noqa: E402
import handoff_status as status  # noqa: E402

LINT = os.path.join(HERE, "handoff_lint.py")
STATUS = os.path.join(HERE, "handoff_status.py")
PY = [sys.executable, "-B", "-E", "-s", "-S"]
FAILS = []


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name}: {detail}")
    print(f"[{'ok' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail and not cond else ""))


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def run(args, cwd, env=None):
    cache = tempfile.mkdtemp(prefix="hs-pyc-")
    try:
        r = subprocess.run(PY + ["-X", f"pycache_prefix={cache}"] + args, cwd=cwd,
                           capture_output=True, env=env)
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, env=GIT_ENV)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8", "replace").strip()


GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="selftest", GIT_AUTHOR_EMAIL="selftest@example.invalid",
               GIT_COMMITTER_NAME="selftest", GIT_COMMITTER_EMAIL="selftest@example.invalid",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", HOME=tempfile.gettempdir())

# ---------------------------------------------------------------- 文法用例

REPO_MD = (
    "# task: repo\n"
    "- 类别: 仓级\n"
    "- 2026-09-07T10:00 · note · 仓级备忘\n"
    "- 2026-09-07T10:01 · open · repo:OD-01 · OD · 仓级待裁项 · 被什么挡住：等 Owner\n"
    "- 2026-09-07T10:02 · open · repo:OD-02 · OD · 第二个待裁项 · 被什么挡住：等 Owner\n"
    "- 2026-09-07T10:03 · open · legacy:KB-09 · KB · 旧档案项 · 现状：未处置（转录自 HANDOFF/LEDGER.md 第 9 行，登记 2026-08-25）\n"
)
TASK_MD = (
    "# task: repo-od-01\n"
    "- 类别: 台账任务 · 承载项 repo:OD-01 · 分支意图 work-a\n"
    "- 2026-09-07T10:10 · intent · step-a · 开工\n"
    "- 2026-09-07T10:20 · result · step-a · 候选入库 · commit:" + "a" * 40 + "\n"
    "- 2026-09-07T10:21 · open · repo-od-01:KB-01 · KB · 坏点一 · 现状：未修\n"
    "- 2026-09-07T10:22 · open · repo-od-01:OD-01 · OD · 待裁一 · 被什么挡住：等 Owner\n"
    "- 2026-09-07T10:23 · answer · repo-od-01:OD-01 · Owner 原话「先不做」 · until 2026-09-20\n"
    "- 2026-09-07T10:24 · close · repo-od-01:KB-01 · 已修 · commit:" + "b" * 40 + "\n"
    "- 2026-09-07T10:25 · close · legacy:KB-09 · 已随本步处置\n"
    "\n"
    "- 2026-09-07T10:26 · note · 空行允许\n"
)
MILESTONE_MD = (
    "# task: gov-t99\n"
    "- 类别: 里程碑任务 · 名单项 gov-t99 · 分支意图 gov-t99-work\n"
    "- 2026-09-07T11:00 · intent · definition-draft · 起草 Definition\n"
)


def lint_case(name, files, expect_exit, expect_rule=None, expect_warning=None):
    root = tempfile.mkdtemp(prefix="hs-lint-")
    try:
        for rel, text in files.items():
            write(root, rel, text)
        code, out, err = run([LINT, "--root", root, "--json"], root)
        try:
            obj = json.loads(out)
        except ValueError:
            obj = {"findings": []}
        rules = {f["rule"] for f in obj.get("findings", []) if f["severity"] == "violation"}
        warns = {f["rule"] for f in obj.get("findings", []) if f["severity"] == "warning"}
        ok = code == expect_exit and (expect_rule is None or expect_rule in rules) \
            and (expect_warning is None or expect_warning in warns)
        check(f"lint · {name}", ok, f"exit={code} rules={sorted(rules)} warnings={sorted(warns)} stderr={err.strip()}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def base_files():
    return {"HANDOFF/progress/repo.md": REPO_MD, "HANDOFF/progress/repo-od-01.md": TASK_MD,
            "HANDOFF/progress/gov-t99.md": MILESTONE_MD}


def mutate(rel, old, new):
    files = base_files()
    assert old in files[rel], (rel, old)
    files[rel] = files[rel].replace(old, new, 1)
    return files


def lint_cases():
    lint_case("正例 · 三类文件全部规则通过", base_files(), 0)
    lint_case("NOT_CHECKED · progress 目录缺失", {"README.md": "x\n"}, 2)
    lint_case("physical · CR 字节", mutate("HANDOFF/progress/gov-t99.md", "起草 Definition\n", "起草 Definition\r\n"), 1, "physical")
    lint_case("physical · 末尾无 LF", mutate("HANDOFF/progress/gov-t99.md", "起草 Definition\n", "起草 Definition"), 1, "physical")
    lint_case("physical · BOM", mutate("HANDOFF/progress/gov-t99.md", "# task", "\ufeff# task"), 1, "physical")
    lint_case("header-title · stem 不符", mutate("HANDOFF/progress/gov-t99.md", "# task: gov-t99", "# task: gov-t98"), 1, "header-title")
    lint_case("header-title · 缺第 1 行", mutate("HANDOFF/progress/gov-t99.md", "# task: gov-t99", "task gov-t99"), 1, "header-title")
    lint_case("header-category · 名单项 ≠ stem", mutate("HANDOFF/progress/gov-t99.md", "名单项 gov-t99", "名单项 gov-t1"), 1, "header-category")
    lint_case("header-category · 承载项小写形态 ≠ stem", mutate("HANDOFF/progress/repo-od-01.md", "承载项 repo:OD-01", "承载项 repo:OD-02"), 1, "header-category")
    lint_case("header-category · 仓级只允许 repo.md", mutate("HANDOFF/progress/gov-t99.md", "- 类别: 里程碑任务 · 名单项 gov-t99 · 分支意图 gov-t99-work", "- 类别: 仓级"), 1, "header-category")
    lint_case("header-category · repo.md 非仓级", mutate("HANDOFF/progress/repo.md", "- 类别: 仓级", "- 类别: 里程碑任务 · 名单项 repo · 分支意图 x"), 1, "header-category")
    lint_case("header-category · 未知类别行", mutate("HANDOFF/progress/gov-t99.md", "- 类别: 里程碑任务", "- 类别: 其他任务"), 1, "header-category")
    lint_case("row-grammar · 不以「- 」开头", mutate("HANDOFF/progress/gov-t99.md", "- 2026-09-07T11:00 · intent", "2026-09-07T11:00 · intent"), 1, "row-grammar")
    lint_case("row-grammar · 空字段", mutate("HANDOFF/progress/gov-t99.md", "· intent · definition-draft ·", "· intent ·  ·"), 1, "row-grammar")
    lint_case("row-time · 到秒", mutate("HANDOFF/progress/gov-t99.md", "2026-09-07T11:00", "2026-09-07T11:00:00"), 1, "row-time")
    lint_case("row-type · 未知行型", mutate("HANDOFF/progress/gov-t99.md", "· intent ·", "· unknown ·"), 1, "row-type")
    lint_case("row-fields · intent 缺文本", mutate("HANDOFF/progress/gov-t99.md", "· definition-draft · 起草 Definition", "· definition-draft"), 1, "row-fields")
    lint_case("row-fields · open 缺现状", mutate("HANDOFF/progress/repo.md", "· 仓级待裁项 · 被什么挡住：等 Owner", "· 仓级待裁项"), 1, "row-fields")
    lint_case("row-fields · close 缺依据", mutate("HANDOFF/progress/repo-od-01.md", "· close · legacy:KB-09 · 已随本步处置", "· close · legacy:KB-09"), 1, "row-fields")
    lint_case("step-name · 含空格", mutate("HANDOFF/progress/gov-t99.md", "· definition-draft ·", "· definition draft ·"), 1, "step-name")
    lint_case("id-grammar · 单位数编号", mutate("HANDOFF/progress/repo.md", "repo:OD-02 · OD", "repo:OD-3 · OD"), 1, "id-grammar")
    lint_case("id-grammar · close 引用不合文法", mutate("HANDOFF/progress/repo-od-01.md", "· close · legacy:KB-09 ·", "· close · KB-09 ·"), 1, "id-grammar")
    lint_case("id-prefix · 铸造前缀 ≠ stem", mutate("HANDOFF/progress/repo-od-01.md", "open · repo-od-01:KB-01", "open · repo:KB-01"), 1, "id-prefix")
    lint_case("id-prefix · legacy 出现在非 repo.md", mutate("HANDOFF/progress/repo-od-01.md", "open · repo-od-01:KB-01 · KB · 坏点一 · 现状：未修", "open · legacy:KB-77 · KB · 旧项 · 现状：x（转录自 HANDOFF/LEDGER.md 第 1 行，登记 2026-08-25）"), 1, "id-prefix")
    lint_case("id-prefix · legacy 非转录行", mutate("HANDOFF/progress/repo.md", "现状：未处置（转录自 HANDOFF/LEDGER.md 第 9 行，登记 2026-08-25）", "现状：未处置"), 1, "id-prefix")
    lint_case("id-kind · 种类字段与 id 不一致", mutate("HANDOFF/progress/repo.md", "repo:OD-02 · OD", "repo:OD-02 · KB"), 1, "id-kind")
    lint_case("id-duplicate · 同 id 两次 open", mutate("HANDOFF/progress/repo.md", "repo:OD-02 · OD · 第二个待裁项", "repo:OD-01 · OD · 第二个待裁项"), 1, "id-duplicate")
    lint_case("id-sequence · 编号倒退", mutate("HANDOFF/progress/repo.md", "10:01 · open · repo:OD-01", "10:01 · open · repo:OD-03"), 1, "id-sequence")
    lint_case("id-gap · 无转录行的文件编号空洞", mutate("HANDOFF/progress/repo-od-01.md", "open · repo-od-01:OD-01", "open · repo-od-01:OD-02"), 1, "id-gap")
    lint_case("id-gap · 首个铸造不自 01 起", {**base_files(), "HANDOFF/progress/gov-t99.md": MILESTONE_MD + "- 2026-09-07T11:01 · open · gov-t99:KB-02 · KB · x · 现状：y\n"}, 1, "id-gap")
    lint_case("id-gap · 含转录行的文件允许空洞", mutate("HANDOFF/progress/repo.md", "repo:OD-02 · OD", "repo:OD-07 · OD"), 0)
    lint_case("answer-kind · answer 对 KB", mutate("HANDOFF/progress/repo-od-01.md", "· close · repo-od-01:KB-01 · 已修 · commit:" + "b" * 40, "· answer · repo-od-01:KB-01 · Owner 原话「关」"), 1, "answer-kind")
    lint_case("answer-until · 日期不合文法", mutate("HANDOFF/progress/repo-od-01.md", "until 2026-09-20", "until 下周"), 1, "answer-until")
    lint_case("commit-anchor · 短 SHA", mutate("HANDOFF/progress/repo-od-01.md", "commit:" + "a" * 40, "commit:abc123"), 1, "commit-anchor")
    lint_case("ref-born · answer 引用未出生 id", mutate("HANDOFF/progress/repo-od-01.md", "· answer · repo-od-01:OD-01 ·", "· answer · repo-od-01:OD-09 ·"), 1, "ref-born")
    lint_case("ref-born · close 引用未出生 id", mutate("HANDOFF/progress/repo-od-01.md", "· close · legacy:KB-09 ·", "· close · legacy:KB-10 ·"), 1, "ref-born")
    lint_case("result-anchor · 缺锚只 warning", mutate("HANDOFF/progress/repo-od-01.md", " · commit:" + "a" * 40 + "\n", "\n"), 0, None, "result-anchor")


# ---------------------------------------------------------------- 并发写场景与现算命令

def concurrency_scenario():
    top = tempfile.mkdtemp(prefix="hs-git-")
    try:
        origin = os.path.join(top, "origin.git")
        seed = os.path.join(top, "seed")
        git(top, "init", "--bare", "-q", "-b", "main", origin)
        git(top, "init", "-q", "-b", "main", seed)
        write(seed, "README.md", "seed\n")
        git(seed, "add", "README.md")
        git(seed, "commit", "-q", "-m", "seed")
        landed_sha = git(seed, "rev-parse", "HEAD")
        write(seed, "HANDOFF/progress/repo.md",
              "# task: repo\n- 类别: 仓级\n"
              "- 2026-09-07T09:00 · open · repo:OD-01 · OD · 承载项一 · 被什么挡住：等减重入库\n"
              "- 2026-09-07T09:01 · open · repo:OD-02 · OD · 承载项二 · 被什么挡住：等减重入库\n")
        write(seed, "HANDOFF/progress/repo-od-01.md",
              "# task: repo-od-01\n- 类别: 台账任务 · 承载项 repo:OD-01 · 分支意图 x\n"
              "- 2026-09-07T09:10 · result · seed · 基线入库 · commit:" + landed_sha + "\n"
              "- 2026-09-07T09:11 · open · repo-od-01:KB-01 · KB · 母任务铸造的坏点 · 现状：待子任务处置\n"
              "- 2026-09-07T09:12 · open · repo-od-01:OD-01 · OD · 母任务待裁项 · 被什么挡住：等 Owner\n")
        write(seed, "HANDOFF/progress/repo-od-02.md",
              "# task: repo-od-02\n- 类别: 台账任务 · 承载项 repo:OD-02 · 分支意图 y\n"
              "- 2026-09-07T09:20 · intent · open-b · 开工\n")
        git(seed, "add", "HANDOFF")
        git(seed, "commit", "-q", "-m", "progress base")
        git(seed, "remote", "add", "origin", origin)
        git(seed, "push", "-q", "origin", "main")
        clone = os.path.join(top, "clone")
        git(top, "clone", "-q", origin, clone)
        # 分支 x：任务 repo-od-01 只追加自己的文件
        git(clone, "checkout", "-q", "-b", "x")
        with open(os.path.join(clone, "HANDOFF/progress/repo-od-01.md"), "a", encoding="utf-8") as f:
            f.write("- 2026-09-07T10:00 · intent · step-x · 分支 x 施工\n"
                    "- 2026-09-07T10:30 · result · step-x · 未运输的结果 · commit:" + "c" * 40 + "\n"
                    "- 2026-09-07T10:31 · open · repo-od-01:KB-02 · KB · 分支 x 新铸 · 现状：未修\n")
        git(clone, "commit", "-q", "-am", "x appends")
        # 分支 y：任务 repo-od-02 在自己的文件内闭合 repo-od-01 铸造的 KB 与 OD
        git(clone, "checkout", "-q", "-b", "y", "origin/main")
        with open(os.path.join(clone, "HANDOFF/progress/repo-od-02.md"), "a", encoding="utf-8") as f:
            f.write("- 2026-09-07T10:05 · open · repo-od-02:OD-01 · OD · 子任务待裁项 · 被什么挡住：等 Owner\n"
                    "- 2026-09-07T10:06 · close · repo-od-01:KB-01 · 子任务已处置母任务的坏点\n"
                    "- 2026-09-07T10:07 · answer · repo-od-01:OD-01 · Owner 原话「按甲」\n")
        git(clone, "commit", "-q", "-am", "y appends")
        r = subprocess.run(["git", "-C", clone, "merge", "-q", "--no-edit", "x"], capture_output=True, env=GIT_ENV)
        check("并发 · git merge 两分支零冲突", r.returncode == 0, r.stderr.decode("utf-8", "replace"))
        code, out, err = run([LINT, "--root", clone], clone)
        check("并发 · 合并后 lint 退出码 0", code == 0, out + err)
        tasks, _ = lint.load_progress(clone)
        closed = lint.closure(tasks)
        check("并发 · 现算判母任务的 KB 已由子任务闭合", "repo-od-01:KB-01" in closed and closed["repo-od-01:KB-01"][0]["task"] == "repo-od-02")
        check("并发 · 分支 x 新铸的 KB 仍 open", "repo-od-01:KB-02" not in closed)
        code, out, err = run([STATUS, "--root", clone, "--json"], clone)
        check("status · 退出码 0", code == 0, err)
        snap = json.loads(out)
        pending = {p["id"] for p in snap["pending_owner"]}
        check("status · 等 Owner 拍板 = 未 answer 的 OD", pending == {"repo:OD-01", "repo:OD-02", "repo-od-02:OD-01"}, str(pending))
        prog = {e["task"]: e for e in snap["in_progress"]}
        check("status · 在办 = 两个承载项未闭合的任务，仓级不进", set(prog) == {"repo-od-01", "repo-od-02"}, str(set(prog)))
        check("status · 在办 worktree 命中分支 y", prog["repo-od-02"]["worktree"] == os.path.realpath(clone) or prog["repo-od-02"]["worktree"] == clone, str(prog["repo-od-02"]))
        check("status · 在办领先 / 落后", prog["repo-od-02"]["ahead"] == 3 and prog["repo-od-02"]["behind"] == 0, str(prog["repo-od-02"]))
        check("status · 分支 x 的领先数", prog["repo-od-01"]["ahead"] == 1 and prog["repo-od-01"]["worktree"] is None, str(prog["repo-od-01"]))
        check("status · 刚落地只含 origin/main 祖先", [l["commit"] for l in snap["landed"]] == [landed_sha], str(snap["landed"]))
        nxt = {n["task"]: n["step"] for n in snap["next"]}
        check("status · legacy 不重放 intent 为下一步", nxt == {"repo-od-01": None, "repo-od-02": None} and all("未提供" in n["text"] for n in snap["next"]), str(nxt))
        code, out, err = run([STATUS, "--root", clone], clone)
        check("status · 人读四段在场", code == 0 and all(h in out for h in ("## 1 等 Owner 拍板", "## 2 在办", "## 3 刚落地", "## 4 下一步")), out)
        check("status · 不写任何文件", git(clone, "status", "--porcelain") == "")
        # 里程碑任务终态：ruling 页首 Type: done
        write(clone, "HANDOFF/progress/gov-t99.md", "# task: gov-t99\n- 类别: 里程碑任务 · 名单项 gov-t99 · 分支意图 gov-t99-work\n- 2026-09-07T11:00 · intent · draft · 起草\n")
        code, out, _ = run([STATUS, "--root", clone, "--json"], clone)
        snap = json.loads(out)
        check("status · 无 ruling 的里程碑任务在办", any(e["task"] == "gov-t99" and e["branch_note"] == "分支在本地与 origin 均不存在" for e in snap["in_progress"]), str(snap["in_progress"]))
        write(clone, "tasks/gov-t99/rulings/RU-02-done.md", "# RU-02\n> Ruling: RU-02\n> Date: 2026-09-07\n> Type: done\n> Object: gov-t99\n> Basis: x\n> Decision: y\n")
        code, out, _ = run([STATUS, "--root", clone, "--json"], clone)
        snap = json.loads(out)
        check("status · done ruling 在场即终态", all(e["task"] != "gov-t99" for e in snap["in_progress"]))
        # 全部终态时下一步固定句
        for rel in ("HANDOFF/progress/repo-od-01.md", "HANDOFF/progress/repo-od-02.md", "HANDOFF/progress/gov-t99.md"):
            os.remove(os.path.join(clone, rel))
        code, out, _ = run([STATUS, "--root", clone], clone)
        check("status · 无在办固定句", code == 0 and "- 无在办\n" in out, out)
        # 文法违规 → NOT_CHECKED
        write(clone, "HANDOFF/progress/bad.md", "# task: bad\n- 类别: 仓级\n")
        code, out, _ = run([STATUS, "--root", clone, "--json"], clone)
        check("status · 进度文件违规即退出码 2", code == 2 and json.loads(out)["conclusion"] == "NOT_CHECKED", out)
        # progress 缺失 → NOT_CHECKED
        shutil.rmtree(os.path.join(clone, "HANDOFF"))
        code, out, _ = run([STATUS, "--root", clone], clone)
        check("status · progress 目录缺失即退出码 2", code == 2, out)
    finally:
        shutil.rmtree(top, ignore_errors=True)


def main():
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"handoff_selftest: NOT_CHECKED（git 不可用：{e}）", file=sys.stderr)
        return 2
    lint_cases()
    concurrency_scenario()
    print(f"handoff_selftest: {'PASS' if not FAILS else 'FAIL'}（失败 {len(FAILS)} 条）")
    for f in FAILS:
        print("  " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"handoff_selftest: NOT_CHECKED（未捕获异常：{exc!r}）", file=sys.stderr)
        sys.exit(2)
