"""PE image parsing and VA/RVA/raw-offset mapping.

Ported and generalized from Fight-Night-Legacy's
`tools/re_function_slice.py` (`parse_pe`, `va_to_file_offset`,
`section_file_window`). The algorithm is unchanged from that proven
implementation; this module only removes the FN5D-specific framing so it
works for any Xenon PE image (dev-key-extracted or conventional).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

IMAGE_LAYOUT_XBOX_RVA = "xbox_rva"
IMAGE_LAYOUT_PE_RAW = "pe_raw"
VALID_IMAGE_LAYOUTS = (IMAGE_LAYOUT_XBOX_RVA, IMAGE_LAYOUT_PE_RAW)
IMAGE_SCN_MEM_EXECUTE = 0x20000000


@dataclass(frozen=True)
class PeSection:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int


def _u16le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def parse_pe(data: bytes) -> tuple[int, tuple[PeSection, ...]]:
    """Parse an MZ/PE image's optional header and section table.

    Returns (image_base, sections). Works for both a conventional
    disk-layout PE and the RVA-mapped Xbox basefile produced by
    `fncre.xex.extract_xex2` — the section table format itself is
    identical; only how you index into the *data* differs, which is what
    `va_to_file_offset`/`layout` handle separately.
    """
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("input is not an MZ/PE image")

    pe_offset = _u32le(data, 0x3C)
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("PE signature not found")

    coff = pe_offset + 4
    num_sections = _u16le(data, coff + 2)
    optional_size = _u16le(data, coff + 16)
    optional = coff + 20

    if optional + optional_size > len(data):
        raise ValueError("truncated PE optional header")

    magic = _u16le(data, optional)
    if magic == 0x10B:  # PE32
        image_base = _u32le(data, optional + 28)
    elif magic == 0x20B:  # PE32+
        image_base = _u64le(data, optional + 24)
    else:
        raise ValueError(f"unsupported PE optional-header magic 0x{magic:04X}")

    section_table = optional + optional_size
    sections: list[PeSection] = []

    for index in range(num_sections):
        off = section_table + index * 40
        if off + 40 > len(data):
            raise ValueError("truncated PE section table")

        raw_name = data[off : off + 8].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", errors="replace")
        virtual_size = _u32le(data, off + 8)
        virtual_address = _u32le(data, off + 12)
        raw_size = _u32le(data, off + 16)
        raw_offset = _u32le(data, off + 20)
        characteristics = _u32le(data, off + 36)

        sections.append(
            PeSection(
                name=name,
                virtual_address=virtual_address,
                virtual_size=virtual_size,
                raw_offset=raw_offset,
                raw_size=raw_size,
                characteristics=characteristics,
            )
        )

    return int(image_base), tuple(sections)


def va_to_file_offset(
    *,
    va: int,
    image_base: int,
    sections: tuple[PeSection, ...],
    image_size: int | None = None,
    layout: str = IMAGE_LAYOUT_XBOX_RVA,
) -> int:
    """Translate a runtime VA to an offset in the supplied image.

    `fncre.xex.extract_xex2` produces an Xbox basefile image laid out by
    RVA: file_offset == RVA. The PE section header's PointerToRawData
    fields do not describe that extracted layout — this is the "critical
    addressing rule" documented in Fight-Night-Legacy's
    docs/re/xex-extraction.md, confirmed against the real FN5D build.
    `pe_raw` remains available for ordinary disk-layout PE files.
    """
    if layout not in VALID_IMAGE_LAYOUTS:
        raise ValueError(f"unknown image layout: {layout}")

    rva = int(va) - int(image_base)
    if rva < 0:
        raise ValueError(f"VA 0x{va:X} is below image base 0x{image_base:X}")

    for section in sections:
        span = max(section.virtual_size, section.raw_size)
        start = section.virtual_address
        end = start + span
        if not (start <= rva < end):
            continue

        if layout == IMAGE_LAYOUT_XBOX_RVA:
            offset = rva
            if image_size is not None and offset >= int(image_size):
                raise ValueError(f"VA 0x{va:X} maps beyond the extracted Xbox basefile")
            return offset

        delta = rva - start
        if delta >= section.raw_size:
            raise ValueError(f"VA 0x{va:X} falls in zero-filled tail of {section.name}")
        offset = section.raw_offset + delta
        if image_size is not None and offset >= int(image_size):
            raise ValueError(f"VA 0x{va:X} maps beyond the PE file")
        return offset

    raise ValueError(f"VA 0x{va:X} is not covered by a PE section")


def section_file_window(
    *,
    section: PeSection,
    image_size: int,
    layout: str = IMAGE_LAYOUT_XBOX_RVA,
) -> tuple[int, int]:
    """Return (file_offset, byte_count) for one section in the chosen layout."""
    if layout not in VALID_IMAGE_LAYOUTS:
        raise ValueError(f"unknown image layout: {layout}")

    if layout == IMAGE_LAYOUT_XBOX_RVA:
        offset = int(section.virtual_address)
        declared = int(section.virtual_size)
    else:
        offset = int(section.raw_offset)
        declared = int(section.raw_size)

    if offset < 0 or offset >= int(image_size):
        return offset, 0
    return offset, min(declared, int(image_size) - offset)
