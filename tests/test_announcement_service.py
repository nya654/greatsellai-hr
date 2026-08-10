from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import Announcement, AnnouncementRead, UserAccount

_PLATFORM_ADMIN_EMAIL = "announcement-platform-admin@example.test"
_PLATFORM_ADMIN_PASSWORD = "announcement-platform-admin-password"

_MEMBER_EMAIL = "announcement-member@example.test"
_MEMBER_PASSWORD = "announcement-member-password"


@pytest.fixture
def announcement_client(tmp_path: Path) -> Iterator[TestClient]:
    """A disposable database with a named platform admin account."""

    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        database_url="sqlite://",
        session_secret="announcement-test-session-secret",
        allow_unauthenticated=False,
        transactional_email_provider="test",
        public_app_url="http://testserver",
    )
    with TestClient(create_app(settings)) as client:
        _register_and_promote_platform_admin(client)
        yield client


def _register(
    client: TestClient,
    *,
    organization_name: str,
    full_name: str,
    email: str,
    password: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/auth/register",
        json={
            "organization_name": organization_name,
            "full_name": full_name,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    delivery = client.app.state.transactional_email_provider.deliveries[-1]
    token = parse_qs(urlsplit(delivery.verification_url).query)["token"][0]
    verified = client.post("/v1/auth/email-verification/complete", json={"token": token})
    assert verified.status_code == 200, verified.text
    return verified.json()


def _register_and_promote_platform_admin(client: TestClient) -> None:
    registered = _register(
        client,
        organization_name="Announcement control workspace",
        full_name="Announcement control administrator",
        email=_PLATFORM_ADMIN_EMAIL,
        password=_PLATFORM_ADMIN_PASSWORD,
    )
    user_id = registered["user"]["user_id"]
    with client.app.state.database.session_factory() as session:
        user = session.scalar(select(UserAccount).where(UserAccount.id == user_id))
        assert user is not None
        user.is_platform_admin = True
        session.commit()
    assert client.post("/v1/auth/logout").status_code == 204


def _register_member(client: TestClient) -> dict[str, object]:
    return _register(
        client,
        organization_name="Announcement fixture workspace",
        full_name="Announcement fixture member",
        email=_MEMBER_EMAIL,
        password=_MEMBER_PASSWORD,
    )


def _login_platform_admin(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/login",
        json={"email": _PLATFORM_ADMIN_EMAIL, "password": _PLATFORM_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_platform_admin"] is True


def _create_announcement(
    client: TestClient,
    *,
    title: str = "Scheduled maintenance",
    body: str = "Platform will be briefly unavailable at 02:00 UTC.",
    reason: str = "notify workspace users",
) -> dict[str, object]:
    response = client.post(
        "/v1/platform/announcements",
        json={"title": title, "body": body, "reason": reason},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_platform_admin_crud_lifecycle(announcement_client: TestClient) -> None:
    _login_platform_admin(announcement_client)

    created = _create_announcement(announcement_client)
    announcement_id = created["announcement_id"]
    assert created["is_published"] is True
    assert created["published_at"] is not None
    assert created["created_at"] is not None

    listed = announcement_client.get("/v1/platform/announcements")
    assert listed.status_code == 200, listed.text
    assert [item["announcement_id"] for item in listed.json()] == [announcement_id]

    updated = announcement_client.put(
        f"/v1/platform/announcements/{announcement_id}",
        json={
            "title": "Maintenance rescheduled",
            "body": "Maintenance now runs at 04:00 UTC.",
            "reason": "reschedule notice",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Maintenance rescheduled"

    unpublished = announcement_client.post(
        f"/v1/platform/announcements/{announcement_id}/unpublish",
        json={"reason": "hide during rollout"},
    )
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["is_published"] is False
    assert unpublished.json()["published_at"] is None

    republished = announcement_client.post(
        f"/v1/platform/announcements/{announcement_id}/publish",
        json={"reason": "rollout complete"},
    )
    assert republished.status_code == 200, republished.text
    assert republished.json()["is_published"] is True
    assert republished.json()["published_at"] is not None

    deleted = announcement_client.request(
        "DELETE",
        f"/v1/platform/announcements/{announcement_id}",
        json={"reason": "no longer needed"},
    )
    assert deleted.status_code == 204, deleted.text

    after = announcement_client.get("/v1/platform/announcements")
    assert after.status_code == 200, after.text
    assert after.json() == []


def test_create_announcement_is_immediately_visible_to_members(
    announcement_client: TestClient,
) -> None:
    _login_platform_admin(announcement_client)
    created = _create_announcement(announcement_client)

    _register_member(announcement_client)
    inbox = announcement_client.get("/v1/announcements")
    assert inbox.status_code == 200, inbox.text
    payload = inbox.json()
    assert payload["unread_count"] == 1
    assert [item["announcement_id"] for item in payload["items"]] == [
        created["announcement_id"]
    ]
    assert payload["items"][0]["title"] == created["title"]


def test_member_open_panel_marks_all_read(announcement_client: TestClient) -> None:
    _login_platform_admin(announcement_client)
    _create_announcement(announcement_client)
    _create_announcement(
        announcement_client,
        title="Second notice",
        body="A second platform notice.",
        reason="second notice",
    )

    _register_member(announcement_client)
    initial = announcement_client.get("/v1/announcements")
    assert initial.json()["unread_count"] == 2

    acknowledged = announcement_client.post("/v1/announcements/read")
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["unread_count"] == 0
    assert len(acknowledged.json()["items"]) == 2

    repeated = announcement_client.post("/v1/announcements/read")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["unread_count"] == 0

    reloaded = announcement_client.get("/v1/announcements")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["unread_count"] == 0
    assert len(reloaded.json()["items"]) == 2


def test_unpublished_announcement_hidden_from_members_but_kept_for_admin(
    announcement_client: TestClient,
) -> None:
    _login_platform_admin(announcement_client)
    created = _create_announcement(announcement_client)
    hidden = _create_announcement(
        announcement_client,
        title="Draft only",
        body="This should not be broadcast yet.",
        reason="keep unpublished",
    )
    removed = announcement_client.post(
        f"/v1/platform/announcements/{hidden['announcement_id']}/unpublish",
        json={"reason": "not ready"},
    )
    assert removed.status_code == 200, removed.text

    admin_list = announcement_client.get(
        "/v1/platform/announcements",
        params={"include_unpublished": "true"},
    )
    assert admin_list.status_code == 200, admin_list.text
    listed_ids = {item["announcement_id"] for item in admin_list.json()}
    assert listed_ids == {created["announcement_id"], hidden["announcement_id"]}

    _register_member(announcement_client)
    inbox = announcement_client.get("/v1/announcements")
    assert inbox.status_code == 200, inbox.text
    assert [item["announcement_id"] for item in inbox.json()["items"]] == [
        created["announcement_id"]
    ]


def test_platform_admin_routes_require_platform_admin(
    announcement_client: TestClient,
) -> None:
    _register_member(announcement_client)

    denied_create = announcement_client.post(
        "/v1/platform/announcements",
        json={
            "title": "Blocked",
            "body": "A non-admin cannot create this.",
            "reason": "should be denied",
        },
    )
    assert denied_create.status_code == 403, denied_create.text

    denied_list = announcement_client.get("/v1/platform/announcements")
    assert denied_list.status_code == 403, denied_list.text


def test_missing_announcement_returns_404(announcement_client: TestClient) -> None:
    _login_platform_admin(announcement_client)

    for method, path, payload in [
        ("PUT", "/v1/platform/announcements/nope", {"title": "x", "body": "y", "reason": "z"}),
        ("POST", "/v1/platform/announcements/nope/publish", {"reason": "z"}),
        ("POST", "/v1/platform/announcements/nope/unpublish", {"reason": "z"}),
        ("DELETE", "/v1/platform/announcements/nope", {"reason": "z"}),
    ]:
        response = announcement_client.request(method, path, json=payload)
        assert response.status_code == 404, (method, response.text)
        assert response.json()["detail"] == "announcement_not_found"


def test_blank_title_or_body_is_rejected(announcement_client: TestClient) -> None:
    _login_platform_admin(announcement_client)

    blank_title = announcement_client.post(
        "/v1/platform/announcements",
        json={"title": "   ", "body": "Has a body.", "reason": "z"},
    )
    assert blank_title.status_code == 422, blank_title.text

    blank_body = announcement_client.post(
        "/v1/platform/announcements",
        json={"title": "Has a title", "body": "", "reason": "z"},
    )
    assert blank_body.status_code == 422, blank_body.text


def test_announcement_mutations_are_audited(announcement_client: TestClient) -> None:
    _login_platform_admin(announcement_client)
    created = _create_announcement(announcement_client)

    events = announcement_client.get(
        "/v1/platform/audit-events",
        params={"action": "announcement.created"},
    )
    assert events.status_code == 200, events.text
    assert any(
        item["target_id"] == created["announcement_id"]
        and item["target_type"] == "announcement"
        for item in events.json()["items"]
    )


def test_read_rows_cascade_when_announcement_deleted(
    announcement_client: TestClient,
) -> None:
    _login_platform_admin(announcement_client)
    created = _create_announcement(announcement_client)

    _register_member(announcement_client)
    assert announcement_client.post("/v1/announcements/read").status_code == 200

    with announcement_client.app.state.database.session_factory() as session:
        assert session.scalar(
            select(AnnouncementRead).where(
                AnnouncementRead.announcement_id == created["announcement_id"]
            )
        ) is not None
        assert session.scalar(
            select(Announcement).where(Announcement.id == created["announcement_id"])
        ) is not None

    _login_platform_admin(announcement_client)
    deleted = announcement_client.request(
        "DELETE",
        f"/v1/platform/announcements/{created['announcement_id']}",
        json={"reason": "clean up"},
    )
    assert deleted.status_code == 204, deleted.text

    with announcement_client.app.state.database.session_factory() as session:
        assert session.scalar(
            select(AnnouncementRead).where(
                AnnouncementRead.announcement_id == created["announcement_id"]
            )
        ) is None
        assert session.scalar(
            select(Announcement).where(Announcement.id == created["announcement_id"])
        ) is None


def test_published_at_is_stamped_and_cleared(announcement_client: TestClient) -> None:
    _login_platform_admin(announcement_client)
    created = _create_announcement(announcement_client)
    assert datetime.fromisoformat(created["published_at"]).tzinfo is not None
    assert datetime.fromisoformat(created["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(created["updated_at"]).tzinfo is not None

    unpublished = announcement_client.post(
        f"/v1/platform/announcements/{created['announcement_id']}/unpublish",
        json={"reason": "unpublish"},
    )
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["published_at"] is None

    republished = announcement_client.post(
        f"/v1/platform/announcements/{created['announcement_id']}/publish",
        json={"reason": "republish"},
    )
    assert republished.status_code == 200, republished.text
    assert republished.json()["is_published"] is True
    assert datetime.fromisoformat(republished.json()["published_at"]).tzinfo is not None
