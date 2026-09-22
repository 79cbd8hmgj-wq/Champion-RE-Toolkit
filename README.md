# fncre — Fight Night Champion RE Toolkit

Reusable reverse-engineering infrastructure for **Fight Night Champion**
(Xbox 360), focused on the `FN5D` development build and `FN5Z` comparison
build. This is a *tooling* repository: it does not contain, and will never
contain, game files.

## What this is not

1. **No game files are included.** No `.xex`, `.map`, `.pdb`, `.xdb`,
   `BIG`/`AST` archives, or any extracted proprietary asset ships in this
   repository, in `tests/fixtures/`, or anywhere else. `.gitignore` blocks
   the known extensions as a backstop, but the real control is: don't add
   them.
2. **You bring your own artifacts.** Every tool in this toolkit takes a
   local file path you supply (e.g. your own copy of `fn5d.xenon.map`).
   Nothing is downloaded, fetched, or bundled.
3. **Derived metadata is exportable.** What you get out of running this
   toolkit against your own files — parsed symbol tables, SQLite indexes,
   JSON exports — is yours to keep, version, and feed into other projects.
4. **[Fight-Night-Legacy](https://github.com/79cbd8hmgj-wq/Fight-Night-Legacy)
   is the downstream research project.** This toolkit exists to produce
   evidence (symbol tables today; more later) that eventually feeds into
   that repository's research. This repo does not do the research itself,
   and it does not reorganize or migrate anything from Fight-Night-Legacy.

See [docs/provenance.md](docs/provenance.md) for the fuller policy this
project follows on evidence, sourcing, and what "demangled" means here.

## Current scope

**Phase 1 (symbol engine):** a parser for Xenon (Xbox 360) MSVC-style
linker MAP files (`fncre.symbols.map_parser`), a normalized `Symbol` model
(`fncre.symbols.models`), a deterministic SQLite-backed index
(`fncre.symbols.index`), and a `fncre` CLI to index and query MAP files.

**Phase 2 (automation primitives generalized from Fight-Night-Legacy's own
RE workflow):**

- MSVC C++ name demangling (`fncre.symbols.demangle`), corrected MAP
  parsing for the real decorated-name/flag format.
- XEX2 dev-key extraction and PE/VA addressing (`fncre.xex`).
- Direct PowerPC branch decoding (`fncre.ppc`).
- Function-boundary slicing and branch cross-referencing
  (`fncre.analysis`).
- Generalized build-identity verification (`fncre.build`).
- Cross-build (e.g. FN5D vs FN5Z) symbol and function diffing
  (`fncre.diff`).

Every Phase 2 module that overlaps existing Fight-Night-Legacy tooling
generalizes that tooling's already-working algorithm rather than
reimplementing it from scratch — see `docs/legacy-compatibility.md` for
the script-by-script rationale.

Explicitly **out of scope** so far (tracked for later phases): PDB
parsing, XDB parsing, a full PPC decompiler, AttribSys/BIG-archive
tunable extraction, Xenia integration, AI-assisted decompilation, and
speculative struct reconstruction.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`undname` (MSVC demangling) and `cryptography` (XEX extraction) are
optional extras included in `[dev]`; install them standalone with
`pip install -e ".[demangle]"` / `pip install -e ".[xex]"` if you only
need the base symbol engine otherwise.

## CLI usage

```bash
# Parse a MAP file and persist it into a local SQLite index
fncre map index /path/to/fn5d.xenon.map --build fn5d

# Parse only (no indexing), print stats
fncre map parse /path/to/fn5d.xenon.map

# Query the index
fncre symbols search fn5d "FightSim::"
fncre symbols exact fn5d "FightSim::UpdateHealth"
fncre symbols address fn5d 0x83601B80
fncre symbols range fn5d 0x83601000 0x83603000
fncre symbols object fn5d "fightsim.obj"
fncre symbols library fn5d "fightsim"
fncre symbols namespace fn5d "LegacyModeLogic::FightSim"
fncre symbols visibility fn5d public
fncre symbols nearest fn5d 0x836016C5
fncre symbols stats fn5d

# Raw decorated names and demangled names both resolve to the same symbol
fncre symbols exact fn5d '?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ'
fncre symbols exact fn5d 'LegacyModeLogic::FightSim::UpdateEnergy'

# Build-identity verification, function slicing, cross-build diffing
fncre build verify fn5d --identity build_identity.json --map fn5d.xenon.map
fncre function show fn5d "LegacyModeLogic::FightSim::UpdateEnergy" --pe fn5d.pe
fncre diff symbol fn5d fn5z "LegacyModeLogic::FightSim::UpdateEnergy"
```

Add `--json` to any subcommand for machine-readable output. The index
defaults to `.fncre/index.db` in the current directory; override with
`--db`.

See [docs/cli_usage.md](docs/cli_usage.md) for the full command reference,
[docs/architecture.md](docs/architecture.md) for how the pieces fit
together, and [docs/legacy-compatibility.md](docs/legacy-compatibility.md)
for how this toolkit relates to Fight-Night-Legacy's existing scripts.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy
```

## License

MIT. See [LICENSE](LICENSE).
