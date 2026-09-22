"""Symbol-level cross-build comparison.

Matches symbols between two builds by raw (decorated) name — MSVC name
mangling does not embed addresses, so a function's decorated name is
stable across a relink/optimization pass as long as its signature is
unchanged; Fight-Night-Legacy's own fn5d-fn5z-comparison.md matches
functions this same way (by qualified name, not address). A name present
in only one build is itself a fact worth surfacing (a build-exclusive
symbol, or a signature/mangling change), not an error.

Per the task's own instruction: a different address alone is never treated
as a meaningful implementation change — `address_moved` is reported as a
plain fact alongside the match, not a severity flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fncre.symbols.models import Symbol

MatchStatus = Literal["both", "only_a", "only_b"]


def _inferred_size(symbols_sorted_by_address: list[Symbol], index: int) -> int | None:
    start = symbols_sorted_by_address[index].address
    if start is None:
        return None
    for later in symbols_sorted_by_address[index + 1 :]:
        if later.address is not None and later.address > start:
            return later.address - start
    return None


@dataclass(frozen=True)
class SymbolDiffEntry:
    raw_name: str
    status: MatchStatus
    symbol_a: Symbol | None
    symbol_b: Symbol | None
    address_moved: bool = False
    inferred_size_a: int | None = None
    inferred_size_b: int | None = None
    size_changed: bool | None = None  # None when either size couldn't be inferred
    object_changed: bool = False
    library_changed: bool = False
    visibility_changed: bool = False


@dataclass(frozen=True)
class SymbolDiffReport:
    only_in_a: tuple[SymbolDiffEntry, ...]
    only_in_b: tuple[SymbolDiffEntry, ...]
    in_both: tuple[SymbolDiffEntry, ...] = field(default_factory=tuple)

    @property
    def all_entries(self) -> tuple[SymbolDiffEntry, ...]:
        return self.only_in_a + self.only_in_b + self.in_both


def compare_symbols(symbols_a: list[Symbol], symbols_b: list[Symbol]) -> SymbolDiffReport:
    """Compare two builds' symbol lists (as from one build's parsed/indexed MAP)."""
    sorted_a = sorted((s for s in symbols_a if s.address is not None), key=lambda s: s.address)  # type: ignore[arg-type,return-value]
    sorted_b = sorted((s for s in symbols_b if s.address is not None), key=lambda s: s.address)  # type: ignore[arg-type,return-value]
    index_a = {s.raw_name: i for i, s in enumerate(sorted_a)}
    index_b = {s.raw_name: i for i, s in enumerate(sorted_b)}

    only_a: list[SymbolDiffEntry] = []
    only_b: list[SymbolDiffEntry] = []
    both: list[SymbolDiffEntry] = []

    for name, i in index_a.items():
        sym_a = sorted_a[i]
        if name not in index_b:
            only_a.append(SymbolDiffEntry(name, "only_a", sym_a, None))
            continue
        j = index_b[name]
        sym_b = sorted_b[j]

        size_a = _inferred_size(sorted_a, i)
        size_b = _inferred_size(sorted_b, j)
        size_changed = None if size_a is None or size_b is None else size_a != size_b

        both.append(
            SymbolDiffEntry(
                raw_name=name,
                status="both",
                symbol_a=sym_a,
                symbol_b=sym_b,
                address_moved=sym_a.address != sym_b.address,
                inferred_size_a=size_a,
                inferred_size_b=size_b,
                size_changed=size_changed,
                object_changed=sym_a.object_name != sym_b.object_name,
                library_changed=sym_a.library != sym_b.library,
                visibility_changed=sym_a.visibility != sym_b.visibility,
            )
        )

    for name, j in index_b.items():
        if name not in index_a:
            only_b.append(SymbolDiffEntry(name, "only_b", None, sorted_b[j]))

    return SymbolDiffReport(
        only_in_a=tuple(only_a), only_in_b=tuple(only_b), in_both=tuple(both)
    )
