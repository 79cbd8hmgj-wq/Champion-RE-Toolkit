"""Optional MSVC C++ name demangling for decorated (mangled) MAP symbols.

Backend: the third-party `undname` PyPI package (cffi bindings around a
mature reimplementation of Microsoft's UnDecorateSymbolName/LLVM's
microsoftDemangle). fncre does not implement its own MSVC demangler.

Why `undname` and not a homebrew demangler: MSVC name mangling covers
templates, calling conventions, cv-qualifiers, overload sets, operator
names, and RTTI/vtable symbols. A partial homebrew implementation would
either silently mis-demangle uncommon forms or need to special-case most of
that grammar anyway. `undname` was verified in this project against real
FN5D symbol forms pulled from Fight-Night-Legacy's own evidence/test
fixtures (see tests/test_demangle.py), including plain member functions,
constructors/destructors, and multi-argument functions with pointer/struct
parameters — all resolved correctly, e.g.:

    ?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ
      -> public: void __cdecl LegacyModeLogic::FightSim::UpdateEnergy(void)

This module never raises on a symbol it can't demangle: demangling is a
best-effort enrichment pass over an already-parsed `ParsedMap`/`Symbol`, and
failures are represented as `DemangleResult(success=False, ...)` so the
original symbol is always preserved unchanged (see `demangle_symbol`).

The `undname` dependency is optional (`pip install fncre[demangle]`). When
it isn't installed, `is_available()` returns False and every symbol simply
keeps `demangled_name=None` — the toolkit degrades gracefully rather than
failing to index a MAP file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from fncre.symbols.models import ParsedMap, Symbol

try:
    import undname as _undname
except ImportError:  # pragma: no cover - exercised via is_available() tests
    _undname = None

_CALLING_CONVENTION_RE = re.compile(
    r"__(?:cdecl|stdcall|thiscall|fastcall|vectorcall)\b\s*\*?\s*"
)
_QUALIFIED_NAME_RE = re.compile(r"^[A-Za-z_~][\w:~<>,\*&\[\] ]*$")


@dataclass(frozen=True)
class DemangleResult:
    """Outcome of attempting to demangle one decorated name."""

    raw_name: str
    success: bool
    demangled: str | None
    """Full undname-formatted signature (return type, calling convention, params)."""
    qualified_name: str | None
    """Best-effort extracted 'Namespace::Class::member' with no signature noise."""
    error: str | None


def is_available() -> bool:
    """Whether the `undname` backend is importable in this environment."""
    return _undname is not None


def demangle_msvc_name(raw_name: str) -> DemangleResult:
    """Attempt to demangle one MSVC-decorated name.

    Always returns a `DemangleResult`; never raises. A name that doesn't
    start with '?' is not a decorated name in the first place and is
    reported as a no-op failure (callers should check `Symbol.is_mangled`
    before calling this, as `demangle_symbol` does).
    """
    if not raw_name.startswith("?"):
        return DemangleResult(raw_name, False, None, None, "not a decorated name")
    if _undname is None:
        return DemangleResult(raw_name, False, None, None, "undname backend not installed")

    try:
        demangled = _undname.undname(raw_name)
    except _undname.UndnameFailure as exc:
        return DemangleResult(raw_name, False, None, None, str(exc))
    except Exception as exc:  # pragma: no cover - defensive: never crash indexing
        return DemangleResult(raw_name, False, None, None, f"{type(exc).__name__}: {exc}")

    if demangled == raw_name:
        # undname's failure mode for genuinely unparseable-but-'?'-prefixed
        # input is to raise; an unchanged echo means it silently declined.
        return DemangleResult(raw_name, False, None, None, "undname returned input unchanged")

    return DemangleResult(
        raw_name,
        True,
        demangled,
        _extract_qualified_name(demangled),
        None,
    )


def _extract_qualified_name(demangled: str) -> str | None:
    """Best-effort strip of a demangled signature down to its qualified name.

    E.g. "public: void __cdecl LegacyModeLogic::FightSim::UpdateEnergy(void)"
    -> "LegacyModeLogic::FightSim::UpdateEnergy".

    This is a heuristic over undname's formatted text, not a structured
    parse: it handles ordinary member functions, constructors/destructors,
    and static functions, but is not guaranteed for every declaration form
    (e.g. vtables, RTTI, operator overloads, data members without a calling
    convention keyword). Returns None rather than a wrong answer when the
    result doesn't look like a plausible qualified name.
    """
    match = _CALLING_CONVENTION_RE.search(demangled)
    if match:
        candidate = demangled[match.end():]
        paren = candidate.find("(")
        if paren != -1:
            candidate = candidate[:paren]
        candidate = candidate.strip()
    else:
        # No calling-convention keyword: typically a plain data symbol, e.g.
        # "int g_fightSimVersion" or "class Foo * const g_ptr". The
        # qualified name is the declarator, which is the last whitespace-
        # separated token (return type/qualifiers always precede it).
        tokens = demangled.split()
        candidate = tokens[-1].lstrip("*&") if tokens else ""

    if not candidate or not _QUALIFIED_NAME_RE.match(candidate):
        return None
    return candidate


def demangle_symbol(symbol: Symbol) -> Symbol:
    """Return `symbol` with `demangled_name`/`namespace_path`/`leaf` filled in.

    No-op for a symbol that isn't mangled, and a safe no-op (returns the
    original symbol unchanged) whenever demangling fails or the backend is
    unavailable — the symbol itself is never dropped or altered otherwise.
    """
    if not symbol.is_mangled:
        return symbol

    result = demangle_msvc_name(symbol.raw_name)
    if not result.success:
        return symbol

    namespace_path = symbol.namespace_path
    leaf = symbol.leaf
    if result.qualified_name and "::" in result.qualified_name:
        namespace_path, _, leaf = result.qualified_name.rpartition("::")
        namespace_path = namespace_path or None
    elif result.qualified_name:
        namespace_path = None
        leaf = result.qualified_name

    return replace(
        symbol,
        demangled_name=result.qualified_name,
        demangled_signature=result.demangled,
        namespace_path=namespace_path,
        leaf=leaf,
    )


def demangle_parsed_map(parsed: ParsedMap) -> ParsedMap:
    """Return a copy of `parsed` with every mangled symbol demangled (best-effort)."""
    return replace(parsed, symbols=[demangle_symbol(sym) for sym in parsed.symbols])
