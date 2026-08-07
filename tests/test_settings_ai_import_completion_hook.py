from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import (
    ResumeAiExtractionJob,
    ResumeScoreBatchItem,
    ResumeSummaryJob,
)
from app.schemas import ResumeFactsSubmission
from app.services import ai_extraction_job_service as job_service
from app.services import document_extraction_job_service
from app.services.resume_score_batch_service import ScoreServiceError
from app.tenant_scope import bypass_organization_scope
from test_candidate_data_lifecycle import _register_and_login
from test_resume_flow import make_pdf_with_text


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """An admin-only completion-hook client with real per-workspace auth.

    The AI-extraction completion gate resolves the workspace from the worker's
    org context and the score enqueue resolves a route pin, so this client needs
    genuine membership-bound sessions plus a configured AI credential.
    """

    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="settings-ai-import-completion-hook-test-session-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        deepseek_api_key="settings-completion-hook-test-key",
        deepseek_model="unit-test-model",
        min_text_chars_per_page=20,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _admin_client(client: TestClient) -> TestClient:
    _register_and_login(
        client,
        organization_name="Settings Ai Import Completion Hook Org",
        email="settings-ai-completion-hook@example.test",
    )
    return client


def _create_score_template(client: TestClient) -> str:
    response = client.post(
        "/v1/score-templates",
        json={
            "name": "Backend Engineer",
            "description": "Completion-hook settings test template",
            "dimensions": [
                {
                    "label": "Skills",
                    "weight": 60,
                    "guidance": "Assess explicit relevant skills only.",
                },
                {
                    "label": "Experience",
                    "weight": 40,
                    "guidance": "Assess explicit work evidence only.",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["template_id"]


def _put_ai_import_settings(
    client: TestClient,
    *,
    auto_summary_enabled: bool,
    auto_score_enabled: bool,
    score_template_ids: list[str],
) -> None:
    response = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": auto_summary_enabled,
            "auto_score_enabled": auto_score_enabled,
            "score_template_ids": score_template_ids,
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 200, response.text


def _upload_run_document_then_ai_worker(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Upload a resume, run both workers, and return the resume_id.

    ``extract_resume_facts`` is monkeypatched with a valid grounded facts
    submission so the AI worker completes the extraction without a model call.
    """
    response = client.post(
        "/v1/resumes/upload",
        files={
            "file": (
                "resume.pdf",
                make_pdf_with_text("Education Skills Python " * 20),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert document_extraction_job_service.run_document_extraction_worker_once(
        client.app.state.database,
        settings=client.app.state.settings,
        worker_id="settings-completion-hook-document-worker",
    )

    def fake_extract(**kwargs: object) -> ResumeFactsSubmission:
        return ResumeFactsSubmission.model_validate(
            {
                "candidate_name_raw": "Completion Hook Candidate",
                "candidate_name_evidence_block_ids": ["page-001"],
                "skills": [
                    {"skill_display": "Python", "evidence_block_ids": ["page-001"]}
                ],
            }
        )

    monkeypatch.setattr(job_service, "extract_resume_facts", fake_extract)
    assert job_service.run_ai_extraction_worker_once(
        client.app.state.database,
        settings=client.app.state.settings,
        worker_id="settings-completion-hook-ai-worker",
    )
    return str(response.json()["resume_id"])


def _summary_jobs_for_resume(client: TestClient, resume_id: str) -> list[ResumeSummaryJob]:
    with client.app.state.database.session_factory() as session:
        with bypass_organization_scope(session):
            return list(
                session.scalars(
                    select(ResumeSummaryJob).where(
                        ResumeSummaryJob.resume_id == resume_id
                    )
                ).all()
            )


def _score_items_for_resume(
    client: TestClient, resume_id: str
) -> list[ResumeScoreBatchItem]:
    with client.app.state.database.session_factory() as session:
        with bypass_organization_scope(session):
            return list(
                session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.resume_id == resume_id
                    )
                ).all()
            )


def _extraction_job_for_resume(
    client: TestClient, resume_id: str
) -> ResumeAiExtractionJob | None:
    with client.app.state.database.session_factory() as session:
        with bypass_organization_scope(session):
            return session.scalar(
                select(ResumeAiExtractionJob).where(
                    ResumeAiExtractionJob.resume_id == resume_id
                )
            )


def test_extraction_completion_auto_enqueues_summary_and_score(
    client,
    monkeypatch,
) -> None:
    # Defaults are all-on; a default score template makes auto-score enqueueable.
    c = _admin_client(client)
    template_id = _create_score_template(c)
    _put_ai_import_settings(
        c,
        auto_summary_enabled=True,
        auto_score_enabled=True,
        score_template_ids=[template_id],
    )
    resume_id = _upload_run_document_then_ai_worker(c, monkeypatch)

    summaries = _summary_jobs_for_resume(client, resume_id)
    assert len(summaries) == 1
    assert summaries[0].status == "queued"

    score_items = _score_items_for_resume(client, resume_id)
    assert len(score_items) == 1
    assert score_items[0].resume_id == resume_id


def test_extraction_completion_respects_auto_summary_off(client, monkeypatch) -> None:
    # Auto-score stays on with a template; only the summary is suppressed.
    c = _admin_client(client)
    template_id = _create_score_template(c)
    _put_ai_import_settings(
        c,
        auto_summary_enabled=False,
        auto_score_enabled=True,
        score_template_ids=[template_id],
    )
    resume_id = _upload_run_document_then_ai_worker(c, monkeypatch)

    assert _summary_jobs_for_resume(client, resume_id) == []

    score_items = _score_items_for_resume(client, resume_id)
    assert len(score_items) == 1
    assert score_items[0].resume_id == resume_id


def test_extraction_completion_score_failure_does_not_rollback(
    client,
    monkeypatch,
) -> None:
    # A missing/invalid scoring route must not roll back the completed facts.
    c = _admin_client(client)
    template_id = _create_score_template(c)
    _put_ai_import_settings(
        c,
        auto_summary_enabled=True,
        auto_score_enabled=True,
        score_template_ids=[template_id],
    )

    def raise_score_error(*args: object, **kwargs: object) -> None:
        raise ScoreServiceError("no_score_route")

    monkeypatch.setattr(
        job_service, "enqueue_resume_score_batch", raise_score_error
    )
    resume_id = _upload_run_document_then_ai_worker(c, monkeypatch)

    extraction_job = _extraction_job_for_resume(client, resume_id)
    assert extraction_job is not None
    assert extraction_job.status == "completed"

    assert len(_summary_jobs_for_resume(client, resume_id)) == 1
    assert _score_items_for_resume(client, resume_id) == []
