"""Attribute-key/hash index: resolving an AttribSys hash back to text.

New in this toolkit (Fight-Night-Legacy has no equivalent database; its
`tools/generated_attrib_keys.py` only ever prints a CSV). Deliberately
keeps four distinct confidence levels rather than collapsing them:

    evidenced   the text is directly confirmed present in build evidence
                (e.g. a generated linker-map initializer symbol whose
                hash was independently checked against `attrib_hash`).
    generated   a candidate string produced by a systematic construction
                rule (a naming convention, a template expansion) but not
                yet confirmed present in any build artifact.
    inferred    a candidate reached by heuristic reasoning (context,
                proximity to known keys, naming-pattern guesswork) —
                weaker than `generated`.
    unresolved  only the raw hash is known; no candidate text at all.

A hash collision (two different texts hashing to the same 32-bit value) is
a real possibility with any 32-bit hash and is preserved, never resolved
by picking one arbitrarily — `lookup` always returns every row for a hash.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

KeyStatus = Literal["evidenced", "generated", "inferred", "unresolved"]
_VALID_STATUSES = ("evidenced", "generated", "inferred", "unresolved")

DEFAULT_DB_PATH = ".fncre/attrib_keys.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attrib_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL,
    hash INTEGER NOT NULL,
    text TEXT,
    status TEXT NOT NULL,
    source TEXT,
    provenance TEXT
);

CREATE INDEX IF NOT EXISTS idx_attrib_keys_build_hash ON attrib_keys(build_id, hash);
CREATE INDEX IF NOT EXISTS idx_attrib_keys_build_text ON attrib_keys(build_id, text);
CREATE INDEX IF NOT EXISTS idx_attrib_keys_build_status ON attrib_keys(build_id, status);
"""


@dataclass(frozen=True)
class AttribKey:
    hash: int
    text: str | None
    status: KeyStatus
    source: str | None
    provenance: str | None
    build_id: str


@dataclass(frozen=True)
class KeyStats:
    build_id: str
    total: int
    by_status: dict[str, int]
    distinct_hashes: int
    collisions: int
    """Distinct hashes with more than one distinct non-null text."""


class AttribKeyIndex:
    """SQLite-backed store of (hash, text, status, provenance) rows."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> AttribKeyIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add(
        self,
        build_id: str,
        *,
        hash_value: int,
        text: str | None,
        status: KeyStatus,
        source: str | None = None,
        provenance: str | None = None,
    ) -> bool:
        """Insert one row. Returns False (no-op) for an exact duplicate
        (same build/hash/text/source already present) rather than erroring."""
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; must be one of {_VALID_STATUSES}")
        if status != "unresolved" and text is None:
            raise ValueError(f"status {status!r} requires non-null text")
        if status == "unresolved" and text is not None:
            raise ValueError("status 'unresolved' must have text=None")

        # SQL UNIQUE constraints treat NULL as distinct from NULL, so a
        # nullable `source` (or `text`, for unresolved hashes) can't be
        # deduplicated by a UNIQUE index alone. Check explicitly with
        # NULL-safe `IS` instead.
        existing = self._conn.execute(
            "SELECT 1 FROM attrib_keys WHERE build_id = ? AND hash = ? "
            "AND text IS ? AND status = ? AND source IS ? LIMIT 1",
            (build_id, hash_value, text, status, source),
        ).fetchone()
        if existing:
            return False

        self._conn.execute(
            "INSERT INTO attrib_keys (build_id, hash, text, status, source, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (build_id, hash_value, text, status, source, provenance),
        )
        self._conn.commit()
        return True

    def add_many(
        self, build_id: str, rows: list[tuple[int, str | None, KeyStatus, str | None, str | None]]
    ) -> int:
        """Bulk `add`; returns the number of rows actually inserted (dupes skipped)."""
        inserted = 0
        for hash_value, text, status, source, provenance in rows:
            if self.add(
                build_id,
                hash_value=hash_value,
                text=text,
                status=status,
                source=source,
                provenance=provenance,
            ):
                inserted += 1
        return inserted

    def lookup(self, build_id: str, hash_value: int) -> list[AttribKey]:
        rows = self._conn.execute(
            "SELECT * FROM attrib_keys WHERE build_id = ? AND hash = ? ORDER BY status, id",
            (build_id, hash_value),
        ).fetchall()
        return [_row_to_key(r) for r in rows]

    def search(self, build_id: str, substring: str, limit: int = 200) -> list[AttribKey]:
        pattern = f"%{substring}%"
        rows = self._conn.execute(
            "SELECT * FROM attrib_keys WHERE build_id = ? AND text LIKE ? ORDER BY id LIMIT ?",
            (build_id, pattern, limit),
        ).fetchall()
        return [_row_to_key(r) for r in rows]

    def stats(self, build_id: str) -> KeyStats:
        total = self._conn.execute(
            "SELECT COUNT(*) FROM attrib_keys WHERE build_id = ?", (build_id,)
        ).fetchone()[0]

        by_status = dict.fromkeys(_VALID_STATUSES, 0)
        for row in self._conn.execute(
            "SELECT status, COUNT(*) c FROM attrib_keys WHERE build_id = ? GROUP BY status",
            (build_id,),
        ):
            by_status[row["status"]] = row["c"]

        distinct_hashes = self._conn.execute(
            "SELECT COUNT(DISTINCT hash) FROM attrib_keys WHERE build_id = ?", (build_id,)
        ).fetchone()[0]

        collisions = self._conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT hash FROM attrib_keys
                WHERE build_id = ? AND text IS NOT NULL
                GROUP BY hash HAVING COUNT(DISTINCT text) > 1
            )
            """,
            (build_id,),
        ).fetchone()[0]

        return KeyStats(
            build_id=build_id,
            total=total,
            by_status=by_status,
            distinct_hashes=distinct_hashes,
            collisions=collisions,
        )


def _row_to_key(row: sqlite3.Row) -> AttribKey:
    return AttribKey(
        hash=row["hash"],
        text=row["text"],
        status=row["status"],
        source=row["source"],
        provenance=row["provenance"],
        build_id=row["build_id"],
    )
