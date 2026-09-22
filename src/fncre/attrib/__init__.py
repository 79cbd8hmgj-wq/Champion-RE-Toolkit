"""AttribSys resource/tunable extraction: hashing, key resolution, vault
parsing, and typed value decoding.

Generalizes Fight-Night-Legacy's `tools/attrib_hash.py`,
`tools/attrib_vault_inspect.py`, and `tools/fn5_attrib_extract.py` — the
*mechanics* of the EA AttribSys middleware (string hashing, VLT chunk
containers, export/fixup records, primitive type decoding) — while keeping
Champion-specific interpretation (which collection means what, what a
field controls in Legacy Mode) in Fight-Night-Legacy. See
docs/legacy-compatibility.md and docs/resource-pipeline.md.
"""
