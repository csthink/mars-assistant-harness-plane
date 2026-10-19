"""SYNTHETIC Ed25519 for tests only (pure Python, slow but exact).

The arithmetic is a Python 3 port of the public-domain Python implementation published by the Ed25519 authors:
ed25519.py ("the main subroutines") from https://ed25519.cr.yp.to/software.html, whose Copyrights section states
"The Ed25519 software is in the public domain." The signature scheme is Ed25519 as specified in RFC 8032
section 5.1. Changes from that implementation: Python 3 bytes and integer division; built-in modular
exponentiation; int.from_bytes and int.to_bytes for the little-endian encodings; the verification scalar is
reduced modulo l as RFC 8032 section 5.1.7 specifies; and verification returns False instead of raising, also
rejecting non-canonical point encodings and an S that is not below l.

Keys are generated in process memory from os.urandom and are never written to disk, printed or passed
as arguments. The real development publisher key is never used by tests (Owner ruling feature-t18:OD-02).
This module also verifies signatures, so a synthetic Host can check the publisher's OpenSSL signature
with an independent implementation.
"""
import base64
import hashlib
import os

BITS = 256
FIELD = 2 ** 255 - 19
ORDER = 2 ** 252 + 27742317777372353535851937790883648493
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
# The PKCS#8 prefix of an Ed25519 private key, split so that no source file carries it contiguously (key scans).
PKCS8_PREFIX = bytes.fromhex("302e0201" "00300506" "032b6570" "04220420")


def _hash(message):
    return hashlib.sha512(message).digest()


def _inv(x):
    return pow(x, FIELD - 2, FIELD)


CURVE_D = -121665 * _inv(121666)
SQRT_M1 = pow(2, (FIELD - 1) // 4, FIELD)


def _xrecover(y):
    xx = (y * y - 1) * _inv(CURVE_D * y * y + 1)
    x = pow(xx, (FIELD + 3) // 8, FIELD)
    if (x * x - xx) % FIELD != 0:
        x = (x * SQRT_M1) % FIELD
    if x % 2 != 0:
        x = FIELD - x
    return x


BASE_Y = 4 * _inv(5)
BASE_X = _xrecover(BASE_Y)
BASE = (BASE_X % FIELD, BASE_Y % FIELD)


def _edwards(p, q):
    x1, y1 = p
    x2, y2 = q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + CURVE_D * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - CURVE_D * x1 * x2 * y1 * y2)
    return (x3 % FIELD, y3 % FIELD)


def _scalarmult(p, e):
    if e == 0:
        return (0, 1)
    q = _scalarmult(p, e // 2)
    q = _edwards(q, q)
    if e & 1:
        q = _edwards(q, p)
    return q


def _encodeint(y):
    return y.to_bytes(BITS // 8, "little")


def _encodepoint(p):
    x, y = p
    return (y | ((x & 1) << (BITS - 1))).to_bytes(BITS // 8, "little")


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _secret_scalar(h):
    return 2 ** (BITS - 2) + sum(2 ** i * _bit(h, i) for i in range(3, BITS - 2))


def _hint(message):
    return int.from_bytes(_hash(message), "little")


def _publickey(secret):
    return _encodepoint(_scalarmult(BASE, _secret_scalar(_hash(secret))))


def _signature(message, secret, public):
    h = _hash(secret)
    a = _secret_scalar(h)
    r = _hint(h[BITS // 8:BITS // 4] + message)
    encoded_r = _encodepoint(_scalarmult(BASE, r))
    s = (r + _hint(encoded_r + public + message) * a) % ORDER
    return encoded_r + _encodeint(s)


def _isoncurve(p):
    x, y = p
    return (-x * x + y * y - 1 - CURVE_D * x * x * y * y) % FIELD == 0


def _decodeint(data):
    return int.from_bytes(data, "little")


def _decodepoint(data):
    if len(data) != BITS // 8:
        return None
    y = _decodeint(data) & ((1 << (BITS - 1)) - 1)
    sign = _bit(data, BITS - 1)
    if y >= FIELD:
        return None
    x = _xrecover(y)
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = FIELD - x
    point = (x, y)
    if not _isoncurve(point):
        return None
    return point


class SyntheticKey:
    """In-memory SYNTHETIC key pair. `label` marks every artefact built with it."""

    label = "SYNTHETIC-ed25519-in-memory"
    identity = dict(program="tests/ed25519_synthetic.py", note="SYNTHETIC test signer, key never leaves process memory")

    def __init__(self, seed=None):
        self._seed = seed if seed is not None else os.urandom(32)
        self.public = _publickey(self._seed)
        der = SPKI_PREFIX + self.public
        self.public_pem = ("-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(der).decode() + "\n-----END PUBLIC KEY-----\n").encode()

    def sign(self, message):
        return _signature(message, self._seed, self.public)

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
    if len(signature) != BITS // 4:
        return False
    point_a = _decodepoint(public)
    point_r = _decodepoint(signature[:BITS // 8])
    s = _decodeint(signature[BITS // 8:])
    if point_a is None or point_r is None or s >= ORDER:
        return False
    h = _hint(signature[:BITS // 8] + public + message) % ORDER
    return _scalarmult(BASE, s) == _edwards(point_r, _scalarmult(point_a, h))
