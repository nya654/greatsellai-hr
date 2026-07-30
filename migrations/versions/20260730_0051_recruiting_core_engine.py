"""Add versioned recruiting workflows and candidate-job applications.

Revision ID: 20260730_0051
Revises: 20260730_0050
Create Date: 2026-07-30 12:00:00

This migration extends the existing ``jobs`` aggregate.  It deliberately does
not copy resume facts or source text into an application: an application pins
the immutable resume-fact, JD, and workflow revisions that were selected by a
recruiter.  Stage movement remains an append-only, human-authored history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0051"
down_revision: Union[str, Sequence[str], None] = "20260730_0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recruiting_workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_recruiting_workflows_id_organization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_recruiting_workflows_organization_name",
        ),
    )
    op.create_index(
        "ix_recruiting_workflows_organization_id",
        "recruiting_workflows",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_recruiting_workflows_organization_updated",
        "recruiting_workflows",
        ["organization_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "recruiting_workflow_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_id", "organization_id"],
            ["recruiting_workflows.id", "recruiting_workflows.organization_id"],
            name="fk_recruiting_workflow_versions_workflow_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_recruiting_workflow_versions_id_organization",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "version",
            name="uq_recruiting_workflow_version",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_recruiting_workflow_version_positive",
        ),
    )
    op.create_index(
        "ix_recruiting_workflow_versions_organization_id",
        "recruiting_workflow_versions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_recruiting_workflow_versions_workflow_id",
        "recruiting_workflow_versions",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        "ix_recruiting_workflow_versions_status",
        "recruiting_workflow_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_recruiting_workflow_versions_organization_status",
        "recruiting_workflow_versions",
        ["organization_id", "status"],
        unique=False,
    )

    op.create_table(
        "recruiting_workflow_stages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=False),
        sa.Column("stage_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "stage_type",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "organization_id"],
            [
                "recruiting_workflow_versions.id",
                "recruiting_workflow_versions.organization_id",
            ],
            name="fk_recruiting_workflow_stages_version_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_recruiting_workflow_stages_id_organization",
        ),
        sa.UniqueConstraint(
            "workflow_version_id",
            "stage_key",
            name="uq_recruiting_workflow_stage_key",
        ),
        sa.UniqueConstraint(
            "workflow_version_id",
            "sort_order",
            name="uq_recruiting_workflow_stage_order",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_recruiting_workflow_stage_order",
        ),
    )
    op.create_index(
        "ix_recruiting_workflow_stages_organization_id",
        "recruiting_workflow_stages",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_recruiting_workflow_stages_workflow_version_id",
        "recruiting_workflow_stages",
        ["workflow_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_recruiting_workflow_stages_organization_version_order",
        "recruiting_workflow_stages",
        ["organization_id", "workflow_version_id", "sort_order"],
        unique=False,
    )

    _extend_jobs()
    _seed_default_workflows_for_existing_jobs()
    _create_job_applications()
    _create_job_application_stage_transitions()


def _extend_jobs() -> None:
    """Add recruiting controls without rebuilding referenced PostgreSQL jobs.

    SQLite cannot add the two foreign-key/check constraints in place, so it
    uses Alembic's batch rebuild. PostgreSQL has already had several tables
    referencing ``jobs`` before this revision; rebuilding that table would
    require dropping it and therefore break the upgrade. Use native ALTER
    operations everywhere except SQLite.
    """

    if _uses_sqlite_batch_rebuild():
        with op.batch_alter_table("jobs", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "recruiting_status",
                    sa.String(length=32),
                    nullable=False,
                    server_default=sa.text("'open'"),
                )
            )
            batch_op.add_column(sa.Column("department", sa.String(length=120), nullable=True))
            batch_op.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
            batch_op.add_column(
                sa.Column(
                    "hc_total",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )
            batch_op.add_column(
                sa.Column(
                    "recruiting_workflow_version_id",
                    sa.String(length=36),
                    nullable=True,
                )
            )
            batch_op.create_foreign_key(
                "fk_jobs_owner_user",
                "user_accounts",
                ["owner_user_id"],
                ["id"],
            )
            batch_op.create_foreign_key(
                "fk_jobs_recruiting_workflow_version_organization",
                "recruiting_workflow_versions",
                ["recruiting_workflow_version_id", "organization_id"],
                ["id", "organization_id"],
                ondelete="RESTRICT",
            )
            batch_op.create_check_constraint("ck_jobs_hc_total_positive", "hc_total >= 1")
    else:
        op.add_column(
            "jobs",
            sa.Column(
                "recruiting_status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'open'"),
            )
        )
        op.add_column("jobs", sa.Column("department", sa.String(length=120), nullable=True))
        op.add_column("jobs", sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        op.add_column(
            "jobs",
            sa.Column(
                "hc_total",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        op.add_column(
            "jobs",
            sa.Column(
                "recruiting_workflow_version_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        op.create_foreign_key(
            "fk_jobs_owner_user",
            "jobs",
            "user_accounts",
            ["owner_user_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_jobs_recruiting_workflow_version_organization",
            "jobs",
            "recruiting_workflow_versions",
            ["recruiting_workflow_version_id", "organization_id"],
            ["id", "organization_id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint("ck_jobs_hc_total_positive", "jobs", "hc_total >= 1")

    # Existing published JDs remain usable in the regular job workspace.  The
    # model default is also open; this explicit update makes the intent robust
    # across engines that materialize a new default during a table rebuild.
    op.execute(
        sa.text(
            "UPDATE jobs SET recruiting_status = 'open' "
            "WHERE kind = 'job'"
        )
    )

    for index_name, columns in (
        ("ix_jobs_recruiting_status", ["recruiting_status"]),
        ("ix_jobs_owner_user_id", ["owner_user_id"]),
        (
            "ix_jobs_recruiting_workflow_version_id",
            ["recruiting_workflow_version_id"],
        ),
        (
            "ix_jobs_organization_recruiting_status",
            ["organization_id", "recruiting_status"],
        ),
        ("ix_jobs_organization_owner_user", ["organization_id", "owner_user_id"]),
        (
            "ix_jobs_organization_recruiting_workflow",
            ["organization_id", "recruiting_workflow_version_id"],
        ),
    ):
        op.create_index(index_name, "jobs", columns, unique=False)


def _uses_sqlite_batch_rebuild() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _seed_default_workflows_for_existing_jobs() -> None:
    """Bind legacy recruiting jobs to a published, immutable default flow.

    This is deliberately a data migration instead of a lazy read-path
    fallback.  After upgrade, every existing ordinary Job has the same
    workflow-version guarantee as a newly created one; applications can
    therefore snapshot a version without silently changing a live process.
    """

    bind = op.get_bind()
    organization_ids = bind.execute(
        sa.text(
            "SELECT DISTINCT organization_id FROM jobs "
            "WHERE kind = 'job' AND recruiting_workflow_version_id IS NULL"
        )
    ).scalars().all()
    if not organization_ids:
        return

    workflows = sa.table(
        "recruiting_workflows",
        sa.column("id", sa.String(length=36)),
        sa.column("organization_id", sa.String(length=36)),
        sa.column("name", sa.String(length=120)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    workflow_versions = sa.table(
        "recruiting_workflow_versions",
        sa.column("id", sa.String(length=36)),
        sa.column("organization_id", sa.String(length=36)),
        sa.column("workflow_id", sa.String(length=36)),
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String(length=32)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )
    stages = sa.table(
        "recruiting_workflow_stages",
        sa.column("id", sa.String(length=36)),
        sa.column("organization_id", sa.String(length=36)),
        sa.column("workflow_version_id", sa.String(length=36)),
        sa.column("stage_key", sa.String(length=64)),
        sa.column("name", sa.String(length=120)),
        sa.column("stage_type", sa.String(length=32)),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    default_stages = (
        ("pending_screen", "待筛选", "active", 10),
        ("initial_screen", "初筛", "active", 20),
        ("interview", "面试", "active", 30),
        ("final_interview", "复试", "active", 40),
        ("offer", "Offer", "active", 50),
        ("hired", "已录用", "hired", 90),
        ("rejected", "已淘汰", "rejected", 100),
    )
    now = datetime.now(timezone.utc)
    for organization_id in organization_ids:
        workflow_id = str(uuid4())
        workflow_version_id = str(uuid4())
        bind.execute(
            workflows.insert().values(
                id=workflow_id,
                organization_id=organization_id,
                name="默认招聘流程",
                created_at=now,
                updated_at=now,
            )
        )
        bind.execute(
            workflow_versions.insert().values(
                id=workflow_version_id,
                organization_id=organization_id,
                workflow_id=workflow_id,
                version=1,
                status="published",
                created_at=now,
                published_at=now,
            )
        )
        bind.execute(
            stages.insert(),
            [
                {
                    "id": str(uuid4()),
                    "organization_id": organization_id,
                    "workflow_version_id": workflow_version_id,
                    "stage_key": stage_key,
                    "name": name,
                    "stage_type": stage_type,
                    "sort_order": sort_order,
                    "created_at": now,
                }
                for stage_key, name, stage_type, sort_order in default_stages
            ],
        )
        bind.execute(
            sa.text(
                "UPDATE jobs SET recruiting_workflow_version_id = :workflow_version_id "
                "WHERE organization_id = :organization_id "
                "AND kind = 'job' AND recruiting_workflow_version_id IS NULL"
            ),
            {
                "organization_id": organization_id,
                "workflow_version_id": workflow_version_id,
            },
        )


def _create_job_applications() -> None:
    op.create_table(
        "job_applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("resume_fact_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("resume_facts_version", sa.Integer(), nullable=False),
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("job_version_number", sa.Integer(), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_version_number", sa.Integer(), nullable=False),
        sa.Column("current_stage_id", sa.String(length=36), nullable=False),
        sa.Column("current_stage_key", sa.String(length=64), nullable=False),
        sa.Column("current_stage_name", sa.String(length=120), nullable=False),
        sa.Column("current_stage_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "round_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("added_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.ForeignKeyConstraint(
            ["resume_fact_snapshot_id"],
            ["resume_fact_snapshots.id"],
        ),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["user_accounts.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "organization_id"],
            [
                "recruiting_workflow_versions.id",
                "recruiting_workflow_versions.organization_id",
            ],
            name="fk_job_applications_workflow_version_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_stage_id", "organization_id"],
            [
                "recruiting_workflow_stages.id",
                "recruiting_workflow_stages.organization_id",
            ],
            name="fk_job_applications_current_stage_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_job_applications_id_organization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "job_id",
            "candidate_id",
            "round_number",
            name="uq_job_application_round",
        ),
        sa.CheckConstraint(
            "round_number >= 1",
            name="ck_job_applications_round_positive",
        ),
        sa.CheckConstraint(
            "resume_facts_version >= 0",
            name="ck_job_applications_resume_facts_version",
        ),
        sa.CheckConstraint(
            "job_version_number >= 1",
            name="ck_job_applications_job_version_positive",
        ),
        sa.CheckConstraint(
            "workflow_version_number >= 1",
            name="ck_job_applications_workflow_version_positive",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_job_applications_state_version_positive",
        ),
    )
    for index_name, columns in (
        ("ix_job_applications_organization_id", ["organization_id"]),
        ("ix_job_applications_job_id", ["job_id"]),
        ("ix_job_applications_candidate_id", ["candidate_id"]),
        ("ix_job_applications_resume_id", ["resume_id"]),
        (
            "ix_job_applications_resume_fact_snapshot_id",
            ["resume_fact_snapshot_id"],
        ),
        ("ix_job_applications_job_version_id", ["job_version_id"]),
        ("ix_job_applications_workflow_version_id", ["workflow_version_id"]),
        ("ix_job_applications_current_stage_id", ["current_stage_id"]),
        ("ix_job_applications_status", ["status"]),
        ("ix_job_applications_is_current", ["is_current"]),
        ("ix_job_applications_added_by_user_id", ["added_by_user_id"]),
        (
            "ix_job_applications_organization_job_stage",
            ["organization_id", "job_id", "current_stage_id"],
        ),
        (
            "ix_job_applications_organization_candidate_created",
            ["organization_id", "candidate_id", "created_at"],
        ),
        (
            "ix_job_applications_organization_resume",
            ["organization_id", "resume_id"],
        ),
    ):
        op.create_index(index_name, "job_applications", columns, unique=False)
    op.create_index(
        "uq_current_job_application_candidate",
        "job_applications",
        ["organization_id", "job_id", "candidate_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current = true"),
    )


def _create_job_application_stage_transitions() -> None:
    op.create_table(
        "job_application_stage_transitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("state_version_after", sa.Integer(), nullable=False),
        sa.Column("from_stage_id", sa.String(length=36), nullable=True),
        sa.Column("from_stage_key", sa.String(length=64), nullable=True),
        sa.Column("from_stage_name", sa.String(length=120), nullable=True),
        sa.Column("from_stage_type", sa.String(length=32), nullable=True),
        sa.Column("to_stage_id", sa.String(length=36), nullable=False),
        sa.Column("to_stage_key", sa.String(length=64), nullable=False),
        sa.Column("to_stage_name", sa.String(length=120), nullable=False),
        sa.Column("to_stage_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["application_id", "organization_id"],
            ["job_applications.id", "job_applications.organization_id"],
            name="fk_job_application_stage_transitions_application_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "state_version_after",
            name="uq_job_application_stage_transition_version",
        ),
        sa.CheckConstraint(
            "state_version_after >= 1",
            name="ck_job_application_stage_transition_version_positive",
        ),
    )
    for index_name, columns in (
        (
            "ix_job_application_stage_transitions_organization_id",
            ["organization_id"],
        ),
        (
            "ix_job_application_stage_transitions_application_id",
            ["application_id"],
        ),
        (
            "ix_job_application_stage_transitions_actor_user_id",
            ["actor_user_id"],
        ),
        (
            "ix_job_application_transition_org_app_version",
            ["organization_id", "application_id", "state_version_after"],
        ),
    ):
        op.create_index(
            index_name,
            "job_application_stage_transitions",
            columns,
            unique=False,
        )


def downgrade() -> None:
    for index_name in (
        "ix_job_application_transition_org_app_version",
        "ix_job_application_stage_transitions_actor_user_id",
        "ix_job_application_stage_transitions_application_id",
        "ix_job_application_stage_transitions_organization_id",
    ):
        op.drop_index(index_name, table_name="job_application_stage_transitions")
    op.drop_table("job_application_stage_transitions")

    op.drop_index(
        "uq_current_job_application_candidate",
        table_name="job_applications",
    )
    for index_name in (
        "ix_job_applications_organization_resume",
        "ix_job_applications_organization_candidate_created",
        "ix_job_applications_organization_job_stage",
        "ix_job_applications_added_by_user_id",
        "ix_job_applications_is_current",
        "ix_job_applications_status",
        "ix_job_applications_current_stage_id",
        "ix_job_applications_workflow_version_id",
        "ix_job_applications_job_version_id",
        "ix_job_applications_resume_fact_snapshot_id",
        "ix_job_applications_resume_id",
        "ix_job_applications_candidate_id",
        "ix_job_applications_job_id",
        "ix_job_applications_organization_id",
    ):
        op.drop_index(index_name, table_name="job_applications")
    op.drop_table("job_applications")

    _downgrade_jobs()

    op.drop_index(
        "ix_recruiting_workflow_stages_organization_version_order",
        table_name="recruiting_workflow_stages",
    )
    op.drop_index(
        "ix_recruiting_workflow_stages_workflow_version_id",
        table_name="recruiting_workflow_stages",
    )
    op.drop_index(
        "ix_recruiting_workflow_stages_organization_id",
        table_name="recruiting_workflow_stages",
    )
    op.drop_table("recruiting_workflow_stages")

    op.drop_index(
        "ix_recruiting_workflow_versions_organization_status",
        table_name="recruiting_workflow_versions",
    )
    op.drop_index(
        "ix_recruiting_workflow_versions_status",
        table_name="recruiting_workflow_versions",
    )
    op.drop_index(
        "ix_recruiting_workflow_versions_workflow_id",
        table_name="recruiting_workflow_versions",
    )
    op.drop_index(
        "ix_recruiting_workflow_versions_organization_id",
        table_name="recruiting_workflow_versions",
    )
    op.drop_table("recruiting_workflow_versions")

    op.drop_index(
        "ix_recruiting_workflows_organization_updated",
        table_name="recruiting_workflows",
    )
    op.drop_index(
        "ix_recruiting_workflows_organization_id",
        table_name="recruiting_workflows",
    )
    op.drop_table("recruiting_workflows")


def _downgrade_jobs() -> None:
    """Remove Job controls without rebuilding referenced PostgreSQL jobs."""

    for index_name in (
        "ix_jobs_organization_recruiting_workflow",
        "ix_jobs_organization_owner_user",
        "ix_jobs_organization_recruiting_status",
        "ix_jobs_recruiting_workflow_version_id",
        "ix_jobs_owner_user_id",
        "ix_jobs_recruiting_status",
    ):
        op.drop_index(index_name, table_name="jobs")
    if _uses_sqlite_batch_rebuild():
        with op.batch_alter_table("jobs", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "fk_jobs_recruiting_workflow_version_organization",
                type_="foreignkey",
            )
            batch_op.drop_constraint("fk_jobs_owner_user", type_="foreignkey")
            batch_op.drop_constraint("ck_jobs_hc_total_positive", type_="check")
            batch_op.drop_column("recruiting_workflow_version_id")
            batch_op.drop_column("hc_total")
            batch_op.drop_column("owner_user_id")
            batch_op.drop_column("department")
            batch_op.drop_column("recruiting_status")
    else:
        op.drop_constraint(
            "fk_jobs_recruiting_workflow_version_organization",
            "jobs",
            type_="foreignkey",
        )
        op.drop_constraint("fk_jobs_owner_user", "jobs", type_="foreignkey")
        op.drop_constraint("ck_jobs_hc_total_positive", "jobs", type_="check")
        op.drop_column("jobs", "recruiting_workflow_version_id")
        op.drop_column("jobs", "hc_total")
        op.drop_column("jobs", "owner_user_id")
        op.drop_column("jobs", "department")
        op.drop_column("jobs", "recruiting_status")
