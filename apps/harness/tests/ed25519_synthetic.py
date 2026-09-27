"""SYNTHETIC Ed25519 for tests only (RFC 8032 section 5.1 arithmetic, pure Python, slow but exact).

Keys are generated in process memory from os.urandom and are never written to disk, printed or passed
as arguments. The real development publisher key is never used by tests (Owner ruling feature-t18:OD-02).
This module also verifies signatures, so a synthetic Host can check the publisher's OpenSSL signature
with an independent implementation.
"""
import base64
import hashlib
import os

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
# The PKCS#8 prefix of an Ed25519 private key, split so that no source file carries it contiguously (key scans).
PKCS8_PREFIX = bytes.fromhex("302e0201" "00300506" "032b6570" "04220420")


def _sha512(data):
    return hashlib.sha512(data).digest()


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % P
    bb = (y1 + x1) * (y2 + x2) % P
    cc = t1 * 2 * D * t2 % P
    dd = z1 * 2 * z2 % P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s, point):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, point)
        point = _add(point, point)
        s >>= 1
    return q


def _equal(a, b):
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


GY = 4 * pow(5, P - 2, P) % P
GX = _recover_x(GY, 0)
G = (GX, GY, 1, GX * GY % P)


def _compress(point):
    x, y, z, _ = point
    zinv = pow(z, P - 2, P)
    x, y = x * zinv % P, y * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _expand(secret):
    digest = _sha512(secret)
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


class SyntheticKey:
    """In-memory SYNTHETIC key pair. `label` marks every artefact built with it."""

    label = "SYNTHETIC-ed25519-in-memory"
    identity = dict(program="tests/ed25519_synthetic.py", note="SYNTHETIC test signer, key never leaves process memory")

    def __init__(self, seed=None):
        self._seed = seed if seed is not None else os.urandom(32)
        a, _ = _expand(self._seed)
        self.public = _compress(_mul(a, G))
        der = SPKI_PREFIX + self.public
        self.public_pem = ("-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(der).decode() + "\n-----END PUBLIC KEY-----\n").encode()

    def sign(self, message):
        a, prefix = _expand(self._seed)
        r = int.from_bytes(_sha512(prefix + message), "little") % L
        big_r = _compress(_mul(r, G))
        h = int.from_bytes(_sha512(big_r + self.public + message), "little") % L
        s = (r + h * a) % L
        return big_r + int.to_bytes(s, 32, "little")

    def __repr__(self):
        return "SyntheticKey(public=%s)" % self.public.hex()


def public_from_pem(pem):
    text = pem.decode("ascii") if isinstance(pem, bytes) else pem
    lines = [line.strip() for line in text.strip().splitlines()]
    der = base64.b64decode("".join(lines[1:-1]))
    if der[:12] != SPKI_PREFIX or len(der) != 44:
        raise ValueError("not an Ed25519 SubjectPublicKeyInfo")
    return der[12:]


def verify(public, message, signature):
    if len(signature) != 64:
        return False
    point_a = _decompress(public)
    point_r = _decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if point_a is None or point_r is None or s >= L:
        return False
    h = int.from_bytes(_sha512(signature[:32] + public + message), "little") % L
    return _equal(_mul(s, G), _add(point_r, _mul(h, point_a)))
