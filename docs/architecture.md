# Architecture

## Package layout

```
src/fncre/
  symbols/
    models.py       Value objects: Symbol, MapHeader, SegmentInfo, ParsedMap, ParseStats
    map_parser.py    Text -> ParsedMap (no I/O beyond reading the input file)
    index.py         ParsedMap -> SQLite, plus the query API (SymbolIndex)
  cli/
    main.py          argparse-based `fncre` entry point, thin over the above
```

Only `symbols/` and `cli/` exist in this phase. `xex/`, `ppc/`, `analysis/`,
`structs/`, `diff/`, and `archives/` are named in the north-star layout but
intentionally not created yet — see "Scope control" in the project's task
description and the Phase 2 recommendations at the end of
[provenance.md](provenance.md). Empty placeholder packages were not added;
they'll be created when the code that belongs in them exists.

## Data flow

```
  fn5d.xenon.map (user-supplied, never committed)
        |
        v
  parse_map_file()              fncre.symbols.map_parser
        |
        v
  ParsedMap                     fncre.symbols.models
    - header (module, load address, entry point)
    - segments[]  (Start/Length/Name/Class table)
    - symbols[]   (Symbol, one per recognized public/static row)
    - issues[]    (ParseIssue, one per line that didn't match)
    - stats       (ParseStats: counts used for validation reporting)
        |
        v
  SymbolIndex.index_parsed_map() fncre.symbols.index
        |
        v
  SQLite database (default .fncre/index.db)
    - builds(build_id, ...)      one row per indexed build (fn5d, fn5z, ...)
    - symbols(build_id, ...)     one row per Symbol, FK to builds
        |
        v
  SymbolIndex query methods  <-  fncre CLI (`fncre symbols ...`)
```

`map_parser` never touches SQLite; `index` never parses text. The `Symbol`
dataclass is the contract between them, so either side can be tested,
replaced, or reused independently (e.g. a future `diff/` module can consume
`Symbol` objects or query two builds via `SymbolIndex` without going back
through parsing).

## MAP parser state machine

The parser is a single-pass, line-oriented state machine over five states:

1. **header** — before the segment table. Captures module name, `Timestamp
   is ...`, `Preferred load address is ...`.
2. **segments** — the `Start Length Name Class` table. Each row becomes a
   `SegmentInfo`; the resulting `{segment_number: section_name}` map is
   used after the main pass to fill in `Symbol.section`.
3. **publics** — rows under a `Publics by Value` header. Visibility=`public`.
4. **publics_by_name** — rows under a `Publics by Name` header, if present.
   This is the same symbol set as `publics`, just sorted differently by the
   linker; it is **skipped**, not parsed, to avoid double-counting. See
   `docs/provenance.md` for why this is treated as an assumption to
   validate against a real file rather than a certainty.
5. **statics** — rows under a `Static symbols` header. Visibility=`static`.

An `entry point at SEG:OFF` line ends symbol parsing (state → trailer).
Blank lines are always skipped. A non-blank line that doesn't match the
expected pattern for the current state is recorded as a `ParseIssue`
(source line number, raw text, reason) and otherwise ignored — it is never
silently dropped from the parse report, and it never crashes the parser.

Symbol rows are matched with a single regex per state:

```
SEG:OFFSET   <name, possibly containing spaces>   ADDRESS  [f]  [Lib:Object]
```

The name capture is a lazy match anchored on the trailing 8-hex-digit
address, so names containing spaces (template instantiations, operator
names) are handled, at the cost of being confusable if a name were to
itself contain an 8-hex-digit run immediately before whitespace — see the
known ambiguities list in `docs/provenance.md`.

## Index schema

Two tables, `builds` and `symbols` (see `fncre/symbols/index.py` for the
canonical `CREATE TABLE` statements). `symbols.build_id` lets one SQLite
file hold multiple builds (e.g. `fn5d` and `fn5z`) side by side, which is
what a future cross-build diff tool will need. Re-running `map index` for a
`build_id` deletes and re-inserts that build's rows in one transaction, so
indexing is idempotent and results are deterministic for an unchanged
input file. Symbols are never deduplicated by name or address — see
"Duplicate handling" in `docs/provenance.md`.

Indexes exist on `(build_id, name)`, `(build_id, address)`,
`(build_id, object_name)`, `(build_id, library)`, `(build_id,
namespace_path)`, and `(build_id, visibility)`, covering every query the
CLI exposes.
