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

## Current scope (Phase 1: symbol engine)

This phase implements a trustworthy MAP-file symbol engine:

- A parser for Xenon (Xbox 360) MSVC-style linker MAP files
  (`fncre.symbols.map_parser`).
- A normalized `Symbol` model that preserves raw MAP text alongside
  searchable fields (`fncre.symbols.models`).
- A deterministic SQLite-backed index with a clean Python query API
  (`fncre.symbols.index`).
- A `fncre` CLI to index and query MAP files.

Explicitly **out of scope** for this phase (tracked for later phases):
XEX loading, PowerPC disassembly, PDB parsing, XDB parsing, BIG/AST
extraction, Xenia integration, AI-assisted decompilation, and speculative
struct reconstruction.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

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
fncre symbols namespace fn5d "FightSim"
fncre symbols visibility fn5d public
fncre symbols nearest fn5d 0x836016C5
fncre symbols stats fn5d
```

Add `--json` to any `symbols` or `map` subcommand for machine-readable
output. The index defaults to `.fncre/index.db` in the current directory;
override with `--db`.

See [docs/cli_usage.md](docs/cli_usage.md) for full command reference and
[docs/architecture.md](docs/architecture.md) for how the pieces fit
together.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy
```

## License

MIT. See [LICENSE](LICENSE).
