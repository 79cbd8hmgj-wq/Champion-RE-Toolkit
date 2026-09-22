# CLI usage

All commands are subcommands of `fncre`. Add `--json` to any `map` or
`symbols` subcommand for machine-readable output.

## `fncre map index`

Parse a MAP file and persist it into a SQLite index under a `build_id` you
choose (e.g. `fn5d`, `fn5z`). Re-running this for the same `build_id`
replaces that build's data — it does not accumulate duplicates across runs.

```bash
fncre map index /path/to/fn5d.xenon.map --build fn5d
fncre map index /path/to/fn5z.xenon.map --build fn5z --db ./builds.db
```

Options:
- `--build ID` (required) — logical build name, used as the key for all
  `symbols` queries.
- `--db PATH` — SQLite database path. Default: `.fncre/index.db`.
- `--json` — print the resulting `BuildSummary` as JSON instead of text.

## `fncre map parse`

Parse a MAP file without writing to any index. Useful for inspecting parse
quality (stats, unrecognized lines) before committing to an index build.

```bash
fncre map parse /path/to/fn5d.xenon.map
fncre map parse /path/to/fn5d.xenon.map --json --include-issues
```

Options:
- `--json` — structured output (header, stats, and optionally issues).
- `--include-issues` — include the list of unparsed lines (source line,
  raw text, reason).
- `--max-issues N` — cap how many issues are printed in text mode
  (default 50; JSON mode includes all of them when `--include-issues` is
  set).

## `fncre symbols ...`

All `symbols` subcommands take a `--db PATH` (default `.fncre/index.db`)
and a positional `build` argument matching the `--build` used at index
time.

```bash
# Exact name
fncre symbols exact fn5d "FightSim::UpdateHealth"

# Substring search
fncre symbols search fn5d "FightSim::"
fncre symbols search fn5d "FightSim::" --limit 50

# Exact address (accepts 0x-prefixed hex or decimal)
fncre symbols address fn5d 0x83601B80

# Address range, inclusive
fncre symbols range fn5d 0x83601000 0x83603000

# By object file / library, exact match
fncre symbols object fn5d "fightsim.obj"
fncre symbols library fn5d "fightsim"

# By class/namespace prefix (matches "NS" or "NS::...")
fncre symbols namespace fn5d "FightSim"

# By visibility
fncre symbols visibility fn5d public
fncre symbols visibility fn5d static

# Nearest symbol before/after/both around an address
fncre symbols nearest fn5d 0x836016C5
fncre symbols nearest fn5d 0x836016C5 --direction before

# Summary stats for an indexed build
fncre symbols stats fn5d
```

Exit codes: `symbols exact` and `symbols address` return `1` when there are
no matches (useful for scripting); other query subcommands always return
`0` and print `(no matches)` when empty.

Both `exact` and `search` match against the raw (decorated) name **and**
the demangled name once `map index` has demangled the build, so
`?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ` and
`LegacyModeLogic::FightSim::UpdateEnergy` resolve to the same symbol.

## `fncre build verify`

Generalizes Fight-Night-Legacy's `evidence/*/build_identity.json` +
`tools/re_validate_fn5d.py` gate: checks local artifacts against an
identity JSON file before you trust anything derived from them.

```bash
fncre build verify fn5d --identity build_identity.json --map fn5d.xenon.map
fncre build verify fn5d --identity build_identity.json \
    --xex fn5d.xex --pe fn5d.pe --map fn5d.xenon.map
```

Exit code `0` only when every artifact you asked to check validated with
zero errors (`report.all_requested_validated`); `1` otherwise. See
`docs/architecture.md`'s "Build identity" section for the schema, and pass
`--json` for the structured per-artifact `trust_level`
(`artifact_unavailable` / `artifact_available` / `identity_validated`).

## `fncre function show`

Slices one function's raw bytes out of an extracted PE image, using the
symbol index for boundary inference (next symbol's address).

```bash
fncre function show fn5d "LegacyModeLogic::FightSim::UpdateEnergy" --pe fn5d.pe
fncre function show fn5d "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ" --pe fn5d.pe
fncre function show fn5d 0x836016C0 --pe fn5d.pe --show-words
```

`--pe` is an already-extracted PE image (see `fncre.xex.dev_extract` for
extraction — no CLI wraps it yet in this phase). `--layout` defaults to
`xbox_rva` (matching that extractor's output); use `pe_raw` for a
conventional disk-layout PE. `--size N` overrides boundary inference
(reported as `boundary: manual_override`) when you know the true size.

## `fncre diff`

Cross-build (e.g. FN5D vs FN5Z) comparison. Produces facts (matched,
address moved, size changed, absent in one build, byte-identical, ...),
never research conclusions — see `docs/provenance.md`.

```bash
# Symbol-level: requires both builds already indexed in the same --db
fncre diff symbol fn5d fn5z "LegacyModeLogic::FightSim::UpdateEnergy"
fncre diff namespace fn5d fn5z "LegacyModeLogic::FightSim"

# Function-level: byte comparison, requires an extracted PE per build
fncre diff function fn5d fn5z "LegacyModeLogic::FightSim::UpdateEnergy" \
    --pe-a fn5d.pe --pe-b fn5z.pe
```

`diff function`'s classification is always one of `byte_identical`,
`relocation_normalized_identical`, `structurally_similar`, or
`different` — it never claims semantic equivalence from byte similarity
alone. If a symbol can't be sliced in one build (e.g. build-exclusive
functionality), the command reports `{"classification": "unresolved", ...}`
and exits `1` rather than guessing.

## `fncre attrib`

EA AttribSys string hashing, attribute-key resolution, and `.vlt`/`.bin`
vault inspection/extraction. See `docs/resource-pipeline.md` for the full
workflow this feeds into.

```bash
# Hashing (exact parity with Fight-Night-Legacy's tools/attrib_hash.py)
fncre attrib hash fight_sim scheduling
fncre attrib hash-file candidate_keys.txt --json

# Attribute-key index: four confidence levels, never collapsed
fncre attrib keys import fn5d_generated_keys.csv --build fn5d   # -> evidenced
fncre attrib keys import wordlist.txt --build fn5d --status generated
fncre attrib keys search fn5d "fight_sim"
fncre attrib keys lookup fn5d 0xA9244D34
fncre attrib keys stats fn5d

# Vault inspection/extraction
fncre attrib inspect attribdb.vlt
fncre attrib extract attribdb.vlt --bin attribdb.bin \
    --build fn5d --class-name fe_legacy --collection fight_sim \
    --keys fn5d_keys.db --json
```

## `fncre archive`

EA BIG (`EB\0\x03`) archive inspection and extraction, generalizing
Fight-Night-Legacy's `tools/ea_eb_extract.py`.

```bash
fncre archive inspect boot_other.big
fncre archive list boot_other.big --match attrib
fncre archive extract boot_other.big --output extracted/ --match attribdb
```

`archive extract` rejects path traversal explicitly (a crafted or
corrupted archive with `../`-style entry paths cannot write outside
`--output`) and decompresses chunkzip-wrapped members by default; pass
`--keep-chunkzip` to get the raw wrapped bytes instead.

## `fncre tunables extract`

The unified pipeline: detects whether `--input` is a BIG archive or a
direct `.vlt` file, runs every stage needed, and writes a
provenance-carrying JSON file. See `docs/resource-pipeline.md` for the
full schema and the archive → vault → resolved-values architecture.

```bash
fncre tunables extract \
    --build fn5d --input boot_other.big \
    --class-name fe_legacy --collection fight_sim \
    --keys fn5d_keys.db --output derived/
```
