"""Asynchronous execution contract and trusted domain authorization boundary."""
from dataclasses import dataclass
from typing import Protocol
import hashlib
from runtime.protocol import canonical


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(value):
    return sha(canonical(value))


class ExecutionError(Exception):
    def __init__(self, code, classification="execution_port_failure"):
        self.code, self.classification = code, classification
        super().__init__(code)


def require(ok, code="execution-port-integrity-mismatch"):
    if not ok:
        raise ExecutionError(code)


@dataclass(frozen=True)
class ExecutionDiscovery:
    """Trusted current connection discovery, never read from review Request.

    These three identities have different namespaces. The discovery implementation
    obtains the Host connection/configuration and protocol provider association.
    """
    profile: dict
    connection_ref: str
    registry_provider: str
    protocol_provider: str
    configuration_revision: str


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Produced by trusted domain policy after scope/Grant/DecisionRecord checks.

    This is not deserialized from a review Request or invocation_authorization.
    The policy callback must freshly revalidate authority on every call/recovery.
    """
    intent_digest: str
    invocation_sha256: str
    caller: str
    author_vendors: tuple
    author_evidence_refs: tuple
    owner_formal: bool
    max_calls: int
    authorization_ref: str = ""
    human_only: bool = False


class ExecutionPort(Protocol):
    async def preflight(self, intent): ...
    async def execute(self, reservation, seal_dir, instruction): ...
    async def query(self, reservation): ...
    async def cancel(self, reservation): ...
