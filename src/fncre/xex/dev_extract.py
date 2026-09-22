"""XEX2 raw-format-1 extraction (development-key path).

Ported and generalized from Fight-Night-Legacy's
`tools/extract_dev_xex.py` / `tools/xex2_raw_extract.py`, which are the
same algorithm: AES-ECB-unwrap the per-image session key with a 16-byte
master key, then AES-CBC-decrypt the raw/zero-fill block stream. Legacy's
two scripts differed only in whether the master key was hardcoded to the
all-zero Xbox 360 devkit key; here it is a parameter (`master_key`,
defaulting to the devkit key) so the same code serves any future build
that also happens to use a raw-format-1 XEX2 with a known 16-byte key.
This module does not contain, and has no path to derive, the Xbox retail
XEX key.

Only compression format 1 (raw blocks + zero-fill) is supported, matching
every real-format example documented in Fight-Night-Legacy's
docs/re/xex-extraction.md. A compressed XEX2 raises `XexExtractionError`
rather than silently producing wrong output.

Requires the optional `cryptography` dependency (`pip install fncre[xex]`).
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

DEVKIT_XEX_KEY = bytes(16)

_XEX_FILE_DATA_DESCRIPTOR_HEADER = 0x000003FF
_XEX_HEADER_ENTRY_POINT = 0x00010100
_XEX_HEADER_PE_BASE = 0x00010201
_XEX_HEADER_PE_MODULE_NAME = 0x000183FF


class XexExtractionError(ValueError):
    """Raised for any XEX2 input this extractor cannot handle."""


@dataclass(frozen=True)
class XexExtractionResult:
    pe_bytes: bytes
    module_flags: int
    header_size: int
    security_info_offset: int
    entry_point: int
    pe_base: int
    module_name: str
    pe_sha256: str


def _u32be(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _parse_directory(data: bytes, count: int, base_offset: int = 24) -> dict[int, int]:
    result: dict[int, int] = {}
    off = base_offset
    for _ in range(count):
        key, value = struct.unpack_from(">II", data, off)
        result[key] = value
        off += 8
    return result


def extract_xex2(data: bytes, *, master_key: bytes = DEVKIT_XEX_KEY) -> XexExtractionResult:
    """Decrypt+reconstruct a raw-format-1 XEX2's PE image.

    `master_key` unwraps the per-image session key via AES-ECB; it defaults
    to the all-zero Xbox 360 development-kit key. This function never
    guesses at a retail key.
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:  # pragma: no cover - exercised by import-guard tests
        raise XexExtractionError(
            "the 'cryptography' package is required for XEX extraction "
            "(pip install fncre[xex])"
        ) from exc

    if data[:4] != b"XEX2":
        raise XexExtractionError("only XEX2 is supported")
    if len(master_key) != 16:
        raise XexExtractionError("master key must be 16 bytes")

    _magic, module_flags, header_size, _discardable, security_info, count = struct.unpack_from(
        ">6I", data, 0
    )
    directory = _parse_directory(data, count)

    if _XEX_FILE_DATA_DESCRIPTOR_HEADER not in directory:
        raise XexExtractionError("XEX file-data descriptor is missing")
    descriptor_off = directory[_XEX_FILE_DATA_DESCRIPTOR_HEADER]
    descriptor_size, encryption, compression = struct.unpack_from(">IHH", data, descriptor_off)

    if compression != 1:
        raise XexExtractionError(
            f"expected raw/uncompressed XEX block format (1), got {compression}"
        )
    if encryption not in (0, 1):
        raise XexExtractionError(f"unsupported encryption flag: {encryption}")

    blocks: list[tuple[int, int]] = []
    off = descriptor_off + 8
    end = descriptor_off + descriptor_size
    while off < end:
        size, zero_size = struct.unpack_from(">II", data, off)
        blocks.append((size, zero_size))
        off += 8

    # XEX2HVImageInfo.ImageKey is 0x150 bytes from XEX2SecurityInfo start,
    # per Fight-Night-Legacy's confirmed FN5D layout.
    image_key = data[security_info + 0x150 : security_info + 0x160]
    if len(image_key) != 16:
        raise XexExtractionError("could not read XEX image key")

    ecb = Cipher(algorithms.AES(master_key), modes.ECB()).decryptor()
    session_key = ecb.update(image_key) + ecb.finalize()

    decryptor = Cipher(algorithms.AES(session_key), modes.CBC(bytes(16))).decryptor()

    output = bytearray()
    file_off = header_size
    for encrypted_size, zero_size in blocks:
        block = data[file_off : file_off + encrypted_size]
        if len(block) != encrypted_size:
            raise XexExtractionError("truncated XEX data block")
        file_off += encrypted_size

        if encryption == 1:
            if len(block) % 16:
                raise XexExtractionError("encrypted block is not AES-block aligned")
            output.extend(decryptor.update(block))
        else:
            output.extend(block)

        output.extend(bytes(zero_size))

    if encryption == 1:
        output.extend(decryptor.finalize())

    if output[:2] != b"MZ":
        raise XexExtractionError(
            "extracted image is not a PE image; this key may not match this XEX"
        )

    module_name = ""
    module_name_off = directory.get(_XEX_HEADER_PE_MODULE_NAME)
    if module_name_off is not None:
        size = _u32be(data, module_name_off)
        raw = data[module_name_off + 4 : module_name_off + size]
        module_name = raw.split(b"\0", 1)[0].decode("ascii", errors="replace")

    pe_bytes = bytes(output)
    return XexExtractionResult(
        pe_bytes=pe_bytes,
        module_flags=module_flags,
        header_size=header_size,
        security_info_offset=security_info,
        entry_point=directory.get(_XEX_HEADER_ENTRY_POINT, 0),
        pe_base=directory.get(_XEX_HEADER_PE_BASE, 0),
        module_name=module_name,
        pe_sha256=hashlib.sha256(pe_bytes).hexdigest(),
    )


def extract_xex2_file(
    path: str | Path, *, master_key: bytes = DEVKIT_XEX_KEY
) -> XexExtractionResult:
    return extract_xex2(Path(path).read_bytes(), master_key=master_key)
