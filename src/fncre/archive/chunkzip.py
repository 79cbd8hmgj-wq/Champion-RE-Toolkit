"""EA "chunkzip" payload compression.

Ported unchanged in algorithm from Fight-Night-Legacy's
`tools/ea_eb_extract.py` (`decompress_chunkzip`). Chunkzip v2 support
covers exactly the chunk types observed in the FN5D boot archives:
type 1 (raw DEFLATE) and type 4 (uncompressed). No other chunk type is
guessed at — an unsupported type raises `ChunkzipError`.
"""

from __future__ import annotations

import struct
import zlib

_MAGIC = b"chunkzip"
_SUPPORTED_VERSION = 2
_CHUNK_TYPE_DEFLATE = 1
_CHUNK_TYPE_RAW = 4


class ChunkzipError(ValueError):
    pass


def is_chunkzip(data: bytes) -> bool:
    return data[:8] == _MAGIC


def decompress_chunkzip(data: bytes) -> bytes:
    """Decompress a chunkzip v2 payload; passes through unchanged data
    that isn't chunkzip-wrapped at all (matching the source tool's
    behavior of being safe to call unconditionally on any extracted
    archive member)."""
    if not is_chunkzip(data):
        return data

    version, full_size, _chunk_output_size, count, *_ = struct.unpack_from(">8I", data, 8)
    if version != _SUPPORTED_VERSION:
        raise ChunkzipError(f"unsupported chunkzip version {version}")

    pos = 40
    output = bytearray()

    for i in range(count):
        # Observed FN5D chunk headers begin at addresses congruent to 8 mod 16.
        if pos % 16 != 8:
            pos += (8 - pos) % 16

        if pos + 8 > len(data):
            raise ChunkzipError(f"truncated chunk header {i}")

        compressed_size, chunk_type = struct.unpack_from(">II", data, pos)
        pos += 8

        # Chunk data itself is 16-byte aligned.
        if pos % 16:
            pos += (-pos) % 16

        block = data[pos : pos + compressed_size]
        pos += compressed_size
        if len(block) != compressed_size:
            raise ChunkzipError(f"truncated chunk {i}")

        if chunk_type == _CHUNK_TYPE_DEFLATE:
            raw = zlib.decompress(block, -15)
        elif chunk_type == _CHUNK_TYPE_RAW:
            raw = block
        else:
            raise ChunkzipError(f"unsupported chunk type {chunk_type} at chunk {i}")

        output.extend(raw)

    if len(output) < full_size:
        raise ChunkzipError(f"decompressed {len(output)} bytes, expected {full_size}")

    return bytes(output[:full_size])
