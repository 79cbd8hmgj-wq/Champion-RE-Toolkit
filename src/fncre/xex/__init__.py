"""Xbox 360 XEX2/PE handling: dev-key extraction and PE/image addressing.

This package generalizes working algorithms already proven in
Fight-Night-Legacy's `tools/extract_dev_xex.py`, `tools/xex2_raw_extract.py`,
and the PE-parsing half of `tools/re_function_slice.py` — it does not
redesign them. See docs/legacy-compatibility.md for the migration/reuse
rationale for each source script.
"""

from fncre.xex.dev_extract import DEVKIT_XEX_KEY, XexExtractionError, extract_xex2
from fncre.xex.pe import (
    IMAGE_LAYOUT_PE_RAW,
    IMAGE_LAYOUT_XBOX_RVA,
    PeSection,
    parse_pe,
    section_file_window,
    va_to_file_offset,
)

__all__ = [
    "DEVKIT_XEX_KEY",
    "XexExtractionError",
    "extract_xex2",
    "IMAGE_LAYOUT_PE_RAW",
    "IMAGE_LAYOUT_XBOX_RVA",
    "PeSection",
    "parse_pe",
    "section_file_window",
    "va_to_file_offset",
]
