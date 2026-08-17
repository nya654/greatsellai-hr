from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from app.ai import CompletionRequest, CompletionResult, InlineImageContentPart
from app.services import document_ocr_service as ocr_service
from app.services.ai_gateway_service import AiExecutionSpec
from app.services.document_image_preparation import PreparedDocumentImage
from app.services.document_ocr_service import AiGatewayDocumentOcrEngine


def test_ai_gateway_ocr_engine_sends_one_private_page_request(
    ai_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    private_image = b"private-rendered-page"

    monkeypatch.setattr(
        ocr_service,
        "prepare_pdf_page_image",
        lambda **_kwargs: PreparedDocumentImage(
            media_type="image/jpeg",
            data=private_image,
        ),
    )

    class FakeExecutor:
        def complete(self, request: CompletionRequest) -> CompletionResult:
            captured["request"] = request
            return CompletionResult(
                content="Candidate Name\nPython experience",
                tool_calls=(),
                finish_reason="stop",
                provider_request_id="request-1",
                usage=None,
                raw_status_code=200,
                model_id="MiniMax-M3",
            )

    @contextmanager
    def fake_gateway(
        session: object,
        *,
        settings: object,
        spec: AiExecutionSpec,
    ) -> Iterator[FakeExecutor]:
        del session, settings
        captured["spec"] = spec
        yield FakeExecutor()

    monkeypatch.setattr(ocr_service, "ai_gateway_execution", fake_gateway)
    engine = AiGatewayDocumentOcrEngine(
        database=ai_client.app.state.database,
        settings=ai_client.app.state.settings,
        organization_id="00000000-0000-4000-8000-000000000001",
        resume_id="resume-vision-1",
        route_policy_version_id="route-version-1",
    )

    text = engine.extract_pdf_page(path=tmp_path / "resume.pdf", page_no=2)

    assert text == "Candidate Name\nPython experience"
    spec = captured["spec"]
    assert isinstance(spec, AiExecutionSpec)
    assert spec.feature == "resume_ocr_page"
    assert spec.business_ref_id == "resume-vision-1:page-2"
    assert spec.pinned_route_policy_version_id == "route-version-1"
    request = captured["request"]
    assert isinstance(request, CompletionRequest)
    assert request.required_capabilities == frozenset({"chat", "vision"})
    assert request.data_classification == "candidate_image"
    user_content = request.messages[1].content
    assert isinstance(user_content, tuple)
    image = next(part for part in user_content if isinstance(part, InlineImageContentPart))
    assert image.data == private_image
    assert private_image.decode("ascii") not in repr(request)


def test_ai_gateway_ocr_engine_rejects_empty_transcription(
    ai_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ocr_service,
        "prepare_image_file",
        lambda **_kwargs: PreparedDocumentImage(
            media_type="image/png",
            data=b"private-image",
        ),
    )

    class FakeExecutor:
        def complete(self, request: CompletionRequest) -> CompletionResult:
            del request
            return CompletionResult(
                content="",
                tool_calls=(),
                finish_reason="stop",
                provider_request_id=None,
                usage=None,
                raw_status_code=200,
                model_id="MiniMax-M3",
            )

    @contextmanager
    def fake_gateway(*args: object, **kwargs: object) -> Iterator[FakeExecutor]:
        del args, kwargs
        yield FakeExecutor()

    monkeypatch.setattr(ocr_service, "ai_gateway_execution", fake_gateway)
    engine = AiGatewayDocumentOcrEngine(
        database=ai_client.app.state.database,
        settings=ai_client.app.state.settings,
        organization_id="00000000-0000-4000-8000-000000000001",
        resume_id="resume-vision-2",
        route_policy_version_id="route-version-1",
    )

    with pytest.raises(ocr_service.DocumentOcrError, match="empty_response"):
        engine.extract_image(path=tmp_path / "resume.png")
