"""Domain-side reservations that protect one external execution (spec FR-30, NFR-09).

A reservation is taken before an external call is released and is kept while the domain cannot
safely confirm the result, the control or the physical effect. Completion, timeout and cancellation
do not release it: release happens only when the same execution fact has been settled and named in
the settlement. Physical execution observation lives under <git-common-dir>/harness/executions/ and
is read-only to the domain; a missing or damaged observation directory never proves that nothing
started, so it cannot release a reservation either.
"""
import copy

from domain.workflow.progression import instance, now, occurrence
from domain.workflow.results import (
    AUTHORITY_MISSING, IDEMPOTENT_REPLAY, REQUEST_CONFLICT, RESERVATION_HELD, TASK_TERMINAL,
    TRIGGER_NOT_APPLICABLE, WorkflowRejection,
)

HELD, SETTLED = "held", "settled"


def reserve(state, topology, task_id, command, *, revision):
    """Persist the reservation before anything external is released."""
    inst = instance(state, task_id)
    if inst["lifecycle"] != "ACTIVE":
        raise WorkflowRejection(TASK_TERMINAL, "a terminal Workflow takes no new reservation", lifecycle=inst["lifecycle"])
    reservation_id = command.get("reservationId")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "reservationId is required")
    if not isinstance(command.get("authorityRef"), str) or not command["authorityRef"]:
        raise WorkflowRejection(AUTHORITY_MISSING, "authorityRef is required to hold a reservation")
    body = dict(reservationId=reservation_id, node=inst["position"], occurrence=occurrence(inst, task_id),
                purpose=command.get("purpose", "external-execution"), authorityRef=command["authorityRef"],
                executionRef=command.get("executionRef"), protects=list(command.get("protects", [])),
                status=HELD, createdAt=now(), domainRevision=revision, settledAt=None, settlement=None, note=None)
    existing = inst["reservations"].get(reservation_id)
    if existing is not None:
        comparable = {k: v for k, v in body.items() if k not in ("createdAt", "domainRevision", "status", "settledAt", "settlement", "note")}
        recorded = {k: v for k, v in existing.items() if k not in ("createdAt", "domainRevision", "status", "settledAt", "settlement", "note")}
        if comparable != recorded:
            raise WorkflowRejection(REQUEST_CONFLICT, "reservationId already bound to a different reservation",
                                    reservationId=reservation_id)
        return dict(result=IDEMPOTENT_REPLAY, reservation=copy.deepcopy(existing))
    inst["reservations"][reservation_id] = body
    return dict(result="RESERVED", reservation=copy.deepcopy(body))


def settle(state, topology, task_id, command, *, revision):
    """Release a reservation only against a settled execution fact that the settlement names."""
    inst = instance(state, task_id)
    reservation_id = command.get("reservationId")
    reservation = inst["reservations"].get(reservation_id)
    if reservation is None:
        raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "no such reservation on this instance", reservationId=reservation_id)
    if reservation["status"] == SETTLED:
        return dict(result=IDEMPOTENT_REPLAY, reservation=copy.deepcopy(reservation))
    settlement = command.get("settlement")
    if not isinstance(settlement, dict) or not settlement.get("executionFact"):
        raise WorkflowRejection(RESERVATION_HELD,
                                "a reservation is released only by naming the settled execution fact; process exit, "
                                "timeout or a successful cancel request is not that fact",
                                reservationId=reservation_id)
    attempt_id = settlement.get("attemptId")
    if attempt_id is not None:
        attempt = next((a for a in inst["attempts"] if a["attemptId"] == attempt_id), None)
        if attempt is None:
            raise WorkflowRejection(TRIGGER_NOT_APPLICABLE, "settlement names an attempt this instance does not hold",
                                    attemptId=attempt_id)
        if attempt["status"] in ("CREATED", "RUNNING"):
            raise WorkflowRejection(RESERVATION_HELD, "the named attempt is not settled yet", attemptId=attempt_id)
    reservation.update(status=SETTLED, settledAt=now(), settlement=copy.deepcopy(settlement))
    return dict(result="SETTLED", reservation=copy.deepcopy(reservation))


def held(inst):
    return sorted(r for r, v in inst["reservations"].items() if v["status"] == HELD)
