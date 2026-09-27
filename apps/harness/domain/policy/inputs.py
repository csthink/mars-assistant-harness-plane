"""Read-only inputs of the Policy Gate (feature-t6 design, 输入取得、控制代次与输入无效).

PolicyInputs binds one product-line repository and the review-channel Registry path. Every read here
happens inside the Domain Core unit of work that records the decision, and the identity of what was
read is written into the decision; nothing here writes the Registry, the repository or the domain.

The Registry is the owner of Reviewer port entries and the Reviewer model mapping. The author vendor
mapping is NOT read from it: after Assistant OD-399 it is product-side Domain configuration
(`configuration.authorVendors`, written by `config set author-vendor`). The Implementer port
registration belongs to feature-t4's product-side registration and is read through an injectable
reader; production injects none until feature-t4 delivers it, so an implement release is NOT_CHECKED.
"""
import copy
import hashlib
import re
import sys
from pathlib import Path

from domain.acceptance.gitrepo import GitAbsent, GitUnavailable, Repository

HP_ROOT = Path(__file__).resolve().parents[4]
MECHANISM = HP_ROOT / "mechanisms" / "review-channel"
REGISTRY_FILE = MECHANISM / "review_channel_registry.json"
# Coordinator ruling (feature-t3 integration, Assistant seam ruling follow-up): the one Registry source is
# the review-channel Registry inside the product-line repository the Runtime is bound to. For hp itself
# the bound repository is hp, so REGISTRY_FILE and the bound path are the same file.
REGISTRY_RELATIVE = Path("mechanisms") / "review-channel" / "review_channel_registry.json"
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class InputsUnavailable(Exception):
    """An input could not be read or identified; the item that needed it is NOT_CHECKED."""

    def __init__(self, code, message, **detail):
        self.code, self.detail = code, dict(detail)
        super().__init__(message)


class _Channel:
    """Lazy handle on the review-channel mechanism modules; imported only when a decision needs them."""
    _modules = None

    @classmethod
    def modules(cls):
        if cls._modules is None:
            if str(MECHANISM) not in sys.path:
                sys.path.insert(0, str(MECHANISM))
            import review_channel_contract as contract
            import review_channel_receipt as receipt
            import review_channel_registry as registry
            import review_channel_runtime as runtime
            import review_channel_selection as selection
            cls._modules = dict(contract=contract, receipt=receipt, registry=registry, runtime=runtime,
                                selection=selection)
        return cls._modules


def vendors():
    """The model vendor closed set; its only owner is review-channel design §6.11 (VENDORS)."""
    return tuple(_Channel.modules()["contract"].VENDORS)


def bound_registry_path(repository):
    return Path(repository) / REGISTRY_RELATIVE


def load_live_registry(path=REGISTRY_FILE, repo_root=HP_ROOT):
    """Load and validate the live Registry exactly as the review channel does; read only."""
    ch = _Channel.modules()
    try:
        loaded = ch["registry"].load_registry(str(path), adapter_loader=lambda rid: ch["runtime"].load_adapter(rid),
                                              repo_root=str(repo_root), profile_checker=ch["receipt"].profile_shape_problems)
    except BaseException as exc:  # noqa: BLE001 - any loader failure is fail-closed, never a pass
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise InputsUnavailable("REGISTRY_UNAVAILABLE", "the review-channel Registry could not be loaded: "
                                + type(exc).__name__ + ": " + str(exc)[:512], path=str(path)) from None
    return dict(registry=loaded["registry"], sha256=loaded["sha256"], revision=loaded["revision"], path=str(path),
                synthetic=False)


def channel_rounds(repository, task_id, stage, review, defaults):
    """Delivered and allowed review rounds, via the review channel's own counting functions (§6.10)."""
    ch = _Channel.modules()
    try:
        rounds = ch["selection"].scan_rounds(str(repository), "tasks/%s/reviews" % task_id, "task", stage)
        request = dict(max_rounds=review.get("maxRounds"), round_extensions=list(review.get("roundExtensions") or []),
                       round_index=None)
        budget = ch["selection"].round_budget(request, defaults, rounds)
    except BaseException as exc:  # noqa: BLE001 - unreadable round facts are NOT_CHECKED
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise InputsUnavailable("ROUND_FACTS_UNREADABLE", "review round facts could not be read: "
                                + type(exc).__name__ + ": " + str(exc)[:512]) from None
    return dict(submitted=budget["submitted_rounds"], allowed=budget["allowed_rounds"], exhausted=budget["exhausted"],
                source="review-channel")


class PolicyInputs:
    """One evaluation's read-only view of the repository, the Registry and the round facts."""

    def __init__(self, repository, *, registry_loader=None, round_reader=None, implementer_registrations=None):
        self.repo = repository if isinstance(repository, Repository) else Repository(repository)
        self.repository_path = str(self.repo.path)
        self._registry_loader = registry_loader or (
            lambda: load_live_registry(bound_registry_path(self.repository_path), repo_root=self.repository_path))
        self._round_reader = round_reader
        self._implementer = implementer_registrations
        self._registry = None

    # -- Registry -------------------------------------------------------------------------------
    def registry(self):
        if self._registry is None:
            self._registry = self._registry_loader()
        return self._registry

    def reviewer_port(self, port_id):
        loaded = self.registry()
        ports = [p for p in loaded["registry"].get("execution_ports", []) if p.get("id") == port_id]
        if len(ports) != 1:
            return None, loaded
        return copy.deepcopy(ports[0]), loaded

    def reviewer_mapping(self, mapping_id):
        loaded = self.registry()
        rows = [m for m in loaded["registry"].get("model_mappings", []) if m.get("id") == mapping_id]
        return copy.deepcopy(rows[0]) if len(rows) == 1 else None

    def defaults(self):
        return copy.deepcopy(self.registry()["registry"]["defaults"])

    # -- feature-t4 product-side Implementer registration --------------------------------------
    def implementer_registration(self, state, port_id):
        """None when no registration reader is installed (production until feature-t4 delivers it)."""
        if self._implementer is None:
            return None
        found = self._implementer(state, port_id)
        return copy.deepcopy(found) if found else None

    # -- review round facts ---------------------------------------------------------------------
    def rounds(self, task_id, stage, review):
        if self._round_reader is not None:
            return self._round_reader(task_id, stage, review, self.defaults())
        return channel_rounds(self.repository_path, task_id, stage, review, self.defaults())

    # -- Git objects ----------------------------------------------------------------------------
    def blob(self, commit, path):
        """Bytes of path at an exact commit; None when absent; InputsUnavailable when git cannot answer."""
        if not FULL_SHA.fullmatch(str(commit)):
            return None
        try:
            return self.repo.read(commit, path)
        except GitAbsent:
            return None
        except GitUnavailable as exc:
            raise InputsUnavailable("INPUTS_UNAVAILABLE", "git could not read the object: " + str(exc)) from None

    def commit_exists(self, commit):
        if not FULL_SHA.fullmatch(str(commit)):
            return False
        try:
            self.repo.text("rev-parse", "--verify", "--quiet", commit + "^{commit}", absent_codes=(1, 128))
            return True
        except GitAbsent:
            return False
        except GitUnavailable as exc:
            raise InputsUnavailable("INPUTS_UNAVAILABLE", "git could not resolve the commit: " + str(exc)) from None


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
