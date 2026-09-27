"""Test-only fixtures for feature-t3: a synthetic product line with one accepted Task, candidate
Definitions on its task branch, a synthetic review Registry, synthetic reviewer output and a
synthetic authorization callback. Nothing here is a production authority, model or Host.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.acceptance.accept import accept_task, set_configuration
from domain.core import HarnessDomain
from execution.port import ExecutionAuthorization, ExecutionError, identity, sha
from product_line import create_product_line, git, write

HP = Path(__file__).resolve().parents[3]
VALIDATOR = "mechanisms/artifact-templates/artifact_lint.py"
REGISTRY = "mechanisms/review-channel/review_channel_registry.json"
EVIDENCE = "records/synthetic/author-evidence.md"
OWNER = "owner:synthetic"
DIGEST = "8061614dbefcbb03bab19bb15b2c23a1427d4555ffadd06ea859bed8b83a5d63"


def profile():
    return dict(id="review/codex-native-readonly", version="1", digest=DIGEST, trustModel="current-user", purpose="review",
                programIdentity=dict(launcher="/synthetic/codex", binaryDigest="e" * 64, version="synthetic"),
                nativeApprovalPolicy="expected-range-gate", configurationDigest=DIGEST, capabilities=["read-only"],
                limitations=["current-user"], operations=["review"], maxContextBytes=1048576, maxToolCalls=20, maxRunSeconds=600)


def port(port_id, mode, status):
    app = dict(executionPort=mode, purpose="review", trustModel="current-user", profileDigest=DIGEST,
               configurationRevision="7", credentialRevision="2")
    return dict(id=port_id, mode=mode, profile=profile(), provider="codex-builtin", model_ref="gpt-6-sol",
                transport="builtin", effort="high", mapping_id="synthetic-openai", approval_policy="expected-range-gate",
                applicability=app, capability=dict(status=status, evidence=None))


def registry(embedded="CONFIGURED", standalone="CONFIGURED"):
    ports = []
    if embedded:
        ports.append(port("embedded", "embedded", embedded))
    if standalone:
        ports.append(port("standalone", "standalone", standalone))
    return dict(registry_schema="review-channel-registry/v5", registry_revision=1, execution_ports=ports,
                model_mappings=[dict(id="synthetic-openai", revision=1, provider="codex-builtin", model_ref="gpt-6-sol",
                                     actual_models=["gpt-6-sol"], model_vendor="OpenAI", route_vendor=None,
                                     allowed_sources=["protocol-init", "protocol-result"])])


def live_registry_copy(standalone=True):
    """The hp live Registry bytes as a product-line Registry: provider capabilities CONFIGURED (their Receipt
    evidence lives only in hp) and, for the standalone entry, a standalone copy of the embedded review port."""
    live = json.loads((HP / REGISTRY).read_text())
    for provider in live["providers"].values():
        for model in provider["models"].values():
            model["capability"] = dict(status="CONFIGURED", note="synthetic copy; evidence stays in hp")
    if standalone:
        embedded = next(p for p in live["execution_ports"] if p["id"] == "embedded")
        other = copy.deepcopy(embedded)
        other.update(id="standalone", mode="standalone")
        other["applicability"]["executionPort"] = "standalone"
        live["execution_ports"].append(other)
    return live


def definition_text(task_id="feature-t0", revision=1, *, h1=None, subject=None, primary=None, depends=None,
                    drop=None, duplicate=None, guide=False):
    """A strict v1 Definition for the synthetic task; keyword arguments break one thing at a time."""
    source = f"milestones.md@r{revision} {task_id}"
    sections = [
        ("Identity", f"- Task record ID: `{task_id}`\n- Task kind: `feature`\n- Definition subject: `{subject or task_id + '-task'}`\n- Product line: `synthetic`"),
        ("通俗说明（给人读）", "本节只帮助人建立心智模型，不是任务契约的权威取值；冲突时以其余正式章节为准。\n\n合成任务。"),
        ("Goal", "Synthetic goal."), ("Goal Conditions", "- Synthetic condition."), ("Scope In", "- Synthetic scope."),
        ("Scope Out", "- Synthetic exclusion."), ("Constraints", "- Synthetic constraint."),
        ("Acceptance Criteria", "- AC-01：synthetic."),
        ("Source References", f"- Primary source: `{primary or source}`"),
    ]
    if drop:
        sections = [s for s in sections if s[0] != drop]
    if duplicate:
        sections = sections + [s for s in sections if s[0] == duplicate]
    head = (f"# {h1 or task_id} · Synthetic Definition\n\n> Depends on:\n> `{depends or source}`\n>\n"
            f"> 权威状态: subject `{task_id}-task`（治理记录目录按所在仓的布局规则解析；唯一状态正本）\n\n")
    body = "\n\n".join(f"## {name}\n\n{text}" for name, text in sections) + "\n"
    if guide:
        body += "\n<!-- template:guide\nleft over\n-->\n"
    return head + body


def create(directory, *, definition_review=False, registry_doc=None, task_id="feature-t0", author_vendor=False):
    directory = Path(directory)
    repo, _head = create_product_line(directory / "repo")
    write(repo, VALIDATOR, (HP / VALIDATOR).read_bytes())
    write(repo, REGISTRY, json.dumps(registry_doc or registry(), indent=1) + "\n")
    write(repo, EVIDENCE, "Synthetic author evidence: human declaration fixture.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "synthetic validator, registry and author evidence")
    head = git(repo, "rev-parse", "HEAD")
    domain = HarnessDomain(repo, entry="cli")
    generation = domain.bind_entry()
    if definition_review:
        set_configuration(domain.store, "definition-review", True, OWNER)
    if author_vendor:
        set_configuration(domain.store, "author-vendor", dict(agent="claude-code", model="claude-opus-5", vendor="Anthropic"), OWNER)
    accept_task(domain.store, dict(requestId="fixture-1", repository=str(repo), taskType="feature", taskId=task_id,
                                   baseRef="main", worktreeRoot=str(directory / "worktrees"), authorityRef=OWNER))
    task = domain.store.read()["tasks"][task_id]
    return dict(repo=Path(repo), head=head, domain=domain, generation=generation, task=task,
                worktree=Path(task["worktree"]), branch=task["branch"], taskId=task_id)


def commit_candidate(worktree, text, task_id="feature-t0", message="synthetic candidate", raw=None):
    write(worktree, f"tasks/{task_id}/{task_id}.md", raw if raw is not None else text)
    git(worktree, "add", "-A")
    git(worktree, "commit", "-q", "-m", message)
    return git(worktree, "rev-parse", "HEAD")


def author(head, human_only=False):
    ref = [dict(commit=head, path=EVIDENCE)]
    if human_only:
        return dict(tool=None, model=None, vendor=None, humanOnly=True, evidenceRefs=ref)
    return dict(tool="claude-code", model="claude-opus-5", vendor="Anthropic", humanOnly=False, evidenceRefs=ref)


# -- synthetic review output -----------------------------------------------------------------------
QUESTIONS = ("Q-FIDELITY", "Q-GOAL", "Q-BOUNDARY", "Q-ACCEPT", "Q-EXEC")


def verdict_block(descriptor, verdict="PASS", *, human=False, questions=QUESTIONS, stage="task", candidate_sha=None,
                  schema="review-channel-verdict/v4"):
    data = descriptor["input"]
    findings = []
    assessments = [dict(question_id=q, assessment="SATISFIED", evidence_refs=[], finding_ids=[]) for q in questions]
    if verdict == "FAIL":
        findings.append(dict(id=data["round"].upper() + "-B1", severity="blocking", title="synthetic blocking",
                             location=dict(file="candidate", anchor="Goal"), origin="changed_region", summary="synthetic"))
        assessments[0].update(assessment="NOT_SATISFIED", finding_ids=[findings[-1]["id"]])
    if human:
        findings.append(dict(id=data["round"].upper() + "-H1", severity="human", title="synthetic human question",
                             location=dict(file="candidate", anchor="Scope"), origin="changed_region", summary="synthetic"))
        assessments[1].update(assessment="INDETERMINATE", finding_ids=[findings[-1]["id"]])
    bundle = dict(bundle_name="candidate", sha256=candidate_sha or data["candidate"]["sha256"])
    return dict(verdict_schema=schema, verdict=verdict, human_decision_required=human, subject=data["subject"], stage=stage,
                round=data["round"], candidate=bundle, candidates=[bundle], question_assessments=assessments,
                findings=findings, previous_findings_disposition=[], accepted_residuals_acknowledged=[],
                scope_files_read=["candidate"], tools_used=["read"], authorization_disclaimer=True)


def valid_outcome(descriptor, block):
    raw = ("```review-channel-verdict\n" + json.dumps(block, ensure_ascii=False) + "\n```\n\n**Verdict: %s**\n" % block["verdict"]).encode()
    digest = hashlib.sha256(raw).hexdigest()
    receipt = dict(classification="completed_with_valid_verdict", verdict_validation="VALID", verdict_published=True,
                   verdict_sha256=digest, failure_code=None)
    ref = dict(kind="synthetic", path="synthetic/receipt-%s.json" % descriptor["input"]["round"], sha256="d" * 64)
    return dict(classification="completed_with_valid_verdict", receipt=receipt, verdict=block, verdictSha256=digest,
                evidenceRef=dict(kind="synthetic", path="synthetic/verdict.md", sha256=digest), receiptRef=ref,
                published=dict(verdict_path="synthetic/verdict.md", receipt_path=ref["path"]))


def failed_outcome(classification, code=None, receipt=True):
    out = dict(classification=classification, failureCode=code)
    if receipt:
        out.update(receipt=dict(classification=classification, failure_code=code, verdict_validation="NOT_REACHED",
                                verdict_published=False), receiptRef=dict(kind="synthetic", path="synthetic/failed.json", sha256="f" * 64))
    return out


class SyntheticReviewer:
    """Scripted reviewer: a queue of outcome builders; counts provider calls it would have made."""

    def __init__(self, *scripts, gate=None, mode="preflight"):
        self.mode = mode  # preflight: the real feature-t17 port preflight; authority: callback only (Runtime tests)
        self.scripts = list(scripts)
        self.calls = 0
        self.requests = []
        self.gate = gate  # optional asyncio.Event the runner waits on (non-blocking test)
        self.query_answer = None

    async def __call__(self, descriptor, env, port, binding, registration, mapping):
        from domain.definition.dispatch import request_document
        request = request_document(descriptor, descriptor["input"].get("formalFactId"))
        self.requests.append(request)
        try:
            if self.mode == "preflight":
                from domain.definition.dispatch import intent_document
                port.bind_result_scanner(self, lambda: [])
                self.intents = getattr(self, "intents", []) + [intent_document(descriptor, env, registration, mapping, binding, request)]
                await port.preflight(self.intents[-1])
            else:
                from domain.definition.dispatch import intent_document
                self.intents = getattr(self, "intents", []) + [intent_document(descriptor, env, registration, mapping, binding, request)]
                await port.authority(self.intents[-1])
        except ExecutionError as exc:
            return dict(classification="preflight_failed", failureCode=exc.code)
        if self.gate is not None:
            while not self.gate.is_set():
                await asyncio.sleep(0.02)
        self.calls += 1
        script = self.scripts.pop(0) if self.scripts else ("valid", "PASS")
        if callable(script):
            return script(descriptor)
        kind = script[0]
        if kind == "valid":
            return valid_outcome(descriptor, verdict_block(descriptor, script[1], **(script[2] if len(script) > 2 else {})))
        return failed_outcome(*script[1:])

    async def query(self, descriptor, env):
        return self.query_answer or dict(classification="unknown", failureCode="synthetic-query-unknown")


def synthetic_intent(descriptor, registration, mapping, request):
    return dict(invocation_authorization=request["invocation_authorization"], caller=request["caller"],
                executionBinding=dict(modelVendor=mapping["model_vendor"]), taskId=descriptor["taskId"],
                round=descriptor["input"]["round"])


def synthetic_authorizer(decision="ALLOW", calls=None, formal_from_domain=True):
    """Test double for feature-t6's execution_authorizer(domain, task_id, subject, entry, generation). Synthetic.

    owner_formal is read from the Owner formal authorization fact the feature-t3 entry records (purpose
    owner-formal-review-authorization), which is the fact shape feature-t6 reads.
    """
    def factory(domain, task_id, subject, entry, generation, *, context=None):
        async def authorize(intent):
            owner_formal = True
            if formal_from_domain:
                facts = domain.store.read()["tasks"][task_id]["workflowInstance"]["facts"].values()
                owner_formal = any(f["purpose"] == "owner-formal-review-authorization" for f in facts)
            if calls is not None:
                calls.append(dict(taskId=task_id, subject=subject, entry=entry, intent=copy.deepcopy(intent),
                                  context=context() if context else None, generation=generation()))
            if decision != "ALLOW":
                raise ExecutionError("policy-denied" if decision == "DENY" else "policy-not-determinable", "preflight_failed")
            return ExecutionAuthorization(identity(intent), sha(intent["invocation_authorization"].encode()), intent["caller"],
                                          ("Anthropic",), ("synthetic-author",), owner_formal, 2, "synthetic-policy:allow")
        return authorize
    return factory


def real_executors(reviewer):
    """The production port factory with feature-t6's real callback; only the reviewer output is synthetic."""
    from domain.definition import dispatch
    from runtime.executions import build_port
    return {"review": dispatch.ReviewExecutor(reviewer, build_port), "ruling-write": dispatch.ruling_executor}


def executors(reviewer, authorizer=None):
    """Test executors: the production ruling writer and review executor with synthetic runner and callback."""
    import functools
    from domain.definition import dispatch
    from runtime.executions import build_port
    factory = functools.partial(build_port, authorizer=authorizer or synthetic_authorizer())
    return {"review": dispatch.ReviewExecutor(reviewer, factory), "ruling-write": dispatch.ruling_executor}


BINDINGS = {"embedded": dict(connectionRef="connection:synthetic", credentialRef="credential:synthetic", credentialRevision="2",
                             configurationRevision="7", agent="agent:codex", protocolProvider="openai")}


class TestHarnessDomain(HarnessDomain):
    """Test-only: the production Domain Core with the feature-t6 availability check answered by the test.

    feature-t6's domain/policy/authorize.py is not on this branch yet; the executors given to the test
    layer carry the explicitly synthetic callback, and this override only lets dispatch proceed.
    """

    authorizer_present = True

    def definition_context(self):
        context = super().definition_context()
        if self.authorizer_present:
            context.authorizer_check = lambda: True
        return context


def runtime_files(directory, fx):
    """launch.json and host-template.json for a Host driver over serve_definition.py."""
    import hashlib as _h
    from domain.acceptance import projection as acceptance_projection
    from domain.definition import projection as definition_projection
    from domain.workflow import projection as workflow_projection
    from workflow_fixture import CONTRACT_DIGEST, LIMITS, VERSION
    directory = Path(directory)
    scope = "scope:" + _h.sha256(b"binding:one").hexdigest()[:24]
    capabilities = [acceptance_projection.capability(), workflow_projection.capability(), definition_projection.capability()]
    auth = dict(authorizationRef="launch:one", bundleDigest="b" * 64, permissionProfileDigest="c" * 64, expiresAt="2099-01-01T00:00:00Z")
    config = dict(installationId="installation:test", instanceId="instance:test", incarnationId="incarnation:one",
                  connectionId="connection:one", bundleDigest="b" * 64, dataFormat="hp-domain-v1", launchAuthorization=auth,
                  executionProfileRequirements=[], repository=str(fx["repo"]), executionBindings=copy.deepcopy(BINDINGS))
    initialize = {k: v for k, v in config.items() if k not in ("dataFormat", "executionProfileRequirements", "repository", "executionBindings")}
    initialize.update(protocols=[dict(version=VERSION, contractDigest=CONTRACT_DIGEST)], capabilities=capabilities,
                      executionProfiles=[], limits=LIMITS)
    template = dict(scopeRef=scope, binding=dict(bindingRef="binding:one", resourceHandle="resource:one", expiresAt="2099-01-01T00:00:00Z"),
                    initialize=initialize, repository=str(fx["repo"]), capabilities=capabilities, taskId=fx["taskId"])
    for name, data in (("launch.json", config), ("host-template.json", template)):
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return template
