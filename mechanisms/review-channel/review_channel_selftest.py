"""review_channel_selftest — 自测引擎（评审通道设计 §12；只写一次）。

- 发现两处声明：单元根 `review_channel_selftest_<模块>.py` 与 `adapters/<x>_selftest.py`；每件导出 `cases()` →
  [(case_id, callable)]。callable 接收 Engine，断言失败以 `Engine.fail` / `check` 记录或抛 AssertionError。
- 夹具：隔离 git 仓（IsoRepo）、假适配器目录、假 Registry、假 zshrc、评审请求构造、净化启动子进程调用入口。
- 变异验收：`fixtures/mutations.json` 逐条施加到单元副本，对应负例在副本下必须红；全部通过才算自测绿。
- 零工作树副产物：全部临时物住 tempfile；运行前后单元目录树摘要相等（断言）。
退出码：0 全绿含变异验收 · 1 任一红 · 2 引擎异常。
调用：<净化启动> review_channel.py selftest [--only <case-id 前缀,...>] [--unit-dir <单元副本>] [--no-mutations] [--list]
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

UNIT_DIR = os.path.dirname(os.path.realpath(__file__))


def _real_repo_root():
    return os.path.realpath(os.path.join(UNIT_DIR, os.pardir, os.pardir))


class Failure(Exception):
    pass


class Engine:
    def __init__(self, unit_dir, only=None, verbose=False, repo_root=None):
        self.unit_dir = unit_dir
        self.fixtures = os.path.join(unit_dir, "fixtures")
        self.only = only or []
        self.verbose = verbose
        self.results = []      # (case_id, ok, detail, seconds)
        self.problems = []     # (case_id, message)
        self.tmp_root = tempfile.mkdtemp(prefix="review-channel-selftest-")
        # R9-B2 整改：仓根由调用方显式传入（变异副本位于临时目录，不得从副本位置推导仓根）
        self.repo_root = os.path.realpath(repo_root) if repo_root else _real_repo_root()
        self.interpreter = sys.executable
        self._current = None

    # ------------------------------------------------------------ 断言
    def check(self, cond, message):
        if not cond:
            self.problems.append((self._current, message))
            raise Failure(message)

    def fail(self, message):
        self.problems.append((self._current, message))
        raise Failure(message)

    def expect_error(self, fn, code=None, exc_type=None, message="expected an error"):
        """fn() 须抛 ChannelError（可指定 code）；返回异常。"""
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            if exc_type is not None and not isinstance(exc, exc_type):
                self.fail("%s: wrong exception type %s" % (message, type(exc).__name__))
            got = getattr(exc, "code", None)
            if code is not None and got != code:
                self.fail("%s: expected code %s, got %s (%s)" % (message, code, got, exc))
            return exc
        self.fail(message + ": no error raised")

    # ------------------------------------------------------------ 夹具
    def tmpdir(self, prefix="t"):
        return tempfile.mkdtemp(prefix=prefix + "-", dir=self.tmp_root)

    def fixture_path(self, name):
        return os.path.join(self.fixtures, name)

    def fixture_bytes(self, name):
        with open(self.fixture_path(name), "rb") as f:
            return f.read()

    def fixture_json(self, name):
        return json.loads(self.fixture_bytes(name).decode("utf-8"))

    def fake_adapters(self, control=None, names=("fake",)):
        """假适配器目录：fixtures/fake_adapter.py 复制为 adapters/<name>.py；control 写 fake_control.json。"""
        d = self.tmpdir("adapters")
        for name in names:
            shutil.copy(self.fixture_path("fake_adapter.py"), os.path.join(d, name + ".py"))
            with open(os.path.join(d, name + ".py"), encoding="utf-8") as source:
                src = source.read()
            src = src.replace('RUNTIME_ID = "fake"', 'RUNTIME_ID = "%s"' % name)
            if name.endswith("inline"):
                src = src.replace("INLINE_DELIVERY = False", "INLINE_DELIVERY = True")
            with open(os.path.join(d, name + ".py"), "w", encoding="utf-8") as f:
                f.write(src)
        self.set_control(d, **(control or {}))
        return d

    def set_control(self, adapters_dir, **control):
        with open(os.path.join(adapters_dir, "fake_control.json"), "w", encoding="utf-8") as f:
            json.dump(control, f)

    def fake_registry(self, mutate=None, path_dir=None, name="registry.json"):
        reg = self.fixture_json("registry_sample.json")
        if mutate:
            mutate(reg)
        d = path_dir or self.tmpdir("registry")
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        return p

    def fake_zshrc(self, text=None, path_dir=None, name="zshrc"):
        d = path_dir or self.tmpdir("zshrc")
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text if text is not None else
                    "export FAKE_API_KEY=sk-fake-secret-value-123\nexport FAKE_API_BASE='https://fake.invalid/v1'\n")
        return p

    def iso_repo(self):
        return IsoRepo(self)

    def install_unit(self, repo, adapters_dir, registry_mutate=None, zshrc_text=None):
        """把假适配器集与假 Registry 装入隔离仓的受治理位置（mechanisms/review-channel/），把假 ~/.zshrc 写入本引擎 HOME
        （R10-B1 整改：入口无任何注入口，Registry / 适配器恒取自被审仓根，配置正本恒取自 HOME）。返回仓内适配器目录。"""
        unit = repo.path("mechanisms/review-channel")
        target = os.path.join(unit, "adapters")
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(adapters_dir, target)
        self.fake_registry(registry_mutate, path_dir=unit, name="review_channel_registry.json")
        self.fake_zshrc(zshrc_text, path_dir=self.tmp_root, name=".zshrc")
        return target

    def channel(self, repo, sub, request_path, *more, timeout=300):
        """净化启动子进程调用入口（HOME = 引擎临时根，其 ~/.zshrc 由 install_unit 写入）；返回 (exit, stdout, stderr, stdout_json|None)。
        `respond` 以 --decisions 取路径（§6.12），其余子命令以 --request。"""
        prefix = tempfile.mkdtemp(prefix="pycache-", dir=self.tmp_root)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp_root, "LC_ALL": "C"}
        argv = [self.interpreter, "-B", "-E", "-s", "-S", "-X", "pycache_prefix=" + prefix,
                os.path.join(self.unit_dir, "review_channel.py"), sub, "--decisions" if sub == "respond" else "--request", request_path,
                "--repo-root", repo.root, *more]
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout)
        try:
            out = json.loads(proc.stdout) if proc.stdout.strip() else None
        except ValueError:
            out = None
        return proc.returncode, proc.stdout, proc.stderr, out

    # ------------------------------------------------------------ 运行
    def selected(self, case_id):
        return not self.only or any(case_id.startswith(p) for p in self.only)

    def run_cases(self, cases):
        for case_id, fn in cases:
            if not self.selected(case_id):
                continue
            self._current = case_id
            t0 = time.time()
            try:
                fn(self)
                self.results.append((case_id, True, "", time.time() - t0))
            except Failure as exc:
                self.results.append((case_id, False, str(exc), time.time() - t0))
            except Exception as exc:  # noqa: BLE001
                detail = "%s: %s" % (type(exc).__name__, exc)
                self.problems.append((case_id, detail))
                self.results.append((case_id, False, detail + "\n" + traceback.format_exc()[-800:], time.time() - t0))
            if self.verbose:
                ok = self.results[-1][1]
                sys.stderr.write("  %s %s\n" % ("PASS" if ok else "FAIL", case_id))

    def cleanup(self):
        shutil.rmtree(self.tmp_root, ignore_errors=True)


class IsoRepo:
    """隔离 git 仓：复制 rules_catalog.json 与 .gitignore、写一件 records/ 下的参考件夹具；建 demo 单元与 task record。"""

    def __init__(self, engine):
        self.engine = engine
        self.root = engine.tmpdir("repo")
        real = engine.repo_root
        for rel in ("mechanisms/gates/rules_catalog.json", ".gitignore"):
            os.makedirs(os.path.join(self.root, os.path.dirname(rel)), exist_ok=True)
            shutil.copy(os.path.join(real, rel), os.path.join(self.root, rel))
        self.write("records/fixture-reference.md", "# fixture reference\n")
        os.makedirs(os.path.join(self.root, "tasks/gov-t1/reviews"))
        os.makedirs(os.path.join(self.root, "tasks/gov-t1/rulings"))
        os.makedirs(os.path.join(self.root, "mechanisms/demo"))
        os.makedirs(os.path.join(self.root, "reviews"))
        os.makedirs(os.path.join(self.root, "records/diagnostics"))
        self.write("mechanisms/demo/HarnessPlane_Demo_Design_v1.md",
                   "# Demo\n\n> Depends on:\n> `AGENTS.md`\n>\n\nBody references `mechanisms/gates/rules_catalog.json` and "
                   "`records/fixture-reference.md`.\n")
        self.write("AGENTS.md", "# agents\n")
        self.git("init", "-q", "-b", "main")
        self.commit("init")

    def write(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def read(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return f.read()

    def path(self, rel):
        return os.path.join(self.root, rel)

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", *args],
                              cwd=self.root, capture_output=True, text=True,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.engine.tmp_root,
                                   "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})

    def commit(self, message):
        # Explicit legacy fixture originals remain tracked despite CL-55 ignores.
        self.git('add','-f','--','reviews','tasks/gov-t1/reviews')
        paths=self.git('ls-files','-m','-d','-o','--exclude-standard','-z').stdout.split('\0')
        paths=sorted(set(p for p in paths if p))
        if paths:self.git('add','--',*paths)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def request(self, rnd, task=True, previous=None, name=None, remediation="fixed", residuals=None, **extra):
        """评审请求夹具（review-channel-request/v4）。r2+：`remediation` = 整改声明（§6.12：须以通道处置段起始，调用方自 respond 输出取得）；
        `residuals` = 已接受残留（缺省一条 RES-1；r2+ 须先列派生残留项）。"""
        req = {"request_schema": "review-channel-request/v4", "subject": "demo", "stage": "impl", "round": rnd,
               "caller": "selftest",
               "artifact_author": {"human_only": False,
                                   "authors": [{"tool": "claude-code", "model": "m", "vendor": "Anthropic"}]},
               "inputs": {"candidates": ["mechanisms/demo/HarnessPlane_Demo_Design_v1.md"],
                          "references": ["AGENTS.md", "mechanisms/gates/rules_catalog.json",
                                         "records/fixture-reference.md"]},
               "review_brief": {"background": "bg", "check_surfaces": "cs", "evidence_limits": [],
                                "accepted_residuals": residuals if residuals is not None else [{"id": "RES-1", "text": "r"}]},
               "invocation_authorization": "selftest:OD-01", "formal_review_authorized_by_owner": True}
        if task:
            req["task_record"] = "gov-t1"
        if previous:
            req["previous_round"] = previous
            req["review_brief"]["remediation_statement"] = remediation
        for k, v in extra.items():
            if v is None:
                req.pop(k, None)
            else:
                req[k] = v
        p = os.path.join(self.engine.tmpdir("req"), name or ("req-%s.json" % rnd))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False, indent=1)
        return p

    def tracked_dir(self, rnd, task=True):
        return "tasks/gov-t1/reviews/impl-%s" % rnd if task else "reviews/demo/%s" % rnd

    def attempts_dir(self, rnd, task=True):
        return "tasks/gov-t1/attempts/impl-%s" % rnd if task else "review-attempts/demo/%s" % rnd

    def previous_round(self, rnd, task=True):
        d = self.tracked_dir(rnd, task)
        return {"verdict_path": d + "/HarnessPlane_Demo_Review_R%s.md" % rnd[1:], "receipt_path": d + "/receipt-%s.json" % rnd}

    def decisions_input(self, rnd, decisions, task=True, name=None, **extra):
        """`respond` 的决定输入夹具（§6.12）：subject / stage / round / task_record 与 decisions[]。"""
        obj = {"subject": "demo", "stage": "impl", "round": rnd, "decisions": decisions}
        if task:
            obj["task_record"] = "gov-t1"
        obj.update(extra)
        p = os.path.join(self.engine.tmpdir("dec"), name or ("decisions-%s.json" % rnd))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        return p


# ---------------------------------------------------------------- 发现与变异

def discover(unit_dir):
    mods = []
    names = sorted(n for n in os.listdir(unit_dir) if n.startswith("review_channel_selftest_") and n.endswith(".py"))
    paths = [os.path.join(unit_dir, n) for n in names]
    adir = os.path.join(unit_dir, "adapters")
    if os.path.isdir(adir):
        paths += [os.path.join(adir, n) for n in sorted(os.listdir(adir)) if n.endswith("_selftest.py")]
    for p in paths:
        modname = "review_channel_selftest_decl_" + os.path.basename(p)[:-3]
        spec = importlib.util.spec_from_file_location(modname, p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        mods.append((os.path.relpath(p, unit_dir), mod))
    return mods


def tree_digest(unit_dir):
    import hashlib
    h = hashlib.sha256()
    for root, dirs, files in os.walk(unit_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for fn in sorted(files):
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, unit_dir)
            h.update(rel.encode("utf-8") + b"\0")
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).hexdigest().encode("ascii"))
    return h.hexdigest()


def mutation_outcome(must_fail, ran_cases, failed_cases):
    """§12 第 17 类判据（r18 自查整改，R18-B3 线索）：变异被捕获 ⇔ 声明的每个 must_fail 用例都变红；任一仍绿即逃逸。
    返回 (state, detail)。"""
    if not ran_cases or set(ran_cases) != set(must_fail):
        return "ENGINE_ERROR", "must_fail cases did not all run: ran %s for %s" % (sorted(ran_cases), list(must_fail))
    green = sorted(set(must_fail) - set(failed_cases))
    if green:
        return "ESCAPED", "must_fail cases stayed green: %s" % green
    return "CAUGHT", "red cases: %s" % sorted(failed_cases)


def run_mutations(engine, mutations):
    """逐条施加变异到单元副本，在副本下只跑 must_fail 用例；声明的每个用例都须变红（mutation_outcome）。"""
    outcomes = []
    for mut in mutations:
        copy_root = tempfile.mkdtemp(prefix="mutant-", dir=engine.tmp_root)
        copy = os.path.join(copy_root, "review-channel")
        shutil.copytree(os.path.join(os.path.dirname(engine.unit_dir), "repo-layout"), os.path.join(copy_root, "repo-layout"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(engine.unit_dir, copy, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        target = os.path.join(copy, mut["file"])
        src = open(target, encoding="utf-8").read()
        if src.count(mut["find"]) != 1:
            outcomes.append({"id": mut["id"], "state": "ENGINE_ERROR", "detail": "find string occurs %d times" % src.count(mut["find"])})
            continue
        with open(target, "w", encoding="utf-8") as f:
            f.write(src.replace(mut["find"], mut["replace"]))
        prefix = tempfile.mkdtemp(prefix="pycache-", dir=engine.tmp_root)
        argv = [engine.interpreter, "-B", "-E", "-s", "-S", "-X", "pycache_prefix=" + prefix,
                os.path.join(copy, "review_channel_selftest.py"), "--unit-dir", copy, "--no-mutations",
                "--repo-root", engine.repo_root, "--only", ",".join(mut["must_fail"])]
        proc = subprocess.run(argv, capture_output=True, text=True,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": engine.tmp_root, "LC_ALL": "C"},
                              timeout=900)
        try:
            summary = json.loads(proc.stdout)
        except ValueError:
            outcomes.append({"id": mut["id"], "state": "ENGINE_ERROR", "detail": proc.stderr[-400:]})
            continue
        ran = [r for r in summary.get("results", [])]
        failed = [r["case"] for r in ran if not r["ok"]]
        state, detail = mutation_outcome(mut["must_fail"], [r["case"] for r in ran], failed)
        outcomes.append({"id": mut["id"], "state": state, "detail": detail})
    return outcomes


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    unit_dir = UNIT_DIR
    only = []
    repo_root = None
    mutations_on = True
    verbose = "--verbose" in argv
    list_only = "--list" in argv
    i = 0
    while i < len(argv):
        if argv[i] == "--unit-dir":
            unit_dir = os.path.realpath(argv[i + 1]); i += 2
        elif argv[i] == "--only":
            only = [x for x in argv[i + 1].split(",") if x]; i += 2
        elif argv[i] == "--no-mutations":
            mutations_on = False; i += 1
        elif argv[i] == "--repo-root":
            repo_root = argv[i + 1]; i += 2
        else:
            i += 1
    if unit_dir != UNIT_DIR:
        sys.path.insert(0, unit_dir)
    before = tree_digest(unit_dir)
    engine = Engine(unit_dir, only=only, verbose=verbose, repo_root=repo_root)
    try:
        mods = discover(unit_dir)
        all_cases = []
        for rel, mod in mods:
            cases = mod.cases()
            for cid, fn in cases:
                all_cases.append((cid, fn))
        if list_only:
            for cid, _fn in all_cases:
                sys.stdout.write(cid + "\n")
            return 0
        ids = [c for c, _f in all_cases]
        if len(set(ids)) != len(ids):
            sys.stderr.write("duplicate case ids\n")
            return 2
        engine.run_cases(all_cases)
        mutation_outcomes = []
        if mutations_on and not only:
            mutations = engine.fixture_json("mutations.json")
            mutation_outcomes = run_mutations(engine, mutations)
        after = tree_digest(unit_dir)
        red = [r for r in engine.results if not r[1]]
        escaped = [m for m in mutation_outcomes if m["state"] != "CAUGHT"]
        byproducts = before != after
        state = "PASS" if not red and not escaped and not byproducts else "VIOLATION"
        summary = {"tool": "review_channel_selftest", "state": state, "cases": len(engine.results),
                   "red": len(red), "results": [{"case": c, "ok": ok, "detail": d, "seconds": round(s, 3)}
                                               for c, ok, d, s in engine.results],
                   "mutations": mutation_outcomes, "unit_tree_unchanged": not byproducts}
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        sys.stderr.write("review_channel_selftest: %s (%d cases, %d red, %d mutations, %d escaped%s)\n"
                         % (state, len(engine.results), len(red), len(mutation_outcomes), len(escaped),
                            ", unit tree changed" if byproducts else ""))
        for c, ok, d, _s in engine.results:
            if not ok:
                sys.stderr.write("  RED %s: %s\n" % (c, d.splitlines()[0] if d else ""))
        for m in escaped:
            sys.stderr.write("  MUTATION %s %s: %s\n" % (m["state"], m["id"], m["detail"]))
        return 0 if state == "PASS" else 1
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("engine error: %s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()[-1200:]))
        return 2
    finally:
        engine.cleanup()


if __name__ == "__main__":
    sys.exit(main())
