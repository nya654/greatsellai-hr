from __future__ import annotations

from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.exc import DataError

from app.models import MailboxConfig
from app.services import mailbox_import_service


class StatusOnlyImap:
    """Enough IMAP behavior for configuration saves that capture UIDNEXT."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def login(self, *args, **kwargs) -> tuple[str, list[bytes]]:
        return "OK", [b"logged in"]

    def status(self, *args, **kwargs) -> tuple[str, list[bytes]]:
        return "OK", [b'INBOX (UIDVALIDITY 9 UIDNEXT 42)']

    def logout(self) -> tuple[str, list[bytes]]:
        return "BYE", [b"logged out"]


def test_mailbox_configuration_never_returns_the_authorization_code(client, monkeypatch) -> None:
    monkeypatch.setattr(mailbox_import_service.imaplib, "IMAP4_SSL", StatusOnlyImap)
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
    assert payload["import_started_at"] is not None
    assert "password" not in payload
    assert "test-authorization-code" not in saved.text

    fetched = client.get("/v1/mailbox/config")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["email_address"] == "recruiting@example.test"
    assert "test-authorization-code" not in fetched.text


def test_mailbox_binding_searches_only_messages_at_or_after_uidnext(
    client,
    monkeypatch,
) -> None:
    message = EmailMessage()
    message["Message-ID"] = "<new-mail-after-binding@example.test>"
    message.set_content("Resume attached")
    message.add_attachment(
        b"not a supported resume format",
        maintype="text",
        subtype="plain",
        filename="resume.txt",
    )
    raw_message = message.as_bytes()

    class BoundMailboxImap:
        search_args: list[tuple[object, ...]] = []
        fetched_uids: list[bytes] = []

        def __init__(self, *args, **kwargs) -> None:
            pass

        def login(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"logged in"]

        def status(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b'INBOX (UIDVALIDITY 9 UIDNEXT 42)']

        def select(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"1"]

        def uid(self, command: str, *args):
            if command == "search":
                self.search_args.append(args)
                return "OK", [b"42"]
            if command == "fetch":
                self.fetched_uids.append(args[0])
                return "OK", [(b"42 (RFC822)", raw_message)]
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
        result = mailbox_import_service.sync_mailbox(
            session,
            settings=client.app.state.settings,
        )

    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert BoundMailboxImap.search_args == [(None, "UID 42:*")]
    assert BoundMailboxImap.fetched_uids == [b"42"]


def test_existing_mailbox_without_watermark_skips_its_history_once(
    client,
    monkeypatch,
) -> None:
    class LegacyMailboxImap:
        selected = False
        searched = False

        def __init__(self, *args, **kwargs) -> None:
            pass

        def login(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"logged in"]

        def status(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b'INBOX (UIDVALIDITY 33 UIDNEXT 108)']

        def select(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            self.selected = True
            raise AssertionError("legacy history must not be selected or fetched")

        def uid(self, command: str, *args):
            self.searched = True
            raise AssertionError("legacy history must not be searched")

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", [b"logged out"]

    monkeypatch.setattr(mailbox_import_service.imaplib, "IMAP4_SSL", LegacyMailboxImap)
    encrypted_password = mailbox_import_service._fernet(
        client.app.state.settings,
    ).encrypt(b"test-authorization-code").decode("ascii")
    with client.app.state.database.session_factory() as session:
        config = MailboxConfig(
            imap_host="imap.example.test",
            imap_port=993,
            email_address="recruiting@example.test",
            mailbox="INBOX",
            encrypted_password=encrypted_password,
            enabled=True,
        )
        session.add(config)
        session.commit()
        config_id = config.id

    with client.app.state.database.session_factory() as session:
        result = mailbox_import_service.sync_mailbox(
            session,
            settings=client.app.state.settings,
            config_id=config_id,
        )
        stored = session.get(MailboxConfig, config_id)
        assert stored is not None
        assert stored.import_start_uid == 108
        assert stored.imap_uidvalidity == 33
        assert stored.import_started_at is not None

    assert result.imported_count == 0
    assert result.skipped_count == 0
    assert LegacyMailboxImap.selected is False
    assert LegacyMailboxImap.searched is False


def test_mailbox_rebinding_resets_the_uid_watermark_but_settings_edits_do_not(
    client,
    monkeypatch,
) -> None:
    class RebindingImap:
        status_replies = [
            b'INBOX (UIDVALIDITY 9 UIDNEXT 42)',
            b'Archive (UIDVALIDITY 12 UIDNEXT 90)',
        ]
        status_calls = 0

        def __init__(self, *args, **kwargs) -> None:
            pass

        def login(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b"logged in"]

        def status(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            reply = self.status_replies[self.status_calls]
            self.__class__.status_calls += 1
            return "OK", [reply]

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", [b"logged out"]

    monkeypatch.setattr(mailbox_import_service.imaplib, "IMAP4_SSL", RebindingImap)
    initial = client.put(
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
    assert initial.status_code == 200, initial.text

    settings_only = client.put(
        "/v1/mailbox/config",
        json={
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "email_address": "recruiting@example.test",
            "mailbox": "INBOX",
            "enabled": False,
        },
    )
    assert settings_only.status_code == 200, settings_only.text
    assert RebindingImap.status_calls == 1

    rebound = client.put(
        "/v1/mailbox/config",
        json={
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "email_address": "recruiting@example.test",
            "mailbox": "Archive",
            "enabled": True,
        },
    )
    assert rebound.status_code == 200, rebound.text
    assert RebindingImap.status_calls == 2

    with client.app.state.database.session_factory() as session:
        config = session.scalar(select(MailboxConfig))
        assert config is not None
        assert config.import_start_uid == 90
        assert config.imap_uidvalidity == 12


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

        def status(self, *args, **kwargs) -> tuple[str, list[bytes]]:
            return "OK", [b'INBOX (UIDVALIDITY 9 UIDNEXT 42)']

        def uid(self, command: str, *args):
            if command == "search":
                return "OK", [b"42"]
            if command == "fetch":
                return "OK", [(b"42 (RFC822)", raw_message)]
            raise AssertionError(f"unexpected IMAP command: {command}")

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", [b"logged out"]

    def database_failure(*args, **kwargs):
        raise DataError("INSERT", {}, ValueError("unexpected NUL byte"))

    monkeypatch.setattr(mailbox_import_service.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(mailbox_import_service, "save_pdf_resume", database_failure)

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
        result = mailbox_import_service.sync_mailbox(
            session,
            settings=client.app.state.settings,
        )

    assert result.imported_count == 0
    assert result.failed_count == 1
    assert result.last_sync_error is None
