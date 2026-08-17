from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Literal

import fitz


MAX_OCR_IMAGE_BYTES = 7 * 1024 * 1024
MAX_RENDERED_PDF_IMAGE_BYTES = 3_500_000
MAX_IMAGE_PIXELS = 12_000_000
MAX_IMAGE_DIMENSION = 12_000
MAX_SOURCE_IMAGE_BYTES = 15 * 1024 * 1024
_MAX_JPEG_DIMENSION_HEADER_BYTES = 1024 * 1024
_RENDER_SCALES = (2.0, 1.6, 1.3, 1.0)
_RENDER_QUALITIES = (90, 82, 74)
_IMAGE_REENCODE_SCALES = (1.0, 0.8, 0.65, 0.5, 0.4)
_IMAGE_REENCODE_QUALITIES = (85, 75, 65)


class DocumentImagePreparationError(RuntimeError):
    """A content-free failure while preparing an in-memory OCR image."""


@dataclass(frozen=True, slots=True)
class PreparedDocumentImage:
    media_type: Literal["image/png", "image/jpeg"]
    data: bytes = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.media_type not in {"image/png", "image/jpeg"}:
            raise DocumentImagePreparationError("document_ocr_invalid_image")
        if not isinstance(self.data, bytes) or not self.data:
            raise DocumentImagePreparationError("document_ocr_invalid_image")
        if len(self.data) > MAX_OCR_IMAGE_BYTES:
            raise DocumentImagePreparationError("document_ocr_image_too_large")


def prepare_pdf_page_image(*, path: Path, page_no: int) -> PreparedDocumentImage:
    """Render one PDF page within fixed pixel and request-size budgets."""

    if page_no < 1:
        raise DocumentImagePreparationError("document_ocr_invalid_page")
    try:
        document = fitz.open(str(path))
        try:
            if page_no > document.page_count:
                raise DocumentImagePreparationError("document_ocr_invalid_page")
            page = document.load_page(page_no - 1)
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            if (
                not math.isfinite(page_width)
                or not math.isfinite(page_height)
                or page_width <= 0
                or page_height <= 0
            ):
                raise DocumentImagePreparationError("document_ocr_page_render_failed")

            attempted_scales: set[float] = set()
            for requested_scale in _RENDER_SCALES:
                scale = _bounded_render_scale(
                    width=page_width,
                    height=page_height,
                    requested_scale=requested_scale,
                )
                normalized_scale = round(scale, 6)
                if normalized_scale in attempted_scales:
                    continue
                attempted_scales.add(normalized_scale)
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csGRAY,
                    alpha=False,
                )
                _validate_pixmap_dimensions(pixmap)
                for quality in _RENDER_QUALITIES:
                    image_bytes = pixmap.tobytes("jpeg", jpg_quality=quality)
                    if len(image_bytes) <= MAX_RENDERED_PDF_IMAGE_BYTES:
                        return PreparedDocumentImage(
                            media_type="image/jpeg",
                            data=image_bytes,
                        )
        finally:
            document.close()
    except DocumentImagePreparationError:
        raise
    except (fitz.FileDataError, OSError, RuntimeError, ValueError) as exc:
        raise DocumentImagePreparationError("document_ocr_page_render_failed") from exc
    raise DocumentImagePreparationError("document_ocr_image_too_large")


def prepare_image_file(*, path: Path) -> PreparedDocumentImage:
    """Read or safely re-encode a PNG/JPEG without mutating its original."""

    try:
        source_size = path.stat().st_size
        if source_size < 1:
            raise DocumentImagePreparationError("document_ocr_invalid_image")
        if source_size > MAX_SOURCE_IMAGE_BYTES:
            raise DocumentImagePreparationError("document_ocr_image_too_large")
        image_bytes = path.read_bytes()
    except DocumentImagePreparationError:
        raise
    except OSError as exc:
        raise DocumentImagePreparationError("document_ocr_image_open_failed") from exc

    width, height = image_dimensions(image_bytes)
    _validate_dimensions(width=width, height=height)
    if len(image_bytes) <= MAX_OCR_IMAGE_BYTES:
        media_type = "image/png" if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
        return PreparedDocumentImage(media_type=media_type, data=image_bytes)
    return _reencode_image_within_limit(path=path)


def _bounded_render_scale(*, width: float, height: float, requested_scale: float) -> float:
    pixel_scale = math.sqrt(MAX_IMAGE_PIXELS / (width * height))
    dimension_scale = min(MAX_IMAGE_DIMENSION / width, MAX_IMAGE_DIMENSION / height)
    scale = min(requested_scale, pixel_scale, dimension_scale)
    if not math.isfinite(scale) or scale <= 0:
        raise DocumentImagePreparationError("document_ocr_page_render_failed")
    return scale


def _reencode_image_within_limit(*, path: Path) -> PreparedDocumentImage:
    try:
        source = fitz.Pixmap(str(path))
        _validate_pixmap_dimensions(source)
        for scale in _IMAGE_REENCODE_SCALES:
            width = max(1, round(source.width * scale))
            height = max(1, round(source.height * scale))
            _validate_dimensions(width=width, height=height)
            pixmap = (
                source
                if width == source.width and height == source.height
                else fitz.Pixmap(source, width, height, None)
            )
            for quality in _IMAGE_REENCODE_QUALITIES:
                image_bytes = encode_pixmap_as_jpeg(pixmap, quality=quality)
                if len(image_bytes) <= MAX_OCR_IMAGE_BYTES:
                    return PreparedDocumentImage(
                        media_type="image/jpeg",
                        data=image_bytes,
                    )
    except DocumentImagePreparationError:
        raise
    except (fitz.FileDataError, OSError, RuntimeError, ValueError) as exc:
        raise DocumentImagePreparationError("document_ocr_image_prepare_failed") from exc
    raise DocumentImagePreparationError("document_ocr_image_too_large")


def encode_pixmap_as_jpeg(pixmap: fitz.Pixmap, *, quality: int) -> bytes:
    opaque_pixmap = flatten_alpha_on_white(pixmap) if pixmap.alpha else pixmap
    return opaque_pixmap.tobytes("jpeg", jpg_quality=quality)


def flatten_alpha_on_white(pixmap: fitz.Pixmap) -> fitz.Pixmap:
    rgba_pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    if not rgba_pixmap.alpha or rgba_pixmap.n != 4:
        raise DocumentImagePreparationError("document_ocr_image_prepare_failed")

    source = rgba_pixmap.samples
    destination = bytearray(rgba_pixmap.width * rgba_pixmap.height * 3)
    destination_offset = 0
    for row in range(rgba_pixmap.height):
        source_offset = row * rgba_pixmap.stride
        for _column in range(rgba_pixmap.width):
            red = source[source_offset]
            green = source[source_offset + 1]
            blue = source[source_offset + 2]
            alpha = source[source_offset + 3]
            inverse_alpha = 255 - alpha
            destination[destination_offset] = (red * alpha + 255 * inverse_alpha + 127) // 255
            destination[destination_offset + 1] = (
                green * alpha + 255 * inverse_alpha + 127
            ) // 255
            destination[destination_offset + 2] = (
                blue * alpha + 255 * inverse_alpha + 127
            ) // 255
            source_offset += 4
            destination_offset += 3
    return fitz.Pixmap(
        fitz.csRGB,
        rgba_pixmap.width,
        rgba_pixmap.height,
        bytes(destination),
        False,
    )


def image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(image_bytes) < 24 or image_bytes[12:16] != b"IHDR":
            raise DocumentImagePreparationError("document_ocr_invalid_image")
        width, height = struct.unpack(">II", image_bytes[16:24])
        if width < 1 or height < 1:
            raise DocumentImagePreparationError("document_ocr_invalid_image")
        return width, height
    if image_bytes.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(image_bytes)
    raise DocumentImagePreparationError("document_ocr_invalid_image")


def _jpeg_dimensions(image_bytes: bytes) -> tuple[int, int]:
    limit = min(len(image_bytes), _MAX_JPEG_DIMENSION_HEADER_BYTES)
    offset = 2
    while offset < limit:
        while offset < limit and image_bytes[offset] != 0xFF:
            offset += 1
        while offset < limit and image_bytes[offset] == 0xFF:
            offset += 1
        if offset >= limit:
            break
        marker = image_bytes[offset]
        offset += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > limit:
            break
        segment_length = int.from_bytes(image_bytes[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > limit:
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                break
            height = int.from_bytes(image_bytes[offset + 3 : offset + 5], "big")
            width = int.from_bytes(image_bytes[offset + 5 : offset + 7], "big")
            if width > 0 and height > 0:
                return width, height
            break
        offset += segment_length
    raise DocumentImagePreparationError("document_ocr_invalid_image")


def _validate_pixmap_dimensions(pixmap: fitz.Pixmap) -> None:
    _validate_dimensions(width=pixmap.width, height=pixmap.height)


def _validate_dimensions(*, width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise DocumentImagePreparationError("document_ocr_invalid_image")
    if (
        width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise DocumentImagePreparationError("document_ocr_image_dimensions_too_large")


__all__ = [
    "DocumentImagePreparationError",
    "MAX_IMAGE_PIXELS",
    "MAX_OCR_IMAGE_BYTES",
    "PreparedDocumentImage",
    "encode_pixmap_as_jpeg",
    "flatten_alpha_on_white",
    "image_dimensions",
    "prepare_image_file",
    "prepare_pdf_page_image",
]
