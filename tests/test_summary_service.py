from __future__ import annotations

from test_filter_mvp_contract import _save_ready_resume


def _fake_summary_provider(**kwargs: object) -> dict[str, object]:
    snapshot = kwargs["fact_snapshot"]
    assert isinstance(snapshot, dict)
    fact_id = snapshot["skills"][0]["fact_id"]
    return {
        "schema_version": "resume_summary.v1",
        "sections": {
            "candidate_positioning": {
                "content": "Backend-oriented candidate.",
                "fact_ids": [fact_id],
            },
            "education_background": {
                "content": "Education is present in the verified facts.",
                "fact_ids": [fact_id],
            },
            "work_and_internship": {
                "content": "Only explicit experience facts were used.",
                "fact_ids": [fact_id],
            },
            "core_skills": {
                "content": "Python and SQL are explicitly listed.",
                "fact_ids": [fact_id],
            },
            "representative_projects": {
                "content": "No project summary was inferred.",
                "fact_ids": [],
            },
            "strengths": {
                "content": "Structured facts support technical screening.",
                "fact_ids": [fact_id],
            },
            "verification_items": {
                "content": "Verify incomplete dates during interview.",
                "fact_ids": [fact_id],
            },
        },
    }


def _resave_current_facts(ai_client, resume_id: str) -> dict[str, object]:
    """Round-trip reviewed facts so the resume receives a new immutable snapshot."""

    review = ai_client.get(f"/v1/resumes/{resume_id}/review")
    assert review.status_code == 200, review.text
    current = review.json()
    payload = {
        "facts": {
            "schema_version": "resume_facts.v1",
            "education": [
                {
                    "school_name_raw": item["school_name_raw"],
                    "degree": item["degree"],
                    "major_raw": item["major_raw"],
                    "start_month": item["start_month"],
                    "end_month": item["end_month"],
                    "evidence_block_ids": item["evidence_block_ids"],
                }
                for item in current["education"]
            ],
            "experiences": [
                {
                    "experience_type": item["experience_type"],
                    "experience_name_raw": item["experience_name_raw"],
                    "organization_name_raw": item["organization_name_raw"],
                    "title_raw": item["title_raw"],
                    "start_month": item["start_month"],
                    "end_month": item["end_month"],
                    "is_current": item["is_current"],
                    "evidence_block_ids": item["evidence_block_ids"],
                    "classification_evidence_block_ids": item[
                        "classification_evidence_block_ids"
                    ],
                    "detail_items": item["detail_items"],
                }
                for item in current["experiences"]
            ],
            "skills": [
                {
                    "skill_display": item["skill_display"],
                    "evidence_block_ids": item["evidence_block_ids"],
                }
                for item in current["skills"]
            ],
        }
    }
    saved = ai_client.put(f"/v1/resumes/{resume_id}/facts", json=payload)
    assert saved.status_code == 200, saved.text
    review_after_save = ai_client.get(f"/v1/resumes/{resume_id}/review")
    assert review_after_save.status_code == 200, review_after_save.text
    return review_after_save.json()


def test_ai_summary_and_manual_version_keep_history(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text=(
            "Education \u6e05\u534e\u5927\u5b66 \u8ba1\u7b97\u673a \u5de5\u4f5c\u7ecf\u5386 "
            "Acme Python Engineer Skills Python SQL"
        ),
    )
    monkeypatch.setattr(
        "app.services.summary_service.summarize_resume_fact_snapshot",
        _fake_summary_provider,
    )

    generated = ai_client.post(f"/v1/resumes/{resume_id}/summaries")
    assert generated.status_code == 200, generated.text
    generated_payload = generated.json()
    assert generated_payload["source"] == "ai"
    assert generated_payload["is_current"] is True
    assert generated_payload["fact_snapshot_id"]
    assert generated_payload["content"]["sections"]["core_skills"]["fact_ids"] == [
        "skill-001"
    ]

    manual = ai_client.post(
        f"/v1/resume-summaries/{generated_payload['summary_id']}/manual-versions",
        json={"content": {"candidate_positioning": "Manual recruiter note."}},
    )
    assert manual.status_code == 200, manual.text
    manual_payload = manual.json()
    assert manual_payload["source"] == "manual"
    assert manual_payload["is_current"] is True
    assert manual_payload["fact_snapshot_id"] == generated_payload["fact_snapshot_id"]

    versions = ai_client.get(f"/v1/resumes/{resume_id}/summaries")
    assert versions.status_code == 200, versions.text
    assert len(versions.json()) == 2
    assert versions.json()[0]["summary_id"] == manual_payload["summary_id"]
    assert versions.json()[1]["summary_id"] == generated_payload["summary_id"]
    assert versions.json()[1]["is_current"] is False


def test_summary_cannot_stay_current_or_be_manually_versioned_after_facts_resave(
    ai_client,
    monkeypatch,
) -> None:
    _, resume_id = _save_ready_resume(
        ai_client,
        source_text=(
            "Education \u6e05\u534e\u5927\u5b66 \u8ba1\u7b97\u673a \u5de5\u4f5c\u7ecf\u5386 "
            "Acme Python Engineer Skills Python SQL"
        ),
    )
    monkeypatch.setattr(
        "app.services.summary_service.summarize_resume_fact_snapshot",
        _fake_summary_provider,
    )

    first_summary = ai_client.post(f"/v1/resumes/{resume_id}/summaries")
    assert first_summary.status_code == 200, first_summary.text
    first_payload = first_summary.json()

    resaved_resume = _resave_current_facts(ai_client, resume_id)
    assert resaved_resume["extraction_status"] == "ready"

    versions_after_resave = ai_client.get(f"/v1/resumes/{resume_id}/summaries")
    assert versions_after_resave.status_code == 200, versions_after_resave.text
    assert len(versions_after_resave.json()) == 1
    old_summary = versions_after_resave.json()[0]
    assert old_summary["summary_id"] == first_payload["summary_id"]
    assert old_summary["fact_snapshot_id"] == first_payload["fact_snapshot_id"]
    assert old_summary["is_current"] is False

    stale_manual = ai_client.post(
        f"/v1/resume-summaries/{first_payload['summary_id']}/manual-versions",
        json={"content": {"candidate_positioning": "This must not revive old facts."}},
    )
    assert stale_manual.status_code == 409, stale_manual.text

    # A fresh AI summary is bound to the new snapshot, and a manual version of
    # that current summary remains a valid recruiter workflow.
    refreshed_summary = ai_client.post(f"/v1/resumes/{resume_id}/summaries")
    assert refreshed_summary.status_code == 200, refreshed_summary.text
    refreshed_payload = refreshed_summary.json()
    assert refreshed_payload["fact_snapshot_id"] != first_payload["fact_snapshot_id"]
    assert refreshed_payload["facts_version"] == resaved_resume["facts_version"]

    current_manual = ai_client.post(
        f"/v1/resume-summaries/{refreshed_payload['summary_id']}/manual-versions",
        json={"content": {"candidate_positioning": "Manual note for current facts."}},
    )
    assert current_manual.status_code == 200, current_manual.text
    assert current_manual.json()["is_current"] is True
    assert current_manual.json()["fact_snapshot_id"] == refreshed_payload["fact_snapshot_id"]


def test_summary_requires_server_side_model_key(client) -> None:
    response = client.post("/v1/resumes/not-a-real-resume/summaries")
    assert response.status_code == 503
    assert response.json()["detail"] == "deepseek_api_key_not_configured"
