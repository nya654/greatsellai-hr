from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.database import Database
from app.models import JobMatch, JobMatchBatch, JobMatchBatchItem, JobVersion, Resume, ResumeFactSnapshot
from app.schemas import JobMatchBatchResponse, JobMatchCreate
from app.services.deepseek_provider import DeepSeekProviderError
from app.services.job_service import (
    JobServiceError,
    JobVersionNotFoundError,
    run_job_match,
)


BATCH_QUEUED = "queued"
BATCH_RUNNING = "running"
BATCH_COMPLETED = "completed"
BATCH_PARTIAL = "partial"
ITEM_QUEUED = "queued"
ITEM_RUNNING = "running"
ITEM_COMPLETED = "completed"
ITEM_FAILED = "failed"
_LEASE_SECONDS = 180


@dataclass(frozen=True)
class ClaimedJobMatchBatchItem:
    item_id: str
    batch_id: str
    resume_id: str
    job_version_id: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _batch_response(batch: JobMatchBatch) -> JobMatchBatchResponse:
    return JobMatchBatchResponse(
        batch_id=batch.id,
        job_version_id=batch.job_version_id,
        status=batch.status,
        total_count=batch.total_count,
        completed_count=batch.completed_count,
        failed_count=batch.failed_count,
        requested_at=batch.requested_at.isoformat(),
        started_at=batch.started_at.isoformat() if batch.started_at else None,
        completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
        last_error=batch.last_error,
    )


def enqueue_job_version_match_batch(
    session: Session,
    *,
    job_version_id: str,
    settings: AppSettings,
) -> JobMatchBatchResponse:
    """Persist one full N×M side of the matrix without calling the model in HTTP."""

    if not settings.deepseek_api_key:
        raise JobServiceError("deepseek_api_key_not_configured")
    job_version = session.get(JobVersion, job_version_id)
    if job_version is None:
        raise JobVersionNotFoundError("job_version_not_found")
    if job_version.status != "confirmed":
        raise JobServiceError("job_version_must_be_confirmed_for_matching")
    if not job_version.requirements:
        raise JobServiceError("job_version_has_no_requirements")

    existing = session.scalar(
        select(JobMatchBatch)
        .where(
            JobMatchBatch.job_version_id == job_version.id,
            JobMatchBatch.status.in_((BATCH_QUEUED, BATCH_RUNNING)),
        )
        .order_by(JobMatchBatch.requested_at.desc())
    )
    if existing is not None:
        return _batch_response(existing)

    now = _utcnow()
    snapshots = session.execute(
        select(Resume.id, ResumeFactSnapshot.id, ResumeFactSnapshot.facts_version)
        .join(
            ResumeFactSnapshot,
            and_(
                ResumeFactSnapshot.resume_id == Resume.id,
                ResumeFactSnapshot.facts_version == Resume.facts_version,
            ),
        )
        .where(Resume.is_active.is_(True), Resume.extraction_status == "ready")
        .order_by(Resume.created_at.asc(), Resume.id.asc())
    ).all()
    batch = JobMatchBatch(
        job_version_id=job_version.id,
        status=BATCH_QUEUED if snapshots else BATCH_COMPLETED,
        total_count=len(snapshots),
        completed_count=0,
        failed_count=0,
        max_attempts=max(1, settings.ai_extraction_job_max_attempts),
        requested_at=now,
        completed_at=now if not snapshots else None,
    )
    session.add(batch)
    session.flush()

    snapshot_ids = [snapshot_id for _, snapshot_id, _ in snapshots]
    cached_by_snapshot: dict[str, str] = {}
    if snapshot_ids:
        cached = session.execute(
            select(JobMatch.fact_snapshot_id, JobMatch.id)
            .where(
                JobMatch.job_version_id == job_version.id,
                JobMatch.fact_snapshot_id.in_(snapshot_ids),
                JobMatch.status.in_(("succeeded", "needs_review")),
            )
            .order_by(JobMatch.created_at.desc(), JobMatch.id.desc())
        ).all()
        for snapshot_id, match_id in cached:
            if snapshot_id is not None:
                cached_by_snapshot.setdefault(snapshot_id, match_id)

    for resume_id, snapshot_id, facts_version in snapshots:
        cached_match_id = cached_by_snapshot.get(snapshot_id)
        session.add(
            JobMatchBatchItem(
                batch_id=batch.id,
                resume_id=resume_id,
                fact_snapshot_id=snapshot_id,
                facts_version=facts_version,
                status=ITEM_COMPLETED if cached_match_id else ITEM_QUEUED,
                next_attempt_at=None if cached_match_id else now,
                job_match_id=cached_match_id,
                completed_at=now if cached_match_id else None,
            )
        )
        if cached_match_id:
            batch.completed_count += 1
    if batch.completed_count == batch.total_count:
        batch.status = BATCH_COMPLETED
        batch.completed_at = now
    session.flush()
    return _batch_response(batch)


def get_job_match_batch(session: Session, *, batch_id: str) -> JobMatchBatchResponse:
    batch = session.get(JobMatchBatch, batch_id)
    if batch is None:
        raise JobServiceError("job_match_batch_not_found")
    return _batch_response(batch)


def run_job_match_batch_worker_once(
    database: Database,
    *,
    settings: AppSettings,
    worker_id: str,
) -> bool:
    claimed = _claim_next_item(database, settings=settings, worker_id=worker_id)
    if claimed is None:
        return False
    _process_claimed_item(database, settings=settings, worker_id=worker_id, claimed=claimed)
    return True


def _recover_expired_items(session: Session, *, now: datetime) -> None:
    expired_items = session.scalars(
        select(JobMatchBatchItem)
        .join(JobMatchBatch)
        .where(
            JobMatchBatchItem.status == ITEM_RUNNING,
            JobMatchBatchItem.lease_expires_at.is_not(None),
            JobMatchBatchItem.lease_expires_at <= now,
        )
    ).all()
    for item in expired_items:
        if item.attempt_count >= item.batch.max_attempts:
            item.status = ITEM_FAILED
            item.completed_at = now
            item.last_error = "job_match_worker_lease_expired"
        else:
            item.status = ITEM_QUEUED
            item.next_attempt_at = now
            item.last_error = "job_match_worker_lease_expired"
        item.lease_owner = None
        item.lease_expires_at = None
        _refresh_batch_progress(session, batch=item.batch, now=now)


def _claim_next_item(
    database: Database,
    *,
    settings: AppSettings,
    worker_id: str,
) -> ClaimedJobMatchBatchItem | None:
    now = _utcnow()
    with database.session_factory() as session:
        _recover_expired_items(session, now=now)
        if not settings.deepseek_api_key:
            session.commit()
            return None
        item = session.scalar(
            select(JobMatchBatchItem)
            .join(JobMatchBatch)
            .where(
                JobMatchBatch.status.in_((BATCH_QUEUED, BATCH_RUNNING)),
                JobMatchBatchItem.status == ITEM_QUEUED,
                or_(
                    JobMatchBatchItem.next_attempt_at.is_(None),
                    JobMatchBatchItem.next_attempt_at <= now,
                ),
            )
            .order_by(
                JobMatchBatch.requested_at.asc(),
                JobMatchBatchItem.next_attempt_at.asc(),
                JobMatchBatchItem.id.asc(),
            )
        )
        if item is None:
            session.commit()
            return None
        item.status = ITEM_RUNNING
        item.attempt_count += 1
        item.next_attempt_at = None
        item.lease_owner = worker_id
        item.lease_expires_at = now + timedelta(seconds=_LEASE_SECONDS)
        item.last_error = None
        batch = item.batch
        batch.status = BATCH_RUNNING
        batch.started_at = batch.started_at or now
        batch.lease_owner = worker_id
        batch.lease_expires_at = item.lease_expires_at
        session.commit()
        return ClaimedJobMatchBatchItem(
            item_id=item.id,
            batch_id=batch.id,
            resume_id=item.resume_id,
            job_version_id=batch.job_version_id,
        )


def _process_claimed_item(
    database: Database,
    *,
    settings: AppSettings,
    worker_id: str,
    claimed: ClaimedJobMatchBatchItem,
) -> None:
    try:
        with database.session_factory() as session:
            item = _owned_item(session, item_id=claimed.item_id, worker_id=worker_id)
            if item is None:
                session.rollback()
                return
            latest_snapshot = session.scalar(
                select(ResumeFactSnapshot)
                .join(Resume)
                .where(
                    Resume.id == item.resume_id,
                    Resume.is_active.is_(True),
                    Resume.extraction_status == "ready",
                    ResumeFactSnapshot.resume_id == Resume.id,
                    ResumeFactSnapshot.facts_version == Resume.facts_version,
                )
            )
            if latest_snapshot is None:
                raise JobServiceError("resume_no_longer_ready_for_job_match")
            item.fact_snapshot_id = latest_snapshot.id
            item.facts_version = latest_snapshot.facts_version
            cached_match = session.scalar(
                select(JobMatch)
                .where(
                    JobMatch.job_version_id == claimed.job_version_id,
                    JobMatch.fact_snapshot_id == latest_snapshot.id,
                    JobMatch.status.in_(("succeeded", "needs_review")),
                )
                .order_by(JobMatch.created_at.desc(), JobMatch.id.desc())
            )
            if cached_match is not None:
                match_id = cached_match.id
            else:
                matched = run_job_match(
                    session,
                    resume_id=item.resume_id,
                    payload=JobMatchCreate(job_version_id=claimed.job_version_id),
                    settings=settings,
                )
                match_id = matched.match_id
            _finish_item_success(session, item=item, worker_id=worker_id, match_id=match_id)
            session.commit()
    except DeepSeekProviderError as exc:
        _finish_item_failure(
            database,
            item_id=claimed.item_id,
            worker_id=worker_id,
            error=str(exc),
            retryable=True,
        )
    except JobServiceError as exc:
        _finish_item_failure(
            database,
            item_id=claimed.item_id,
            worker_id=worker_id,
            error=str(exc),
            retryable=False,
        )
    except Exception:
        _finish_item_failure(
            database,
            item_id=claimed.item_id,
            worker_id=worker_id,
            error="job_match_worker_error",
            retryable=True,
        )


def _owned_item(
    session: Session,
    *,
    item_id: str,
    worker_id: str,
) -> JobMatchBatchItem | None:
    return session.scalar(
        select(JobMatchBatchItem).where(
            JobMatchBatchItem.id == item_id,
            JobMatchBatchItem.status == ITEM_RUNNING,
            JobMatchBatchItem.lease_owner == worker_id,
        )
    )


def _finish_item_success(
    session: Session,
    *,
    item: JobMatchBatchItem,
    worker_id: str,
    match_id: str,
) -> None:
    if item.lease_owner != worker_id or item.status != ITEM_RUNNING:
        raise JobServiceError("job_match_batch_item_lease_lost")
    now = _utcnow()
    item.status = ITEM_COMPLETED
    item.job_match_id = match_id
    item.lease_owner = None
    item.lease_expires_at = None
    item.next_attempt_at = None
    item.last_error = None
    item.completed_at = now
    _refresh_batch_progress(session, batch=item.batch, now=now)


def _finish_item_failure(
    database: Database,
    *,
    item_id: str,
    worker_id: str,
    error: str,
    retryable: bool,
) -> None:
    now = _utcnow()
    with database.session_factory() as session:
        item = _owned_item(session, item_id=item_id, worker_id=worker_id)
        if item is None:
            session.rollback()
            return
        if retryable and item.attempt_count < item.batch.max_attempts:
            item.status = ITEM_QUEUED
            item.next_attempt_at = now + timedelta(seconds=min(60, 2 ** (item.attempt_count - 1)))
            item.completed_at = None
        else:
            item.status = ITEM_FAILED
            item.next_attempt_at = None
            item.completed_at = now
        item.lease_owner = None
        item.lease_expires_at = None
        item.last_error = error[:2000]
        _refresh_batch_progress(session, batch=item.batch, now=now)
        session.commit()


def _refresh_batch_progress(session: Session, *, batch: JobMatchBatch, now: datetime) -> None:
    # The just-finished item must be visible to the aggregate query.  An
    # explicit flush also keeps this correct when the session was previously
    # used by the matching persistence path.
    session.flush()
    counts = dict(
        session.execute(
            select(JobMatchBatchItem.status, func.count())
            .where(JobMatchBatchItem.batch_id == batch.id)
            .group_by(JobMatchBatchItem.status)
        ).all()
    )
    batch.completed_count = counts.get(ITEM_COMPLETED, 0)
    batch.failed_count = counts.get(ITEM_FAILED, 0)
    pending = counts.get(ITEM_QUEUED, 0) + counts.get(ITEM_RUNNING, 0)
    if pending:
        batch.status = BATCH_RUNNING
        return
    batch.status = BATCH_PARTIAL if batch.failed_count else BATCH_COMPLETED
    batch.completed_at = now
    batch.lease_owner = None
    batch.lease_expires_at = None
    if batch.failed_count:
        last_failed = session.scalar(
            select(JobMatchBatchItem.last_error)
            .where(
                JobMatchBatchItem.batch_id == batch.id,
                JobMatchBatchItem.status == ITEM_FAILED,
            )
            .order_by(JobMatchBatchItem.updated_at.desc())
        )
        batch.last_error = last_failed
    else:
        batch.last_error = None


__all__ = [
    "BATCH_COMPLETED",
    "BATCH_PARTIAL",
    "BATCH_QUEUED",
    "BATCH_RUNNING",
    "enqueue_job_version_match_batch",
    "get_job_match_batch",
    "run_job_match_batch_worker_once",
]
