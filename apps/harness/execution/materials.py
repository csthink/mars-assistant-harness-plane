"""Verify sealed originals and export immutable Runtime resources transactionally."""
import base64
import json
import os
import stat
from pathlib import Path
from .port import require, sha, identity
from runtime.protocol import evidence_key


def sealed_materials(seal_dir, manifest, instruction, profile):
    root = Path(seal_dir).resolve(strict=True)
    require(isinstance(instruction, bytes))
    entries = manifest.get("inputs")
    require(isinstance(entries, list) and len(entries) + 1 <= 32)
    require(sha(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()) == manifest.get("manifest_sha256"))
    materials = []
    names = set()
    for item in entries:
        name = item["bundle_name"]
        require(isinstance(name, str) and name not in names and Path(name).name == name and name not in (".", ".."))
        path = root / name
        require(not path.is_symlink() and path.is_file() and path.resolve().parent == root)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_size == item["bytes"])
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(item["bytes"] + 1)
        finally:
            os.close(fd)
        require(len(raw) == item["bytes"] and sha(raw) == item["sha256"])
        raw.decode("utf-8", "strict")
        names.add(name)
        materials.append(("material", name, raw))
    # Object names are stable and the instruction maps original names to Host-visible refs.
    mapping = "\n".join(name + " -> material:" + sha(name.encode())[:32] for _, name, _ in materials)
    mapped = instruction + ("\n\nMaterial identity map (bundle_name -> objectRef):\n" + mapping + "\n").encode()
    result = [("instruction", "instruction", mapped)] + materials
    require(sum(len(b) for _, _, b in result) <= profile["maxContextBytes"])
    return result


def export_resources(state, intent, materials):
    refs = []
    for role, name, raw in materials:
        token = identity([intent["executionRequestId"], role, name, sha(raw)])
        ref = dict(authority="runtime", resourceHandle=intent["resourceHandle"],
                   scopeRef=intent["scopeRef"], objectRef="instruction" if role == "instruction" else "material:" + sha(name.encode())[:32],
                   revision=token, mediaType="text/markdown", bytes=len(raw), digest=sha(raw))
        value = dict(evidence=ref, dataBase64=base64.b64encode(raw).decode())
        key=evidence_key(ref)
        old = state.setdefault("resources", {}).get(key)
        require(old is None or old == value)
        state["resources"][key] = value
        refs.append(ref)
    return refs
