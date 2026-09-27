"""自测声明：adapters/claude 占位（设计 §7.3：探针与 Owner 裁定前恒 fail closed，Registry 引用即装载失败）。"""
import review_channel_registry as G
import review_channel_runtime as RT


def placeholder_fails_closed(e):
    A = RT.load_adapter("claude")
    e.check(A.RUNTIME_ID == "claude" and A.SUPPORTED_KINDS == () and A.SUPPORTED_TRANSPORTS == (), "no supported kind or transport")
    e.expect_error(lambda: A.preflight({}), code="runtime-adapter-unmaterialized", message="preflight")
    e.expect_error(lambda: A.run({}), code="runtime-adapter-unmaterialized", message="run")
    p = e.fake_registry(lambda r: r["providers"]["fake-official"].update(runtime="claude", transport="builtin"))
    e.expect_error(lambda: G.load_registry(p, adapter_loader=RT.load_adapter, verify_evidence=False), code="registry-invalid",
                   message="registry entry naming the placeholder is refused")


def cases():
    return [("adapter.claude.placeholder", placeholder_fails_closed)]
