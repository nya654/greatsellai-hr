from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.database import Database
from app.models import (
    Candidate,
    Organization,
    Resume,
    ResumeFactSnapshot,
    ResumeScoreBatchItem,
    ScoreTemplate,
    ScoreTemplateDimension,
)
from app.services import resume_score_batch_service
from app.tenant_scope import (
    clear_organization_context,
    set_organization_context,
)


@contextmanager
def _workspace(session: Session, organization_id: str) -> Iterator[None]:
    set_organization_context(session, organization_id)
    try:
        yield
    finally:
        clear_organization_context(session)


def _settings(tmp_path: Path) -> AppSettings:
    data_dir = tmp_path / "data"
    return AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=False,
        session_secret="resume-score-batch-single-test-secret",
        transactional_email_provider="test",
        public_app_url="http://testserver",
        deepseek_api_key="resume-score-batch-single-test-key",
        deepseek_model="unit-test-model",
        min_text_chars_per_page=20,
    )


def _seed_ready_resume(
    session: Session,
    *,
    organization_id: str,
    label: str,
) -> tuple[str, str]:
    """Persist a ready, trusted resume and its current immutable fact snapshot."""

    with _workspace(session, organization_id):
        candidate = Candidate(display_name=f"Candidate {label}")
        session.add(candidate)
        session.flush()
        resume = Resume(
            candidate_id=candidate.id,
            original_filename=f"{label}.pdf",
            storage_key=f"{organization_id}/{label}.pdf",
            sha256=(label * 64)[:64],
            source_page_count=1,
            parsed_page_count=1,
            extraction_status="ready",
            quality_flags=[],
            parser_version="resume-score-batch-single-test",
            raw_text="Synthetic resume used only for single-resume scoping tests.",
            is_active=True,
            facts_version=1,
        )
        session.add(resume)
        session.flush()
        snapshot = ResumeFactSnapshot(
            resume_id=resume.id,
            facts_version=1,
            canonical_facts_json='{"schema_version":"resume_facts.v1","education":[],"experiences":[],"skills":[]}',
            facts_sha256=(f"snapshot-{label}" * 64)[:64],
            source_block_ids=[],
            created_by="single-test",
        )
        session.add(snapshot)
        session.flush()
        return resume.id, snapshot.id


def _scoreable_template(session: Session, *, name: str) -> ScoreTemplate:
    template = ScoreTemplate(name=name, version=1)
    session.add(template)
    session.flush()
    session.add(
        ScoreTemplateDimension(
            template_id=template.id,
            key="skills",
            label="Skills",
            weight=100,
            guidance=None,
            sort_order=0,
        )
    )
    session.flush()
    return template


def test_enqueue_score_batch_scoped_to_single_resume(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Single score batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id

            first_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_id,
                label="scoped-one",
            )
            second_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_id,
                label="scoped-two",
            )

            with _workspace(session, organization_id):
                template = _scoreable_template(
                    session,
                    name="Single resume template",
                )

                response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id=first_resume_id,
                )

                assert response.total_count == 1
                assert response.status == "queued"
                assert response.completed_count == 0
                items = session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.batch_id == response.batch_id
                    )
                ).all()
                assert len(items) == 1
                assert items[0].resume_id == first_resume_id
                assert items[0].resume_id != second_resume_id
                assert items[0].status == "queued"
    finally:
        database.dispose()


def test_enqueue_score_batch_scoped_to_unknown_resume_is_empty(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Empty score batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id

            _seed_ready_resume(
                session,
                organization_id=organization_id,
                label="still-scoreable",
            )

            with _workspace(session, organization_id):
                template = _scoreable_template(
                    session,
                    name="Unknown-resume template",
                )

                response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id="00000000-0000-4000-8000-000000000000",
                )

            assert response.total_count == 0
            assert response.status == "completed"
            assert response.completed_count == 0
            assert response.failed_count == 0
    finally:
        database.dispose()


def test_enqueue_score_batch_scoped_to_foreign_resume_is_empty(
    tmp_path: Path,
) -> None:
    """A cross-organization resume id must not be admitted to the batch."""

    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization_a = Organization(name="Single score batch org A")
            organization_b = Organization(name="Single score batch org B")
            session.add_all((organization_a, organization_b))
            session.flush()
            organization_a_id = organization_a.id
            organization_b_id = organization_b.id

            foreign_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_b_id,
                label="foreign-ready",
            )
            _seed_ready_resume(
                session,
                organization_id=organization_a_id,
                label="local-ready",
            )

            with _workspace(session, organization_a_id):
                template = _scoreable_template(
                    session,
                    name="Foreign-resume template",
                )

                response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id=foreign_resume_id,
                )

            assert response.total_count == 0
            assert response.status == "completed"
            assert response.completed_count == 0
    finally:
        database.dispose()


def test_enqueue_score_batch_scoped_resumes_append_to_active_batch(
    tmp_path: Path,
) -> None:
    """Scoped enqueues attach to the active batch instead of silently dropping.

    The auto-score chain enqueues once per extraction completion.  When a
    scoped enqueue arrives while a batch for the same template is already
    active, the resume must be appended to that batch rather than ignored.
    """
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Append to active batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id

            first_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_id,
                label="append-first",
            )
            second_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_id,
                label="append-second",
            )

            with _workspace(session, organization_id):
                template = _scoreable_template(
                    session,
                    name="Append to active batch template",
                )

                first_response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id=first_resume_id,
                )
                assert first_response.total_count == 1
                assert first_response.status == "queued"
                batch_id = first_response.batch_id

                second_response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id=second_resume_id,
                )
                assert second_response.batch_id == batch_id
                assert second_response.total_count == 2
                # _refresh_batch_progress flips a batch with pending items to
                # "running", which is still claimable by the score worker.
                assert second_response.status == "running"

                items = session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.batch_id == batch_id
                    )
                ).all()
                assert {item.resume_id for item in items} == {
                    first_resume_id,
                    second_resume_id,
                }
                assert {item.status for item in items} == {"queued"}

                third_response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id=first_resume_id,
                )
                assert third_response.batch_id == batch_id
                assert third_response.total_count == 2
                items = session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.batch_id == batch_id
                    )
                ).all()
                assert len(items) == 2
    finally:
        database.dispose()


def test_enqueue_score_batch_scoped_unknown_resume_while_active_batch_returns_existing(
    tmp_path: Path,
) -> None:
    """A non-scoreable scoped resume must not disturb an active batch."""

    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Append-empty org")
            session.add(organization)
            session.flush()
            organization_id = organization.id

            scoreable_resume_id, _ = _seed_ready_resume(
                session,
                organization_id=organization_id,
                label="append-active-scoreable",
            )

            with _workspace(session, organization_id):
                template = _scoreable_template(
                    session,
                    name="Append-empty template",
                )

                first = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id=scoreable_resume_id,
                )
                assert first.total_count == 1
                assert first.status == "queued"

                second = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_id="00000000-0000-4000-8000-000000000000",
                )

                # Returns the existing active batch unchanged: no raise, no
                # item for the unknown resume, aggregate untouched.
                assert second.batch_id == first.batch_id
                assert second.total_count == 1
                assert second.status == "queued"
                items = session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.batch_id == first.batch_id
                    )
                ).all()
                assert len(items) == 1
                assert items[0].resume_id == scoreable_resume_id
    finally:
        database.dispose()


def test_enqueue_score_batch_scoped_to_resume_subset(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Subset score batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id
            first_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="subset-one"
            )
            second_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="subset-two"
            )
            third_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="subset-three"
            )
            with _workspace(session, organization_id):
                template = _scoreable_template(session, name="Subset template")

                response = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id, second_resume_id],
                )

                assert response.status == "queued"
                assert response.total_count == 2
                items = session.scalars(
                    select(ResumeScoreBatchItem).where(
                        ResumeScoreBatchItem.batch_id == response.batch_id
                    )
                ).all()
                assert {item.resume_id for item in items} == {
                    first_resume_id,
                    second_resume_id,
                }
                assert third_resume_id not in {item.resume_id for item in items}
    finally:
        database.dispose()


def test_score_batch_resume_subset_appends_to_active_batch_idempotently(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    database = Database("sqlite://")
    database.create_all()
    try:
        with database.session_factory() as session:
            organization = Organization(name="Subset append score batch org")
            session.add(organization)
            session.flush()
            organization_id = organization.id
            first_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="append-one"
            )
            second_resume_id, _ = _seed_ready_resume(
                session, organization_id=organization_id, label="append-two"
            )
            with _workspace(session, organization_id):
                template = _scoreable_template(session, name="Append template")

                first = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id],
                )
                assert first.total_count == 1

                second = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id, second_resume_id],
                )
                assert second.batch_id == first.batch_id
                assert second.total_count == 2

                # 重复入队同一子集：按 (batch, resume) 唯一约束幂等，不产生重复项。
                third = resume_score_batch_service.enqueue_resume_score_batch(
                    session,
                    template_id=template.id,
                    settings=settings,
                    resume_ids=[first_resume_id],
                )
                assert third.batch_id == first.batch_id
                assert third.total_count == 2
    finally:
        database.dispose()
