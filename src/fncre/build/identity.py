"""Build-identity schema and verification.

Schema (matches Fight-Night-Legacy's `evidence/fn5d/build_identity.json`
exactly — no FN5D-specific field was renamed or added):

    {
      "_meta": { ... arbitrary provenance notes ... },
      "xex": {
        "filename": str, "size": int, "sha256": str, "magic": "XEX2",
        "module_flags": "0xHEX", "header_size": "0xHEX",
        "security_info_offset": "0xHEX", "image_base": "0xHEX",
        "entry_point": "0xHEX", "module_name": str
      },
      "extracted_basefile": {
        "filename": str, "size": int, "sha256": str, "magic": "MZ",
        "image_base": "0xHEX"
      },
      "map": {
        "filename": str, "size": int, "preferred_load_address": "0xHEX",
        "anchors": [{"query": str, "address": "0xHEX"}, ...]
      }
    }

Every top-level block is optional in the file; you only get out what you
put artifacts in to check against. `map.anchors[].query` is matched the
same way Fight-Night-Legacy's `re_function_slice.find_unique_symbol` does:
a case-insensitive substring against the raw (decorated) symbol name,
preferring a match that starts right at a `?`-decorated name boundary when
the substring is otherwise ambiguous.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fncre.symbols.map_parser import parse_map_file
from fncre.symbols.models import Symbol
from fncre.xex.pe import parse_pe

_XEX_ENTRY_POINT = 0x00010100
_XEX_PE_BASE = 0x00010201
_XEX_PE_MODULE_NAME = 0x000183FF

TrustLevel = Literal["artifact_unavailable", "artifact_available", "identity_validated"]


@dataclass(frozen=True)
class BuildIdentity:
    """Parsed build-identity document. Any block may be absent."""

    raw: dict[str, Any]

    @property
    def xex_spec(self) -> dict[str, Any] | None:
        return self.raw.get("xex")

    @property
    def extracted_basefile_spec(self) -> dict[str, Any] | None:
        return self.raw.get("extracted_basefile")

    @property
    def map_spec(self) -> dict[str, Any] | None:
        return self.raw.get("map")


@dataclass
class ArtifactVerification:
    artifact: str
    trust_level: TrustLevel
    errors: list[str] = field(default_factory=list)


@dataclass
class VerifyReport:
    build_id: str
    identity_path: str
    artifacts: list[ArtifactVerification]

    @property
    def all_requested_validated(self) -> bool:
        """True only if at least one artifact was checked and none failed.

        This is the 'derived evidence trusted' gate: distinct from merely
        having the files on disk (artifact_available) or having checked
        some but not all of them.
        """
        checked = [a for a in self.artifacts if a.trust_level != "artifact_unavailable"]
        if not checked:
            return False
        return all(a.trust_level == "identity_validated" for a in checked)


def load_identity(path: str | Path) -> BuildIdentity:
    return BuildIdentity(json.loads(Path(path).read_text(encoding="utf-8")))


def _u32be(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expect(label: str, actual: Any, expected: Any, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def _xex_directory(data: bytes) -> dict[int, int]:
    if len(data) < 24 or data[:4] != b"XEX2":
        raise ValueError("input is not XEX2")
    count = _u32be(data, 0x14)
    end = 0x18 + count * 8
    if end > len(data):
        raise ValueError("truncated XEX optional-header directory")
    return {_u32be(data, 0x18 + i * 8): _u32be(data, 0x1C + i * 8) for i in range(count)}


def _read_xex_module_name(data: bytes, directory: dict[int, int]) -> str:
    offset = directory.get(_XEX_PE_MODULE_NAME)
    if offset is None:
        return ""
    if offset + 4 > len(data):
        raise ValueError("truncated XEX module-name header")
    size = _u32be(data, offset)
    if size < 4 or offset + size > len(data):
        raise ValueError("invalid XEX module-name header size")
    raw = data[offset + 4 : offset + size]
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")


def verify_xex_bytes(data: bytes, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _expect("XEX size", len(data), int(spec["size"]), errors)
    _expect("XEX sha256", _sha256_bytes(data), str(spec["sha256"]).lower(), errors)
    if len(data) < 24:
        errors.append("XEX is too small to contain a complete header")
        return errors

    _expect(
        "XEX magic", data[:4].decode("ascii", errors="replace"), spec.get("magic", "XEX2"), errors
    )
    if data[:4] != b"XEX2":
        return errors

    module_flags = _u32be(data, 0x04)
    header_size = _u32be(data, 0x08)
    security_info = _u32be(data, 0x10)
    if "module_flags" in spec:
        _expect("XEX module flags", f"0x{module_flags:08X}", spec["module_flags"], errors)
    if "header_size" in spec:
        _expect("XEX header size", f"0x{header_size:X}", spec["header_size"], errors)
    if "security_info_offset" in spec:
        _expect(
            "XEX security-info offset", f"0x{security_info:X}", spec["security_info_offset"], errors
        )

    try:
        directory = _xex_directory(data)
        entry = directory.get(_XEX_ENTRY_POINT)
        base = directory.get(_XEX_PE_BASE)
        if "entry_point" in spec:
            _expect(
                "XEX entry point",
                None if entry is None else f"0x{entry:08X}",
                spec["entry_point"],
                errors,
            )
        if "image_base" in spec:
            _expect(
                "XEX image base",
                None if base is None else f"0x{base:08X}",
                spec["image_base"],
                errors,
            )
        if "module_name" in spec:
            _expect(
                "XEX module name",
                _read_xex_module_name(data, directory),
                spec["module_name"],
                errors,
            )
    except ValueError as exc:
        errors.append(str(exc))

    return errors


def verify_pe_bytes(data: bytes, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _expect("extracted basefile size", len(data), int(spec["size"]), errors)
    _expect(
        "extracted basefile sha256", _sha256_bytes(data), str(spec["sha256"]).lower(), errors
    )
    _expect(
        "basefile magic",
        data[:2].decode("ascii", errors="replace") if len(data) >= 2 else "",
        spec.get("magic", "MZ"),
        errors,
    )
    if len(data) < 2 or data[:2] != b"MZ":
        return errors

    if "image_base" in spec:
        try:
            image_base, _sections = parse_pe(data)
            _expect("basefile image base", f"0x{image_base:08X}", spec["image_base"], errors)
        except ValueError as exc:
            errors.append(str(exc))

    return errors


def _find_unique_symbol(symbols: list[Symbol], query: str) -> Symbol:
    """Same disambiguation rule as Fight-Night-Legacy's find_unique_symbol."""
    query_lower = query.lower()
    matches = [s for s in symbols if query_lower in s.raw_name.lower()]
    if not matches:
        raise ValueError(f"no symbol matches {query!r}")

    if len(matches) > 1:
        decorated_prefix = "?" + query_lower
        boundary_matches = [
            s
            for s in matches
            if s.raw_name.lower().startswith(decorated_prefix) or s.raw_name.lower() == query_lower
        ]
        if len(boundary_matches) == 1:
            return boundary_matches[0]
        if boundary_matches:
            matches = boundary_matches

    if len(matches) != 1:
        names = ", ".join(s.raw_name for s in matches[:8])
        raise ValueError(f"symbol query {query!r} is ambiguous ({len(matches)} matches): {names}")
    return matches[0]


def verify_map_file(path: str | Path, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    actual_size = Path(path).stat().st_size
    if "size" in spec:
        _expect("linker-map size", actual_size, int(spec["size"]), errors)

    parsed = parse_map_file(path)
    if "preferred_load_address" in spec:
        actual_load = (
            None
            if parsed.header.preferred_load_address is None
            else f"0x{parsed.header.preferred_load_address:08X}"
        )
        _expect("preferred load address", actual_load, spec["preferred_load_address"], errors)

    for anchor in spec.get("anchors", []):
        query = str(anchor["query"])
        try:
            symbol = _find_unique_symbol(parsed.symbols, query)
        except ValueError as exc:
            errors.append(f"map anchor {query!r}: {exc}")
            continue
        expected = int(str(anchor["address"]), 0)
        if symbol.address != expected:
            actual_repr = "None" if symbol.address is None else f"0x{symbol.address:08X}"
            errors.append(f"map anchor {query!r}: expected 0x{expected:08X}, got {actual_repr}")

    return errors


def verify_build(
    build_id: str,
    identity: BuildIdentity,
    identity_path: str | Path,
    *,
    xex_path: str | Path | None = None,
    pe_path: str | Path | None = None,
    map_path: str | Path | None = None,
) -> VerifyReport:
    """Run every check the caller has artifacts for. Missing artifacts are
    reported as `artifact_unavailable`, never silently skipped."""
    artifacts: list[ArtifactVerification] = []

    if xex_path is not None:
        spec = identity.xex_spec
        if spec is None:
            artifacts.append(
                ArtifactVerification(
                    "xex", "artifact_available", ["identity file has no 'xex' block"]
                )
            )
        else:
            errors = verify_xex_bytes(Path(xex_path).read_bytes(), spec)
            level: TrustLevel = "identity_validated" if not errors else "artifact_available"
            artifacts.append(ArtifactVerification("xex", level, errors))

    if pe_path is not None:
        spec = identity.extracted_basefile_spec
        if spec is None:
            artifacts.append(
                ArtifactVerification(
                    "extracted_basefile",
                    "artifact_available",
                    ["identity file has no 'extracted_basefile' block"],
                )
            )
        else:
            errors = verify_pe_bytes(Path(pe_path).read_bytes(), spec)
            level = "identity_validated" if not errors else "artifact_available"
            artifacts.append(ArtifactVerification("extracted_basefile", level, errors))

    if map_path is not None:
        spec = identity.map_spec
        if spec is None:
            artifacts.append(
                ArtifactVerification(
                    "map", "artifact_available", ["identity file has no 'map' block"]
                )
            )
        else:
            errors = verify_map_file(map_path, spec)
            level = "identity_validated" if not errors else "artifact_available"
            artifacts.append(ArtifactVerification("map", level, errors))

    return VerifyReport(build_id=build_id, identity_path=str(identity_path), artifacts=artifacts)
