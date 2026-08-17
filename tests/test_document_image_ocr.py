from __future__ import annotations

from pathlib import Path

import pytest

from app.services import document_text_extraction as document_text
from app.services.document_ocr_service import DocumentOcrError
from app.services.document_text_extraction import DocumentExtractionError
from app.services.text_extraction import PdfExtractionError


class _FakeOcrEngine:
    parser_label = "test-ocr"

    def __init__(self, callback):
        self._callback = callback

    def extract_pdf_page(self, *, path: Path, page_no: int) -> str:
        return self._callback(path=path, page_no=page_no)

    def extract_image(self, *, path: Path) -> str:
        return self._callback(path=path)


def _extract(path: Path, *, ocr_engine):
    return document_text.extract_document_text(
        path,
        min_text_chars_per_page=1,
        ocr_sparse_text_chars_per_page=1,
        ocr_engine=ocr_engine,
    )


def test_png_and_jpg_use_configured_ocr_engine(tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_image_ocr(*, path: Path) -> str:
        calls.append(path)
        return "Candidate Python project experience"

    engine = _FakeOcrEngine(fake_image_ocr)
    for suffix in (".png", ".jpg"):
        image_path = tmp_path / f"resume{suffix}"
        image_path.write_bytes(b"synthetic image")
        result = _extract(image_path, ocr_engine=engine)
        assert result.parser_version == "test-ocr"
        assert result.raw_text.endswith("Candidate Python project experience")
        assert result.ocr_attempted_page_count == 1
        assert result.ocr_successful_page_count == 1
        assert result.ocr_selected_page_count == 1
        assert result.ocr_failed_page_count == 0

    assert [path.suffix for path in calls] == [".png", ".jpg"]


def test_image_requires_ocr_configuration(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "resume.png"
    image_path.write_bytes(b"synthetic image")

    with pytest.raises(DocumentExtractionError, match="document_ocr_not_configured"):
        _extract(image_path, ocr_engine=None)


def test_image_provider_error_is_preserved_as_stable_document_failure(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "resume.jpeg"
    image_path.write_bytes(b"synthetic image")

    def fail(*_args: object, **_kwargs: object) -> str:
        raise DocumentOcrError("document_ocr_request_failed")

    with pytest.raises(DocumentExtractionError, match="document_ocr_request_failed"):
        _extract(image_path, ocr_engine=_FakeOcrEngine(fail))


def test_pdf_error_preserves_count_only_ocr_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The document boundary preserves counters but never parser text."""

    monkeypatch.setattr(
        document_text,
        "extract_pdf_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PdfExtractionError(
                "document_text_limit_exceeded",
                source_page_count=2,
                ocr_attempted_page_count=2,
                ocr_successful_page_count=1,
                ocr_selected_page_count=1,
                ocr_failed_page_count=1,
            )
        ),
    )

    with pytest.raises(DocumentExtractionError) as raised:
        _extract(
            tmp_path / "resume.pdf",
            ocr_engine=_FakeOcrEngine(lambda **kwargs: "unused"),
        )

    error = raised.value
    assert str(error) == "document_text_limit_exceeded"
    assert error.source_page_count == 2
    assert error.ocr_attempted_page_count == 2
    assert error.ocr_successful_page_count == 1
    assert error.ocr_selected_page_count == 1
    assert error.ocr_failed_page_count == 1
