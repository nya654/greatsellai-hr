from __future__ import annotations

from test_fact_snapshots import _create_resume, _facts


def test_unmatched_school_stays_unknown_until_manual_review(client) -> None:
    resume_id = _create_resume(client)

    pending = client.put(
        f"/v1/resumes/{resume_id}/facts",
        json=_facts(skills=["Python"]),
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["extraction_status"] == "needs_review"
    assert pending.json()["is_active"] is False
    assert pending.json()["is_985_211"] is None
    assert "school_unresolved" in pending.json()["quality_flags"]

    assert client.post("/v1/candidates/search", json={"limit": 10}).json()["items"] == []

    incomplete_review = client.put(
        f"/v1/resumes/{resume_id}/facts",
        json={
            **_facts(skills=["Python"]),
            "complete_review": True,
            "review_note": "Checked the school name against the source.",
        },
    )
    assert incomplete_review.status_code == 422
    assert incomplete_review.json()["detail"] == "school_review_requires_985_211_override"

    completed = client.put(
        f"/v1/resumes/{resume_id}/facts",
        json={
            **_facts(skills=["Python"]),
            "complete_review": True,
            "review_note": "Checked the school name against the source.",
            "is_985_211_override": False,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["extraction_status"] == "ready"
    assert completed.json()["is_985_211"] is False

    results = client.post(
        "/v1/candidates/search",
        json={"is_985_211": False},
    )
    assert len(results.json()["items"]) == 1
