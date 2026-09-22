"""Function-boundary slicing from a PE image and a symbol list.

Generalizes Fight-Night-Legacy's `tools/re_function_slice.py`
(`inferred_symbol_end`, `extract_one`) to operate on `fncre.symbols.models.Symbol`
objects (from a `SymbolIndex`) instead of a CSV/map-specific reader, and to
report explicit boundary provenance rather than assuming every caller wants
the same inference.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from fncre.ppc.branch import decode_direct_branch, hexdump_words
from fncre.symbols.models import Symbol
from fncre.xex.pe import IMAGE_LAYOUT_XBOX_RVA, PeSection, va_to_file_offset

BoundaryKind = Literal["exact", "next_symbol_inferred", "manual_override", "unknown"]


class FunctionSliceError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedBranch:
    offset_in_function: int
    va: int
    instruction_word: int
    kind: str  # "b", "bl", "bc", "bcl"
    target: int


@dataclass(frozen=True)
class FunctionSlice:
    symbol: Symbol
    start_va: int
    end_va: int | None
    size: int
    boundary: BoundaryKind
    blob: bytes
    ppc_words: str
    branches: tuple[DecodedBranch, ...]
    sha256: str


def infer_function_end(
    function_symbols_sorted: list[Symbol], start_address: int
) -> tuple[int | None, BoundaryKind]:
    """Find the next distinct address among (function-flagged) symbols.

    `function_symbols_sorted` must be sorted by address ascending and
    should normally be filtered to `is_function is True` first — mixing in
    data symbols would infer a boundary the linker didn't intend as a
    function edge (this mirrors Legacy's `read_map_function_symbols`,
    which filters on the 'f' flag before inferring boundaries).
    """
    for symbol in function_symbols_sorted:
        if symbol.address is not None and symbol.address > start_address:
            return symbol.address, "next_symbol_inferred"
    return None, "unknown"


def slice_function(
    *,
    pe: bytes,
    image_base: int,
    sections: tuple[PeSection, ...],
    function_symbols_sorted: list[Symbol],
    target: Symbol,
    max_bytes: int | None = None,
    override_size: int | None = None,
    layout: str = IMAGE_LAYOUT_XBOX_RVA,
) -> FunctionSlice:
    """Extract one function's raw bytes plus decoded direct branches.

    `override_size`, when given, takes precedence and is reported with
    boundary="manual_override" — use it when you know the true size (e.g.
    from a full linker map) rather than trusting boundary inference.
    """
    if target.address is None:
        raise FunctionSliceError(f"symbol {target.name!r} has no address")
    start = target.address

    if override_size is not None:
        end: int | None = start + override_size
        size = override_size
        boundary: BoundaryKind = "manual_override"
    else:
        end, boundary = infer_function_end(function_symbols_sorted, start)
        if end is None:
            raise FunctionSliceError(
                f"cannot infer end of {target.name!r}: no later symbol address"
            )
        size = end - start

    if size <= 0:
        raise FunctionSliceError(f"invalid inferred size for {target.name!r}: {size}")
    if max_bytes is not None:
        size = min(size, max_bytes)

    file_offset = va_to_file_offset(
        va=start,
        image_base=image_base,
        sections=sections,
        image_size=len(pe),
        layout=layout,
    )
    blob = pe[file_offset : file_offset + size]
    if len(blob) != size:
        raise FunctionSliceError(f"truncated PE data while extracting {target.name!r}")

    branches: list[DecodedBranch] = []
    for word_offset in range(0, len(blob) - (len(blob) % 4), 4):
        word = int.from_bytes(blob[word_offset : word_offset + 4], "big")
        va = start + word_offset
        decoded = decode_direct_branch(word, va)
        if decoded is None:
            continue
        kind = "bc" if decoded["conditional"] else "b"
        if decoded["link"]:
            kind += "l"
        branches.append(
            DecodedBranch(
                offset_in_function=word_offset,
                va=va,
                instruction_word=word,
                kind=kind,
                target=decoded["target"],
            )
        )

    return FunctionSlice(
        symbol=target,
        start_va=start,
        end_va=end,
        size=size,
        boundary=boundary,
        blob=blob,
        ppc_words=hexdump_words(blob, start),
        branches=tuple(branches),
        sha256=hashlib.sha256(blob).hexdigest(),
    )
