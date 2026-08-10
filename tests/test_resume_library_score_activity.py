from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import AppSettings
from app.main import create_app
from app.models import ResumeScoreBatchItem
from app.tenant_scope import bypass_organization_scope
from test_resume_score_batch_tenant_isolation import (
    _register_and_login,
    _seed_ready_resume,
)


def _settings(tmp_path: Path) -> AppSettings:
    data_dir = tmp_path / "data"
    return AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="resume-library-score-activity-tenant-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        deepseek_api_key="resume-library-score-activity-test-key",
        deepseek_model="unit-test-model",
        min_text_chars_per_page=20,
    )


@pytest.fixture
def library_workspace_clients(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient]]:
    """Two authenticated workspaces sharing one test database."""

    app = create_app(_settings(tmp_path))
    with TestClient(app):
        client_a = TestClient(app)
        client_b = TestClient(app)
        try:
            yield client_a, client_b
        finally:
            client_a.close()
            client_b.close()


def _template_payload(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "Workspace-scoped library activity fixture.",
        "dimensions": [
            {
                "label": "Skills",
                "weight": 100,
                "guidance": "Use explicit resume facts only.",
            }
        ],
    }


def test_foreign_workspace_score_batch_never_leaks_into_library_activity(
    library_workspace_clients: tuple[TestClient, TestClient],
) -> None:
    client_a, client_b = library_workspace_clients
    organization_a = _register_and_login(
        client_a,
        organization_name="Library Activity Alpha",
        email="library-activity-alpha@example.test",
    )
    organization_b = _register_and_login(
        client_b,
        organization_name="Library Activity Beta",
        email="library-activity-beta@example.test",
    )

    database = client_a.app.state.database
    with database.session_factory() as session:
        resume_a_id, _ = _seed_ready_resume(
            session,
            organization_id=organization_a,
            label="library-alpha-ready",
        )
        resume_b_id, _ = _seed_ready_resume(
            session,
            organization_id=organization_b,
            label="library-beta-ready",
        )
        session.commit()

    template_b = client_b.post(
        "/v1/score-templates",
        json=_template_payload("Beta activity template"),
    )
    assert template_b.status_code == 200, template_b.text
    batch_b = client_b.post(
        f"/v1/score-templates/{template_b.json()['template_id']}/score-all"
    )
    assert batch_b.status_code == 200, batch_b.text
    batch_b_id = batch_b.json()["batch_id"]

    # 把 B 的 item 置为 running，让潜在泄漏最大化。
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            item = session.scalar(
                select(ResumeScoreBatchItem).where(
                    ResumeScoreBatchItem.batch_id == batch_b_id
                )
            )
            assert item is not None
            item.status = "running"
            session.commit()

    library_a = client_a.get("/v1/resume-library")
    assert library_a.status_code == 200, library_a.text
    a_items = library_a.json()["items"]
    assert {item["resume_id"] for item in a_items} == {resume_a_id}
    assert a_items[0]["score_task_state"] == "none"

    library_b = client_b.get("/v1/resume-library")
    assert library_b.status_code == 200, library_b.text
    b_by_resume = {
        item["resume_id"]: item["score_task_state"]
        for item in library_b.json()["items"]
    }
    assert b_by_resume[resume_b_id] == "running"
