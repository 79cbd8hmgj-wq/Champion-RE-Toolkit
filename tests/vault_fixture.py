"""Build a minimal, entirely synthetic AttribSys .vlt/.bin pair for tests.

Not derived from any real Fight-Night-Legacy vault payload — hand-built to
match the byte layout documented in Fight-Night-Legacy's
tools/fn5_attrib_extract.py / tools/attrib_vault_inspect.py, with one class
("test_class") and one collection ("test_collection") exercising all three
value paths fncre.attrib.vault decodes: an inline scalar, a non-inline
scalar (BIN pointer), and a non-inline array.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from fncre.attrib.hash import attrib_hash
from fncre.attrib.vault import CLASS_LOAD_HASH, COLLECTION_LOAD_HASH

UINT32_HASH = attrib_hash("EA::Reflection::UInt32")
FLOAT_HASH = attrib_hash("EA::Reflection::Float")
UINT16_HASH = attrib_hash("EA::Reflection::UInt16")

CLASS_NAME = "test_class"
COLLECTION_NAME = "test_collection"
INLINE_FIELD_NAME = "inline_field"
SCALAR_FIELD_NAME = "scalar_field"
ARRAY_FIELD_NAME = "array_field"

CLASS_HASH = attrib_hash(CLASS_NAME)
COLLECTION_HASH = attrib_hash(COLLECTION_NAME)
INLINE_FIELD_HASH = attrib_hash(INLINE_FIELD_NAME)
SCALAR_FIELD_HASH = attrib_hash(SCALAR_FIELD_NAME)
ARRAY_FIELD_HASH = attrib_hash(ARRAY_FIELD_NAME)

INLINE_VALUE = 7
SCALAR_VALUE = 3.5
ARRAY_VALUES = [10, 20, 30]


def _chunk(tag: bytes, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return struct.pack(">4sI", tag, size) + payload


@dataclass(frozen=True)
class BuiltVault:
    vlt: bytes
    bin: bytes


def build_vault() -> BuiltVault:
    # --- BIN layout -----------------------------------------------------
    definitions = (
        struct.pack(">IIHHHBB", INLINE_FIELD_HASH, UINT32_HASH, 0, 4, 1, 0, 0)
        + struct.pack(">IIHHHBB", SCALAR_FIELD_HASH, FLOAT_HASH, 0, 4, 1, 0, 0)
        + struct.pack(">IIHHHBB", ARRAY_FIELD_HASH, UINT16_HASH, 0, 2, 4, 0x01, 1)
    )
    definitions_offset = 0
    scalar_value_offset = len(definitions)
    scalar_bytes = struct.pack(">f", SCALAR_VALUE)

    array_header_offset = scalar_value_offset + len(scalar_bytes)
    array_header = struct.pack(">HHHH", 4, len(ARRAY_VALUES), 2, 0)
    array_elements = b"".join(struct.pack(">H", v) for v in ARRAY_VALUES)

    bin_data = definitions + scalar_bytes + array_header + array_elements

    # --- VLT layout -------------------------------------------------------
    vers = _chunk(b"Vers", struct.pack(">II", 1, 0))
    depn = _chunk(b"DepN", struct.pack(">I", 2))  # dependency_count=2 (vlt=0, bin=1)

    running = len(vers) + len(depn)

    # ExpN and PtrN offsets/content depend on the DatN offset (for export
    # `offset` fields) and vice versa is not true, so compute DatN first
    # by reserving its position after ExpN+PtrN.
    class_record = struct.pack(
        ">IIIIIIIHH",
        CLASS_HASH,
        0,  # collection_reserve
        3,  # num_definitions
        0,  # definitions_pointer raw field (unused; real value via PtrN fixup)
        0,  # static_size
        0,  # static_pointer
        0,  # layout_size
        0,  # unknown
        0,  # num_base_fields
    )
    collection_record = struct.pack(
        ">IIIIIIHHI",
        COLLECTION_HASH,
        CLASS_HASH,  # collection_class
        0,  # parent
        0,  # reserve
        0,  # unknown
        3,  # num_entries
        0,  # num_types
        0,  # types_len
        0,  # layout_raw
    )

    # ExpN chunk: 2 exports (class, collection). Their `offset` fields point
    # into the DatN payload, computed below once we know where DatN starts.
    exp_n_size = 8 + 4 + 2 * 16
    ptr_n_placeholder_size = 8 + 3 * 12  # 3 fixup records, no terminator needed
    dat_n_offset = running + exp_n_size + ptr_n_placeholder_size

    class_offset = dat_n_offset + 8
    collection_offset = class_offset + len(class_record)
    entries_offset = collection_offset + len(collection_record)

    # An inline entry's "raw_pointer" 4 bytes ARE the value itself, not a
    # pointer — the record stays the standard 12 bytes.
    entry_inline = struct.pack(">II", INLINE_FIELD_HASH, INLINE_VALUE) + struct.pack(
        ">HBB", 0, 0x40, 0
    )
    entry_scalar_header = struct.pack(">IIHBB", SCALAR_FIELD_HASH, 0, 0, 0x00, 0)
    entry_array_header = struct.pack(">IIHBB", ARRAY_FIELD_HASH, 0, 0, 0x00, 0)

    entry_inline_offset = entries_offset
    entry_scalar_offset = entry_inline_offset + len(entry_inline)
    entry_array_offset = entry_scalar_offset + len(entry_scalar_header)

    dat_n_payload = (
        class_record
        + collection_record
        + entry_inline
        + entry_scalar_header
        + entry_array_header
    )
    dat_n = _chunk(b"DatN", dat_n_payload)

    exports_payload = struct.pack(">I", 2) + struct.pack(
        ">IIII", CLASS_HASH, CLASS_LOAD_HASH, len(class_record), class_offset
    ) + struct.pack(
        ">IIII", COLLECTION_HASH, COLLECTION_LOAD_HASH, len(collection_record), collection_offset
    )
    exp_n = _chunk(b"ExpN", exports_payload)
    assert len(exp_n) == exp_n_size

    fixups_payload = (
        # definitions_pointer fixup: source = class_offset+12, dep=1(BIN), dest=definitions_offset
        struct.pack(">IHHI", class_offset + 12, 3, 1, definitions_offset)
        # scalar_field value fixup: source = entry_scalar_offset+4
        + struct.pack(">IHHI", entry_scalar_offset + 4, 3, 1, scalar_value_offset)
        # array_field value fixup: source = entry_array_offset+4
        + struct.pack(">IHHI", entry_array_offset + 4, 3, 1, array_header_offset)
    )
    ptr_n = _chunk(b"PtrN", fixups_payload)
    assert len(ptr_n) == ptr_n_placeholder_size

    end_c = _chunk(b"EndC", b"")

    vlt = vers + depn + exp_n + ptr_n + dat_n + end_c
    assert dat_n_offset == len(vers) + len(depn) + len(exp_n) + len(ptr_n), (
        dat_n_offset,
        len(vers) + len(depn) + len(exp_n) + len(ptr_n),
    )

    return BuiltVault(vlt=vlt, bin=bin_data)
