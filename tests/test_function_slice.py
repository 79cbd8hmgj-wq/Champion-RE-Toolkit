from __future__ import annotations

import pytest

from fncre.analysis.function_slice import FunctionSliceError, infer_function_end, slice_function
from fncre.xex.pe import parse_pe
from tests.pe_builder import build_pe32
from tests.symbol_builder import make_symbol

IMAGE_BASE = 0x82000000
SECTION_VA = 0x1000


def _sample_image():
    # Two tiny "functions": a branch at +0x00, then 0x10 bytes later another.
    code = bytearray(0x20)
    branch_word = (18 << 26) | 8  # b +8
    code[0:4] = branch_word.to_bytes(4, "big")
    data = build_pe32(
        image_base=IMAGE_BASE,
        section_name=b".text",
        section_va=SECTION_VA,
        section_bytes=bytes(code),
    )
    image_base, sections = parse_pe(data)
    return data, image_base, sections


def test_infer_function_end_uses_next_address():
    symbols = [
        make_symbol("Foo", 0x1000),
        make_symbol("Bar", 0x1010),
    ]
    end, boundary = infer_function_end(symbols, 0x1000)
    assert end == 0x1010
    assert boundary == "next_symbol_inferred"


def test_infer_function_end_unknown_for_last_symbol():
    symbols = [make_symbol("Foo", 0x1000)]
    end, boundary = infer_function_end(symbols, 0x1000)
    assert end is None
    assert boundary == "unknown"


def test_slice_function_extracts_bytes_and_decodes_branch():
    pe, image_base, sections = _sample_image()
    target = make_symbol("Foo", IMAGE_BASE + SECTION_VA)
    following = make_symbol("Bar", IMAGE_BASE + SECTION_VA + 0x10)

    result = slice_function(
        pe=pe,
        image_base=image_base,
        sections=sections,
        function_symbols_sorted=[target, following],
        target=target,
    )

    assert result.boundary == "next_symbol_inferred"
    assert result.size == 0x10
    assert result.end_va == IMAGE_BASE + SECTION_VA + 0x10
    assert len(result.branches) == 1
    assert result.branches[0].target == IMAGE_BASE + SECTION_VA + 8
    assert result.branches[0].kind == "b"


def test_slice_function_manual_override_size():
    pe, image_base, sections = _sample_image()
    target = make_symbol("Foo", IMAGE_BASE + SECTION_VA)

    result = slice_function(
        pe=pe, image_base=image_base, sections=sections, function_symbols_sorted=[target],
        target=target, override_size=4,
    )
    assert result.boundary == "manual_override"
    assert result.size == 4


def test_slice_function_raises_when_no_boundary_available():
    pe, image_base, sections = _sample_image()
    target = make_symbol("Foo", IMAGE_BASE + SECTION_VA)

    with pytest.raises(FunctionSliceError):
        slice_function(
            pe=pe, image_base=image_base, sections=sections,
            function_symbols_sorted=[target], target=target,
        )


def test_slice_function_requires_address():
    pe, image_base, sections = _sample_image()
    target = make_symbol("Foo", IMAGE_BASE + SECTION_VA)
    object.__setattr__(target, "address", None)

    with pytest.raises(FunctionSliceError):
        slice_function(
            pe=pe, image_base=image_base, sections=sections,
            function_symbols_sorted=[target], target=target, override_size=4,
        )
