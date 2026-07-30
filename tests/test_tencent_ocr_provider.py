from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import tencent_ocr_provider as provider
from app.services.tencent_ocr_provider import TencentOcrConfig, TencentOcrError


def _config() -> TencentOcrConfig:
    return TencentOcrConfig(
        secret_id="test-secret-id",
        secret_key="test-secret-key",
        region="ap-guangzhou",
        timeout_seconds=5,
    )


def test_image_ocr_uses_base64_without_public_image_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "resume.jpg"
    image_bytes = b"\xff\xd8synthetic-resume-image"
    image_path.write_bytes(image_bytes)
    captured: dict[str, object] = {}

    class FakeRequest:
        def from_json_string(self, value: str) -> None:
            captured["request"] = json.loads(value)

    class FakeClient:
        def __init__(self, *_args: object) -> None:
            pass

        def GeneralBasicOCR(self, _request: object) -> object:
            return SimpleNamespace(
                TextDetections=[
                    SimpleNamespace(DetectedText="  Candidate Name  "),
                    SimpleNamespace(DetectedText=""),
                    SimpleNamespace(DetectedText="Python"),
                ]
            )

    monkeypatch.setattr(provider.models, "GeneralBasicOCRRequest", FakeRequest)
    monkeypatch.setattr(provider.ocr_client, "OcrClient", FakeClient)

    result = provider.extract_image_text(path=image_path, config=_config())

    assert result == "Candidate Name\nPython"
    payload = captured["request"]
    assert isinstance(payload, dict)
    assert set(payload) == {"ImageBase64"}
    assert base64.b64decode(str(payload["ImageBase64"])) == image_bytes


def test_oversized_image_is_reencoded_before_tencent_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "large.jpg"
    image_path.write_bytes(b"x" * (provider._MAX_OCR_IMAGE_BYTES + 1))
    captured: dict[str, object] = {}

    def fake_reencode(*, path: Path) -> bytes:
        captured["reencode_path"] = path
        return b"compressed-image"

    def fake_request(*, image_bytes: bytes, config: TencentOcrConfig) -> str:
        captured["image_bytes"] = image_bytes
        captured["config"] = config
        return "Recovered text"

    monkeypatch.setattr(provider, "_reencode_image_within_ocr_limit", fake_reencode)
    monkeypatch.setattr(provider, "_extract_general_basic_ocr", fake_request)

    assert provider.extract_image_text(path=image_path, config=_config()) == "Recovered text"
    assert captured["reencode_path"] == image_path
    assert captured["image_bytes"] == b"compressed-image"


def test_provider_failure_does_not_expose_upstream_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "resume.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")

    class FailingClient:
        def __init__(self, *_args: object) -> None:
            raise RuntimeError("upstream credential detail must not escape")

    monkeypatch.setattr(provider.ocr_client, "OcrClient", FailingClient)

    with pytest.raises(TencentOcrError) as raised:
        provider.extract_image_text(path=image_path, config=_config())

    assert str(raised.value) == "tencent_ocr_request_failed"
