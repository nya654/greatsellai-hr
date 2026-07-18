from __future__ import annotations

from sqlalchemy import select

from app.models import JobMatchBatchItem
from app.schemas import JobCreate, JobRequirements
from app.services import job_match_batch_service, job_service
from test_filter_mvp_contract import _save_ready_resume


def _batch_match_output(**kwargs: object) -> dict[str, object]:
    requirements = kwargs["confirmed_requirements"]
    assert isinstance(requirements, list)
    return {
        "schema_version": "jd_match.v1",
        "requirement_matches": [
            {
                "requirement_id": requirement["requirement_id"],
                "status": "met",
                "rationale": "Python is explicitly present in the structured resume facts.",
                "fact_ids": ["skill-001"],
                "uncertainties": [],
            }
            for requirement in requirements
        ],
        "needs_human_review": False,
    }


def test_confirmed_jd_can_queue_and_cache_all_ready_resume_matches(
    ai_client,
    monkeypatch,
) -> None:
    source_text = "\u6559\u80b2\u7ecf\u5386 \u6e05\u534e\u5927\u5b66 \u8ba1\u7b97\u673a \u5de5\u4f5c\u7ecf\u5386 Acme Python Engineer \u6280\u80fd Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    _save_ready_resume(ai_client, source_text=source_text)
    created = ai_client.post(
        "/v1/jobs",
        json=JobCreate(
            title="Backend Engineer",
            jd_text="Python experience is required.",
            requirements=JobRequirements(must_have=["Python experience"]),
        ).model_dump(),
    )
    assert created.status_code == 200, created.text
    job_version_id = created.json()["job_version_id"]
    assert created.json()["status"] == "confirmed"

    monkeypatch.setattr(
        job_service,
        "match_resume_fact_snapshot_against_requirements",
        _batch_match_output,
    )
    queued = ai_client.post(f"/v1/job-versions/{job_version_id}/match-all")
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "queued"
    assert queued.json()["total_count"] == 2
    batch_id = queued.json()["batch_id"]

    database = ai_client.app.state.database
    assert job_match_batch_service.run_job_match_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="test-worker",
    )
    assert job_match_batch_service.run_job_match_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="test-worker",
    )
    assert not job_match_batch_service.run_job_match_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="test-worker",
    )

    completed = ai_client.get(f"/v1/job-match-batches/{batch_id}")
    assert completed.status_code == 200, completed.text
    with database.session_factory() as session:
        item_states = session.execute(
            select(JobMatchBatchItem.status, JobMatchBatchItem.last_error)
            .where(JobMatchBatchItem.batch_id == batch_id)
        ).all()
    assert completed.json()["status"] == "completed", (completed.json(), item_states)
    assert completed.json()["completed_count"] == 2
    assert completed.json()["failed_count"] == 0

    batch_items = ai_client.get(f"/v1/job-match-batches/{batch_id}/items")
    assert batch_items.status_code == 200, batch_items.text
    assert len(batch_items.json()) == 2
    assert {item["status"] for item in batch_items.json()} == {"completed"}
    assert {item["candidate_display_name"] for item in batch_items.json()} == {"测试候选人"}

    matches = ai_client.get(f"/v1/job-versions/{job_version_id}/matches")
    assert matches.status_code == 200, matches.text
    assert len(matches.json()) == 2
    assert {item["total_score"] for item in matches.json()} == {100.0}

    # A second request makes a new historical batch but reuses the immutable
    # JD-version + fact-snapshot matches instead of spending two model calls.
    cached = ai_client.post(f"/v1/job-versions/{job_version_id}/match-all")
    assert cached.status_code == 200, cached.text
    assert cached.json()["status"] == "completed"
    assert cached.json()["completed_count"] == 2
