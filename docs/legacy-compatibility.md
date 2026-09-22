# Compatibility with Fight-Night-Legacy's existing RE scripts

Fight-Night-Legacy's `research/fn5d-debug-legacy` branch already has
working, tested infrastructure for MAP parsing, XEX extraction, function
slicing, branch cross-referencing, and build-identity validation. This
toolkit's Phase 2 generalizes several of those algorithms into reusable
`fncre` modules — it does not redo the reverse engineering, and it does
not silently duplicate the existing scripts without a migration plan.

This document classifies each overlapping script and records why. Nothing
in Fight-Night-Legacy was modified to produce this classification; no
wrapper was written into that repository in this phase (see "Why no
wrapper was added to Fight-Night-Legacy yet" below).

| Script | Classification | Why |
| --- | --- | --- |
| `tools/map_symbols.py` | **REPLACE AFTER PARITY** | `fncre.symbols.map_parser` is a strict superset: same real-format regex (confirmed identical flag/name handling), plus visibility tracking (public/static), segment-table parsing, section resolution, demangling, and SQLite indexing that `map_symbols.py` doesn't have. Until a Legacy researcher actually re-points their workflow at `fncre` and confirms parity on real files, `map_symbols.py` keeps working exactly as before — nothing here breaks it. |
| `tools/extract_dev_xex.py` / `tools/xex2_raw_extract.py` | **WRAP TOOLKIT** | Identical algorithm (AES-ECB session-key unwrap + AES-CBC block decrypt), generalized in `fncre.xex.dev_extract.extract_xex2` with `master_key` as a parameter instead of hardcoded. The two Legacy scripts differed only in whether that key was hardcoded; a thin Legacy-side wrapper calling `fncre.xex.dev_extract.extract_xex2(data, master_key=DEVKIT_XEX_KEY)` would be a safe follow-up once this package is installable from Legacy's own environment — not done in this phase since it would mean editing Fight-Night-Legacy, which this task asked to avoid unless genuinely required. |
| `tools/re_function_slice.py` | **WRAP TOOLKIT** | Its PE-parsing half (`parse_pe`, `va_to_file_offset`, `section_file_window`) is ported unchanged into `fncre.xex.pe`. Its function-slicing half (`inferred_symbol_end`, `extract_one`) is generalized into `fncre.analysis.function_slice`, operating on `fncre.symbols.models.Symbol` instead of a CSV/map-specific reader, with explicit boundary provenance (`next_symbol_inferred`/`manual_override`/`unknown`) rather than assuming one policy. The branch-decoding half (`decode_direct_branch`, `hexdump_words`) is ported unchanged into `fncre.ppc.branch`. |
| `tools/re_branch_xrefs.py` | **WRAP TOOLKIT** | `iter_direct_branches`, `build_function_ranges`, `caller_for_address`, `find_direct_xrefs` are ported unchanged in algorithm into `fncre.analysis.branch_xrefs`, generalized to `Symbol` objects. Same explicit limitations preserved (direct branches only, no indirect/virtual dispatch, no data/TOC refs). |
| `tools/re_validate_fn5d.py` | **REPLACE AFTER PARITY** | `fncre.build.identity` reads the *exact same* `build_identity.json` schema (no field renamed, no FN5D-specific hardcoding) and reimplements `validate_xex`/`validate_pe`/`validate_map` as `verify_xex_bytes`/`verify_pe_bytes`/`verify_map_file`, generalized to accept any `build_id`/identity file rather than being wired to one default path. Same anchor-disambiguation rule (`find_unique_symbol`'s decorated-boundary preference) is preserved. Not yet proven against the real `evidence/fn5d/build_identity.json` (no real files in this environment — see the final report's validation-status section), so `re_validate_fn5d.py` should keep running until someone runs `fncre build verify` against the real files and confirms identical verdicts. |

## Why no wrapper was added to Fight-Night-Legacy yet

The task instructions for this phase were explicit: avoid modifying
Fight-Night-Legacy unless a compatibility test/wrapper or documentation
update is genuinely required, and do most of the implementation in
Champion-RE-Toolkit. A wrapper is not yet *required* because:

1. `fncre` isn't published anywhere Fight-Night-Legacy's own environment
   could `pip install` it from (it exists only as an unmerged branch of a
   sibling repository in this session).
2. None of the ported algorithms have been proven against the *real*
   FN5D/FN5Z files yet (see the parity-testing note below) — wrapping
   Legacy's scripts around unverified code would be premature.

Once both are true, the recommended shape is a thin compatibility layer:
Legacy's scripts import from `fncre` and keep their existing CLI/output
format, rather than Legacy re-implementing anything `fncre` now owns. That
is a Fight-Night-Legacy-side change for a future phase, done by that
repository's own maintainers/RE workflow once `fncre` is trusted.

## Parity testing performed in this phase

Every ported algorithm was tested against synthetic fixtures built to
match the real format (see `tests/test_xex_pe.py`,
`tests/test_xex_dev_extract.py`, `tests/test_ppc_branch.py`,
`tests/test_function_slice.py`, `tests/test_branch_xrefs.py`,
`tests/test_build_identity.py`), and Fight-Night-Legacy's *own* unmodified
test suite was run to confirm it still passes unchanged (this toolkit
never touched that repository's files). **No byte-for-byte comparison
against Legacy's actual scripts run on a real FN5D/FN5Z file was
performed**, because no such file exists in this environment — that
remains the concrete next step before calling any "REPLACE AFTER PARITY"
row above actually replaced. See the final report's "XEX/function-slice
regression results" section for exactly what was and wasn't verified.
