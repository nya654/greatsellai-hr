"""Per-user filter display-field preference API coverage.

A signed-in member (admin *or* recruiter) can read and write their own
``(user_id, organization_id)`` column selection under ``/v1/settings/display-fields``.
The preference is intentionally per-user-within-a-workspace, so two members of
the same workspace keep separate selections and one member's columns never
appear for the other.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import OrganizationMembership, UserAccount, utcnow
from app.services.identity_service import hash_password
from app.tenant_scope import set_organization_context
from test_candidate_data_lifecycle import _register_and_login


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A member settings client with real per-workspace authentication.

    The shared conftest ``client`` fixture enables ``allow_unauthenticated``,
    which resolves every request to the local development identity in the
    legacy workspace.  Per-user settings tests need real membership-bound
    sessions, so this module overrides the fixture with the same ephemeral
    database shape used by the candidate-data lifecycle tests.
    """

    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="settings-display-fields-test-session-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _member_client(client: TestClient) -> TestClient:
    # register + login a workspace owner, set client.auth cookies, return client
    _register_and_login(
        client,
        organization_name="Display Fields Org",
        email="display-fields-member@example.test",
    )
    return client


def _create_same_workspace_member_client(
    owner_client: TestClient,
    *,
    organization_id: str,
    email: str,
) -> TestClient:
    """Create a second verified recruiter in the owner's existing workspace.

    Product invitation acceptance is independently covered by identity tests.
    This narrow setup keeps the test focused on the crucial fact that two
    authenticated users can occupy the *same* workspace while still having
    distinct private preferences.
    """

    password = "display-fields-member-password"
    database = owner_client.app.state.database
    with database.session_factory() as session:
        set_organization_context(session, organization_id)
        member = UserAccount(
            email=email,
            email_key=email.casefold(),
            full_name="Display fields workspace recruiter",
            password_hash=hash_password(password),
            email_verified_at=utcnow(),
        )
        session.add(member)
        session.flush()
        session.add(
            OrganizationMembership(
                organization_id=organization_id,
                user_id=member.id,
                role="recruiter",
            )
        )
        session.commit()

    member_client = TestClient(owner_client.app)
    logged_in = member_client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert logged_in.status_code == 200, logged_in.text
    return member_client


def test_display_fields_defaults_empty(client):
    c = _member_client(client)
    response = c.get("/v1/settings/display-fields")
    assert response.status_code == 200, response.text
    assert response.json() == {"display_field_keys": []}


def test_display_fields_save_and_read(client):
    c = _member_client(client)
    response = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": ["school", "major", "skills"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["display_field_keys"] == ["school", "major", "skills"]
    assert (
        c.get("/v1/settings/display-fields").json()["display_field_keys"]
        == ["school", "major", "skills"]
    )


def test_display_fields_save_empty_clears_selection(client):
    c = _member_client(client)
    saved = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": ["school"]},
    )
    assert saved.status_code == 200, saved.text
    cleared = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["display_field_keys"] == []
    assert (
        c.get("/v1/settings/display-fields").json()["display_field_keys"] == []
    )


def test_display_fields_reject_unknown_key(client):
    c = _member_client(client)
    response = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": ["not_a_real_key"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "unknown_display_field_key"


def test_display_fields_reject_any_unknown_key_among_valid(client):
    c = _member_client(client)
    response = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": ["school", "major", "not_a_real_key"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "unknown_display_field_key"


def test_display_fields_dedupe_preserving_order(client):
    c = _member_client(client)
    response = c.put(
        "/v1/settings/display-fields",
        json={"display_field_keys": ["school", "skills", "school", "major"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["display_field_keys"] == ["school", "skills", "major"]


def test_display_fields_per_user_isolation(client):
    owner = _register_and_login(
        client,
        organization_name="Display Fields Isolation Org",
        email="display-fields-owner@example.test",
    )
    organization_id = owner["organization"]["organization_id"]
    colleague_client = _create_same_workspace_member_client(
        client,
        organization_id=organization_id,
        email="display-fields-colleague@example.test",
    )
    try:
        # The owner (workspace admin) saves a column selection.
        saved = client.put(
            "/v1/settings/display-fields",
            json={"display_field_keys": ["school", "major"]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["display_field_keys"] == ["school", "major"]

        # The colleague (a recruiter in the same workspace) still sees the
        # auto-derived fallback, not the owner's selection.
        colleague_defaults = colleague_client.get("/v1/settings/display-fields")
        assert colleague_defaults.status_code == 200, colleague_defaults.text
        assert colleague_defaults.json()["display_field_keys"] == []

        # The colleague is an authenticated member too, so can save their own.
        colleague_saved = colleague_client.put(
            "/v1/settings/display-fields",
            json={"display_field_keys": ["skills"]},
        )
        assert colleague_saved.status_code == 200, colleague_saved.text
        assert colleague_saved.json()["display_field_keys"] == ["skills"]

        # The owner's selection is unchanged by the colleague's write.
        owner_again = client.get("/v1/settings/display-fields")
        assert owner_again.status_code == 200, owner_again.text
        assert owner_again.json()["display_field_keys"] == ["school", "major"]
    finally:
        colleague_client.close()
