from __future__ import annotations

import pytest

from fncre.archive.big import (
    ArchiveFormatError,
    PathTraversalError,
    parse_big,
    read_entry,
    safe_extract_path,
)
from tests.big_fixture import FileSpec, build_big


def test_parse_big_reads_entries_and_folders():
    data = build_big(
        [
            FileSpec("data/xenon/database/attrib", "attribdb.vlt", b"vlt-bytes-here"),
            FileSpec("data/xenon/database/attrib", "attribdb.bin", b"bin-bytes"),
            FileSpec("", "toplevel.txt", b"root file"),
        ]
    )
    archive = parse_big(data)

    assert archive.count == 3
    assert archive.folder_count == 2  # the two distinct folders
    paths = {e.path for e in archive.entries}
    assert paths == {
        "data/xenon/database/attrib/attribdb.vlt",
        "data/xenon/database/attrib/attribdb.bin",
        "toplevel.txt",
    }


def test_read_entry_recovers_exact_bytes():
    data = build_big([FileSpec("folder", "file.bin", b"exact payload bytes")])
    archive = parse_big(data)
    entry = archive.entries[0]
    assert read_entry(data, entry) == b"exact payload bytes"


def test_parse_big_rejects_bad_magic():
    with pytest.raises(ArchiveFormatError):
        parse_big(b"NOTBIG\x00\x00" + b"\x00" * 40)


def test_parse_big_rejects_size_mismatch():
    data = bytearray(build_big([FileSpec("f", "n.bin", b"x" * 20)]))
    data[28:32] = (len(data) + 100).to_bytes(4, "big")  # lie about archive_size
    with pytest.raises(ArchiveFormatError):
        parse_big(bytes(data))


def test_read_entry_detects_truncated_archive():
    data = build_big([FileSpec("f", "n.bin", b"payload")])
    archive = parse_big(data)
    entry = archive.entries[0]
    truncated = data[: entry.offset + 2]  # cut off mid-payload
    with pytest.raises(ArchiveFormatError):
        read_entry(truncated, entry)


def test_safe_extract_path_accepts_normal_entries(tmp_path):
    data = build_big([FileSpec("sub/dir", "file.bin", b"x")])
    archive = parse_big(data)
    entry = archive.entries[0]

    resolved = safe_extract_path(tmp_path, entry)
    assert resolved == (tmp_path / "sub" / "dir" / "file.bin").resolve()


def test_safe_extract_path_rejects_traversal(tmp_path):
    data = build_big([FileSpec("../../etc", "passwd", b"x")])
    archive = parse_big(data)
    entry = archive.entries[0]

    with pytest.raises(PathTraversalError):
        safe_extract_path(tmp_path, entry)


def test_safe_extract_path_rejects_traversal_via_filename(tmp_path):
    data = build_big([FileSpec("", "../../escape.bin", b"x")])
    archive = parse_big(data)
    entry = archive.entries[0]

    with pytest.raises(PathTraversalError):
        safe_extract_path(tmp_path, entry)
