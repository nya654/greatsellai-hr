from __future__ import annotations

from email.message import EmailMessage

from sqlalchemy.exc import DataError

from app.services import mailbox_import_service


def test_mailbox_configuration_never_returns_the_authorization_code(client) -> None:
    initial = client.get("/v1/mailbox/config")
    assert initial.status_code == 200, initial.text
    assert initial.json()["configured"] is False

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
    payload = saved.json()
    assert payload["configured"] is True
    assert payload["password_configured"] is True
    assert "password" not in payload
    assert "test-authorization-code" not in saved.text

    fetched = client.get("/v1/mailbox/config")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["email_address"] == "recruiting@example.test"
    assert "test-authorization-code" not in fetched.text


def test_html_resume_upload_is_preserved_and_served_as_html(client) -> None:
    response = client.post(
        "/v1/resumes/upload",
        files={
            "file": (
                "candidate.html",
                b"<html><body><h1>Candidate</h1><p>Python FastAPI machine learning engineer</p></body></html>",
                "text/html",
            )
        },
    )
    assert response.status_code == 200, response.text
    resume_id = response.json()["resume_id"]

    original = client.get(f"/v1/resumes/{resume_id}/original-file")
    assert original.status_code == 200, original.text
    assert original.headers["content-type"].startswith("text/html")
    assert b"Candidate" in original.content


def test_mailbox_sync_records_database_attachment_failure_without_crashing_worker(
    client,
    monkeypatch,
) -> None:
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

    message = EmailMessage()
    message["Message-ID"] = "<mailbox-failure-test@example.test>"
    message.set_content("Resume attached")
    message.add_attachment(
        b"%PDF-1.7 test attachment",
        maintype="application",
        subtype="pdf",
        filename="resume.pdf",
    )
    raw_message = message.as_bytes()

    class FakeImap:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def login(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"logged in"]

        def select(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"1"]

        def uid(self, command: str, *args):
            if command == "search":
                return "OK", [b"1"]
            if command == "fetch":
                return "OK", [(b"1 (RFC822)", raw_message)]
            raise AssertionError(f"unexpected IMAP command: {command}")

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", [b"logged out"]

    def database_failure(*args, **kwargs):
        raise DataError("INSERT", {}, ValueError("unexpected NUL byte"))

    monkeypatch.setattr(mailbox_import_service.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(mailbox_import_service, "save_pdf_resume", database_failure)

    with client.app.state.database.session_factory() as session:
        result = mailbox_import_service.sync_mailbox(
            session,
            settings=client.app.state.settings,
        )

    assert result.imported_count == 0
    assert result.failed_count == 1
    assert result.last_sync_error is None
