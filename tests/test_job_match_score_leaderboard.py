from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import AppSettings
from app.main import create_app
from app.models import ResumeScore, ResumeScoreBatch, ResumeScoreBatchItem
from app.schemas import JobCreate, JobRequirements
from app.services import job_match_batch_service, resume_score_batch_service
from test_filter_mvp_contract import _save_ready_resume
from test_job_service import _create_job
from test_resume_score_batches import _score_output, _template_payload


def _fake_score_provider(**kwargs: object) -> dict[str, object]:
    return _score_output(**kwargs)


@pytest.fixture
def score_batch_workspace_clients(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient]]:
    """Two authenticated workspaces sharing one test database."""

    data_dir = tmp_path / "data"
    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="resume-score-batch-tenant-test-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        deepseek_api_key="resume-score-batch-tenant-test-key",
        deepseek_model="unit-test-model",
        min_text_chars_per_page=20,
    )
    app = create_app(settings)
    with TestClient(app):
        client_a = TestClient(app)
        client_b = TestClient(app)
        try:
            yield client_a, client_b
        finally:
            client_a.close()
            client_b.close()


def test_score_leaderboard_derivation_states(ai_client, monkeypatch) -> None:
    """有分 / 无分 / 生成中 / 无活跃批次四种派生正确。"""

    monkeypatch.setattr(
        "app.services.score_service.score_resume_fact_snapshot",
        _fake_score_provider,
    )
    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, scored_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    _, unscored_resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    # 只对 scored 简历跑评分批次，并跑完，得到一条已完成的分数。
    with database.session_factory() as session:
        resume_score_batch_service.enqueue_resume_score_batch(
            session,
            template_id=template_id,
            settings=ai_client.app.state.settings,
            resume_ids=[scored_resume_id],
        )
        session.commit()

    assert resume_score_batch_service.run_resume_score_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="leaderboard-worker",
    )
    assert not resume_score_batch_service.run_resume_score_batch_worker_once(
        database,
        settings=ai_client.app.state.settings,
        worker_id="leaderboard-worker",
    )

    with database.session_factory() as session:
        board = job_match_batch_service.list_job_version_score_leaderboard(
            session,
            job_version_id=job_version_id,
            template_id=template_id,
        )
        assert board.batch is None
        by_resume = {item.resume_id: item for item in board.items}
        assert set(by_resume) == {scored_resume_id, unscored_resume_id}
        scored = by_resume[scored_resume_id]
        assert scored.score_status == "succeeded"
        assert scored.score_total is not None
        assert scored.score_task_state == "none"
        assert by_resume[unscored_resume_id].score_total is None
        assert by_resume[unscored_resume_id].score_task_state == "none"


def test_score_leaderboard_reports_active_batch_task_state(ai_client) -> None:
    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    with database.session_factory() as session:
        resume_score_batch_service.enqueue_resume_score_batch(
            session,
            template_id=template_id,
            settings=ai_client.app.state.settings,
            resume_ids=[resume_id],
        )
        session.commit()

    with database.session_factory() as session:
        board = job_match_batch_service.list_job_version_score_leaderboard(
            session,
            job_version_id=job_version_id,
            template_id=template_id,
        )
        assert board.batch is not None
        assert board.batch.status == "queued"
        assert board.batch.total_count == 1
        assert board.items[0].score_task_state == "queued"


def test_score_leaderboard_rejects_unknown_job_or_template(ai_client) -> None:
    from app.services.job_service import JobVersionNotFoundError
    from app.services.score_service import ScoreTemplateNotFoundError

    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    with database.session_factory() as session:
        try:
            job_match_batch_service.list_job_version_score_leaderboard(
                session,
                job_version_id="00000000-0000-4000-8000-000000000000",
                template_id=template_id,
            )
        except JobVersionNotFoundError:
            pass
        else:
            raise AssertionError("expected JobVersionNotFoundError")

        try:
            job_match_batch_service.list_job_version_score_leaderboard(
                session,
                job_version_id=job_version_id,
                template_id="00000000-0000-4000-8000-000000000000",
            )
        except ScoreTemplateNotFoundError:
            pass
        else:
            raise AssertionError("expected ScoreTemplateNotFoundError")


def test_match_all_endpoint_with_score_template_id_enqueues_both_batches(
    ai_client,
    monkeypatch,
) -> None:
    from app.models import ResumeScoreBatch

    monkeypatch.setattr(
        "app.services.score_service.score_resume_fact_snapshot",
        _fake_score_provider,
    )

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]

    matched = ai_client.post(
        f"/v1/job-versions/{job_version_id}/match-all",
        json={"score_template_id": template_id},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["status"] == "queued"
    assert matched.json()["total_count"] == 2

    database = ai_client.app.state.database
    with database.session_factory() as session:
        score_batch = session.scalar(
            select(ResumeScoreBatch).where(
                ResumeScoreBatch.template_id == template_id,
                ResumeScoreBatch.status == "queued",
            )
        )
        assert score_batch is not None
        assert score_batch.total_count == 2


def test_match_all_endpoint_without_body_is_backward_compatible(ai_client) -> None:
    from app.models import ResumeScoreBatch

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])

    matched = ai_client.post(f"/v1/job-versions/{job_version_id}/match-all")
    assert matched.status_code == 200, matched.text
    assert matched.json()["total_count"] == 1

    database = ai_client.app.state.database
    with database.session_factory() as session:
        assert session.scalar(select(func.count(ResumeScoreBatch.id))) == 0


def test_score_leaderboard_endpoint_returns_items_and_batch(ai_client) -> None:
    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]

    board = ai_client.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": template_id},
    )
    assert board.status_code == 200, board.text
    payload = board.json()
    assert payload["batch"] is None
    assert len(payload["items"]) == 1
    assert payload["items"][0]["score_task_state"] == "none"


def test_score_leaderboard_is_tenant_isolated(
    score_batch_workspace_clients,
) -> None:
    from app.services import job_service
    from test_resume_score_batch_tenant_isolation import (
        _create_template,
        _register_and_login,
        _seed_ready_resume,
        _workspace,
    )

    client_a, client_b = score_batch_workspace_clients
    organization_a = _register_and_login(
        client_a,
        organization_name="Leaderboard Alpha",
        email="leaderboard-alpha@example.com",
    )
    organization_b = _register_and_login(
        client_b,
        organization_name="Leaderboard Beta",
        email="leaderboard-beta@example.com",
    )
    database = client_a.app.state.database

    with database.session_factory() as session:
        with _workspace(session, organization_a):
            a_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_a,
                label="alpha-ready",
            )
        template_a = _create_template(client_a, name="Alpha template")

        with _workspace(session, organization_a):
            job = job_service.create_job(
                session,
                payload=JobCreate(
                    title="Tenant Backend Engineer",
                    jd_text="Must have Python experience.",
                    requirements=JobRequirements(
                        must_have=["Python experience"]
                    ),
                ),
            )
        session.commit()
    job_version_id = str(job.job_version_id)

    with database.session_factory() as session:
        with _workspace(session, organization_b):
            _seed_ready_resume(
                session,
                organization_id=organization_b,
                label="beta-ready",
            )
        b_template_id = _create_template(client_b, name="Beta template")
        session.commit()

    # A 工作区的评分榜只含 A 的候选，绝不混入 B 的简历。
    board = client_a.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": template_a},
    )
    assert board.status_code == 200, board.text
    assert {item["resume_id"] for item in board.json()["items"]} == {a_resume_id}

    # A 工作区的评分榜看不到 B 的模板（ID 不是通行证）。
    foreign = client_a.get(
        f"/v1/job-versions/{job_version_id}/score-leaderboard",
        params={"template_id": b_template_id},
    )
    assert foreign.status_code == 404, foreign.text


def test_score_leaderboard_ignores_stale_template_version_batch(ai_client) -> None:
    """旧版本批次的活跃项不得让当前模板版本的评分榜显示「生成中」。"""
    from app.models import ScoreTemplate

    source_text = "教育经历 清华大学 计算机 工作经历 Acme Python Engineer 技能 Python SQL"
    _, resume_id = _save_ready_resume(ai_client, source_text=source_text)
    job = _create_job(
        ai_client,
        requirements=JobRequirements(must_have=["Python experience"]),
    )
    job_version_id = str(job["job_version_id"])
    template = ai_client.post("/v1/score-templates", json=_template_payload())
    assert template.status_code == 200, template.text
    template_id = template.json()["template_id"]
    database = ai_client.app.state.database

    # 入队一个 v1 活跃批次后编辑模板，使版本 +1（旧批次保持 active）。
    with database.session_factory() as session:
        resume_score_batch_service.enqueue_resume_score_batch(
            session,
            template_id=template_id,
            settings=ai_client.app.state.settings,
            resume_ids=[resume_id],
        )
        template_row = session.get(ScoreTemplate, template_id)
        assert template_row is not None
        template_row.version += 1
        session.commit()

    with database.session_factory() as session:
        board = job_match_batch_service.list_job_version_score_leaderboard(
            session,
            job_version_id=job_version_id,
            template_id=template_id,
        )
        # 旧版本批次的活跃项不得让行停留在「生成中」，也不得冒出进行中标签。
        assert board.batch is None
        by_resume = {item.resume_id: item for item in board.items}
        assert by_resume[resume_id].score_task_state == "none"
        assert by_resume[resume_id].score_total is None
