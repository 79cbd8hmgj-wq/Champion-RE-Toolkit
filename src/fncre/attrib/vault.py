"""EA AttribSys `.vlt`/`.bin` vault parsing.

Generalizes Fight-Night-Legacy's `tools/attrib_vault_inspect.py` (chunk
container parsing) and `tools/fn5_attrib_extract.py` (export/fixup/class/
collection record parsing) into reusable, class-name-agnostic mechanics.
Every struct offset and field order below is transcribed unchanged from
those two scripts — this module does not reinterpret the format, and it
does not hardcode Fight-Night-Legacy's `fe_legacy` class name or default
root-collection list anywhere; callers supply those.

Two generic AttribSys export-type hashes gate which exports are a "class"
record vs. a "collection" record — `Attrib::ClassLoadData` and
`Attrib::CollectionLoadData`. These are EA middleware type names, not
Champion-specific vocabulary.
"""

from __future__ import annotations

import struct
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fncre.attrib.hash import attrib_hash
from fncre.attrib.values import ArrayValue, RawValue, decode_array, decode_primitive

CLASS_LOAD_HASH = attrib_hash("Attrib::ClassLoadData")
COLLECTION_LOAD_HASH = attrib_hash("Attrib::CollectionLoadData")

KNOWN_CHUNK_TAGS: dict[bytes, str] = {
    b"DepN": "dependency metadata",
    b"EndC": "end marker",
    b"ExpN": "export metadata",
    b"PtrN": "pointer/fixup metadata",
    b"Sign": "secure-signature metadata",
    b"Vers": "version metadata",
}

# Fixup record ptr_type values, from Fight-Night-Legacy's parse_fixups.
PTR_END = 0
PTR_NULL = 1
PTR_SET_FIXUP_TARGET = 2
PTR_DEP_RELATIVE = 3

NODE_FLAG_IS_INLINE = 0x40
DEFINITION_FLAG_ARRAY = 0x01


class VaultFormatError(ValueError):
    """Raised for a `.vlt`/`.bin` structure this parser cannot make sense of.

    Never raised speculatively — only when a chunk/record genuinely
    violates the format's own invariants (overruns the file, etc).
    """


@dataclass(frozen=True)
class VaultChunk:
    offset: int
    tag: bytes
    size: int
    payload: bytes

    @property
    def name(self) -> str:
        try:
            return self.tag.decode("ascii")
        except UnicodeDecodeError:
            return self.tag.hex()

    @property
    def role(self) -> str:
        return KNOWN_CHUNK_TAGS.get(self.tag, "unknown")


def _u32be(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def iter_vault_chunks(data: bytes) -> Iterator[VaultChunk]:
    """Walk a `.vlt`'s top-level `{tag, size}` chunk stream.

    Stops after yielding the `EndC` chunk (bytes after it may be legitimate
    dependency/data payload, not another top-level chunk — matching
    Fight-Night-Legacy's own conservative stance on that trailing data).
    """
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise VaultFormatError(
                f"trailing {len(data) - offset} byte(s) at 0x{offset:X}; "
                "not enough for a chunk header"
            )

        tag = data[offset : offset + 4]
        size = _u32be(data, offset + 4)
        if size < 8:
            raise VaultFormatError(
                f"invalid chunk size 0x{size:X} at 0x{offset:X} ({tag!r}); expected >= 8"
            )

        end = offset + size
        if end > len(data):
            raise VaultFormatError(
                f"chunk {tag!r} at 0x{offset:X} overruns file: end=0x{end:X}, file=0x{len(data):X}"
            )

        yield VaultChunk(offset, tag, size, data[offset + 8 : end])

        offset = end
        if tag == b"EndC":
            return


def chunk_map(data: bytes) -> dict[bytes, VaultChunk]:
    """First occurrence of each chunk tag, keyed by raw tag bytes."""
    result: dict[bytes, VaultChunk] = {}
    for chunk in iter_vault_chunks(data):
        result.setdefault(chunk.tag, chunk)
    return result


# -- exports ------------------------------------------------------------


@dataclass(frozen=True)
class ExportRecord:
    """One `ExpN` export: (hash/key, type_hash, size, offset-into-vlt)."""

    key: int
    type_hash: int
    size: int
    offset: int


def parse_exports(vlt: bytes, exp_chunk: VaultChunk) -> list[ExportRecord]:
    if exp_chunk.tag != b"ExpN":
        raise VaultFormatError(f"expected an ExpN chunk, got {exp_chunk.tag!r}")
    base = exp_chunk.offset
    count = _u32be(vlt, base + 8)
    exports = []
    for i in range(count):
        key, type_hash, size, offset = struct.unpack_from(">IIII", vlt, base + 12 + i * 16)
        exports.append(ExportRecord(key, type_hash, size, offset))
    return exports


# -- fixups ---------------------------------------------------------------

FixupEntry = tuple[int, int, int]  # (dependency_index, destination, ptr_type)


def parse_fixups(vlt: bytes, ptr_chunk: VaultChunk) -> dict[int, dict[int, FixupEntry]]:
    """Parse the `PtrN` chunk into `{fixup_target: {source_offset: entry}}`.

    A `PtrSetFixupTarget` (ptr_type 2) record switches the active target;
    subsequent `Null`/`DepRelative` records (ptr_type 1/3) are filed under
    that target, keyed by their source offset within the vlt.
    """
    if ptr_chunk.tag != b"PtrN":
        raise VaultFormatError(f"expected a PtrN chunk, got {ptr_chunk.tag!r}")

    pos = ptr_chunk.offset + 8
    end = ptr_chunk.offset + ptr_chunk.size
    current_target = 0
    fixups: dict[int, dict[int, FixupEntry]] = defaultdict(dict)

    while pos + 12 <= end:
        source, ptr_type, index, destination = struct.unpack_from(">IHHI", vlt, pos)
        pos += 12

        if ptr_type == PTR_END:
            break
        if ptr_type == PTR_SET_FIXUP_TARGET:
            current_target = index
        elif ptr_type in (PTR_NULL, PTR_DEP_RELATIVE):
            fixups[current_target][source] = (index, destination, ptr_type)

    return dict(fixups)


# -- class / field definitions --------------------------------------------


@dataclass(frozen=True)
class FieldDefinition:
    key: int
    type_hash: int
    field_offset: int
    size: int
    max_count: int
    flags: int
    alignment: int

    @property
    def is_array(self) -> bool:
        return bool(self.flags & DEFINITION_FLAG_ARRAY)


@dataclass(frozen=True)
class ClassRecord:
    class_hash: int
    collection_reserve: int
    num_definitions: int
    definitions: dict[int, FieldDefinition]
    static_size: int
    static_pointer: int
    layout_size: int
    num_base_fields: int


def find_class_export(exports: list[ExportRecord], class_hash: int) -> ExportRecord:
    for export in exports:
        if export.key == class_hash and export.type_hash == CLASS_LOAD_HASH:
            return export
    raise VaultFormatError(f"no ClassLoadData export for class hash 0x{class_hash:08X}")

def parse_class_definitions(
    vlt: bytes,
    bin_data: bytes,
    class_export: ExportRecord,
    fixups: dict[int, dict[int, FixupEntry]],
) -> ClassRecord:
    offset = class_export.offset
    (
        class_hash,
        collection_reserve,
        num_definitions,
        _definitions_pointer,
        static_size,
        static_pointer,
        layout_size,
        _unknown,
        num_base_fields,
    ) = struct.unpack_from(">IIIIIIIHH", vlt, offset)

    definitions_fixup = fixups.get(0, {}).get(offset + 12)
    if not definitions_fixup or definitions_fixup[0] != 1:
        raise VaultFormatError("class definitions pointer does not resolve into the BIN dependency")
    definitions_offset = definitions_fixup[1]

    definitions: dict[int, FieldDefinition] = {}
    for i in range(num_definitions):
        key, type_hash, field_offset, size, max_count, flags, alignment_exp = struct.unpack_from(
            ">IIHHHBB", bin_data, definitions_offset + i * 16
        )
        definitions[key] = FieldDefinition(
            key=key,
            type_hash=type_hash,
            field_offset=field_offset,
            size=size,
            max_count=max_count,
            flags=flags,
            alignment=1 << alignment_exp,
        )

    return ClassRecord(
        class_hash=class_hash,
        collection_reserve=collection_reserve,
        num_definitions=num_definitions,
        definitions=definitions,
        static_size=static_size,
        static_pointer=static_pointer,
        layout_size=layout_size,
        num_base_fields=num_base_fields,
    )


# -- collections / entries -------------------------------------------------


@dataclass(frozen=True)
class CollectionRecord:
    key: int
    export_id: int
    offset: int
    size: int
    collection_class_hash: int
    parent: int
    reserve: int
    unknown: int
    num_entries: int
    num_types: int
    types_len: int
    layout_raw: int


def parse_collections(
    vlt: bytes, exports: list[ExportRecord], class_hash: int
) -> list[CollectionRecord]:
    """Every `CollectionLoadData` export belonging to `class_hash`."""
    collections = []
    for export in exports:
        if export.type_hash != COLLECTION_LOAD_HASH:
            continue
        offset = export.offset
        if offset + 32 > len(vlt):
            continue
        (
            key,
            collection_class,
            parent,
            reserve,
            unknown,
            num_entries,
            num_types,
            types_len,
            layout_pointer,
        ) = struct.unpack_from(">IIIIIIHHI", vlt, offset)
        if collection_class != class_hash:
            continue
        collections.append(
            CollectionRecord(
                key=key,
                export_id=export.key,
                offset=offset,
                size=export.size,
                collection_class_hash=collection_class,
                parent=parent,
                reserve=reserve,
                unknown=unknown,
                num_entries=num_entries,
                num_types=num_types,
                types_len=types_len,
                layout_raw=layout_pointer,
            )
        )
    return collections


@dataclass(frozen=True)
class UnresolvedPointer:
    """An entry whose value pointer didn't resolve through a known fixup."""

    raw_pointer: int
    fixup: FixupEntry | None


@dataclass(frozen=True)
class AttribEntry:
    key: int
    offset: int
    """Absolute byte offset of this entry's 12-byte record within the vlt."""
    type_hash: int | None
    type_index: int
    node_flags: int
    entry_flags: int
    value: Any  # int | float | RawValue | ArrayValue | UnresolvedPointer | None

    @property
    def is_inline(self) -> bool:
        return bool(self.node_flags & NODE_FLAG_IS_INLINE)


def collection_type_table(vlt: bytes, collection: CollectionRecord) -> list[int]:
    type_table = collection.offset + 32
    hashes = [
        struct.unpack_from(">I", vlt, type_table + i * 4)[0] for i in range(collection.types_len)
    ]
    return hashes[: collection.num_types]


def parse_collection_entries(
    vlt: bytes,
    bin_data: bytes,
    collection: CollectionRecord,
    definitions: dict[int, FieldDefinition],
    fixups: dict[int, dict[int, FixupEntry]],
) -> list[AttribEntry]:
    type_table = collection.offset + 32
    entries_offset = type_table + collection.types_len * 4
    dep_fixups = fixups.get(0, {})

    entries: list[AttribEntry] = []
    for i in range(collection.num_entries):
        entry_offset = entries_offset + i * 12
        key, raw_pointer, type_index, node_flags, entry_flags = struct.unpack_from(
            ">IIHBB", vlt, entry_offset
        )

        definition = definitions.get(key)
        value: Any = None

        if definition is not None:
            if node_flags & NODE_FLAG_IS_INLINE:
                value = decode_primitive(
                    vlt[entry_offset + 4 : entry_offset + 8],
                    size=definition.size,
                    type_name=_type_name(definition.type_hash),
                )
            else:
                fixup = dep_fixups.get(entry_offset + 4)
                if fixup and fixup[0] == 1:
                    destination = fixup[1]
                    if definition.is_array:
                        value = decode_array(
                            bin_data,
                            destination=destination,
                            element_size=definition.size,
                            element_type_name=_type_name(definition.type_hash),
                            alignment=definition.alignment,
                        )
                    else:
                        value = decode_primitive(
                            bin_data[destination : destination + definition.size],
                            size=definition.size,
                            type_name=_type_name(definition.type_hash),
                        )
                else:
                    value = UnresolvedPointer(raw_pointer=raw_pointer, fixup=fixup)

        entries.append(
            AttribEntry(
                key=key,
                offset=entry_offset,
                type_hash=definition.type_hash if definition else None,
                type_index=type_index,
                node_flags=node_flags,
                entry_flags=entry_flags,
                value=value,
            )
        )

    return entries


def _type_name(type_hash: int) -> str:
    from fncre.attrib.values import TYPE_HASH

    return TYPE_HASH.get(type_hash, f"0x{type_hash:08X}")


__all__ = [
    "AttribEntry",
    "ArrayValue",
    "ClassRecord",
    "CLASS_LOAD_HASH",
    "COLLECTION_LOAD_HASH",
    "CollectionRecord",
    "ExportRecord",
    "FieldDefinition",
    "FixupEntry",
    "RawValue",
    "UnresolvedPointer",
    "VaultChunk",
    "VaultFormatError",
    "chunk_map",
    "collection_type_table",
    "find_class_export",
    "iter_vault_chunks",
    "parse_class_definitions",
    "parse_collection_entries",
    "parse_collections",
    "parse_exports",
    "parse_fixups",
]
