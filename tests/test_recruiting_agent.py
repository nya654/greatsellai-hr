from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.services.recruiting_agent_service import ResolvedJob, _resolve_job


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
        return {
            "content": "## 筛选结果\n\n已按 **985/211、3 年以上和 Python** 条件完成筛选。"
        }

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
    assert payload["message"] == "## 筛选结果\n\n已按 **985/211、3 年以上和 Python** 条件完成筛选。"
    assert payload["tool_trace"][0]["tool"] == "简历筛选"
    assert "Python" in payload["tool_trace"][0]["summary"]
    assert calls == 2


def test_agent_timeout_is_returned_as_a_retryable_service_error(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    def timeout(*args, **kwargs):
        raise TimeoutError("model request timed out")

    monkeypatch.setattr(
        "app.services.recruiting_agent_service.urllib.request.urlopen",
        timeout,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "找 985/211、3 年以上的候选人"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "agent_model_timeout"


def test_agent_unexpected_exception_never_becomes_raw_internal_server_error(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_failure(*args, **kwargs):
        raise RuntimeError("unexpected agent failure")

    monkeypatch.setattr("app.main.run_recruiting_agent_turn", unexpected_failure)

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "查看当前 JD 排行榜"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "agent_service_unavailable"


def test_agent_never_uses_an_original_jd_without_matching_requirements(
    client: TestClient,
) -> None:
    original = client.post(
        "/v1/jobs/publish-original",
        json={
            "title": "Original source JD",
            "jd_text": "This source JD must not invoke AI matching.",
        },
    )
    assert original.status_code == 200, original.text
    job_version_id = original.json()["job_version_id"]

    database = client.app.state.database
    with database.session_factory() as session:
        assert _resolve_job(session, job_version_id) is None


def test_agent_starts_current_job_batch_with_runtime_settings(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    calls = 0
    captured: dict[str, object] = {}

    def fake_completion(*, settings, messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-start-batch",
                        "type": "function",
                        "function": {
                            "name": "start_current_job_match_batch",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        return {"content": "已启动当前 JD 的批量匹配。"}

    def fake_enqueue(session, *, job_version_id, settings):
        captured["job_version_id"] = job_version_id
        captured["settings"] = settings
        return SimpleNamespace(batch_id="batch-001", total_count=2, status="queued")

    monkeypatch.setattr(
        "app.services.recruiting_agent_service._model_completion",
        fake_completion,
    )
    monkeypatch.setattr(
        "app.services.recruiting_agent_service._resolve_job",
        lambda session, requested_job_version_id: ResolvedJob(
            job_version_id="job-version-001",
            title="Backend Engineer",
        ),
    )
    monkeypatch.setattr(
        "app.services.recruiting_agent_service.enqueue_job_version_match_batch",
        fake_enqueue,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "为当前 JD 批量匹配"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["batch_id"] == "batch-001"
    assert captured == {
        "job_version_id": "job-version-001",
        "settings": ai_client.app.state.settings,
    }
