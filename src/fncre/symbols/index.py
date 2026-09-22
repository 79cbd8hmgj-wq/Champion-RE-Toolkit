"""SQLite-backed, deterministic symbol index.

One `SymbolIndex` (one SQLite database) can hold symbols from multiple
"builds" (e.g. both fn5d and fn5z), keyed by a caller-chosen `build_id`
string, so the same database can back cross-build diffing later without a
schema change. Re-indexing a build replaces its rows so results stay
deterministic across repeated `map index` runs on an unchanged file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fncre.symbols.models import ParsedMap, Symbol, Visibility

_SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (
    build_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    module_name TEXT,
    timestamp_raw TEXT,
    preferred_load_address INTEGER,
    entry_point_segment INTEGER,
    entry_point_offset INTEGER,
    total_lines INTEGER,
    total_symbols INTEGER,
    public_count INTEGER,
    static_count INTEGER,
    function_count INTEGER,
    data_count INTEGER,
    unknown_kind_count INTEGER,
    duplicate_name_count INTEGER,
    duplicate_address_count INTEGER,
    unparsed_line_count INTEGER,
    segment_count INTEGER
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL REFERENCES builds(build_id) ON DELETE CASCADE,
    raw_name TEXT NOT NULL,
    name TEXT NOT NULL,
    demangled_name TEXT,
    demangled_signature TEXT,
    is_mangled INTEGER NOT NULL,
    address INTEGER,
    segment INTEGER,
    offset INTEGER,
    section TEXT,
    library TEXT,
    object_name TEXT,
    visibility TEXT NOT NULL,
    is_function INTEGER,
    is_internal INTEGER,
    raw_flags TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL,
    source_line INTEGER NOT NULL,
    namespace_path TEXT,
    leaf TEXT
);

CREATE INDEX IF NOT EXISTS idx_symbols_build_name ON symbols(build_id, name);
CREATE INDEX IF NOT EXISTS idx_symbols_build_address ON symbols(build_id, address);
CREATE INDEX IF NOT EXISTS idx_symbols_build_object ON symbols(build_id, object_name);
CREATE INDEX IF NOT EXISTS idx_symbols_build_library ON symbols(build_id, library);
CREATE INDEX IF NOT EXISTS idx_symbols_build_namespace ON symbols(build_id, namespace_path);
CREATE INDEX IF NOT EXISTS idx_symbols_build_visibility ON symbols(build_id, visibility);
"""

DEFAULT_DB_PATH = ".fncre/index.db"


@dataclass
class BuildSummary:
    build_id: str
    source_path: str
    module_name: str | None
    preferred_load_address: int | None
    entry_point_segment: int | None
    entry_point_offset: int | None
    total_symbols: int
    public_count: int
    static_count: int
    function_count: int
    data_count: int
    unknown_kind_count: int
    duplicate_name_count: int
    duplicate_address_count: int
    unparsed_line_count: int
    segment_count: int


class SymbolIndex:
    """Thin, explicit wrapper around a SQLite database of indexed symbols."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SymbolIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- ingestion -----------------------------------------------------

    def index_parsed_map(self, build_id: str, parsed: ParsedMap) -> BuildSummary:
        """Replace any existing data for `build_id` with `parsed`'s contents."""
        conn = self._conn
        with conn:
            conn.execute("DELETE FROM builds WHERE build_id = ?", (build_id,))
            conn.execute("DELETE FROM symbols WHERE build_id = ?", (build_id,))
            conn.execute(
                """
                INSERT INTO builds (
                    build_id, source_path, module_name, timestamp_raw,
                    preferred_load_address, entry_point_segment, entry_point_offset,
                    total_lines, total_symbols, public_count, static_count,
                    function_count, data_count, unknown_kind_count,
                    duplicate_name_count, duplicate_address_count,
                    unparsed_line_count, segment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    build_id,
                    parsed.source_path,
                    parsed.header.module_name,
                    parsed.header.timestamp_raw,
                    parsed.header.preferred_load_address,
                    parsed.header.entry_point_segment,
                    parsed.header.entry_point_offset,
                    parsed.stats.total_lines,
                    parsed.stats.total_symbols,
                    parsed.stats.public_count,
                    parsed.stats.static_count,
                    parsed.stats.function_count,
                    parsed.stats.data_count,
                    parsed.stats.unknown_kind_count,
                    parsed.stats.duplicate_name_count,
                    parsed.stats.duplicate_address_count,
                    parsed.stats.unparsed_line_count,
                    parsed.stats.segment_count,
                ),
            )
            conn.executemany(
                """
                INSERT INTO symbols (
                    build_id, raw_name, name, demangled_name, demangled_signature,
                    is_mangled,
                    address, segment, offset, section, library, object_name,
                    visibility, is_function, is_internal, raw_flags,
                    order_index, source_line, namespace_path, leaf
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        build_id,
                        sym.raw_name,
                        sym.name,
                        sym.demangled_name,
                        sym.demangled_signature,
                        int(sym.is_mangled),
                        sym.address,
                        sym.segment,
                        sym.offset,
                        sym.section,
                        sym.library,
                        sym.object_name,
                        sym.visibility,
                        None if sym.is_function is None else int(sym.is_function),
                        None if sym.is_internal is None else int(sym.is_internal),
                        sym.raw_flags,
                        sym.order_index,
                        sym.source_line,
                        sym.namespace_path,
                        sym.leaf,
                    )
                    for sym in parsed.symbols
                ),
            )
        return self.build_summary(build_id)  # type: ignore[return-value]

    # -- build metadata --------------------------------------------------

    def list_builds(self) -> list[str]:
        rows = self._conn.execute("SELECT build_id FROM builds ORDER BY build_id").fetchall()
        return [r["build_id"] for r in rows]

    def build_summary(self, build_id: str) -> BuildSummary | None:
        row = self._conn.execute(
            "SELECT * FROM builds WHERE build_id = ?", (build_id,)
        ).fetchone()
        if row is None:
            return None
        return BuildSummary(
            build_id=row["build_id"],
            source_path=row["source_path"],
            module_name=row["module_name"],
            preferred_load_address=row["preferred_load_address"],
            entry_point_segment=row["entry_point_segment"],
            entry_point_offset=row["entry_point_offset"],
            total_symbols=row["total_symbols"],
            public_count=row["public_count"],
            static_count=row["static_count"],
            function_count=row["function_count"],
            data_count=row["data_count"],
            unknown_kind_count=row["unknown_kind_count"],
            duplicate_name_count=row["duplicate_name_count"],
            duplicate_address_count=row["duplicate_address_count"],
            unparsed_line_count=row["unparsed_line_count"],
            segment_count=row["segment_count"],
        )

    # -- queries ---------------------------------------------------------

    def exact(self, build_id: str, name: str) -> list[Symbol]:
        """Exact lookup by raw (decorated) name OR demangled name.

        A query like ``?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ`` and
        ``LegacyModeLogic::FightSim::UpdateEnergy`` (once demangled) both
        resolve to the same row.
        """
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? "
            "AND (name = ? OR demangled_name = ?) ORDER BY order_index",
            (build_id, name, name),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def search(self, build_id: str, substring: str, limit: int = 200) -> list[Symbol]:
        """Substring search over both the raw name and the demangled name."""
        pattern = f"%{_escape_like(substring)}%"
        rows = self._conn.execute(
            """
            SELECT * FROM symbols
            WHERE build_id = ?
              AND (name LIKE ? ESCAPE '\\' OR demangled_name LIKE ? ESCAPE '\\')
            ORDER BY order_index LIMIT ?
            """,
            (build_id, pattern, pattern, limit),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def by_namespace(self, build_id: str, namespace: str, limit: int = 500) -> list[Symbol]:
        namespace = namespace.rstrip(":")
        rows = self._conn.execute(
            """
            SELECT * FROM symbols
            WHERE build_id = ? AND (namespace_path = ? OR namespace_path LIKE ? ESCAPE '\\')
            ORDER BY order_index LIMIT ?
            """,
            (build_id, namespace, f"{_escape_like(namespace)}::%", limit),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def by_address(self, build_id: str, address: int) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? AND address = ? ORDER BY order_index",
            (build_id, address),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def address_range(self, build_id: str, lo: int, hi: int) -> list[Symbol]:
        rows = self._conn.execute(
            """
            SELECT * FROM symbols
            WHERE build_id = ? AND address BETWEEN ? AND ?
            ORDER BY address
            """,
            (build_id, lo, hi),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def by_object(self, build_id: str, object_name: str) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? AND object_name = ? "
            "ORDER BY order_index",
            (build_id, object_name),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def by_library(self, build_id: str, library: str) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? AND library = ? ORDER BY order_index",
            (build_id, library),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def by_visibility(self, build_id: str, visibility: Visibility) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? AND visibility = ? "
            "ORDER BY order_index",
            (build_id, visibility),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def all_symbols(self, build_id: str) -> list[Symbol]:
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? ORDER BY order_index",
            (build_id,),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def function_symbols(self, build_id: str) -> list[Symbol]:
        """Symbols with the 'f' flag, sorted by address — the boundary set
        `fncre.analysis.function_slice` needs to infer a function's end."""
        rows = self._conn.execute(
            "SELECT * FROM symbols WHERE build_id = ? AND is_function = 1 "
            "AND address IS NOT NULL ORDER BY address",
            (build_id,),
        ).fetchall()
        return [_row_to_symbol(r) for r in rows]

    def nearest_before(self, build_id: str, address: int) -> Symbol | None:
        row = self._conn.execute(
            """
            SELECT * FROM symbols
            WHERE build_id = ? AND address IS NOT NULL AND address <= ?
            ORDER BY address DESC LIMIT 1
            """,
            (build_id, address),
        ).fetchone()
        return _row_to_symbol(row) if row else None

    def nearest_after(self, build_id: str, address: int) -> Symbol | None:
        row = self._conn.execute(
            """
            SELECT * FROM symbols
            WHERE build_id = ? AND address IS NOT NULL AND address >= ?
            ORDER BY address ASC LIMIT 1
            """,
            (build_id, address),
        ).fetchone()
        return _row_to_symbol(row) if row else None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_symbol(row: sqlite3.Row) -> Symbol:
    return Symbol(
        raw_name=row["raw_name"],
        name=row["name"],
        demangled_name=row["demangled_name"],
        demangled_signature=row["demangled_signature"],
        is_mangled=bool(row["is_mangled"]),
        address=row["address"],
        segment=row["segment"],
        offset=row["offset"],
        section=row["section"],
        library=row["library"],
        object_name=row["object_name"],
        visibility=row["visibility"],
        is_function=None if row["is_function"] is None else bool(row["is_function"]),
        is_internal=None if row["is_internal"] is None else bool(row["is_internal"]),
        raw_flags=row["raw_flags"],
        order_index=row["order_index"],
        source_line=row["source_line"],
        namespace_path=row["namespace_path"],
        leaf=row["leaf"],
    )


def iter_all_symbols(index: SymbolIndex, build_id: str) -> Iterable[Symbol]:
    """Convenience generator over every symbol in a build, address order."""
    rows = index._conn.execute(  # noqa: SLF001 - internal helper, same package
        "SELECT * FROM symbols WHERE build_id = ? ORDER BY order_index",
        (build_id,),
    ).fetchall()
    for row in rows:
        yield _row_to_symbol(row)
