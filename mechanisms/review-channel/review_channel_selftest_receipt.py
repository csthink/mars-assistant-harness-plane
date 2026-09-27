"""自测声明：review_channel_receipt（第 9 类聚合与归约、第 13 类运行时版本、第 19 类补产字段闭集、Profile 三组；KB-249 Receipt 版本分派读取回归）。"""
import review_channel_contract as C
import review_channel_receipt as RC


def call_record(i, cpp="PROVEN", pb="SUFFICIENT", effort="high", version="v1", model=None, lmm="unreported", **over):
    """一份满足 CALL_RECORD_KEYS 全字段校验的 calls[] 项（供各声明构造合法 Profile）。"""
    rec = {"call_index": i, "response_model": model, "logical_model_match": lmm,
           "upstream_route_visibility": "reported" if model is not None else "unreported",
           "route_provenance": "direct", "effective_effort": effort, "effort_source": "registry-default",
           "provider_effective_behavior": "unverified", "runtime_version": version,
           "process": {"exit_code": 0, "timed_out": False, "stderr_summary": ""}, "usage": "unknown",
           "jsonl_event_count": 1, "request_count": "unknown", "request_ids": "unknown",
           "retry": {"transport_retry_state": "unknown", "provider_retry_state": "unknown"}, "http_status": None,
           "failure": None, "call_path_proof": cpp, "profile_binding": pb}
    rec.update(over)
    return rec


_call = call_record


SAMPLE_PROVIDER = {"kind": "official-direct", "runtime": "fake", "transport": "responses", "key_env": "FAKE_API_KEY",
                   "base_env": "FAKE_API_BASE", "display_name": "Fake"}
SAMPLE_MODEL = {"claimed_vendor": "DeepSeek", "default_effort": "high", "supported_efforts": ["low", "high"],
                "capability": {"status": "CONFIGURED"}}


def selected_sample(**over):
    """一份合法的选定组（供各声明构造可通过全字段校验的 Profile）。"""
    sel = {"caller": "selftest", "artifact_author": {"human_only": False, "authors": [{"tool": "claude-code", "model": "m", "vendor": "Anthropic"}]},
           "model_vendors": ["Anthropic"], "provider_id": "fake-official", "provider": SAMPLE_PROVIDER, "model_slug": "fake-model",
           "model": SAMPLE_MODEL, "effort": "high", "effort_source": "registry-default", "overrides": {}, "overrides_source": "none",
           "selection_source": "system-default", "registry_revision": 1, "registry_sha256": "1" * 64, "contract_version": "v",
           "contract_design_sha256": "d" * 64, "request_sha256": "2" * 64, "input_manifest_sha256": "3" * 64, "round": "r1",
           "attempt_id": "A", "question_ids": ["Q-CHANGE"], "bundle_names": ["T.md", "c.md"], "task_file": "T.md", "delivery": "tool"}
    sel.update(over)
    return RC.selected_group(sel)


def _selected():
    return selected_sample()


def valid_profile(calls=None, published=None, **over):
    return RC.build_profile(selected_sample(**over), calls, published)


def profile_groups(e):
    prof = RC.build_profile(_selected(), None, None)
    e.check(RC.profile_shape_problems(prof) == [] and prof["calls"] is None and prof["verdict_path"] is None,
            "sealed: selected only: %s" % RC.profile_shape_problems(prof))
    prof = RC.build_profile(_selected(), [_call(1)], None)
    e.check(RC.profile_shape_problems(prof) == [] and prof["calls"][0]["call_index"] == 1 and prof["effective_effort"] == "high"
            and prof["verdict_sha256"] is None, "called group")
    prof = RC.build_profile(_selected(), [_call(1)], {"verdict_path": "p", "verdict_sha256": "0" * 64})
    e.check(RC.profile_shape_problems(prof) == [] and prof["verdict_path"] == "p" and set(prof) == set(RC.PROFILE_KEYS), "published group; key set closed")
    e.check(RC.profile_shape_problems({"profile_schema": "x"}) and RC.profile_shape_problems(dict(prof, extra=1)), "shape negatives")
    e.check(RC.profile_shape_problems(dict(prof, verdict_path=5)) and RC.profile_shape_problems(dict(prof, verdict_path=""))
            and RC.profile_shape_problems(dict(prof, verdict_path={"p": 1})), "published verdict_path must be a non-empty string (R15-B1)")
    e.check(RC.profile_shape_problems(dict(prof, transport="smoke")) and RC.profile_shape_problems(dict(prof, claimed_vendor="deepseek"))
            and RC.profile_shape_problems(dict(prof, auth_mode="login-session")) and RC.profile_shape_problems(dict(prof, verdict_sha256=None))
            and RC.profile_shape_problems(dict(prof, calls=[])) and RC.profile_shape_problems(dict(prof, registry_revision=True)),
            "value-domain and cross-constraint negatives (R1-B7)")
    e.check(RC.profile_shape_problems(dict(prof, effective_effort=None)), "reduction-null effort without a conflict is illegal (R4-B4)")
    # R3-B7：calls[] 单项全字段、嵌套对象闭集与交叉约束
    e.check(set(RC.call_record_problems(_call(1))) == set() and RC.call_record_problems({}) and RC.call_record_problems(dict(_call(1), extra=1))
            and RC.call_record_problems({k: v for k, v in _call(1).items() if k != "retry"}), "call record key set closed")
    for bad in (dict(call_index=True), dict(response_model=""), dict(logical_model_match="maybe"), dict(upstream_route_visibility="seen"),
                dict(route_provenance="x"), dict(effective_effort="ultra"), dict(effort_source="guess"), dict(provider_effective_behavior="verified"),
                dict(runtime_version=""), dict(process={"exit_code": 0}), dict(process={"exit_code": "0", "timed_out": False, "stderr_summary": ""}),
                dict(usage=[]), dict(jsonl_event_count=-1), dict(request_count="many"), dict(request_ids=[]), dict(request_ids=[1]),
                dict(retry={}), dict(http_status="200"), dict(failure="secret-leak"), dict(call_path_proof="MAYBE"), dict(profile_binding="OK"),
                dict(failure="provider_unavailable", call_path_proof="PROVEN")):
        e.check(RC.call_record_problems(_call(1, **bad)), "call record negative: %s" % bad)
    e.check(RC.profile_shape_problems(dict(prof, calls=[dict(_call(1), extra=1)])), "profile rejects a malformed call item")
    e.check(RC.profile_shape_problems(dict(prof, runtime_overrides={"k": None})) and RC.profile_shape_problems(dict(prof, runtime_overrides={"": 1}))
            and RC.profile_shape_problems(dict(prof, runtime_overrides={"k": [1]})), "runtime_overrides nested value domain")
    e.check(RC.profile_shape_problems(dict(prof, resolved_upstream={"provider": "fake-official", "model": "fake-model", "route_visibility": "seen"}))
            and RC.profile_shape_problems(dict(prof, resolved_upstream={"provider": "other", "model": "fake-model", "route_visibility": "direct"}))
            and RC.profile_shape_problems(dict(prof, resolved_upstream={"provider": None, "model": None, "route_visibility": "pending-response"})),
            "resolved_upstream closed set and cross-constraints with the route provider")
    e.check(RC.profile_shape_problems(dict(prof, reviewer_tool_surface={"web_search": "forced-off", "delivery": "tool", "x": 1})),
            "reviewer_tool_surface key set closed")
    # R4-B4：派生关系——作者 provenance 与调用组归约字段
    aa = prof["artifact_author"]
    e.check(RC.profile_shape_problems(dict(prof, artifact_author=dict(aa, model_vendors=["OpenAI"])))
            and RC.profile_shape_problems(dict(prof, artifact_author=dict(aa, human_only=True)))
            and RC.profile_shape_problems(dict(prof, artifact_author={"human_only": True, "authors": [{"tool": "human", "model": "x", "vendor": "human"}], "model_vendors": []}))
            and RC.profile_shape_problems({**prof, "artifact_author": {"human_only": True, "authors": [{"tool": "human", "model": "human", "vendor": "human"}], "model_vendors": []}}) == [],
            "artifact_author derivation (R4-B4)")
    e.check(RC.profile_shape_problems(dict(prof, effective_effort="low")) and RC.profile_shape_problems(dict(prof, logical_model_match="exact")),
            "call group reduced fields must equal the recomputation (R4-B4)")
    # R5-B3：记录内部交叉约束与 kind 派生
    for bad in (dict(process={"exit_code": 1, "timed_out": False, "stderr_summary": ""}), dict(process={"exit_code": None, "timed_out": True, "stderr_summary": ""}),
                dict(http_status=500), dict(lmm="exact"), dict(model="m", lmm="unreported"), dict(model="m", lmm="mismatch"),
                dict(model="m", lmm="exact", pb="MISMATCH"), dict(model="m", lmm="exact", upstream_route_visibility="unreported")):
        e.check(RC.call_record_problems(_call(1, **bad)), "intra-record cross constraint: %s" % bad)
    agg_prov = dict(SAMPLE_PROVIDER, kind="aggregator")
    agg_bad = valid_profile([_call(1)], provider=agg_prov)   # 默认记录：unreported + SUFFICIENT + direct
    e.check(RC.profile_shape_problems(agg_bad), "aggregator with unreported identity cannot be SUFFICIENT / direct (R5-B3)")
    agg_ok = valid_profile([_call(1, pb="INSUFFICIENT", route_provenance="unverifiable")], provider=agg_prov)
    e.check(RC.profile_shape_problems(agg_ok) == [], "aggregator unreported record in its derived form: %s" % RC.profile_shape_problems(agg_ok))
    e.check(RC.profile_shape_problems(valid_profile([_call(1, model="up/x", lmm="registered_equivalent", route_provenance="direct")], provider=agg_prov)),
            "aggregator route_provenance must follow the match")
    # R6-B2：response_model 与 logical_model_match 互证（requested_model = fake-model）
    e.check(RC.profile_shape_problems(valid_profile([_call(1, model="other", lmm="exact")]))
            and RC.profile_shape_problems(valid_profile([_call(1, model="fake-model", lmm="mismatch", pb="MISMATCH")]))
            and RC.profile_shape_problems(valid_profile([_call(1, model="fake-model", lmm="exact")])) == []
            and RC.profile_shape_problems(valid_profile([_call(1, model="other", lmm="mismatch", pb="MISMATCH")])) == [],
            "response_model must agree with the match conclusion (R6-B2)")
    conflict = RC.build_profile(_selected(), [_call(1), _call(2, effort="low")], None)
    e.check(RC.profile_shape_problems(conflict) == [] and RC.profile_shape_problems(dict(conflict, effective_effort="high")),
            "conflict → whole group null is the only legal form")


def call_record_key_set(e):
    import review_channel_runtime as RT
    import review_channel_contract as C2
    r = RT.empty_result()
    rec = RT.build_call_record(1, "review", r, "official-direct", "m", None, "high", "registry-default")
    e.check(tuple(rec) == C2.CALL_RECORD_KEYS and RC.call_record_problems(rec) == [], "runtime call record satisfies the contract closed key set: %s" % RC.call_record_problems(rec))
    r["final_message"] = b"x"
    r["process"] = {"exit_code": 0, "timed_out": False, "stderr_summary": ""}
    e.check(RC.call_record_problems(RT.build_call_record(2, "review", r, "aggregator", "m", ["m2"], "low", "explicit-request")) == [], "aggregator record valid")
    # R5-B2：registered_equivalents 字符串只认全等、数组只认成员全等
    e.check(RT.assess_profile_binding("aggregator", "upstream/agg-v1", "agg", {"agg": "upstream/agg-v1"}) == ("SUFFICIENT", "registered_equivalent")
            and RT.assess_profile_binding("aggregator", "agg-v1", "agg", {"agg": "upstream/agg-v1"}) == ("MISMATCH", "mismatch")
            and RT.assess_profile_binding("aggregator", "b", "agg", {"agg": ["a", "b"]}) == ("SUFFICIENT", "registered_equivalent")
            and RT.assess_profile_binding("aggregator", "a", "agg", {"agg": ["ab"]}) == ("MISMATCH", "mismatch")
            and RT.assess_profile_binding("aggregator", "x", "agg", {"agg": 5}) == ("MISMATCH", "mismatch"), "registered equivalents: whole-string equality only (R5-B2)")


def aggregation_and_reduction(e):
    e.check(RC.aggregate_dims([_call(1), _call(2, pb="MISMATCH")]) == ("PROVEN", "MISMATCH"), "SUFFICIENT + MISMATCH → MISMATCH")
    e.check(RC.aggregate_dims([_call(1, pb="INSUFFICIENT"), _call(2)]) == ("PROVEN", "INSUFFICIENT"), "INSUFFICIENT + SUFFICIENT → INSUFFICIENT")
    e.check(C.capability_transition(*RC.aggregate_dims([_call(1, pb="INSUFFICIENT"), _call(2)]), "VALID")[1] != "REVIEW_ENABLED", "no REVIEW_ENABLED suggestion")
    e.check(RC.aggregate_dims([_call(1), _call(2, cpp="NOT_PROVEN")]) == ("NOT_PROVEN", "SUFFICIENT"), "PROVEN + NOT_PROVEN → NOT_PROVEN")
    cg = RC.call_group([_call(1), _call(2)])
    e.check(cg["effective_effort"] == "high" and cg["logical_model_match"] == "unreported" and len(cg["calls"]) == 2, "equal values reduce to the value")
    cg = RC.call_group([_call(1), _call(2, effort="low")])
    e.check(cg["effective_effort"] is None and cg["effort_source"] is None and cg["response_model"] is None and cg["logical_model_match"] is None,
            "any conflict → all three reduced fields null (R1-B3)")
    e.check(RC.aggregate_dims([_call(1), _call(2, effort="low")])[1] == "MISMATCH", "reduction conflict forces MISMATCH")
    src_conflict = [_call(1), dict(_call(2), effort_source="explicit-request")]
    cg = RC.call_group(src_conflict)
    e.check(cg["effective_effort"] is None and cg["effort_source"] is None and RC.aggregate_dims(src_conflict)[1] == "MISMATCH",
            "effort source conflict alone nulls the group and forces MISMATCH (R2-B3)")
    agg = [dict(_call(1, model="up/x", lmm="registered_equivalent"), upstream_route_visibility="reported", route_provenance="registered_equivalent")]
    e.check(RC.route_facts(agg) == ("reported", "registered_equivalent") and RC.route_facts([]) == (None, None)
            and RC.route_facts([dict(_call(1), upstream_route_visibility="unreported", route_provenance="unverifiable")]) == ("unreported", "unverifiable"),
            "receipt-level route facts (R1-B10)")
    e.check(RC.aggregate_dims([_call(1, version="v1"), _call(2, version="v2")]) == ("PROVEN", "SUFFICIENT"), "runtime_version does not reduce or degrade")
    e.check(RC.aggregate_dims([]) == ("NOT_PROVEN", "INSUFFICIENT"), "no calls")
    first = _call(1)
    calls = [first]
    RC.call_group(calls)
    calls.append(_call(2))
    e.check(calls[0] is first and calls[0]["call_index"] == 1, "first call record never overwritten")


def runtime_group(e):
    g = RC.runtime_group("codex", [_call(1, version="0.1"), _call(2, version="0.2")], None, False)
    e.check(g["tool_version"] == "0.1" and g["api_endpoint_id"] is None and g["changed_within_attempt"] is True and g["changed_across_rounds"] is None,
            "first call version, within-attempt change, no previous → null")
    g = RC.runtime_group("codex", [_call(1, version="0.1")], {"adapter": "http", "api_endpoint_id": "x"}, False)
    e.check(g["changed_across_rounds"] is True and g["changed_within_attempt"] is False, "adapter change → true")
    g = RC.runtime_group("codex", [_call(1, version="0.1")], {"adapter": "codex", "tool_version": "0.0"}, False)
    e.check(g["changed_across_rounds"] is True, "same adapter different version → true")
    g = RC.runtime_group("codex", [_call(1, version="0.1")], {"adapter": "codex", "tool_version": "0.1"}, False)
    e.check(g["changed_across_rounds"] is False, "same adapter same version → false")
    g = RC.runtime_group("http", [_call(1, version="chat:abc")], {"adapter": "http", "api_endpoint_id": "chat:abc"}, True)
    e.check(g["api_endpoint_id"] == "chat:abc" and g["tool_version"] is None and g["changed_across_rounds"] is False, "inline endpoint id")


def interrupted_synthesis(e):
    who = {"pid": 1, "pid_start": "t", "attempt_id": None, "role": "preflight"}
    base_att = {"attempt_id": "A", "mode": "review", "routing": {"subject": "s", "stage": "impl", "round": "r2", "task_record": "gov-t1"},
                "request_sha256": "q", "invocation_authorization_sha256": "i", "formal_review_authorized_by_owner": True,
                "effective_profile": valid_profile(), "input_manifest_sha256": "m", "round_budget": {"x": 1},
                "decisions_sha256": None, "delivery": "tool", "runtime_group": {"adapter": "fake"}}
    routed = dict(base_att, phase="routed")
    r = RC.synthesize_interrupted(routed, who)
    e.check(r["classification"] == "interrupted" and r["failure_code"] == "interrupted" and r["attempt_outcome"] == "preflight_failed"
            and (r["call_path_proof"], r["profile_binding"], r["verdict_validation"]) == ("NOT_PROVEN", "INSUFFICIENT", "NOT_REACHED")
            and r["effective_profile"] is None and r["input_manifest_sha256"] is None and r["runtime"] is None and r["extraction"] is None
            and r["synthesized_by"] == who and r["verdict_published"] is False, "routed closed set")
    sealed = dict(base_att, phase="sealed")
    r = RC.synthesize_interrupted(sealed, who)
    e.check(r["effective_profile"]["calls"] is None and r["effective_profile"]["verdict_path"] is None and r["input_manifest_sha256"] == "m"
            and r["round_budget"] == {"x": 1} and r["runtime"] is None and RC.profile_shape_problems(r["effective_profile"]) == [],
            "sealed: selected group only, copied from the record")
    r = RC.synthesize_interrupted(dict(sealed, decisions_sha256="9" * 64), who)
    e.check(r["decisions_sha256"] == "9" * 64 and "standard_questions_effective" not in RC.RECEIPT_KEYS and "decisions_sha256" in RC.RECEIPT_KEYS,
            "decisions_sha256 copied from the record; the standard-questions member is retired from the Receipt key set (Amendment 4)")
    calling1 = dict(base_att, phase="calling", call_index=1, calls=[])
    r = RC.synthesize_interrupted(calling1, who)
    e.check((r["call_path_proof"], r["profile_binding"], r["verdict_validation"]) == ("INDETERMINATE", "INSUFFICIENT", "NOT_REACHED")
            and r["effective_profile"]["calls"] is None and r["runtime"] is None, "first calling")
    calling2 = dict(base_att, phase="calling", call_index=2, calls=[_call(1)], effective_profile=valid_profile([_call(1)]))
    r = RC.synthesize_interrupted(calling2, who)
    e.check((r["call_path_proof"], r["profile_binding"]) == ("INDETERMINATE", "INSUFFICIENT") and len(r["effective_profile"]["calls"]) == 1
            and r["runtime"] == {"adapter": "fake"}, "re-emission calling: first call + conservative aggregation, runtime group present")
    called = dict(base_att, phase="called", call_path_proof="PROVEN", profile_binding="MISMATCH",
                  effective_profile=valid_profile([_call(1), _call(2, pb="MISMATCH")]))
    r = RC.synthesize_interrupted(called, who)
    e.check((r["call_path_proof"], r["profile_binding"], r["verdict_validation"]) == ("PROVEN", "MISMATCH", "NOT_REACHED")
            and len(r["effective_profile"]["calls"]) == 2 and r["extraction"] is None, "called: recorded dims × 2")
    # 自查整改（r18 前）：补产行闭集之外恒 null——路由来源两字段不由 calls[] 归约
    e.check(r["upstream_route_visibility"] is None and r["route_provenance"] is None and r["runtime"] == {"adapter": "fake"},
            "called synthesis: route facts stay null, runtime group copied")
    # R3-B4：called 补产只复制记录内的 attempt 级两维，不从 calls[] 重算
    r = RC.synthesize_interrupted(dict(called, call_path_proof="NOT_PROVEN", profile_binding="INSUFFICIENT"), who)
    e.check((r["call_path_proof"], r["profile_binding"]) == ("NOT_PROVEN", "INSUFFICIENT"), "called synthesis copies, never recomputes")
    e.expect_error(lambda: RC.synthesize_interrupted({k: v for k, v in called.items() if k != "call_path_proof"}, who), exc_type=KeyError,
                   message="called record without the recorded dims is malformed, not recomputed")
    validated = dict(base_att, phase="validated", calls=[_call(1)], call_path_proof="PROVEN", profile_binding="SUFFICIENT",
                     verdict_validation="INVALID", extraction={"tier": "strict"}, effective_profile=valid_profile([_call(1)], {"verdict_path": "x", "verdict_sha256": "0" * 64}))
    r = RC.synthesize_interrupted(validated, who)
    e.check(r["effective_profile"]["verdict_path"] is None and r["effective_profile"]["verdict_sha256"] is None, "published group forced null on synthesis")
    e.check(r["verdict_validation"] == "INVALID" and r["extraction"] == {"tier": "strict"} and r["verdict_path"] is None, "validated: actual values × 3")
    e.check(r["upstream_route_visibility"] is None and r["route_provenance"] is None, "validated synthesis: route facts stay null")
    e.check(set(r) == set(RC.RECEIPT_KEYS), "receipt key set closed")


def legacy_shape_semantics(e):
    """KB-249 回归（feature-t17:KB-05）：receipt_shape_problems 按物理版本分派——legacy-git v2 的已提交成员集合有多种形态
    （缺 decisions_sha256 / 多 standard_questions_effective / 缺路由事实），按原读取语义只核冻结引用字段与无新版成员；
    v3 / v4 闭集不变，v4 新字段不得塞回旧版本。"""
    import review_channel_execution as X
    legacy_profile = {k: v for k, v in valid_profile([_call(1)], {"verdict_path": "p", "verdict_sha256": "0" * 64}).items() if k != "execution_applicability"}
    legacy_profile["profile_schema"] = "review-channel-effective-profile/v3"
    facts = {"receipt_schema": "review-channel-receipt/v2", "classification": "completed_with_valid_verdict", "failure_code": None,
             "mode": "review", "receipt_phase": "completed", "attempt_outcome": "governed_verdict", "call_path_proof": "PROVEN",
             "profile_binding": "SUFFICIENT", "verdict_validation": "VALID", "verdict_published": True, "verdict_path": "p",
             "verdict_sha256": "0" * 64, "effective_profile": legacy_profile, "input_manifest_sha256": "m"}
    v2_closed = {**{k: None for k in C.LEGACY_RECEIPT_KEYS}, **facts}
    e.check(RC.receipt_shape_problems(v2_closed) == [], "v2 with the LEGACY_RECEIPT_KEYS members still reads: %s" % RC.receipt_shape_problems(v2_closed))
    # r31 形态：缺 decisions_sha256、多 standard_questions_effective（Amendment 4 之前的写入）
    r31_shape = {k: v for k, v in v2_closed.items() if k != "decisions_sha256"}
    r31_shape["standard_questions_effective"] = []
    e.check(RC.receipt_shape_problems(r31_shape) == [] and X.receipt_common_problems(r31_shape) == [],
            "v2 written before Amendment 4 reads by its original semantics: %s" % RC.receipt_shape_problems(r31_shape))
    oldest = {k: v for k, v in r31_shape.items() if k not in ("failure_call_index", "route_provenance", "upstream_route_visibility")}
    e.check(RC.receipt_shape_problems(oldest) == [], "the oldest committed v2 shape (no route facts) reads: %s" % RC.receipt_shape_problems(oldest))
    for field in C.RECEIPT_REF_FIELDS:
        bad = {k: v for k, v in r31_shape.items() if k != field}
        e.check(RC.receipt_shape_problems(bad) == (["Receipt schema"] if field == "receipt_schema" else ["Receipt fields"]), "v2 without %s is refused" % field)
    for member in ("execution", "evidence_storage"):
        e.check(RC.receipt_shape_problems(dict(r31_shape, **{member: None})) == ["Receipt fields"], "v4/v3 member %s cannot be pushed back into v2" % member)
    e.check(RC.receipt_shape_problems(dict(r31_shape, classification="cancelled_by_host")) == ["legacy Receipt enum"]
            and RC.receipt_shape_problems(dict(r31_shape, effective_profile=dict(legacy_profile, profile_schema=C.PROFILE_SCHEMA, execution_applicability=None))) == ["legacy Profile version"],
            "v2 keeps the legacy enum and Profile version checks")
    # v3：恰为 LEGACY_RECEIPT_KEYS + evidence_storage
    storage = {"kind": "archive", "repository_id": "repo", "round_key": "reviews/x/r1"}
    v3 = dict(v2_closed, receipt_schema="review-channel-receipt/v3", evidence_storage=storage)
    e.check(RC.receipt_shape_problems(v3) == [] and RC.receipt_shape_problems({k: v for k, v in v3.items() if k != "decisions_sha256"}) == ["Receipt fields"]
            and RC.receipt_shape_problems(dict(v3, standard_questions_effective=[])) == ["Receipt fields"]
            and RC.receipt_shape_problems(dict(r31_shape, receipt_schema="review-channel-receipt/v3", evidence_storage=storage)) == ["Receipt fields"],
            "v3 keeps its closed member set")
    # v4：恰为 RECEIPT_KEYS；v2 形状换标 v4 拒绝
    v4_profile = dict(legacy_profile, profile_schema=C.PROFILE_SCHEMA, execution_applicability=None)
    v4 = dict(v3, receipt_schema=C.RECEIPT_SCHEMA, execution=None, effective_profile=v4_profile)
    e.check(RC.receipt_shape_problems(v4) == [] and RC.receipt_shape_problems({k: v for k, v in v4.items() if k != "execution"}) == ["Receipt fields"]
            and RC.receipt_shape_problems(dict(v4, standard_questions_effective=[])) == ["Receipt fields"]
            and RC.receipt_shape_problems(dict(r31_shape, receipt_schema=C.RECEIPT_SCHEMA, effective_profile=v4_profile)) == ["Receipt fields"],
            "v4 keeps its closed member set: %s" % RC.receipt_shape_problems(v4))


def cases():
    return [
        ("receipt.profile-groups", profile_groups),
        ("receipt.call-record-keys", call_record_key_set),
        ("receipt.aggregation-reduction", aggregation_and_reduction),
        ("receipt.runtime-group", runtime_group),
        ("receipt.interrupted-synthesis", interrupted_synthesis),
        ("receipt.legacy-shape-semantics", legacy_shape_semantics),
    ]
