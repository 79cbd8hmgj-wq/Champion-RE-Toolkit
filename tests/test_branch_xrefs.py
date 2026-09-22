from __future__ import annotations

from fncre.analysis.branch_xrefs import build_function_ranges, caller_for_address, find_direct_xrefs
from fncre.xex.pe import parse_pe
from tests.pe_builder import build_pe32
from tests.symbol_builder import make_symbol

IMAGE_BASE = 0x82000000
SECTION_VA = 0x1000


def test_build_function_ranges_and_caller_lookup():
    symbols = [
        make_symbol("Foo", 0x1000),
        make_symbol("Bar", 0x1010),
        make_symbol("Baz", 0x1020),
    ]
    ranges = build_function_ranges(symbols)
    assert ranges == [(0x1000, 0x1010, symbols[0]), (0x1010, 0x1020, symbols[1])]

    assert caller_for_address(0x1004, ranges).name == "Foo"
    assert caller_for_address(0x1010, ranges).name == "Bar"
    assert caller_for_address(0x1020, ranges) is None  # last symbol has no known end
    assert caller_for_address(0x500, ranges) is None


def test_find_direct_xrefs_locates_caller_of_target():
    # Foo (at +0x00) calls Bar (at +0x10) via `bl +0x10`.
    code = bytearray(0x20)
    branch_word = (18 << 26) | 0x10 | 0b01  # bl +0x10
    code[0:4] = branch_word.to_bytes(4, "big")
    data = build_pe32(
        image_base=IMAGE_BASE,
        section_name=b".text",
        section_va=SECTION_VA,
        section_bytes=bytes(code),
    )
    image_base, sections = parse_pe(data)

    foo = make_symbol("Foo", IMAGE_BASE + SECTION_VA)
    bar = make_symbol("Bar", IMAGE_BASE + SECTION_VA + 0x10)
    all_symbols = [foo, bar]

    xrefs = find_direct_xrefs(
        data, image_base=image_base, sections=sections, all_symbols=all_symbols, targets=[bar]
    )

    assert bar.address in xrefs
    matches = xrefs[bar.address]
    assert len(matches) == 1
    assert matches[0].kind == "bl"
    assert matches[0].caller is not None
    assert matches[0].caller.name == "Foo"
    assert matches[0].callsite_va == IMAGE_BASE + SECTION_VA
