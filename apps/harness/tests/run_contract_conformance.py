"""Reproducible new-runtime evidence; historical fixtures remain separately frozen."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest

APP=Path(__file__).resolve().parents[1]
REPO=APP.parents[1]
sys.path.insert(0,str(APP))
from runtime.protocol import DIGEST, METHODS, SCHEMA, VERSION, Schemas

AC_TESTS={
 "AC-01":["test_strict_frames","test_params_correlation_and_liveness","test_negotiated_unterminated_frame_closes","test_event_window_preserves_control_requests","test_tiny_limit_profile_is_rejected_without_partial_initialize"],
 "AC-02":["test_launch_and_required_capability_digests","test_dynamic_grants_and_inactive","test_inflight_grant_result_cannot_reactivate_scope","test_grant_revoked_while_decision_awaited","test_product_has_no_synthetic_capability"],
 "AC-03":["test_basic_scopes_and_pagination","test_snapshot_to_subscribe_and_ack","test_epoch_loss_and_cross_scope_tokens","test_snapshot_lease_expiry_with_controlled_clock","test_snapshot_cache_is_bounded"],
 "AC-04":["test_action_payload_and_human_decision","test_missing_operation_and_action","test_local_registry_resolves_and_never_downloads"],
 "AC-05":["test_auth_before_dedup","test_idempotency_and_digest","test_replay_after_action_removed","test_tombstone_and_unknown_index","test_crash_before_durable_acceptance","test_crash_after_commit_before_invoke_reply"],
 "AC-06":["test_cancel_quiesce_and_shutdown","test_cancel_completed_target_preserves_terminal","test_crash_after_cancel_commit_before_reply"],
 "AC-07":["test_upgrade_release_atomic_revision","test_blocked_upgrade_and_restart_barrier","test_shared_writer_obeys_upgrade_barrier","test_crash_after_release_commit_before_reply","test_read_only_retry_preserves_revision"],
 "AC-08":["test_resource_identity_and_terminal_errors","test_all_ten_reverse_methods_real_pipes","test_all_ten_reject_mismatched_context","test_all_ten_propagate_host_error","test_all_ten_timeout_preserves_unknown","test_all_ten_reject_schema_violation"],
 "AC-09":["report:source-identities","report:method-coverage","report:wire-validation"],
 "AC-10":["README.md","coordinator-independent-acceptance"]}

def fingerprint():
    files=[]
    for p in sorted(APP.rglob("*")):
        if p.is_file() and not any(part in (".venv","__pycache__") for part in p.relative_to(APP).parts):
            data=p.read_bytes()
            files.append(dict(path=str(p.relative_to(REPO)),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    return files

class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.cases=[];self.subcases=[]
    def addSuccess(self,test):
        super().addSuccess(test);self.cases.append(dict(id=test.id(),status="PASS"))
    def addFailure(self,test,error):
        super().addFailure(test,error);self.cases.append(dict(id=test.id(),status="FAIL",detail=self._exc_info_to_string(error,test)))
    def addError(self,test,error):
        super().addError(test,error);self.cases.append(dict(id=test.id(),status="ERROR",detail=self._exc_info_to_string(error,test)))
    def addSubTest(self,test,subtest,error):
        super().addSubTest(test,subtest,error)
        self.subcases.append(dict(id=subtest.id(),status="PASS" if error is None else "FAIL"))

def wire_report(directory):
    schemas=Schemas()
    coverage={method:dict(direction=desc["direction"],requests=0,successes=0,errors=0,evidence=[]) for method,desc in METHODS.items()}
    failures=[];count=0
    for path in sorted(directory.rglob("*frames*.jsonl")):
        pending={}
        for number,line in enumerate(path.read_text().splitlines(),1):
            entry=json.loads(line);frame=entry["frame"];method=frame.get("method")
            # Deliberate Host-invalid responses are inputs, not Runtime protocol outputs.
            location=str(path.relative_to(directory))+":"+str(number)
            if entry["direction"]=="runtime-to-host":
                try:
                    if method=="runtime.event":schemas.validate("Notification",frame)
                    elif method:
                        schemas.validate("Request",frame);schemas.validate(METHODS[method]["params"],frame["params"])
                    elif "error"in frame:schemas.validate("Failure",frame)
                    else:
                        schemas.validate("Success",frame)
                        if frame["id"]in pending:schemas.validate(METHODS[pending[frame["id"]]]["result"],frame["result"])
                    count+=1
                except Exception as exc:failures.append(dict(location=location,error=str(exc)))
            if method in METHODS and "id"in frame:
                pending[frame["id"]]=method
                try:schemas.validate(METHODS[method]["params"],frame["params"])
                except Exception:continue
                coverage[method]["requests"]+=1
            elif "id"in frame and frame["id"]in pending:
                request_method=pending[frame["id"]]
                kind="successes" if "result"in frame else "errors"
                if kind=="successes":
                    try:schemas.validate(METHODS[request_method]["result"],frame["result"])
                    except Exception:continue
                coverage[request_method][kind]+=1
                if len(coverage[request_method]["evidence"])<8:coverage[request_method]["evidence"].append(location)
    for method,value in coverage.items():
        value["status"]="PASS" if value["requests"] and value["successes"] else "NOT_COVERED"
        value["meaning"]="Runtime behavior with synthetic DomainPort" if value["direction"]=="host-to-runtime" else "Host client codec/correlation only; synthetic broker, no physical execution"
    return dict(validatedRuntimeFrames=count,failures=failures,methods=coverage)

def durable_facts(directory):
    facts=[]
    for marker in sorted(directory.rglob(".synthetic-hp-domain")):
        repo=marker.parent
        def git(*args):return subprocess.run(["git","-C",str(repo),*args],capture_output=True,text=True,check=True).stdout.strip()
        try:
            head=git("rev-parse","refs/harness/runtime")
            state=json.loads(git("show",head+":state.json"))
            facts.append(dict(repository=str(repo.relative_to(directory)),ref="refs/harness/runtime",commit=head,state=state))
        except subprocess.CalledProcessError:pass
    return facts

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True,type=Path);parser.add_argument("--pattern",default="test_*.py",choices=["test_*.py","test_host_client.py"]);args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    before=fingerprint()
    os.environ["HP_TEST_OUTPUT"]=str(output/"cases")
    suite=unittest.defaultTestLoader.discover(str(APP/"tests"),pattern=args.pattern)
    with (output/"unittest.log").open("w") as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    wire=wire_report(output/"cases")
    cases={r["id"].split(".")[-1]:r["status"] for r in result.cases}
    required_methods = [m for m,d in METHODS.items() if args.pattern == "test_*.py" or d["direction"] == "runtime-to-host"]
    ac={key:dict(tests=tests,status=("PENDING_COORDINATOR_ACCEPTANCE" if key=="AC-10" else
         "PASS" if key=="AC-09" and not wire["failures"] and all(m["status"]=="PASS" for m in wire["methods"].values())
         or key!="AC-09" and all(cases.get(test)=="PASS" for test in tests) else "FAIL")) for key,tests in AC_TESTS.items()}
    source_unchanged=before==fingerprint()
    report=dict(schema="hp-runtime-conformance/v1",startedFromCommit=subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"],text=True).strip(),
        scope="full" if args.pattern == "test_*.py" else "host-client-delta", protocolVersion=VERSION,contractDigest=DIGEST,createdAt=datetime.now(timezone.utc).isoformat(),
        environment=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),
            dependencies={name:version(name) for name in ("jsonschema","rfc8785","referencing","attrs","jsonschema-specifications","rpds-py","typing-extensions")}),
        files=before,sourceUnchanged=source_unchanged,testsRun=result.testsRun,cases=result.cases,subcases=result.subcases,
        wire=wire,acceptanceCriteria=ac,passed=result.wasSuccessful() and source_unchanged and not wire["failures"] and all(wire["methods"][m]["status"]=="PASS" for m in required_methods),
        historicalFixtures=dict(sourceCheckpoint="7e70aeb3e46b987e9b4c5a7f961b17e17ec24189",protocolVersion="0.1.0-draft.4",transcripts=32,
            inputInventory="records/diagnostics/feature-t16/2026-09-21/inputs.json",staticValidation="Assistant original validator: 270 checks PASS in input preparation; not rerun or promoted to Runtime behavior"),
        limits=["Synthetic Git DomainPort and Host broker; no actual Workflow or model execution", "No bundle/upgrade maintenance or physical ExecutionPort qualification", "Human done and J-02 coordinator acceptance are external gates"])
    if args.pattern != "test_*.py":
        report["acceptanceCriteria"] = {key: dict(value, status="NOT_EVALUATED_IN_HOST_CLIENT_DELTA") for key,value in ac.items()}
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    (output/"durable-facts.json").write_text(json.dumps(durable_facts(output/"cases"),ensure_ascii=False,indent=2)+"\n")
    with gzip.open(output/"wire-frames.jsonl.gz","wt",encoding="utf-8") as archive:
        for path in sorted((output/"cases").rglob("*frames*.jsonl")):
            for number,line in enumerate(path.read_text().splitlines(),1):
                archive.write(json.dumps(dict(source=str(path.relative_to(output/"cases")),line=number,**json.loads(line)),ensure_ascii=False)+"\n")
    print(json.dumps(dict(passed=report["passed"],testsRun=result.testsRun,runtimeFrames=wire["validatedRuntimeFrames"],coveredMethods=sum(m["status"]=="PASS" for m in wire["methods"].values()),report=str(output/"report.json"))))
    return 0 if report["passed"] else 1

if __name__=="__main__":raise SystemExit(main())
