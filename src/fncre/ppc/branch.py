"""Direct PowerPC branch decoding, ported from Fight-Night-Legacy's
`tools/re_function_slice.py` (`decode_direct_branch`, `hexdump_words`)
unchanged in algorithm.
"""

from __future__ import annotations

from typing import TypedDict


class DirectBranch(TypedDict):
    target: int
    link: bool
    conditional: bool
    absolute: bool


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def decode_direct_branch(word: int, address: int) -> DirectBranch | None:
    """Decode PPC I-form/B-form direct branch targets.

    This is intentionally narrow. It does not attempt to decode indirect
    branches through LR/CTR or interpret BO/BI conditions.
    """
    opcode = (word >> 26) & 0x3F

    if opcode == 18:  # b / bl
        displacement = _sign_extend(word & 0x03FFFFFC, 26)
        absolute = bool(word & 0x2)
        link = bool(word & 0x1)
        target = displacement if absolute else address + displacement
        return {
            "target": target & 0xFFFFFFFF,
            "link": link,
            "conditional": False,
            "absolute": absolute,
        }

    if opcode == 16:  # bc / bcl family
        displacement = _sign_extend(word & 0x0000FFFC, 16)
        absolute = bool(word & 0x2)
        link = bool(word & 0x1)
        target = displacement if absolute else address + displacement
        return {
            "target": target & 0xFFFFFFFF,
            "link": link,
            "conditional": True,
            "absolute": absolute,
        }

    return None


def hexdump_words(blob: bytes, start_va: int) -> str:
    lines: list[str] = []
    for offset in range(0, len(blob), 4):
        chunk = blob[offset : offset + 4]
        if len(chunk) < 4:
            lines.append(f"{start_va + offset:08X}  {chunk.hex()}")
            continue

        word = int.from_bytes(chunk, "big")
        line = f"{start_va + offset:08X}  {word:08X}"
        branch = decode_direct_branch(word, start_va + offset)
        if branch is not None:
            kind = "bc" if branch["conditional"] else "b"
            if branch["link"]:
                kind += "l"
            line += f"  ; {kind} -> 0x{branch['target']:08X}"
        lines.append(line)

    return "\n".join(lines) + "\n"
