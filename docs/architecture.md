# Architecture

## Package layout

```
src/fncre/
  symbols/
    models.py        Value objects: Symbol, MapHeader, SegmentInfo, ParsedMap, ParseStats
    map_parser.py     Text -> ParsedMap (no I/O beyond reading the input file)
    demangle.py       Optional MSVC demangling pass over a ParsedMap (undname backend)
    index.py          ParsedMap -> SQLite, plus the query API (SymbolIndex)
  xex/
    pe.py             PE parsing + VA/RVA/raw-offset mapping
    dev_extract.py     XEX2 raw-format-1 dev-key extraction
  ppc/
    branch.py         Direct I-form/B-form branch decoding
  analysis/
    function_slice.py  Symbol + PE -> extracted function bytes, boundary provenance
    branch_xrefs.py    Direct-branch cross-referencing against named symbols
  build/
    identity.py        Generalized build-identity schema + verification
  diff/
    symbol_diff.py      Cross-build symbol comparison
    function_diff.py    Byte-level, relocation-aware function comparison
  attrib/
    hash.py             EA AttribSys string hashing
    keys.py             SQLite-backed hash -> text index (4-tier confidence)
    keys_import.py      Parsers for generated-keys CSVs and wordlists
    vault.py            .vlt/.bin chunk/export/fixup/class/collection parsing
    values.py           AttribSys primitive/array value decoding
    pipeline.py         Unified archive/vault -> resolved-tunables workflow
  archive/
    big.py              EA EB\0\x03 BIG archive parsing + safe extraction
    chunkzip.py          Chunkzip v2 decompression
  cli/
    main.py            argparse-based `fncre` entry point (map/symbols commands)
    analysis_commands.py  build/function/diff subcommands
    resource_commands.py  attrib/archive/tunables subcommands
```

`structs/` is named in the north-star layout but still not created.
Every other package listed above generalizes an algorithm Fight-Night-
Legacy's `research/fn5d-debug-legacy` branch already has working and
tested. `docs/legacy-compatibility.md` records which source script each
one came from and why (KEEP / WRAP / MIGRATE LATER / REPLACE AFTER
PARITY / CHAMPION-SPECIFIC KEEP); `docs/resource-pipeline.md` covers the
`attrib`/`archive` layers' user-facing workflow and architecture in depth.

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
SEG:OFFSET   <name, one token>   ADDRESS   [f][ i]   [Lib:Object]
```

The name column is a single non-whitespace token (`\S+`), confirmed against
Fight-Night-Legacy's own `tools/map_symbols.py` and its
`evidence/fn5d/*_symbols.csv`: real FN5D/FN5Z names are MSVC-decorated
(e.g. `?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ`), which never
contain spaces. The flags column is zero or more space-separated letters
from `{f, i}` (e.g. `f`, `i`, or `f i`); an absent letter means "unknown",
never "false" — see `Symbol.is_function`/`is_internal`/`raw_flags`.

## Demangling (`fncre.symbols.demangle`)

A separate, optional pass (`demangle_parsed_map`/`demangle_symbol`) using
the `undname` backend (see `docs/provenance.md` for why that backend was
chosen over a homebrew demangler). It fills in `Symbol.demangled_name`
(bare qualified name, e.g. `LegacyModeLogic::FightSim::UpdateEnergy`,
comparable with raw-name queries) and `Symbol.demangled_signature` (the
full formatted signature) without ever discarding a symbol it can't
demangle. `SymbolIndex.exact`/`search` match against both the raw and
demangled name, so a query can use either form.

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
CLI exposes. `SymbolIndex.function_symbols(build_id)` returns the
`is_function`-flagged rows sorted by address — the boundary set
`fncre.analysis.function_slice` needs to infer where a function ends.

## XEX/PE/PPC (`fncre.xex`, `fncre.ppc`)

`xex.dev_extract.extract_xex2` decrypts a raw-format-1 XEX2 (AES-ECB-unwrap
the session key with a 16-byte master key, defaulting to the all-zero
Xbox 360 devkit key, then AES-CBC-decrypt the block stream) into a plain PE
image. `xex.pe.parse_pe`/`va_to_file_offset`/`section_file_window` then
read that PE's section table and map a runtime VA to a file offset, in
either `xbox_rva` layout (file_offset == RVA, what `extract_xex2` produces)
or `pe_raw` layout (conventional disk PE). `ppc.branch.decode_direct_branch`
decodes PowerPC I-form/B-form direct branches only — no indirect
LR/CTR calls, no virtual dispatch. All three modules are direct ports of
already-working Fight-Night-Legacy algorithms; see
`docs/legacy-compatibility.md`.

## Analysis (`fncre.analysis`)

`function_slice.slice_function` extracts one function's raw bytes given a
target `Symbol`, a sorted function-symbol list (for boundary inference),
and a PE image. Boundary provenance is always explicit:
`next_symbol_inferred` (default), `manual_override` (caller supplied
`override_size`), or the `FunctionSliceError` raised when neither is
possible. `branch_xrefs.find_direct_xrefs` scans a PE's executable
sections for direct branches into a set of target addresses and attributes
each one to its containing function via `build_function_ranges`.

## Build identity (`fncre.build.identity`)

Generalizes Fight-Night-Legacy's `evidence/fn5d/build_identity.json` +
`tools/re_validate_fn5d.py` gate: `verify_build` checks whichever of
`--xex`/`--pe`/`--map` the caller supplies against the matching block of an
identity JSON file (same schema as Legacy's file, no FN5D-specific
renaming), and reports a `trust_level` per artifact —
`artifact_unavailable` (not checked), `artifact_available` (checked, has
errors), or `identity_validated` (checked, zero errors).
`VerifyReport.all_requested_validated` is the "derived evidence trusted"
gate: true only when every artifact the caller asked to check validated
cleanly.

## Diff (`fncre.diff`)

`symbol_diff.compare_symbols` matches two builds' symbols by raw
(decorated) name — mangling doesn't embed addresses, so a name is stable
across a relink as long as its signature didn't change — and reports
`only_a`/`only_b`/`both` plus, for matches, whether the address moved,
inferred size changed (from each build's own next-symbol gap), or
object/library/visibility changed. A different address alone is never
flagged as a meaningful change, per the task this module was built to
satisfy. `function_diff.classify_function_diff` compares two already-sliced
function blobs and returns one of four conservative classifications
(`byte_identical`, `relocation_normalized_identical`,
`structurally_similar`, `different`) — never a semantic-equivalence claim.
See `docs/provenance.md` for the evidence/conclusion boundary this module
respects.
