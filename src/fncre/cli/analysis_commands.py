"""`fncre build`, `fncre function`, and `fncre diff` subcommands.

Kept separate from cli/main.py's original map/symbols commands to keep
each file a manageable size; `main.py` wires these in via `register`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from fncre.analysis.function_slice import FunctionSliceError, slice_function
from fncre.build.identity import load_identity, verify_build
from fncre.diff.function_diff import classify_function_diff
from fncre.diff.symbol_diff import compare_symbols
from fncre.symbols.index import DEFAULT_DB_PATH, SymbolIndex
from fncre.symbols.models import Symbol
from fncre.xex.pe import IMAGE_LAYOUT_XBOX_RVA, VALID_IMAGE_LAYOUTS, parse_pe


class SymbolResolutionError(ValueError):
    pass


def _parse_address(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 16)


def resolve_symbol(index: SymbolIndex, build_id: str, query: str) -> Symbol:
    """Resolve a query as: exact raw/demangled name, then address, then a
    unique substring search. Raises SymbolResolutionError with a message
    listing candidates if the query is ambiguous or matches nothing."""
    exact = index.exact(build_id, query)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise SymbolResolutionError(
            f"{query!r} matches {len(exact)} symbols exactly "
            f"(same name in both public and static, or across objects); "
            f"disambiguate by address instead"
        )

    try:
        address = _parse_address(query)
    except ValueError:
        pass
    else:
        by_addr = index.by_address(build_id, address)
        if len(by_addr) == 1:
            return by_addr[0]
        if len(by_addr) > 1:
            names = ", ".join(s.raw_name for s in by_addr[:8])
            raise SymbolResolutionError(f"address {query!r} is ambiguous: {names}")

    results = index.search(build_id, query, limit=10)
    if len(results) == 1:
        return results[0]
    if not results:
        raise SymbolResolutionError(f"no symbol matches {query!r} in build {build_id!r}")
    names = ", ".join(s.raw_name for s in results[:8])
    raise SymbolResolutionError(f"{query!r} is ambiguous ({len(results)} matches): {names}")


# -- fncre build verify ---------------------------------------------------


def cmd_build_verify(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    report = verify_build(
        args.build,
        identity,
        args.identity,
        xex_path=args.xex,
        pe_path=args.pe,
        map_path=args.map_path,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "build_id": report.build_id,
                    "identity_path": report.identity_path,
                    "all_requested_validated": report.all_requested_validated,
                    "artifacts": [asdict(a) for a in report.artifacts],
                },
                indent=2,
            )
        )
    else:
        print(f"build-identity check for '{report.build_id}' against {report.identity_path}")
        if not report.artifacts:
            print("  (no artifacts given to check: pass --xex/--pe/--map)")
        for artifact in report.artifacts:
            print(f"  {artifact.artifact}: {artifact.trust_level}")
            for error in artifact.errors:
                print(f"    - {error}")
        verdict = "TRUSTED" if report.all_requested_validated else "NOT TRUSTED"
        print(f"  derived evidence from these artifacts: {verdict}")
    return 0 if report.all_requested_validated else 1


# -- fncre function show ---------------------------------------------------


def cmd_function_show(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        try:
            target = resolve_symbol(index, args.build, args.query)
        except SymbolResolutionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        function_symbols = index.function_symbols(args.build)

    pe = Path(args.pe).read_bytes()
    image_base, sections = parse_pe(pe)

    try:
        result = slice_function(
            pe=pe,
            image_base=image_base,
            sections=sections,
            function_symbols_sorted=function_symbols,
            target=target,
            max_bytes=args.max_bytes,
            override_size=args.size,
            layout=args.layout,
        )
    except FunctionSliceError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload = {
        "raw_name": target.raw_name,
        "demangled_name": target.demangled_name,
        "demangled_signature": target.demangled_signature,
        "start_va": f"0x{result.start_va:08X}",
        "end_va": None if result.end_va is None else f"0x{result.end_va:08X}",
        "size": result.size,
        "boundary": result.boundary,
        "object_name": target.object_name,
        "library": target.library,
        "layout": args.layout,
        "sha256": result.sha256,
        "branches": [
            {
                "offset": f"+0x{b.offset_in_function:X}",
                "va": f"0x{b.va:08X}",
                "kind": b.kind,
                "target": f"0x{b.target:08X}",
            }
            for b in result.branches
        ],
    }
    if args.json:
        payload["ppc_words"] = result.ppc_words
        print(json.dumps(payload, indent=2))
    else:
        print(f"{target.raw_name}")
        if target.demangled_signature:
            print(f"  {target.demangled_signature}")
        print(f"  start: {payload['start_va']}  end: {payload['end_va']}  "
              f"size: {result.size}  boundary: {result.boundary}")
        print(f"  object: {target.object_name}  library: {target.library}")
        for b in result.branches:
            print(f"  {b.offset_in_function:+#06x}  {b.kind} -> 0x{b.target:08X}")
        if args.show_words:
            print(result.ppc_words)
    return 0


# -- fncre diff -------------------------------------------------------------


def cmd_diff_symbol(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        try:
            target_a = resolve_symbol(index, args.build_a, args.query)
        except SymbolResolutionError as exc:
            print(f"in {args.build_a}: {exc}", file=sys.stderr)
            return 1
        symbols_a = index.all_symbols(args.build_a)
        symbols_b = index.all_symbols(args.build_b)

    report = compare_symbols(symbols_a, symbols_b)
    entry = next((e for e in report.all_entries if e.raw_name == target_a.raw_name), None)
    if entry is None:
        print("internal error: symbol not found in its own build's diff entries", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(_entry_to_dict(entry), indent=2))
    else:
        _print_symbol_diff_entry(entry)
    return 0


def cmd_diff_namespace(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        symbols_a = index.all_symbols(args.build_a)
        symbols_b = index.all_symbols(args.build_b)

    report = compare_symbols(symbols_a, symbols_b)
    ns = args.namespace.rstrip(":")

    def in_ns(sym: Symbol | None) -> bool:
        if sym is None or sym.namespace_path is None:
            return False
        return sym.namespace_path == ns or sym.namespace_path.startswith(ns + "::")

    entries = [
        e for e in report.all_entries if in_ns(e.symbol_a) or in_ns(e.symbol_b)
    ]

    if args.json:
        print(json.dumps([_entry_to_dict(e) for e in entries], indent=2))
    else:
        for e in entries:
            _print_symbol_diff_entry(e)
    return 0


def _entry_to_dict(entry) -> dict:  # noqa: ANN001 - SymbolDiffEntry, avoid import cycle noise
    return {
        "raw_name": entry.raw_name,
        "status": entry.status,
        "address_a": None if entry.symbol_a is None or entry.symbol_a.address is None
        else f"0x{entry.symbol_a.address:08X}",
        "address_b": None if entry.symbol_b is None or entry.symbol_b.address is None
        else f"0x{entry.symbol_b.address:08X}",
        "address_moved": entry.address_moved,
        "inferred_size_a": entry.inferred_size_a,
        "inferred_size_b": entry.inferred_size_b,
        "size_changed": entry.size_changed,
        "object_changed": entry.object_changed,
        "library_changed": entry.library_changed,
        "visibility_changed": entry.visibility_changed,
    }


def _print_symbol_diff_entry(entry) -> None:  # noqa: ANN001
    if entry.status == "only_a":
        print(f"only in A: {entry.raw_name}")
    elif entry.status == "only_b":
        print(f"only in B: {entry.raw_name}")
    else:
        flags = []
        if entry.address_moved:
            flags.append("address moved")
        if entry.size_changed:
            flags.append(f"size {entry.inferred_size_a} -> {entry.inferred_size_b}")
        if entry.object_changed:
            flags.append("object changed")
        if entry.library_changed:
            flags.append("library changed")
        if entry.visibility_changed:
            flags.append("visibility changed")
        suffix = f"  ({', '.join(flags)})" if flags else "  (no differences)"
        print(f"both: {entry.raw_name}{suffix}")


def cmd_diff_function(args: argparse.Namespace) -> int:
    with SymbolIndex(args.db) as index:
        try:
            target_a = resolve_symbol(index, args.build_a, args.query)
        except SymbolResolutionError as exc:
            print(f"in {args.build_a}: unresolved ({exc})", file=sys.stderr)
            return 1
        try:
            target_b = resolve_symbol(index, args.build_b, args.query)
        except SymbolResolutionError as exc:
            print(f"in {args.build_b}: unresolved ({exc})", file=sys.stderr)
            return 1
        fn_symbols_a = index.function_symbols(args.build_a)
        fn_symbols_b = index.function_symbols(args.build_b)

    def slice_one(pe_path: str, target: Symbol, fn_symbols: list[Symbol], layout: str):
        pe = Path(pe_path).read_bytes()
        image_base, sections = parse_pe(pe)
        return slice_function(
            pe=pe,
            image_base=image_base,
            sections=sections,
            function_symbols_sorted=fn_symbols,
            target=target,
            layout=layout,
        )

    try:
        slice_a = slice_one(args.pe_a, target_a, fn_symbols_a, args.layout_a)
    except FunctionSliceError as exc:
        print(json.dumps({"classification": "unresolved", "reason": f"build A: {exc}"}, indent=2))
        return 1
    try:
        slice_b = slice_one(args.pe_b, target_b, fn_symbols_b, args.layout_b)
    except FunctionSliceError as exc:
        print(json.dumps({"classification": "unresolved", "reason": f"build B: {exc}"}, indent=2))
        return 1

    result = classify_function_diff(slice_a.blob, slice_b.blob)
    payload = {
        "query": args.query,
        "symbol_a": target_a.raw_name,
        "symbol_b": target_b.raw_name,
        **asdict(result),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{target_a.raw_name}  vs  {target_b.raw_name}")
        print(f"  classification: {result.classification}")
        print(f"  size: {result.size_a} -> {result.size_b} (delta {result.size_delta:+d})")
        print(f"  similarity: {result.similarity:.2%}")
        if result.differing_word_offsets:
            offsets = ", ".join(f"+0x{o:X}" for o in result.differing_word_offsets[:16])
            print(f"  differing word offsets: {offsets}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    build_parser_ = subparsers.add_parser("build", help="build-identity verification")
    build_sub = build_parser_.add_subparsers(dest="build_command", required=True)

    p_verify = build_sub.add_parser(
        "verify", help="verify local artifacts against an identity file"
    )
    p_verify.add_argument("build")
    p_verify.add_argument("--identity", required=True, help="path to a build_identity.json")
    p_verify.add_argument("--xex")
    p_verify.add_argument("--pe")
    p_verify.add_argument("--map", dest="map_path")
    p_verify.add_argument("--json", action="store_true")
    p_verify.set_defaults(func=cmd_build_verify)

    function_parser = subparsers.add_parser("function", help="function boundary/slice inspection")
    function_sub = function_parser.add_subparsers(dest="function_command", required=True)

    p_show = function_sub.add_parser("show", help="slice one function from a PE image")
    p_show.add_argument("build")
    p_show.add_argument("query", help="raw/demangled name, substring, or address")
    p_show.add_argument("--pe", required=True, help="extracted PE image path")
    p_show.add_argument("--db", default=DEFAULT_DB_PATH)
    p_show.add_argument("--layout", choices=VALID_IMAGE_LAYOUTS, default=IMAGE_LAYOUT_XBOX_RVA)
    p_show.add_argument("--max-bytes", type=lambda v: int(v, 0), default=None)
    p_show.add_argument(
        "--size", type=lambda v: int(v, 0), default=None, help="override inferred size"
    )
    p_show.add_argument("--show-words", action="store_true", help="print raw PPC words (text mode)")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=cmd_function_show)

    diff_parser = subparsers.add_parser("diff", help="cross-build symbol/function comparison")
    diff_sub = diff_parser.add_subparsers(dest="diff_command", required=True)

    p_dsym = diff_sub.add_parser("symbol", help="compare one symbol across two builds")
    p_dsym.add_argument("build_a")
    p_dsym.add_argument("build_b")
    p_dsym.add_argument("query")
    p_dsym.add_argument("--db", default=DEFAULT_DB_PATH)
    p_dsym.add_argument("--json", action="store_true")
    p_dsym.set_defaults(func=cmd_diff_symbol)

    p_dns = diff_sub.add_parser("namespace", help="compare a namespace's symbols across two builds")
    p_dns.add_argument("build_a")
    p_dns.add_argument("build_b")
    p_dns.add_argument("namespace")
    p_dns.add_argument("--db", default=DEFAULT_DB_PATH)
    p_dns.add_argument("--json", action="store_true")
    p_dns.set_defaults(func=cmd_diff_namespace)

    p_dfn = diff_sub.add_parser("function", help="byte-level function comparison across two builds")
    p_dfn.add_argument("build_a")
    p_dfn.add_argument("build_b")
    p_dfn.add_argument("query")
    p_dfn.add_argument("--pe-a", required=True)
    p_dfn.add_argument("--pe-b", required=True)
    p_dfn.add_argument("--layout-a", choices=VALID_IMAGE_LAYOUTS, default=IMAGE_LAYOUT_XBOX_RVA)
    p_dfn.add_argument("--layout-b", choices=VALID_IMAGE_LAYOUTS, default=IMAGE_LAYOUT_XBOX_RVA)
    p_dfn.add_argument("--db", default=DEFAULT_DB_PATH)
    p_dfn.add_argument("--json", action="store_true")
    p_dfn.set_defaults(func=cmd_diff_function)
