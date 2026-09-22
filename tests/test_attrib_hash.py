from __future__ import annotations

import pytest

from fncre.attrib.hash import attrib_hash, attrib_hash_bytes, strip_key_prefix

# Exact vectors documented in Fight-Night-Legacy's tools/attrib_hash.py,
# verified there against FN5D's own generated hash initializers.
KNOWN_VECTORS = {
    "rating_bum": 0x56D9A633,
    "career_goals": 0xF681681B,
    "fight_sim": 0xA9244D34,
    "pro_settings": 0x5B62B6EC,
    "ranking_formula": 0x4B147504,
    "scheduling": 0xA00607F5,
}


@pytest.mark.parametrize(("text", "expected"), KNOWN_VECTORS.items())
def test_known_vectors_match_legacy_exactly(text, expected):
    assert attrib_hash(text) == expected


def test_hash_is_deterministic():
    assert attrib_hash("fight_sim") == attrib_hash("fight_sim")


def test_hash_result_fits_in_uint32():
    for text in KNOWN_VECTORS:
        assert 0 <= attrib_hash(text) <= 0xFFFFFFFF


def test_empty_string_hash_is_stable():
    assert attrib_hash("") == attrib_hash("")


def test_attrib_hash_bytes_matches_attrib_hash_of_utf8():
    text = "some_key"
    assert attrib_hash_bytes(text.encode("utf-8")) == attrib_hash(text)


def test_custom_seed_changes_result():
    assert attrib_hash("fight_sim", seed=0) != attrib_hash("fight_sim")


def test_strip_key_prefix():
    assert strip_key_prefix("key_fight_sim") == "fight_sim"
    assert strip_key_prefix("Jab_Damage") == "Jab_Damage"
    assert strip_key_prefix("key_") == ""
