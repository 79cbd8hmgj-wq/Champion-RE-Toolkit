"""Unified archive -> vault -> resolved-tunables extraction pipeline.

This is new in this toolkit: Fight-Night-Legacy's equivalent workflow is
five separately-invoked scripts (`ea_eb_extract.py` to pull the vault
members out of a BIG archive and undo chunkzip, `fn5_attrib_extract.py` to
walk the AttribSys records, `generated_attrib_keys.py`/`attrib_hash.py` to
resolve names by hand). `extract_tunables` runs that whole chain from one
call, auto-detecting which stages a given input needs, and always returns
provenance precise enough to trace a value back to the exact archive
member/vault chunk/record offset it came from (see `ExtractionProvenance`,
`PROVENANCE_SCHEMA_VERSION`).

This module never decides *what a value means* — see `ExtractedRecord`:
it carries a resolved key's text and confidence status if a key index
resolves it, and leaves it `None`/`"unresolved"` otherwise. Naming a field
"this is the jab damage tunable" is a Fight-Night-Legacy-side research
conclusion, not something this module infers.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from fncre import __version__ as TOOL_VERSION
from fncre.archive.big import ArchiveFormatError, parse_big, read_entry
from fncre.archive.chunkzip import decompress_chunkzip, is_chunkzip
from fncre.attrib.hash import attrib_hash
from fncre.attrib.keys import AttribKeyIndex
from fncre.attrib.values import ArrayValue, RawValue
from fncre.attrib.vault import (
    UnresolvedPointer,
    VaultFormatError,
    chunk_map,
    find_class_export,
    parse_class_definitions,
    parse_collection_entries,
    parse_collections,
    parse_exports,
    parse_fixups,
)

PROVENANCE_SCHEMA_VERSION = "1.0.0"

InputKind = Literal["archive", "vlt_bin"]

# Confidence ranking, strongest first — used to pick a representative match
# when a key index has multiple candidate texts for one hash (a collision).
_STATUS_RANK = {"evidenced": 0, "generated": 1, "inferred": 2, "unresolved": 3}


class PipelineError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ResolvedInput:
    vlt: bytes
    bin: bytes
    input_kind: InputKind
    archive_path: str | None
    archive_sha256: str | None
    archive_member_vlt: str | None
    archive_member_bin: str | None
    vlt_path: str | None
    bin_path: str | None


def resolve_input(
    input_path: str | Path,
    *,
    vlt_match: str = ".vlt",
    bin_match: str = ".bin",
    bin_path_override: str | Path | None = None,
) -> ResolvedInput:
    """Detect what kind of input this is and produce (vlt_bytes, bin_bytes).

    Supported today: a BIG archive containing exactly one member whose path
    contains `vlt_match` and one containing `bin_match` (chunkzip-decoded
    automatically), or a direct `.vlt` file paired with a `.bin` file
    (same stem by default, or `bin_path_override`). Anything else raises
    `PipelineError` — this never guesses at an unsupported input shape.
    """
    input_path = Path(input_path)
    data = input_path.read_bytes()

    if data[:4] == b"EB\x00\x03":
        try:
            archive = parse_big(data)
        except ArchiveFormatError as exc:
            raise PipelineError(f"{input_path}: not a readable BIG archive: {exc}") from exc

        vlt_candidates = [e for e in archive.entries if vlt_match.lower() in e.path.lower()]
        bin_candidates = [e for e in archive.entries if bin_match.lower() in e.path.lower()]
        if len(vlt_candidates) != 1:
            raise PipelineError(
                f"{input_path}: expected exactly one member matching {vlt_match!r}, "
                f"found {len(vlt_candidates)}"
            )
        if len(bin_candidates) != 1:
            raise PipelineError(
                f"{input_path}: expected exactly one member matching {bin_match!r}, "
                f"found {len(bin_candidates)}"
            )

        vlt_entry, bin_entry = vlt_candidates[0], bin_candidates[0]
        vlt_bytes = decompress_chunkzip(read_entry(data, vlt_entry))
        bin_bytes = decompress_chunkzip(read_entry(data, bin_entry))

        return ResolvedInput(
            vlt=vlt_bytes,
            bin=bin_bytes,
            input_kind="archive",
            archive_path=str(input_path),
            archive_sha256=_sha256(data),
            archive_member_vlt=vlt_entry.path,
            archive_member_bin=bin_entry.path,
            vlt_path=None,
            bin_path=None,
        )

    if input_path.suffix == ".vlt":
        bin_path = Path(bin_path_override) if bin_path_override else input_path.with_suffix(".bin")
        if not bin_path.exists():
            raise PipelineError(
                f"{input_path}: no matching .bin file at {bin_path} "
                "(pass bin_path_override if it lives elsewhere)"
            )
        bin_bytes = bin_path.read_bytes()
        vlt_bytes = data
        if is_chunkzip(vlt_bytes):
            vlt_bytes = decompress_chunkzip(vlt_bytes)
        if is_chunkzip(bin_bytes):
            bin_bytes = decompress_chunkzip(bin_bytes)

        return ResolvedInput(
            vlt=vlt_bytes,
            bin=bin_bytes,
            input_kind="vlt_bin",
            archive_path=None,
            archive_sha256=None,
            archive_member_vlt=None,
            archive_member_bin=None,
            vlt_path=str(input_path),
            bin_path=str(bin_path),
        )

    raise PipelineError(
        f"{input_path}: unrecognized input (not a BIG archive, not a .vlt file). "
        "Supported inputs: a BIG archive, or a .vlt with a matching .bin."
    )


@dataclass(frozen=True)
class ExtractedRecord:
    key_hash: int
    resolved_text: str | None
    resolution_status: str
    """One of 'evidenced'/'generated'/'inferred'/'unresolved' (from a key
    index match) or 'no_key_index' when no `AttribKeyIndex` was supplied."""
    export_offset: int
    record_offset: int
    type_hash: int | None
    type_name: str | None
    value: Any
    node_flags: int
    entry_flags: int

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["key_hash_hex"] = f"0x{self.key_hash:08X}"
        d["type_hash_hex"] = None if self.type_hash is None else f"0x{self.type_hash:08X}"
        d["value"] = _value_to_json(self.value)
        return d


def _value_to_json(value: Any) -> Any:
    if isinstance(value, RawValue):
        return {"raw_hex": value.hex, "type_name": value.type_name}
    if isinstance(value, ArrayValue):
        return {
            "values": [_value_to_json(v) for v in value.values],
            "capacity": value.capacity,
            "count": value.count,
        }
    if isinstance(value, UnresolvedPointer):
        return {"unresolved_pointer": True, "raw_pointer": value.raw_pointer}
    return value


@dataclass(frozen=True)
class ExtractionProvenance:
    schema_version: str
    tool_version: str
    build_id: str
    input_kind: InputKind
    archive_path: str | None
    archive_sha256: str | None
    archive_member_vlt: str | None
    archive_member_bin: str | None
    vlt_path: str | None
    bin_path: str | None
    vlt_sha256: str
    bin_sha256: str
    class_name: str
    class_hash: int
    collection_name: str
    collection_hash: int
    build_identity_status: str = "not_checked"

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["class_hash_hex"] = f"0x{self.class_hash:08X}"
        d["collection_hash_hex"] = f"0x{self.collection_hash:08X}"
        return d


@dataclass(frozen=True)
class ExtractionResult:
    provenance: ExtractionProvenance
    records: list[ExtractedRecord] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        return {
            "provenance": self.provenance.to_json_dict(),
            "records": [r.to_json_dict() for r in self.records],
        }


def _type_name(type_hash: int | None) -> str | None:
    if type_hash is None:
        return None
    from fncre.attrib.values import TYPE_HASH

    return TYPE_HASH.get(type_hash)


def extract_tunables(
    input_path: str | Path,
    *,
    build_id: str,
    class_name: str,
    collection_name: str,
    key_index: AttribKeyIndex | None = None,
    vlt_match: str = ".vlt",
    bin_match: str = ".bin",
    bin_path_override: str | Path | None = None,
    build_identity_status: str = "not_checked",
) -> ExtractionResult:
    """Run the full archive/vlt -> AttribSys record -> resolved-value chain.

    `class_name`/`collection_name` are plain text; this function hashes
    them itself (never trusts a pre-computed hash from the caller), so a
    typo in a name simply fails to find the export rather than silently
    reading the wrong record.
    """
    resolved = resolve_input(
        input_path, vlt_match=vlt_match, bin_match=bin_match, bin_path_override=bin_path_override
    )
    vlt, bin_data = resolved.vlt, resolved.bin

    try:
        cm = chunk_map(vlt)
        exports = parse_exports(vlt, cm[b"ExpN"])
        fixups = parse_fixups(vlt, cm[b"PtrN"])
    except (KeyError, VaultFormatError) as exc:
        raise PipelineError(f"{input_path}: not a readable AttribSys vault: {exc}") from exc

    class_hash = attrib_hash(class_name)
    collection_hash = attrib_hash(collection_name)

    class_export = find_class_export(exports, class_hash)
    class_record = parse_class_definitions(vlt, bin_data, class_export, fixups)

    collections = parse_collections(vlt, exports, class_hash)
    matching = [c for c in collections if c.key == collection_hash]
    if not matching:
        raise PipelineError(
            f"no collection {collection_name!r} (0x{collection_hash:08X}) "
            f"under class {class_name!r}"
        )
    collection = matching[0]

    entries = parse_collection_entries(vlt, bin_data, collection, class_record.definitions, fixups)

    records = []
    for entry in entries:
        resolved_text: str | None = None
        status = "no_key_index"
        if key_index is not None:
            matches = key_index.lookup(build_id, entry.key)
            if matches:
                best = min(matches, key=lambda k: _STATUS_RANK.get(k.status, 99))
                resolved_text = best.text
                status = best.status
            else:
                status = "unresolved"

        records.append(
            ExtractedRecord(
                key_hash=entry.key,
                resolved_text=resolved_text,
                resolution_status=status,
                export_offset=collection.offset,
                record_offset=entry.offset,
                type_hash=entry.type_hash,
                type_name=_type_name(entry.type_hash),
                value=entry.value,
                node_flags=entry.node_flags,
                entry_flags=entry.entry_flags,
            )
        )

    provenance = ExtractionProvenance(
        schema_version=PROVENANCE_SCHEMA_VERSION,
        tool_version=TOOL_VERSION,
        build_id=build_id,
        input_kind=resolved.input_kind,
        archive_path=resolved.archive_path,
        archive_sha256=resolved.archive_sha256,
        archive_member_vlt=resolved.archive_member_vlt,
        archive_member_bin=resolved.archive_member_bin,
        vlt_path=resolved.vlt_path,
        bin_path=resolved.bin_path,
        vlt_sha256=_sha256(vlt),
        bin_sha256=_sha256(bin_data),
        class_name=class_name,
        class_hash=class_hash,
        collection_name=collection_name,
        collection_hash=collection_hash,
        build_identity_status=build_identity_status,
    )

    return ExtractionResult(provenance=provenance, records=records)
