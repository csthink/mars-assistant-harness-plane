"""自测声明：adapters/http（第 14 类：三协议请求体、内联定界、结构化输出、应答模型标识、聚合商 logical_model_match；回环服务器实撞）。"""
import http.server
import json
import os
import threading

import review_channel_base as base
import review_channel_runtime as RT
import review_channel_secrets as S


def _adapter():
    return RT.load_adapter("http")


def builders_and_parsers(e):
    A = _adapter()
    path, body = A.build_chat("m", "high", "SYS", "USER", "json_object")
    e.check(path == "/chat/completions" and body["messages"][0] == {"role": "system", "content": "SYS"} and body["reasoning_effort"] == "high"
            and body["response_format"] == {"type": "json_object"} and body["stream"] is False, "chat body")
    path, body = A.build_chat("m", "low", "S", "U", "json_schema")
    e.check(body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["schema"]["required"] == ["machine", "narrative"], "chat json_schema")
    path, body = A.build_responses("m", "low", "S", "U", "json_schema")
    e.check(path == "/responses" and body["reasoning"] == {"effort": "low"} and body["instructions"] == "S" and body["text"]["format"]["type"] == "json_schema"
            and body["store"] is False, "responses body")
    path, body = A.build_messages("m", "high", "S", "U", "none")
    e.check(path == "/messages" and body["system"] == "S" and body["thinking"]["budget_tokens"] == 16384, "messages body with thinking budget")
    e.check("thinking" not in A.build_messages("m", "minimal", "S", "U", "none")[1], "minimal effort disables thinking")
    # r18 自查整改（R18-B4 线索）：messages 传输物化 json_schema 为 output_config.format；json_object 无线上形态 → preflight 拒绝
    path, body = A.build_messages("m", "high", "S", "U", "json_schema")
    e.check(body["output_config"]["format"]["type"] == "json_schema" and body["output_config"]["format"]["schema"]["required"] == ["machine", "narrative"],
            "messages json_schema materialized as output_config.format")
    e.check("output_config" not in A.build_messages("m", "high", "S", "U", "none")[1], "messages none: no output_config")
    e.expect_error(lambda: A.preflight({"provider": {"transport": "messages", "structured_output": "json_object"}, "overrides": {}}),
                   exc_type=base.PreflightError, message="messages + json_object rejected at preflight, not accepted-and-ignored")
    e.check(A.preflight({"provider": {"transport": "messages", "structured_output": "json_schema"}, "overrides": {}})["structured_output"] == "json_schema",
            "messages + json_schema accepted")
    e.check(A.preflight({"provider": {"transport": "chat", "structured_output": "json_object"}, "overrides": {}})["structured_output"] == "json_object",
            "chat + json_object still accepted")
    e.check(A.headers_for("chat", "K")["Authorization"] == "Bearer K" and A.headers_for("messages", "K")["x-api-key"] == "K"
            and "anthropic-version" in A.headers_for("messages", "K"), "headers per transport")
    e.check(A.parse_chat({"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}], "model": "x"})[:2] == ("ab", "x"), "chat parts")
    e.check(A.parse_responses({"output_text": "t", "model": "y"})[:2] == ("t", "y"), "responses output_text fallback")
    e.check(A.parse_messages({"content": [{"type": "text", "text": "z"}], "model": "c", "usage": {"u": 1}})[:3] == ("z", "c", {"u": 1}), "messages parse")
    e.check(A.endpoint_id("chat", "https://a/v1") != A.endpoint_id("chat", "https://b/v1") and "https://a" not in A.endpoint_id("chat", "https://a/v1"), "endpoint id is a hash")
    seal = e.tmpdir("seal")
    for name, text in (("T.md", "task"), ("c.md", "cand"), ("r.md", "ref")):
        open(os.path.join(seal, name), "w").write(text)
    inputs = [{"bundle_name": "r.md", "role": "reference", "bytes": 3, "sha256": "c" * 64},
              {"bundle_name": "c.md", "role": "candidate", "bytes": 4, "sha256": "a" * 64},
              {"bundle_name": "T.md", "role": "review-task", "bytes": 4, "sha256": "b" * 64}]
    msg = A.inline_user_message(seal, inputs, "T.md")
    e.check(msg.index("BEGIN INPUT T.md") < msg.index("BEGIN INPUT c.md") < msg.index("BEGIN INPUT r.md"), "task book first, candidate, then references")
    e.check("sha256=%s" % ("a" * 64) in msg and "bytes=4" in msg and "===== END INPUT c.md =====" in msg, "delimited segments carry identity")
    e.check(RT.assess_profile_binding("aggregator", "upstream/agg-v1", "agg", {"agg": "upstream/agg-v1"}) == ("SUFFICIENT", "registered_equivalent")
            and RT.assess_profile_binding("aggregator", "other", "agg", {"agg": "upstream/agg-v1"}) == ("MISMATCH", "mismatch")
            and RT.assess_profile_binding("aggregator", "agg", "agg", {}) == ("SUFFICIENT", "exact")
            and RT.assess_profile_binding("aggregator", "unreported", "agg", {}) == ("INSUFFICIENT", "unreported")
            and RT.assess_profile_binding("official-direct", "unreported", "m", {}) == ("SUFFICIENT", "unreported"), "logical_model_match rules")
    e.check(A.classify_http_failure(401, "") == "authentication_failed" and A.classify_http_failure(429, "") == "provider_unavailable"
            and A.classify_http_failure(400, "") == "runtime_rejected_config" and A.classify_http_failure(None, "timed out") == "timeout_or_transport_failure",
            "http failure classification")


class _Server:
    def __init__(self, responses):
        server = self
        self.seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                server.seen.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body.decode("utf-8"))})
                status, payload = responses[min(len(server.seen) - 1, len(responses) - 1)]
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("x-request-id", "rid-%d" % len(server.seen))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def loopback_run(e):
    A = _adapter()
    srv = _Server([(200, {"choices": [{"message": {"content": '{"machine": {}, "narrative": "n"}'}}], "model": "upstream/agg-v1", "usage": {"t": 1}, "id": "body-1"}),
                   (401, {"error": "bad key"}),
                   (500, {"error": "boom"}),
                   (302, {"error": "moved"})])
    try:
        h = S.SecretHandle()
        h.put("K", "sk-loop")
        h.put("B", "http://127.0.0.1:%d/v1" % srv.port)
        prov = {"kind": "aggregator", "key_env": "K", "base_env": "B", "transport": "chat", "structured_output": "json_object", "display_name": "agg"}
        seal = e.tmpdir("seal")
        open(os.path.join(seal, "T.md"), "w").write("task")
        open(os.path.join(seal, "c.md"), "w").write("cand")
        inputs = [{"bundle_name": "c.md", "role": "candidate", "bytes": 4, "sha256": "a" * 64},
                  {"bundle_name": "T.md", "role": "review-task", "bytes": 4, "sha256": "b" * 64}]
        ctx = {"mode": "review", "provider_id": "agg", "provider": prov, "model_slug": "agg", "model": {}, "effort": "high", "overrides": {},
               "secrets": h, "attempt_dir": e.tmpdir("att"), "seal_dir": seal, "instruction": "SYS", "instruction_user": None,
               "timeout_seconds": 30, "call_index": 1, "inputs": inputs, "task_file": "T.md"}
        # R5-B6：直接接口适配器不承认任何 override 键；R5-B5：请求经无代理 opener
        e.expect_error(lambda: A.preflight(dict(ctx, overrides={"x": 1})), code="runtime-key-unrecognized", message="overrides refused, never silently ignored")
        e.check(A.preflight(ctx)["proxy"] == "disabled", "preflight reports proxy disabled")
        e.check(not any(isinstance(h, A.urllib.request.ProxyHandler) for h in A.OPENER.handlers), "opener carries no proxy handler (empty ProxyHandler suppresses the environment default)")
        src = open(os.path.join(e.unit_dir, "adapters", "http.py"), encoding="utf-8").read()
        e.check("urlopen(" not in src and src.count("OPENER.open(") == 1 and "build_opener(urllib.request.ProxyHandler({}), _NoRedirect())" in src,
                "static: the only request path is the isolated opener built with an empty ProxyHandler")
        r = A.run(ctx)
        e.check(r["http_status"] == 200 and r["final_message"] == b'{"machine": {}, "narrative": "n"}' and r["identity_claim"] == "upstream/agg-v1"
                and r["runtime_evidence"]["request_ids"] == ["rid-1", "body-1"] and r["runtime_evidence"]["request_count"] == 1
                and r["api_endpoint_id"].startswith("chat:"), "successful call facts: %s" % r["runtime_evidence"])
        req = srv.seen[0]
        e.check(req["path"] == "/v1/chat/completions" and req["headers"]["Authorization"] == "Bearer sk-loop" and req["body"]["model"] == "agg"
                and req["body"]["response_format"] == {"type": "json_object"} and "BEGIN INPUT T.md" in req["body"]["messages"][1]["content"]
                and req["body"]["messages"][0]["content"] == "SYS", "request shape on the wire")
        e.check(RT.assess_profile_binding("aggregator", r["identity_claim"], "agg", {"agg": "upstream/agg-v1"}) == ("SUFFICIENT", "registered_equivalent"),
                "aggregator formal tier reachable via registered equivalent")
        e.check(b"sk-loop" not in r["raw"]["request_shape"], "request shape diagnostic carries no secret")
        r = A.run(dict(ctx, call_index=2, instruction_user="again"))
        e.check(r["failure"] == "authentication_failed" and r["http_status"] == 401 and RT.assess_call_path("review", r) == "NOT_PROVEN", "401 classified")
        r = A.run(dict(ctx, call_index=2, instruction_user="again"))
        e.check(r["failure"] == "provider_unavailable" and r["http_status"] == 500, "500 classified")
        seen_before = len(srv.seen)
        r = A.run(dict(ctx, call_index=4, instruction_user="x"))
        e.check(r["http_status"] == 302 and r["failure"] == "provider_unavailable" and len(srv.seen) == seen_before + 1
                and r["runtime_evidence"]["request_count"] == 1, "3xx is not followed: one request, classified as failure (R6-B6): %s" % r["http_status"])
        e.check(any(isinstance(h, A._NoRedirect) for h in A.OPENER.handlers), "opener installs the non-following redirect handler")
    finally:
        srv.close()
    h2 = S.SecretHandle()
    h2.put("K", "k")
    h2.put("B", "http://127.0.0.1:9/v1")
    r = A.run(dict(ctx, secrets=h2, call_index=1))
    e.check(r["failure"] in ("provider_unavailable", "timeout_or_transport_failure") and r["http_status"] is None, "connection refused classified")


def cases():
    return [
        ("adapter.http.builders-parsers", builders_and_parsers),
        ("adapter.http.loopback-run", loopback_run),
    ]
