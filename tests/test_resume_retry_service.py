"""One-click retry dispatch + endpoints for failed/abnormal resume library rows.

Covers the four dispatch branches (document reparse, AI extraction, summary,
scoring), the documented skip reasons, the single/batch retry endpoints, and
the five status-filter tabs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import (
    Resume,
    ResumeFactSnapshot,
    ResumeScoreBatch,
    ResumeScoreBatchItem,
    ResumeSummaryJob,
    ScoreTemplate,
)
from app.services import resume_retry_service
from app.services.ai_extraction_job_service import NON_RESUME_DOCUMENT_FLAG
from app.services.resume_retry_service import (
    ACTION_AI_EXTRACTION,
    ACTION_DOCUMENT_EXTRACTION,
    ACTION_SCORE,
    ACTION_SUMMARY,
    SKIP_ACTIVE_RESUME_IMMUTABLE,
    SKIP_JOB_ALREADY_RUNNING,
    SKIP_NO_FAILED_STEP,
    SKIP_NO_SCORE_TEMPLATE,
    SKIP_RESUME_NOT_SCOREABLE,
    SKIP_TEMPLATE_ARCHIVED,
    retry_resume_failed,
)
from app.tenant_scope import bypass_organization_scope
from test_filter_mvp_contract import _save_ready_resume
from test_score_service import _template_payload


def _save_ready(ai_client) -> tuple[str, str]:
    return _save_ready_resume(
        ai_client,
        source_text=(
            "教育经历 清华大学 计算机 本科。工作经历 "
            "Acme Python Engineer。技能 Python SQL"
        ),
    )


def _latest_summary_job(session, resume_id: str, facts_version: int):
    return session.scalar(
        select(ResumeSummaryJob).where(
            ResumeSummaryJob.resume_id == resume_id,
            ResumeSummaryJob.facts_version == facts_version,
        )
    )


def _current_snapshot(session, resume: Resume) -> ResumeFactSnapshot:
    snapshot = session.scalar(
        select(ResumeFactSnapshot).where(
            ResumeFactSnapshot.resume_id == resume.id,
            ResumeFactSnapshot.facts_version == resume.facts_version,
        )
    )
    assert snapshot is not None
    return snapshot


def _dispatch(ai_client, resume_id: str):
    database = ai_client.app.state.database
    settings = ai_client.app.state.settings
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            dispatch = retry_resume_failed(session, resume=resume, settings=settings)
        session.rollback()
        return dispatch


def _set_summary_failed(session, resume: Resume) -> None:
    job = _latest_summary_job(session, resume.id, resume.facts_version)
    assert job is not None, "facts save should have auto-queued a summary job"
    job.status = "failed"
    job.last_error = "model_timeout"
    job.completed_at = datetime.now(timezone.utc)


def _create_score_item(
    ai_client,
    resume: Resume,
    *,
    status: str = "failed",
    archived_template: bool = False,
) -> str:
    database = ai_client.app.state.database
    now = datetime.now(timezone.utc)
    template_payload = _template_payload()
    created = ai_client.post("/v1/score-templates", json=template_payload)
    assert created.status_code == 200, created.text
    template_id = created.json()["template_id"]
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            if archived_template:
                template = session.get(ScoreTemplate, template_id)
                assert template is not None
                template.is_archived = True
            batch = ResumeScoreBatch(
                organization_id=resume.organization_id,
                template_id=template_id,
                template_version=1,
                status="completed",
                requested_at=now,
            )
            session.add(batch)
            session.flush()
            snapshot = _current_snapshot(session, resume)
            session.add(
                ResumeScoreBatchItem(
                    organization_id=resume.organization_id,
                    batch_id=batch.id,
                    resume_id=resume.id,
                    fact_snapshot_id=snapshot.id,
                    facts_version=resume.facts_version,
                    status=status,
                    updated_at=now,
                    completed_at=now,
                    last_error="provider_timeout",
                )
            )
            session.commit()
    return template_id


# --- dispatcher unit tests -------------------------------------------------


def test_dispatch_document_extraction_failure(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    settings = ai_client.app.state.settings
    calls = []

    def fake_document_reextract(session, *, resume_id, settings):
        del session, settings
        calls.append(resume_id)

    monkeypatch.setattr(
        resume_retry_service,
        "request_resume_document_extraction",
        fake_document_reextract,
    )
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.extraction_status = "failed"
            resume.is_active = False
            ai_job = resume.ai_extraction_job
            assert ai_job is not None
            ai_job.status = "completed"
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == (ACTION_DOCUMENT_EXTRACTION,)
    assert dispatch.skip_reasons == ()
    assert calls == [resume_id]


def test_dispatch_ai_extraction_failure(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    settings = ai_client.app.state.settings
    calls = []

    def fake_ai_reextract(session, *, resume_id, settings):
        del session, settings
        calls.append(resume_id)

    monkeypatch.setattr(
        resume_retry_service,
        "request_resume_ai_extraction",
        fake_ai_reextract,
    )
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.extraction_status = "text_ready"
            resume.is_active = False
            ai_job = resume.ai_extraction_job
            assert ai_job is not None
            ai_job.status = "needs_attention"
            ai_job.last_error = "model_unavailable"
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == (ACTION_AI_EXTRACTION,)
    assert dispatch.skip_reasons == ()
    assert calls == [resume_id]


def test_dispatch_summary_failure(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    settings = ai_client.app.state.settings
    calls = []

    def fake_summary_requeue(session, *, resume, settings):
        del session, settings
        calls.append(resume.id)
        return None

    monkeypatch.setattr(
        resume_retry_service,
        "request_resume_summary_job",
        fake_summary_requeue,
    )
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            assert resume.is_active and resume.extraction_status == "ready"
            _set_summary_failed(session, resume)
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == (ACTION_SUMMARY,)
    assert dispatch.skip_reasons == (SKIP_NO_SCORE_TEMPLATE,)
    assert calls == [resume_id]


def test_dispatch_never_summarized_requeues_summary(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    calls = []

    def fake_summary_requeue(session, *, resume, settings):
        del session, settings
        calls.append(resume.id)
        return None

    monkeypatch.setattr(
        resume_retry_service,
        "request_resume_summary_job",
        fake_summary_requeue,
    )
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            for job in list(resume.summary_jobs):
                session.delete(job)
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == (ACTION_SUMMARY,)
    assert SKIP_NO_SCORE_TEMPLATE in dispatch.skip_reasons
    assert calls == [resume_id]


def test_dispatch_first_time_scores_with_configured_templates(
    ai_client,
    monkeypatch,
) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    settings = ai_client.app.state.settings
    template_id = "template-first-score"
    calls = []

    def fake_score_enqueue(session, *, template_id, settings, resume_id):
        del session, settings
        calls.append((template_id, resume_id))
        return None

    monkeypatch.setattr(
        resume_retry_service,
        "enqueue_resume_score_batch",
        fake_score_enqueue,
    )
    monkeypatch.setattr(
        resume_retry_service,
        "_auto_score_template_ids",
        lambda session: [template_id],
    )

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == (ACTION_SCORE,)
    assert dispatch.skip_reasons == ()
    assert calls == [(template_id, resume_id)]


def test_dispatch_first_time_score_not_triggered_for_inactive_resume(
    ai_client,
    monkeypatch,
) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.is_active = False
            session.commit()

    monkeypatch.setattr(
        resume_retry_service,
        "_auto_score_template_ids",
        lambda session: ["template-first-score"],
    )

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == ()


def test_dispatch_score_failure(ai_client, monkeypatch) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    settings = ai_client.app.state.settings
    template_id = None
    calls = []

    def fake_score_enqueue(session, *, template_id, settings, resume_id):
        del session, settings
        calls.append((template_id, resume_id))
        return None

    monkeypatch.setattr(
        resume_retry_service,
        "enqueue_resume_score_batch",
        fake_score_enqueue,
    )
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            template_id = _create_score_item(ai_client, resume)
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == (ACTION_SCORE,)
    assert dispatch.skip_reasons == ()
    assert calls == [(template_id, resume_id)]


def test_dispatch_skips_active_resume_for_document_reparse(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.extraction_status = "failed"
            resume.is_active = True
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == (SKIP_ACTIVE_RESUME_IMMUTABLE,)


def test_dispatch_skips_when_replacement_already_running(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.extraction_status = "failed"
            resume.is_active = False
            ai_job = resume.ai_extraction_job
            assert ai_job is not None
            ai_job.status = "running"
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == (SKIP_JOB_ALREADY_RUNNING,)


def test_dispatch_skips_archived_score_template(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            _create_score_item(ai_client, resume, archived_template=True)
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == (SKIP_TEMPLATE_ARCHIVED,)


def test_dispatch_skips_not_scoreable_resume(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            _create_score_item(ai_client, resume)
            resume.is_active = False
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == (SKIP_RESUME_NOT_SCOREABLE,)


def test_dispatch_reports_no_failed_step_for_healthy_resume(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    now = datetime.now(timezone.utc)
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            summary_job = _latest_summary_job(
                session, resume.id, resume.facts_version
            )
            assert summary_job is not None
            summary_job.status = "succeeded"
            summary_job.completed_at = now
            _create_score_item(ai_client, resume, status="succeeded")
            session.commit()

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == ()


def test_dispatch_never_scored_skips_without_configured_template(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)

    dispatch = _dispatch(ai_client, resume_id)
    assert dispatch.actions == ()
    assert dispatch.skip_reasons == (SKIP_NO_SCORE_TEMPLATE,)


# --- retry endpoints -------------------------------------------------------


def test_single_retry_requeues_failed_summary(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            _set_summary_failed(session, resume)
            session.commit()

    response = ai_client.post(f"/v1/resumes/{resume_id}/retry-failed")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["queued"] == [ACTION_SUMMARY]
    assert payload["skipped"] == [SKIP_NO_SCORE_TEMPLATE]

    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            job = _latest_summary_job(session, resume.id, resume.facts_version)
            assert job is not None
            assert job.status in {"queued", "unavailable"}
            assert job.completed_at is None
            assert job.last_error in {None, "deepseek_api_key_not_configured"}


def test_batch_retry_collects_queued_and_skipped(ai_client) -> None:
    first_candidate, first_resume_id = _save_ready(ai_client)
    second_candidate, second_resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, first_resume_id)
            assert resume is not None
            _set_summary_failed(session, resume)
            session.commit()

    response = ai_client.post(
        "/v1/resumes/retry-failed",
        json={"resume_ids": [first_resume_id, second_resume_id]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["queued"] == [
        {"resume_id": first_resume_id, "actions": [ACTION_SUMMARY]}
    ]
    assert payload["skipped"] == [
        {"resume_id": second_resume_id, "reason": SKIP_NO_SCORE_TEMPLATE}
    ]
    assert payload["queued_count"] == 1
    assert payload["skipped_count"] == 1
    assert first_candidate and second_candidate


def test_batch_retry_rejects_unknown_resume(ai_client) -> None:
    response = ai_client.post(
        "/v1/resumes/retry-failed",
        json={"resume_ids": ["missing-resume-id"]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "resume_not_found"


def test_batch_retry_all_scores_whole_library(ai_client) -> None:
    _, first_resume_id = _save_ready(ai_client)
    _, second_resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, first_resume_id)
            assert resume is not None
            _set_summary_failed(session, resume)
            session.commit()

    response = ai_client.post("/v1/resumes/retry-failed", json={"all": True})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["queued_count"] == 1
    assert payload["skipped_count"] == 1
    assert {item["resume_id"] for item in payload["queued"]} == {first_resume_id}
    assert {item["resume_id"] for item in payload["skipped"]} == {second_resume_id}
    assert payload["skipped"][0]["reason"] == SKIP_NO_SCORE_TEMPLATE
    assert {first_resume_id, second_resume_id} == {
        item["resume_id"] for item in payload["queued"] + payload["skipped"]
    }


def test_batch_retry_rejects_missing_or_ambiguous_target(ai_client) -> None:
    empty_response = ai_client.post("/v1/resumes/retry-failed", json={})
    assert empty_response.status_code == 422

    ambiguous_response = ai_client.post(
        "/v1/resumes/retry-failed",
        json={"resume_ids": ["some-id"], "all": True},
    )
    assert ambiguous_response.status_code == 422


def test_single_retry_returns_404_for_missing_resume(ai_client) -> None:
    response = ai_client.post("/v1/resumes/missing-resume-id/retry-failed")
    assert response.status_code == 404
    assert response.json()["detail"] == "resume_not_found"


def test_single_retry_reports_skip_for_immutable_resume(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.extraction_status = "failed"
            resume.is_active = True
            session.commit()

    response = ai_client.post(f"/v1/resumes/{resume_id}/retry-failed")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "queued": [],
        "skipped": [SKIP_ACTIVE_RESUME_IMMUTABLE],
    }


# --- status filter + retryable fields ---------------------------------------


def _library_items(ai_client) -> list[dict[str, object]]:
    response = ai_client.get("/v1/resume-library")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _item_by_resume(items, resume_id: str) -> dict[str, object]:
    return next(item for item in items if item["resume_id"] == resume_id)


def test_status_filter_returns_only_matching_tab(ai_client) -> None:
    # summary_pending: active+ready with a failed summary job.
    _, summary_resume_id = _save_ready(ai_client)
    # attention: document parsing failed.
    _, attention_resume_id = _save_ready(ai_client)
    # unscored: active+ready with a completed summary but no score yet.
    _, unscored_resume_id = _save_ready(ai_client)
    # processing: active+ready with the summary still queued.
    _, processing_resume_id = _save_ready(ai_client)
    # non_resume: a completed AI job whose source was classified as non-resume.
    _, non_resume_resume_id = _save_ready(ai_client)

    database = ai_client.app.state.database
    now = datetime.now(timezone.utc)
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            summary_resume = session.get(Resume, summary_resume_id)
            assert summary_resume is not None
            _set_summary_failed(session, summary_resume)

            attention_resume = session.get(Resume, attention_resume_id)
            assert attention_resume is not None
            attention_resume.extraction_status = "failed"
            attention_resume.is_active = False

            unscored_resume = session.get(Resume, unscored_resume_id)
            assert unscored_resume is not None
            unscored_job = _latest_summary_job(
                session,
                unscored_resume.id,
                unscored_resume.facts_version,
            )
            assert unscored_job is not None
            unscored_job.status = "succeeded"
            unscored_job.completed_at = now

            processing_resume = session.get(Resume, processing_resume_id)
            assert processing_resume is not None
            non_resume_resume = session.get(Resume, non_resume_resume_id)
            assert non_resume_resume is not None
            non_resume_resume.quality_flags = [NON_RESUME_DOCUMENT_FLAG]
            session.commit()

    expected = {
        "summary_pending": summary_resume_id,
        "attention": attention_resume_id,
        "unscored": unscored_resume_id,
        "processing": processing_resume_id,
        "non_resume": non_resume_resume_id,
    }
    for tab, expected_resume_id in expected.items():
        response = ai_client.get(f"/v1/resume-library?status_filter={tab}")
        assert response.status_code == 200, response.text
        payload = response.json()
        resume_ids = {item["resume_id"] for item in payload["items"]}
        assert resume_ids == {expected_resume_id}, (
            f"{tab} matched {resume_ids}, expected only {expected_resume_id}"
        )


def test_status_filter_mutually_exclusive_and_combines_with_mailbox(
    ai_client,
) -> None:
    # A failed-parsing resume is attention, never processing or unscored.
    _, attention_resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, attention_resume_id)
            assert resume is not None
            resume.extraction_status = "failed"
            resume.is_active = False
            session.commit()

    for tab in ("processing", "unscored", "summary_pending"):
        response = ai_client.get(f"/v1/resume-library?status_filter={tab}")
        assert response.status_code == 200, response.text
        assert all(
            item["resume_id"] != attention_resume_id
            for item in response.json()["items"]
        ), f"{tab} must not contain a failed-parsing resume"


def test_resume_library_exposes_score_retryable_state(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            _create_score_item(ai_client, resume)
            session.commit()

    items = _library_items(ai_client)
    item = _item_by_resume(items, resume_id)
    assert item["latest_score_status"] == "failed"
    assert item["score_retryable"] is True


def test_resume_library_never_scored_is_not_retryable(ai_client) -> None:
    _, resume_id = _save_ready(ai_client)

    items = _library_items(ai_client)
    item = _item_by_resume(items, resume_id)
    assert item["latest_score_status"] is None
    assert item["score_retryable"] is False
