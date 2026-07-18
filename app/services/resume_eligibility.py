"""Shared eligibility checks for using a resume in automated screening.

The parser can occasionally recover a long string of glyphs from a PDF whose
embedded font has a broken Unicode map.  Those strings look populated to a
length-only check, but they are not safe evidence for filtering, scoring, or
JD matching.  Keep the interpretation of those parser flags in one place so
every screening entry point applies the same protection.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.models import Resume


SOURCE_TEXT_UNRELIABLE_FLAG = "source_text_unreliable"
_UNRELIABLE_PAGE_FLAG = re.compile(
    r"page_\d+_(?:source_text_unreliable|possible_mojibake)$",
    re.IGNORECASE,
)


def has_unreliable_source_text(quality_flags: object) -> bool:
    """Return whether parser flags say the extracted source cannot be trusted.

    The legacy ``possible_mojibake`` page flag remains blocking.  A successful
    ``*_pymupdf_text_recovered`` flag is deliberately *not* blocking: it means
    the fallback supplied readable source text.
    """

    if not isinstance(quality_flags, Iterable) or isinstance(
        quality_flags,
        (str, bytes, bytearray),
    ):
        return False
    for raw_flag in quality_flags:
        if not isinstance(raw_flag, str):
            continue
        flag = raw_flag.strip()
        if flag.lower() == SOURCE_TEXT_UNRELIABLE_FLAG:
            return True
        if _UNRELIABLE_PAGE_FLAG.fullmatch(flag):
            return True
    return False


def is_resume_screening_eligible(resume: Resume) -> bool:
    """Whether this version may feed automated recruiter-facing decisions."""

    return (
        resume.is_active
        and resume.extraction_status == "ready"
        and not has_unreliable_source_text(resume.quality_flags)
    )


__all__ = [
    "SOURCE_TEXT_UNRELIABLE_FLAG",
    "has_unreliable_source_text",
    "is_resume_screening_eligible",
]
