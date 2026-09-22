"""Parser for Xenon (Xbox 360) MSVC-style linker MAP files.

The Xenon toolchain (used to build fn5d.xex / fn5z.xex) emits linker maps in
the same family of format as desktop MSVC link.exe: a header block, a
segment table ("Start Length Name Class"), one or more symbol tables
("Publics by Value", optionally "Publics by Name", optionally
"Static symbols"), and an entry point line.

This module is deliberately tolerant: any line inside a symbol section that
cannot be classified is recorded as a `ParseIssue` rather than dropped
silently, and the raw text of every recognized symbol is preserved verbatim
in `Symbol.raw_name` / alongside `Symbol.source_line` for provenance.

See docs/architecture.md for the state machine this parser implements and
docs/provenance.md for what "demangled" means in this toolkit's output.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

from fncre.symbols.models import (
    MapHeader,
    ParsedMap,
    ParseIssue,
    ParseStats,
    SegmentInfo,
    Symbol,
    Visibility,
)

_MODULE_NAME_RE = re.compile(r"^\s*(?P<name>\S+)\s*$")
_TIMESTAMP_RE = re.compile(r"^\s*Timestamp is\s+(?P<raw>.+?)\s*$", re.IGNORECASE)
_PREFERRED_LOAD_RE = re.compile(
    r"^\s*Preferred load address is\s+(?P<addr>[0-9A-Fa-f]+)\s*$", re.IGNORECASE
)
_SEGMENT_TABLE_HEADER_RE = re.compile(
    r"^\s*Start\s+Length\s+Name\s+Class\s*$", re.IGNORECASE
)
_SEGMENT_ROW_RE = re.compile(
    r"^\s*(?P<seg>[0-9A-Fa-f]{4}):(?P<off>[0-9A-Fa-f]{8})\s+"
    r"(?P<len>[0-9A-Fa-f]+)H\s+(?P<name>\S+)\s+(?P<cls>\S+)\s*$"
)
_PUBLICS_BY_VALUE_RE = re.compile(r"Publics by Value", re.IGNORECASE)
_PUBLICS_BY_NAME_RE = re.compile(r"Publics by Name", re.IGNORECASE)
_STATIC_SYMBOLS_RE = re.compile(r"^\s*Static symbols\s*$", re.IGNORECASE)
_SYMBOL_TABLE_COLUMN_HEADER_RE = re.compile(
    r"^\s*Address\s+.*Lib:Object\s*$", re.IGNORECASE
)
_ENTRY_POINT_RE = re.compile(
    r"^\s*entry point at\s+(?P<seg>[0-9A-Fa-f]{4}):(?P<off>[0-9A-Fa-f]{8})",
    re.IGNORECASE,
)
_SYMBOL_ROW_RE = re.compile(
    r"^\s*(?P<seg>[0-9A-Fa-f]{4}):(?P<off>[0-9A-Fa-f]{8})\s+"
    r"(?P<name>\S+)\s+"
    r"(?P<addr>[0-9A-Fa-f]{8})"
    r"(?P<flags>(?:\s+[fi])*)"
    r"(?:\s+(?P<libobj>\S+))?"
    r"\s*$"
)

_STATE_HEADER = "header"
_STATE_SEGMENTS = "segments"
_STATE_PUBLICS = "publics"
_STATE_PUBLICS_BY_NAME = "publics_by_name"
_STATE_STATICS = "statics"
_STATE_TRAILER = "trailer"


def parse_map_file(path: str | Path) -> ParsedMap:
    """Parse a MAP file from disk.

    Tries UTF-8 first, then falls back to cp1252 (common for MSVC-toolchain
    output), then latin-1 as a last resort so no file is rejected outright
    for encoding reasons.
    """
    path = Path(path)
    raw_bytes = path.read_bytes()
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 never fails to decode
        text = raw_bytes.decode("latin-1", errors="replace")
    return parse_map_text(text, source_path=str(path))


def parse_map_text(text: str, source_path: str = "<string>") -> ParsedMap:
    """Parse MAP file content already loaded into memory."""
    header = MapHeader()
    segments: list[SegmentInfo] = []
    symbols: list[Symbol] = []
    issues: list[ParseIssue] = []

    state = _STATE_HEADER
    order_index = 0
    module_name_candidate: str | None = None

    lines = text.splitlines()
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n\r")
        stripped = line.strip()

        if not stripped:
            continue

        if _SEGMENT_TABLE_HEADER_RE.match(line):
            state = _STATE_SEGMENTS
            continue
        if _PUBLICS_BY_NAME_RE.search(line):
            # Duplicate listing of the same symbols sorted by name instead of
            # address. Skipped to avoid double-counting; see docs/provenance.md.
            state = _STATE_PUBLICS_BY_NAME
            continue
        if _PUBLICS_BY_VALUE_RE.search(line):
            state = _STATE_PUBLICS
            continue
        if _STATIC_SYMBOLS_RE.match(line):
            state = _STATE_STATICS
            continue
        if _ENTRY_POINT_RE.match(line):
            match = _ENTRY_POINT_RE.match(line)
            assert match is not None
            header = _with_entry_point(header, match)
            state = _STATE_TRAILER
            continue
        if _SYMBOL_TABLE_COLUMN_HEADER_RE.match(line):
            continue  # column header repeated per-section; not data

        if state == _STATE_HEADER:
            header, module_name_candidate = _try_parse_header_line(
                line, header, module_name_candidate
            )
            continue

        if state == _STATE_SEGMENTS:
            seg_match = _SEGMENT_ROW_RE.match(line)
            if seg_match:
                segments.append(
                    SegmentInfo(
                        segment=int(seg_match.group("seg"), 16),
                        start_offset=int(seg_match.group("off"), 16),
                        length=int(seg_match.group("len"), 16),
                        name=seg_match.group("name"),
                        section_class=seg_match.group("cls"),
                        source_line=lineno,
                    )
                )
            else:
                issues.append(
                    ParseIssue(lineno, raw_line, "unrecognized segment-table line")
                )
            continue

        if state in (_STATE_PUBLICS, _STATE_STATICS):
            visibility: Visibility = "public" if state == _STATE_PUBLICS else "static"
            sym_match = _SYMBOL_ROW_RE.match(line)
            if sym_match:
                symbols.append(
                    _build_symbol(sym_match, visibility, order_index, lineno)
                )
                order_index += 1
            else:
                issues.append(
                    ParseIssue(lineno, raw_line, f"unrecognized {visibility} symbol line")
                )
            continue

        # _STATE_PUBLICS_BY_NAME and _STATE_TRAILER: intentionally ignored.

    section_by_number = {seg.segment: seg.name for seg in segments}
    symbols = [_attach_section(sym, section_by_number) for sym in symbols]

    stats = _compute_stats(len(lines), segments, symbols, issues)

    return ParsedMap(
        header=header,
        segments=segments,
        symbols=symbols,
        issues=issues,
        stats=stats,
        source_path=source_path,
    )


def _try_parse_header_line(
    line: str, header: MapHeader, module_name_candidate: str | None
) -> tuple[MapHeader, str | None]:
    ts_match = _TIMESTAMP_RE.match(line)
    if ts_match:
        return (
            MapHeader(
                module_name=header.module_name or module_name_candidate,
                timestamp_raw=ts_match.group("raw"),
                preferred_load_address=header.preferred_load_address,
                entry_point_segment=header.entry_point_segment,
                entry_point_offset=header.entry_point_offset,
            ),
            module_name_candidate,
        )
    load_match = _PREFERRED_LOAD_RE.match(line)
    if load_match:
        return (
            MapHeader(
                module_name=header.module_name or module_name_candidate,
                timestamp_raw=header.timestamp_raw,
                preferred_load_address=int(load_match.group("addr"), 16),
                entry_point_segment=header.entry_point_segment,
                entry_point_offset=header.entry_point_offset,
            ),
            module_name_candidate,
        )
    if header.module_name is None and module_name_candidate is None:
        name_match = _MODULE_NAME_RE.match(line)
        if name_match:
            module_name_candidate = name_match.group("name")
    return header, module_name_candidate


def _with_entry_point(header: MapHeader, match: re.Match[str]) -> MapHeader:
    return MapHeader(
        module_name=header.module_name,
        timestamp_raw=header.timestamp_raw,
        preferred_load_address=header.preferred_load_address,
        entry_point_segment=int(match.group("seg"), 16),
        entry_point_offset=int(match.group("off"), 16),
    )


def _build_symbol(
    match: re.Match[str], visibility: Visibility, order_index: int, lineno: int
) -> Symbol:
    # The name column is a single non-whitespace token (\S+): real FN5D/FN5Z
    # MAP files carry MSVC-decorated names here, which never contain spaces.
    # See docs/provenance.md for how this was confirmed against
    # Fight-Night-Legacy's own map_symbols.py and evidence CSVs.
    raw_name = match.group("name")
    name = raw_name
    is_mangled = raw_name.startswith("?")
    # This module never invents a demangled form; fncre.symbols.demangle
    # fills this in as a separate, optional pass over a ParsedMap.
    demangled_name = None if is_mangled else name

    namespace_path: str | None = None
    leaf: str | None = None
    if not is_mangled and "::" in name:
        namespace_path, _, leaf = name.rpartition("::")
        if not namespace_path:
            namespace_path = None

    libobj = match.group("libobj")
    library: str | None = None
    object_name: str | None = None
    if libobj:
        if ":" in libobj:
            library, _, object_name = libobj.partition(":")
        else:
            object_name = libobj

    # The flags column is zero or more space-separated single-letter flags
    # (observed: 'f' function, 'i' — meaning not yet confirmed by Legacy's
    # own research either; see docs/provenance.md). Both may appear together
    # ("f i"). Absence of a letter means "unknown", never "False".
    raw_flags = " ".join(match.group("flags").split())
    flag_letters = set(raw_flags.split())
    is_function: bool | None = True if "f" in flag_letters else None
    is_internal: bool | None = True if "i" in flag_letters else None

    return Symbol(
        raw_name=raw_name,
        name=name,
        demangled_name=demangled_name,
        is_mangled=is_mangled,
        address=int(match.group("addr"), 16),
        segment=int(match.group("seg"), 16),
        offset=int(match.group("off"), 16),
        section=None,
        library=library,
        object_name=object_name,
        visibility=visibility,
        is_function=is_function,
        is_internal=is_internal,
        raw_flags=raw_flags,
        order_index=order_index,
        source_line=lineno,
        namespace_path=namespace_path,
        leaf=leaf,
    )


def _attach_section(symbol: Symbol, section_by_number: dict[int, str]) -> Symbol:
    if symbol.segment is None:
        return symbol
    section = section_by_number.get(symbol.segment)
    if section is None:
        return symbol
    return replace(symbol, section=section)


def _compute_stats(
    total_lines: int,
    segments: list[SegmentInfo],
    symbols: list[Symbol],
    issues: list[ParseIssue],
) -> ParseStats:
    name_counts = Counter(sym.name for sym in symbols)
    addr_counts = Counter(sym.address for sym in symbols if sym.address is not None)

    return ParseStats(
        total_lines=total_lines,
        total_symbols=len(symbols),
        public_count=sum(1 for s in symbols if s.visibility == "public"),
        static_count=sum(1 for s in symbols if s.visibility == "static"),
        function_count=sum(1 for s in symbols if s.is_function is True),
        data_count=sum(1 for s in symbols if s.is_function is False),
        unknown_kind_count=sum(1 for s in symbols if s.is_function is None),
        duplicate_name_count=sum(1 for c in name_counts.values() if c > 1),
        duplicate_address_count=sum(1 for c in addr_counts.values() if c > 1),
        unparsed_line_count=len(issues),
        segment_count=len(segments),
    )
