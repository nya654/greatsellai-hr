from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.tencent_ocr_provider import (
    TencentOcrConfig,
    TencentOcrError,
    extract_pdf_page_text,
)


NON_WHITESPACE = re.compile(r"\S")


class PdfExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractedPage:
    page_no: int
    text: str
    non_whitespace_chars: int


@dataclass(frozen=True)
class PdfExtractionResult:
    source_page_count: int
    parsed_page_count: int
    pages: list[ExtractedPage]
    raw_text: str
    quality_flags: list[str]
    parser_version: str

    @property
    def status(self) -> str:
        return "text_ready" if not self.quality_flags else "needs_review"


def extract_pdf_text(
    path: Path,
    *,
    min_text_chars_per_page: int,
    ocr_sparse_text_chars_per_page: int = 500,
    tencent_ocr_config: TencentOcrConfig | None = None,
) -> PdfExtractionResult:
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfExtractionError("pdf_open_failed") from exc

    if reader.is_encrypted:
        raise PdfExtractionError("encrypted_pdf")

    try:
        source_page_count = len(reader.pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfExtractionError("pdf_page_count_failed") from exc

    if source_page_count < 1:
        raise PdfExtractionError("empty_pdf")

    if ocr_sparse_text_chars_per_page < min_text_chars_per_page:
        raise ValueError("ocr_sparse_text_chars_per_page_must_cover_minimum_text")

    page_texts: list[str] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except (PdfReadError, OSError, ValueError) as exc:
            # PyMuPDF and OCR can still recover this page; do not fail the
            # whole upload before the configured fallbacks get a chance.
            text = ""

        page_texts.append(text)

    parser_labels = [f"pypdf-{importlib.metadata.version('pypdf')}"]
    sparse_page_numbers = [
        page_no
        for page_no, text in enumerate(page_texts, start=1)
        if _non_whitespace_char_count(text) < ocr_sparse_text_chars_per_page
    ]
    if sparse_page_numbers:
        native_fallbacks = _extract_pymupdf_page_texts(path, sparse_page_numbers)
        for page_no in sparse_page_numbers:
            fallback_text = native_fallbacks.get(page_no, "")
            if _non_whitespace_char_count(fallback_text) > _non_whitespace_char_count(
                page_texts[page_no - 1]
            ):
                page_texts[page_no - 1] = fallback_text
                if "pymupdf" not in parser_labels:
                    parser_labels.append("pymupdf")

    ocr_failed_pages: set[int] = set()
    if tencent_ocr_config is not None:
        for page_no, text in enumerate(page_texts, start=1):
            if _non_whitespace_char_count(text) >= ocr_sparse_text_chars_per_page:
                continue
            try:
                ocr_text = extract_pdf_page_text(
                    path=path,
                    page_no=page_no,
                    config=tencent_ocr_config,
                )
            except TencentOcrError:
                ocr_failed_pages.add(page_no)
                continue
            if _non_whitespace_char_count(ocr_text) > _non_whitespace_char_count(text):
                page_texts[page_no - 1] = ocr_text
                if "tencent-ocr" not in parser_labels:
                    parser_labels.append("tencent-ocr")

    pages: list[ExtractedPage] = []
    flags: list[str] = []
    for page_no, text in enumerate(page_texts, start=1):
        non_whitespace_chars = len(NON_WHITESPACE.findall(text))
        pages.append(
            ExtractedPage(
                page_no=page_no,
                text=text,
                non_whitespace_chars=non_whitespace_chars,
            )
        )
        if non_whitespace_chars < min_text_chars_per_page:
            flags.append(f"page_{page_no}_insufficient_text")
        if text and text.count("\ufffd") / max(len(text), 1) > 0.01:
            flags.append(f"page_{page_no}_possible_mojibake")
        if (
            page_no in ocr_failed_pages
            and non_whitespace_chars < min_text_chars_per_page
        ):
            flags.append(f"page_{page_no}_tencent_ocr_failed")

    parsed_page_count = sum(
        page.non_whitespace_chars >= min_text_chars_per_page for page in pages
    )
    if parsed_page_count != source_page_count:
        flags.append("parsed_page_count_mismatch")

    raw_text = "\n\n".join(
        f"--- PAGE {page.page_no} ---\n{page.text}" for page in pages if page.text
    )
    if not raw_text:
        flags.append("no_extractable_text")

    return PdfExtractionResult(
        source_page_count=source_page_count,
        parsed_page_count=parsed_page_count,
        pages=pages,
        raw_text=raw_text,
        quality_flags=sorted(set(flags)),
        parser_version="+".join(parser_labels),
    )


def _non_whitespace_char_count(text: str) -> int:
    return len(NON_WHITESPACE.findall(text))


def _extract_pymupdf_page_texts(path: Path, page_numbers: list[int]) -> dict[int, str]:
    """Return a best-effort native fallback; OCR remains the final fallback."""

    try:
        document = fitz.open(str(path))
        try:
            return {
                page_no: document.load_page(page_no - 1).get_text("text").strip()
                for page_no in page_numbers
                if 1 <= page_no <= document.page_count
            }
        finally:
            document.close()
    except (fitz.FileDataError, OSError, RuntimeError, ValueError):
        return {}
