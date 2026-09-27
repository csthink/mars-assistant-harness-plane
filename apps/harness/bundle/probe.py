"""Build-time probe, run by the builder inside the staged bundle interpreter as `python3.12 -I -B probe.py <root>`.

It imports every product module and every mechanism module that is a member, opens the production
Domain Core on an empty temporary Git repository to read the registered capabilities and schemas, and
reports them with the RFC 8785 bytes computed by the bundle's own dependencies. It also reports every
loaded module file so the builder can refuse a bundle whose code resolves outside its own root.
Nothing here is a bundle member.
"""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def refs(node, found):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                found.append(value)
            refs(value, found)
    elif isinstance(node, list):
        for value in node:
            refs(value, found)
    return found


def main():
    root = Path(sys.argv[1]).resolve()
    app = root / "app" / "apps" / "harness"
    mechanism = root / "app" / "mechanisms" / "review-channel"
    imported = []
    for path in sorted(app.rglob("*.py")):
        parts = path.relative_to(app).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts or parts == ("bundle", "probe"):
            continue
        importlib.import_module(".".join(parts))
        imported.append(".".join(parts))
    if str(mechanism) not in sys.path:
        sys.path.insert(0, str(mechanism))
    for path in sorted(mechanism.rglob("*.py")):
        parts = path.relative_to(mechanism).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        importlib.import_module(".".join(parts))
        imported.append("mechanisms:" + ".".join(parts))
    import rfc8785
    from domain.core import HarnessDomain
    with tempfile.TemporaryDirectory(prefix="hp-bundle-probe-") as directory:
        subprocess.run(["git", "init", "-q", directory], check=True)
        domain = HarnessDomain(directory, entry="runtime")
        by_digest = {hashlib.sha256(rfc8785.dumps(schema)).hexdigest(): (uri, schema) for uri, schema in domain.schemas.items()}
        capabilities = []
        for capability in domain.capabilities:
            uri, schema = by_digest[capability["schemaDigest"]]
            canonical = rfc8785.dumps(schema)
            capabilities.append(dict(capability, schemaUri=uri, canonicalSchemaHex=canonical.hex(),
                                     nonLocalRefs=[r for r in refs(schema, []) if not str(r).startswith("#/")]))
    loaded = sorted({str(Path(m.__file__).resolve()) for name, m in list(sys.modules.items())
                     if name != "__main__" and getattr(m, "__file__", None)})
    outside = [f for f in loaded if not f.startswith(str(root) + "/")]
    print(json.dumps(dict(python=sys.version, executable=sys.executable, flags=dict(isolated=sys.flags.isolated,
                                                                                    dont_write_bytecode=sys.flags.dont_write_bytecode),
                          imported=imported, capabilities=capabilities, loadedFiles=len(loaded), outsideRoot=outside)))


if __name__ == "__main__":
    main()
