"""fncre command-line entry point.

Subcommand groups:
  fncre map ...       parse and index MAP files
  fncre symbols ...   query an already-built symbol index

Run `fncre <command> -h` for per-command help.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from fncre.symbols.index import DEFAULT_DB_PATH, SymbolIndex
from fncre.symbols.map_parser import parse_map_file
from fncre.symbols.models import Symbol


def parse_address(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 16)


def _symbol_to_dict(sym: Symbol) -> dict:
    d = asdict(sym)
    if d.get("address") is not None:
        d["address_hex"] = f"0x{d['address']:08X}"
    return d


def _print_symbols(symbols: list[Symbol], as_json: bool) -> None:
    if as_json:
        print(json.dumps([_symbol_to_dict(s) for s in symbols], indent=2))
        return
    if not symbols:
        print("(no matches)")
        return
    for sym in symbols:
        addr = f"0x{sym.address:08X}" if sym.address is not None else "?" * 10
        vis = "pub" if sym.visibility == "public" else "sta"
        kind = "f" if sym.is_function else ("d" if sym.is_function is False else "?")
        obj = sym.object_name or "-"
        print(f"{addr}  [{vis}/{kind}]  {sym.name}   ({obj})")


def cmd_map_index(args: argparse.Namespace) -> int:
    parsed = parse_map_file(args.map_path)
    with SymbolIndex(args.db) as index:
        summary = index.index_parsed_map(args.build, parsed)
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(f"Indexed build '{args.build}' from {parsed.source_path}")
        print(f"  db: {args.db}")
        print(f"  total symbols   : {summary.total_symbols}")
        print(f"  public / static : {summary.public_count} / {summary.static_count}")
        print(
            f"  function / data / unknown-kind : "
            f"{summary.function_count} / {summary.data_count} / {summary.unknown_kind_count}"
        )
        print(f"  duplicate names   : {summary.duplicate_name_count}")
        print(f"  duplicate addrs   : {summary.duplicate_address_count}")
        print(f"  unparsed lines    : {summary.unparsed_line_count}")
        print(f"  segments parsed   : {summary.segment_count}")
        if summary.unparsed_line_count:
            print(
                "  note: unparsed lines were skipped, not guessed at; "
                "see `fncre map parse --json` to inspect them."
            )
    return 0


def cmd_map_parse(args: argparse.Namespace) -> int:
    parsed = parse_map_file(args.map_path)
    if args.json:
        payload = {
            "source_path": parsed.source_path,
            "header": asdict(parsed.header),
            "stats": asdict(parsed.stats),
            "issues": [asdict(i) for i in parsed.issues] if args.include_issues else None,
        }
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Parsed {parsed.source_path}")
    print(f"  module           : {parsed.header.module_name}")
    print(f"  preferred load   : {parsed.header.preferred_load_address}")
    print(f"  total lines      : {parsed.stats.total_lines}")
    print(f"  total symbols    : {parsed.stats.total_symbols}")
    print(f"  public / static  : {parsed.stats.public_count} / {parsed.stats.static_count}")
    print(f"  duplicate names  : {parsed.stats.duplicate_name_count}")
    print(f"  duplicate addrs  : {parsed.stats.duplicate_address_count}")
    print(f"  unparsed lines   : {parsed.stats.unparsed_line_count}")
    if args.include_issues:
        for issue in parsed.issues[: args.max_issues]:
            print(f"    line {issue.source_line}: {issue.reason}: {issue.text.strip()!r}")
    return 0


def cmd_symbols_search(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        results = index.search(args.build, args.substring, limit=args.limit)
        _print_symbols(results, args.json)
    return 0


def cmd_symbols_exact(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        results = index.exact(args.build, args.name)
        _print_symbols(results, args.json)
    return 0 if results else 1


def cmd_symbols_address(args: argparse.Namespace) -> int:
    addr = parse_address(args.address)
    with SymbolIndex(args.db) as index:
        results = index.by_address(args.build, addr)
        _print_symbols(results, args.json)
    return 0 if results else 1


def cmd_symbols_range(args: argparse.Namespace) -> int:
    lo, hi = parse_address(args.lo), parse_address(args.hi)
    with SymbolIndex(args.db) as index:
        results = index.address_range(args.build, lo, hi)
        _print_symbols(results, args.json)
    return 0


def cmd_symbols_object(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        results = index.by_object(args.build, args.object_name)
        _print_symbols(results, args.json)
    return 0


def cmd_symbols_library(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        results = index.by_library(args.build, args.library)
        _print_symbols(results, args.json)
    return 0


def cmd_symbols_namespace(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        results = index.by_namespace(args.build, args.namespace, limit=args.limit)
        _print_symbols(results, args.json)
    return 0


def cmd_symbols_visibility(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        results = index.by_visibility(args.build, args.visibility)
        _print_symbols(results, args.json)
    return 0


def cmd_symbols_nearest(args: argparse.Namespace) -> int:
    addr = parse_address(args.address)
    want_before = args.direction in ("before", "both")
    want_after = args.direction in ("after", "both")
    with SymbolIndex(args.db) as index:
        before = index.nearest_before(args.build, addr) if want_before else None
        after = index.nearest_after(args.build, addr) if want_after else None
    if args.json:
        print(
            json.dumps(
                {
                    "before": _symbol_to_dict(before) if before else None,
                    "after": _symbol_to_dict(after) if after else None,
                },
                indent=2,
            )
        )
        return 0
    if before:
        print("before:")
        _print_symbols([before], False)
    if after:
        print("after:")
        _print_symbols([after], False)
    if not before and not after:
        print("(no matches)")
    return 0


def cmd_symbols_stats(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        summary = index.build_summary(args.build)
    if summary is None:
        print(f"no such build indexed: {args.build}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        for key, value in asdict(summary).items():
            print(f"  {key}: {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fncre", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    # map
    map_parser = subparsers.add_parser("map", help="parse and index MAP files")
    map_sub = map_parser.add_subparsers(dest="map_command", required=True)

    p_index = map_sub.add_parser("index", help="parse a MAP file and persist it to the index")
    p_index.add_argument("map_path")
    p_index.add_argument("--build", required=True, help="build id, e.g. fn5d")
    p_index.add_argument(
        "--db", default=DEFAULT_DB_PATH, help=f"index DB path (default {DEFAULT_DB_PATH})"
    )
    p_index.add_argument("--json", action="store_true")
    p_index.set_defaults(func=cmd_map_index)

    p_parse = map_sub.add_parser("parse", help="parse a MAP file without indexing it")
    p_parse.add_argument("map_path")
    p_parse.add_argument("--json", action="store_true")
    p_parse.add_argument(
        "--include-issues", action="store_true", help="include unparsed-line detail"
    )
    p_parse.add_argument("--max-issues", type=int, default=50)
    p_parse.set_defaults(func=cmd_map_parse)

    # symbols
    sym_parser = subparsers.add_parser("symbols", help="query an indexed build")
    sym_sub = sym_parser.add_subparsers(dest="symbols_command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--db", default=DEFAULT_DB_PATH)
        p.add_argument("--json", action="store_true")

    p_search = sym_sub.add_parser("search", help="substring search over symbol names")
    p_search.add_argument("build")
    p_search.add_argument("substring")
    p_search.add_argument("--limit", type=int, default=200)
    add_common(p_search)
    p_search.set_defaults(func=cmd_symbols_search)

    p_exact = sym_sub.add_parser("exact", help="exact symbol name lookup")
    p_exact.add_argument("build")
    p_exact.add_argument("name")
    add_common(p_exact)
    p_exact.set_defaults(func=cmd_symbols_exact)

    p_addr = sym_sub.add_parser("address", help="lookup symbol(s) at an exact address")
    p_addr.add_argument("build")
    p_addr.add_argument("address", help="hex (0x...) or decimal")
    add_common(p_addr)
    p_addr.set_defaults(func=cmd_symbols_address)

    p_range = sym_sub.add_parser("range", help="lookup symbols within an address range")
    p_range.add_argument("build")
    p_range.add_argument("lo")
    p_range.add_argument("hi")
    add_common(p_range)
    p_range.set_defaults(func=cmd_symbols_range)

    p_obj = sym_sub.add_parser("object", help="lookup symbols by object file name")
    p_obj.add_argument("build")
    p_obj.add_argument("object_name")
    add_common(p_obj)
    p_obj.set_defaults(func=cmd_symbols_object)

    p_lib = sym_sub.add_parser("library", help="lookup symbols by library name")
    p_lib.add_argument("build")
    p_lib.add_argument("library")
    add_common(p_lib)
    p_lib.set_defaults(func=cmd_symbols_library)

    p_ns = sym_sub.add_parser("namespace", help="lookup symbols by class/namespace prefix")
    p_ns.add_argument("build")
    p_ns.add_argument("namespace", help="e.g. 'FightSim' or 'FightSim::'")
    p_ns.add_argument("--limit", type=int, default=500)
    add_common(p_ns)
    p_ns.set_defaults(func=cmd_symbols_namespace)

    p_vis = sym_sub.add_parser("visibility", help="lookup symbols by public/static")
    p_vis.add_argument("build")
    p_vis.add_argument("visibility", choices=["public", "static"])
    add_common(p_vis)
    p_vis.set_defaults(func=cmd_symbols_visibility)

    p_near = sym_sub.add_parser("nearest", help="find nearest symbol(s) around an address")
    p_near.add_argument("build")
    p_near.add_argument("address", help="hex (0x...) or decimal")
    p_near.add_argument("--direction", choices=["before", "after", "both"], default="both")
    add_common(p_near)
    p_near.set_defaults(func=cmd_symbols_nearest)

    p_stats = sym_sub.add_parser("stats", help="show summary stats for an indexed build")
    p_stats.add_argument("build")
    add_common(p_stats)
    p_stats.set_defaults(func=cmd_symbols_stats)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
