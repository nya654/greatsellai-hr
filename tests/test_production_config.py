from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppSettings


def _settings(tmp_path: Path, **overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "project_dir": tmp_path,
        "data_dir": tmp_path / "data",
        "upload_dir": tmp_path / "data" / "uploads",
        "database_url": "postgresql+psycopg://user:pass@db/resume_v3",
        "environment": "production",
        "auto_create_schema": False,
        "seed_registry_on_startup": False,
    }
    values.update(overrides)
    return AppSettings(**values)


def test_production_refuses_sqlite_and_implicit_schema_bootstrap(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="production_requires_postgresql"):
        _settings(tmp_path, database_url="sqlite:///local.db").validate_runtime()
    with pytest.raises(RuntimeError, match="production_must_use_alembic"):
        _settings(tmp_path, auto_create_schema=True).validate_runtime()
    with pytest.raises(RuntimeError, match="production_must_seed_registry"):
        _settings(tmp_path, seed_registry_on_startup=True).validate_runtime()
    with pytest.raises(RuntimeError, match="production_must_not_allow_unauthenticated"):
        _settings(tmp_path, allow_unauthenticated=True).validate_runtime()


def test_production_postgresql_with_explicit_migration_path_is_valid(tmp_path: Path) -> None:
    _settings(tmp_path).validate_runtime()
