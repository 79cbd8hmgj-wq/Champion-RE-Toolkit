from __future__ import annotations

import json

from fncre.cli.main import main
from tests.big_fixture import FileSpec, build_big
from tests.vault_fixture import (
    ARRAY_FIELD_NAME,
    CLASS_NAME,
    COLLECTION_NAME,
    INLINE_FIELD_NAME,
    INLINE_VALUE,
    build_vault,
)


def _run(capsys, args):
    exit_code = main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_attrib_hash_cli_matches_known_vector(capsys):
    code, out, _ = _run(capsys, ["attrib", "hash", "fight_sim", "--json"])
    assert code == 0
    payload = json.loads(out)
    assert payload[0]["hash_hex"] == "0xA9244D34"


def test_attrib_hash_file_cli(tmp_path, capsys):
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("fight_sim\nscheduling\n")
    code, out, _ = _run(capsys, ["attrib", "hash-file", str(wordlist)])
    assert code == 0
    assert "0xA9244D34  fight_sim" in out


def test_attrib_keys_import_search_lookup_stats(tmp_path, capsys):
    csv_path = tmp_path / "keys.csv"
    csv_path.write_text("cpp_name,source_name,hash\nkey_fight_sim,fight_sim,0xA9244D34\n")
    db_path = str(tmp_path / "keys.db")

    code, out, _ = _run(
        capsys, ["attrib", "keys", "import", str(csv_path), "--build", "fn5d", "--db", db_path]
    )
    assert code == 0
    assert "imported 1/1" in out

    code, out, _ = _run(
        capsys, ["attrib", "keys", "lookup", "fn5d", "0xA9244D34", "--db", db_path, "--json"]
    )
    assert code == 0
    results = json.loads(out)
    assert results[0]["text"] == "fight_sim"
    assert results[0]["status"] == "evidenced"

    code, out, _ = _run(
        capsys, ["attrib", "keys", "search", "fn5d", "fight", "--db", db_path]
    )
    assert code == 0
    assert "fight_sim" in out

    code, out, _ = _run(capsys, ["attrib", "keys", "stats", "fn5d", "--db", db_path, "--json"])
    assert code == 0
    stats = json.loads(out)
    assert stats["total"] == 1
    assert stats["by_status"]["evidenced"] == 1


def test_attrib_keys_lookup_missing_hash_returns_nonzero(tmp_path, capsys):
    db_path = str(tmp_path / "keys.db")
    code, out, _ = _run(capsys, ["attrib", "keys", "lookup", "fn5d", "0xDEADBEEF", "--db", db_path])
    assert code == 1
    assert "unresolved" in out


def test_attrib_inspect_and_extract_cli(tmp_path, capsys):
    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    (tmp_path / "attribdb.bin").write_bytes(built.bin)
    vlt_path.write_bytes(built.vlt)

    code, out, _ = _run(capsys, ["attrib", "inspect", str(vlt_path), "--json"])
    assert code == 0
    payload = json.loads(out)
    assert [c["tag"] for c in payload["chunks"]] == ["Vers", "DepN", "ExpN", "PtrN", "DatN", "EndC"]

    code, out, _ = _run(
        capsys,
        [
            "attrib", "extract", str(vlt_path),
            "--build", "fn5d", "--class-name", CLASS_NAME, "--collection", COLLECTION_NAME,
            "--json",
        ],
    )
    assert code == 0
    payload = json.loads(out)
    assert len(payload["records"]) == 3
    inline = next(r for r in payload["records"] if r["value"] == INLINE_VALUE)
    assert inline["key_hash_hex"]


def test_archive_inspect_list_extract_cli(tmp_path, capsys):
    archive_bytes = build_big(
        [
            FileSpec("folder", "one.bin", b"payload-one"),
            FileSpec("folder", "two.bin", b"payload-two"),
        ]
    )
    archive_path = tmp_path / "test.big"
    archive_path.write_bytes(archive_bytes)

    code, out, _ = _run(capsys, ["archive", "inspect", str(archive_path), "--json"])
    assert code == 0
    assert json.loads(out)["entries"] == 2

    code, out, _ = _run(capsys, ["archive", "list", str(archive_path), "--json"])
    assert code == 0
    entries = json.loads(out)
    assert {e["path"] for e in entries} == {"folder/one.bin", "folder/two.bin"}

    output_dir = tmp_path / "extracted"
    code, out, _ = _run(
        capsys,
        ["archive", "extract", str(archive_path), "--output", str(output_dir), "--match", "one"],
    )
    assert code == 0
    assert (output_dir / "folder" / "one.bin").read_bytes() == b"payload-one"
    assert not (output_dir / "folder" / "two.bin").exists()


def test_tunables_extract_cli_writes_output_file(tmp_path, capsys):
    built = build_vault()
    vlt_path = tmp_path / "attribdb.vlt"
    (tmp_path / "attribdb.bin").write_bytes(built.bin)
    vlt_path.write_bytes(built.vlt)

    keys_csv = tmp_path / "keys.csv"
    keys_csv.write_text(f"cpp_name,source_name,hash\nkey_{INLINE_FIELD_NAME},{INLINE_FIELD_NAME},0x0\n")
    keys_db = str(tmp_path / "keys.db")
    _run(capsys, ["attrib", "keys", "import", str(keys_csv), "--build", "fn5d", "--db", keys_db])

    output_dir = tmp_path / "out"
    code, out, _ = _run(
        capsys,
        [
            "tunables", "extract",
            "--build", "fn5d",
            "--input", str(vlt_path),
            "--class-name", CLASS_NAME,
            "--collection", COLLECTION_NAME,
            "--keys", keys_db,
            "--output", str(output_dir),
        ],
    )
    assert code == 0
    out_file = output_dir / f"{COLLECTION_NAME}.json"
    assert out_file.exists()
    payload = json.loads(out_file.read_text())
    resolved = [r for r in payload["records"] if r["resolved_text"] == INLINE_FIELD_NAME]
    assert len(resolved) == 1
    assert resolved[0]["resolution_status"] == "evidenced"
    assert ARRAY_FIELD_NAME  # imported for readability/consistency with other tests
