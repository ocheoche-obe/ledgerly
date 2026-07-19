"""ULID generation — sortable unique IDs, stdlib-only.

The Lambda asset ships as a plain source tree (no `pip install` step), so we keep the
zero-runtime-dependencies posture and hand-roll a ULID rather than pull in a package that
would need vendoring or a layer. A ULID is a 128-bit value — 48 bits of millisecond
timestamp + 80 bits of randomness — rendered as 26 Crockford base32 characters. The
timestamp prefix makes IDs lexicographically sortable by creation time, which is why
architecture §2.4 keys categories as ``CAT#<ulid>``.
"""
from __future__ import annotations

import os
import time

# Crockford base32 alphabet (excludes I, L, O, U to avoid ambiguity).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_ulid(now_ms: int | None = None, randomness: bytes | None = None) -> str:
    """A fresh 26-char ULID. Args are injectable so callers can make tests deterministic."""
    ms = now_ms if now_ms is not None else int(time.time() * 1000)
    rand = randomness if randomness is not None else os.urandom(10)
    if len(rand) != 10:
        raise ValueError("ULID randomness must be exactly 10 bytes")
    return _encode(ms & ((1 << 48) - 1), 10) + _encode(int.from_bytes(rand, "big"), 16)
