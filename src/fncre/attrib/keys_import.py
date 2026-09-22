"""Parsers that turn external key sources into `AttribKeyIndex` rows.

Two formats are recognized:

- The CSV produced by Fight-Night-Legacy's `tools/generated_attrib_keys.py`
  (header `cpp_name,source_name,hash`): each row is a linker-map-confirmed
  generated initializer, so these import as `status="evidenced"`.
- A plain text file, one candidate key per line: the caller must say
  what confidence these candidates deserve (`generated` or `inferred`) —
  there is no way to infer that from a bare wordlist, so it is a required
  parameter rather than a silently-chosen default.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

from fncre.attrib.hash import attrib_hash

GeneratedKeyStatus = Literal["generated", "inferred"]


def parse_generated_keys_csv(path: str | Path) -> list[tuple[int, str, str, str]]:
    """Parse a `generated_attrib_keys.py`-format CSV.

    Returns a list of `(hash, source_name, cpp_name, provenance)` tuples.
    Re-hashes `source_name` itself (rather than trusting the file's own
    hash column) so an import can never silently propagate a stale or
    hand-edited hash value that no longer matches its text.
    """
    rows = []
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["cpp_name", "source_name", "hash"]:
            raise ValueError(
                f"{path}: expected header 'cpp_name,source_name,hash', "
                f"got {reader.fieldnames!r}"
            )
        for row in reader:
            source_name = row["source_name"]
            computed = attrib_hash(source_name)
            provenance = f"cpp identifier {row['cpp_name']!r} from {path}"
            file_hash = int(row["hash"], 0)
            if file_hash != computed:
                provenance += (
                    f"; WARNING file hash 0x{file_hash:08X} != recomputed 0x{computed:08X}"
                )
            rows.append((computed, source_name, row["cpp_name"], provenance))
    return rows


def parse_wordlist(path: str | Path) -> list[tuple[int, str]]:
    """One candidate key per line (blank lines and `#`-comments skipped).

    Returns `(hash, text)` pairs; the caller assigns a `GeneratedKeyStatus`.
    """
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            rows.append((attrib_hash(text), text))
    return rows
