from __future__ import annotations

from test_fact_snapshots import _create_resume, _facts


def test_review_endpoint_returns_evidence_facts_and_audit_history(client) -> None:
    resume_id = _create_resume(client)
    saved = client.put(f"/v1/resumes/{resume_id}/facts", json=_facts(skills=["Python"]))
    assert saved.status_code == 200, saved.text

    response = client.get(f"/v1/resumes/{resume_id}/review")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["resume_id"] == resume_id
    assert payload["facts_version"] == 1
    assert payload["source_blocks"][0]["block_id"] == "page-001"
    assert payload["education"][0]["school_name_raw"] == "Test University"
    assert payload["experiences"] == [
        {
            "classification_evidence_block_ids": [],
            "detail_items": [
                {
                    "detail_raw": "Designed ingestion pipeline",
                    "evidence_block_ids": ["page-001"],
                },
                {
                    "detail_raw": "Reduced report latency",
                    "evidence_block_ids": ["page-001"],
                },
            ],
            "end_month": "2024-06",
            "evidence_block_ids": ["page-001"],
            "experience_name_raw": "Data Platform Project",
            "experience_type": "project",
            "is_current": False,
            "organization_name_raw": "Example Company",
            "start_month": "2022-07",
            "title_raw": "Python Engineer",
        }
    ]
    assert payload["skills"] == [
        {"skill_display": "Python", "evidence_block_ids": ["page-001"]}
    ]
    assert payload["review_actions"][0]["action"] == "facts_saved_pending_school_review"


def test_combined_upload_creates_candidate_and_resume(client) -> None:
    from test_fact_snapshots import _make_pdf_with_text

    response = client.post(
        "/v1/resumes/upload",
        # The public upload route deliberately ignores legacy/manual name
        # input; a candidate is named only after source-grounded AI extraction.
        data={"display_name": "Must not be used before extraction"},
        files={
            "file": (
                "resume.pdf",
                _make_pdf_with_text("Python SQL " * 30),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["candidate_id"]
    assert response.json()["resume_id"]
    assert response.json()["candidate_display_name"] is None
