from __future__ import annotations

import pytest

from fncre.attrib.hash import attrib_hash
from fncre.attrib.keys_import import parse_generated_keys_csv, parse_wordlist


def test_parse_generated_keys_csv(tmp_path):
    csv_path = tmp_path / "keys.csv"
    csv_path.write_text(
        "cpp_name,source_name,hash\n"
        f"key_fight_sim,fight_sim,0x{attrib_hash('fight_sim'):08X}\n"
        f"Jab_Damage,Jab_Damage,0x{attrib_hash('Jab_Damage'):08X}\n"
    )

    rows = parse_generated_keys_csv(csv_path)
    assert len(rows) == 2
    h0, text0, cpp0, prov0 = rows[0]
    assert text0 == "fight_sim"
    assert h0 == attrib_hash("fight_sim")
    assert cpp0 == "key_fight_sim"
    assert "WARNING" not in prov0


def test_parse_generated_keys_csv_flags_stale_hash(tmp_path):
    csv_path = tmp_path / "keys.csv"
    csv_path.write_text("cpp_name,source_name,hash\nkey_x,x,0xDEADBEEF\n")

    rows = parse_generated_keys_csv(csv_path)
    h, text, _cpp, provenance = rows[0]
    assert h == attrib_hash("x")  # recomputed, not the stale file value
    assert "WARNING" in provenance


def test_parse_generated_keys_csv_rejects_wrong_header(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("name,hash\nfoo,0x1\n")
    with pytest.raises(ValueError):
        parse_generated_keys_csv(csv_path)


def test_parse_wordlist_skips_blank_and_comment_lines(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("fight_sim\n\n# a comment\nscheduling\n")

    rows = parse_wordlist(path)
    assert rows == [
        (attrib_hash("fight_sim"), "fight_sim"),
        (attrib_hash("scheduling"), "scheduling"),
    ]
