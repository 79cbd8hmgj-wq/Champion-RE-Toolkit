"""Cross-build (e.g. FN5D vs FN5Z) symbol and function comparison.

Formalizes what Fight-Night-Legacy's `docs/re/fn5d-fn5z-comparison.md` and
`evidence/fn5z/*.json` currently do by hand: this module produces facts
(symbol matched, address moved, instruction differs, function absent in one
build) — never research conclusions ("this is a gameplay bug", "this path
is semantically equivalent"). Those conclusions belong in
Fight-Night-Legacy, informed by this module's output; see
docs/provenance.md's evidence/conclusion separation.
"""

from fncre.diff.function_diff import FunctionDiffResult, classify_function_diff
from fncre.diff.symbol_diff import SymbolDiffEntry, SymbolDiffReport, compare_symbols

__all__ = [
    "FunctionDiffResult",
    "classify_function_diff",
    "SymbolDiffEntry",
    "SymbolDiffReport",
    "compare_symbols",
]
