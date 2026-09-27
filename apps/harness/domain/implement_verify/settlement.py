"""The one mapping from persisted physical execution facts to a domain settlement kind.

Embedded and standalone ports persist the same PhysicalExecution projection in the port reservation
record, so one table serves both (design §J-06 停止未确认、执行事实结算与恢复判定). Stop unconfirmed is
recognised exactly as J-06 r2 §3.1 states it: state `stopping`, `exit` present and `reason` beginning
with `stop unconfirmed after`. No Contract method, field, state or stop reason is added.

Kinds: pending (keep querying the original request), completed, failed, stop-unconfirmed, stopped,
unknown. Only `completed` can become a consumable result, and only after the candidate check; the
others enter recovery. Completion, timeout or cancellation alone never releases a reservation.
"""
import hashlib

STOP_UNCONFIRMED_PREFIX = "stop unconfirmed after"
PENDING_STATES = ("queued", "reserved", "running")
# Port faults raised before anything was released: the attempt failed and no side effect happened.
PRE_RELEASE_FAULTS = ("execution-port-unregistered", "execution-port-purpose-mismatch", "execution-port-profile-mismatch",
                      "execution-port-binding-mismatch", "execution-port-capability-unverified",
                      "execution-port-identity-unverified", "eligibility", "request-invalid", "policy-denied",
                      "policy-not-determinable", "secret-leak")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def latest(port):
    observations = (port or {}).get("observations") or []
    return observations[-1]["physical_execution"] if observations else None


def stop_unconfirmed(physical):
    return (physical is not None and physical.get("state") == "stopping" and physical.get("exit") is not None
            and isinstance(physical.get("reason"), str) and physical["reason"].startswith(STOP_UNCONFIRMED_PREFIX))


def classify(port, port_error=None):
    """Return dict(kind=..., reason=..., physical=...) from the port record and the caught port error."""
    physical = latest(port)
    summary = None if physical is None else {k: physical.get(k) for k in (
        "state", "stopReason", "exit", "observationCompleteness", "reason", "actualBinding", "accounting")}
    if port is not None and port.get("result") is not None:
        return dict(kind="completed", reason="completed", physical=summary)
    if stop_unconfirmed(physical):
        return dict(kind="stop-unconfirmed", reason="stop-unconfirmed", physical=summary)
    if physical is not None:
        state = physical.get("state")
        if state == "stopped":
            return dict(kind="stopped", reason="stopped-" + str(physical.get("stopReason")), physical=summary)
        if state == "failed":
            return dict(kind="failed", reason="failed-" + str(physical.get("stopReason") or "exit"), physical=summary)
        if state == "unknown":
            return dict(kind="unknown", reason="physical-unknown", physical=summary)
    if port_error is not None:
        code = port_error.get("code")
        if str(code).startswith("pre-release:") and (port is None or not port.get("start_dispatched")):
            return dict(kind="failed", reason="rejected-before-release:" + code[len("pre-release:"):], physical=summary,
                        portError=port_error)
        if code == "cancelled_by_host" and port is not None and not port.get("start_dispatched"):
            return dict(kind="failed", reason="cancelled-before-release", physical=summary, portError=port_error)
        if code in PRE_RELEASE_FAULTS and (port is None or not port.get("start_dispatched")):
            return dict(kind="failed", reason="rejected-before-release:" + code, physical=summary, portError=port_error)
        if code in ("execution-port-identity-unverified", "execution-port-binding-mismatch", "secret-leak",
                    "execution-port-integrity-mismatch", "execution-port-approval-out-of-policy") and port is not None and port.get("start_dispatched"):
            # The execution ran but its result is not trustworthy for this registration.
            return dict(kind="failed", reason="result-rejected:" + code, physical=summary, portError=port_error)
        if code == "execution_port_failure":
            return dict(kind="failed", reason="execution-port-failure", physical=summary, portError=port_error)
        return dict(kind="unknown", reason="port-error:" + str(code), physical=summary, portError=port_error)
    if physical is not None and (physical.get("state") in PENDING_STATES or physical.get("state") == "stopping"):
        return dict(kind="pending", reason="physical-" + physical["state"], physical=summary)
    return dict(kind="pending", reason="no-physical-fact", physical=summary)
