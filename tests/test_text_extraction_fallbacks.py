from __future__ import annotations

from app.services import text_extraction
from app.services.tencent_ocr_provider import TencentOcrConfig, TencentOcrError


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    is_encrypted = False

    def __init__(self, text: str) -> None:
        self.pages = [_FakePage(text)]


def _ocr_config() -> TencentOcrConfig:
    return TencentOcrConfig(
        secret_id="test-secret-id",
        secret_key="test-secret-key",
        region="ap-guangzhou",
        timeout_seconds=5,
    )


def test_sparse_native_text_is_replaced_by_tencent_ocr(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        text_extraction,
        "PdfReader",
        lambda path: _FakeReader("short"),
    )
    monkeypatch.setattr(
        text_extraction,
        "_extract_pymupdf_page_texts",
        lambda path, pages: {},
    )
    calls: list[dict[str, object]] = []

    def fake_ocr(**kwargs: object) -> str:
        calls.append(kwargs)
        return "OCR recovered education skills project experience " * 20

    monkeypatch.setattr(text_extraction, "extract_pdf_page_text", fake_ocr)

    result = text_extraction.extract_pdf_text(
        tmp_path / "resume.pdf",
        min_text_chars_per_page=20,
        ocr_sparse_text_chars_per_page=100,
        tencent_ocr_config=_ocr_config(),
    )

    assert result.status == "text_ready"
    assert result.pages[0].text.startswith("OCR recovered")
    assert result.parsed_page_count == 1
    assert "tencent-ocr" in result.parser_version
    assert len(calls) == 1
    assert calls[0]["page_no"] == 1


def test_better_pymupdf_text_avoids_an_ocr_request(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        text_extraction,
        "PdfReader",
        lambda path: _FakeReader("short native text"),
    )
    monkeypatch.setattr(
        text_extraction,
        "_extract_pymupdf_page_texts",
        lambda path, pages: {1: "PyMuPDF recovered text " * 30},
    )

    def should_not_call_ocr(**kwargs: object) -> str:
        raise AssertionError("OCR should not run when native fallback is sufficient")

    monkeypatch.setattr(text_extraction, "extract_pdf_page_text", should_not_call_ocr)

    result = text_extraction.extract_pdf_text(
        tmp_path / "resume.pdf",
        min_text_chars_per_page=20,
        ocr_sparse_text_chars_per_page=100,
        tencent_ocr_config=_ocr_config(),
    )

    assert result.status == "text_ready"
    assert result.pages[0].text.startswith("PyMuPDF recovered")
    assert "pymupdf" in result.parser_version
    assert "tencent-ocr" not in result.parser_version


def test_failed_ocr_does_not_silently_accept_sparse_native_text(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        text_extraction,
        "PdfReader",
        lambda path: _FakeReader("short"),
    )
    monkeypatch.setattr(
        text_extraction,
        "_extract_pymupdf_page_texts",
        lambda path, pages: {},
    )

    def failed_ocr(**kwargs: object) -> str:
        raise TencentOcrError("tencent_ocr_request_failed")

    monkeypatch.setattr(text_extraction, "extract_pdf_page_text", failed_ocr)

    result = text_extraction.extract_pdf_text(
        tmp_path / "resume.pdf",
        min_text_chars_per_page=10,
        ocr_sparse_text_chars_per_page=100,
        tencent_ocr_config=_ocr_config(),
    )

    assert result.status == "needs_review"
    assert result.pages[0].text == "short"
    assert "page_1_tencent_ocr_failed" in result.quality_flags
