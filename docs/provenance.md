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

The task this toolkit was built for describes recovering "the demangled
C++ name as represented in the MAP." That phrasing is deliberate: this
phase does **not** implement an MSVC name-demangling algorithm. Xenon (like
desktop MSVC) mangles C++ names with a scheme starting in `?`; correctly
reversing that scheme (templates, calling conventions, cv-qualifiers,
overload sets) is a substantial, error-prone undertaking on its own and is
out of scope for a "trustworthy symbol engine" milestone — a wrong
demangler is worse than none, because it would produce confident-looking
but false names.

Instead, `Symbol.demangled_name` reflects only what the MAP file itself
already shows:

- If `raw_name` does **not** start with `?` (i.e. it isn't in MSVC mangled
  form), it's treated as already human-readable, and `demangled_name` is
  set equal to it (this covers cases like `FightSim::UpdateEnergy` where
  the toolchain's MAP output has already resolved the readable form).
- If `raw_name` **does** start with `?`, `is_mangled` is `True` and
  `demangled_name` is left `None`. `raw_name` is preserved so a real
  demangler (a later phase, or an external tool like `undname`/
  `msvc-demangler`) can be layered on top without re-parsing the MAP.

This is why the toolkit never invents a demangled name — it surfaces
exactly what's there and is explicit about what it doesn't know.

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

## Known ambiguities (not yet verified against a real FN5D/FN5Z MAP)

No real `fn5d.xenon.map` or `fn5z.xenon.map` was available in the
environment this toolkit was built in (see `docs/architecture.md` and the
project's validation report for how this was confirmed). Everything below
is a documented assumption based on the standard MSVC/Xenon linker MAP
format and the facts given in the task description, not something
confirmed against real output. **Run `fncre map parse` against your own
copy of the real MAP and compare the reported stats and `--include-issues`
output before trusting this toolkit's results for research.**

Specific open questions:

1. **Function/data flag.** The parser recognizes a trailing single-letter
   `f` flag as "this is a function." It's unconfirmed whether the real
   Xenon linker map uses exactly this flag, a different one, or omits it
   for some/all entries. When absent, `Symbol.is_function` is `None`
   (unknown), never guessed as `False`.
2. **Whether names are pre-demangled.** The task's example symbols
   (`FightSim::UpdateEnergy`, etc.) are already human-readable, which
   suggests the real MAP may show undecorated names for at least some
   symbols — but "many C++ names survive intact" (per the task) implies
   others may not. The parser handles both cases per-symbol (see above),
   but the real mix is unverified.
3. **`Lib:Object` format.** Assumed to be `library:object.obj`, falling
   back to a bare object name with no library when there's no `:`. Real
   Xenon maps may use different separators, omit the library for some
   entries, or use synthetic markers like `<internal>` — the parser
   doesn't special-case those beyond "no colon means no library."
4. **Section resolution.** `Symbol.section` is resolved by looking up the
   symbol's segment number in the "Start Length Name Class" table parsed
   earlier in the same file. If a real MAP's segment table uses a
   different header string or column layout, this silently produces
   `section = None` rather than a wrong section — but that failure mode is
   itself unverified against a real file.
5. **Symbol names containing an 8-hex-digit run.** The symbol-row regex
   finds the *address* column by looking for an 8-hex-digit token; a name
   containing spaces followed by something that happens to look like 8 hex
   digits (unlikely for C++ identifiers, more plausible for template
   arguments or embedded literals) could misparse. Not observed in
   practice, but not ruled out either.
6. **Entry point address.** The MAP's `entry point at SEG:OFF` line is
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
