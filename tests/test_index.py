from __future__ import annotations

from fncre.symbols.index import SymbolIndex
from fncre.symbols.map_parser import parse_map_file


def _index_fixture(fixtures_dir, tmp_path, filename, build_id):
    parsed = parse_map_file(fixtures_dir / filename)
    index = SymbolIndex(tmp_path / "index.db")
    index.index_parsed_map(build_id, parsed)
    return index


def test_index_and_exact_lookup(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        results = index.exact("fn5d", "FightSim::UpdateHealth")
        assert len(results) == 1
        assert results[0].address == 0x83601B80
    finally:
        index.close()


def test_search_substring(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        results = index.search("fn5d", "FightSim::")
        names = {s.name for s in results}
        assert "FightSim::UpdateEnergy" in names
        assert "FightSim::ThrowPunch" in names
        assert all(n.startswith("FightSim::") for n in names)
    finally:
        index.close()


def test_address_exact_and_range(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        exact = index.by_address("fn5d", 0x83601B80)
        assert len(exact) == 1
        assert exact[0].name == "FightSim::UpdateHealth"

        ranged = index.address_range("fn5d", 0x83601000, 0x83603000)
        names = {s.name for s in ranged}
        assert "FightSim::UpdateEnergy" in names
        assert "FightSim::ThrowPunch" in names
        assert "RankingFormula::CalculateWinRank" not in names
    finally:
        index.close()


def test_namespace_and_object_and_library(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        ns_results = index.by_namespace("fn5d", "FightSim")
        assert {s.leaf for s in ns_results} >= {"UpdateEnergy", "UpdateHealth", "ThrowPunch"}

        obj_results = index.by_object("fn5d", "fightsim.obj")
        assert any(s.name == "FightSim::UpdateEnergy" for s in obj_results)

        lib_results = index.by_library("fn5d", "rankingformula")
        assert {s.name for s in lib_results} == {
            "RankingFormula::CalculateWinRank",
            "RankingFormula::CalculateLoseRank",
        }
    finally:
        index.close()


def test_visibility_filter(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        static_results = index.by_visibility("fn5d", "static")
        assert {s.name for s in static_results if not s.is_mangled} == {"LegacyModeLogic::Tick"}
        public_results = index.by_visibility("fn5d", "public")
        assert len(public_results) == 15
    finally:
        index.close()


def test_nearest_before_and_after(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        # Halfway between UpdateEnergy (0x836016c0) and UpdateFatigue (0x83601950)
        probe = 0x83601800
        before = index.nearest_before("fn5d", probe)
        after = index.nearest_after("fn5d", probe)
        assert before.name == "FightSim::UpdateEnergy"
        assert after.name == "FightSim::UpdateFatigue"

        exact_before = index.nearest_before("fn5d", 0x83601B80)
        assert exact_before.name == "FightSim::UpdateHealth"
    finally:
        index.close()


def test_reindexing_build_replaces_rows_deterministically(fixtures_dir, tmp_path):
    parsed = parse_map_file(fixtures_dir / "synthetic_fn5d_style.map.txt")
    index = SymbolIndex(tmp_path / "index.db")
    try:
        index.index_parsed_map("fn5d", parsed)
        first_count = index.build_summary("fn5d").total_symbols

        index.index_parsed_map("fn5d", parsed)
        second_count = index.build_summary("fn5d").total_symbols

        assert first_count == second_count == 17
        assert len(index.exact("fn5d", "FightSim::UpdateEnergy")) == 1
    finally:
        index.close()


def test_duplicate_names_and_addresses_are_preserved_not_deduped(fixtures_dir, tmp_path):
    index = _index_fixture(
        fixtures_dir, tmp_path, "publics_by_name_and_duplicates.map.txt", "dup"
    )
    try:
        alpha_one = index.exact("dup", "Alpha::One")
        assert len(alpha_one) == 2  # both kept, from different objects

        shared_addr = index.by_address("dup", 0x82000010)
        assert len(shared_addr) == 2  # Alpha::Two and Beta::Aliased alias the address
    finally:
        index.close()


def test_multiple_builds_coexist_in_one_db(fixtures_dir, tmp_path):
    db_path = tmp_path / "index.db"
    index = SymbolIndex(db_path)
    try:
        index.index_parsed_map(
            "fn5d", parse_map_file(fixtures_dir / "synthetic_fn5d_style.map.txt")
        )
        index.index_parsed_map("minimal", parse_map_file(fixtures_dir / "minimal_valid.map.txt"))

        assert set(index.list_builds()) == {"fn5d", "minimal"}
        assert len(index.exact("fn5d", "FightSim::UpdateEnergy")) == 1
        assert len(index.exact("minimal", "FightSim::UpdateEnergy")) == 0
        assert len(index.exact("minimal", "Foo::Bar")) == 1
    finally:
        index.close()
