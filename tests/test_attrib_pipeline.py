"""End-to-end pipeline tests: archive -> vault -> resolved records.

Exercises the full chain the task describes as currently five manual
scripts in Fight-Night-Legacy, using the same synthetic vault fixture as
tests/test_attrib_vault.py, packed into a synthetic BIG archive (with and
without chunkzip wrapping) and a direct .vlt/.bin pair.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from fncre.attrib.hash import attrib_hash
from fncre.attrib.keys import AttribKeyIndex
from fncre.attrib.pipeline import PipelineError, extract_tunables, resolve_input
from tests.big_fixture import FileSpec, build_big
from tests.vault_fixture import (
    ARRAY_FIELD_NAME,
    ARRAY_VALUES,
    CLASS_NAME,
    COLLECTION_NAME,
    INLINE_FIELD_NAME,
    INLINE_VALUE,
    SCALAR_FIELD_NAME,
    SCALAR_VALUE,
    build_vault,
)


def _chunkzip_wrap(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = compressor.compress(data) + compressor.flush()
    header = struct.pack(">8I", 2, len(data), 0, 1, 0, 0, 0, 0)
    out = bytearray(b"chunkzip" + header)
    assert len(out) % 16 == 8
    out.extend(struct.pack(">II", len(compressed), 1))
    if len(out) % 16:
        out.extend(b"\x00" * ((-len(out)) % 16))
    out.extend(compressed)
    return bytes(out)


def test_resolve_input_from_direct_vlt_bin(tmp_path):
    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    bin_path = tmp_path / "attribdb.bin"
    vlt_path.write_bytes(built.vlt)
    bin_path.write_bytes(built.bin)

    resolved = resolve_input(vlt_path)
    assert resolved.input_kind == "vlt_bin"
    assert resolved.vlt == built.vlt
    assert resolved.bin == built.bin


def test_resolve_input_from_archive_with_chunkzip(tmp_path):
    built = build_vault()
    archive = build_big(
        [
            FileSpec("data/attrib", "attribdb.vlt", _chunkzip_wrap(built.vlt)),
            FileSpec("data/attrib", "attribdb.bin", _chunkzip_wrap(built.bin)),
        ]
    )
    archive_path = tmp_path / "boot_other.big"
    archive_path.write_bytes(archive)

    resolved = resolve_input(archive_path)
    assert resolved.input_kind == "archive"
    assert resolved.vlt == built.vlt
    assert resolved.bin == built.bin
    assert resolved.archive_member_vlt == "data/attrib/attribdb.vlt"


def test_resolve_input_rejects_unsupported_file(tmp_path):
    path = tmp_path / "random.bin"
    path.write_bytes(b"not a big archive or a vlt")
    with pytest.raises(PipelineError):
        resolve_input(path)


def test_extract_tunables_end_to_end_without_key_index(tmp_path):
    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    (tmp_path / "attribdb.bin").write_bytes(built.bin)
    vlt_path.write_bytes(built.vlt)

    result = extract_tunables(
        vlt_path,
        build_id="fn5d",
        class_name=CLASS_NAME,
        collection_name=COLLECTION_NAME,
    )

    assert result.provenance.schema_version
    assert result.provenance.vlt_sha256
    assert result.provenance.class_name == CLASS_NAME
    assert len(result.records) == 3
    assert all(r.resolution_status == "no_key_index" for r in result.records)

    inline_record = next(r for r in result.records if r.value == INLINE_VALUE)
    assert inline_record.key_hash == attrib_hash(INLINE_FIELD_NAME)


def test_extract_tunables_resolves_names_via_key_index(tmp_path):
    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    (tmp_path / "attribdb.bin").write_bytes(built.bin)
    vlt_path.write_bytes(built.vlt)

    key_index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        key_index.add(
            "fn5d",
            hash_value=attrib_hash(INLINE_FIELD_NAME),
            text=INLINE_FIELD_NAME,
            status="evidenced",
        )
        key_index.add(
            "fn5d",
            hash_value=attrib_hash(SCALAR_FIELD_NAME),
            text=SCALAR_FIELD_NAME,
            status="generated",
        )
        # array_field is deliberately left unresolved.

        result = extract_tunables(
            vlt_path,
            build_id="fn5d",
            class_name=CLASS_NAME,
            collection_name=COLLECTION_NAME,
            key_index=key_index,
        )
    finally:
        key_index.close()

    by_text = {r.resolved_text: r for r in result.records if r.resolved_text}
    assert by_text[INLINE_FIELD_NAME].resolution_status == "evidenced"
    assert by_text[SCALAR_FIELD_NAME].resolution_status == "generated"
    assert by_text[SCALAR_FIELD_NAME].value == pytest.approx(SCALAR_VALUE)

    unresolved = [r for r in result.records if r.resolved_text is None]
    assert len(unresolved) == 1
    assert unresolved[0].resolution_status == "unresolved"
    assert unresolved[0].key_hash == attrib_hash(ARRAY_FIELD_NAME)


def test_extract_tunables_json_roundtrip_is_serializable(tmp_path):
    import json

    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    (tmp_path / "attribdb.bin").write_bytes(built.bin)
    vlt_path.write_bytes(built.vlt)

    result = extract_tunables(
        vlt_path, build_id="fn5d", class_name=CLASS_NAME, collection_name=COLLECTION_NAME
    )
    payload = json.dumps(result.to_json_dict(), indent=2)
    reloaded = json.loads(payload)

    assert reloaded["provenance"]["class_name"] == CLASS_NAME
    array_records = [
        r
        for r in reloaded["records"]
        if isinstance(r["value"], dict) and "values" in r["value"]
    ]
    assert len(array_records) == 1
    assert array_records[0]["value"]["values"] == ARRAY_VALUES


def test_extract_tunables_unknown_collection_raises(tmp_path):
    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    (tmp_path / "attribdb.bin").write_bytes(built.bin)
    vlt_path.write_bytes(built.vlt)

    with pytest.raises(PipelineError):
        extract_tunables(
            vlt_path, build_id="fn5d", class_name=CLASS_NAME, collection_name="does_not_exist"
        )
