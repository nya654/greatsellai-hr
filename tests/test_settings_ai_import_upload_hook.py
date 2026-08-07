from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import ResumeAiExtractionJob
from app.services import document_extraction_job_service
from app.tenant_scope import bypass_organization_scope
from test_candidate_data_lifecycle import _register_and_login
from test_resume_flow import make_pdf_with_text


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """An admin-only upload-hook client with real per-workspace auth.

    The AI-import settings gate resolves the workspace from the worker's org
    context, so these tests need genuine membership-bound sessions rather than
    the shared ``allow_unauthenticated`` client.
    """

    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="settings-ai-import-upload-hook-test-session-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        min_text_chars_per_page=20,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _admin_client(client: TestClient) -> TestClient:
    # register + login a workspace admin, set client.auth cookies, return client
    _register_and_login(
        client,
        organization_name="Settings Ai Import Upload Hook Org",
        email="settings-ai-upload-hook@example.test",
    )
    return client


def _create_score_template(client: TestClient) -> str:
    response = client.post(
        "/v1/score-templates",
        json={
            "name": "Backend Engineer",
            "description": "Upload-hook settings test template",
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


def _upload_and_run_document_worker(
    client: TestClient,
    *,
    filename: str = "resume.pdf",
) -> dict[str, object]:
    response = client.post(
        "/v1/resumes/upload",
        files={
            "file": (
                filename,
                make_pdf_with_text("Education Skills Python " * 20),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert document_extraction_job_service.run_document_extraction_worker_once(
        client.app.state.database,
        settings=client.app.state.settings,
        worker_id="settings-upload-hook-document-worker",
    )
    return response.json()


def _ai_job_count_for_resume(client: TestClient, resume_id: str) -> int:
    with client.app.state.database.session_factory() as session:
        with bypass_organization_scope(session):
            return len(
                session.scalars(
                    select(ResumeAiExtractionJob).where(
                        ResumeAiExtractionJob.resume_id == resume_id
                    )
                ).all()
            )


def test_manual_upload_auto_enqueues_ai_extraction(client) -> None:
    # Defaults are all-on, so the worker's auto-enqueue must run exactly as it
    # did before the settings gate existed.
    c = _admin_client(client)
    uploaded = _upload_and_run_document_worker(c)
    assert _ai_job_count_for_resume(c, str(uploaded["resume_id"])) == 1


def test_manual_upload_respects_trigger_off(client) -> None:
    c = _admin_client(client)
    template_id = _create_score_template(c)
    response = c.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "score_template_ids": [template_id],
            "trigger_manual_upload": False,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 200, response.text
    uploaded = _upload_and_run_document_worker(c)
    assert _ai_job_count_for_resume(c, str(uploaded["resume_id"])) == 0


def test_manual_upload_respects_automation_off(client) -> None:
    c = _admin_client(client)
    response = c.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": False,
            "auto_score_enabled": False,
            "score_template_ids": [],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 200, response.text
    uploaded = _upload_and_run_document_worker(c)
    assert _ai_job_count_for_resume(c, str(uploaded["resume_id"])) == 0
