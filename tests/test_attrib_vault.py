from __future__ import annotations

import struct

import pytest

from fncre.attrib.values import ArrayValue
from fncre.attrib.vault import (
    VaultFormatError,
    chunk_map,
    find_class_export,
    iter_vault_chunks,
    parse_class_definitions,
    parse_collection_entries,
    parse_collections,
    parse_exports,
    parse_fixups,
)
from tests.vault_fixture import (
    ARRAY_VALUES,
    CLASS_HASH,
    COLLECTION_HASH,
    INLINE_VALUE,
    SCALAR_VALUE,
    build_vault,
)


def _load():
    built = build_vault()
    return built.vlt, built.bin


def test_iter_vault_chunks_walks_full_stream():
    vlt, _bin = _load()
    chunks = list(iter_vault_chunks(vlt))
    assert [c.name for c in chunks] == ["Vers", "DepN", "ExpN", "PtrN", "DatN", "EndC"]
    assert chunks[-1].tag == b"EndC"


def test_iter_vault_chunks_rejects_truncated_header():
    with pytest.raises(VaultFormatError):
        list(iter_vault_chunks(b"Vers\x00\x00"))  # only 6 bytes, need 8


def test_iter_vault_chunks_rejects_overrunning_chunk():
    bad = struct.pack(">4sI", b"Vers", 0xFF) + b"\x00" * 4  # claims far more than present
    with pytest.raises(VaultFormatError):
        list(iter_vault_chunks(bad))


def test_iter_vault_chunks_rejects_size_below_header():
    bad = struct.pack(">4sI", b"Vers", 4)  # size < 8 is invalid
    with pytest.raises(VaultFormatError):
        list(iter_vault_chunks(bad))


def test_chunk_map_and_parse_exports():
    vlt, _bin = _load()
    cm = chunk_map(vlt)
    exports = parse_exports(vlt, cm[b"ExpN"])
    assert len(exports) == 2
    keys = {e.key for e in exports}
    assert keys == {CLASS_HASH, COLLECTION_HASH}


def test_parse_fixups_groups_by_target():
    vlt, _bin = _load()
    cm = chunk_map(vlt)
    fixups = parse_fixups(vlt, cm[b"PtrN"])
    assert set(fixups.keys()) == {0}
    assert len(fixups[0]) == 3


def test_full_class_and_collection_round_trip():
    vlt, bin_data = _load()
    cm = chunk_map(vlt)
    exports = parse_exports(vlt, cm[b"ExpN"])
    fixups = parse_fixups(vlt, cm[b"PtrN"])

    class_export = find_class_export(exports, CLASS_HASH)
    class_record = parse_class_definitions(vlt, bin_data, class_export, fixups)
    assert class_record.num_definitions == 3
    assert len(class_record.definitions) == 3

    collections = parse_collections(vlt, exports, CLASS_HASH)
    assert len(collections) == 1
    assert collections[0].key == COLLECTION_HASH

    entries = parse_collection_entries(
        vlt, bin_data, collections[0], class_record.definitions, fixups
    )
    assert len(entries) == 3

    by_key = {e.key: e for e in entries}
    inline_entry = next(e for e in entries if e.is_inline)
    assert inline_entry.value == INLINE_VALUE

    scalar_entries = [e for e in entries if not e.is_inline and isinstance(e.value, float)]
    assert scalar_entries[0].value == pytest.approx(SCALAR_VALUE)

    array_entries = [e for e in entries if isinstance(e.value, ArrayValue)]
    assert len(array_entries) == 1
    assert array_entries[0].value.values == ARRAY_VALUES
    assert array_entries[0].value.count == len(ARRAY_VALUES)
    assert by_key  # keeps the dict referenced for clarity


def test_find_class_export_raises_for_unknown_hash():
    vlt, _bin = _load()
    cm = chunk_map(vlt)
    exports = parse_exports(vlt, cm[b"ExpN"])
    with pytest.raises(VaultFormatError):
        find_class_export(exports, 0xDEADBEEF)


def test_parse_collections_filters_by_class_hash():
    vlt, _bin = _load()
    cm = chunk_map(vlt)
    exports = parse_exports(vlt, cm[b"ExpN"])
    assert parse_collections(vlt, exports, 0xDEADBEEF) == []
