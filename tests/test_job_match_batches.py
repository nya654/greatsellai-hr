from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import (
    JobMatch,
    JobMatchBatch,
    JobMatchBatchItem,
    JobVersion,
    ResumeFactSnapshot,
)
from app.schemas import JobCreate, JobRequirements
from app.services import job_match_batch_service, job_service
from test_filter_mvp_contract import _save_ready_resume
from test_job_service import _create_job


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


def test_job_match_claim_uses_postgresql_skip_locked() -> None:
    """Two workers must not both lease one queued resume for an LLM call."""

    statement = job_match_batch_service._claimable_job_match_item_statement(
        now=datetime.now(timezone.utc),
    )
    compiled = str(statement.compile(dialect=postgresql.dialect())).upper()

    assert "FOR UPDATE OF JOB_MATCH_BATCH_ITEMS SKIP LOCKED" in compiled


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


def test_active_job_match_batch_augments_only_the_later_server_scope(
    ai_client,
) -> None:
    """A coalesced active batch must grow by the later private scope only.

    Talent-search and recruiting-agent results are server-derived subsets.  If
    one subset starts a JD batch while another is still active, both subsets
    need progress in the same batch, but unrelated workspace resumes must not
    be silently added.
    """

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, first_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    _, second_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    _, unrelated_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    database = ai_client.app.state.database

    with database.session_factory() as session:
        first_batch = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
            resume_ids=[first_resume_id],
        )
        assert first_batch.status == "queued"
        assert first_batch.total_count == 1
        assert first_batch.completed_count == 0

        # A cached result in the later scope should be reused and reflected in
        # the coalesced batch's count, without completing the still-queued
        # first-scope item.
        job_version = session.get(JobVersion, job_version_id)
        assert job_version is not None
        second_snapshot = session.scalar(
            select(ResumeFactSnapshot).where(
                ResumeFactSnapshot.resume_id == second_resume_id,
            ).order_by(ResumeFactSnapshot.facts_version.desc())
        )
        assert second_snapshot is not None
        session.add(
            JobMatch(
                job_id=job_version.job_id,
                job_version_id=job_version.id,
                resume_id=second_resume_id,
                fact_snapshot_id=second_snapshot.id,
                facts_version=second_snapshot.facts_version,
                job_version=job_version.version,
                total_score=1.0,
                must_have_passed=True,
                evidence_coverage=1.0,
                hard_requirement_status="pass",
                analysis={"summary": "cached test result"},
                status="succeeded",
                model_name="test-model",
            )
        )
        session.flush()

        second_batch = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
            resume_ids=[second_resume_id],
        )
        repeated_scope = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
            resume_ids=[second_resume_id],
        )

        assert second_batch.batch_id == first_batch.batch_id
        assert repeated_scope.batch_id == first_batch.batch_id
        assert second_batch.status == "queued"
        assert second_batch.total_count == 2
        assert second_batch.completed_count == 1
        assert second_batch.failed_count == 0
        assert repeated_scope.total_count == 2
        assert repeated_scope.completed_count == 1

        batch = session.get(JobMatchBatch, first_batch.batch_id)
        assert batch is not None
        items = session.scalars(
            select(JobMatchBatchItem).where(JobMatchBatchItem.batch_id == batch.id)
        ).all()
        assert {item.resume_id for item in items} == {first_resume_id, second_resume_id}
        assert unrelated_resume_id not in {item.resume_id for item in items}
        assert len(items) == 2
        assert {item.resume_id: item.status for item in items} == {
            first_resume_id: "queued",
            second_resume_id: "completed",
        }
        assert batch.total_count == 2
        assert batch.completed_count == 1
        assert batch.failed_count == 0


def test_refresh_never_marks_a_batch_completed_while_an_appended_item_is_queued(
    ai_client,
) -> None:
    """Worker progress must preserve a later scoped append as claimable work."""

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, first_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    _, second_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    database = ai_client.app.state.database

    with database.session_factory() as session:
        first = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
            resume_ids=[first_resume_id],
        )
        second = job_match_batch_service.enqueue_job_version_match_batch(
            session,
            job_version_id=job_version_id,
            settings=ai_client.app.state.settings,
            resume_ids=[second_resume_id],
        )
        assert second.batch_id == first.batch_id

        batch = session.get(JobMatchBatch, first.batch_id)
        assert batch is not None
        first_item = session.scalar(
            select(JobMatchBatchItem).where(
                JobMatchBatchItem.batch_id == batch.id,
                JobMatchBatchItem.resume_id == first_resume_id,
            )
        )
        second_item = session.scalar(
            select(JobMatchBatchItem).where(
                JobMatchBatchItem.batch_id == batch.id,
                JobMatchBatchItem.resume_id == second_resume_id,
            )
        )
        assert first_item is not None
        assert second_item is not None
        assert second_item.status == job_match_batch_service.ITEM_QUEUED

        # Simulate a worker completing the original scope while a later
        # server-derived scope is already appended but has not been claimed.
        first_item.status = job_match_batch_service.ITEM_COMPLETED
        first_item.completed_at = job_match_batch_service._utcnow()
        first_item.next_attempt_at = None
        job_match_batch_service._refresh_batch_progress(
            session,
            batch=batch,
            now=job_match_batch_service._utcnow(),
        )

        assert batch.status == job_match_batch_service.BATCH_RUNNING
        assert batch.total_count == 2
        assert batch.completed_count == 1
        assert batch.completed_at is None
