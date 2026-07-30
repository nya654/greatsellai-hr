from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import fitz
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.ocr.v20181119 import models, ocr_client


# Tencent GeneralBasicOCR accepts an ImageBase64 payload up to 10 MiB.  Base64
# expands its input by roughly 4/3, so keeping the raw image under 7 MiB leaves
# protocol headroom without relying on an undocumented server-side rounding
# rule.  PDF pages retain a lower render budget below because they are created
# locally from an untrusted PDF and a conservative raster is sufficient for
# resume text.
_MAX_OCR_IMAGE_BYTES = 7 * 1024 * 1024
_MAX_RENDERED_PDF_IMAGE_BYTES = 3_500_000
_IMAGE_REENCODE_SCALES = (1.0, 0.8, 0.65, 0.5, 0.4)
_IMAGE_REENCODE_QUALITIES = (85, 75, 65)


class TencentOcrError(RuntimeError):
    """A UI-safe OCR provider failure; raw provider output is never retained."""


@dataclass(frozen=True)
class TencentOcrConfig:
    secret_id: str
    secret_key: str
    region: str
    timeout_seconds: int


def extract_pdf_page_text(
    *,
    path: Path,
    page_no: int,
    config: TencentOcrConfig,
) -> str:
    """Render one PDF page locally and submit its Base64 bytes to Tencent OCR.

    No file URL is created: the original PDF and rendered image stay on the
    server, and the image exists only in process memory for this request.
    """

    image_bytes = _render_page_for_ocr(path=path, page_no=page_no)
    return _extract_general_basic_ocr(image_bytes=image_bytes, config=config)


def extract_image_text(
    *,
    path: Path,
    config: TencentOcrConfig,
) -> str:
    """Submit a PNG/JPEG original to Tencent OCR without publishing a URL.

    Small originals go directly from the workspace file to the provider.  A
    larger but accepted upload is locally re-encoded only when needed to stay
    below Tencent's Base64 request limit.  The original is never mutated,
    copied to public storage, or sent through an ImageUrl.
    """

    image_bytes = _prepare_image_for_ocr(path=path)
    return _extract_general_basic_ocr(image_bytes=image_bytes, config=config)


def _extract_general_basic_ocr(
    *,
    image_bytes: bytes,
    config: TencentOcrConfig,
) -> str:
    if not image_bytes:
        raise TencentOcrError("tencent_ocr_invalid_image")
    if len(image_bytes) > _MAX_OCR_IMAGE_BYTES:
        raise TencentOcrError("tencent_ocr_image_too_large")
    try:
        http_profile = HttpProfile()
        http_profile.reqTimeout = config.timeout_seconds
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        client = ocr_client.OcrClient(
            credential.Credential(config.secret_id, config.secret_key),
            config.region,
            client_profile,
        )
        request = models.GeneralBasicOCRRequest()
        request.from_json_string(
            json.dumps(
                {"ImageBase64": base64.b64encode(image_bytes).decode("ascii")},
                separators=(",", ":"),
            )
        )
        response = client.GeneralBasicOCR(request)
    except TencentCloudSDKException as exc:
        raise TencentOcrError("tencent_ocr_request_failed") from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise TencentOcrError("tencent_ocr_request_failed") from exc

    try:
        lines = [
            item.DetectedText.strip()
            for item in (response.TextDetections or [])
            if item.DetectedText and item.DetectedText.strip()
        ]
    except (AttributeError, TypeError) as exc:
        raise TencentOcrError("tencent_ocr_invalid_response") from exc
    return "\n".join(lines)


def _prepare_image_for_ocr(*, path: Path) -> bytes:
    try:
        image_bytes = path.read_bytes()
    except OSError as exc:
        raise TencentOcrError("tencent_ocr_image_open_failed") from exc
    if not image_bytes:
        raise TencentOcrError("tencent_ocr_invalid_image")
    if len(image_bytes) <= _MAX_OCR_IMAGE_BYTES:
        return image_bytes
    return _reencode_image_within_ocr_limit(path=path)


def _reencode_image_within_ocr_limit(*, path: Path) -> bytes:
    """Shrink an oversized image for Tencent without changing its original.

    This branch is intentionally rare: normal resume screenshots are submitted
    as-is and no local OCR engine is involved.  The bounded scale/quality
    ladder prevents a 15 MiB browser upload from exceeding Tencent's Base64
    request size while retaining a legible raster for text recognition.
    """

    try:
        source = fitz.Pixmap(str(path))
        if source.width < 1 or source.height < 1:
            raise TencentOcrError("tencent_ocr_invalid_image")
        for scale in _IMAGE_REENCODE_SCALES:
            width = max(1, round(source.width * scale))
            height = max(1, round(source.height * scale))
            pixmap = (
                source
                if width == source.width and height == source.height
                else fitz.Pixmap(source, width, height, None)
            )
            for quality in _IMAGE_REENCODE_QUALITIES:
                image_bytes = pixmap.tobytes("jpeg", jpg_quality=quality)
                if len(image_bytes) <= _MAX_OCR_IMAGE_BYTES:
                    return image_bytes
    except TencentOcrError:
        raise
    except (fitz.FileDataError, OSError, RuntimeError, ValueError) as exc:
        raise TencentOcrError("tencent_ocr_image_prepare_failed") from exc
    raise TencentOcrError("tencent_ocr_image_too_large")


def _render_page_for_ocr(*, path: Path, page_no: int) -> bytes:
    if page_no < 1:
        raise TencentOcrError("tencent_ocr_invalid_page")
    try:
        document = fitz.open(str(path))
        try:
            if page_no > document.page_count:
                raise TencentOcrError("tencent_ocr_invalid_page")
            page = document.load_page(page_no - 1)
            # Grayscale prevents a photo or decorative background from making
            # the Base64 request oversized while retaining readable text.
            for scale in (2.0, 1.6, 1.3):
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csGRAY,
                    alpha=False,
                )
                image_bytes = pixmap.tobytes("png")
                if len(image_bytes) <= _MAX_RENDERED_PDF_IMAGE_BYTES:
                    return image_bytes
        finally:
            document.close()
    except TencentOcrError:
        raise
    except (fitz.FileDataError, OSError, RuntimeError, ValueError) as exc:
        raise TencentOcrError("tencent_ocr_page_render_failed") from exc
    raise TencentOcrError("tencent_ocr_image_too_large")
