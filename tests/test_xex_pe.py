from __future__ import annotations

import pytest

from fncre.xex.pe import IMAGE_LAYOUT_XBOX_RVA, parse_pe, section_file_window, va_to_file_offset
from tests.pe_builder import build_pe32

IMAGE_BASE = 0x82000000


def _sample_pe(section_bytes: bytes = bytes(0x100)) -> bytes:
    return build_pe32(
        image_base=IMAGE_BASE, section_name=b".text", section_va=0x1000, section_bytes=section_bytes
    )


def test_parse_pe_reads_image_base_and_section():
    data = _sample_pe()
    image_base, sections = parse_pe(data)
    assert image_base == IMAGE_BASE
    assert len(sections) == 1
    assert sections[0].name == ".text"
    assert sections[0].virtual_address == 0x1000


def test_parse_pe_rejects_non_pe():
    with pytest.raises(ValueError):
        parse_pe(b"not a pe")


def test_va_to_file_offset_xbox_rva_layout():
    data = _sample_pe()
    image_base, sections = parse_pe(data)
    offset = va_to_file_offset(
        va=IMAGE_BASE + 0x1010,
        image_base=image_base,
        sections=sections,
        image_size=len(data),
        layout=IMAGE_LAYOUT_XBOX_RVA,
    )
    assert offset == 0x1010  # xbox_rva: file_offset == RVA


def test_va_to_file_offset_below_image_base_raises():
    data = _sample_pe()
    image_base, sections = parse_pe(data)
    with pytest.raises(ValueError):
        va_to_file_offset(va=0x1000, image_base=image_base, sections=sections, image_size=len(data))


def test_va_to_file_offset_outside_any_section_raises():
    data = _sample_pe()
    image_base, sections = parse_pe(data)
    with pytest.raises(ValueError):
        va_to_file_offset(
            va=IMAGE_BASE + 0x9000, image_base=image_base, sections=sections, image_size=len(data)
        )


def test_section_file_window_xbox_rva():
    data = _sample_pe(section_bytes=bytes(0x40))
    _image_base, sections = parse_pe(data)
    offset, count = section_file_window(section=sections[0], image_size=len(data))
    assert offset == 0x1000
    assert count == 0x40
