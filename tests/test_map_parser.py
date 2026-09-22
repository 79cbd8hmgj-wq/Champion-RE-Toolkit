"""Parser tests against small, hand-authored synthetic fixtures.

None of these fixtures are extracted from any real Fight Night Champion
build artifact. They are hand-written to match the *real* Xenon linker MAP
format confirmed against Fight-Night-Legacy's own research corpus
(`research/fn5d-debug-legacy`): real FN5D/FN5Z symbol names are MSVC-decorated
(e.g. ``?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ``), not plain
``FightSim::UpdateEnergy`` text, and the flags column supports 'f' and 'i'
letters, alone or combined ("f i") — both confirmed by
`Fight-Night-Legacy/tools/map_symbols.py`'s own regex and its
`evidence/fn5d/*_symbols.csv` files. `synthetic_fn5d_style.map.txt` encodes
the publicly known FN5D validation anchors (symbol name + runtime address
pairs) in that real decorated form, purely so this suite can assert the
parser recovers name/address pairs correctly end-to-end. It is not a copy
of, or derived from, the real fn5d.xenon.map file.
"""

from __future__ import annotations

from fncre.symbols.map_parser import parse_map_file

# Raw decorated names as they appear in the fixture (== Symbol.name for a
# mangled symbol, since map_parser never rewrites raw text).
KNOWN_FN5D_ANCHORS = {
    "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ": 0x836016C0,
    "?UpdateFatigue@FightSim@LegacyModeLogic@@QAAXXZ": 0x83601950,
    "?UpdateHealth@FightSim@LegacyModeLogic@@QAAXXZ": 0x83601B80,
    "?UpdateInjury@FightSim@LegacyModeLogic@@QAAXXZ": 0x83601E38,
    "?UpdateKnockDown@FightSim@LegacyModeLogic@@QAAXXZ": 0x83601E98,
    "?UpdateFoul@FightSim@LegacyModeLogic@@QAAXXZ": 0x836020D8,
    "?UpdateSwelling@FightSim@LegacyModeLogic@@QAAXXZ": 0x836021F0,
    "?UpdateCut@FightSim@LegacyModeLogic@@QAAXXZ": 0x83602370,
    "?ThrowPunch@FightSim@LegacyModeLogic@@QAAXXZ": 0x83602D68,
    "?CalculateWinRank@RankingFormula@@QAAHXZ": 0x83604868,
    "?CalculateLoseRank@RankingFormula@@QAAHXZ": 0x83604AB0,
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
    assert sym.is_internal is None
    assert sym.raw_flags == "f"
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
        assert by_name[name].is_mangled is True
        # map_parser itself never demangles; that's a separate opt-in pass.
        assert by_name[name].demangled_name is None

    assert parsed.stats.total_symbols == 17
    assert parsed.stats.public_count == 15
    assert parsed.stats.static_count == 2
    assert parsed.stats.unparsed_line_count == 0

    static_names = {s.name for s in parsed.symbols if s.visibility == "static"}
    assert "?Tick@LegacyModeLogic@@QAAXXZ" in static_names

    mangled = by_name.get("?InternalHelper@FightSim@LegacyModeLogic@@AAEXXZ")
    assert mangled is not None
    assert mangled.is_mangled is True
    assert mangled.demangled_name is None
    assert mangled.visibility == "static"
    assert mangled.is_function is True
    assert mangled.is_internal is True
    assert mangled.raw_flags == "f i"


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


def test_flag_letters_f_i_and_combined(fixtures_dir):
    """Real MAP flags are 'f', 'i', or both together ("f i"), or absent."""
    parsed = parse_map_file(fixtures_dir / "real_format_flags_and_duplicates.map.txt")
    by_line = {s.source_line: s for s in parsed.symbols}

    update_energy = by_line[12]
    assert update_energy.raw_name == "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ"
    assert update_energy.raw_flags == "f"
    assert update_energy.is_function is True
    assert update_energy.is_internal is None

    update_fatigue = by_line[13]
    assert update_fatigue.raw_flags == "f i"
    assert update_fatigue.is_function is True
    assert update_fatigue.is_internal is True

    throw_punch = by_line[14]
    assert throw_punch.raw_flags == "i"
    assert throw_punch.is_function is None  # 'i' alone never implies function
    assert throw_punch.is_internal is True

    ctor = by_line[15]
    assert ctor.raw_flags == ""
    assert ctor.is_function is None
    assert ctor.is_internal is None

    assert parsed.stats.unparsed_line_count == 0


def test_flags_fixture_duplicate_address_and_symbol_and_visibility(fixtures_dir):
    parsed = parse_map_file(fixtures_dir / "real_format_flags_and_duplicates.map.txt")

    # UpdateEnergy (public) and ThrowPunch (public) share address 0x836016c0.
    at_addr = [s for s in parsed.symbols if s.address == 0x836016C0]
    assert len(at_addr) == 2
    assert {s.raw_name for s in at_addr} == {
        "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ",
        "?ThrowPunch@FightSim@LegacyModeLogic@@QAAXXZ",
    }

    # UpdateEnergy appears once in Publics and once in Static symbols —
    # same raw name, different visibility and address, both kept.
    same_name = [
        s
        for s in parsed.symbols
        if s.raw_name == "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ"
    ]
    assert len(same_name) == 2
    assert {s.visibility for s in same_name} == {"public", "static"}
    assert {s.address for s in same_name} == {0x836016C0, 0x83602000}

    assert parsed.stats.duplicate_name_count == 1
    assert parsed.stats.duplicate_address_count == 1
    assert parsed.stats.public_count == 4
    assert parsed.stats.static_count == 1
