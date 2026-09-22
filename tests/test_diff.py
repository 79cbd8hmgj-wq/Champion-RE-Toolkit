from __future__ import annotations

from fncre.diff.function_diff import classify_function_diff
from fncre.diff.symbol_diff import compare_symbols
from tests.symbol_builder import make_symbol


def test_compare_symbols_classifies_both_only_a_only_b():
    a = [
        make_symbol("?Foo@@QAAXXZ", 0x1000),
        make_symbol("?OnlyA@@QAAXXZ", 0x2000),
    ]
    b = [
        make_symbol("?Foo@@QAAXXZ", 0x3000, object_name="different.obj"),
        make_symbol("?OnlyB@@QAAXXZ", 0x4000),
    ]
    report = compare_symbols(a, b)

    assert {e.raw_name for e in report.only_in_a} == {"?OnlyA@@QAAXXZ"}
    assert {e.raw_name for e in report.only_in_b} == {"?OnlyB@@QAAXXZ"}
    assert len(report.in_both) == 1

    foo = report.in_both[0]
    assert foo.address_moved is True  # 0x1000 != 0x3000
    assert foo.object_changed is True


def test_compare_symbols_address_moved_alone_is_not_size_or_object_change():
    a = [make_symbol("?Foo@@QAAXXZ", 0x1000)]
    b = [make_symbol("?Foo@@QAAXXZ", 0x5000)]
    report = compare_symbols(a, b)
    foo = report.in_both[0]
    assert foo.address_moved is True
    assert foo.object_changed is False
    assert foo.library_changed is False
    assert foo.visibility_changed is False


def test_compare_symbols_infers_size_change_from_next_symbol_gap():
    a = [make_symbol("?Foo@@QAAXXZ", 0x1000), make_symbol("?Next@@QAAXXZ", 0x1010)]  # size 0x10
    b = [make_symbol("?Foo@@QAAXXZ", 0x3000), make_symbol("?Next@@QAAXXZ", 0x3020)]  # size 0x20
    report = compare_symbols(a, b)
    foo = report.in_both[0]
    assert foo.inferred_size_a == 0x10
    assert foo.inferred_size_b == 0x20
    assert foo.size_changed is True


def test_classify_function_diff_byte_identical():
    blob = bytes([0x60, 0x00, 0x00, 0x00] * 4)  # all nops
    result = classify_function_diff(blob, blob)
    assert result.classification == "byte_identical"
    assert result.similarity == 1.0
    assert result.size_delta == 0


def test_classify_function_diff_relocation_normalized_identical():
    # Same function, but the branch displacement differs because it's
    # linked at a different address in each build; everything else matches.
    def make(displacement: int) -> bytes:
        branch_word = (18 << 26) | (displacement & 0x03FFFFFC)
        nop = 0x60000000
        return branch_word.to_bytes(4, "big") + nop.to_bytes(4, "big")

    blob_a = make(0x100)
    blob_b = make(0x200)
    assert blob_a != blob_b

    result = classify_function_diff(blob_a, blob_b)
    assert result.classification == "relocation_normalized_identical"
    assert result.similarity == 1.0


def test_classify_function_diff_structurally_similar_vs_different():
    nop = (0x60000000).to_bytes(4, "big")
    branch = ((18 << 26) | 0x10).to_bytes(4, "big")
    # 4 matching nops + 1 differing word out of 5 -> similarity 0.8
    blob_a = nop * 4 + nop
    blob_b = nop * 4 + branch
    result = classify_function_diff(blob_a, blob_b)
    assert result.classification == "structurally_similar"
    assert result.similarity == 0.8

    # Mostly different content -> "different"
    blob_c = nop * 1 + branch * 4
    result2 = classify_function_diff(blob_a, blob_c)
    assert result2.classification == "different"
    assert result2.similarity < 0.6


def test_classify_function_diff_never_claims_identical_for_different_sizes():
    blob_a = bytes(0x10)
    blob_b = bytes(0x14)
    result = classify_function_diff(blob_a, blob_b)
    assert result.classification != "byte_identical"
    assert result.classification != "relocation_normalized_identical"
    assert result.size_delta == 4
