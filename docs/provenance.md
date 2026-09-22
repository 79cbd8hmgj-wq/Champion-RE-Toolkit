# Provenance and evidence philosophy

This toolkit exists to turn proprietary build artifacts *you already have
a legal copy of* into structured, queryable, re-checkable evidence for the
downstream research project ([Fight-Night-Legacy][fnl]). That framing
drives every decision below.

[fnl]: https://github.com/79cbd8hmgj-wq/Fight-Night-Legacy

## No game files, ever

Nothing under this repository's version control is, contains, or is
derived from copyrighted Fight Night Champion assets: no `.xex`, `.map`,
`.pdb`, `.xdb`, `BIG`/`AST` archive, or extracted proprietary data. This is
enforced two ways: a `.gitignore` covering the known extensions as a
backstop, and, more importantly, a hard rule for contributors (human or
AI): don't add them, don't add fixtures "derived from" them beyond the
smallest textual fragment needed to test a format detail, and don't paste
their contents into issues, commits, or docs. `tests/fixtures/` contains
only hand-authored synthetic files, clearly labeled as such in a header
comment, and named with a `.map.txt` extension specifically so they are
never mistaken for (or accidentally gitignored as) a real MAP file.

## What "recover the demangled name" means here

Phase 1 of this toolkit described recovering "the demangled C++ name as
represented in the MAP" and deliberately did **not** implement an MSVC
name-demangling algorithm — at the time, no real FN5D/FN5Z MAP was
available to confirm whether names even needed demangling (see the
resolved-ambiguities note above: it turned out they do, almost always).

Phase 2 adds `fncre.symbols.demangle`, a real demangling pass — but still
not a homebrew one. **Backend: the `undname` PyPI package** (cffi bindings
around a mature reimplementation of Microsoft's `UnDecorateSymbolName` /
LLVM's `microsoftDemangle`). MSVC name mangling covers templates, calling
conventions, cv-qualifiers, overload sets, operator names, and RTTI/vtable
symbols; a partial homebrew implementation would either silently
mis-demangle uncommon forms or need to reimplement most of that grammar
anyway, and a wrong demangler is worse than none because it produces
confident-looking but false names. `undname` was verified in this project
against real FN5D symbol forms pulled from Fight-Night-Legacy's own
evidence/test fixtures (see `tests/test_demangle.py`), including member
functions, constructors/destructors, and multi-argument functions with
pointer/struct parameters — all resolved correctly.

`Symbol.demangled_name` reflects what's actually knowable:

- If `raw_name` does **not** start with `?` (i.e. it isn't in MSVC mangled
  form), it's treated as already human-readable, and `demangled_name` is
  set equal to it.
- If `raw_name` **does** start with `?`, demangling is opt-in and
  best-effort: `fncre map index` runs it by default (disable with
  `--no-demangle`), degrading gracefully to `demangled_name=None` when the
  optional `undname` dependency isn't installed or a given name can't be
  demangled. A symbol is never dropped because demangling failed.
  `demangled_name` holds the bare qualified name (e.g.
  `LegacyModeLogic::FightSim::UpdateEnergy`) so raw and demangled queries
  stay comparable; the full formatted signature (return type, calling
  convention, parameters) is kept separately in `demangled_signature`.
  `namespace_path`/`leaf` are re-derived from the demangled structure when
  available, via a best-effort heuristic over `undname`'s formatted output
  (documented in `fncre/symbols/demangle.py`) — not guaranteed for every
  declaration form (vtables, RTTI, operator overloads), but verified
  against every real FN5D form seen so far.

## Duplicate handling

Symbols are never deduplicated by name or by address. Real linker maps
legitimately contain:

- **Duplicate names** — e.g. an overload set, or the same symbol appearing
  once per translation unit before the linker folds COMDATs (if the MAP
  was captured pre-fold), or a static symbol shadowing a public one from a
  different object.
- **Duplicate addresses** — e.g. thunks, aliases, or multiple symbols
  folded to the same address by the linker/optimizer.

`SymbolIndex` keeps every row and reports `duplicate_name_count` /
`duplicate_address_count` as *counts of distinct names/addresses that
recur*, not as an error condition. Silently deduplicating would throw away
real information a researcher might need (e.g. "this address has two
names — which one does the disassembly actually reference?").

## The "Publics by Name" section

Some MSVC-family linkers emit the public symbol table twice: once sorted
by address (`Publics by Value`) and once sorted by name (`Publics by
Name`), containing the *same* symbols. This parser recognizes `Publics by
Name` and skips it entirely rather than parsing it as additional symbols,
specifically to avoid silently doubling every public symbol's count. This
is called out explicitly because it is an assumption, not a directly
verified fact about the real FN5D/FN5Z maps — see "Known ambiguities"
below.

## Resolved against Fight-Night-Legacy's real research corpus

Two of this document's original "known ambiguities" have since been
resolved by studying Fight-Night-Legacy's `research/fn5d-debug-legacy`
branch — its own MAP tooling (`tools/map_symbols.py`) and derived, non-
proprietary evidence (`evidence/fn5d/*_symbols.csv`) show the real format
directly:

- **Names are MSVC-decorated, not plain.** Real FN5D/FN5Z symbol names look
  like `?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ`, never
  `FightSim::UpdateEnergy` as literal MAP text — the plain form seen
  elsewhere is Fight-Night-Legacy's own human-readable research label, not
  what the linker actually emits. The parser's name column is therefore
  `\S+` (a single token; decorated names never contain spaces), and
  `fncre.symbols.demangle` (see below) is how a readable form gets
  produced, on top of the raw text, never instead of it.
- **The flags column supports `f` and `i`, singly or combined.**
  Confirmed directly from `map_symbols.py`'s own regex
  (`(?:\s+[fi])*`). `Symbol.is_function`/`is_internal`/`raw_flags` reflect
  this; an absent letter is `None` (unknown), never guessed `False`. The
  semantic meaning of `i` is still not documented anywhere in
  Fight-Night-Legacy's own research either — it's structurally exposed,
  not interpreted.

## Known ambiguities (not yet verified against a real FN5D/FN5Z MAP)

No real `fn5d.xenon.map` or `fn5z.xenon.map` was available in the
environment this toolkit was built in (see `docs/architecture.md` and the
project's validation report for how this was confirmed). Everything below
is a documented assumption based on the standard MSVC/Xenon linker MAP
format, not something confirmed against real output. **Run `fncre map
parse` against your own copy of the real MAP and compare the reported
stats and `--include-issues` output before trusting this toolkit's results
for research.**

Specific open questions:

1. **`Lib:Object` format.** Assumed to be `library:object.obj`, falling
   back to a bare object name with no library when there's no `:`. Real
   Xenon maps may use different separators, omit the library for some
   entries, or use synthetic markers like `<internal>` — the parser
   doesn't special-case those beyond "no colon means no library."
2. **Section resolution.** `Symbol.section` is resolved by looking up the
   symbol's segment number in the "Start Length Name Class" table parsed
   earlier in the same file. If a real MAP's segment table uses a
   different header string or column layout, this silently produces
   `section = None` rather than a wrong section — but that failure mode is
   itself unverified against a real file.
3. **`i` flag semantics.** Confirmed to exist and to combine with `f`
   (see above), but what it means is not documented anywhere yet — treat
   `Symbol.is_internal` as "the linker marked this with 'i'", not as any
   particular claim about internal linkage.
4. **Entry point address.** The MAP's `entry point at SEG:OFF` line is
   captured as `(segment, offset)`, not resolved to an absolute address —
   doing that correctly requires knowing each segment's own base within
   the loaded image, which this phase doesn't attempt. Cross-reference a
   symbol at that `segment:offset` instead if you need the absolute
   address.

## Validation status

See the project's Phase 1 completion report (in the pull request
description) for exact test results. In summary: the parser and index are
covered by tests against small, hand-authored synthetic fixtures that
match the *documented* format, including the publicly known FN5D
`FightSim`/`RankingFormula` symbol-name-to-address anchors listed in the
task description. **No test in this repository runs against a real FN5D
or FN5Z MAP file** — none was available in the build environment. That
means: the parser's *shape* has been exercised, but its *fitness for the
real files* has not been confirmed. Treat Phase 1 as "ready to validate
against your own files," not "validated."
