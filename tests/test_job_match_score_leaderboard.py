from __future__ import annotations

from sqlalchemy import select

from app.models import ResumeScore, ResumeScoreBatch, ResumeScoreBatchItem
from app.schemas import JobRequirements
from app.services import job_match_batch_service, resume_score_batch_service
from test_filter_mvp_contract import _save_ready_resume
from test_job_service import _create_job
from test_resume_score_batches import _score_output, _template_payload


def _fake_score_provider(**kwargs: object) -> dict[str, object]:
    return _score_output(**kwargs)


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
