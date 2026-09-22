# Resource/tunable extraction pipeline

## "I have an FN5 resource archive. I want the tunables inside it."

```bash
fncre tunables extract \
    --build fn5d \
    --input boot_other.big \
    --class-name fe_legacy \
    --collection fight_sim \
    --keys fn5d_keys.db \
    --output derived/
```

This runs the whole chain in one command: detects that `boot_other.big` is
a BIG archive, finds and extracts the member that looks like a `.vlt` and
the member that looks like a `.bin` (chunkzip-decompressing them if
needed), walks the AttribSys export/fixup/class/collection records for the
`fight_sim` collection under the `fe_legacy` class, resolves each field's
name against `fn5d_keys.db` (an `AttribKeyIndex` you build once — see
below), and writes `derived/fight_sim.json`.

If you already have a decompressed `.vlt`/`.bin` pair (e.g. from
`fncre archive extract`), point `--input` at the `.vlt` file directly
instead of the archive — the pipeline detects which stages it needs:

```bash
fncre tunables extract \
    --build fn5d --input attribdb.vlt --bin attribdb.bin \
    --class-name fe_legacy --collection fight_sim --output derived/
```

### Building the key index first

Field names come from a linker-map-derived `AttribKeyIndex`, not from the
vault itself (the vault only stores 32-bit hashes). Build one once per
build, from the same CSV Fight-Night-Legacy's own
`generated_attrib_keys.py` already produces:

```bash
python tools/generated_attrib_keys.py fn5d.xenon.map > fn5d_keys.csv
fncre attrib keys import fn5d_keys.csv --build fn5d --db fn5d_keys.db
```

Rows from that CSV import with `status="evidenced"` (the text is directly
confirmed present as a linker-map initializer). See "Key confidence
levels" below for the other three levels and how to add candidates to
them.

### Tracing a value back to its source

Every record in the output JSON carries enough to find the exact bytes it
came from — see `provenance` at the top of the file and each record's
`export_offset`/`record_offset`/`key_hash_hex`. Nothing is ever reported
without this trail; see "Provenance schema" below for the full field list.

## Pipeline stages

```
  BIG archive (e.g. boot_other.big)             .vlt file directly
        |                                              |
        v                                              |
  fncre.archive.big.parse_big                          |
        |                                              |
        v                                              |
  fncre.archive.chunkzip.decompress_chunkzip            |
        |                                              |
        +----------------------- both paths converge --+
                                  |
                                  v
                    fncre.attrib.vault (chunk walk,
                    export table, fixups, class/field
                    definitions, collection entries)
                                  |
                                  v
                    fncre.attrib.values (primitive/
                    array decoding)
                                  |
                                  v
                    fncre.attrib.keys (hash -> resolved
                    text, with confidence level)
                                  |
                                  v
                    fncre.attrib.pipeline.extract_tunables
                    (ExtractionResult: provenance + records)
                                  |
                                  v
                    derived evidence JSON
                    (safe to commit; no proprietary bytes)
```

`fncre.attrib.pipeline.resolve_input` is the only stage that looks at the
*shape* of the input to decide which earlier stages to run — everything
below it always runs the same way regardless of whether the input started
as an archive or a bare vault.

## Key confidence levels

`AttribKeyIndex` (`fncre.attrib.keys`) never collapses these into one
number:

| Status | Meaning | How you'd add one |
| --- | --- | --- |
| `evidenced` | Text is directly confirmed present in build evidence (a generated linker-map initializer). | `fncre attrib keys import <generated_attrib_keys.py CSV>` |
| `generated` | A candidate produced by a systematic construction rule, not yet confirmed present. | `fncre attrib keys import <wordlist> --status generated` |
| `inferred` | A candidate reached by heuristic reasoning (context, naming-pattern guesswork). | `fncre attrib keys import <wordlist> --status inferred` |
| `unresolved` | No candidate text at all — only the hash is known. | Produced automatically by `extract_tunables` when a record's hash has no index match. |

A hash collision — two different texts hashing to the same 32-bit value —
is preserved, never silently resolved by picking one. `fncre attrib keys
lookup <build> <hash>` always returns every candidate.

## Provenance schema (v1.0.0)

`ExtractionProvenance.to_json_dict()` (top-level `"provenance"` key):

| Field | Meaning |
| --- | --- |
| `schema_version` | This document's version number; bump it if the shape changes. |
| `tool_version` | `fncre.__version__` that produced the file. |
| `build_id` | The build this extraction is for (`fn5d`, `fn5z`, ...). |
| `input_kind` | `"archive"` or `"vlt_bin"`. |
| `archive_path` / `archive_sha256` | The source BIG archive, if `input_kind == "archive"`. |
| `archive_member_vlt` / `archive_member_bin` | Which archive member each file came from. |
| `vlt_path` / `bin_path` | The `.vlt`/`.bin` file paths, if given directly. |
| `vlt_sha256` / `bin_sha256` | Hashes of the *decompressed* vault bytes actually parsed. |
| `class_name` / `class_hash` | The AttribSys class extracted. |
| `collection_name` / `collection_hash` | The collection extracted. |
| `build_identity_status` | `"not_checked"` unless the caller separately validated the source artifacts with `fncre build verify` and passed its result in. |

Each record (`"records"` list) carries `key_hash_hex`, `resolved_text` /
`resolution_status` (one of the four confidence levels, or
`"no_key_index"` if no `AttribKeyIndex` was supplied), `export_offset`
(the collection's own export-table offset), `record_offset` (this
specific entry's byte offset within the vault), `type_hash_hex` /
`type_name`, and `value`.

This schema is deliberately narrow: it's what `fncre` itself established
from the bytes. A record's `resolved_text` says a hash matched a known
name; it does not say what that field *does* in Legacy Mode gameplay —
that's a Fight-Night-Legacy-side research conclusion, recorded in *its*
evidence files, not duplicated here.

## Growth-package integration

Fight-Night-Legacy's `tools/fn5_growth_extract.py` decodes the
`DestinyPackage` growth-rule tables. Studying it (see
`docs/legacy-compatibility.md`) shows a clean split:

- **Generic** (now in `fncre`): locating a named collection's entries,
  resolving a field's pointer fixup into the `.bin` dependency, decoding a
  primitive or array value at that offset. `fn5_growth_extract.py` already
  calls exactly these operations (via `fn5_attrib_extract.py`'s `load`,
  `chunks`, `parse_fixups` — the same functions `fncre.attrib.vault` now
  generalizes).
- **Champion-specific** (stays in Fight-Night-Legacy): the growth system's
  own vocabulary — `WEIGHT_CLASSES` order, `AGE_GROUP_MAX` boundaries, the
  15 `RATINGS` names, the `PACKAGE_ORDER`/`PACKAGE_ENUM` naming, and the
  fixed `RULE_SIZE`/`AGE_BLOCK_SIZE`/`WEIGHT_BLOCK_SIZE`/`PACKAGE_SIZE`
  byte-layout constants that only make sense once you already know this is
  a growth-rule table (as opposed to, say, a scheduling table with a
  completely different internal layout).

A future Fight-Night-Legacy-side change (not made in this phase — see
"Why no wrapper was added" in `docs/legacy-compatibility.md`) could
rewrite `fn5_growth_extract.py` as a thin consumer:

```python
# illustrative only — not implemented in this phase
from fncre.attrib.pipeline import extract_tunables

result = extract_tunables(
    "attribdb.vlt", build_id="fn5d",
    class_name="fe_legacy", collection_name="package_user",
    bin_path_override="attribdb.bin",
)
# then apply Fight Night Champion-specific interpretation
# (WEIGHT_CLASSES, RATINGS, the 16-byte rule layout) to result.records
```

`fncre` was deliberately **not** given a `weight_class_growth` module or
any other Champion-domain vocabulary — see "Important constraints" in the
task this phase implements, and the "Generic mechanics belong in the
toolkit" principle throughout `docs/legacy-compatibility.md`.

## What's out of scope here

Everything under "Important constraints" in this phase's task: new
FightSim/live-combat/Legacy reverse engineering, PDB/XDB parsing, Xenia
integration, patching/injection, a full PPC decompiler, AI pseudocode
generation. Also out of scope for *this* pipeline specifically: any
Champion-specific field-name-to-meaning mapping (that's Fight-Night-
Legacy's job, using this pipeline's `resolved_text`/`value` output as
input to its own research), and BIG archive formats other than the
`EB\0\x03` layout already confirmed in Fight-Night-Legacy's research.
