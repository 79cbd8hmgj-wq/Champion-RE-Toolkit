"""Generalized build-identity/provenance validation.

Generalizes the concept already used by Fight-Night-Legacy's
`evidence/fn5d/build_identity.json` + `tools/re_validate_fn5d.py`: before
trusting any newly-derived RE result, verify the local artifacts you're
about to analyze are byte-identical to the ones the identity file
describes. Nothing here is FN5D-specific — `build_identity.json`'s own
schema (an `xex` block, an `extracted_basefile` block, a `map` block with
symbol/address anchors) is exactly what `fncre.build.identity` reads, so
the same JSON file that already validates FN5D also validates FN5Z or any
future build without code changes.
"""

from fncre.build.identity import BuildIdentity, VerifyReport, load_identity, verify_build

__all__ = ["BuildIdentity", "VerifyReport", "load_identity", "verify_build"]
