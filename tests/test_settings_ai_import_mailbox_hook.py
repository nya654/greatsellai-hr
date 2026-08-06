from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import EmailAttachmentImport, Resume, ResumeAiExtractionJob
from app.services import document_extraction_job_service
from app.services import mailbox_import_service
from app.tenant_scope import bypass_organization_scope, set_organization_context
from test_candidate_data_lifecycle import _register_and_login
from test_resume_flow import make_pdf_with_text


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """An admin-only mailbox-hook client with real per-workspace auth.

    The mailbox-import gate must read the same org-scoped AI-import settings
    that the admin PUT via the HTTP endpoint, so these tests need genuine
    membership-bound sessions rather than the shared ``allow_unauthenticated``
    client.  The generic-IMAP host used by the protocol double is pinned to the
    deployment-owned test allowlist, matching the conftest client.
    """

    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="settings-ai-import-mailbox-hook-test-session-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        min_text_chars_per_page=20,
        mailbox_imap_allowed_hosts=("imap.example.test",),
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _admin_org(client: TestClient) -> str:
    # register + login a workspace admin (owner is an admin by default),
    # leave the auth cookies on the shared client, and return the workspace.
    logged_in = _register_and_login(
        client,
        organization_name="Settings Ai Import Mailbox Hook Org",
        email="settings-ai-mailbox-hook@example.test",
    )
    return logged_in["organization"]["organization_id"]


def _create_score_template(client: TestClient) -> str:
    response = client.post(
        "/v1/score-templates",
        json={
            "name": "Backend Engineer",
            "description": "Mailbox-hook settings test template",
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


def _mail_with_attachment(*, message_id: str, filename: str, content: bytes) -> bytes:
    message = EmailMessage()
    message["Message-ID"] = message_id
    message.set_content("Resume attached")
    message.add_attachment(
        content,
        maintype="application",
        subtype="pdf",
        filename=filename,
    )
    return message.as_bytes()


def _import_one_mailbox_resume_and_run_worker(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    organization_id: str,
) -> str:
    """Drive one real mailbox import end-to-end and return the resume_id.

    The real ``save_pdf_resume`` path is used (not a monkeypatched fake), so
    the document-extraction worker can claim the enqueued job and run the Task 6
    gate in ``_save_completed_document_extraction`` against the imported resume.
    """
    raw_message = _mail_with_attachment(
        message_id="<settings-mailbox-hook@example.test>",
        filename="candidate.pdf",
        content=make_pdf_with_text("Education Skills Python " * 20),
    )

    class BoundMailboxImap:
        status_calls = 0

        def __init__(self, *args, **kwargs) -> None:
            pass

        def login(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"logged in"]

        def status(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            self.__class__.status_calls += 1
            # Binding captures UIDNEXT 42; the sync run sees 43, so UID 42 is
            # the one post-bind message to fetch and import.
            uidnext = 42 if self.__class__.status_calls == 1 else 43
            return "OK", [f"INBOX (UIDVALIDITY 9 UIDNEXT {uidnext})".encode()]

        def select(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"1"]

        def uid(self, command: str, *args):
            if command == "search":
                return "OK", [b"42"]
            if command == "fetch":
                return "OK", [(b"RFC822", raw_message)]
            raise AssertionError(f"unexpected IMAP command: {command}")

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", [b"logged out"]

    monkeypatch.setattr(mailbox_import_service.imaplib, "IMAP4_SSL", BoundMailboxImap)

    saved = client.put(
        "/v1/mailbox/config",
        json={
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "email_address": "recruiting@example.test",
            "mailbox": "INBOX",
            "password": "test-authorization-code",
            "enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text

    with client.app.state.database.session_factory() as session:
        # ``sync_mailbox`` resolves the workspace from the mailbox config, so
        # the write session must be bound to the same workspace that owns the
        # config and the AI-import settings row.
        set_organization_context(session, organization_id)
        result = mailbox_import_service.sync_mailbox(
            session,
            settings=client.app.state.settings,
        )
        imports = session.scalars(
            select(EmailAttachmentImport).order_by(EmailAttachmentImport.message_uid)
        ).all()

    assert result.imported_count == 1, result
    assert len(imports) == 1
    resume_id = str(imports[0].resume_id)
    assert resume_id not in {"None", ""}

    assert document_extraction_job_service.run_document_extraction_worker_once(
        client.app.state.database,
        settings=client.app.state.settings,
        worker_id="settings-mailbox-hook-document-worker",
    )
    return resume_id


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


def _resume_ingestion_source_type(client: TestClient, resume_id: str) -> str | None:
    with client.app.state.database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            return resume.ingestion_source_type if resume is not None else None


def test_mailbox_import_auto_enqueues_ai_extraction(client, monkeypatch) -> None:
    # Defaults are all-on, so the worker's auto-enqueue must run exactly as it
    # did before the settings gate existed, even for a mailbox-imported resume.
    organization_id = _admin_org(client)
    resume_id = _import_one_mailbox_resume_and_run_worker(
        client,
        monkeypatch,
        organization_id=organization_id,
    )
    # The provenance stamp must survive the import transaction (regression for
    # the fix that flushed it before ``_complete_processing_import``'s
    # ``session.expire_all()``). Without it the resume is mislabeled as a
    # manual upload and the mailbox gate branch is unreachable.
    assert (
        _resume_ingestion_source_type(client, resume_id) == "mailbox_attachment"
    )
    assert _ai_job_count_for_resume(client, resume_id) == 1


def test_mailbox_import_respects_trigger_off(client, monkeypatch) -> None:
    # Manual upload stays enabled, so this proves the mailbox branch specifically
    # honors its own trigger rather than falling through to the manual setting.
    organization_id = _admin_org(client)
    template_id = _create_score_template(client)
    response = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "default_score_template_id": template_id,
            "trigger_manual_upload": True,
            "trigger_mailbox_import": False,
        },
    )
    assert response.status_code == 200, response.text
    resume_id = _import_one_mailbox_resume_and_run_worker(
        client,
        monkeypatch,
        organization_id=organization_id,
    )
    assert _ai_job_count_for_resume(client, resume_id) == 0


def test_mailbox_import_respects_automation_off(client, monkeypatch) -> None:
    # Both automation switches off (triggers remain on) suppresses the enqueue
    # for a mailbox source too, not just for manual uploads.
    organization_id = _admin_org(client)
    response = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": False,
            "auto_score_enabled": False,
            "default_score_template_id": None,
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 200, response.text
    resume_id = _import_one_mailbox_resume_and_run_worker(
        client,
        monkeypatch,
        organization_id=organization_id,
    )
    assert _ai_job_count_for_resume(client, resume_id) == 0
