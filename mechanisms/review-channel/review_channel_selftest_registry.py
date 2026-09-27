"""自测声明：review_channel_registry（第 2 类 schema 与约束、第 21 类 receipt_ref 核验、第 22 类适配器发现；KB-249 活体 Registry legacy 读取回归）。"""
import json
import os

import review_channel_base as base
import review_channel_contract as C
import review_channel_receipt as RC
import review_channel_registry as G
import review_channel_runtime as RT


def _loader(e, names=("fake", "fakeinline")):
    d = e.fake_adapters(names=names)
    return lambda rid: RT.load_adapter(rid, d), d


def _load(e, mutate=None, loader=None, verify=False, repo_root=None):
    p = e.fake_registry(mutate)
    ld = loader or _loader(e)[0]
    return G.load_registry(p, adapter_loader=ld, repo_root=repo_root or e.tmpdir("nr"), verify_evidence=verify)


def _rej(e, mutate, code="registry-invalid", message=""):
    e.expect_error(lambda: _load(e, mutate), code=code, message=message or code)


def schema_and_constraints(e):
    reg = _load(e)
    e.check(reg["revision"] == 1 and set(reg["adapters"]) == {"fake", "fakeinline"}, "sample registry loads")
    _rej(e, lambda r: r.update(registry_schema="review-channel-registry/v2"), message="schema version")
    _rej(e, lambda r: r.update(registry_revision=True), message="revision bool")
    _rej(e, lambda r: r["defaults"].pop("max_rounds"), message="defaults.max_rounds required")
    _rej(e, lambda r: r["defaults"].update(timeout_seconds="60"), message="defaults type")
    _rej(e, lambda r: r["defaults"].update(effort="ultra"), message="defaults effort closed set")
    _rej(e, lambda r: r.update(system_default={"provider": "fake-official", "model": "nope"}), message="system_default must exist")
    _rej(e, lambda r: r["providers"]["fake-official"].update(kind="weird"), message="kind closed set")
    _rej(e, lambda r: r["providers"]["fake-official"].update(transport="smoke"), message="transport closed set")
    _rej(e, lambda r: r["providers"]["fake-official"].update(auth_source="~/x"), message="auth_source forbidden for official-direct")
    _rej(e, lambda r: r["providers"]["fake-official"].pop("base_env"), message="base_env required")
    _rej(e, lambda r: r["providers"]["fake-inline"]["models"]["inline-model"].pop("max_input_bytes"), message="max_input_bytes required for inline")
    # r18 R18-B2 整改：runtime / kind 不适用的字段一律拒绝（§6.11 schema），不得接受后被忽略
    _rej(e, lambda r: r["providers"]["fake-official"].update(structured_output="json_object"), message="structured_output forbidden on a non-inline runtime")
    _rej(e, lambda r: r["providers"]["fake-official"]["models"]["fake-model"].update(max_input_bytes=1000), message="max_input_bytes forbidden on a non-inline runtime")
    _rej(e, lambda r: r["providers"]["fake-official"]["models"]["fake-model"].update(registered_equivalents={"a": "b"}), message="registered_equivalents forbidden on an official-direct model")
    _rej(e, lambda r: r["providers"]["fake-inline"]["models"]["inline-model"].update(registered_equivalents={"a": "b"}), message="registered_equivalents forbidden on an inline official-direct model")
    _rej(e, lambda r: r["providers"]["fake-aggregator"].update(registered_equivalents={}), message="provider-level registered_equivalents is outside the frozen schema")
    e.check(_load(e, lambda r: r["providers"]["fake-aggregator"]["models"]["agg-model"].update(registered_equivalents={"x": "y"}))["revision"] == 1,
            "aggregator model-level registered_equivalents accepted")
    _rej(e, lambda r: r["providers"]["fake-official"]["models"]["fake-model"].update(default_effort="medium"),
         message="default_effort in supported_efforts")
    _rej(e, lambda r: r["providers"]["fake-official"]["models"]["fake-model"].update(claimed_vendor="deepseek"),
         code="vendor-not-registered", message="claimed_vendor case variant")
    _rej(e, lambda r: r["providers"]["fake-official"]["models"]["fake-model"]["capability"].update(status="PROBED"),
         message="PROBED claimed without binding tuple")
    _rej(e, lambda r: r["providers"]["fake-official"]["models"]["fake-model"]["capability"].update(
        status="REVIEW_ENABLED", bound_transport="responses", bound_effort="medium", receipt_ref="r", receipt_commit="a" * 40,
        receipt_sha256="b" * 64), message="bound_effort must be supported")

    def builtin(r):
        r["providers"]["fake-builtin"] = {"display_name": "b", "kind": "builtin-native", "runtime": "fake", "transport": "builtin",
                                          "auth_source": "~/.codex/auth.json", "models": {}}
    e.check("fake-builtin" in _load(e, builtin)["registry"]["providers"], "builtin-native with auth_source loads")

    def builtin_bad(r):
        builtin(r)
        r["providers"]["fake-builtin"]["key_env"] = "K"
    _rej(e, builtin_bad, message="key_env forbidden for builtin-native")
    e.check(G.effective_status({"capability": {"status": "PROBED", "bound_transport": "chat", "bound_effort": "high"}}, "chat", "low") == "UNVERIFIED",
            "tuple drift falls to UNVERIFIED")
    e.check(G.admission("REGISTERED", "probe", True) == "capability-not-configured", "REGISTERED refused")
    e.check(G.admission("CONFIGURED", "review", False) == "formal-authorization-required", "CONFIGURED needs formal")
    e.check(G.admission("PROBED", "probe", True) is None and G.admission("REVIEW_ENABLED", "review", False) is None, "admission matrix")


def adapter_discovery(e):
    _rej(e, lambda r: r["providers"]["fake-official"].update(runtime="ghost"), code="runtime-adapter-missing", message="absent adapter file")
    d = e.fake_adapters(names=("fake",))
    src = open(os.path.join(d, "fake.py"), encoding="utf-8").read().replace(
        'SUPPORTED_TRANSPORTS = ("responses", "chat", "messages", "builtin")', 'SUPPORTED_TRANSPORTS = ("chat",)')
    open(os.path.join(d, "fake.py"), "w", encoding="utf-8").write(src)
    ld = lambda rid: RT.load_adapter(rid, d)  # noqa: E731
    p = e.fake_registry(lambda r: (r["providers"].pop("fake-inline"), r["providers"].pop("fake-aggregator")))
    e.expect_error(lambda: G.load_registry(p, adapter_loader=ld, verify_evidence=False), code="registry-invalid",
                   message="transport outside adapter support set")
    p2 = e.fake_registry(lambda r: (r["providers"].pop("fake-inline"), r["providers"].pop("fake-aggregator"),
                                    r["providers"]["fake-official"].update(transport="chat")))
    e.check("fake-official" in G.load_registry(p2, adapter_loader=ld, verify_evidence=False)["registry"]["providers"], "supported transport passes")
    mod = RT.load_adapter("http")
    import http as stdlib_http
    e.check(mod is not None and mod.RUNTIME_ID == "http" and hasattr(stdlib_http, "HTTPStatus"), "adapters/http.py loads without shadowing stdlib http")
    e.check("review_channel_adapter_http" in __import__("sys").modules, "module name prefix")
    e.check(RT.load_adapter("../x") is None and RT.load_adapter("") is None, "runtime id grammar")


def _receipt(mode, phase, classification, three, published, pid, slug, prov, model, outcome="receipt_only"):
    from review_channel_selftest_receipt import valid_profile, call_record
    pub = {"verdict_path": "tasks/gov-t1/reviews/impl-r1/V.md", "verdict_sha256": "0" * 64} if published else None
    prof = valid_profile([call_record(1, cpp=three[0], pb=three[1])], pub, provider_id=pid, provider=dict(prov), model_slug=slug, model=model)
    return {**RC.empty_receipt(), "receipt_schema": C.RECEIPT_SCHEMA, "attempt_id": "A", "subject": "s", "stage": "impl", "round": "r1", "mode": mode,
            "receipt_phase": phase, "classification": classification, "attempt_outcome": outcome,
            "call_path_proof": three[0], "profile_binding": three[1], "verdict_validation": three[2],
            "verdict_published": published, "verdict_path": pub["verdict_path"] if pub else None,
            "verdict_sha256": pub["verdict_sha256"] if pub else None, "effective_profile": prof,
            "input_manifest_sha256": "m"}


def receipt_ref_verification(e):
    repo = e.iso_repo()
    reg = e.fixture_json("registry_sample.json")
    pid, slug = "fake-official", "fake-model"
    prov = reg["providers"][pid]
    model = prov["models"][slug]
    rec = _receipt("probe", "completed", "probe_completed", ("PROVEN", "SUFFICIENT", "NOT_REACHED"), False, pid, slug, prov, model)
    ref = "records/diagnostics/review-channel/2026-09-02/receipt-A.json"
    data = base.pretty_json(rec)
    repo.write(ref, data.decode("utf-8"))
    repo.git("add","-f","--",ref)  # Explicit legacy original fixture.
    commit = repo.commit("diagnostics receipt")
    sha = base.sha256_bytes(data)

    def probed(r, **kw):
        cap = r["providers"][pid]["models"][slug]["capability"]
        cap.update({"status": "PROBED", "bound_transport": "responses", "bound_effort": "high", "receipt_ref": ref,
                    "receipt_commit": commit, "receipt_sha256": sha})
        cap.update(kw)
    ld, _d = _loader(e)
    p = e.fake_registry(probed)
    e.check(G.load_registry(p, adapter_loader=ld, repo_root=repo.root, profile_checker=RC.profile_shape_problems)["revision"] == 1, "tracked diagnostics receipt anchors PROBED")
    e.expect_error(lambda: G.load_registry(e.fake_registry(lambda r: probed(r, receipt_sha256="0" * 64)), adapter_loader=ld, repo_root=repo.root, profile_checker=RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="sha mismatch")
    e.expect_error(lambda: G.load_registry(e.fake_registry(lambda r: probed(r, receipt_commit="1" * 40)), adapter_loader=ld, repo_root=repo.root, profile_checker=RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="commit not an ancestor")
    e.expect_error(lambda: G.load_registry(e.fake_registry(lambda r: probed(r, bound_effort="low")), adapter_loader=ld, repo_root=repo.root, profile_checker=RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="bound_effort differs from receipt effective_effort")
    # 工作树篡改 + Registry 同步改哈希：blob 三方相等不成立
    tampered = data.replace(b'"probe_completed"', b'"probe_completed" ')
    repo.write(ref, tampered.decode("utf-8"))
    e.expect_error(lambda: G.load_registry(e.fake_registry(lambda r: probed(r, receipt_sha256=base.sha256_bytes(tampered))), adapter_loader=ld, repo_root=repo.root, profile_checker=RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="working tree rewrite with matching registry hash still rejected by blob")
    repo.write(ref, data.decode("utf-8"))
    os.unlink(repo.path(ref))
    e.check(G.load_registry(p,adapter_loader=ld,repo_root=repo.root,profile_checker=RC.profile_shape_problems)['revision']==1,
            'CL-55 fixed Receipt remains valid after working copy is retired')
    repo.write(ref,data.decode('utf-8'))
    # 未跟踪的 attempt 目录 Receipt
    untracked = "tasks/gov-t1/attempts/impl-r1/A/receipt.json"
    repo.write(untracked, data.decode("utf-8"))
    e.expect_error(lambda: G.load_registry(e.fake_registry(lambda r: probed(r, receipt_ref=untracked)), adapter_loader=ld, repo_root=repo.root, profile_checker=RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="attempt-dir receipt is not a durable location")
    # routed 阶段 Receipt、mode 缺失、REVIEW_ENABLED 路径
    routed = dict(rec, receipt_phase="routed", classification="preflight_failed", call_path_proof="NOT_PROVEN")
    e.expect_error(lambda: G.check_receipt_evidence(routed, "PROBED", "diagnostics", pid, prov, slug, model, {"bound_transport": "responses", "bound_effort": "high"}, RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="routed receipt is audit only")
    nomode = {k: v for k, v in rec.items() if k != "mode"}
    e.expect_error(lambda: G.check_receipt_evidence(nomode, "PROBED", "diagnostics", pid, prov, slug, model, {"bound_transport": "responses", "bound_effort": "high"}, RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="mode missing")
    inv = _receipt("review", "called", "reviewer_output_invalid", ("PROVEN", "SUFFICIENT", "INVALID"), False, pid, slug, prov, model)
    G.check_receipt_evidence(inv, "PROBED", "diagnostics", pid, prov, slug, model, {"bound_transport": "responses", "bound_effort": "high"}, RC.profile_shape_problems)
    ok = _receipt("review", "completed", "completed_with_valid_verdict", ("PROVEN", "SUFFICIENT", "VALID"), True, pid, slug, prov, model, outcome="governed_verdict")
    G.check_receipt_evidence(ok, "REVIEW_ENABLED", "tracked", pid, prov, slug, model, {"bound_transport": "responses", "bound_effort": "high"}, RC.profile_shape_problems)
    # R3-B7：阶段 / 结局 / 发布标志交叉条件与 Profile 全字段校验在 capability 读端生效
    cap = {"bound_transport": "responses", "bound_effort": "high"}
    for mutate, why in ((lambda r: r.update(verdict_published=True), "probe evidence with verdict_published true"),
                        (lambda r: r.update(attempt_outcome="governed_verdict"), "probe evidence with governed_verdict outcome"),
                        (lambda r: r.update(receipt_phase="called"), "probe_completed must be a completed-phase receipt"),
                        (lambda r: r.update(verdict_path="x"), "probe evidence with a verdict path"),
                        (lambda r: r["effective_profile"]["calls"][0].update(extra=1), "malformed call item in the profile"),
                        (lambda r: r["effective_profile"].update(calls=None, effective_effort=None, effort_source=None, response_model=None, logical_model_match=None),
                         "call group absent")):
        bad = json.loads(base.pretty_json(rec))
        mutate(bad)
        e.expect_error(lambda b=bad: G.check_receipt_evidence(b, "PROBED", "diagnostics", pid, prov, slug, model, cap, RC.profile_shape_problems), code="receipt-ref-invalid", message=why)
    for mutate, why in ((lambda r: r.update(attempt_outcome="receipt_only"), "REVIEW_ENABLED needs governed_verdict"),
                        (lambda r: r["effective_profile"].update(verdict_sha256="1" * 64), "profile published group must equal the receipt fields")):
        bad = json.loads(base.pretty_json(ok))
        mutate(bad)
        e.expect_error(lambda b=bad: G.check_receipt_evidence(b, "REVIEW_ENABLED", "tracked", pid, prov, slug, model, cap, RC.profile_shape_problems), code="receipt-ref-invalid", message=why)
    e.expect_error(lambda: G.check_receipt_evidence(ok, "REVIEW_ENABLED", "diagnostics", pid, prov, slug, model, {"bound_transport": "responses", "bound_effort": "high"}, RC.profile_shape_problems),
                   code="receipt-ref-invalid", message="REVIEW_ENABLED requires the tracked round dir")
    # R6-B7：契约模块不横向导入；校验器由入口注入，缺席即 fail closed
    e.expect_error(lambda: G.check_receipt_evidence(ok, "REVIEW_ENABLED", "tracked", pid, prov, slug, model, {"bound_transport": "responses", "bound_effort": "high"}),
                   code="receipt-ref-invalid", message="missing profile checker fails closed")
    reg_src = open(os.path.join(e.unit_dir, "review_channel_registry.py"), encoding="utf-8").read()
    e.check("import review_channel_receipt" not in reg_src and "profile_checker" in reg_src, "static: registry does not import the receipt contract module")
    e.check(G._durable_location(".", "tasks/gov-t1/reviews/impl-r1/receipt-r1.json") == "tracked"
            and G._durable_location(".", "reviews/demo/r2/receipt-r2.json") == "tracked"
            and G._durable_location(".", "records/diagnostics/review-channel/2026-01-01/receipt-x.json") == "diagnostics"
            and G._durable_location(".", "reviews/demo/r2/other.json") is None, "durable location grammar")


def _legacy_v2_receipt(pid, prov, slug, model, verdict_path):
    """合成的 legacy-git v2 维护 Receipt：成员集合取 Amendment 4 之前的已提交形态（缺 decisions_sha256、多
    standard_questions_effective），Profile 为 v3；全部取值为合成值，满足 REVIEW_ENABLED 证据路径。"""
    from review_channel_selftest_receipt import valid_profile, call_record
    published = {"verdict_path": verdict_path, "verdict_sha256": "0" * 64}
    profile = {k: v for k, v in valid_profile([call_record(1, effort=model["default_effort"])], published, provider_id=pid,
                                              provider=dict(prov), model_slug=slug, model=model).items() if k != "execution_applicability"}
    profile["profile_schema"] = "review-channel-effective-profile/v3"
    facts = {"receipt_schema": "review-channel-receipt/v2", "attempt_id": "A", "subject": "demo", "stage": "impl", "round": "r1",
             "classification": "completed_with_valid_verdict", "failure_code": None, "mode": "review", "receipt_phase": "completed",
             "attempt_outcome": "governed_verdict", "call_path_proof": "PROVEN", "profile_binding": "SUFFICIENT",
             "verdict_validation": "VALID", "verdict_published": True, **published, "effective_profile": profile,
             "input_manifest_sha256": "m"}
    receipt = {**{k: None for k in C.LEGACY_RECEIPT_KEYS if k != "decisions_sha256"}, "standard_questions_effective": [], **facts}
    return receipt


def legacy_receipt_read_semantics(e):
    """KB-249 回归（feature-t17:KB-05）：已提交的活体 Registry 以本仓历史核验装载；带 legacy-git 维护能力的同一 Registry 形态
    以隔离仓历史中的合成 v2 Receipt 核验装载，v2 按原读取语义（C.RECEIPT_REF_FIELDS 存在、无新版成员）而非
    LEGACY_RECEIPT_KEYS 闭集；v3 / v4 闭集与 execution 拒绝保持。"""
    import review_channel_execution as X
    import review_evidence as E
    live = os.path.join(e.repo_root, "mechanisms", "review-channel", "review_channel_registry.json")
    ld = lambda rid: RT.load_adapter(rid, os.path.join(e.unit_dir, "adapters"))  # noqa: E731
    reg = G.load_registry(live, adapter_loader=ld, repo_root=e.repo_root, verify_evidence=True, profile_checker=RC.profile_shape_problems)
    e.check(reg["sha256"] == base.sha256_bytes(open(live, "rb").read()) and reg["registry"]["registry_schema"] == C.REGISTRY_SCHEMA,
            "committed live Registry loads with evidence verification against the real repository history")
    # 本仓历史不含 legacy-git 能力证据：在隔离仓提交合成 v2 Receipt，把活体 Registry 的 builtin-native 模型锚定到该提交
    repo = e.iso_repo()
    root = repo.root
    obj = json.loads(base.pretty_json(reg["registry"]))
    pid, prov = next((i, p) for i, p in sorted(obj["providers"].items()) if p["kind"] == "builtin-native" and p["models"])
    slug, model = sorted(prov["models"].items())[0]
    ref = "reviews/demo/r1/receipt-r1.json"
    data = base.pretty_json(_legacy_v2_receipt(pid, prov, slug, model, "reviews/demo/r1/HarnessPlane_Demo_Review_R1.md"))
    repo.write(ref, data.decode("utf-8"))
    model["capability"] = {"status": "REVIEW_ENABLED", "bound_transport": prov["transport"], "bound_effort": model["default_effort"],
                           "receipt_ref": ref, "receipt_commit": repo.commit("synthetic legacy v2 receipt"),
                           "receipt_sha256": base.sha256_bytes(data), "note": "selftest: synthetic legacy-git anchor"}
    anchored_path = os.path.join(e.tmpdir("registry"), "review_channel_registry.json")
    with open(anchored_path, "wb") as f:
        f.write(base.pretty_json(obj))
    reg = G.load_registry(anchored_path, adapter_loader=ld, repo_root=root, verify_evidence=True, profile_checker=RC.profile_shape_problems)
    e.check(reg["revision"] == obj["registry_revision"], "live Registry shape with a legacy-git maintenance capability loads with evidence verification against the isolated repository history")
    anchored = [(pid, prov, slug, model) for pid, prov in reg["registry"]["providers"].items() for slug, model in prov["models"].items()
                if model["capability"].get("receipt_ref")]
    e.check(anchored, "precondition: the anchored Registry carries at least one legacy-git maintenance capability anchored by receipt_ref")
    pid, prov, slug, model = anchored[0]
    cap = model["capability"]
    loc = G._durable_location(root, cap["receipt_ref"])
    receipt = base.strict_json_load(E.fixed_file(root, cap["receipt_commit"], cap["receipt_ref"])["content"])
    e.check(receipt["receipt_schema"] == "review-channel-receipt/v2" and X.receipt_common_problems(receipt) == [] and RC.receipt_shape_problems(receipt) == [],
            "committed legacy v2 Receipt is read by its original semantics: %s / %s" % (X.receipt_common_problems(receipt), RC.receipt_shape_problems(receipt)))
    e.check(set(receipt) != set(C.LEGACY_RECEIPT_KEYS), "precondition: the committed v2 member set differs from LEGACY_RECEIPT_KEYS (the closed set that rejected it)")
    G.check_receipt_evidence(receipt, cap["status"], loc, pid, prov, slug, model, cap, RC.profile_shape_problems)
    check = lambda r: G.check_receipt_evidence(r, cap["status"], loc, pid, prov, slug, model, cap, RC.profile_shape_problems)  # noqa: E731
    # v2 缺任一冻结引用字段仍拒绝
    for field in C.RECEIPT_REF_FIELDS:
        bad = {k: v for k, v in receipt.items() if k != field}
        expected = ["Receipt schema"] if field == "receipt_schema" else ["Receipt fields"]
        e.check(X.receipt_common_problems(bad) == expected and RC.receipt_shape_problems(bad) == expected, "v2 without %s is refused" % field)
        e.expect_error(lambda b=bad: check(b), code="receipt-ref-invalid", message="v2 without %s is not maintenance evidence" % field)
    # v2 带新版成员（execution / evidence_storage）不能作维护证据，无论取值
    for member, value in (("execution", None), ("execution", {"port_id": "embedded"}), ("evidence_storage", None),
                          ("evidence_storage", {"kind": "archive", "repository_id": "x", "round_key": "reviews/x/r1"})):
        bad = dict(receipt, **{member: value})
        e.check(X.receipt_common_problems(bad) == ["Receipt fields"] and RC.receipt_shape_problems(bad) == ["Receipt fields"], "v2 carrying %s=%r is refused" % (member, value))
        e.expect_error(lambda b=bad: check(b), code="receipt-ref-invalid", message="v2 carrying %s is not maintenance evidence" % member)
    # v2 的 legacy 枚举与 Profile 版本检查保持
    e.check(X.receipt_common_problems(dict(receipt, classification="cancelled_by_host")) == ["legacy Receipt enum"]
            and X.receipt_common_problems(dict(receipt, failure_code="execution-port-unregistered")) == ["legacy Receipt enum"]
            and X.receipt_common_problems(dict(receipt, effective_profile=dict(receipt["effective_profile"], profile_schema=C.PROFILE_SCHEMA))) == ["legacy Profile version"],
            "v2 keeps the legacy enum and Profile version checks")
    # v3 闭集不变：同一成员集合换标 v3 仍拒绝；恰等于 LEGACY_RECEIPT_KEYS + evidence_storage 才通过成员检查
    relabeled = dict(receipt, receipt_schema="review-channel-receipt/v3", evidence_storage={"kind": "archive", "repository_id": "x", "round_key": "reviews/x/r1"})
    e.check(X.receipt_key_problems(relabeled) == ["Receipt fields"], "v3 keeps its closed member set")
    v3 = {k: None for k in C.LEGACY_RECEIPT_KEYS + ("evidence_storage",)}
    v3["receipt_schema"] = "review-channel-receipt/v3"
    e.check(X.receipt_key_problems(v3) == [] and X.receipt_key_problems({k: v for k, v in v3.items() if k != "decisions_sha256"}) == ["Receipt fields"]
            and X.receipt_key_problems(dict(v3, standard_questions_effective=[])) == ["Receipt fields"], "v3 closed set: exact members only")
    # v4 闭集不变：缺一、多一、或把 v2 形状换标 v4 均拒绝
    v4 = {k: None for k in C.RECEIPT_KEYS}
    v4["receipt_schema"] = C.RECEIPT_SCHEMA
    e.check(X.receipt_key_problems(v4) == [] and X.receipt_key_problems({k: v for k, v in v4.items() if k != "execution"}) == ["Receipt fields"]
            and X.receipt_key_problems(dict(v4, standard_questions_effective=[])) == ["Receipt fields"]
            and X.receipt_key_problems(dict(receipt, receipt_schema=C.RECEIPT_SCHEMA)) == ["Receipt fields"], "v4 closed set unchanged")
    e.expect_error(lambda: check(dict(receipt, receipt_schema=C.RECEIPT_SCHEMA)), code="receipt-ref-invalid", message="v2 members relabeled as v4 are not maintenance evidence")


def cases():
    return [
        ("registry.schema-constraints", schema_and_constraints),
        ("registry.adapter-discovery", adapter_discovery),
        ("registry.receipt-ref", receipt_ref_verification),
        ("registry.legacy-receipt-read-semantics", legacy_receipt_read_semantics),
    ]
