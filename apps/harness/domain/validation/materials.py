"""The reviewed materials of one impl round: a single candidate change document plus reference files.

The review channel's task axis takes exactly one candidate (review-channel r10 §6.1), so the whole
candidate change (dispatch baseline to candidate commit, every remediation round included) is rendered
into one deterministic document: a header with the base and candidate commits and the per-path blob
SHA-256 at the candidate, the Verify outcome bound to that candidate, and the unified diff inside a fenced
block (the channel does not scan fenced blocks for references). The references are the finalized
Definition at its finalization commit, the accepted-anchor revision of proposal / spec / milestones
(D-02 §12: downstream uses the same accepted anchor) and design.md at the candidate when present.

build() only reads Git objects and returns bytes; it runs inside the dispatch transaction to fix the
identities and again outside it to prove the same bytes before any provider call. materialize() writes
them under the task's ignored attempts area and is used by the production channel runner only.
"""
import hashlib
import json
from pathlib import Path

from domain.implement_verify import worktree
from domain.validation.results import REVIEW_MATERIAL_MISMATCH, ValidationRejection

ROLE_PATHS = {"proposal": "sdd/proposal.md", "spec": "sdd/spec.md", "milestones": "sdd/milestones.md"}
DOCUMENT = "candidate-change.md"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def directory(task_id, round_label):
    return "tasks/%s/attempts/validation/%s" % (task_id, round_label)


def _show(path, commit, file):
    found = worktree.git(path, "cat-file", "-e", "%s:%s" % (commit, file), check=False)
    if found.returncode != 0:
        return None
    return worktree.blob(path, commit, file)


def render(task_id, round_label, base, candidate, changed, verification, diff):
    lines = ["# Candidate change of %s, impl round %s" % (task_id, round_label), "",
             "- Task record: %s" % task_id, "- Dispatch baseline commit: %s" % base, "- Candidate commit: %s" % candidate,
             "- Changed paths (blob SHA-256 at the candidate commit):"]
    for path, digest in changed:
        lines.append("  - %s: %s" % (path, digest))
    lines += ["", "## Verify", ""]
    if verification["result"] == "NOT_APPLICABLE":
        lines.append("- Result: None Applicable (no applicable prescribed deterministic check)")
    else:
        lines.append("- Result: %s (checks revision %s)" % (verification["result"], verification.get("checksRevision")))
        for result in verification.get("checkResults") or []:
            lines.append("  - %s: exit %s, stdout SHA-256 %s" % (result.get("id"), result.get("exitCode"),
                                                                 (result.get("stdout") or {}).get("sha256")))
    lines += ["", "## Unified diff (baseline to candidate)", "", "```diff", diff.rstrip("\n"), "```", ""]
    return "\n".join(lines).encode("utf-8")


def build(worktree_path, task, round_label, base, candidate, verification, final):
    """Return {document: {name, raw}, references: [{role, name, sourceCommit, sourcePath, raw}]} or raise."""
    path = Path(worktree_path)
    changed = []
    for file in worktree.changed_files(path, base, candidate):
        raw = _show(path, candidate, file)
        changed.append((file, "deleted" if raw is None else sha256(raw)))
    diff = worktree.git(path, "diff", "--no-color", "--no-ext-diff", "--no-renames", base, candidate).stdout.decode(
        "utf-8", errors="replace")
    document = render(task["taskId"], round_label, base, candidate, changed, verification, diff)
    references = []
    definition = _show(path, final["commit"], final["path"])
    if definition is None or sha256(definition) != final["sha256"]:
        raise ValidationRejection(REVIEW_MATERIAL_MISMATCH, "the finalized Definition bytes cannot be read at their commit",
                                  definition=final)
    references.append(dict(role="definition", name="definition.md", sourceCommit=final["commit"], sourcePath=final["path"],
                           raw=definition))
    anchor = task["anchor"]
    for role, file in ROLE_PATHS.items():
        identity = (anchor.get("components") or {}).get(role)
        if identity is None:
            continue
        raw = _show(path, anchor["sourceRevision"], file)
        if raw is None or sha256(raw) != identity.get("sha256"):
            raise ValidationRejection(REVIEW_MATERIAL_MISMATCH, "an accepted-anchor source differs from its anchored identity",
                                      role=role, path=file, sourceRevision=anchor["sourceRevision"])
        references.append(dict(role=role, name=role + ".md", sourceCommit=anchor["sourceRevision"], sourcePath=file, raw=raw))
    design_path = str(Path(final["path"]).parent / "design.md")
    design = _show(path, candidate, design_path)
    if design is not None:
        references.append(dict(role="design", name="design.md", sourceCommit=candidate, sourcePath=design_path, raw=design))
    return dict(document=dict(name=DOCUMENT, raw=document), references=references)


def identity(materials):
    doc = materials["document"]
    return dict(document=dict(name=doc["name"], bytes=len(doc["raw"]), sha256=sha256(doc["raw"])),
                references=[dict(role=r["role"], name=r["name"], sourceCommit=r["sourceCommit"], sourcePath=r["sourcePath"],
                                 bytes=len(r["raw"]), sha256=sha256(r["raw"])) for r in materials["references"]])


def check(recorded, materials):
    """The rebuilt materials must be byte-identical to the identities fixed at dispatch."""
    rebuilt = identity(materials)
    if rebuilt != {k: recorded[k] for k in ("document", "references")}:
        raise ValidationRejection(REVIEW_MATERIAL_MISMATCH, "the reviewed materials differ from the identities fixed at dispatch",
                                  recorded=json.loads(json.dumps(recorded)), rebuilt=rebuilt)
    return rebuilt


def materialize(worktree_path, task_id, round_label, materials):
    """Write the materials under the task's ignored attempts area; returns the repository-relative paths."""
    base = directory(task_id, round_label)
    target = Path(worktree_path) / base
    target.mkdir(parents=True, exist_ok=True)
    (target / materials["document"]["name"]).write_bytes(materials["document"]["raw"])
    names = []
    for reference in materials["references"]:
        (target / reference["name"]).write_bytes(reference["raw"])
        names.append(base + "/" + reference["name"])
    return base + "/" + materials["document"]["name"], names
