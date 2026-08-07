from __future__ import annotations

from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_workspace_ai_import_settings_upgrade_and_downgrade_are_sqlite_safe(
    tmp_path,
) -> None:
    """The additive per-workspace settings table must migrate cleanly on SQLite."""

    database_path = tmp_path / "workspace-ai-import-settings.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config("alembic.ini")
    config.cmd_opts = SimpleNamespace(x=[f"database_url={database_url}"])

    command.upgrade(config, "20260805_0057")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        table_name = "workspace_ai_import_settings"
        assert table_name in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert {
            "id",
            "organization_id",
            "auto_summary_enabled",
            "auto_score_enabled",
            "default_score_template_id",
            "trigger_manual_upload",
            "trigger_mailbox_import",
            "updated_by_user_id",
            "created_at",
            "updated_at",
        }.issubset(columns)
        unique_constraints = inspector.get_unique_constraints(table_name)
        assert "uq_workspace_ai_import_settings_organization" in {
            constraint["name"] for constraint in unique_constraints
        }
    finally:
        engine.dispose()

    command.downgrade(config, "20260805_0057")
    engine = create_engine(database_url)
    try:
        assert "workspace_ai_import_settings" not in inspect(
            engine
        ).get_table_names()
    finally:
        engine.dispose()
