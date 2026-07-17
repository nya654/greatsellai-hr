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


_MAX_OCR_IMAGE_BYTES = 3_500_000


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

    lines = [
        item.DetectedText.strip()
        for item in (response.TextDetections or [])
        if item.DetectedText and item.DetectedText.strip()
    ]
    return "\n".join(lines)


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
                if len(image_bytes) <= _MAX_OCR_IMAGE_BYTES:
                    return image_bytes
        finally:
            document.close()
    except TencentOcrError:
        raise
    except (fitz.FileDataError, OSError, RuntimeError, ValueError) as exc:
        raise TencentOcrError("tencent_ocr_page_render_failed") from exc
    raise TencentOcrError("tencent_ocr_image_too_large")
