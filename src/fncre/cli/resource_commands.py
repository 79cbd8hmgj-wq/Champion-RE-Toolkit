"""`fncre attrib`, `fncre archive`, and `fncre tunables` subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from fncre.archive.big import ArchiveFormatError, parse_big, read_entry, safe_extract_path
from fncre.archive.chunkzip import ChunkzipError, decompress_chunkzip
from fncre.attrib.hash import attrib_hash
from fncre.attrib.keys import AttribKeyIndex
from fncre.attrib.keys_import import parse_generated_keys_csv, parse_wordlist
from fncre.attrib.pipeline import PipelineError, extract_tunables
from fncre.attrib.vault import VaultFormatError, iter_vault_chunks

DEFAULT_KEYS_DB = ".fncre/attrib_keys.db"


# -- fncre attrib hash / hash-file -----------------------------------------


def cmd_attrib_hash(args: argparse.Namespace) -> int:
    results = [{"text": text, "hash": attrib_hash(text)} for text in args.text]
    if args.json:
        print(json.dumps([{**r, "hash_hex": f"0x{r['hash']:08X}"} for r in results], indent=2))
    else:
        for r in results:
            print(f"0x{r['hash']:08X}  {r['text']}")
    return 0


def cmd_attrib_hash_file(args: argparse.Namespace) -> int:
    rows = parse_wordlist(args.file)
    if args.json:
        print(
            json.dumps(
                [{"text": text, "hash": h, "hash_hex": f"0x{h:08X}"} for h, text in rows], indent=2
            )
        )
    else:
        for h, text in rows:
            print(f"0x{h:08X}  {text}")
    return 0


# -- fncre attrib keys ------------------------------------------------------


def cmd_attrib_keys_import(args: argparse.Namespace) -> int:
    path = Path(args.file)
    with AttribKeyIndex(args.db) as index:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().strip()
        if header == "cpp_name,source_name,hash":
            rows = parse_generated_keys_csv(path)
            inserted = 0
            for h, text, _cpp, provenance in rows:
                if index.add(
                    args.build,
                    hash_value=h,
                    text=text,
                    status="evidenced",
                    source=str(path),
                    provenance=provenance,
                ):
                    inserted += 1
            total = len(rows)
        else:
            if not args.status:
                print(
                    f"error: {path} is not a generated_attrib_keys.py-style CSV "
                    "(expected header 'cpp_name,source_name,hash'); "
                    "pass --status for a plain wordlist import",
                    file=sys.stderr,
                )
                return 1
            wordlist_rows = parse_wordlist(path)
            inserted = 0
            for h, text in wordlist_rows:
                if index.add(
                    args.build, hash_value=h, text=text, status=args.status, source=str(path)
                ):
                    inserted += 1
            total = len(wordlist_rows)

    result = {
        "file": str(path),
        "total_rows": total,
        "inserted": inserted,
        "duplicates_skipped": total - inserted,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        skipped = total - inserted
        print(f"imported {inserted}/{total} rows from {path} ({skipped} duplicate(s) skipped)")
    return 0


def cmd_attrib_keys_search(args: argparse.Namespace) -> int:
    with AttribKeyIndex(args.db) as index:
        results = index.search(args.build, args.text)
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        for r in results:
            print(f"0x{r.hash:08X}  [{r.status}]  {r.text}  ({r.source or '-'})")
        if not results:
            print("(no matches)")
    return 0


def cmd_attrib_keys_lookup(args: argparse.Namespace) -> int:
    try:
        h = int(args.hash, 0)
    except ValueError:
        h = int(args.hash, 16)
    with AttribKeyIndex(args.db) as index:
        results = index.lookup(args.build, h)
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        if not results:
            print("(unresolved: no candidate text known for this hash)")
        for r in results:
            print(f"[{r.status}]  {r.text}  ({r.source or '-'})")
    return 0 if results else 1


def cmd_attrib_keys_stats(args: argparse.Namespace) -> int:
    with AttribKeyIndex(args.db) as index:
        stats = index.stats(args.build)
    if args.json:
        print(json.dumps(asdict(stats), indent=2))
    else:
        print(f"build: {stats.build_id}")
        print(f"  total rows       : {stats.total}")
        for status, count in stats.by_status.items():
            print(f"  {status:<10}: {count}")
        print(f"  distinct hashes  : {stats.distinct_hashes}")
        print(f"  hash collisions  : {stats.collisions}")
    return 0


# -- fncre attrib inspect / extract -----------------------------------------


def cmd_attrib_inspect(args: argparse.Namespace) -> int:
    data = Path(args.file).read_bytes()
    try:
        chunks = list(iter_vault_chunks(data))
    except VaultFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "file": str(args.file),
                    "size": len(data),
                    "chunks": [
                        {"offset": c.offset, "tag": c.name, "size": c.size, "role": c.role}
                        for c in chunks
                    ],
                },
                indent=2,
            )
        )
    else:
        print(f"file: {args.file}  size: 0x{len(data):X} ({len(data)})")
        for c in chunks:
            print(f"  0x{c.offset:08X}  {c.name:<4}  size=0x{c.size:08X} ({c.size:>8})  {c.role}")
        tags = {c.tag for c in chunks}
        missing = [t.decode() for t in (b"DepN", b"PtrN", b"ExpN") if t not in tags]
        if missing:
            print("required chunks not observed: " + ", ".join(missing))
        else:
            print("required chunks observed: DepN, PtrN, ExpN")
    return 0


def cmd_attrib_extract(args: argparse.Namespace) -> int:
    vlt_path = Path(args.file)
    bin_path = Path(args.bin) if args.bin else vlt_path.with_suffix(".bin")
    if not bin_path.exists():
        print(f"error: no .bin file at {bin_path} (pass --bin)", file=sys.stderr)
        return 1

    key_index = AttribKeyIndex(args.keys) if args.keys else None
    try:
        result = extract_tunables(
            vlt_path,
            build_id=args.build,
            class_name=args.class_name,
            collection_name=args.collection,
            key_index=key_index,
            bin_path_override=bin_path,
        )
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if key_index is not None:
            key_index.close()

    payload = result.to_json_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"class={args.class_name}  collection={args.collection}  "
            f"records={len(result.records)}"
        )
        for r in result.records:
            name = r.resolved_text or f"0x{r.key_hash:08X}"
            print(f"  [{r.resolution_status:<12}] {name} = {r.value!r}")
    return 0


# -- fncre archive -----------------------------------------------------------


def cmd_archive_inspect(args: argparse.Namespace) -> int:
    data = Path(args.file).read_bytes()
    try:
        archive = parse_big(data)
    except ArchiveFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = {
        "file": str(args.file),
        "entries": archive.count,
        "folders": archive.folder_count,
        "data_start": f"0x{archive.data_start:X}",
        "archive_size": archive.archive_size,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"  {key}: {value}")
    return 0


def cmd_archive_list(args: argparse.Namespace) -> int:
    data = Path(args.file).read_bytes()
    try:
        archive = parse_big(data)
    except ArchiveFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    entries = [e for e in archive.entries if not args.match or args.match.lower() in e.path.lower()]
    if args.json:
        print(json.dumps([asdict(e) | {"path": e.path} for e in entries], indent=2))
    else:
        for e in entries:
            print(f"{e.index:5d}  0x{e.offset:08X}  0x{e.stored_size:08X}  {e.path}")
    return 0


def cmd_archive_extract(args: argparse.Namespace) -> int:
    data = Path(args.file).read_bytes()
    try:
        archive = parse_big(data)
    except ArchiveFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    terms = [m.lower() for m in args.match] if args.match else None
    selected = [
        e for e in archive.entries if terms is None or any(t in e.path.lower() for t in terms)
    ]

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for entry in selected:
        try:
            raw = read_entry(data, entry)
            payload = raw if args.keep_chunkzip else decompress_chunkzip(raw)
        except (ArchiveFormatError, ChunkzipError) as exc:
            print(f"error extracting {entry.path}: {exc}", file=sys.stderr)
            return 1

        try:
            dest = safe_extract_path(output_dir, entry)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        written.append({"path": entry.path, "output": str(dest), "size": len(payload)})

    if args.json:
        print(json.dumps(written, indent=2))
    else:
        for w in written:
            print(f"{w['path']} -> {w['output']} ({w['size']} bytes)")
    return 0


# -- fncre tunables extract ---------------------------------------------------


def cmd_tunables_extract(args: argparse.Namespace) -> int:
    key_index = AttribKeyIndex(args.keys) if args.keys else None
    try:
        result = extract_tunables(
            args.input,
            build_id=args.build,
            class_name=args.class_name,
            collection_name=args.collection,
            key_index=key_index,
            bin_path_override=args.bin,
        )
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if key_index is not None:
            key_index.close()

    payload = result.to_json_dict()
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{args.collection}.json"
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out_path}  ({len(result.records)} records)")
    elif args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"class={args.class_name}  collection={args.collection}  "
            f"records={len(result.records)}"
        )
        resolved = sum(1 for r in result.records if r.resolved_text)
        print(f"  resolved names: {resolved}/{len(result.records)}")
    return 0


# -- registration -------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction) -> None:  # noqa: SLF001
    attrib_parser = subparsers.add_parser(
        "attrib", help="AttribSys hashing, keys, and vault extraction"
    )
    attrib_sub = attrib_parser.add_subparsers(dest="attrib_command", required=True)

    p_hash = attrib_sub.add_parser("hash", help="hash one or more keys")
    p_hash.add_argument("text", nargs="+")
    p_hash.add_argument("--json", action="store_true")
    p_hash.set_defaults(func=cmd_attrib_hash)

    p_hash_file = attrib_sub.add_parser("hash-file", help="hash every key in a wordlist file")
    p_hash_file.add_argument("file")
    p_hash_file.add_argument("--json", action="store_true")
    p_hash_file.set_defaults(func=cmd_attrib_hash_file)

    keys_parser = attrib_sub.add_parser("keys", help="attribute-key/hash index")
    keys_sub = keys_parser.add_subparsers(dest="keys_command", required=True)

    def add_common_keys(p: argparse.ArgumentParser) -> None:
        p.add_argument("--db", default=DEFAULT_KEYS_DB)
        p.add_argument("--json", action="store_true")

    p_import = keys_sub.add_parser("import", help="import a generated-keys CSV or a plain wordlist")
    p_import.add_argument("file")
    p_import.add_argument("--build", required=True)
    p_import.add_argument(
        "--status",
        choices=["generated", "inferred"],
        help="required for a plain wordlist; CSV rows import as 'evidenced' automatically",
    )
    add_common_keys(p_import)
    p_import.set_defaults(func=cmd_attrib_keys_import)

    p_search = keys_sub.add_parser("search", help="substring search over resolved key text")
    p_search.add_argument("build")
    p_search.add_argument("text")
    add_common_keys(p_search)
    p_search.set_defaults(func=cmd_attrib_keys_search)

    p_lookup = keys_sub.add_parser("lookup", help="look up all candidates for a hash")
    p_lookup.add_argument("build")
    p_lookup.add_argument("hash")
    add_common_keys(p_lookup)
    p_lookup.set_defaults(func=cmd_attrib_keys_lookup)

    p_stats = keys_sub.add_parser("stats", help="summary counts for a build's key index")
    p_stats.add_argument("build")
    add_common_keys(p_stats)
    p_stats.set_defaults(func=cmd_attrib_keys_stats)

    p_inspect = attrib_sub.add_parser("inspect", help="inspect a .vlt file's chunk structure")
    p_inspect.add_argument("file")
    p_inspect.add_argument("--json", action="store_true")
    p_inspect.set_defaults(func=cmd_attrib_inspect)

    p_extract = attrib_sub.add_parser("extract", help="extract one class/collection from a vault")
    p_extract.add_argument("file", help=".vlt file path")
    p_extract.add_argument("--bin", help="matching .bin file (default: same stem, .bin)")
    p_extract.add_argument("--build", required=True)
    p_extract.add_argument("--class-name", required=True)
    p_extract.add_argument("--collection", required=True)
    p_extract.add_argument("--keys", help="attribute-key index DB to resolve names against")
    p_extract.add_argument("--json", action="store_true")
    p_extract.set_defaults(func=cmd_attrib_extract)

    archive_parser = subparsers.add_parser(
        "archive", help="EA BIG/EB archive inspection/extraction"
    )
    archive_sub = archive_parser.add_subparsers(dest="archive_command", required=True)

    p_ainspect = archive_sub.add_parser("inspect", help="show archive header summary")
    p_ainspect.add_argument("file")
    p_ainspect.add_argument("--json", action="store_true")
    p_ainspect.set_defaults(func=cmd_archive_inspect)

    p_alist = archive_sub.add_parser("list", help="list archive entries")
    p_alist.add_argument("file")
    p_alist.add_argument("--match", help="case-insensitive substring filter")
    p_alist.add_argument("--json", action="store_true")
    p_alist.set_defaults(func=cmd_archive_list)

    p_aextract = archive_sub.add_parser("extract", help="extract matching archive entries")
    p_aextract.add_argument("file")
    p_aextract.add_argument("--output", required=True)
    p_aextract.add_argument(
        "--match", action="append", help="case-insensitive substring; repeatable"
    )
    p_aextract.add_argument("--keep-chunkzip", action="store_true")
    p_aextract.add_argument("--json", action="store_true")
    p_aextract.set_defaults(func=cmd_archive_extract)

    tunables_parser = subparsers.add_parser(
        "tunables", help="unified archive/vault -> tunables workflow"
    )
    tunables_sub = tunables_parser.add_subparsers(dest="tunables_command", required=True)

    p_textract = tunables_sub.add_parser(
        "extract", help="run the full archive/vault -> resolved-values pipeline"
    )
    p_textract.add_argument("--build", required=True)
    p_textract.add_argument("--input", required=True, help="a BIG archive or a .vlt file")
    p_textract.add_argument(
        "--bin", help="matching .bin file, if --input is a .vlt with a different stem"
    )
    p_textract.add_argument("--class-name", required=True)
    p_textract.add_argument("--collection", required=True)
    p_textract.add_argument("--keys", help="attribute-key index DB to resolve names against")
    p_textract.add_argument("--output", help="directory to write <collection>.json into")
    p_textract.add_argument("--json", action="store_true")
    p_textract.set_defaults(func=cmd_tunables_extract)
