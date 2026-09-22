"""Round-trip test for fncre.xex.dev_extract against a synthetic XEX2 image.

Builds a minimal, entirely synthetic XEX2 container using the exact inverse
of the algorithm under test (AES-ECB-wrap a random session key with the
devkit master key, AES-CBC-encrypt a small fake PE payload), then verifies
extraction recovers the original bytes. No real XEX file is used or needed.
"""

from __future__ import annotations

import struct

import pytest

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402

from fncre.xex.dev_extract import DEVKIT_XEX_KEY, XexExtractionError, extract_xex2  # noqa: E402

XEX_FILE_DATA_DESCRIPTOR_HEADER = 0x000003FF
XEX_ENTRY_POINT = 0x00010100
XEX_PE_BASE = 0x00010201


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(data) + enc.finalize()


def _aes_cbc_encrypt(data: bytes, key: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return enc.update(data) + enc.finalize()


def _build_synthetic_xex2(plaintext_pe: bytes, *, master_key: bytes) -> bytes:
    assert len(plaintext_pe) % 16 == 0
    session_key = bytes(range(16))  # arbitrary, fixed for determinism
    image_key = _aes_ecb_encrypt(session_key, master_key)
    encrypted_block = _aes_cbc_encrypt(plaintext_pe, session_key)

    directory_entries = {
        XEX_FILE_DATA_DESCRIPTOR_HEADER: 0,  # filled in below
        XEX_ENTRY_POINT: 0x82000100,
        XEX_PE_BASE: 0x82000000,
    }
    directory_size = 24 + len(directory_entries) * 8
    security_info = (directory_size + 0xF) & ~0xF
    descriptor_off = security_info + 0x200  # room for the security-info struct + key
    directory_entries[XEX_FILE_DATA_DESCRIPTOR_HEADER] = descriptor_off

    data_start = descriptor_off + 8 + 8  # descriptor header(8) + one block entry(8)
    data_start = (data_start + 0xF) & ~0xF
    # Real XEX2 data blocks begin exactly at file offset `header_size`, so the
    # header (directory + security info + descriptor) must all fit before it.
    header_size = data_start
    total_size = data_start + len(encrypted_block)

    buf = bytearray(total_size)
    buf[0:4] = b"XEX2"
    struct.pack_into(">I", buf, 4, 1)  # module_flags
    struct.pack_into(">I", buf, 8, header_size)
    struct.pack_into(">I", buf, 12, 0)  # discardable
    struct.pack_into(">I", buf, 16, security_info)
    struct.pack_into(">I", buf, 20, len(directory_entries))

    off = 24
    for key, value in directory_entries.items():
        struct.pack_into(">II", buf, off, key, value)
        off += 8

    buf[security_info + 0x150 : security_info + 0x160] = image_key

    descriptor_size = 8 + 8
    # encryption=1, compression=1
    struct.pack_into(">IHH", buf, descriptor_off, descriptor_size, 1, 1)
    struct.pack_into(">II", buf, descriptor_off + 8, len(encrypted_block), 0)

    buf[data_start : data_start + len(encrypted_block)] = encrypted_block
    return bytes(buf)


def test_extract_xex2_round_trips_devkit_key():
    plaintext = b"MZ" + b"\0" * 14  # 16-byte aligned fake PE start
    xex_bytes = _build_synthetic_xex2(plaintext, master_key=DEVKIT_XEX_KEY)

    result = extract_xex2(xex_bytes, master_key=DEVKIT_XEX_KEY)

    assert result.pe_bytes == plaintext
    assert result.pe_sha256 == __import__("hashlib").sha256(plaintext).hexdigest()
    assert result.entry_point == 0x82000100
    assert result.pe_base == 0x82000000


def test_extract_xex2_wrong_master_key_fails_cleanly():
    plaintext = b"MZ" + b"\0" * 14
    xex_bytes = _build_synthetic_xex2(plaintext, master_key=DEVKIT_XEX_KEY)

    wrong_key = bytes([1] * 16)
    with pytest.raises(XexExtractionError):
        extract_xex2(xex_bytes, master_key=wrong_key)


def test_extract_xex2_rejects_non_xex2():
    with pytest.raises(XexExtractionError):
        extract_xex2(b"not an xex", master_key=DEVKIT_XEX_KEY)
