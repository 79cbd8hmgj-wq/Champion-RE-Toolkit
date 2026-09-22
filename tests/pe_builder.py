"""Minimal synthetic PE32 builder for tests.

Builds just enough of an MZ/PE32 image (DOS stub, PE signature, COFF
header, a PE32 optional header with ImageBase, and one section header) for
`fncre.xex.pe.parse_pe` and the analysis modules to exercise their real
logic without any proprietary or real-world binary.
"""

from __future__ import annotations

import struct

IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000


def build_pe32(
    *,
    image_base: int,
    section_name: bytes,
    section_va: int,
    section_bytes: bytes,
    characteristics: int = IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
) -> bytes:
    """Build an xbox_rva-layout PE32 image: file_offset == RVA for the section."""
    pe_offset = 0x80
    coff = pe_offset + 4
    optional = coff + 20
    optional_size = 96  # minimal PE32 optional header we actually populate
    section_table = optional + optional_size
    data_start = section_va  # xbox_rva layout: file offset == RVA

    total_size = data_start + len(section_bytes)
    buf = bytearray(total_size)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, pe_offset)
    buf[pe_offset : pe_offset + 4] = b"PE\0\0"

    # COFF header: Machine, NumberOfSections, TimeDateStamp, PtrToSymTab,
    # NumSymbols, SizeOfOptionalHeader, Characteristics
    struct.pack_into(
        "<HHIIIHH", buf, coff, 0x01F2, 1, 0, 0, 0, optional_size, 0x0102
    )

    # PE32 optional header (subset): Magic, then pad to ImageBase at +28.
    struct.pack_into("<H", buf, optional, 0x10B)
    struct.pack_into("<I", buf, optional + 28, image_base)

    name_field = (section_name + b"\0" * 8)[:8]
    buf[section_table : section_table + 8] = name_field
    struct.pack_into(
        "<IIIIIIHHI",
        buf,
        section_table + 8,
        len(section_bytes),  # VirtualSize
        section_va,  # VirtualAddress
        len(section_bytes),  # SizeOfRawData
        data_start,  # PointerToRawData
        0,
        0,
        0,
        0,
        characteristics,
    )

    buf[data_start : data_start + len(section_bytes)] = section_bytes
    return bytes(buf)
