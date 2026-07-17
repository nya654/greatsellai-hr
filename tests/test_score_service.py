from __future__ import annotations

from test_filter_mvp_contract import _save_ready_resume
from app.services.deepseek_provider import FACT_SNAPSHOT_SCHEMA_VERSION


def _template_payload() -> dict[str, object]:
    return {
        "name": "Backend Engineer",
        "description": "Grounded scoring test template",
        "dimensions": [
            {
                "key": "skills",
                "label": "Skills",
                "weight": 60,
                "max_raw_score": 80,
                "guidance": "Assess explicit relevant skills only.",
            },
            {
                "key": "experience",
                "label": "Experience",
                "weight": 40,
                "max_raw_score": 100,
                "guidance": "Assess explicit work evidence only.",
            },
        ],
    }


def _fake_score_provider(**kwargs: object) -> dict[str, object]:
    snapshot = kwargs["fact_snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["schema_version"] == FACT_SNAPSHOT_SCHEMA_VERSION
    fact_id = snapshot["skills"][0]["fact_id"]
    return {
        "schema_version": "resume_score.v1",
        "dimension_scores": [
            {
                "key": "skills",
                "raw_score": 40,
                "rationale": "Explicit Python and SQL facts are present.",
                "fact_ids": [fact_id],
                "uncertainties": [],
            },
            {
                "key": "experience",
                "raw_score": 50,
                "rationale": "Only the explicit experience fact was considered.",
                "fact_ids": [fact_id],
                "uncertainties": ["Dates are incomplete."],
            },
        ],
        "overall_summary": "Grounded test score.",
        "risk_flags": [],
        "needs_human_review": False,
    }


def test_score_template_score_run_and_manual_override(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text=(
            "Education \u6e05\u534e\u5927\u5b66 \u8ba1\u7b97\u673a \u5de5\u4f5c\u7ecf\u5386 "
            "Acme Python Engineer Skills Python SQL"
        ),
    )
    # The test helper's source text is replaced after upload, so use a direct
    # provider substitute rather than making a live model call.
    monkeypatch.setattr(
        "app.services.score_service.score_resume_fact_snapshot",
        _fake_score_provider,
    )

    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    assert template.json()["dimensions"][0]["max_raw_score"] == 80

    score = ai_client.post(
        f"/v1/resumes/{resume_id}/scores",
        json={"template_id": template_id},
    )
    assert score.status_code == 200, score.text
    payload = score.json()
    assert payload["fact_snapshot_id"]
    assert payload["ai_total_score"] == 50.0
    assert payload["total_score"] == 50.0
    assert payload["status"] == "succeeded"
    assert payload["model_name"] == "unit-test-model"
    assert payload["created_at"]
    assert payload["analysis"]["overall_summary"] == "Grounded test score."
    assert payload["dimension_scores"][0]["ai_raw_score"] == 40.0

    overridden = ai_client.post(
        f"/v1/resume-scores/{payload['score_id']}/dimensions/skills/override",
        json={"raw_score": 80, "reason": "Verified with portfolio evidence."},
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["ai_total_score"] == 50.0
    assert overridden.json()["total_score"] == 80.0
    assert overridden.json()["status"] == "overridden"
    assert overridden.json()["dimension_scores"][0]["manual_reason"] == (
        "Verified with portfolio evidence."
    )

    history = ai_client.get(f"/v1/resumes/{resume_id}/scores")
    assert history.status_code == 200, history.text
    assert [item["score_id"] for item in history.json()] == [payload["score_id"]]

    exceeds_max = ai_client.post(
        f"/v1/resume-scores/{payload['score_id']}/dimensions/skills/override",
        json={"raw_score": 81, "reason": "Too high."},
    )
    assert exceeds_max.status_code == 422
    assert exceeds_max.json()["detail"] == "score_override_exceeds_dimension_max"


def test_score_requires_server_side_model_key(client) -> None:
    template = client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    response = client.post(
        "/v1/resumes/not-a-real-resume/scores",
        json={"template_id": template.json()["template_id"]},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "deepseek_api_key_not_configured"
