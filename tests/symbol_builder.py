"""Test helper: build a minimal Symbol without going through the MAP parser."""

from __future__ import annotations

from fncre.symbols.models import Symbol


def make_symbol(
    name: str,
    address: int,
    *,
    visibility: str = "public",
    is_function: bool | None = True,
    object_name: str = "test.obj",
    library: str | None = "testlib",
    order_index: int = 0,
    source_line: int = 1,
) -> Symbol:
    return Symbol(
        raw_name=name,
        name=name,
        demangled_name=name if not name.startswith("?") else None,
        is_mangled=name.startswith("?"),
        address=address,
        segment=1,
        offset=address,
        section=".text",
        library=library,
        object_name=object_name,
        visibility=visibility,  # type: ignore[arg-type]
        is_function=is_function,
        is_internal=None,
        raw_flags="f" if is_function else "",
        order_index=order_index,
        source_line=source_line,
    )
