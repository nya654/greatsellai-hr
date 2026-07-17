from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_agent_fails_visibly_when_model_is_not_configured(client: TestClient) -> None:
    response = client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "找 985/211、3 年以上的候选人"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "agent_model_not_configured"


def test_agent_executes_model_selected_search_tool(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    calls = 0

    def fake_completion(*, settings, messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-search",
                        "type": "function",
                        "function": {
                            "name": "search_candidates",
                            "arguments": json.dumps(
                                {
                                    "is_985_211": True,
                                    "min_employment_months": 36,
                                    "skills_all_of": ["Python"],
                                    "limit": None,
                                }
                            ),
                        },
                    }
                ],
            }
        return {"content": "已按 985/211、3 年以上和 Python 条件完成筛选。"}

    monkeypatch.setattr(
        "app.services.recruiting_agent_service._model_completion",
        fake_completion,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "找 985/211、3 年以上 Python 的候选人"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "已按 985/211、3 年以上和 Python 条件完成筛选。"
    assert payload["tool_trace"][0]["tool"] == "简历筛选"
    assert "Python" in payload["tool_trace"][0]["summary"]
    assert calls == 2
