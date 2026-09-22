from __future__ import annotations

import pytest

from fncre.attrib.hash import attrib_hash
from fncre.attrib.keys import AttribKeyIndex


def test_add_and_lookup_roundtrip(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        h = attrib_hash("fight_sim")
        added = index.add(
            "fn5d", hash_value=h, text="fight_sim", status="evidenced", source="test"
        )
        assert added is True

        results = index.lookup("fn5d", h)
        assert len(results) == 1
        assert results[0].text == "fight_sim"
        assert results[0].status == "evidenced"
    finally:
        index.close()


def test_duplicate_add_is_a_noop(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        h = attrib_hash("fight_sim")
        first = index.add("fn5d", hash_value=h, text="fight_sim", status="evidenced")
        second = index.add("fn5d", hash_value=h, text="fight_sim", status="evidenced")
        assert first is True
        assert second is False
        assert len(index.lookup("fn5d", h)) == 1
    finally:
        index.close()


def test_hash_collision_preserves_both_texts(tmp_path):
    """Two different texts sharing one hash must both survive, not be merged."""
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        h = 0x12345678
        index.add("fn5d", hash_value=h, text="alpha", status="evidenced")
        index.add("fn5d", hash_value=h, text="beta", status="generated")

        results = index.lookup("fn5d", h)
        assert {r.text for r in results} == {"alpha", "beta"}

        stats = index.stats("fn5d")
        assert stats.collisions == 1
    finally:
        index.close()


def test_unresolved_status_requires_null_text(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        with pytest.raises(ValueError):
            index.add("fn5d", hash_value=1, text="oops", status="unresolved")
        with pytest.raises(ValueError):
            index.add("fn5d", hash_value=1, text=None, status="generated")
    finally:
        index.close()


def test_unresolved_hash_is_queryable_without_text(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        index.add("fn5d", hash_value=0xAABBCCDD, text=None, status="unresolved")
        results = index.lookup("fn5d", 0xAABBCCDD)
        assert len(results) == 1
        assert results[0].text is None
        assert results[0].status == "unresolved"
    finally:
        index.close()


def test_search_by_text_substring(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        index.add("fn5d", hash_value=1, text="fight_sim_jab_damage", status="generated")
        index.add("fn5d", hash_value=2, text="scheduling_max_fights", status="generated")
        results = index.search("fn5d", "fight_sim")
        assert len(results) == 1
        assert results[0].text == "fight_sim_jab_damage"
    finally:
        index.close()


def test_stats_reports_all_four_statuses_distinctly(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        index.add("fn5d", hash_value=1, text="a", status="evidenced")
        index.add("fn5d", hash_value=2, text="b", status="generated")
        index.add("fn5d", hash_value=3, text="c", status="inferred")
        index.add("fn5d", hash_value=4, text=None, status="unresolved")

        stats = index.stats("fn5d")
        assert stats.total == 4
        assert stats.by_status == {
            "evidenced": 1,
            "generated": 1,
            "inferred": 1,
            "unresolved": 1,
        }
        assert stats.distinct_hashes == 4
    finally:
        index.close()


def test_invalid_status_rejected(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        with pytest.raises(ValueError):
            index.add("fn5d", hash_value=1, text="x", status="confirmed")  # type: ignore[arg-type]
    finally:
        index.close()


def test_builds_are_isolated(tmp_path):
    index = AttribKeyIndex(tmp_path / "keys.db")
    try:
        h = attrib_hash("shared_name")
        index.add("fn5d", hash_value=h, text="shared_name", status="evidenced")
        assert len(index.lookup("fn5d", h)) == 1
        assert len(index.lookup("fn5z", h)) == 0
    finally:
        index.close()
