"""Internal shared domain transaction seam, not a second Workflow authority.

Feature-t2 supplies the production implementation and its projection/action policy.
Every writer must use transaction: generation, barrier, revision, operation index,
projection events and release state share one atomic commit. The callback must have
no external side effects. Side effects may only use a durably accepted operation.
"""
from typing import Protocol, Callable, TypeVar
class DomainUnavailable(Exception):
    """A production domain adapter is not installed."""

T = TypeVar("T")

class DomainPort(Protocol):
    available: bool
    capabilities: list[dict]
    schemas: dict

    def acquire_generation(self) -> str: ...
    def read(self) -> dict: ...
    def transaction(self, generation: str, callback: Callable[[dict], T], *, intent: str = "domain") -> T: ...
    def action(self, state: dict, scope: str, action_id: str) -> dict: ...
    def accept_action(self, state: dict, operation: dict, request: dict) -> None: ...

class UnavailableDomain:
    available = False
    capabilities = []
    schemas = {}

    def acquire_generation(self):
        return "1"

    def read(self):
        return {"generation": "1", "revision": "0", "scopes": {}, "quiesced": False}

    def transaction(self, generation, callback, *, intent="domain"):
        raise DomainUnavailable("Production DomainPort is not installed")

    def action(self, state, scope, action_id):
        raise DomainUnavailable("Production DomainPort is not installed")

    def accept_action(self, state, operation, request):
        raise DomainUnavailable("Production DomainPort is not installed")
