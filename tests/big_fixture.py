"""Build a minimal, entirely synthetic EA EB\\0\\3 BIG archive for tests.

Not derived from any real Fight-Night-Legacy archive — hand-built to match
the byte layout documented in tools/ea_eb_extract.py: big-endian metadata,
16-byte file records from 0x30, 41-byte filename records, 40-byte fixed
folder-name records, 16-byte-unit payload offsets.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class FileSpec:
    folder: str
    name: str
    data: bytes


def build_big(files: list[FileSpec]) -> bytes:
    folders = []
    for f in files:
        if f.folder not in folders:
            folders.append(f.folder)

    count = len(files)
    names_offset = 0x30 + count * 16
    folder_offset = (names_offset + count * 41 + 15) & ~15
    data_start_bytes = folder_offset + len(folders) * 40
    data_start = (data_start_bytes + 15) & ~15

    # Payload offsets are in 16-byte units and must land on that grid.
    payload_offset = data_start
    payloads = []
    records = []
    for f in files:
        folder_index = folders.index(f.folder)
        offset_units = payload_offset // 16
        assert payload_offset % 16 == 0
        records.append((folder_index, f.name, offset_units, len(f.data)))
        payloads.append((payload_offset, f.data))
        payload_offset += (len(f.data) + 15) & ~15

    total_size = payload_offset

    buf = bytearray(total_size)
    buf[0:4] = b"EB\x00\x03"
    struct.pack_into(">I", buf, 4, count)
    struct.pack_into(">I", buf, 8, data_start)
    struct.pack_into(">I", buf, 12, names_offset)
    struct.pack_into(">H", buf, 22, len(folders))
    struct.pack_into(">I", buf, 28, total_size)

    for i, (folder_index, name, offset_units, size) in enumerate(records):
        record = 0x30 + i * 16
        struct.pack_into(">IIII", buf, record, offset_units, 0, size, 0)

        name_record = names_offset + i * 41
        struct.pack_into(">H", buf, name_record, folder_index)
        name_bytes = name.encode("utf-8")[:38]
        buf[name_record + 2 : name_record + 2 + len(name_bytes)] = name_bytes

    for i, folder in enumerate(folders):
        raw = folder.encode("utf-8")[:39]
        buf[folder_offset + i * 40 : folder_offset + i * 40 + len(raw)] = raw

    for offset, data in payloads:
        buf[offset : offset + len(data)] = data

    return bytes(buf)
