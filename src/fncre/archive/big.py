"""EA `EB\\0\\x03` BIG archive parsing.

Ported from Fight-Night-Legacy's `tools/ea_eb_extract.py` (`parse_big`,
`Entry`) unchanged in algorithm: big-endian metadata, 16-byte file records
from 0x30, 41-byte filename records, 40-byte fixed folder-name records,
16-byte-unit payload offsets.

One deliberate addition beyond the source script: `safe_extract_path`
rejects path traversal explicitly. `ea_eb_extract.py` joins an entry's
folder/name directly into the output directory with no such check: a
crafted or corrupted archive containing `../`-style folder/name fields
could write outside the requested output directory. This module refuses
to do that rather than reproducing the gap.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAGIC = b"EB\x00\x03"


class ArchiveFormatError(ValueError):
    pass


class PathTraversalError(ValueError):
    """Raised when an entry's path would extract outside the output directory."""


@dataclass(frozen=True)
class BigEntry:
    index: int
    folder_index: int
    folder: str
    name: str
    offset: int
    stored_size: int
    checksum: int

    @property
    def path(self) -> str:
        return str(PurePosixPath(self.folder) / self.name) if self.folder else self.name


@dataclass(frozen=True)
class BigArchive:
    entries: tuple[BigEntry, ...]
    count: int
    data_start: int
    names_offset: int
    folder_count: int
    archive_size: int


def _be32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def parse_big(data: bytes) -> BigArchive:
    if data[:4] != MAGIC:
        raise ArchiveFormatError(f"expected {MAGIC!r} archive magic, got {data[:4]!r}")
    if len(data) < 32:
        raise ArchiveFormatError("archive too small to contain a header")

    count = _be32(data, 4)
    data_start = _be32(data, 8)
    names_offset = _be32(data, 12)
    folder_count = struct.unpack_from(">H", data, 22)[0]
    archive_size = _be32(data, 28)

    if archive_size and archive_size != len(data):
        raise ArchiveFormatError(f"archive size header={archive_size}, actual={len(data)}")

    # The filename table uses 41-byte records. Folder records begin at the
    # next 16-byte boundary and are fixed 40-byte strings.
    folder_offset = (names_offset + count * 41 + 15) & ~15
    folders = []
    for i in range(folder_count):
        raw = data[folder_offset + i * 40 : folder_offset + (i + 1) * 40]
        folders.append(raw.split(b"\0", 1)[0].decode("utf-8", "replace"))

    entries = []
    for i in range(count):
        name_record = names_offset + i * 41
        folder_index = struct.unpack_from(">H", data, name_record)[0]
        name = (
            data[name_record + 2 : name_record + 41].split(b"\0", 1)[0].decode("utf-8", "replace")
        )

        record = 0x30 + i * 16
        offset_units, _unknown, stored_size, checksum = struct.unpack_from(">IIII", data, record)
        offset = offset_units * 16
        if folder_index < len(folders):
            folder = folders[folder_index]
        else:
            folder = f"__folder_{folder_index}"

        entries.append(
            BigEntry(
                index=i,
                folder_index=folder_index,
                folder=folder,
                name=name,
                offset=offset,
                stored_size=stored_size,
                checksum=checksum,
            )
        )

    return BigArchive(
        entries=tuple(entries),
        count=count,
        data_start=data_start,
        names_offset=names_offset,
        folder_count=folder_count,
        archive_size=archive_size,
    )


def read_entry(data: bytes, entry: BigEntry) -> bytes:
    raw = data[entry.offset : entry.offset + entry.stored_size]
    if len(raw) != entry.stored_size:
        raise ArchiveFormatError(
            f"entry {entry.path!r}: expected {entry.stored_size} bytes at "
            f"0x{entry.offset:X}, got {len(raw)} (archive truncated?)"
        )
    return raw


def safe_extract_path(output_dir: Path, entry: BigEntry) -> Path:
    """Resolve `entry`'s path under `output_dir`, refusing to escape it.

    Raises `PathTraversalError` for an absolute path or a `..` component
    that would land outside `output_dir`, rather than silently
    normalizing it or writing to the escaped location.
    """
    output_dir = output_dir.resolve()
    candidate = (output_dir / PurePosixPath(entry.path)).resolve()
    try:
        candidate.relative_to(output_dir)
    except ValueError as exc:
        raise PathTraversalError(
            f"entry {entry.path!r} would extract outside {output_dir}"
        ) from exc
    return candidate
