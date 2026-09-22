"""Demangler tests using real decorated-name forms.

These decorated names are copied verbatim (a handful of short identifier
strings, not bulk data) from Fight-Night-Legacy's own derived, non-
proprietary evidence: `evidence/fn5d/fightsim_symbols.csv` and the literal
fixtures already committed in `tests/test_re_function_slice.py` /
`tests/test_re_validate_fn5d.py` on that project's `research/fn5d-debug-legacy`
branch. No proprietary bytes, only short symbol-name strings.
"""

from __future__ import annotations

import pytest

from fncre.symbols import demangle

undname_available = pytest.mark.skipif(
    not demangle.is_available(), reason="undname backend not installed"
)


def test_is_available_reflects_backend_presence():
    assert isinstance(demangle.is_available(), bool)


def test_non_decorated_name_is_reported_as_not_mangled():
    result = demangle.demangle_msvc_name("plain_c_symbol")
    assert result.success is False
    assert result.demangled is None
    assert result.error == "not a decorated name"


@undname_available
@pytest.mark.parametrize(
    ("raw", "expected_signature", "expected_qualified"),
    [
        (
            "?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ",
            "public: void __cdecl LegacyModeLogic::FightSim::UpdateEnergy(void)",
            "LegacyModeLogic::FightSim::UpdateEnergy",
        ),
        (
            "?ThrowPunch@FightSim@LegacyModeLogic@@QAAXXZ",
            "public: void __cdecl LegacyModeLogic::FightSim::ThrowPunch(void)",
            "LegacyModeLogic::FightSim::ThrowPunch",
        ),
        (
            # Real form from Fight-Night-Legacy evidence/fn5d/fightsim_symbols.csv
            "??0FightSim@LegacyModeLogic@@QAA@XZ",
            "public: __cdecl LegacyModeLogic::FightSim::FightSim(void)",
            "LegacyModeLogic::FightSim::FightSim",
        ),
        (
            "??1FightSim@LegacyModeLogic@@QAA@XZ",
            "public: __cdecl LegacyModeLogic::FightSim::~FightSim(void)",
            "LegacyModeLogic::FightSim::~FightSim",
        ),
        (
            "?GetTunables@FightSim@LegacyModeLogic@@QBAPBUTunables@12@XZ",
            "public: struct LegacyModeLogic::FightSim::Tunables const * "
            "__cdecl LegacyModeLogic::FightSim::GetTunables(void)const ",
            "LegacyModeLogic::FightSim::GetTunables",
        ),
    ],
)
def test_known_real_fn5d_decorated_forms(raw, expected_signature, expected_qualified):
    result = demangle.demangle_msvc_name(raw)
    assert result.success is True
    assert result.demangled == expected_signature
    assert result.qualified_name == expected_qualified


@undname_available
def test_plain_data_symbol_qualified_name_excludes_return_type():
    result = demangle.demangle_msvc_name("?g_fightSimVersion@@3HA")
    assert result.success is True
    assert result.demangled == "int g_fightSimVersion"
    assert result.qualified_name == "g_fightSimVersion"


@undname_available
def test_malformed_decorated_name_fails_without_raising():
    result = demangle.demangle_msvc_name("?totally@broken@mangling@@ZZZZINVALID")
    assert result.success is False
    assert result.demangled is None
    assert result.error is not None


def test_demangle_symbol_never_drops_a_symbol_on_failure(monkeypatch):
    from fncre.symbols.map_parser import parse_map_text

    text = (
        " t\n\n Timestamp is 0 (x)\n\n Preferred load address is 82000000\n\n"
        " Start         Length     Name                   Class\n"
        " 0001:00000000 00000010H .text                   CODE\n\n"
        "  Address         Publics by Value              Rva+Base       Lib:Object\n\n"
        " 0001:00000000       ?totally@broken@@ZZINVALID   82000000 f   x:x.obj\n\n"
        " entry point at        0001:00000000\n"
    )
    parsed = parse_map_text(text)
    assert len(parsed.symbols) == 1

    result = demangle.demangle_parsed_map(parsed)
    assert len(result.symbols) == 1  # symbol preserved even though demangling fails
    assert result.symbols[0].raw_name == "?totally@broken@@ZZINVALID"
    assert result.symbols[0].demangled_name is None


@undname_available
def test_demangle_parsed_map_round_trips_through_map_parser(fixtures_dir):
    from fncre.symbols.map_parser import parse_map_file

    parsed = parse_map_file(fixtures_dir / "synthetic_fn5d_style.map.txt")
    result = demangle.demangle_parsed_map(parsed)

    by_raw = {s.raw_name: s for s in result.symbols}
    energy = by_raw["?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ"]
    assert energy.demangled_name == "LegacyModeLogic::FightSim::UpdateEnergy"
    assert energy.demangled_signature == (
        "public: void __cdecl LegacyModeLogic::FightSim::UpdateEnergy(void)"
    )
    assert energy.namespace_path == "LegacyModeLogic::FightSim"
    assert energy.leaf == "UpdateEnergy"

    # Non-mangled symbols are unaffected by the demangling pass.
    ctor_free = [s for s in result.symbols if not s.is_mangled]
    for sym in ctor_free:
        assert sym.demangled_name == sym.name
