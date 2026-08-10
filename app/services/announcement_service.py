"""Platform-wide system announcements and per-user read state.

Announcements are intentionally global (never tenant-scoped): the same active
set is served to every signed-in user, while read state lives in
``announcement_reads`` so one person acknowledging a notice never hides it
from anyone else.  Admin mutations are audited by the route layer; the
workspace bell endpoints here only read published rows or insert read rows.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Announcement, AnnouncementRead
from app.schemas import AnnouncementInboxResponse, AnnouncementResponse


class AnnouncementNotFoundError(RuntimeError):
    """One stable response for a missing or already-deleted announcement."""


def _get_announcement(session: Session, *, announcement_id: str) -> Announcement:
    announcement = session.get(Announcement, announcement_id)
    if announcement is None:
        raise AnnouncementNotFoundError("announcement_not_found")
    return announcement


def _response(announcement: Announcement) -> AnnouncementResponse:
    return AnnouncementResponse(
        announcement_id=announcement.id,
        title=announcement.title,
        body=announcement.body,
        is_published=announcement.is_published,
        published_at=announcement.published_at,
        created_at=announcement.created_at,
        updated_at=announcement.updated_at,
    )


def list_announcements(
    session: Session,
    *,
    include_unpublished: bool,
) -> list[AnnouncementResponse]:
    """List all announcements (admin) or only the published set (workspace)."""

    statement = select(Announcement)
    if not include_unpublished:
        statement = statement.where(Announcement.is_published.is_(True))
    announcements = session.scalars(
        statement.order_by(
            Announcement.published_at.desc().nulls_last(),
            Announcement.created_at.desc(),
            Announcement.id.desc(),
        )
    ).all()
    return [_response(item) for item in announcements]


def create_announcement(
    session: Session,
    *,
    title: str,
    body: str,
    actor_user_id: str | None,
) -> AnnouncementResponse:
    """Create a system announcement in the published state.

    The product lifecycle is "create and it is immediately live, unpublish to
    hide it, republish to show it again" — there is intentionally no draft
    state or scheduled expiry.
    """

    now = datetime.now(timezone.utc)
    announcement = Announcement(
        title=title,
        body=body,
        is_published=True,
        published_at=now,
        created_by_user_id=actor_user_id,
    )
    session.add(announcement)
    session.flush()
    return _response(announcement)


def update_announcement(
    session: Session,
    *,
    announcement_id: str,
    title: str,
    body: str,
) -> AnnouncementResponse:
    """Edit an announcement's content, preserving its publish state."""

    announcement = _get_announcement(session, announcement_id=announcement_id)
    announcement.title = title
    announcement.body = body
    session.flush()
    return _response(announcement)


def set_announcement_published(
    session: Session,
    *,
    announcement_id: str,
    published: bool,
) -> AnnouncementResponse:
    """Toggle an announcement between published and unpublished.

    Publishing stamps ``published_at`` so the workspace list stays newest
    first; unpublishing clears it.  A no-op toggle keeps its current value.
    """

    announcement = _get_announcement(session, announcement_id=announcement_id)
    if published and not announcement.is_published:
        announcement.is_published = True
        announcement.published_at = datetime.now(timezone.utc)
    elif not published and announcement.is_published:
        announcement.is_published = False
        announcement.published_at = None
    session.flush()
    return _response(announcement)


def delete_announcement(session: Session, *, announcement_id: str) -> None:
    """Delete an announcement and its cascade of per-user read rows."""

    announcement = _get_announcement(session, announcement_id=announcement_id)
    session.delete(announcement)
    session.flush()


def announcement_inbox(
    session: Session,
    *,
    user_id: str,
) -> AnnouncementInboxResponse:
    """Active announcements plus one user's unread count, newest first."""

    active = session.scalars(
        select(Announcement)
        .where(Announcement.is_published.is_(True))
        .order_by(
            Announcement.published_at.desc().nulls_last(),
            Announcement.created_at.desc(),
            Announcement.id.desc(),
        )
    ).all()
    if active:
        read_ids = set(
            session.scalars(
                select(AnnouncementRead.announcement_id).where(
                    AnnouncementRead.user_id == user_id,
                    AnnouncementRead.announcement_id.in_(
                        [item.id for item in active]
                    ),
                )
            ).all()
        )
    else:
        read_ids = set()
    items = [_response(item) for item in active]
    unread_count = sum(1 for item in active if item.id not in read_ids)
    return AnnouncementInboxResponse(items=items, unread_count=unread_count)


def mark_all_announcements_read(
    session: Session,
    *,
    user_id: str,
) -> AnnouncementInboxResponse:
    """Acknowledge every currently active announcement for this user.

    The unique ``(announcement_id, user_id)`` constraint makes a second
    browser tab a harmless duplicate-insert race; a savepoint keeps it from
    rolling back the request transaction.
    """

    active_ids = set(
        session.scalars(
            select(Announcement.id).where(Announcement.is_published.is_(True))
        ).all()
    )
    if active_ids:
        already_read = set(
            session.scalars(
                select(AnnouncementRead.announcement_id).where(
                    AnnouncementRead.user_id == user_id,
                    AnnouncementRead.announcement_id.in_(active_ids),
                )
            ).all()
        )
        for announcement_id in sorted(active_ids - already_read):
            session.add(
                AnnouncementRead(
                    announcement_id=announcement_id,
                    user_id=user_id,
                )
            )
        session.flush()
    return announcement_inbox(session, user_id=user_id)


__all__ = [
    "AnnouncementNotFoundError",
    "announcement_inbox",
    "create_announcement",
    "delete_announcement",
    "list_announcements",
    "mark_all_announcements_read",
    "set_announcement_published",
    "update_announcement",
]
