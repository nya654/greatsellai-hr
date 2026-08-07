from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import OrganizationMembership, ScoreTemplate
from app.tenant_scope import set_organization_context
from test_candidate_data_lifecycle import _register_and_login


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """An admin-only settings client with real per-workspace authentication.

    The shared conftest ``client`` fixture enables ``allow_unauthenticated``,
    which resolves every request to the local development identity in the
    legacy workspace.  Org-scoped settings tests need real membership-bound
    sessions, so this module overrides the fixture with the same ephemeral
    database shape used by the candidate-data lifecycle tests.
    """

    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="settings-ai-import-test-session-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _admin_client(client: TestClient) -> TestClient:
    # register + login a workspace admin, set client.auth cookies, return client
    _register_and_login(
        client,
        organization_name="Settings Ai Import Org",
        email="settings-ai-admin@example.test",
    )
    return client


def test_ai_import_settings_defaults(client):
    c = _admin_client(client)
    response = c.get("/v1/settings/ai-import")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_summary_enabled"] is True
    assert body["auto_score_enabled"] is True
    assert body["trigger_manual_upload"] is True
    assert body["trigger_mailbox_import"] is True
    assert body["score_template_ids"] == []


def test_ai_import_settings_require_admin(client):
    # A registered workspace owner is an admin by default, so demote the
    # second account's membership to recruiter before asserting the admin-only
    # gate rejects it.
    _register_and_login(
        client,
        organization_name="Settings Ai Require Admin Org",
        email="settings-ai-require-admin@example.test",
    )
    member = _register_and_login(
        client,
        organization_name="Settings Ai Recruiter Org",
        email="settings-ai-recruiter@example.test",
    )
    user_id = member["user"]["user_id"]
    organization_id = member["organization"]["organization_id"]
    with client.app.state.database.session_factory() as session:
        membership = session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == organization_id,
            )
        )
        assert membership is not None
        membership.role = "recruiter"
        session.commit()
    assert client.post("/v1/auth/logout").status_code == 204
    logged_in = client.post(
        "/v1/auth/login",
        json={
            "email": "settings-ai-recruiter@example.test",
            "password": "candidate-data-lifecycle-test-password",
        },
    )
    assert logged_in.status_code == 200, logged_in.text
    response = client.get("/v1/settings/ai-import")
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "organization_admin_required"


def test_ai_import_settings_toggle_and_persist(client):
    c = _admin_client(client)
    response = c.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": False,
            "auto_score_enabled": False,
            "score_template_ids": [],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_summary_enabled"] is False
    assert body["trigger_mailbox_import"] is False
    # persisted across reads
    again = c.get("/v1/settings/ai-import")
    assert again.json()["auto_summary_enabled"] is False


def test_ai_import_settings_auto_score_requires_template(client):
    c = _admin_client(client)
    response = c.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "score_template_ids": [],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "score_template_required"


def test_ai_import_settings_rejects_foreign_template(client):
    _register_and_login(
        client,
        organization_name="Settings Ai Import Org",
        email="settings-ai-admin@example.test",
    )
    other_org = _register_and_login(
        client,
        organization_name="Settings Ai Template Foreign Org",
        email="settings-ai-template-foreign@example.test",
    )
    other_org_id = other_org["organization"]["organization_id"]
    with client.app.state.database.session_factory() as session:
        set_organization_context(session, other_org_id)
        template = ScoreTemplate(name="Foreign template", version=1)
        session.add(template)
        session.commit()
        foreign_template_id = template.id

    # Re-login as the original admin and try to use the foreign template.
    assert client.post("/v1/auth/logout").status_code == 204
    logged_in = client.post(
        "/v1/auth/login",
        json={
            "email": "settings-ai-admin@example.test",
            "password": "candidate-data-lifecycle-test-password",
        },
    )
    assert logged_in.status_code == 200, logged_in.text

    foreign = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "score_template_ids": [foreign_template_id],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert foreign.status_code == 422, foreign.text
    assert foreign.json()["detail"] == "score_template_not_found"

    unknown = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "score_template_ids": ["00000000-0000-4000-8000-000000000000"],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["detail"] == "score_template_not_found"


def test_ai_import_settings_org_isolation(client):
    # workspace A: turn auto summary off
    _register_and_login(
        client,
        organization_name="Settings Ai Isolation Alpha",
        email="settings-ai-alpha@example.test",
    )
    put_a = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": False,
            "auto_score_enabled": False,
            "score_template_ids": [],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert put_a.status_code == 200, put_a.text
    assert put_a.json()["auto_summary_enabled"] is False

    # workspace B starts from defaults; its own write does not touch A
    _register_and_login(
        client,
        organization_name="Settings Ai Isolation Beta",
        email="settings-ai-beta@example.test",
    )
    defaults = client.get("/v1/settings/ai-import")
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()["auto_summary_enabled"] is True

    put_b = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": False,
            "score_template_ids": [],
            "trigger_manual_upload": False,
            "trigger_mailbox_import": True,
        },
    )
    assert put_b.status_code == 200, put_b.text
    assert put_b.json()["trigger_manual_upload"] is False

    # switch back to A and confirm its settings are unchanged
    assert client.post("/v1/auth/logout").status_code == 204
    back_as_a = client.post(
        "/v1/auth/login",
        json={
            "email": "settings-ai-alpha@example.test",
            "password": "candidate-data-lifecycle-test-password",
        },
    )
    assert back_as_a.status_code == 200, back_as_a.text
    refreshed = client.get("/v1/settings/ai-import")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["auto_summary_enabled"] is False
    assert refreshed.json()["trigger_manual_upload"] is True


def test_ai_import_settings_multiple_templates_persist(client):
    registration = _register_and_login(
        client,
        organization_name="Settings Ai Multi Org",
        email="settings-ai-multi@example.test",
    )
    org_id = registration["organization"]["organization_id"]
    with client.app.state.database.session_factory() as session:
        set_organization_context(session, org_id)
        first = ScoreTemplate(name="Multi template A", version=1)
        second = ScoreTemplate(name="Multi template B", version=1)
        session.add_all([first, second])
        session.commit()
        first_id, second_id = first.id, second.id

    response = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "score_template_ids": [first_id, second_id],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["score_template_ids"]) == {first_id, second_id}
    assert set(client.get("/v1/settings/ai-import").json()["score_template_ids"]) == {
        first_id,
        second_id,
    }


def test_ai_import_settings_rejects_duplicate_template(client):
    registration = _register_and_login(
        client,
        organization_name="Settings Ai Duplicate Org",
        email="settings-ai-duplicate@example.test",
    )
    org_id = registration["organization"]["organization_id"]
    with client.app.state.database.session_factory() as session:
        set_organization_context(session, org_id)
        template = ScoreTemplate(name="Duplicate template", version=1)
        session.add(template)
        session.commit()
        template_id = template.id

    response = client.put(
        "/v1/settings/ai-import",
        json={
            "auto_summary_enabled": True,
            "auto_score_enabled": True,
            "score_template_ids": [template_id, template_id],
            "trigger_manual_upload": True,
            "trigger_mailbox_import": True,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "duplicate_score_template"
