"""Data model for symbols recovered from Xenon (Xbox 360) linker MAP files.

These types are intentionally toolchain-agnostic value objects: the parser
(`fncre.symbols.map_parser`) produces them, and the index
(`fncre.symbols.index`) persists and queries them. Nothing here reads files
or touches SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Visibility = Literal["public", "static"]


@dataclass(frozen=True)
class SegmentInfo:
    """One row of the linker's "Start Length Name Class" segment table."""

    segment: int
    """Segment number (e.g. 1 for '0001')."""
    start_offset: int
    """Offset within the segment (usually 0)."""
    length: int
    """Length in bytes."""
    name: str
    """Section name, e.g. '.text', '.rdata', '.pdata'."""
    section_class: str
    """Linker class, e.g. 'CODE', 'DATA'."""
    source_line: int


@dataclass(frozen=True)
class MapHeader:
    """Metadata parsed from the top of a MAP file, before the segment table."""

    module_name: str | None = None
    timestamp_raw: str | None = None
    preferred_load_address: int | None = None
    entry_point_segment: int | None = None
    entry_point_offset: int | None = None


@dataclass(frozen=True)
class Symbol:
    """A single symbol record recovered from a MAP file.

    Both the untouched source text (`raw_line`, `raw_name`) and normalized,
    searchable fields (`name`, `namespace_path`, `leaf`) are retained, so
    downstream consumers can always recover exactly what the linker emitted.
    """

    raw_name: str
    """Symbol name exactly as it appeared in the MAP, whitespace-trimmed only."""
    name: str
    """Normalized name used for lookups (collapses internal whitespace runs)."""
    demangled_name: str | None
    """The MAP's own human-readable form, if `raw_name` already looks undecorated.

    This toolkit does not implement its own C++ name demangler in this phase;
    it only surfaces what the MAP already represents (see docs/provenance.md).
    """
    is_mangled: bool
    """True if `raw_name` looks like an MSVC-decorated name (starts with '?')."""

    address: int | None
    """Absolute runtime address (Rva+Base), if the MAP provided one."""
    segment: int | None
    """Segment number from the 'segment:offset' column, if present."""
    offset: int | None
    """Offset within the segment, if present."""
    section: str | None
    """Section name resolved via the segment table (e.g. '.text'), if known."""

    library: str | None
    """Library name from the 'Lib:Object' column, if the entry had one."""
    object_name: str | None
    """Object file name from the 'Lib:Object' column."""

    visibility: Visibility
    """'public' or 'static', per which MAP section the symbol was listed under."""
    is_function: bool | None
    """True/False if the MAP's function flag ('f') let us tell; None if unknown."""

    order_index: int
    """0-based index in overall parse order (stable across public/static)."""
    source_line: int
    """1-based line number in the source MAP file, for provenance."""

    namespace_path: str | None = field(default=None)
    """Everything before the final '::' in `name`, e.g. 'FightSim'. None if flat."""
    leaf: str | None = field(default=None)
    """The final '::'-separated component of `name`, e.g. 'UpdateEnergy'."""


@dataclass
class ParseIssue:
    """A line the parser could not confidently classify."""

    source_line: int
    text: str
    reason: str


@dataclass
class ParseStats:
    """Summary counters for a parse run, used for validation reporting."""

    total_lines: int = 0
    total_symbols: int = 0
    public_count: int = 0
    static_count: int = 0
    function_count: int = 0
    data_count: int = 0
    unknown_kind_count: int = 0
    duplicate_name_count: int = 0
    """Number of distinct names that occur on more than one symbol record."""
    duplicate_address_count: int = 0
    """Number of distinct addresses that occur on more than one symbol record."""
    unparsed_line_count: int = 0
    segment_count: int = 0


@dataclass
class ParsedMap:
    """The full result of parsing one MAP file."""

    header: MapHeader
    segments: list[SegmentInfo]
    symbols: list[Symbol]
    issues: list[ParseIssue]
    stats: ParseStats
    source_path: str
