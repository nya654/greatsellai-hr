from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.services.recruiting_agent_service import ResolvedJob, _TOOLS, _resolve_job
from test_filter_mvp_contract import _save_ready_resume
from test_score_service import _fake_score_provider, _template_payload


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


def test_agent_search_supports_full_recruiter_filter_contract(
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
                        "id": "call-complete-search",
                        "type": "function",
                        "function": {
                            "name": "search_candidates",
                            "arguments": json.dumps(
                                {
                                    "is_985_211": True,
                                    "min_employment_months": 36,
                                    "min_employment_or_internship_months": 42,
                                    "education_any_of": [
                                        {
                                            "degree_in": ["master"],
                                            "school_name_contains": ["清华大学"],
                                            "major_contains": ["计算机"],
                                        }
                                    ],
                                    "experience_any_of": [
                                        {
                                            "experience_types": [
                                                "employment",
                                                "internship",
                                            ],
                                            "organization_name_contains": ["Acme"],
                                            "title_contains": ["Engineer"],
                                        }
                                    ],
                                    "skills_all_of": ["Python", "SQL"],
                                    "skills_any_of": ["Kubernetes", "Ray"],
                                    "keywords_all_of": ["FastAPI"],
                                    "keywords_any_of": ["LLM", "Agent"],
                                }
                            ),
                        },
                    }
                ],
            }
        return {"content": "已按完整条件完成筛选。"}

    def fake_search(session, request):
        captured["request"] = request
        return SimpleNamespace(items=[], needs_review_count=0)

    monkeypatch.setattr(
        "app.services.recruiting_agent_service._model_completion",
        fake_completion,
    )
    monkeypatch.setattr(
        "app.services.recruiting_agent_service.search_candidates",
        fake_search,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "筛 985/211、清华计算机硕士、3 年工作且工作加实习 42 个月的 Python 人才"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "search_candidates"
    request = captured["request"]
    assert request.is_985_211 is True
    assert request.min_employment_months == 36
    assert request.min_employment_or_internship_months == 42
    assert request.education_any_of[0].degree_in == ["master"]
    assert request.education_any_of[0].school_name_contains == ["清华大学"]
    assert request.education_any_of[0].major_contains == ["计算机"]
    assert request.experience_any_of[0].experience_types == ["employment", "internship"]
    assert request.experience_any_of[0].organization_name_contains == ["Acme"]
    assert request.experience_any_of[0].title_contains == ["Engineer"]
    assert request.skills_all_of == ["Python", "SQL"]
    assert request.skills_any_of == ["Kubernetes", "Ray"]
    assert request.keywords_all_of == ["FastAPI"]
    assert request.keywords_any_of == ["LLM", "Agent"]

    search_tool = next(
        item["function"] for item in _TOOLS if item["function"]["name"] == "search_candidates"
    )
    properties = search_tool["parameters"]["properties"]
    assert {"education_any_of", "experience_any_of", "skills_all_of", "skills_any_of", "keywords_all_of", "keywords_any_of"}.issubset(properties)


def test_agent_runs_current_candidate_score_with_existing_template(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text=(
            "Education 清华大学 计算机 工作经历 "
            "Acme Python Engineer Skills Python SQL"
        ),
    )
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    calls = 0

    def fake_completion(*, settings, messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            # The model receives only server-owned template IDs, not an
            # unbounded template-creation surface.
            assert template_id in messages[-1]["content"]
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-score-current",
                        "type": "function",
                        "function": {
                            "name": "score_current_candidate",
                            "arguments": json.dumps({"template_id": template_id}),
                        },
                    }
                ],
            }
        return {"content": "## 评分结果\n\n已生成评分，请结合证据与不确定项判断。"}

    monkeypatch.setattr(
        "app.services.recruiting_agent_service._model_completion",
        fake_completion,
    )
    monkeypatch.setattr(
        "app.services.score_service.score_resume_fact_snapshot",
        _fake_score_provider,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "用现有模板给当前候选人评分", "resume_id": resume_id},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "score_current_candidate"
    assert payload["message"].startswith("## 评分结果")
    assert payload["tool_trace"] == [
        {
            "tool": "候选人评分",
            "summary": "已按“Backend Engineer”v1 为当前候选人生成 50.0 分评分",
        }
    ]
    assert payload["actions"] == [
        {
            "action": "open_resume",
            "label": "打开候选人评分详情",
            "resume_id": resume_id,
        }
    ]
    saved_scores = ai_client.get(f"/v1/resumes/{resume_id}/scores")
    assert saved_scores.status_code == 200, saved_scores.text
    assert len(saved_scores.json()) == 1
    assert saved_scores.json()[0]["template_id"] == template_id


def test_agent_never_runs_score_with_an_unlisted_template(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    calls = 0
    score_called = False

    def fake_completion(*, settings, messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-invalid-score-template",
                        "type": "function",
                        "function": {
                            "name": "score_current_candidate",
                            "arguments": json.dumps({"template_id": "invented-template"}),
                        },
                    }
                ],
            }
        assert "不存在或已归档" in messages[-1]["content"]
        return {"content": "当前模板不可用，未执行评分。"}

    def unexpected_score(*args, **kwargs):
        nonlocal score_called
        score_called = True
        raise AssertionError("unlisted template must not reach the scoring service")

    monkeypatch.setattr(
        "app.services.recruiting_agent_service._model_completion",
        fake_completion,
    )
    monkeypatch.setattr(
        "app.services.recruiting_agent_service.run_resume_score",
        unexpected_score,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={"message": "给当前候选人评分", "resume_id": "resume-not-real"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "score_current_candidate"
    assert score_called is False
