from __future__ import annotations

import hashlib
import json

from fncre.cli.main import main
from fncre.symbols.index import SymbolIndex
from fncre.symbols.map_parser import parse_map_file
from tests.pe_builder import build_pe32

IMAGE_BASE = 0x82000000
UPDATE_ENERGY_RAW = "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ"


def _run(capsys, args):
    exit_code = main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _index_fixture(fixtures_dir, tmp_path, build_id="fn5d"):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    main(["map", "index", map_path, "--build", build_id, "--db", db_path])
    return db_path


def test_build_verify_cli_pass_and_fail(fixtures_dir, tmp_path, capsys):
    map_path = fixtures_dir / "synthetic_fn5d_style.map.txt"
    identity = {
        "map": {
            "anchors": [{"query": "UpdateEnergy@FightSim", "address": "0x836016C0"}],
        }
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity))

    code, out, _ = _run(
        capsys,
        [
            "build", "verify", "fn5d",
            "--identity", str(identity_path),
            "--map", str(map_path),
            "--json",
        ],
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["all_requested_validated"] is True

    bad_identity = {"map": {"anchors": [{"query": "UpdateEnergy@FightSim", "address": "0xBAD"}]}}
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad_identity))
    code, out, _ = _run(
        capsys,
        ["build", "verify", "fn5d", "--identity", str(bad_path), "--map", str(map_path), "--json"],
    )
    assert code == 1
    payload = json.loads(out)
    assert payload["all_requested_validated"] is False


def test_function_show_cli(fixtures_dir, tmp_path, capsys):
    db_path = _index_fixture(fixtures_dir, tmp_path)
    capsys.readouterr()

    update_energy_va = 0x836016C0
    section_va = update_energy_va - IMAGE_BASE
    # UpdateFatigue follows at +0x290 in the fixture; the blob must cover
    # the whole inferred size or extraction is (correctly) truncated.
    code = bytearray(0x2A0)
    branch_word = (18 << 26) | 8
    code[0:4] = branch_word.to_bytes(4, "big")
    pe_bytes = build_pe32(
        image_base=IMAGE_BASE,
        section_name=b".text",
        section_va=section_va,
        section_bytes=bytes(code),
    )
    pe_path = tmp_path / "fn5d.pe"
    pe_path.write_bytes(pe_bytes)

    code_ret, out, err = _run(
        capsys,
        [
            "function", "show", "fn5d", UPDATE_ENERGY_RAW,
            "--pe", str(pe_path), "--db", db_path, "--json",
        ],
    )
    assert code_ret == 0, err
    payload = json.loads(out)
    assert payload["raw_name"] == UPDATE_ENERGY_RAW
    assert payload["start_va"] == "0x836016C0"
    assert payload["boundary"] == "next_symbol_inferred"
    assert len(payload["branches"]) == 1
    assert payload["sha256"] == hashlib.sha256(bytes(code[:payload["size"]])).hexdigest()


def test_diff_symbol_cli_reports_both_and_only_variants(fixtures_dir, tmp_path, capsys):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    main(["map", "index", map_path, "--build", "fn5d", "--db", db_path])
    main(["map", "index", map_path, "--build", "fn5d_copy", "--db", db_path])
    capsys.readouterr()

    code, out, _ = _run(
        capsys,
        ["diff", "symbol", "fn5d", "fn5d_copy", UPDATE_ENERGY_RAW, "--db", db_path, "--json"],
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "both"
    assert payload["address_moved"] is False


def test_diff_namespace_cli(fixtures_dir, tmp_path, capsys):
    db_path = str(tmp_path / "index.db")
    map_path = str(fixtures_dir / "synthetic_fn5d_style.map.txt")
    parsed_a = parse_map_file(map_path)
    with SymbolIndex(db_path) as index:
        index.index_parsed_map("fn5d", parsed_a)
        index.index_parsed_map("fn5d_copy", parsed_a)

    from fncre.symbols import demangle as demangle_mod

    if demangle_mod.is_available():
        with SymbolIndex(db_path) as index:
            index.index_parsed_map("fn5d", demangle_mod.demangle_parsed_map(parsed_a))
            index.index_parsed_map("fn5d_copy", demangle_mod.demangle_parsed_map(parsed_a))

        code, out, _ = _run(
            capsys,
            [
                "diff", "namespace", "fn5d", "fn5d_copy",
                "LegacyModeLogic::FightSim", "--db", db_path, "--json",
            ],
        )
        assert code == 0
        payload = json.loads(out)
        assert len(payload) == 10  # matches test_symbols_namespace_cli's known count
        assert all(e["status"] == "both" for e in payload)
