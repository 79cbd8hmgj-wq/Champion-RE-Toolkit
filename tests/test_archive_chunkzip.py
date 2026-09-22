from __future__ import annotations

import struct
import zlib

import pytest

from fncre.archive.chunkzip import ChunkzipError, decompress_chunkzip, is_chunkzip


def _build_chunkzip(chunks: list[bytes], *, chunk_type: int = 1) -> bytes:
    """Build a minimal chunkzip v2 payload from a list of raw chunk contents."""
    full_size = sum(len(c) for c in chunks)
    header = struct.pack(">8I", 2, full_size, 0, len(chunks), 0, 0, 0, 0)
    payload_blocks = []
    for chunk in chunks:
        if chunk_type == 1:
            compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
            compressed = compressor.compress(chunk) + compressor.flush()
        else:
            compressed = chunk
        payload_blocks.append(compressed)

    out = bytearray(b"chunkzip" + header)
    for compressed in payload_blocks:
        if len(out) % 16 != 8:
            out.extend(b"\x00" * ((8 - len(out)) % 16))
        out.extend(struct.pack(">II", len(compressed), chunk_type))
        if len(out) % 16:
            out.extend(b"\x00" * ((-len(out)) % 16))
        out.extend(compressed)

    return bytes(out)


def test_is_chunkzip_detects_magic():
    assert is_chunkzip(b"chunkzip" + b"\x00" * 40) is True
    assert is_chunkzip(b"not chunkzip data") is False


def test_decompress_passthrough_for_non_chunkzip_data():
    data = b"just some raw bytes"
    assert decompress_chunkzip(data) == data


def test_decompress_deflate_chunk_type_1():
    payload = _build_chunkzip([b"hello world, this is chunk zero"], chunk_type=1)
    assert decompress_chunkzip(payload) == b"hello world, this is chunk zero"


def test_decompress_raw_chunk_type_4():
    payload = _build_chunkzip([b"raw uncompressed payload data"], chunk_type=4)
    assert decompress_chunkzip(payload) == b"raw uncompressed payload data"


def test_decompress_multiple_chunks_concatenates_in_order():
    payload = _build_chunkzip([b"first-chunk-", b"second-chunk"], chunk_type=4)
    assert decompress_chunkzip(payload) == b"first-chunk-second-chunk"


def test_unsupported_chunk_type_raises():
    payload = _build_chunkzip([b"data"], chunk_type=99)
    with pytest.raises(ChunkzipError):
        decompress_chunkzip(payload)


def test_unsupported_version_raises():
    header = struct.pack(">8I", 3, 4, 0, 1, 0, 0, 0, 0)
    with pytest.raises(ChunkzipError):
        decompress_chunkzip(b"chunkzip" + header + b"\x00" * 16)


def test_truncated_chunk_header_raises():
    with pytest.raises(ChunkzipError):
        decompress_chunkzip(b"chunkzip" + struct.pack(">8I", 2, 10, 0, 1, 0, 0, 0, 0))
