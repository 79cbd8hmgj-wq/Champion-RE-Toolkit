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
