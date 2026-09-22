"""EA AttribSys string/attribute hashing.

Ported unchanged in algorithm from Fight-Night-Legacy's
`tools/attrib_hash.py`: a Bob Jenkins lookup2-style 32-bit hash with
a=b=0x9E3779B9, c=0xABCDEF00 (seed), consuming input in 12-byte
little-endian blocks. Verified against the same example vectors documented
there (from FN5D's own generated hash initializers):

    rating_bum      -> 0x56D9A633
    career_goals    -> 0xF681681B
    fight_sim       -> 0xA9244D34
    pro_settings    -> 0x5B62B6EC
    ranking_formula -> 0x4B147504
    scheduling      -> 0xA00607F5

Generated C++ identifiers named `key_<text>` hash `<text>`, not the
`key_` prefix itself — see `strip_key_prefix`.

This module intentionally does not modify the algorithm in any way: it is
the oracle other fncre.attrib modules resolve hashes against.
"""

from __future__ import annotations

_MASK = 0xFFFFFFFF
_GOLDEN = 0x9E3779B9
DEFAULT_SEED = 0xABCDEF00


def _u32(value: int) -> int:
    return value & _MASK


def _mix(a: int, b: int, c: int) -> tuple[int, int, int]:
    a = _u32(a - b - c)
    a ^= c >> 13
    b = _u32(b - c - a)
    b ^= _u32(a << 8)
    c = _u32(c - a - b)
    c ^= b >> 13

    a = _u32(a - b - c)
    a ^= c >> 12
    b = _u32(b - c - a)
    b ^= _u32(a << 16)
    c = _u32(c - a - b)
    c ^= b >> 5

    a = _u32(a - b - c)
    a ^= c >> 3
    b = _u32(b - c - a)
    b ^= _u32(a << 10)
    c = _u32(c - a - b)
    c ^= b >> 15

    return _u32(a), _u32(b), _u32(c)


def attrib_hash_bytes(data: bytes, seed: int = DEFAULT_SEED) -> int:
    a = _GOLDEN
    b = _GOLDEN
    c = _u32(seed)

    total_length = len(data)
    offset = 0
    remaining = total_length

    while remaining >= 12:
        a = _u32(a + int.from_bytes(data[offset : offset + 4], "little"))
        b = _u32(b + int.from_bytes(data[offset + 4 : offset + 8], "little"))
        c = _u32(c + int.from_bytes(data[offset + 8 : offset + 12], "little"))
        a, b, c = _mix(a, b, c)
        offset += 12
        remaining -= 12

    c = _u32(c + total_length)
    tail = data[offset:]

    # Exact lookup2 fall-through tail packing.
    if remaining >= 11:
        c = _u32(c + (tail[10] << 24))
    if remaining >= 10:
        c = _u32(c + (tail[9] << 16))
    if remaining >= 9:
        c = _u32(c + (tail[8] << 8))
    if remaining >= 8:
        b = _u32(b + (tail[7] << 24))
    if remaining >= 7:
        b = _u32(b + (tail[6] << 16))
    if remaining >= 6:
        b = _u32(b + (tail[5] << 8))
    if remaining >= 5:
        b = _u32(b + tail[4])
    if remaining >= 4:
        a = _u32(a + (tail[3] << 24))
    if remaining >= 3:
        a = _u32(a + (tail[2] << 16))
    if remaining >= 2:
        a = _u32(a + (tail[1] << 8))
    if remaining >= 1:
        a = _u32(a + tail[0])

    _, _, c = _mix(a, b, c)
    return c


def attrib_hash(text: str, seed: int = DEFAULT_SEED) -> int:
    return attrib_hash_bytes(text.encode("utf-8"), seed)


def strip_key_prefix(cpp_identifier: str) -> str:
    """`key_fight_sim` -> `fight_sim`; anything else is returned unchanged.

    Generated AttribSys C++ globals named `key_<text>` hash `<text>`, not
    the literal `key_` prefix — this is the one naming convention needed to
    go from a linker-map identifier to the string that was actually hashed.
    """
    return cpp_identifier[4:] if cpp_identifier.startswith("key_") else cpp_identifier
