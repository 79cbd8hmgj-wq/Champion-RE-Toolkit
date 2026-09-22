"""Byte-level, relocation-aware function comparison.

Deliberately conservative wording, per the task's own instruction: this
module never claims semantic equivalence merely because bytes are similar.
It reports one of four classifications, from strongest to weakest evidence:

    byte_identical                 — the raw bytes match exactly.
    relocation_normalized_identical — bytes match once direct-branch
                                      displacement immediates are masked
                                      out (the two builds' functions are at
                                      different addresses, so an otherwise
                                      identical function's internal branch
                                      offsets will legitimately differ).
    structurally_similar           — most instruction words match after
                                      relocation normalization, but not all;
                                      a human should look at the remaining
                                      differences.
    different                      — the functions are not a close byte
                                      match; a human should re-derive this
                                      one, this tool draws no conclusion
                                      about *why*.

A fifth state, "unresolved", is for callers to use when a function
couldn't even be sliced in one or both builds (e.g. absent in one build) —
this module does not produce it itself since it always receives two
already-extracted blobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Classification = Literal[
    "byte_identical",
    "relocation_normalized_identical",
    "structurally_similar",
    "different",
]

_SIMILARITY_THRESHOLD = 0.6

# Displacement-field masks for the two opcodes fncre.ppc.branch decodes.
_I_FORM_OPCODE = 18
_B_FORM_OPCODE = 16
_I_FORM_DISPLACEMENT_MASK = 0x03FFFFFC
_B_FORM_DISPLACEMENT_MASK = 0x0000FFFC


@dataclass(frozen=True)
class FunctionDiffResult:
    classification: Classification
    size_a: int
    size_b: int
    size_delta: int
    matching_word_count: int
    total_word_count: int
    similarity: float
    """matching_word_count / total_word_count over the compared (min-length) span."""
    differing_word_offsets: tuple[int, ...]
    """Offsets (within the shorter blob) of words that still differ after
    relocation normalization, capped to a reasonable count for reporting."""


def _normalize_word(word: int) -> int:
    """Zero out a direct branch's displacement bits; pass through everything else."""
    opcode = (word >> 26) & 0x3F
    if opcode == _I_FORM_OPCODE:
        return word & ~_I_FORM_DISPLACEMENT_MASK
    if opcode == _B_FORM_OPCODE:
        return word & ~_B_FORM_DISPLACEMENT_MASK
    return word


def _words(blob: bytes) -> list[int]:
    usable = len(blob) - (len(blob) % 4)
    return [int.from_bytes(blob[i : i + 4], "big") for i in range(0, usable, 4)]


def classify_function_diff(
    blob_a: bytes, blob_b: bytes, *, max_reported_offsets: int = 32
) -> FunctionDiffResult:
    if blob_a == blob_b:
        words = _words(blob_a)
        return FunctionDiffResult(
            classification="byte_identical",
            size_a=len(blob_a),
            size_b=len(blob_b),
            size_delta=0,
            matching_word_count=len(words),
            total_word_count=len(words),
            similarity=1.0,
            differing_word_offsets=(),
        )

    words_a = _words(blob_a)
    words_b = _words(blob_b)
    norm_a = [_normalize_word(w) for w in words_a]
    norm_b = [_normalize_word(w) for w in words_b]

    span = min(len(norm_a), len(norm_b))
    differing_offsets = [
        i * 4 for i in range(span) if norm_a[i] != norm_b[i]
    ]
    matching = span - len(differing_offsets)
    total = max(len(norm_a), len(norm_b))
    similarity = matching / total if total else 1.0

    if len(words_a) == len(words_b) and not differing_offsets:
        classification: Classification = "relocation_normalized_identical"
    elif similarity >= _SIMILARITY_THRESHOLD:
        classification = "structurally_similar"
    else:
        classification = "different"

    return FunctionDiffResult(
        classification=classification,
        size_a=len(blob_a),
        size_b=len(blob_b),
        size_delta=len(blob_b) - len(blob_a),
        matching_word_count=matching,
        total_word_count=total,
        similarity=round(similarity, 4),
        differing_word_offsets=tuple(differing_offsets[:max_reported_offsets]),
    )
