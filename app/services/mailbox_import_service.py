from __future__ import annotations

import base64
import hashlib
import imaplib
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.models import Candidate, EmailAttachmentImport, MailboxConfig
from app.schemas import (
    MailboxConfigResponse,
    MailboxConfigUpdate,
    MailboxImportHistoryResponse,
    MailboxImportResponse,
    MailboxSyncResponse,
)
from app.services.ai_extraction_job_service import enqueue_uploaded_resume_ai_extraction
from app.services.document_text_extraction import SUPPORTED_DOCUMENT_EXTENSIONS
from app.services.resume_service import (
    UploadValidationError,
    create_candidate,
    save_pdf_resume,
)


class MailboxImportError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fernet(settings: AppSettings) -> Fernet:
    """Use a dedicated key when present, otherwise derive from app session key."""

    material = (
        settings.email_credentials_key
        or settings.session_secret
        or settings.admin_token
        or "resume-v3-development-session"
    )
    if settings.email_credentials_key:
        try:
            return Fernet(material.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise MailboxImportError("mailbox_credentials_key_invalid") from exc
    derived = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(derived)


def _safe_filename(value: str | None) -> str:
    if not value:
        return "attachment"
    try:
        decoded = str(make_header(decode_header(value)))
    except (TypeError, ValueError):
        decoded = value
    return (
        decoded.replace("/", "_")
        .replace("\\", "_")
        .replace("\x00", "")
        .strip()[:255]
        or "attachment"
    )


def _received_at(message: Message) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(message.get("Date"))
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _config_response(config: MailboxConfig | None) -> MailboxConfigResponse:
    if config is None:
        return MailboxConfigResponse(configured=False)
    return MailboxConfigResponse(
        configured=True,
        imap_host=config.imap_host,
        imap_port=config.imap_port,
        email_address=config.email_address,
        mailbox=config.mailbox,
        enabled=config.enabled,
        password_configured=bool(config.encrypted_password),
        last_synced_at=config.last_synced_at,
        last_sync_error=config.last_sync_error,
    )


def get_mailbox_config(session: Session) -> MailboxConfigResponse:
    config = session.scalar(select(MailboxConfig).order_by(desc(MailboxConfig.created_at)))
    return _config_response(config)


def save_mailbox_config(
    session: Session,
    *,
    settings: AppSettings,
    payload: MailboxConfigUpdate,
) -> MailboxConfigResponse:
    config = session.scalar(select(MailboxConfig).order_by(desc(MailboxConfig.created_at)))
    if config is None and not payload.password:
        raise MailboxImportError("mailbox_password_required")
    encrypted_password = config.encrypted_password if config is not None else ""
    if payload.password:
        encrypted_password = _fernet(settings).encrypt(payload.password.encode("utf-8")).decode("ascii")
    if config is None:
        config = MailboxConfig(
            imap_host=payload.imap_host.strip(),
            imap_port=payload.imap_port,
            email_address=payload.email_address.strip(),
            mailbox=payload.mailbox.strip(),
            encrypted_password=encrypted_password,
            enabled=payload.enabled,
        )
        session.add(config)
    else:
        config.imap_host = payload.imap_host.strip()
        config.imap_port = payload.imap_port
        config.email_address = payload.email_address.strip()
        config.mailbox = payload.mailbox.strip()
        config.encrypted_password = encrypted_password
        config.enabled = payload.enabled
        config.last_sync_error = None
    session.commit()
    return _config_response(config)


def list_mailbox_imports(session: Session, *, limit: int = 40) -> MailboxImportHistoryResponse:
    records = session.scalars(
        select(EmailAttachmentImport)
        .order_by(desc(EmailAttachmentImport.created_at))
        .limit(limit)
    ).all()
    total = session.scalar(select(func.count()).select_from(EmailAttachmentImport))
    return MailboxImportHistoryResponse(
        items=[
            MailboxImportResponse(
                attachment_filename=item.attachment_filename,
                status=item.status,
                error=item.error,
                resume_id=item.resume_id,
                created_at=item.created_at,
            )
            for item in records
        ],
        total=int(total or 0),
    )


def _record(
    session: Session,
    *,
    config: MailboxConfig,
    uid: str,
    message_id: str | None,
    filename: str,
    attachment_sha256: str,
    status: str,
    error: str | None,
    resume_id: str | None,
    received_at: datetime | None,
) -> None:
    session.add(
        EmailAttachmentImport(
            mailbox_config_id=config.id,
            message_uid=uid,
            message_id=message_id[:998] if message_id else None,
            attachment_filename=filename,
            attachment_sha256=attachment_sha256,
            status=status,
            error=error,
            resume_id=resume_id,
            received_at=received_at,
        )
    )
    session.commit()


def _already_imported(session: Session, *, config_id: str, uid: str, digest: str) -> bool:
    return (
        session.scalar(
            select(EmailAttachmentImport.id).where(
                EmailAttachmentImport.mailbox_config_id == config_id,
                EmailAttachmentImport.message_uid == uid,
                EmailAttachmentImport.attachment_sha256 == digest,
            )
        )
        is not None
    )


def _known_message_uids(session: Session, *, config_id: str) -> set[str]:
    """Return message UIDs already handled by an earlier incremental run."""

    return set(
        session.scalars(
            select(EmailAttachmentImport.message_uid).where(
                EmailAttachmentImport.mailbox_config_id == config_id
            )
        ).all()
    )


def _attachments(message: Message) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    for part in message.walk():
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if not filename or disposition not in {"attachment", "inline"}:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            found.append((_safe_filename(filename), payload))
    return found


def sync_mailbox(
    session: Session,
    *,
    settings: AppSettings,
    config_id: str | None = None,
) -> MailboxSyncResponse:
    config_query = select(MailboxConfig).order_by(desc(MailboxConfig.created_at))
    if config_id:
        config_query = select(MailboxConfig).where(MailboxConfig.id == config_id)
    config = session.scalar(config_query)
    if config is None:
        return MailboxSyncResponse(configured=False)
    if not config.enabled:
        return MailboxSyncResponse(
            configured=True,
            last_synced_at=config.last_synced_at,
            last_sync_error=config.last_sync_error,
        )
    mailbox_config_id = config.id
    try:
        password = _fernet(settings).decrypt(config.encrypted_password.encode("ascii")).decode("utf-8")
    except (MailboxImportError, InvalidToken, UnicodeDecodeError) as exc:
        config.last_sync_error = "mailbox_credentials_unavailable"
        session.commit()
        raise MailboxImportError("mailbox_credentials_unavailable") from exc

    imported = duplicates = skipped = failed = 0
    client: imaplib.IMAP4_SSL | None = None
    try:
        client = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=30)
        client.login(config.email_address, password)
        status, _ = client.select(config.mailbox, readonly=True)
        if status != "OK":
            raise MailboxImportError("mailbox_select_failed")
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise MailboxImportError("mailbox_search_failed")
        known_uids = _known_message_uids(session, config_id=config.id)
        selected_uids: list[bytes] = []
        # Work newest-first so freshly received resumes arrive immediately.
        # Already-recorded UIDs are skipped before a full RFC822 fetch. Once a
        # batch is done, the next run naturally continues farther back through
        # historical mail rather than repeatedly fetching the same messages.
        for raw_uid in reversed((data[0] or b"").split()):
            uid = raw_uid.decode("ascii", errors="ignore")
            if not uid or uid in known_uids:
                continue
            selected_uids.append(raw_uid)
            if len(selected_uids) >= settings.mailbox_sync_attachment_limit:
                break
        uids = list(reversed(selected_uids))
        for raw_uid in uids:
            uid = raw_uid.decode("ascii", errors="ignore")
            status, fetched = client.uid("fetch", raw_uid, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                failed += 1
                continue
            message = BytesParser(policy=policy.default).parsebytes(fetched[0][1])
            message_id = str(message.get("Message-ID") or "").strip() or None
            received_at = _received_at(message)
            attachments = _attachments(message)
            if not attachments:
                digest = hashlib.sha256(b"").hexdigest()
                _record(
                    session,
                    config=config,
                    uid=uid,
                    message_id=message_id,
                    filename="[no supported attachment]",
                    attachment_sha256=digest,
                    status="skipped",
                    error="no_supported_attachment",
                    resume_id=None,
                    received_at=received_at,
                )
                skipped += 1
                known_uids.add(uid)
                continue
            for filename, content in attachments:
                digest = hashlib.sha256(content).hexdigest()
                if _already_imported(session, config_id=config.id, uid=uid, digest=digest):
                    duplicates += 1
                    continue
                if not any(filename.lower().endswith(ext) for ext in SUPPORTED_DOCUMENT_EXTENSIONS):
                    _record(session, config=config, uid=uid, message_id=message_id, filename=filename, attachment_sha256=digest, status="skipped", error="unsupported_document_type", resume_id=None, received_at=received_at)
                    skipped += 1
                    continue
                try:
                    candidate = create_candidate(session, display_name=None)
                    resume = save_pdf_resume(
                        session,
                        candidate_id=candidate.id,
                        original_filename=filename,
                        content=content,
                        settings=settings,
                    )
                    enqueue_uploaded_resume_ai_extraction(session, resume=resume, settings=settings)
                    _record(session, config=config, uid=uid, message_id=message_id, filename=filename, attachment_sha256=digest, status="imported", error=None, resume_id=resume.id, received_at=received_at)
                    imported += 1
                except (UploadValidationError, RuntimeError, SQLAlchemyError):
                    session.rollback()
                    config = session.get(MailboxConfig, mailbox_config_id)
                    if config is None:
                        raise MailboxImportError("mailbox_config_not_found")
                    _record(session, config=config, uid=uid, message_id=message_id, filename=filename, attachment_sha256=digest, status="failed", error="attachment_import_failed", resume_id=None, received_at=received_at)
                    failed += 1
        config = session.get(MailboxConfig, mailbox_config_id)
        if config is None:
            raise MailboxImportError("mailbox_config_not_found")
        config.last_synced_at = _utcnow()
        config.last_sync_error = None
        session.commit()
    except (imaplib.IMAP4.error, OSError, MailboxImportError, SQLAlchemyError) as exc:
        session.rollback()
        config = session.get(MailboxConfig, mailbox_config_id)
        if config is not None:
            config.last_sync_error = (
                str(exc)
                if str(exc).startswith("mailbox_")
                else "mailbox_sync_failed"
                if isinstance(exc, SQLAlchemyError)
                else "mailbox_connection_failed"
            )
            session.commit()
        if isinstance(exc, MailboxImportError):
            raise
        if isinstance(exc, SQLAlchemyError):
            raise MailboxImportError("mailbox_sync_failed") from exc
        raise MailboxImportError("mailbox_connection_failed") from exc
    finally:
        if client is not None:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
    return MailboxSyncResponse(
        configured=True,
        imported_count=imported,
        duplicate_count=duplicates,
        skipped_count=skipped,
        failed_count=failed,
        last_synced_at=config.last_synced_at,
        last_sync_error=config.last_sync_error,
    )


def sync_due_mailboxes(*, database, settings: AppSettings) -> bool:
    cutoff = _utcnow() - timedelta(seconds=settings.mailbox_sync_interval_seconds)
    with database.session_factory() as session:
        config = session.scalar(
            select(MailboxConfig)
            .where(MailboxConfig.enabled.is_(True))
            .where(
                (MailboxConfig.last_synced_at.is_(None))
                | (MailboxConfig.last_synced_at <= cutoff)
            )
            .order_by(MailboxConfig.last_synced_at)
        )
        if config is None:
            return False
        try:
            sync_mailbox(session, settings=settings, config_id=config.id)
        except MailboxImportError:
            return True
        return True
