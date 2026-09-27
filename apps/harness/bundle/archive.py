"""Deterministic ustar archive writer and a strict reader.

The same writer runs in the publisher's build and, at start, inside the bundle's own Runtime to rebuild
the archive from the installed members (the self-check that binds Initialize.bundleDigest to the real
bytes). It depends on nothing outside the standard library and never on tarfile, whose byte output is
not a stable contract across interpreter releases.

Every header is fixed except the path, the mode and the size: mtime, uid and gid are 0, uname and gname
are empty, typeflag is '0' (regular file), and the archive ends with two zero blocks and no record
padding. Paths use the ustar prefix field when longer than 100 bytes.
"""
import hashlib

BLOCK = 512
MODES = {"0644": 0o644, "0755": 0o755}


class ArchiveError(ValueError):
    """A member cannot be represented, or archive bytes do not parse as the accepted ustar subset."""


def valid_relative_path(path):
    """No leading slash, no empty, '.' or '..' segment, no backslash, no NUL (release-record RelativePath)."""
    return (isinstance(path, str) and 0 < len(path) <= 512 and "\\" not in path and "\0" not in path
            and not path.startswith("/") and all(part not in ("", ".", "..") for part in path.split("/")))


def _split(path):
    raw = path.encode("utf-8")
    if len(raw) <= 100:
        return raw, b""
    # ustar: name <= 100 bytes, prefix <= 155 bytes, joined by one '/'.
    for index in range(len(raw) - 1, -1, -1):
        if raw[index:index + 1] == b"/":
            prefix, name = raw[:index], raw[index + 1:]
            if len(prefix) <= 155 and 0 < len(name) <= 100:
                return name, prefix
    raise ArchiveError("path cannot be stored in a ustar header: " + path)


def _octal(value, width):
    text = "%0*o" % (width - 1, value)
    if len(text) > width - 1:
        raise ArchiveError("value does not fit the ustar field: %d" % value)
    return text.encode("ascii") + b"\0"


def header(path, size, mode):
    if not valid_relative_path(path):
        raise ArchiveError("member path is not a bundle-relative path: %r" % path)
    if mode not in MODES:
        raise ArchiveError("member mode must be 0644 or 0755: %r" % mode)
    name, prefix = _split(path)
    block = bytearray(BLOCK)
    block[0:len(name)] = name
    block[100:108] = _octal(MODES[mode], 8)
    block[108:116] = _octal(0, 8)
    block[116:124] = _octal(0, 8)
    block[124:136] = _octal(size, 12)
    block[136:148] = _octal(0, 12)
    block[148:156] = b" " * 8
    block[156:157] = b"0"
    block[257:263] = b"ustar\0"
    block[263:265] = b"00"
    block[345:345 + len(prefix)] = prefix
    checksum = sum(block)
    block[148:156] = ("%06o" % checksum).encode("ascii") + b"\0 "
    return bytes(block)


def write(members):
    """members: iterable of (path, data bytes, mode string). Returns the archive bytes."""
    seen = set()
    out = bytearray()
    for path, data, mode in members:
        if path in seen:
            raise ArchiveError("duplicate member path: " + path)
        seen.add(path)
        out += header(path, len(data), mode)
        out += data
        out += b"\0" * ((BLOCK - len(data) % BLOCK) % BLOCK)
    out += b"\0" * (2 * BLOCK)
    return bytes(out)


def digest(members):
    return hashlib.sha256(write(members)).hexdigest()


def _text(field):
    return field.split(b"\0", 1)[0].decode("utf-8")


def read(archive):
    """Parse archive bytes into a list of dicts (path, size, mode, type, linkname, data); every entry is
    reported so that a caller can refuse links and other member types by itself."""
    members, offset = [], 0
    while offset + BLOCK <= len(archive):
        block = archive[offset:offset + BLOCK]
        if block == b"\0" * BLOCK:
            break
        if block[257:262] != b"ustar":
            raise ArchiveError("archive is not ustar at offset %d" % offset)
        stored = int(_text(block[148:156]).strip() or "0", 8)
        computed = sum(block[:148]) + 8 * 32 + sum(block[156:])
        if stored != computed:
            raise ArchiveError("header checksum mismatch at offset %d" % offset)
        name, prefix = _text(block[0:100]), _text(block[345:500])
        size = int(_text(block[124:136]).strip() or "0", 8)
        mode = int(_text(block[100:108]).strip() or "0", 8) & 0o777
        typeflag = block[156:157].decode("ascii") if block[156] else "0"
        if offset + BLOCK + size > len(archive):
            raise ArchiveError("member size escapes the archive at offset %d" % offset)
        data = archive[offset + BLOCK:offset + BLOCK + size]
        members.append(dict(path=prefix + "/" + name if prefix else name, size=size, mode="%04o" % mode,
                            type=typeflag, linkname=_text(block[157:257]), data=data))
        offset += BLOCK + ((size + BLOCK - 1) // BLOCK) * BLOCK
    return members
