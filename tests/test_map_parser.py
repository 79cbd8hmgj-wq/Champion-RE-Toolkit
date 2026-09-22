"""Parser tests against small, hand-authored synthetic fixtures.

None of these fixtures are extracted from any real Fight Night Champion
build artifact. `synthetic_fn5d_style.map.txt` is hand-written to match the
documented Xenon linker MAP layout and deliberately encodes the publicly
known FN5D validation anchors (symbol name + runtime address pairs) from
the project's manual research, purely so this suite can assert the parser
recovers name/address pairs correctly end-to-end. It is not a copy of, or
derived from, the real fn5d.xenon.map file.
"""

from __future__ import annotations

from fncre.symbols.map_parser import parse_map_file

KNOWN_FN5D_ANCHORS = {
    "FightSim::UpdateEnergy": 0x836016C0,
    "FightSim::UpdateFatigue": 0x83601950,
    "FightSim::UpdateHealth": 0x83601B80,
    "FightSim::UpdateInjury": 0x83601E38,
    "FightSim::UpdateKnockDown": 0x83601E98,
    "FightSim::UpdateFoul": 0x836020D8,
    "FightSim::UpdateSwelling": 0x836021F0,
    "FightSim::UpdateCut": 0x83602370,
    "FightSim::ThrowPunch": 0x83602D68,
    "RankingFormula::CalculateWinRank": 0x83604868,
    "RankingFormula::CalculateLoseRank": 0x83604AB0,
}


def test_minimal_valid_map(fixtures_dir):
    parsed = parse_map_file(fixtures_dir / "minimal_valid.map.txt")

    assert parsed.header.module_name == "testmodule"
    assert parsed.header.preferred_load_address == 0x82000000
    assert parsed.header.entry_point_segment == 1
    assert parsed.header.entry_point_offset == 0

    assert len(parsed.segments) == 1
    assert parsed.segments[0].name == ".text"

    assert len(parsed.symbols) == 1
    sym = parsed.symbols[0]
    assert sym.name == "Foo::Bar"
    assert sym.address == 0x82000000
    assert sym.visibility == "public"
    assert sym.is_function is True
    assert sym.section == ".text"
    assert sym.library == "foo"
    assert sym.object_name == "foo.obj"
    assert sym.namespace_path == "Foo"
    assert sym.leaf == "Bar"
    assert sym.is_mangled is False
    assert sym.demangled_name == "Foo::Bar"

    assert parsed.stats.unparsed_line_count == 0


def test_synthetic_fn5d_style_resolves_known_anchors(fixtures_dir):
    parsed = parse_map_file(fixtures_dir / "synthetic_fn5d_style.map.txt")

    by_name = {s.name: s for s in parsed.symbols}
    for name, expected_address in KNOWN_FN5D_ANCHORS.items():
        assert name in by_name, f"missing known anchor symbol {name}"
        assert by_name[name].address == expected_address, (
            f"{name}: expected {expected_address:#010x}, "
            f"got {by_name[name].address:#010x}"
        )
        assert by_name[name].visibility == "public"
        assert by_name[name].is_function is True

    assert parsed.stats.total_symbols == 17
    assert parsed.stats.public_count == 15
    assert parsed.stats.static_count == 2
    assert parsed.stats.unparsed_line_count == 0

    static_names = {s.name for s in parsed.symbols if s.visibility == "static"}
    assert "LegacyModeLogic::Tick" in static_names

    mangled = by_name.get("?InternalHelper@FightSim@@AAEXXZ")
    assert mangled is not None
    assert mangled.is_mangled is True
    assert mangled.demangled_name is None
    assert mangled.visibility == "static"


def test_publics_by_name_section_is_skipped_not_double_counted(fixtures_dir):
    parsed = parse_map_file(fixtures_dir / "publics_by_name_and_duplicates.map.txt")

    # 4 entries in "Publics by Value"; the "Publics by Name" section repeats
    # 2 of them and must not be counted again.
    assert parsed.stats.total_symbols == 4
    assert parsed.stats.duplicate_name_count == 1  # Alpha::One appears twice
    assert parsed.stats.duplicate_address_count == 1  # 0x82000010 shared


def test_malformed_lines_are_preserved_as_issues_not_dropped(fixtures_dir):
    parsed = parse_map_file(fixtures_dir / "malformed_lines.map.txt")

    names = {s.name for s in parsed.symbols}
    assert names == {"Good::Symbol", "Another::Good"}

    assert parsed.stats.unparsed_line_count == len(parsed.issues)
    assert parsed.stats.unparsed_line_count >= 3
    # Every unparsed line's original text must be retained verbatim.
    for issue in parsed.issues:
        assert issue.text.strip() != ""
        assert issue.source_line > 0


def test_order_index_is_stable_parse_order(fixtures_dir):
    parsed = parse_map_file(fixtures_dir / "synthetic_fn5d_style.map.txt")
    order_indices = [s.order_index for s in parsed.symbols]
    assert order_indices == sorted(order_indices)
    assert order_indices == list(range(len(parsed.symbols)))
