from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.ocr.v20181119 import models, ocr_client

from app.config import (
    TENCENT_OCR_API_GENERAL_ACCURATE,
    TENCENT_OCR_API_GENERAL_BASIC,
    TENCENT_OCR_APIS,
)
from app.services import document_image_preparation as image_preparation
from app.services.document_image_preparation import DocumentImagePreparationError


_MAX_OCR_IMAGE_BYTES = image_preparation.MAX_OCR_IMAGE_BYTES
_MAX_RENDERED_PDF_IMAGE_BYTES = image_preparation.MAX_RENDERED_PDF_IMAGE_BYTES
_MAX_REENCODE_IMAGE_PIXELS = image_preparation.MAX_IMAGE_PIXELS


class TencentOcrError(RuntimeError):
    """A UI-safe OCR provider failure; raw provider output is never retained."""


@dataclass(frozen=True)
class TencentOcrConfig:
    secret_id: str
    secret_key: str
    region: str
    timeout_seconds: int
    api: str = TENCENT_OCR_API_GENERAL_BASIC


def extract_pdf_page_text(
    *,
    path: Path,
    page_no: int,
    config: TencentOcrConfig,
) -> str:
    """Render one PDF page locally and submit only its bytes to Tencent OCR."""

    image_bytes = _render_page_for_ocr(path=path, page_no=page_no)
    return _extract_tencent_ocr(image_bytes=image_bytes, config=config)


def extract_image_text(
    *,
    path: Path,
    config: TencentOcrConfig,
) -> str:
    """Submit a bounded PNG/JPEG original without publishing a file URL."""

    image_bytes = _prepare_image_for_ocr(path=path)
    return _extract_tencent_ocr(image_bytes=image_bytes, config=config)


def _extract_tencent_ocr(
    *,
    image_bytes: bytes,
    config: TencentOcrConfig,
) -> str:
    if not image_bytes:
        raise TencentOcrError("tencent_ocr_invalid_image")
    if len(image_bytes) > _MAX_OCR_IMAGE_BYTES:
        raise TencentOcrError("tencent_ocr_image_too_large")
    if config.api not in TENCENT_OCR_APIS:
        raise TencentOcrError("tencent_ocr_request_invalid")
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
        request = (
            models.GeneralAccurateOCRRequest()
            if config.api == TENCENT_OCR_API_GENERAL_ACCURATE
            else models.GeneralBasicOCRRequest()
        )
        request.from_json_string(
            json.dumps(
                {"ImageBase64": base64.b64encode(image_bytes).decode("ascii")},
                separators=(",", ":"),
            )
        )
        response = (
            client.GeneralAccurateOCR(request)
            if config.api == TENCENT_OCR_API_GENERAL_ACCURATE
            else client.GeneralBasicOCR(request)
        )
    except TencentCloudSDKException as exc:
        raise TencentOcrError(_provider_error_code(exc)) from exc
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


def _provider_error_code(exc: TencentCloudSDKException) -> str:
    raw_code = (exc.get_code() or "").strip().lower()
    if raw_code in {"authfailure", "unauthorizedoperation"} or raw_code.startswith(
        ("authfailure.", "unauthorizedoperation.")
    ):
        return "tencent_ocr_auth_failed"
    if raw_code in {
        "invalidparameter",
        "invalidparametervalue",
        "unsupportedoperation",
    } or raw_code.startswith(
        ("invalidparameter.", "invalidparametervalue.", "unsupportedoperation.")
    ):
        return "tencent_ocr_request_invalid"
    if raw_code in {"requestlimitexceeded", "limitexceeded"} or raw_code.startswith(
        ("requestlimitexceeded.", "limitexceeded.")
    ):
        return "tencent_ocr_rate_limited"
    return "tencent_ocr_request_failed"


def _preparation_error(exc: DocumentImagePreparationError) -> TencentOcrError:
    code = str(exc)
    if code.startswith("document_ocr_"):
        code = f"tencent_ocr_{code.removeprefix('document_ocr_')}"
    else:
        code = "tencent_ocr_image_prepare_failed"
    return TencentOcrError(code)


def _prepare_image_for_ocr(*, path: Path) -> bytes:
    try:
        return image_preparation.prepare_image_file(path=path).data
    except DocumentImagePreparationError as exc:
        raise _preparation_error(exc) from exc


def _render_page_for_ocr(*, path: Path, page_no: int) -> bytes:
    try:
        return image_preparation.prepare_pdf_page_image(path=path, page_no=page_no).data
    except DocumentImagePreparationError as exc:
        raise _preparation_error(exc) from exc


# Compatibility helpers retained for focused provider tests and downstream code
# that imported the old private names during the image-budget rollout.
def _image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    try:
        return image_preparation.image_dimensions(image_bytes)
    except DocumentImagePreparationError as exc:
        raise _preparation_error(exc) from exc


def _reencode_image_within_ocr_limit(*, path: Path) -> bytes:
    try:
        return image_preparation._reencode_image_within_limit(path=path).data
    except DocumentImagePreparationError as exc:
        raise _preparation_error(exc) from exc


def _encode_pixmap_as_jpeg(pixmap: object, *, quality: int) -> bytes:
    try:
        return image_preparation.encode_pixmap_as_jpeg(pixmap, quality=quality)  # type: ignore[arg-type]
    except DocumentImagePreparationError as exc:
        raise _preparation_error(exc) from exc


def _flatten_alpha_on_white(pixmap: object) -> object:
    try:
        return image_preparation.flatten_alpha_on_white(pixmap)  # type: ignore[arg-type]
    except DocumentImagePreparationError as exc:
        raise _preparation_error(exc) from exc


__all__ = [
    "TencentOcrConfig",
    "TencentOcrError",
    "extract_image_text",
    "extract_pdf_page_text",
]
