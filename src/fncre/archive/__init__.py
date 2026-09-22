"""EA BIG/EB archive extraction and chunkzip decompression.

Generalizes Fight-Night-Legacy's `tools/ea_eb_extract.py`. See
docs/legacy-compatibility.md and docs/resource-pipeline.md.
"""

from fncre.archive.big import (
    ArchiveFormatError,
    BigArchive,
    BigEntry,
    PathTraversalError,
    parse_big,
    read_entry,
    safe_extract_path,
)
from fncre.archive.chunkzip import ChunkzipError, decompress_chunkzip, is_chunkzip

__all__ = [
    "ArchiveFormatError",
    "BigArchive",
    "BigEntry",
    "ChunkzipError",
    "PathTraversalError",
    "decompress_chunkzip",
    "is_chunkzip",
    "parse_big",
    "read_entry",
    "safe_extract_path",
]
