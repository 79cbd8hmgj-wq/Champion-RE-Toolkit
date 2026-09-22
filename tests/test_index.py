from __future__ import annotations

from fncre.symbols import demangle
from fncre.symbols.index import SymbolIndex
from fncre.symbols.map_parser import parse_map_file

UPDATE_ENERGY_RAW = "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ"
UPDATE_HEALTH_RAW = "?UpdateHealth@FightSim@LegacyModeLogic@@QAAXXZ"
THROW_PUNCH_RAW = "?ThrowPunch@FightSim@LegacyModeLogic@@QAAXXZ"
WIN_RANK_RAW = "?CalculateWinRank@RankingFormula@@QAAHXZ"
LOSE_RANK_RAW = "?CalculateLoseRank@RankingFormula@@QAAHXZ"


def _index_fixture(fixtures_dir, tmp_path, filename, build_id, *, demangled=True):
    parsed = parse_map_file(fixtures_dir / filename)
    if demangled:
        parsed = demangle.demangle_parsed_map(parsed)
    index = SymbolIndex(tmp_path / "index.db")
    index.index_parsed_map(build_id, parsed)
    return index


def test_index_and_exact_lookup_by_raw_name(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        results = index.exact("fn5d", UPDATE_HEALTH_RAW)
        assert len(results) == 1
        assert results[0].address == 0x83601B80
    finally:
        index.close()


def test_exact_lookup_by_demangled_name_resolves_same_symbol(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        by_raw = index.exact("fn5d", UPDATE_HEALTH_RAW)
        by_demangled = index.exact(
            "fn5d", "LegacyModeLogic::FightSim::UpdateHealth"
        )
        assert len(by_raw) == 1
        assert len(by_demangled) == 1
        assert by_raw[0].address == by_demangled[0].address == 0x83601B80
        assert by_raw[0].raw_name == by_demangled[0].raw_name == UPDATE_HEALTH_RAW
    finally:
        index.close()


def test_search_substring_matches_raw_and_demangled(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        by_raw_substr = index.search("fn5d", "@FightSim@LegacyModeLogic@")
        by_demangled_substr = index.search("fn5d", "LegacyModeLogic::FightSim::")

        raw_names = {s.raw_name for s in by_raw_substr}
        demangled_names = {s.raw_name for s in by_demangled_substr}
        assert UPDATE_ENERGY_RAW in raw_names
        assert THROW_PUNCH_RAW in raw_names
        assert raw_names == demangled_names
    finally:
        index.close()


def test_address_exact_and_range(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        exact = index.by_address("fn5d", 0x83601B80)
        assert len(exact) == 1
        assert exact[0].raw_name == UPDATE_HEALTH_RAW

        ranged = index.address_range("fn5d", 0x83601000, 0x83603000)
        raw_names = {s.raw_name for s in ranged}
        assert UPDATE_ENERGY_RAW in raw_names
        assert THROW_PUNCH_RAW in raw_names
        assert WIN_RANK_RAW not in raw_names
    finally:
        index.close()


def test_namespace_prefers_demangled_structure(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        ns_results = index.by_namespace("fn5d", "LegacyModeLogic::FightSim")
        assert {s.leaf for s in ns_results} >= {"UpdateEnergy", "UpdateHealth", "ThrowPunch"}
        assert all(s.namespace_path == "LegacyModeLogic::FightSim" for s in ns_results)

        obj_results = index.by_object("fn5d", "fightsim.obj")
        assert any(s.raw_name == UPDATE_ENERGY_RAW for s in obj_results)

        lib_results = index.by_library("fn5d", "rankingformula")
        assert {s.raw_name for s in lib_results} == {WIN_RANK_RAW, LOSE_RANK_RAW}
    finally:
        index.close()


def test_namespace_falls_back_without_demangling(fixtures_dir, tmp_path):
    """Without the demangle pass, mangled symbols have no namespace_path at all."""
    index = _index_fixture(
        fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d", demangled=False
    )
    try:
        assert index.by_namespace("fn5d", "LegacyModeLogic::FightSim") == []
        # The raw mangled name is still fully queryable.
        assert len(index.exact("fn5d", UPDATE_ENERGY_RAW)) == 1
    finally:
        index.close()


def test_visibility_filter(fixtures_dir, tmp_path):
    index = _index_fixture(fixtures_dir, tmp_path, "synthetic_fn5d_style.map.txt", "fn5d")
    try:
        static_results = index.by_visibility("fn5d", "static")
        assert {s.raw_name for s in static_results if not s.is_mangled} == set()
        assert len(static_results) == 2
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
        assert before.raw_name == UPDATE_ENERGY_RAW
        assert after.raw_name == "?UpdateFatigue@FightSim@LegacyModeLogic@@QAAXXZ"

        exact_before = index.nearest_before("fn5d", 0x83601B80)
        assert exact_before.raw_name == UPDATE_HEALTH_RAW
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
        assert len(index.exact("fn5d", UPDATE_ENERGY_RAW)) == 1
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


def test_flags_and_visibility_duplicate_symbol_across_sections(fixtures_dir, tmp_path):
    index = _index_fixture(
        fixtures_dir, tmp_path, "real_format_flags_and_duplicates.map.txt", "fn5d"
    )
    try:
        both = index.exact("fn5d", UPDATE_ENERGY_RAW)
        assert len(both) == 2
        assert {s.visibility for s in both} == {"public", "static"}
        assert {s.address for s in both} == {0x836016C0, 0x83602000}

        by_addr = index.by_address("fn5d", 0x836016C0)
        assert {s.raw_name for s in by_addr} == {UPDATE_ENERGY_RAW, THROW_PUNCH_RAW}

        fatigue = index.exact(
            "fn5d", "?UpdateFatigue@FightSim@LegacyModeLogic@@QAAXXZ"
        )
        assert len(fatigue) == 1
        assert fatigue[0].raw_flags == "f i"
        assert fatigue[0].is_function is True
        assert fatigue[0].is_internal is True
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
        assert len(index.exact("fn5d", UPDATE_ENERGY_RAW)) == 1
        assert len(index.exact("minimal", UPDATE_ENERGY_RAW)) == 0
        assert len(index.exact("minimal", "Foo::Bar")) == 1
    finally:
        index.close()
