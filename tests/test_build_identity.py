from __future__ import annotations

import hashlib
import json

from fncre.build.identity import BuildIdentity, load_identity, verify_build
from tests.pe_builder import build_pe32

IMAGE_BASE = 0x82000000


def _write_map(tmp_path, symbols):
    lines = [
        " testmod",
        "",
        " Timestamp is 0 (x)",
        "",
        " Preferred load address is 82000000",
        "",
        " Start         Length     Name                   Class",
        " 0001:00000000 00001000H .text                   CODE",
        "",
        "  Address         Publics by Value              Rva+Base       Lib:Object",
        "",
    ]
    for name, addr in symbols:
        lines.append(f" 0001:{addr - IMAGE_BASE:08x}       {name} {addr:08x} f   x:x.obj")
    lines.append("")
    lines.append(" entry point at        0001:00000000")
    path = tmp_path / "test.map"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_verify_map_passes_when_anchors_match(tmp_path):
    map_path = _write_map(
        tmp_path,
        [
            ("?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ", 0x836016C0),
            ("?ThrowPunch@FightSim@LegacyModeLogic@@QAAXXZ", 0x83602D68),
        ],
    )
    identity_doc = {
        "map": {
            "preferred_load_address": "0x82000000",
            "anchors": [
                {"query": "UpdateEnergy@FightSim", "address": "0x836016C0"},
                {"query": "ThrowPunch@FightSim", "address": "0x83602D68"},
            ],
        }
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity_doc))

    identity = load_identity(identity_path)
    report = verify_build("fn5d", identity, identity_path, map_path=map_path)

    assert len(report.artifacts) == 1
    assert report.artifacts[0].trust_level == "identity_validated"
    assert report.artifacts[0].errors == []
    assert report.all_requested_validated is True


def test_verify_map_fails_when_anchor_address_is_wrong(tmp_path):
    map_path = _write_map(
        tmp_path, [("?UpdateEnergy@FightSim@LegacyModeLogic@@QAAXXZ", 0x836016C0)]
    )
    identity_doc = {
        "map": {"anchors": [{"query": "UpdateEnergy@FightSim", "address": "0xDEADBEEF"}]}
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity_doc))

    identity = load_identity(identity_path)
    report = verify_build("fn5d", identity, identity_path, map_path=map_path)

    assert report.artifacts[0].trust_level == "artifact_available"
    assert report.artifacts[0].errors
    assert "UpdateEnergy@FightSim" in report.artifacts[0].errors[0]
    assert report.all_requested_validated is False


def test_verify_build_reports_artifact_unavailable_when_not_checked(tmp_path):
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps({}))
    identity = load_identity(identity_path)

    report = verify_build("fn5d", identity, identity_path)
    assert report.artifacts == []
    assert report.all_requested_validated is False


def test_verify_xex_bytes_matches_generic_schema(tmp_path):
    xex_bytes = b"XEX2" + b"\0" * 60
    spec = {
        "size": len(xex_bytes),
        "sha256": hashlib.sha256(xex_bytes).hexdigest(),
        "magic": "XEX2",
    }
    from fncre.build.identity import verify_xex_bytes

    errors = verify_xex_bytes(xex_bytes, spec)
    assert errors == []


def test_verify_pe_bytes_checks_image_base(tmp_path):
    pe_bytes = build_pe32(
        image_base=IMAGE_BASE, section_name=b".text", section_va=0x1000, section_bytes=bytes(0x10)
    )
    spec = {
        "size": len(pe_bytes),
        "sha256": hashlib.sha256(pe_bytes).hexdigest(),
        "magic": "MZ",
        "image_base": f"0x{IMAGE_BASE:08X}",
    }
    from fncre.build.identity import verify_pe_bytes

    assert verify_pe_bytes(pe_bytes, spec) == []

    bad_spec = dict(spec, image_base="0x00000000")
    errors = verify_pe_bytes(pe_bytes, bad_spec)
    assert errors
    assert "image base" in errors[0]


def test_build_identity_blocks_are_optional():
    identity = BuildIdentity({"xex": {"size": 1}})
    assert identity.xex_spec == {"size": 1}
    assert identity.extracted_basefile_spec is None
    assert identity.map_spec is None
