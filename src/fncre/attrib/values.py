"""EA AttribSys primitive type names and value decoding.

Ported from Fight-Night-Legacy's `tools/fn5_attrib_extract.py`
(`TYPE_NAMES`, `TYPE_HASH`, `decode_primitive`). These are EA AttribSys
middleware primitive type names (`EA::Reflection::*`, `Attrib::*`) — part
of the reusable AttribSys SDK type system, not Fight Night Champion
gameplay vocabulary, so they live here rather than in Fight-Night-Legacy.

Decoding is deliberately limited to what Legacy's own parser already
established: a fixed set of primitive scalar types, plus fixed-size arrays
of them (the `DefinitionFlags.Array` bit). Anything else is returned as a
raw-bytes/type-hash record rather than guessed at.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from fncre.attrib.hash import attrib_hash

# EA AttribSys primitive type names, as referenced by generated type-hash
# initializers in the FN5D linker map.
TYPE_NAMES = (
    "EA::Reflection::Float",
    "EA::Reflection::UInt16",
    "EA::Reflection::Int16",
    "EA::Reflection::UInt32",
    "EA::Reflection::Int32",
    "EA::Reflection::UInt8",
    "EA::Reflection::Int8",
    "EA::Reflection::Bool",
    "EA::Reflection::Text",
    "Attrib::StringKey",
    "Attrib::RefSpec",
    "Attrib::Blob",
    "EA::Reflection::String",
)
TYPE_HASH: dict[int, str] = {attrib_hash(name): name for name in TYPE_NAMES}

DEFINITION_FLAG_ARRAY = 0x01


@dataclass(frozen=True)
class RawValue:
    """A value whose type isn't one of the known decodable primitives."""

    hex: str
    type_name: str | None


@dataclass(frozen=True)
class ArrayValue:
    values: list[Any]
    capacity: int
    count: int
    field_size: int
    header_unknown: int


def decode_primitive(data: bytes, *, size: int, type_name: str) -> Any:
    """Decode a single scalar value of a known AttribSys primitive type.

    Returns `None` if `data` is shorter than `size` (truncated/unavailable
    data — never fabricated), or a `RawValue` for a type this decoder
    doesn't have a rule for yet (e.g. Text/String/RefSpec/Blob, which need
    an out-of-band string table or reference resolver Legacy's own parser
    doesn't establish either).
    """
    raw = data[:size]
    if len(raw) < size:
        return None

    if type_name.endswith("Float") and size == 4:
        return struct.unpack(">f", raw)[0]
    if type_name.endswith("Int8") and not type_name.endswith("UInt8"):
        return int.from_bytes(raw, "big", signed=True)
    if type_name.endswith("UInt8") or type_name.endswith("Bool"):
        return int.from_bytes(raw, "big")
    if type_name.endswith("Int16") and not type_name.endswith("UInt16"):
        return int.from_bytes(raw, "big", signed=True)
    if type_name.endswith("UInt16"):
        return int.from_bytes(raw, "big")
    if type_name.endswith("Int32") and not type_name.endswith("UInt32"):
        return int.from_bytes(raw, "big", signed=True)
    if type_name.endswith("UInt32") or type_name == "Attrib::StringKey":
        return int.from_bytes(raw, "big")

    return RawValue(hex=raw.hex(), type_name=type_name)


def decode_array(
    bin_data: bytes,
    *,
    destination: int,
    element_size: int,
    element_type_name: str,
    alignment: int,
) -> ArrayValue:
    """Decode a `DefinitionFlags.Array`-flagged field.

    Layout (confirmed by Fight-Night-Legacy's `read_noninline`):
    an 8-byte header (capacity, count, field_size, unknown — all uint16 be)
    followed by `count` elements, each aligned to `alignment`.
    """
    capacity, count, field_size, header_unknown = struct.unpack_from(
        ">HHHH", bin_data, destination
    )
    pos = destination + 8
    values: list[Any] = []

    for _ in range(count):
        if pos % alignment:
            pos += (-pos) % alignment
        values.append(
            decode_primitive(
                bin_data[pos : pos + field_size], size=field_size, type_name=element_type_name
            )
        )
        pos += field_size

    return ArrayValue(
        values=values,
        capacity=capacity,
        count=count,
        field_size=field_size,
        header_unknown=header_unknown,
    )
