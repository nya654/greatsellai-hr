from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from openpyxl import load_workbook

from app.services.text_extraction import ExtractedPage, PdfExtractionError, PdfExtractionResult, extract_pdf_text
from app.services.tencent_ocr_provider import TencentOcrConfig


class DocumentExtractionError(RuntimeError):
    pass


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".xls", ".xlsx", ".html", ".htm"})


def extract_document_text(
    path: Path,
    *,
    min_text_chars_per_page: int,
    ocr_sparse_text_chars_per_page: int,
    tencent_ocr_config: TencentOcrConfig | None = None,
) -> PdfExtractionResult:
    """Normalize supported resume files into source-cited page text."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            return extract_pdf_text(path, min_text_chars_per_page=min_text_chars_per_page, ocr_sparse_text_chars_per_page=ocr_sparse_text_chars_per_page, tencent_ocr_config=tencent_ocr_config)
        except PdfExtractionError as exc:
            raise DocumentExtractionError(str(exc)) from exc
    if suffix in {".doc", ".docx"}:
        return _extract_office_as_pdf(path, min_text_chars_per_page, ocr_sparse_text_chars_per_page, tencent_ocr_config)
    if suffix in {".xls", ".xlsx"}:
        if suffix == ".xls":
            return _extract_legacy_spreadsheet(path, min_text_chars_per_page)
        return _extract_spreadsheet(path, min_text_chars_per_page)
    if suffix in {".html", ".htm"}:
        return _extract_html(path, min_text_chars_per_page)
    if suffix in {".png", ".jpg", ".jpeg"}:
        return _extract_image(path, min_text_chars_per_page)
    raise DocumentExtractionError("unsupported_document_type")


def _result(texts: list[str], minimum: int, parser: str) -> PdfExtractionResult:
    pages = [ExtractedPage(page_no=index, text=text.strip(), non_whitespace_chars=len("".join(text.split()))) for index, text in enumerate(texts, 1)]
    flags = [f"page_{page.page_no}_insufficient_text" for page in pages if page.non_whitespace_chars < minimum]
    if not any(page.text for page in pages):
        flags.append("no_extractable_text")
    return PdfExtractionResult(source_page_count=len(pages), parsed_page_count=sum(page.non_whitespace_chars >= minimum for page in pages), pages=pages, raw_text="\n\n".join(f"--- PAGE {page.page_no} ---\n{page.text}" for page in pages if page.text), quality_flags=flags, parser_version=parser)


def _extract_office_as_pdf(path: Path, minimum: int, sparse: int, config: TencentOcrConfig | None) -> PdfExtractionResult:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        try:
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(output), str(path)], check=True, capture_output=True, timeout=90)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DocumentExtractionError("office_conversion_failed") from exc
        converted = output / f"{path.stem}.pdf"
        if not converted.is_file():
            raise DocumentExtractionError("office_conversion_failed")
        try:
            return extract_pdf_text(converted, min_text_chars_per_page=minimum, ocr_sparse_text_chars_per_page=sparse, tencent_ocr_config=config)
        except PdfExtractionError as exc:
            raise DocumentExtractionError(str(exc)) from exc


def _extract_spreadsheet(path: Path, minimum: int) -> PdfExtractionResult:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        texts = ["\n".join(" | ".join(str(value).strip() for value in row if value not in (None, "")) for row in sheet.iter_rows(values_only=True) if any(value not in (None, "") for value in row)) for sheet in workbook.worksheets]
    except Exception as exc:
        raise DocumentExtractionError("spreadsheet_open_failed") from exc
    return _result(texts or [""], minimum, "openpyxl")


def _extract_legacy_spreadsheet(path: Path, minimum: int) -> PdfExtractionResult:
    """Convert legacy XLS through LibreOffice, then use the normal XLSX reader."""

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        try:
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to",
                    "xlsx",
                    "--outdir",
                    str(output),
                    str(path),
                ],
                check=True,
                capture_output=True,
                timeout=90,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DocumentExtractionError("spreadsheet_conversion_failed") from exc
        converted = output / f"{path.stem}.xlsx"
        if not converted.is_file():
            raise DocumentExtractionError("spreadsheet_conversion_failed")
        return _extract_spreadsheet(converted, minimum)


def _extract_html(path: Path, minimum: int) -> PdfExtractionResult:
    try:
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
    except OSError as exc:
        raise DocumentExtractionError("html_open_failed") from exc
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return _result([soup.get_text("\n", strip=True)], minimum, "beautifulsoup4")


def _extract_image(path: Path, minimum: int) -> PdfExtractionResult:
    try:
        completed = subprocess.run(["tesseract", str(path), "stdout", "-l", "chi_sim+eng"], check=True, capture_output=True, timeout=60)
        text = completed.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        raise DocumentExtractionError("image_ocr_failed") from exc
    return _result([text], minimum, "tesseract")
