"""Narrow PowerPC direct-branch decoding.

Intentionally scoped to exactly what Fight-Night-Legacy's
`tools/re_function_slice.py` / `tools/re_branch_xrefs.py` already decode:
I-form (`b`/`bl`) and B-form (`bc`/`bcl`) direct branches. This is not a
disassembler — indirect calls through LR/CTR, virtual dispatch, and TOC
references are explicitly out of scope until direct-branch parity with
those existing tools is demonstrated (see docs/legacy-compatibility.md).
"""

from fncre.ppc.branch import decode_direct_branch, hexdump_words

__all__ = ["decode_direct_branch", "hexdump_words"]
