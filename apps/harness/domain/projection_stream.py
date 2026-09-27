"""Object-level revisions and the ordered projection stream of every open scope (Assistant KB-296).

The projection builders (acceptance, Workflow, Definition, Implement/Verify, budget, Validate Change,
Publish) derive each scope's objects and actions from domain state. The Runtime Contract (快照、事件与竞争)
binds every object to its own domain revision, which advances only when that object's own rows change, and
requires every change after a snapshot watermark to be replayed on the scope's ordered stream as object,
action or pending-item upsert and remove.

rebuild() is the one way a projection is rebuilt. It compares every rebuilt scope with the projection last
committed in the same state: an unchanged object keeps its revision; a new or changed object takes the domain
revision of the committing transaction; every action binds the current revision of the object it targets; and
each change is appended to the scope's stream in the same transaction, removals before upserts and objects
before the actions and pending items that refer to them. A Host that applies these events after its snapshot
watermark therefore holds what a new snapshot taken at the same point returns. A write that changes no
projected content appends nothing and changes no revision.
"""
import copy
import uuid

# (view bucket, identity field, event family); removals are emitted in this order, upserts in reverse.
FAMILIES = (("actions", "actionId", "action"), ("pendingItems", "itemRef", "pending"), ("objects", "objectRef", "object"))


def emit(state, scope, kind, payload, cause=None):
    """Append one data event to the scope's stream; its seq is the next contiguous number."""
    view = state["scopes"][scope]
    view["seq"] = str(int(view["seq"]) + 1)
    view["events"].append(dict(eventId="event:" + uuid.uuid4().hex, scopeRef=scope, streamId=view["streamId"],
                               epoch=view["epoch"], seq=view["seq"], domainRevision=state["revision"],
                               causationId=cause, kind=kind, payload=copy.deepcopy(payload)))


def index(view):
    return {bucket: {item[key]: item for item in view.get(bucket, [])} for bucket, key, _family in FAMILIES}


def content(obj):
    return {k: v for k, v in obj.items() if k != "revision"}


def rebuild(state, build, causes=None):
    """Run the projection builders, then assign object revisions and publish every change as events.

    causes maps a scope to the Operation that caused this write there. Without an entry, a scope's events take
    the causation of the last event this same transaction already appended to that scope (the Operation change
    it settles), or none.
    """
    before = {scope: copy.deepcopy(index(view)) for scope, view in state.get("scopes", {}).items()}
    build(state)
    for scope, view in state.get("scopes", {}).items():
        publish(state, scope, view, before.get(scope) or index({}), (causes or {}).get(scope))


def publish(state, scope, view, before, cause):
    revision = state["revision"]
    for obj in view["objects"]:
        old = before["objects"].get(obj["objectRef"])
        obj["revision"] = old["revision"] if old is not None and content(old) == content(obj) else revision
    current = {obj["objectRef"]: obj["revision"] for obj in view["objects"]}
    for action in view["actions"]:
        if action["objectRef"] in current:
            action["expectedRevision"] = current[action["objectRef"]]
    after = index(view)
    tail = view["events"][-1] if view["events"] else None
    if cause is None and tail is not None and tail["domainRevision"] == revision:
        cause = tail["causationId"]
    for bucket, key, family in FAMILIES:
        for ref in before[bucket]:
            if ref not in after[bucket]:
                emit(state, scope, family + ".remove", {key: ref}, cause)
    for bucket, key, family in reversed(FAMILIES):
        for item in view.get(bucket, []):
            if before[bucket].get(item[key]) != item:
                emit(state, scope, family + ".upsert", item, cause)


def bind(state, scope, action):
    """The action as projected: its expectedRevision is the current revision of the object it targets."""
    for obj in state.get("scopes", {}).get(scope, {}).get("objects", []):
        if obj["objectRef"] == action["objectRef"]:
            return dict(action, expectedRevision=obj["revision"])
    return action
