"""Offline acceptance report for feature-t18: runs test_bundle and checks one delivery build; maps both to AC-01..AC-11.

Usage (every location explicit; no default machine path):
    HP_BUNDLE_INPUTS_DIR=<build inputs> HP_BUNDLE_OPENSSL=<openssl program> \\
    python run_bundle_report.py --output <new directory> [--cases <new directory>] [--delivery <delivery build output>] \\
        [--key-scan <private key file>]

--output receives unittest.log, report.json and report.md. --cases keeps each test's synthetic product lines, instance
directories and frames; otherwise a temporary directory is used and removed. --delivery names the output directory of
the delivery build (bundle/ and build-record.json): its files are re-identified, admitted by the synthetic Host with the
record's publisher pin, its real signature is verified with OpenSSL and with the independent pure implementation, a
rebuild of the same commit with a SYNTHETIC key must give the same archive and manifest bytes, and the installed
delivery is started once. --key-scan names the private key file: OpenSSL exports it into this process's memory only to
search the scanned files for the raw key in binary, hex and base64 form; only counts are written, never key bytes.

A unittest ERROR is never product PASS or FAIL: the erroring test is re-run once, both runs are recorded, and an
ERROR that persists leaves its criterion NOT_RUN. Assistant supervisor launch and J-03 acceptance, real model, J-04,
J-05, J-07 and real GitHub stay NOT_RUN.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import unittest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
for entry in (APP, APP / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from bundle import archive, build, release  # noqa: E402
import bundle_host as BH  # noqa: E402
import ed25519_synthetic  # noqa: E402
from run_publish_report import Recorder  # noqa: E402  (same result recorder as feature-t7)
import instance_area  # noqa: E402

MODULES = ("test_bundle",)
SOURCES = ["hp.py", "requirements.lock", "runtime/main.py", "runtime/launch.py", "runtime/dispatcher.py", "bundle/__init__.py",
           "bundle/archive.py", "bundle/layout.py", "bundle/manifest.py", "bundle/release.py", "bundle/probe.py", "bundle/build.py",
           "bundle/inputs.lock.json", "tests/bundle_fixture.py", "tests/bundle_host.py", "tests/ed25519_synthetic.py",
           "tests/test_bundle.py", "tests/run_bundle_report.py", "tests/host_driver.py", "tests/product_line.py"]
INPUTS = ["tasks/feature-t18/feature-t18.md", "tasks/feature-t18/rulings/RU-01-definition-review-skip.md",
          "tasks/feature-t18/rulings/RU-02-definition-finalization.md", "records/diagnostics/feature-t18/2026-09-24/inputs.json",
          "records/diagnostics/feature-t16/2026-09-21/inputs/assistant/docs/design/runtime-contract-v0/contract-manifest.json",
          "records/diagnostics/feature-t16/2026-09-21/inputs/assistant/docs/design/runtime-contract-v0/release-record/release-record.schema.json"]
RELEASE_SCHEMA = "records/diagnostics/feature-t16/2026-09-21/inputs/assistant/docs/design/runtime-contract-v0/release-record/release-record.schema.json"
CRITERIA = {
    "AC-01": "组成与已交付子集（FR-05、FR-64）",
    "AC-02": "身份与自证（FR-06、FR-64）",
    "AC-03": "可复现与版本身份",
    "AC-04": "准入正反例（FR-61）",
    "AC-05": "启动与协商（FR-61）",
    "AC-06": "可信启动事实与单一写者（FR-61）",
    "AC-07": "断连与恢复（FR-61、FR-63）",
    "AC-08": "bundle 内的最小路径（FR-64）",
    "AC-09": "版本无关（FR-61、FR-64）",
    "AC-10": "签名私钥安全",
    "AC-11": "验收报告与交付说明",
}
NOT_RUN = {
    "AC-04": ["Assistant 真实准入（本报告为 hp 自写的合成 Host 复现）"],
    "AC-05": ["Assistant supervisor 真实启动与协商（冻结组合表第 6 行，Assistant feature-t31 / feature-t32）"],
    "AC-08": ["经 Assistant Host 的真实旅程（J-03 接收与 J-05）"],
    "AC-11": ["Assistant supervisor 真实启动与 J-03 接收", "真实模型调用", "J-04 真实资格与 REVIEW_ENABLED 提升（Assistant OD-360）",
              "J-05 真实任务", "J-07 切片仓接入（feature-t19）", "真实 GitHub 推送与 Pull Request（Assistant KB-273）",
              "签名产品化、Developer ID 与公证（feature-t8、gov-t13）"],
}
PRIVATE_PATTERNS = [re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=]{16,}"),
                    re.compile(re.escape(base64.b64encode(ed25519_synthetic.PKCS8_PREFIX)[:20])),
                    re.compile(re.escape(ed25519_synthetic.PKCS8_PREFIX)),
                    re.compile(re.escape(ed25519_synthetic.PKCS8_PREFIX.hex().encode()))]
# Operational files carry no absolute path under a user's home directory (macOS /Users/<name>, Linux /home/<name>).
PATH_PATTERN = r"/(Users|home)/[A-Za-z0-9._-]+"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def identity(path):
    raw = Path(path).read_bytes()
    return dict(bytes=len(raw), sha256=sha256(raw))


def git(*args):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def environment(openssl):
    dirty = git("status", "--porcelain", "--", "apps", "mechanisms") or ""
    return dict(python=sys.version, executable_is_dev_venv=".venv" in sys.executable, platform=platform.platform(),
                machine=platform.machine(), macos=platform.mac_ver()[0], git=subprocess.run(["git", "--version"], capture_output=True,
                                                                                            text=True).stdout.strip(),
                repository_head=git("rev-parse", "HEAD"), source_dirty=bool(dirty), source_dirty_paths=dirty.splitlines(),
                openssl=release.program_identity(openssl) if openssl else None,
                dependencies=dict(lock="apps/harness/requirements.lock", **identity(APP / "requirements.lock")))


def run(names, cases, log):
    os.environ["HP_TEST_OUTPUT"] = str(cases)
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    return unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Recorder).run(suite)


def scan(files, key_forms):
    """Per-file hit counts for private key encodings and, when given, the raw key forms."""
    rows, total = [], 0
    for path in files:
        data = Path(path).read_bytes()
        hits = sum(1 for p in PRIVATE_PATTERNS if p.search(data)) + sum(1 for form in key_forms if form in data)
        total += hits
        rows.append(dict(path=str(path), bytes=len(data), hits=hits))
    return rows, total


def raw_key_forms(key_path, openssl):
    der = subprocess.run([openssl, "pkey", "-in", str(key_path), "-outform", "DER"], capture_output=True, check=True).stdout
    seed = der[-32:]
    forms = [seed, seed.hex().encode(), base64.b64encode(seed).rstrip(b"=")]
    return forms


def path_hits(ref):
    """git grep over apps/, mechanisms/ and .agents/ at a commit (tracked files only)."""
    out = subprocess.run(["git", "-C", str(ROOT), "grep", "-n", "-E", PATH_PATTERN, ref, "--", "apps", "mechanisms", ".agents"],
                         capture_output=True, text=True)
    return [line.split(":", 1)[1] for line in out.stdout.splitlines() if line]  # path:line:text, without the commit


def delivery_checks(delivery, openssl, cases):
    delivery = Path(delivery)
    record = json.loads((delivery / "build-record.json").read_text())
    import_dir = delivery / "bundle"
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(check=name, result="PASS" if ok else "FAIL", detail=detail))
    files = {n: identity(import_dir / n) for n in ("bundle.tar", "release.json", "release.sig", "publisher.pub")}
    check("files-match-build-record", all(files[n] == record["files"][n] for n in files), files)
    import jsonschema
    schema = json.loads(instance_area.path(RELEASE_SCHEMA).read_text())
    release_value = json.loads((import_dir / "release.json").read_bytes())
    wrapper = {"$schema": schema["$schema"], "$ref": "#/definitions/ReleaseRecord", "definitions": schema["definitions"]}
    errors = [e.message for e in jsonschema.Draft7Validator(wrapper).iter_errors(release_value)]
    check("release-record-validates-frozen-schema", not errors, errors[:5])
    record_bytes = (import_dir / "release.json").read_bytes()
    signature = bytes.fromhex((import_dir / "release.sig").read_text().strip())
    pem = (import_dir / "publisher.pub").read_bytes()
    check("signature-verifies-openssl", release.openssl_verify(openssl, pem, record_bytes, signature))
    check("signature-verifies-independent-implementation",
          ed25519_synthetic.verify(ed25519_synthetic.public_from_pem(pem), record_bytes, signature))
    check("publisher-digest", release.public_key_digest(pem) == release_value["publisher"]["publicKeyDigest"] ==
          record["publisherKey"]["spkiDigest"], record["publisherKey"]["spkiDigest"])
    verdict = BH.admit(import_dir, pins={release_value["runtimeId"]: release.public_key_digest(pem)})
    check("synthetic-host-admission", verdict.identity_verified and verdict.incompatibility is None, verdict.reasons[:5])
    rebuilt = Path(cases) / "delivery-rebuild"
    key = ed25519_synthetic.SyntheticKey()
    rebuild = build.build(repository=ROOT, commit=record["sourceCommit"], inputs_dir=os.environ["HP_BUNDLE_INPUTS_DIR"],
                          runtime_id=record["runtimeId"], publisher_id=record["publisherId"], source_reference=record["sourceReference"],
                          signer=key, output=rebuilt, identity_registry=Path(cases) / "delivery-rebuild-registry.jsonl")
    check("tested-builder-reproduces-delivered-archive", rebuild["archive"] == record["archive"] and rebuild["manifest"] == record["manifest"],
          dict(delivered=record["archive"]["sha256"], rebuilt=rebuild["archive"]["sha256"]))
    launch = dict()
    if verdict.identity_verified and not verdict.incompatibility:
        from product_line import create_product_line
        installation = BH.Installation(verdict, Path(cases) / "delivery-runtime")
        host = BH.BundleHost(installation, output=Path(cases) / "delivery-frames-unbound.jsonl")
        try:
            host.start()
            unbound = host.call("runtime.health")
        finally:
            host.close()
        repo, _ = create_product_line(Path(cases) / "delivery-product-line" / "repo")
        written = subprocess.run([str(installation.package / "python/bin/python3.12"), "-I", "-B", "-m", "hp", "binding", "write",
                                  "--instance-dir", str(installation.instance_dir), "--repository", str(repo), "--resource-handle",
                                  "resource:delivery-check", "--authority-ref", "owner:synthetic"], capture_output=True, text=True,
                                 env=installation.environment())
        host = BH.BundleHost(installation, output=Path(cases) / "delivery-frames.jsonl")
        try:
            result = host.start()
            health = host.call("runtime.health")
            scope, _ = host.open_scope("resource:delivery-check", [("harness.task-acceptance", "runtime.snapshot.open")])
            page = host.call("runtime.snapshot.open", dict(scopeRef=scope))
            launch = dict(unboundHealth=unbound, bindingExit=written.returncode, controlGeneration=result["context"]["controlGeneration"],
                          capabilities=[c["id"] for c in result["capabilities"]], health=health["health"],
                          actions=[a["actionId"] for a in page["actions"] if a["enabled"]])
            check("delivery-starts-and-negotiates", unbound["health"] == "degraded" and written.returncode == 0
                  and health["health"] == "ready" and len(result["capabilities"]) == len(verdict.manifest["capabilities"])
                  and "task.accept" in launch["actions"], launch)
        finally:
            host.close()
    members = {m["path"]: m["data"] for m in archive.read((import_dir / "bundle.tar").read_bytes())}
    return dict(buildRecord=dict(path=str(delivery / "build-record.json"), **identity(delivery / "build-record.json")),
                files=files, runtimeId=record["runtimeId"], version=record["version"], sourceCommit=record["sourceCommit"],
                archive=record["archive"], manifest=record["manifest"], releaseRecord=record["releaseRecord"],
                publisherKey=record["publisherKey"], members=len(members), checks=checks, launch=launch, memberData=members)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--delivery", type=Path, default=None)
    parser.add_argument("--key-scan", type=Path, default=None)
    args = parser.parse_args()
    instance_area.require()
    for variable in ("HP_BUNDLE_INPUTS_DIR", "HP_BUNDLE_OPENSSL"):
        if not os.environ.get(variable):
            raise SystemExit(variable + " is not set")
    openssl = os.environ["HP_BUNDLE_OPENSSL"]
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("output must not exist: " + str(output))
    if args.cases is not None and args.cases.resolve().exists():
        raise SystemExit("cases must not exist: " + str(args.cases))
    output.mkdir(parents=True)
    temp = None
    if args.cases is None:
        temp = tempfile.TemporaryDirectory(prefix="hp-t18-report-cases-")
        cases = Path(temp.name)
    else:
        cases = args.cases.resolve()
        cases.mkdir(parents=True)
    before = {p: identity(instance_area.path(p)) for p in INPUTS}
    started = time.monotonic()
    with (output / "unittest.log").open("w") as log:
        log.write("## run 1\n")
        log.flush()
        records = run(MODULES, cases / "run-1", log).records
        reruns = []
        for record in [r for r in records if r["outcome"] == "ERROR"]:
            log.write("\n## re-run of %s (ERROR in run 1; ERROR is never product PASS or FAIL)\n" % record["test"])
            log.flush()
            reruns.extend(dict(r, rerunOf=record["test"]) for r in run([record["test"]], cases / ("rerun-" + record["test"].rsplit(".", 1)[-1]), log).records)
    test_seconds = round(time.monotonic() - started, 3)
    evidence = {}
    for name, test in (("refusals", "test_ac04_each_refusal_is_classified_and_starts_nothing"),
                       ("minimalPath", "test_ac08_minimal_path_through_the_installed_bundle"),
                       ("killBeforeReply", "test_ac07_killed_before_the_reply_nothing_is_duplicated")):
        found = sorted((cases / "run-1").glob("t18-%s/*.json" % test))
        if found:
            evidence[name] = json.loads(found[0].read_text())
    delivery = delivery_checks(args.delivery, openssl, cases) if args.delivery else None
    after = {p: identity(instance_area.path(p)) for p in INPUTS}
    final = {}
    for r in records:
        prior = final.get(r["test"])
        if prior is None or prior["outcome"] == "PASS":
            final[r["test"]] = r
    for r in reruns:
        final[r["test"]] = r
    finals = list(final.values())
    key_forms = raw_key_forms(args.key_scan, openssl) if args.key_scan else []
    scanned = [p for p in instance_area.path("records/diagnostics/feature-t18").rglob("*") if p.is_file()]
    scanned += [p for p in output.iterdir() if p.is_file()]
    if args.delivery:
        scanned += [p for p in Path(args.delivery).rglob("*") if p.is_file()]
    tracked = (git("ls-files") or "").splitlines()
    scanned += [ROOT / p for p in tracked if (ROOT / p).is_file()]
    scan_rows, scan_hits = scan(scanned, key_forms)
    if delivery:
        member_hits = sum(1 for data in delivery["memberData"].values() for p in PRIVATE_PATTERNS if p.search(data))
        member_hits += sum(1 for data in delivery["memberData"].values() for form in key_forms if form in data)
        delivery["memberScan"] = dict(members=len(delivery["memberData"]), hits=member_hits)
        scan_hits += member_hits
        delivery.pop("memberData")
    del key_forms
    base = "8e3c5a85fb63d256d1b4d46e5dcf93c2a2972349"
    head = git("rev-parse", "HEAD")
    path_scan = dict(pattern_note="absolute paths under a user's home directory (/Users/<name>, /home/<name>)",
                     baseline=dict(commit=base, hits=path_hits(base)), head=dict(commit=head, hits=path_hits(head)))
    path_scan["newHits"] = sorted(set(path_scan["head"]["hits"]) - set(path_scan["baseline"]["hits"]))
    criteria = {}
    for ac, subject in CRITERIA.items():
        tests = [r for r in finals if ac in r["criteria"]]
        outcomes = {r["outcome"] for r in tests}
        if ac == "AC-11":
            ok = all(r["outcome"] == "PASS" for r in finals) and (delivery is None or all(c["result"] == "PASS" for c in delivery["checks"]))
            result_ac = "PASS" if ok and before == after else "FAIL"
        elif not tests:
            result_ac = "NOT_RUN"
        elif "FAIL" in outcomes:
            result_ac = "FAIL"
        elif "ERROR" in outcomes:
            result_ac = "NOT_RUN"
        else:
            result_ac = "PASS"
        if ac == "AC-10" and scan_hits:
            result_ac = "FAIL"
        if ac in ("AC-02", "AC-03", "AC-04") and delivery and any(c["result"] != "PASS" for c in delivery["checks"]):
            result_ac = "FAIL"
        criteria[ac] = dict(subject=subject, result=result_ac, tests=[dict(test=r["test"], outcome=r["outcome"], seconds=r["seconds"])
                                                                      for r in tests],
                            failed=[r["test"] for r in tests if r["outcome"] == "FAIL"],
                            errors=[r["test"] for r in tests if r["outcome"] == "ERROR"], not_run=NOT_RUN.get(ac, []))
    report = dict(
        kind="feature-t18-acceptance-report", generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        environment=environment(openssl), sources={p: identity(APP / p) for p in SOURCES},
        inputs=dict(before=before, after=after, unchanged=before == after),
        buildInputs=dict(lock=identity(APP / "bundle/inputs.lock.json"), note="asset and wheels are read from HP_BUNDLE_INPUTS_DIR by digest"),
        tests=records, reruns=reruns, testSeconds=test_seconds, criteria=criteria, evidence=evidence, delivery=delivery,
        privateKeyScan=dict(files=len(scan_rows), hits=scan_hits, rawKeyFormsSearched=bool(args.key_scan), rows=scan_rows),
        pathScan=path_scan,
        conclusion=dict(allCriteria={ac: c["result"] for ac, c in criteria.items()},
                        tests=dict(total=len(finals), passed=sum(r["outcome"] == "PASS" for r in finals),
                                   failed=sum(r["outcome"] == "FAIL" for r in finals), errors=sum(r["outcome"] == "ERROR" for r in finals))),
        limits=["The Host here is hp's synthetic reproduction of the receiver; the receiver's own admission and launch are NOT_RUN.",
                "Program identities are those of SYNTHETIC Agent and platform programs; no real Agent, model, remote or platform ran."])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    lines = ["# feature-t18 acceptance report", "", "| AC | 结论 | 测试 |", "| --- | --- | --- |"]
    for ac, c in criteria.items():
        lines.append("| %s %s | %s | %d |" % (ac, c["subject"], c["result"], len(c["tests"])))
    lines += ["", "测试：%(total)d，PASS %(passed)d，FAIL %(failed)d，ERROR %(errors)d；耗时 %(s)s 秒。" % dict(report["conclusion"]["tests"], s=test_seconds),
              "私钥扫描：%d 个文件，命中 %d。" % (len(scan_rows), scan_hits),
              "家目录绝对路径检索（apps/、mechanisms/、.agents/）：基线 %d，HEAD %d，本任务新增 %d。" % (
                  len(path_scan["baseline"]["hits"]), len(path_scan["head"]["hits"]), len(path_scan["newHits"]))]
    if delivery:
        lines += ["", "交付构建：%s %s，archive %s（%d bytes），检查 %s。" % (
            delivery["runtimeId"], delivery["version"], delivery["archive"]["sha256"], delivery["archive"]["bytes"],
            ", ".join("%s=%s" % (c["check"], c["result"]) for c in delivery["checks"]))]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    if temp is not None:
        temp.cleanup()
    print(json.dumps(report["conclusion"], ensure_ascii=False))
    return 0 if all(c["result"] == "PASS" for c in criteria.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
