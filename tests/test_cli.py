from __future__ import annotations

import json

from fncre.cli.main import main


def _run(capsys, args):
    exit_code = main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_map_index_then_symbols_exact(fixtures_dir, tmp_path, capsys):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")

    code, out, _ = _run(
        capsys, ["map", "index", map_path, "--build", "fn5d", "--db", db_path, "--json"]
    )
    assert code == 0
    summary = json.loads(out)
    assert summary["total_symbols"] == 17
    assert summary["public_count"] == 15
    assert summary["static_count"] == 2

    code, out, _ = _run(
        capsys,
        ["symbols", "exact", "fn5d", "FightSim::UpdateHealth", "--db", db_path, "--json"],
    )
    assert code == 0
    results = json.loads(out)
    assert len(results) == 1
    assert results[0]["address_hex"] == "0x83601B80"


def test_symbols_search_and_address(fixtures_dir, tmp_path, capsys):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    main(["map", "index", map_path, "--build", "fn5d", "--db", db_path])
    capsys.readouterr()

    code, out, _ = _run(capsys, ["symbols", "search", "fn5d", "FightSim::", "--db", db_path])
    assert code == 0
    assert "FightSim::UpdateEnergy" in out

    code, out, _ = _run(
        capsys, ["symbols", "address", "fn5d", "0x83601B80", "--db", db_path]
    )
    assert code == 0
    assert "FightSim::UpdateHealth" in out


def test_symbols_exact_missing_returns_nonzero(fixtures_dir, tmp_path, capsys):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    main(["map", "index", map_path, "--build", "fn5d", "--db", db_path])
    capsys.readouterr()

    code, out, _ = _run(
        capsys, ["symbols", "exact", "fn5d", "NoSuch::Symbol", "--db", db_path]
    )
    assert code == 1
    assert "no matches" in out


def test_map_parse_without_indexing_does_not_create_db(fixtures_dir, tmp_path, capsys):
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    code, out, _ = _run(capsys, ["map", "parse", map_path, "--json"])
    assert code == 0
    payload = json.loads(out)
    assert payload["stats"]["total_symbols"] == 17
    assert not (tmp_path / "index.db").exists()


def test_symbols_namespace_cli(fixtures_dir, tmp_path, capsys):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    main(["map", "index", map_path, "--build", "fn5d", "--db", db_path])
    capsys.readouterr()

    code, out, _ = _run(
        capsys, ["symbols", "namespace", "fn5d", "FightSim", "--db", db_path, "--json"]
    )
    assert code == 0
    results = json.loads(out)
    assert all(r["namespace_path"] == "FightSim" for r in results)
    assert len(results) == 9
