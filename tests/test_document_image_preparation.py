from __future__ import annotations

import struct
from pathlib import Path

import fitz
import pytest

from app.services.document_image_preparation import (
    DocumentImagePreparationError,
    MAX_IMAGE_PIXELS,
    MAX_OCR_IMAGE_BYTES,
    prepare_image_file,
    prepare_pdf_page_image,
)


def _minimal_png(*, width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def test_pdf_page_is_rendered_to_bounded_private_jpeg(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 100), "Synthetic resume page")
    document.save(path)
    document.close()

    prepared = prepare_pdf_page_image(path=path, page_no=1)

    assert prepared.media_type == "image/jpeg"
    assert prepared.data.startswith(b"\xff\xd8")
    assert len(prepared.data) <= MAX_OCR_IMAGE_BYTES
    assert prepared.data.hex()[:32] not in repr(prepared)
    assert list(tmp_path.iterdir()) == [path]


def test_pdf_page_rejects_out_of_range_page_without_rendering(tmp_path: Path) -> None:
    path = tmp_path / "one-page.pdf"
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()

    with pytest.raises(DocumentImagePreparationError, match="invalid_page"):
        prepare_pdf_page_image(path=path, page_no=2)


def test_image_pixel_bomb_is_rejected_before_decode(tmp_path: Path) -> None:
    path = tmp_path / "pixel-bomb.png"
    path.write_bytes(_minimal_png(width=MAX_IMAGE_PIXELS, height=2))

    with pytest.raises(DocumentImagePreparationError, match="dimensions_too_large"):
        prepare_image_file(path=path)
