"""Direct PPC branch/call cross-referencing against named functions.

Ported and generalized from Fight-Night-Legacy's `tools/re_branch_xrefs.py`
(`iter_direct_branches`, `build_function_ranges`, `caller_for_address`,
`find_direct_xrefs`) to operate on `fncre.symbols.models.Symbol` lists.

Same scope and limitations as the source tool: direct I-form/B-form
branches only, scanned in PE sections marked executable. Indirect
LR/CTR calls, virtual dispatch, and data/TOC references are not resolved.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass

from fncre.ppc.branch import decode_direct_branch
from fncre.symbols.models import Symbol
from fncre.xex.pe import (
    IMAGE_LAYOUT_XBOX_RVA,
    IMAGE_SCN_MEM_EXECUTE,
    PeSection,
    section_file_window,
)


@dataclass(frozen=True)
class DirectBranchSite:
    section: str
    callsite_va: int
    instruction_word: int
    kind: str
    target: int


@dataclass(frozen=True)
class Xref:
    callsite_va: int
    instruction_word: int
    kind: str
    section: str
    caller: Symbol | None


LIMITATIONS = (
    "direct PPC I-form/B-form branches only",
    "indirect LR/CTR calls and virtual dispatch are not included",
    "data/TOC references are not included",
    "only PE sections marked executable are scanned",
)


def iter_direct_branches(
    pe: bytes,
    *,
    image_base: int,
    sections: tuple[PeSection, ...],
    layout: str = IMAGE_LAYOUT_XBOX_RVA,
    executable_only: bool = True,
) -> Iterator[DirectBranchSite]:
    for section in sections:
        if executable_only and not (int(section.characteristics) & IMAGE_SCN_MEM_EXECUTE):
            continue

        file_offset, available = section_file_window(
            section=section, image_size=len(pe), layout=layout
        )
        available -= available % 4

        for delta in range(0, available, 4):
            off = file_offset + delta
            word = int.from_bytes(pe[off : off + 4], "big")
            va = image_base + section.virtual_address + delta
            branch = decode_direct_branch(word, va)
            if branch is None:
                continue
            kind = "bc" if branch["conditional"] else "b"
            if branch["link"]:
                kind += "l"
            yield DirectBranchSite(
                section=section.name,
                callsite_va=va,
                instruction_word=word,
                kind=kind,
                target=branch["target"],
            )


def build_function_ranges(symbols: list[Symbol]) -> list[tuple[int, int, Symbol]]:
    """Non-overlapping caller-attribution ranges from function-address symbols."""
    by_address: dict[int, Symbol] = {}
    for symbol in symbols:
        if symbol.address is not None:
            by_address.setdefault(symbol.address, symbol)

    ordered = [by_address[address] for address in sorted(by_address)]
    ranges: list[tuple[int, int, Symbol]] = []
    for current, following in zip(ordered, ordered[1:], strict=False):
        if following.address is not None and current.address is not None:
            if following.address > current.address:
                ranges.append((current.address, following.address, current))
    return ranges


def caller_for_address(callsite: int, ranges: list[tuple[int, int, Symbol]]) -> Symbol | None:
    if not ranges:
        return None
    starts = [start for start, _end, _symbol in ranges]
    index = bisect_right(starts, callsite) - 1
    if index < 0:
        return None
    start, end, symbol = ranges[index]
    if start <= callsite < end:
        return symbol
    return None


def find_direct_xrefs(
    pe: bytes,
    *,
    image_base: int,
    sections: tuple[PeSection, ...],
    all_symbols: list[Symbol],
    targets: list[Symbol],
    layout: str = IMAGE_LAYOUT_XBOX_RVA,
) -> dict[int, list[Xref]]:
    """Map each target symbol's address to the direct branches that reach it."""
    target_addresses = {t.address for t in targets if t.address is not None}
    results: dict[int, list[Xref]] = {addr: [] for addr in target_addresses}

    ranges = build_function_ranges(all_symbols)

    for site in iter_direct_branches(
        pe, image_base=image_base, sections=sections, layout=layout, executable_only=True
    ):
        if site.target not in results:
            continue
        caller = caller_for_address(site.callsite_va, ranges)
        results[site.target].append(
            Xref(
                callsite_va=site.callsite_va,
                instruction_word=site.instruction_word,
                kind=site.kind,
                section=site.section,
                caller=caller,
            )
        )

    return results
