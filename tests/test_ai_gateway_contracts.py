from __future__ import annotations

import base64
import json
import urllib.error
from dataclasses import fields, replace
from typing import Any

import pytest

from app.ai.adapters.openai_compatible import OpenAICompatibleAdapter
from app.ai.contracts import (
    ChatMessage,
    CompletionRequest,
    GatewayContractError,
    InlineImageContentPart,
    RouteAuthentication,
    RouteTarget,
    ToolCall,
    ToolChoice,
    ToolDefinition,
    TextContentPart,
)
from app.ai.errors import ProviderError, ProviderErrorCategory, ProviderResponseError
from app.services.deepseek_provider import DeepSeekProviderError, _post_chat_completion


class _FakeResponse:
    def __init__(self, body: dict[str, object], *, status: int = 200) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"X-Request-Id": "request-test-42"}
        self._status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def getcode(self) -> int:
        return self._status


def _route() -> RouteTarget:
    return RouteTarget(
        id="route-target-001",
        driver="openai_compatible",
        provider_profile_id="provider-profile-001",
        model_profile_id="model-profile-001",
        endpoint_url="https://gateway-test.invalid/v1/chat/completions",
        provider_model_id="approved-model-001",
        timeout_seconds=12,
        credential="test-credential",
        authentication=RouteAuthentication(
            header_name="Authorization",
            value_prefix="Bearer ",
        ),
        headers={"X-Route-Test": "enabled"},
        request_defaults={"top_p": 0.8},
    )


def _request() -> CompletionRequest:
    return CompletionRequest(
        feature="resume_extract_rich",
        organization_id="organization-001",
        actor_user_id="user-001",
        run_id="run-001",
        business_ref_type="resume_ai_extraction_job",
        business_ref_id="job-001",
        prompt_revision_id="prompt-001",
        contract_version="resume_facts.v2",
        messages=(
            ChatMessage(role="system", content="Return only source-grounded facts."),
            ChatMessage(role="user", content="Candidate fact snapshot."),
        ),
        tools=(
            ToolDefinition(
                name="submit_facts",
                description="Submit grounded facts.",
                parameters={"type": "object", "properties": {}},
                strict=True,
            ),
        ),
        tool_choice=ToolChoice.named("submit_facts"),
        required_capabilities=frozenset({"forced_tool_choice"}),
        max_output_tokens=500,
        temperature=0,
    )


def test_completion_request_has_no_provider_connection_fields() -> None:
    field_names = {field.name for field in fields(CompletionRequest)}
    assert field_names.isdisjoint(
        {
            "provider",
            "provider_id",
            "model",
            "model_id",
            "api_key",
            "credential",
            "url",
            "endpoint_url",
            "route_preference",
        }
    )

    with pytest.raises(TypeError):
        CompletionRequest(
            feature="resume_extract_rich",
            organization_id="organization-001",
            messages=(ChatMessage(role="user", content="test"),),
            model="must-not-be-accepted",  # type: ignore[call-arg]
        )


def test_legacy_direct_transport_is_rejected_without_a_gateway_context() -> None:
    with pytest.raises(DeepSeekProviderError, match="ai_gateway_context_required"):
        _post_chat_completion(
            api_key="must-not-be-used",
            timeout_seconds=1,
            payload={"messages": [{"role": "user", "content": "test"}]},
        )


@pytest.mark.parametrize(
    "unsafe_endpoint",
    [
        "http://provider.example.test/v1/chat/completions",
        "https://user:password@provider.example.test/v1/chat/completions",
        "https://127.0.0.1/v1/chat/completions",
        "https://[::1]/v1/chat/completions",
        "https://localhost/v1/chat/completions",
    ],
)
def test_route_target_rejects_unsafe_provider_endpoints(unsafe_endpoint: str) -> None:
    with pytest.raises(GatewayContractError):
        replace(_route(), endpoint_url=unsafe_endpoint)


def test_inline_image_contract_requires_private_bytes_and_explicit_vision() -> None:
    private_image = b"private-candidate-page"
    image = InlineImageContentPart(
        media_type="image/jpeg",
        data=private_image,
        detail="high",
    )
    message = ChatMessage(
        role="user",
        content=(
            TextContentPart("Transcribe the page."),
            image,
        ),
    )

    assert private_image.decode("ascii") not in repr(image)
    assert private_image.decode("ascii") not in repr(message)
    with pytest.raises(GatewayContractError, match="non_empty_bytes"):
        InlineImageContentPart(
            media_type="image/jpeg",
            data="https://untrusted.invalid/page.jpg",  # type: ignore[arg-type]
        )
    with pytest.raises(GatewayContractError, match="require_user_role"):
        ChatMessage(role="system", content=(image,))
    with pytest.raises(GatewayContractError, match="require_vision"):
        CompletionRequest(
            feature="resume_ocr_page",
            organization_id="organization-001",
            messages=(message,),
            data_classification="candidate_image",
        )
    with pytest.raises(GatewayContractError, match="candidate_image_classification"):
        CompletionRequest(
            feature="resume_ocr_page",
            organization_id="organization-001",
            messages=(message,),
            required_capabilities=frozenset({"chat", "vision"}),
        )


def test_openai_compatible_adapter_serializes_inline_image_only_at_transport() -> None:
    captured: dict[str, Any] = {}
    image_bytes = b"private-candidate-page"
    request = CompletionRequest(
        feature="resume_ocr_page",
        organization_id="organization-001",
        messages=(
            ChatMessage(role="system", content="Transcribe only."),
            ChatMessage(
                role="user",
                content=(
                    TextContentPart("Read every visible line."),
                    InlineImageContentPart(
                        media_type="image/jpeg",
                        data=image_bytes,
                        detail="high",
                    ),
                ),
            ),
        ),
        required_capabilities=frozenset({"chat", "vision"}),
        data_classification="candidate_image",
        max_output_tokens=4096,
        temperature=0,
    )

    def fake_urlopen(http_request: Any, *, timeout: float) -> _FakeResponse:
        captured["request"] = http_request
        assert timeout == 12
        return _FakeResponse(
            {
                "id": "vision-response-001",
                "model": "MiniMax-M3",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "transcribed text"}}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3},
            }
        )

    result = OpenAICompatibleAdapter(opener=fake_urlopen).complete(request, _route())

    payload = json.loads(captured["request"].data.decode("utf-8"))
    parts = payload["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "Read every visible line."}
    assert parts[1] == {
        "type": "image_url",
        "image_url": {
            "url": (
                "data:image/jpeg;base64,"
                + base64.b64encode(image_bytes).decode("ascii")
            ),
            "detail": "high",
        },
    }
    assert result.content == "transcribed text"
    assert image_bytes.decode("ascii") not in repr(request)


def test_openai_compatible_adapter_serializes_resolved_route_and_normalizes_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(http_request: Any, *, timeout: float) -> _FakeResponse:
        captured["request"] = http_request
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "id": "response-001",
                "debug_payload": "candidate-private-text",
                "model": "provider-response-model-001",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-001",
                                    "type": "function",
                                    "function": {
                                        "name": "submit_facts",
                                        "arguments": '{"education":[]}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 9,
                    "total_tokens": 21,
                    "prompt_tokens_details": {"cached_tokens": 2},
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = OpenAICompatibleAdapter().complete(_request(), _route())

    request = captured["request"]
    assert request.full_url == "https://gateway-test.invalid/v1/chat/completions"
    assert captured["timeout"] == 12.0
    sent_headers = {name.casefold(): value for name, value in request.header_items()}
    assert sent_headers["authorization"] == "Bearer test-credential"
    assert sent_headers["x-route-test"] == "enabled"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "approved-model-001"
    assert payload["max_tokens"] == 500
    assert payload["temperature"] == 0.0
    assert payload["stream"] is False
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_facts"},
    }
    assert payload["tools"][0]["function"]["strict"] is True

    assert result.provider_request_id == "request-test-42"
    assert result.provider_response_id == "response-001"
    assert result.model_id == "provider-response-model-001"
    assert result.tool_calls[0].name == "submit_facts"
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.cached_read_input_tokens == 2
    assert result.usage.output_tokens == 6
    assert result.usage.reasoning_tokens == 3
    assert result.usage.request_units == 1
    assert result.usage.metered_token_total == 21
    assert result.raw_response["id"] == "response-001"
    assert "candidate-private-text" not in repr(result)


def test_openai_compatible_adapter_keeps_null_content_for_assistant_tool_calls() -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(http_request: Any, *, timeout: float) -> _FakeResponse:
        captured["request"] = http_request
        assert timeout == 12
        return _FakeResponse(
            {
                "id": "response-tool-follow-up",
                "model": "provider-response-model-001",
                "choices": [{"finish_reason": "stop", "message": {"content": "已完成"}}],
            }
        )

    request = replace(
        _request(),
        metadata={},
        messages=(
            ChatMessage(role="system", content="Use tools when needed."),
            ChatMessage(role="user", content="Find the strongest candidate."),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call-search-001",
                        name="search_candidates",
                        arguments='{"skill":"RAG"}',
                    ),
                ),
            ),
            ChatMessage(
                role="tool",
                tool_call_id="call-search-001",
                content='{"items":[]}',
            ),
        ),
    )

    OpenAICompatibleAdapter(opener=fake_urlopen).complete(request, _route())

    payload = json.loads(captured["request"].data.decode("utf-8"))
    assistant_message = payload["messages"][2]
    assert assistant_message["role"] == "assistant"
    assert "content" in assistant_message
    assert assistant_message["content"] is None
    assert assistant_message["tool_calls"][0]["id"] == "call-search-001"


def test_openai_compatible_adapter_treats_empty_usage_as_unknown() -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(
            {
                "id": "response-no-usage",
                "model": "provider-response-model-001",
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {},
            }
        )

    result = OpenAICompatibleAdapter(opener=fake_urlopen).complete(_request(), _route())

    assert result.usage is None


def test_openai_compatible_adapter_does_not_price_total_tokens_only_as_zero() -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(
            {
                "id": "response-total-only-usage",
                "model": "provider-response-model-001",
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"total_tokens": 42},
            }
        )

    result = OpenAICompatibleAdapter(opener=fake_urlopen).complete(_request(), _route())

    assert result.usage is None


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (401, ProviderErrorCategory.AUTH, False),
        (429, ProviderErrorCategory.RATE_LIMITED, True),
        (503, ProviderErrorCategory.PROVIDER_5XX, True),
    ],
)
def test_openai_compatible_adapter_classifies_http_errors_without_raw_body(
    status_code: int,
    category: ProviderErrorCategory,
    retryable: bool,
) -> None:
    def failing_urlopen(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError(
            url="https://gateway-test.invalid/v1/chat/completions",
            code=status_code,
            msg="provider response omitted",
            hdrs={"X-Request-Id": "error-request-001"},
            fp=None,
        )

    with pytest.raises(ProviderError) as raised:
        OpenAICompatibleAdapter(opener=failing_urlopen).complete(_request(), _route())

    error = raised.value
    assert error.category is category
    assert error.retryable is retryable
    assert error.provider_request_id == "error-request-001"
    assert "provider response omitted" not in str(error)


def test_openai_compatible_adapter_marks_network_failure_as_possibly_billed() -> None:
    def failing_urlopen(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("connection failed")

    with pytest.raises(ProviderError) as raised:
        OpenAICompatibleAdapter(opener=failing_urlopen).complete(_request(), _route())

    assert raised.value.category is ProviderErrorCategory.NETWORK
    assert raised.value.retryable is True
    assert raised.value.may_have_billed is True


def test_openai_compatible_adapter_rejects_oversized_response_body() -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(
            {
                "id": "oversized-response",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "x" * (8 * 1024 * 1024)},
                    }
                ],
            }
        )

    with pytest.raises(ProviderResponseError):
        OpenAICompatibleAdapter(opener=fake_urlopen).complete(_request(), _route())


def test_openai_compatible_adapter_rejects_malformed_response() -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse({"id": "response-malformed", "choices": []})

    with pytest.raises(ProviderResponseError) as raised:
        OpenAICompatibleAdapter(opener=fake_urlopen).complete(_request(), _route())

    assert raised.value.category is ProviderErrorCategory.STRUCTURED_INVALID
    assert raised.value.may_have_billed is True
