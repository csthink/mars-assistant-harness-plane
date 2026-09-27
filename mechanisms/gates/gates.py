"""人工可选 lint：0=PASS，1=VIOLATION，2=NOT_CHECKED；未查成优先于违规。

JSON 写 stdout，摘要写 stderr；manifest --write 仅报告写入结果，不产生 PASS。
普通读取不写仓库；selftest 在独立临时仓运行。不接 pre-commit 与 CI。
"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
UNIT_DIR = os.path.dirname(os.path.realpath(__file__))


def emit(command, state, checks, repo_root, reason=None):
    record = dict(command=command, state=state, exit_code={"PASS": 0, "VIOLATION": 1, "NOT_CHECKED": 2}[state],
                  repo_root=repo_root, checks=checks)
    if reason:
        record["reason"] = reason
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print("[%s] %s%s" % (command, state, ": " + reason if reason else ""), file=sys.stderr)
    for check in checks:
        if check.get("reason"):
            print("  %s: %s" % (check["check"], check["reason"]), file=sys.stderr)
        for finding in check.get("findings", []):
            print("  %s %s: %s" % (finding["rule"], finding["subject"], finding["detail"]), file=sys.stderr)
    return record["exit_code"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("all", "layout", "manifest", "selftest"))
    parser.add_argument("--repo-root", help="显式指定绝对仓根；缺省自工具目录向上寻找")
    parser.add_argument("--write", action="store_true", help="仅 manifest：先计算全部输出，再逐文件原子写入")
    args = parser.parse_args(argv)
    root = args.repo_root
    if args.write and args.command != "manifest":
        parser.error("--write 仅适用于 manifest")
    try:
        import gates_base as base
        root = base.explicit_repo_root(root) if root else base.find_repo_root(UNIT_DIR)
        if args.command == "selftest":
            import selftest
            return selftest.run_selftest(root)
        catalog = base.load_catalog(os.path.join(root, "mechanisms", "gates"))
        ctx = base.Context(root, base.profile_from_catalog(catalog), catalog)
        if args.write:
            import gates_generate as gen
            code, messages = gen.write_all(ctx)
            print(json.dumps(dict(command="manifest --write", exit_code=code, repo_root=root,
                                  messages=messages), ensure_ascii=False, indent=2))
            for message in messages:
                print(message, file=sys.stderr)
            return code
        checks = []
        for name in (("layout", "manifest") if args.command == "all" else (args.command,)):
            try:
                import importlib
                module = importlib.import_module("gates_" + name)
                checks.extend(base.run_gate(module.GATE, ctx))
            except Exception as exc:
                checks.append(base.CheckResult(name, base.NOT_CHECKED, [], str(exc)))
        state = base.aggregate_states(c.state for c in checks)
        return emit(args.command, state, [base.check_json(c) for c in checks], root)
    except Exception as exc:
        if args.write:
            print(json.dumps(dict(command="manifest --write", exit_code=2, repo_root=root,
                                  messages=["未写入：%s: %s" % (type(exc).__name__, exc)]), ensure_ascii=False))
            print("写入失败：%s" % exc, file=sys.stderr)
            return 2
        return emit(args.command, "NOT_CHECKED", [], root, "%s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    sys.exit(main())
