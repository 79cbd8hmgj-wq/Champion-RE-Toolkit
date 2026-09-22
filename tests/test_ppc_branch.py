from __future__ import annotations

from fncre.ppc.branch import decode_direct_branch, hexdump_words


def test_decode_i_form_relative_branch():
    # b +8 (relative, no link, no absolute): opcode 18, displacement=8
    word = (18 << 26) | 8
    branch = decode_direct_branch(word, address=0x1000)
    assert branch is not None
    assert branch["target"] == 0x1008
    assert branch["conditional"] is False
    assert branch["link"] is False
    assert branch["absolute"] is False


def test_decode_i_form_absolute_branch_with_link():
    # bla 0x2000: opcode 18, AA=1, LK=1, absolute displacement = 0x2000
    word = (18 << 26) | 0x2000 | 0b11
    branch = decode_direct_branch(word, address=0x1000)
    assert branch is not None
    assert branch["target"] == 0x2000
    assert branch["absolute"] is True
    assert branch["link"] is True


def test_decode_b_form_conditional_branch():
    # bc +16 relative: opcode 16, displacement=16
    word = (16 << 26) | 16
    branch = decode_direct_branch(word, address=0x2000)
    assert branch is not None
    assert branch["target"] == 0x2010
    assert branch["conditional"] is True


def test_decode_negative_displacement_sign_extends():
    # b -4 (branch to itself - 4)
    displacement = (-4) & 0x03FFFFFC
    word = (18 << 26) | displacement
    branch = decode_direct_branch(word, address=0x1000)
    assert branch is not None
    assert branch["target"] == 0x0FFC


def test_decode_non_branch_returns_none():
    word = 0x60000000  # ori r0,r0,0 (nop), opcode 24
    assert decode_direct_branch(word, address=0x1000) is None


def test_hexdump_words_annotates_branch():
    word = (18 << 26) | 8
    blob = word.to_bytes(4, "big")
    text = hexdump_words(blob, start_va=0x1000)
    assert f"00001000  {word:08X}  ; b -> 0x00001008" in text
