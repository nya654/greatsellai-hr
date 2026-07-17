from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=True,
        min_text_chars_per_page=20,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ai_client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        allow_unauthenticated=True,
        deepseek_api_key="unit-test-key",
        deepseek_model="unit-test-model",
        min_text_chars_per_page=20,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def protected_client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    settings = AppSettings(
        project_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        database_url="sqlite://",
        admin_token="test-admin-token",
        min_text_chars_per_page=20,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
