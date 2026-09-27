"""Definition Human Gates: which decisions need the Definition entry, and their business preconditions.

Two decisions freeze the Definition and therefore must be accompanied by a finalization ruling
(FR-20): Authorize & Freeze at `Human Gate · Authorize Definition` and Accept With reservation at
`Human Gate · Definition Escalation`. The generic `workflow decide` path refuses exactly these two,
and the workflow.decide projection stops listing them (an intentional narrowing of feature-t2
behaviour; Definition Scope In). No other gate is listed here.
"""
from domain.definition.results import (
    BASIS_MISSING, BASIS_NOT_FINAL, RESERVATION_REQUIRED, DefinitionRejection,
)

AUTH_GATE = "N-DEF-AUTH-GATE"
ESCALATION_GATE = "N-DEF-ESCALATION-GATE"
VERDICT_DECISION = "N-DEF-VERDICT-DECISION"
AUTHORIZE = "Authorize & Freeze"
ACCEPT_RESERVATION = "Accept With reservation"
DISPOSE = "Dispose findings"
DEFINITION_ENTRY_DECISIONS = frozenset({(AUTH_GATE, AUTHORIZE), (ESCALATION_GATE, ACCEPT_RESERVATION)})


def requires_definition_entry(position, decision):
    return (position, decision) in DEFINITION_ENTRY_DECISIONS


def generic_filter(position, decisions):
    """Drop the decisions the generic entry may not submit; used by the workflow projection and status."""
    return [d for d in decisions if (position, d["decision"] if isinstance(d, dict) else d) not in DEFINITION_ENTRY_DECISIONS]


def entered_by(inst, node):
    """The edge that brought the current occurrence of `node` into being, from the immutable commits."""
    for record in reversed(inst["commits"]):
        nxt = record["nextSnapshot"]
        if (record["transitionKind"] == "POSITION_ADVANCE" and nxt["position"] == node
                and nxt["positionEntryRuntimeVersion"] == inst["positionEntryRevision"]):
            return record["selectedEdge"]
    return None


def authorize_basis(inst, definition):
    """Authorize & Freeze needs the final PASS verdict of the current candidate, or the review-skip path."""
    candidate = definition["candidates"][-1]
    edge = entered_by(inst, AUTH_GATE)
    if edge == "E-D04":
        return dict(kind="review-skip", candidate=candidate)
    if edge != "E-D07":
        raise DefinitionRejection(BASIS_MISSING, "the Definition authorization gate was not reached through PASS or Disabled",
                                  enteredBy=edge)
    rounds = [r for r in definition["rounds"] if r.get("verdict")]
    if not rounds:
        raise DefinitionRejection(BASIS_MISSING, "no recorded verdict")
    last = rounds[-1]
    if last["candidateId"] != candidate["candidateId"] or last["verdict"]["verdict"] != "PASS":
        raise DefinitionRejection(BASIS_NOT_FINAL, "the final recorded verdict is not a PASS for the current candidate",
                                  round=last["round"], candidateId=last["candidateId"], verdict=last["verdict"]["verdict"])
    return dict(kind="verdict", candidate=candidate, round=last)


def reservation_basis(definition, reservation):
    if not isinstance(reservation, str) or not reservation.strip():
        raise DefinitionRejection(RESERVATION_REQUIRED, "Accept With reservation needs the reservation text")
    rounds = [r for r in definition["rounds"] if r.get("verdict")]
    if not rounds or rounds[-1]["verdict"]["verdict"] != "FAIL":
        raise DefinitionRejection(BASIS_MISSING, "Accept With reservation keeps a FAIL verdict; none is the final verdict")
    candidate = definition["candidates"][-1]
    if rounds[-1]["candidateId"] != candidate["candidateId"]:
        raise DefinitionRejection(BASIS_NOT_FINAL, "the final FAIL verdict is for another candidate",
                                  round=rounds[-1]["round"])
    return dict(kind="reservation", candidate=candidate, round=rounds[-1])
