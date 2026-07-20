"""Add tenant identity, plans, and workspace-scoped business roots.

Revision ID: 20260720_0013
Revises: 20260720_0012
Create Date: 2026-07-20 16:00:00

The migration deliberately does not inspect environment variables, files, or
candidate content.  It creates one durable legacy workspace and attaches every
pre-existing tenant-owned record to it before making the new foreign keys
non-null.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0013"
down_revision: Union[str, Sequence[str], None] = "20260720_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000001"
LEGACY_USER_ID = "00000000-0000-4000-8000-000000000002"
LEGACY_MEMBERSHIP_ID = "00000000-0000-4000-8000-000000000003"
PLAN_BASIC_ID = "00000000-0000-4000-8000-000000000101"
PLAN_ADVANCED_ID = "00000000-0000-4000-8000-000000000102"
PLAN_PROFESSIONAL_ID = "00000000-0000-4000-8000-000000000103"


# These are records that may be loaded without joining their parent resume,
# job, template, or mailbox configuration.  The session-level tenant guard
# can safely apply one criterion to every one of them.
SCOPED_TABLES = (
    "candidates",
    "resumes",
    "resume_upload_idempotency_keys",
    "mailbox_configs",
    "email_attachment_imports",
    "resume_ai_extraction_jobs",
    "resume_fact_snapshots",
    "saved_filters",
    "score_templates",
    "resume_scores",
    "resume_summaries",
    "jobs",
    "job_versions",
    "job_matches",
    "job_match_batches",
    "job_match_batch_items",
)

SPECIAL_REBUILT_TABLES = {
    "resume_upload_idempotency_keys",
    "saved_filters",
    "score_templates",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_identity_tables() -> None:
    op.create_table(
        "product_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("monthly_price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("trial_days", sa.Integer(), nullable=False),
        sa.Column("feature_flags", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_available_for_signup", sa.Boolean(), nullable=False),
        sa.Column("is_default_trial", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_plans_code", "product_plans", ["code"], unique=True)
    op.create_index("ix_product_plans_is_active", "product_plans", ["is_active"])
    op.create_index("ix_product_plans_is_default_trial", "product_plans", ["is_default_trial"])
    op.create_index(
        "ix_product_plans_signup_order",
        "product_plans",
        ["is_available_for_signup", "sort_order"],
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=True),
        sa.Column("plan_status", sa.String(length=32), nullable=False),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["product_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_plan_id", "organizations", ["plan_id"])
    op.create_index("ix_organizations_plan_status", "organizations", ["plan_status"])
    op.create_index(
        "ix_organizations_plan_status_trial_ends",
        "organizations",
        ["plan_status", "trial_ends_at"],
    )

    op.create_table(
        "user_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_key", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_accounts_email_key", "user_accounts", ["email_key"], unique=True)
    op.create_index("ix_user_accounts_is_active", "user_accounts", ["is_active"])
    op.create_index("ix_user_accounts_is_platform_admin", "user_accounts", ["is_platform_admin"])

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_membership"),
    )
    op.create_index("ix_organization_memberships_organization_id", "organization_memberships", ["organization_id"])
    op.create_index("ix_organization_memberships_user_id", "organization_memberships", ["user_id"])
    op.create_index("ix_organization_memberships_role", "organization_memberships", ["role"])
    op.create_index("ix_organization_memberships_is_active", "organization_memberships", ["is_active"])
    op.create_index(
        "ix_organization_memberships_user_active",
        "organization_memberships",
        ["user_id", "is_active"],
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("email_key", sa.String(length=320), nullable=True),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["user_accounts.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"])
    op.create_index("ix_organization_invitations_email_key", "organization_invitations", ["email_key"])
    op.create_index("ix_organization_invitations_token_digest", "organization_invitations", ["token_digest"], unique=True)
    op.create_index("ix_organization_invitations_expires_at", "organization_invitations", ["expires_at"])
    op.create_index("ix_organization_invitations_accepted_by_user_id", "organization_invitations", ["accepted_by_user_id"])
    op.create_index("ix_organization_invitations_created_by_user_id", "organization_invitations", ["created_by_user_id"])
    op.create_index(
        "ix_organization_invitations_org_expiry",
        "organization_invitations",
        ["organization_id", "expires_at"],
    )
    op.create_index(
        "ix_organization_invitations_email_expiry",
        "organization_invitations",
        ["email_key", "expires_at"],
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_digest", "password_reset_tokens", ["token_digest"], unique=True)
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
    op.create_index(
        "ix_password_reset_tokens_user_requested",
        "password_reset_tokens",
        ["user_id", "requested_at"],
    )
    op.create_index("ix_password_reset_tokens_expiry", "password_reset_tokens", ["expires_at"])


def _seed_plans_and_legacy_workspace() -> None:
    now = _utcnow()
    product_plans = sa.table(
        "product_plans",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("monthly_price_cents", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("trial_days", sa.Integer()),
        sa.column("feature_flags", sa.JSON()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_available_for_signup", sa.Boolean()),
        sa.column("is_default_trial", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    shared_flags = {
        "resume_library": True,
        "candidate_filtering": True,
        "ai_scoring": True,
        "ai_summary": True,
        "jd_matching": True,
        "recruiting_agent": True,
    }
    op.bulk_insert(
        product_plans,
        [
            {
                "id": PLAN_BASIC_ID,
                "code": "basic",
                "name": "基础版",
                "monthly_price_cents": 0,
                "currency": "CNY",
                "trial_days": 30,
                "feature_flags": {**shared_flags, "mailbox_import": False, "ai_jd_generation": False, "interview_questions": False, "interview_records": False, "hrbp_reference": False},
                "is_active": True,
                "is_available_for_signup": True,
                "is_default_trial": False,
                "sort_order": 10,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PLAN_ADVANCED_ID,
                "code": "advanced",
                "name": "进阶版",
                "monthly_price_cents": 0,
                "currency": "CNY",
                "trial_days": 30,
                "feature_flags": {**shared_flags, "mailbox_import": True, "ai_jd_generation": True, "interview_questions": False, "interview_records": False, "hrbp_reference": False},
                "is_active": True,
                "is_available_for_signup": True,
                "is_default_trial": True,
                "sort_order": 20,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PLAN_PROFESSIONAL_ID,
                "code": "professional",
                "name": "专业版",
                "monthly_price_cents": 0,
                "currency": "CNY",
                "trial_days": 30,
                "feature_flags": {**shared_flags, "mailbox_import": True, "ai_jd_generation": True, "interview_questions": False, "interview_records": False, "hrbp_reference": False},
                "is_active": True,
                "is_available_for_signup": True,
                "is_default_trial": False,
                "sort_order": 30,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    organizations = sa.table(
        "organizations",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("plan_id", sa.String()),
        sa.column("plan_status", sa.String()),
        sa.column("trial_started_at", sa.DateTime(timezone=True)),
        sa.column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        organizations,
        [
            {
                "id": LEGACY_ORGANIZATION_ID,
                "name": "Legacy workspace",
                "plan_id": PLAN_ADVANCED_ID,
                "plan_status": "active",
                "trial_started_at": None,
                "trial_ends_at": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    user_accounts = sa.table(
        "user_accounts",
        sa.column("id", sa.String()),
        sa.column("email", sa.String()),
        sa.column("email_key", sa.String()),
        sa.column("full_name", sa.String()),
        sa.column("password_hash", sa.Text()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_platform_admin", sa.Boolean()),
        sa.column("email_verified_at", sa.DateTime(timezone=True)),
        sa.column("last_login_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        user_accounts,
        [
            {
                "id": LEGACY_USER_ID,
                "email": "legacy-admin@system.invalid",
                "email_key": "legacy-admin@system.invalid",
                "full_name": "Legacy Administrator",
                # This is intentionally not a usable password hash.  The
                # existing single-admin compatibility login remains outside
                # this migration and is mapped to this identity by the app.
                "password_hash": "!legacy-configuration-authentication!",
                "is_active": True,
                "is_platform_admin": True,
                "email_verified_at": None,
                "last_login_at": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    memberships = sa.table(
        "organization_memberships",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("user_id", sa.String()),
        sa.column("role", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        memberships,
        [
            {
                "id": LEGACY_MEMBERSHIP_ID,
                "organization_id": LEGACY_ORGANIZATION_ID,
                "user_id": LEGACY_USER_ID,
                "role": "admin",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def _add_and_backfill_organization_columns() -> None:
    for table_name in SCOPED_TABLES:
        op.add_column(
            table_name,
            sa.Column("organization_id", sa.String(length=36), nullable=True),
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET organization_id = :organization_id "
                "WHERE organization_id IS NULL"
            ).bindparams(organization_id=LEGACY_ORGANIZATION_ID)
        )


def _make_regular_scoped_tables_strict(dialect_name: str) -> None:
    for table_name in SCOPED_TABLES:
        if table_name in SPECIAL_REBUILT_TABLES:
            continue
        foreign_key_name = f"fk_{table_name}_organization_id"
        if dialect_name == "sqlite":
            with op.batch_alter_table(table_name, recreate="always") as batch_op:
                batch_op.alter_column(
                    "organization_id",
                    existing_type=sa.String(length=36),
                    nullable=False,
                )
                batch_op.create_foreign_key(
                    foreign_key_name,
                    "organizations",
                    ["organization_id"],
                    ["id"],
                )
        else:
            op.alter_column(
                table_name,
                "organization_id",
                existing_type=sa.String(length=36),
                nullable=False,
            )
            op.create_foreign_key(
                foreign_key_name,
                table_name,
                "organizations",
                ["organization_id"],
                ["id"],
            )


def _sqlite_rebuild_special_scoped_tables() -> None:
    metadata = sa.MetaData()

    saved_filters = sa.Table(
        "saved_filters",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_saved_filters_organization_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_saved_filter_organization_name",
        ),
    )
    with op.batch_alter_table(
        "saved_filters",
        recreate="always",
        copy_from=saved_filters,
    ):
        pass

    score_templates = sa.Table(
        "score_templates",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_score_templates_organization_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_score_template_organization_name",
        ),
    )
    with op.batch_alter_table(
        "score_templates",
        recreate="always",
        copy_from=score_templates,
    ):
        pass

    upload_keys = sa.Table(
        "resume_upload_idempotency_keys",
        metadata,
        sa.Column("organization_id", sa.String(length=36), primary_key=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), primary_key=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_resume_upload_idempotency_keys_organization_id",
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.UniqueConstraint("resume_id", name="uq_resume_upload_idempotency_resume"),
    )
    with op.batch_alter_table(
        "resume_upload_idempotency_keys",
        recreate="always",
        copy_from=upload_keys,
    ):
        pass


def _drop_unique_constraints_for_columns(table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    for constraint in sa.inspect(bind).get_unique_constraints(table_name):
        if constraint.get("column_names") == columns and constraint.get("name"):
            op.drop_constraint(constraint["name"], table_name, type_="unique")


def _make_special_scoped_tables_strict(dialect_name: str) -> None:
    if dialect_name == "sqlite":
        _sqlite_rebuild_special_scoped_tables()
        return

    for table_name in SPECIAL_REBUILT_TABLES:
        op.alter_column(
            table_name,
            "organization_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        op.create_foreign_key(
            f"fk_{table_name}_organization_id",
            table_name,
            "organizations",
            ["organization_id"],
            ["id"],
        )

    _drop_unique_constraints_for_columns("saved_filters", ["name"])
    op.create_unique_constraint(
        "uq_saved_filter_organization_name",
        "saved_filters",
        ["organization_id", "name"],
    )
    _drop_unique_constraints_for_columns("score_templates", ["name"])
    op.create_unique_constraint(
        "uq_score_template_organization_name",
        "score_templates",
        ["organization_id", "name"],
    )

    bind = op.get_bind()
    primary_key = sa.inspect(bind).get_pk_constraint("resume_upload_idempotency_keys")
    if primary_key.get("name"):
        op.drop_constraint(
            primary_key["name"],
            "resume_upload_idempotency_keys",
            type_="primary",
        )
    op.create_primary_key(
        "pk_resume_upload_idempotency_keys",
        "resume_upload_idempotency_keys",
        ["organization_id", "idempotency_key_hash"],
    )


def _create_scoped_indexes() -> None:
    for table_name in SCOPED_TABLES:
        if table_name == "resume_upload_idempotency_keys":
            continue
        op.create_index(
            f"ix_{table_name}_organization_id",
            table_name,
            ["organization_id"],
        )

    op.create_index("ix_candidates_organization_created", "candidates", ["organization_id", "created_at"])
    op.create_index("ix_resumes_organization_created", "resumes", ["organization_id", "created_at"])
    op.create_index("ix_resumes_organization_candidate", "resumes", ["organization_id", "candidate_id"])
    op.create_index(
        "ix_resume_upload_idempotency_keys_organization_created",
        "resume_upload_idempotency_keys",
        ["organization_id", "created_at"],
    )
    op.create_index("ix_mailbox_configs_organization_enabled", "mailbox_configs", ["organization_id", "enabled"])
    op.create_index(
        "ix_email_attachment_imports_organization_created",
        "email_attachment_imports",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_resume_ai_extraction_job_organization_claim",
        "resume_ai_extraction_jobs",
        ["organization_id", "status", "next_attempt_at"],
    )
    op.create_index(
        "ix_resume_fact_snapshot_organization_created",
        "resume_fact_snapshots",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_score_templates_organization_archived",
        "score_templates",
        ["organization_id", "is_archived"],
    )
    op.create_index(
        "ix_resume_summaries_organization_created",
        "resume_summaries",
        ["organization_id", "created_at"],
    )
    op.create_index("ix_jobs_organization_updated", "jobs", ["organization_id", "updated_at"])
    op.create_index(
        "ix_job_versions_organization_status",
        "job_versions",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_job_matches_organization_created",
        "job_matches",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_job_matches_organization_job",
        "job_matches",
        ["organization_id", "job_id"],
    )
    op.create_index(
        "ix_job_match_batches_organization_claim",
        "job_match_batches",
        ["organization_id", "status", "lease_expires_at"],
    )
    op.create_index(
        "ix_job_match_batch_item_organization_claim",
        "job_match_batch_items",
        ["organization_id", "status", "next_attempt_at"],
    )


def upgrade() -> None:
    _create_identity_tables()
    _seed_plans_and_legacy_workspace()
    _add_and_backfill_organization_columns()

    dialect_name = op.get_bind().dialect.name
    _make_regular_scoped_tables_strict(dialect_name)
    _make_special_scoped_tables_strict(dialect_name)
    _create_scoped_indexes()


def _drop_scoped_indexes() -> None:
    index_names = (
        "ix_job_match_batch_item_organization_claim",
        "ix_job_match_batches_organization_claim",
        "ix_job_matches_organization_job",
        "ix_job_matches_organization_created",
        "ix_job_versions_organization_status",
        "ix_jobs_organization_updated",
        "ix_resume_summaries_organization_created",
        "ix_score_templates_organization_archived",
        "ix_resume_fact_snapshot_organization_created",
        "ix_resume_ai_extraction_job_organization_claim",
        "ix_email_attachment_imports_organization_created",
        "ix_mailbox_configs_organization_enabled",
        "ix_resume_upload_idempotency_keys_organization_created",
        "ix_resumes_organization_candidate",
        "ix_resumes_organization_created",
        "ix_candidates_organization_created",
    )
    for index_name in index_names:
        table_name = _table_name_for_index(index_name)
        op.drop_index(index_name, table_name=table_name)
    for table_name in SCOPED_TABLES:
        if table_name == "resume_upload_idempotency_keys":
            continue
        op.drop_index(f"ix_{table_name}_organization_id", table_name=table_name)


def _table_name_for_index(index_name: str) -> str:
    prefixes = (
        ("ix_job_match_batch_item_", "job_match_batch_items"),
        ("ix_job_match_batches_", "job_match_batches"),
        ("ix_job_matches_", "job_matches"),
        ("ix_job_versions_", "job_versions"),
        ("ix_jobs_", "jobs"),
        ("ix_resume_summaries_", "resume_summaries"),
        ("ix_score_templates_", "score_templates"),
        ("ix_resume_fact_snapshot_", "resume_fact_snapshots"),
        ("ix_resume_ai_extraction_job_", "resume_ai_extraction_jobs"),
        ("ix_email_attachment_imports_", "email_attachment_imports"),
        ("ix_mailbox_configs_", "mailbox_configs"),
        ("ix_resume_upload_idempotency_keys_", "resume_upload_idempotency_keys"),
        ("ix_resumes_", "resumes"),
        ("ix_candidates_", "candidates"),
    )
    for prefix, table_name in prefixes:
        if index_name.startswith(prefix):
            return table_name
    raise RuntimeError(f"unknown scoped index: {index_name}")


def _assert_downgrade_can_restore_global_uniques() -> None:
    bind = op.get_bind()
    duplicate_specs = (
        ("saved_filters", "name"),
        ("score_templates", "name"),
        ("resume_upload_idempotency_keys", "idempotency_key_hash"),
    )
    for table_name, column_name in duplicate_specs:
        duplicate = bind.execute(
            sa.text(
                f"SELECT 1 FROM {table_name} "
                f"GROUP BY {column_name} HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicate is not None:
            raise RuntimeError(
                "tenant migration downgrade would discard a valid cross-workspace "
                f"duplicate in {table_name}.{column_name}; aborting safely"
            )


def _sqlite_rebuild_special_tables_for_downgrade() -> None:
    metadata = sa.MetaData()

    saved_filters = sa.Table(
        "saved_filters",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("saved_filters", recreate="always", copy_from=saved_filters):
        pass

    score_templates = sa.Table(
        "score_templates",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("score_templates", recreate="always", copy_from=score_templates):
        pass

    upload_keys = sa.Table(
        "resume_upload_idempotency_keys",
        metadata,
        sa.Column("idempotency_key_hash", sa.String(length=64), primary_key=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
    )
    with op.batch_alter_table(
        "resume_upload_idempotency_keys",
        recreate="always",
        copy_from=upload_keys,
    ):
        pass


def _drop_organization_columns(dialect_name: str) -> None:
    for table_name in SCOPED_TABLES:
        if table_name in SPECIAL_REBUILT_TABLES:
            continue
        foreign_key_name = f"fk_{table_name}_organization_id"
        if dialect_name == "sqlite":
            with op.batch_alter_table(table_name, recreate="always") as batch_op:
                batch_op.drop_constraint(foreign_key_name, type_="foreignkey")
                batch_op.drop_column("organization_id")
        else:
            op.drop_constraint(foreign_key_name, table_name, type_="foreignkey")
            op.drop_column(table_name, "organization_id")


def _drop_identity_tables() -> None:
    for index_name in (
        "ix_password_reset_tokens_expiry",
        "ix_password_reset_tokens_user_requested",
        "ix_password_reset_tokens_expires_at",
        "ix_password_reset_tokens_token_digest",
        "ix_password_reset_tokens_user_id",
    ):
        op.drop_index(index_name, table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    for index_name in (
        "ix_organization_invitations_email_expiry",
        "ix_organization_invitations_org_expiry",
        "ix_organization_invitations_created_by_user_id",
        "ix_organization_invitations_accepted_by_user_id",
        "ix_organization_invitations_expires_at",
        "ix_organization_invitations_token_digest",
        "ix_organization_invitations_email_key",
        "ix_organization_invitations_organization_id",
    ):
        op.drop_index(index_name, table_name="organization_invitations")
    op.drop_table("organization_invitations")

    for index_name in (
        "ix_organization_memberships_user_active",
        "ix_organization_memberships_is_active",
        "ix_organization_memberships_role",
        "ix_organization_memberships_user_id",
        "ix_organization_memberships_organization_id",
    ):
        op.drop_index(index_name, table_name="organization_memberships")
    op.drop_table("organization_memberships")

    for index_name in (
        "ix_user_accounts_is_platform_admin",
        "ix_user_accounts_is_active",
        "ix_user_accounts_email_key",
    ):
        op.drop_index(index_name, table_name="user_accounts")
    op.drop_table("user_accounts")

    for index_name in (
        "ix_organizations_plan_status_trial_ends",
        "ix_organizations_plan_status",
        "ix_organizations_plan_id",
    ):
        op.drop_index(index_name, table_name="organizations")
    op.drop_table("organizations")

    for index_name in (
        "ix_product_plans_signup_order",
        "ix_product_plans_is_default_trial",
        "ix_product_plans_is_active",
        "ix_product_plans_code",
    ):
        op.drop_index(index_name, table_name="product_plans")
    op.drop_table("product_plans")


def downgrade() -> None:
    _assert_downgrade_can_restore_global_uniques()
    _drop_scoped_indexes()

    dialect_name = op.get_bind().dialect.name
    if dialect_name == "sqlite":
        _sqlite_rebuild_special_tables_for_downgrade()
    else:
        _drop_unique_constraints_for_columns(
            "saved_filters",
            ["organization_id", "name"],
        )
        op.create_unique_constraint(None, "saved_filters", ["name"])
        _drop_unique_constraints_for_columns(
            "score_templates",
            ["organization_id", "name"],
        )
        op.create_unique_constraint(None, "score_templates", ["name"])
        primary_key = sa.inspect(op.get_bind()).get_pk_constraint(
            "resume_upload_idempotency_keys"
        )
        if primary_key.get("name"):
            op.drop_constraint(
                primary_key["name"],
                "resume_upload_idempotency_keys",
                type_="primary",
            )
        op.create_primary_key(
            "resume_upload_idempotency_keys_pkey",
            "resume_upload_idempotency_keys",
            ["idempotency_key_hash"],
        )
        for table_name in SPECIAL_REBUILT_TABLES:
            op.drop_constraint(
                f"fk_{table_name}_organization_id",
                table_name,
                type_="foreignkey",
            )
            op.drop_column(table_name, "organization_id")

    _drop_organization_columns(dialect_name)
    _drop_identity_tables()
