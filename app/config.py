from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _environment_flag(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean environment flag")


@dataclass(frozen=True)
class AppSettings:
    project_dir: Path
    data_dir: Path
    upload_dir: Path
    database_url: str
    environment: str = "development"
    auto_create_schema: bool = True
    seed_registry_on_startup: bool = True
    database_pool_size: int = 5
    database_max_overflow: int = 10
    admin_token: str | None = None
    session_secret: str | None = None
    session_cookie_secure: bool = False
    allow_unauthenticated: bool = False
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: int = 90
    ai_extraction_job_max_attempts: int = 3
    ai_extraction_job_lease_seconds: int = 180
    ai_extraction_worker_poll_seconds: float = 2.0
    mailbox_sync_interval_seconds: float = 600.0
    # This is a per-run message batch, not an unbounded mailbox scan. Each
    # following run resumes older unseen message UIDs after newer ones are
    # recorded, so the worker remains responsive on large mailboxes.
    mailbox_sync_attachment_limit: int = 20
    email_credentials_key: str | None = None
    max_upload_bytes: int = 15 * 1024 * 1024
    min_text_chars_per_page: int = 80
    tencent_secret_id: str | None = None
    tencent_secret_key: str | None = None
    tencent_ocr_region: str = "ap-guangzhou"
    tencent_ocr_timeout_seconds: int = 20
    ocr_sparse_text_chars_per_page: int = 500

    @classmethod
    def from_env(cls) -> "AppSettings":
        project_dir = Path(__file__).resolve().parents[1]
        data_dir = Path(os.getenv("RESUME_V3_DATA_DIR", project_dir / "data"))
        database_url = os.getenv(
            "RESUME_V3_DATABASE_URL",
            f"sqlite:///{(data_dir / 'resume_v3.db').as_posix()}",
        )
        environment = os.getenv("RESUME_V3_ENVIRONMENT", "development").strip().lower()
        default_bootstrap = database_url.startswith("sqlite")
        return cls(
            project_dir=project_dir,
            data_dir=data_dir,
            upload_dir=data_dir / "uploads",
            database_url=database_url,
            environment=environment,
            auto_create_schema=_environment_flag(
                "RESUME_V3_AUTO_CREATE_SCHEMA",
                default=default_bootstrap,
            ),
            seed_registry_on_startup=_environment_flag(
                "RESUME_V3_SEED_REGISTRY_ON_STARTUP",
                default=default_bootstrap,
            ),
            database_pool_size=int(os.getenv("RESUME_V3_DATABASE_POOL_SIZE", "5")),
            database_max_overflow=int(
                os.getenv("RESUME_V3_DATABASE_MAX_OVERFLOW", "10")
            ),
            admin_token=os.getenv("RESUME_V3_ADMIN_TOKEN") or None,
            session_secret=os.getenv("RESUME_V3_SESSION_SECRET") or None,
            session_cookie_secure=_environment_flag(
                "RESUME_V3_SESSION_COOKIE_SECURE",
                default=environment in {"production", "prod"},
            ),
            allow_unauthenticated=os.getenv("RESUME_V3_ALLOW_UNAUTHENTICATED") == "1",
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            deepseek_timeout_seconds=int(
                os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90")
            ),
            ai_extraction_job_max_attempts=int(
                os.getenv("RESUME_V3_AI_EXTRACTION_JOB_MAX_ATTEMPTS", "3")
            ),
            ai_extraction_job_lease_seconds=int(
                os.getenv("RESUME_V3_AI_EXTRACTION_JOB_LEASE_SECONDS", "180")
            ),
            ai_extraction_worker_poll_seconds=float(
                os.getenv("RESUME_V3_AI_EXTRACTION_WORKER_POLL_SECONDS", "2")
            ),
            mailbox_sync_interval_seconds=float(
                os.getenv("RESUME_V3_MAILBOX_SYNC_INTERVAL_SECONDS", "600")
            ),
            mailbox_sync_attachment_limit=int(
                os.getenv("RESUME_V3_MAILBOX_SYNC_ATTACHMENT_LIMIT", "20")
            ),
            email_credentials_key=os.getenv("RESUME_V3_EMAIL_CREDENTIALS_KEY") or None,
            tencent_secret_id=os.getenv("TENCENT_SECRET_ID") or None,
            tencent_secret_key=os.getenv("TENCENT_SECRET_KEY") or None,
            tencent_ocr_region=os.getenv("TENCENT_OCR_REGION", "ap-guangzhou"),
            tencent_ocr_timeout_seconds=int(
                os.getenv("TENCENT_OCR_TIMEOUT_SECONDS", "20")
            ),
            ocr_sparse_text_chars_per_page=int(
                os.getenv("OCR_SPARSE_TEXT_CHARS_PER_PAGE", "500")
            ),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate_runtime(self) -> None:
        if self.database_pool_size < 1:
            raise ValueError("RESUME_V3_DATABASE_POOL_SIZE must be at least 1")
        if self.database_max_overflow < 0:
            raise ValueError("RESUME_V3_DATABASE_MAX_OVERFLOW must not be negative")
        if self.deepseek_timeout_seconds < 1:
            raise ValueError("DEEPSEEK_TIMEOUT_SECONDS must be at least 1")
        if bool(self.tencent_secret_id) != bool(self.tencent_secret_key):
            raise ValueError(
                "TENCENT_SECRET_ID and TENCENT_SECRET_KEY must be configured together"
            )
        if self.tencent_ocr_timeout_seconds < 1:
            raise ValueError("TENCENT_OCR_TIMEOUT_SECONDS must be at least 1")
        if self.ocr_sparse_text_chars_per_page < self.min_text_chars_per_page:
            raise ValueError(
                "OCR_SPARSE_TEXT_CHARS_PER_PAGE must be at least "
                "MIN_TEXT_CHARS_PER_PAGE"
            )
        if self.ai_extraction_job_max_attempts < 1:
            raise ValueError(
                "RESUME_V3_AI_EXTRACTION_JOB_MAX_ATTEMPTS must be at least 1"
            )
        if self.ai_extraction_job_lease_seconds < self.deepseek_timeout_seconds + 30:
            raise ValueError(
                "RESUME_V3_AI_EXTRACTION_JOB_LEASE_SECONDS must exceed "
                "DEEPSEEK_TIMEOUT_SECONDS by at least 30 seconds"
            )
        if self.ai_extraction_worker_poll_seconds <= 0:
            raise ValueError(
                "RESUME_V3_AI_EXTRACTION_WORKER_POLL_SECONDS must be positive"
            )
        if self.mailbox_sync_interval_seconds <= 0:
            raise ValueError("RESUME_V3_MAILBOX_SYNC_INTERVAL_SECONDS must be positive")
        if self.mailbox_sync_attachment_limit < 1:
            raise ValueError("RESUME_V3_MAILBOX_SYNC_ATTACHMENT_LIMIT must be at least 1")
        if self.environment in {"production", "prod"}:
            if self.allow_unauthenticated:
                raise RuntimeError("production_must_not_allow_unauthenticated")
            if self.database_url.startswith("sqlite"):
                raise RuntimeError("production_requires_postgresql_database_url")
            if self.auto_create_schema:
                raise RuntimeError("production_must_use_alembic_not_auto_create_schema")
            if self.seed_registry_on_startup:
                raise RuntimeError("production_must_seed_registry_explicitly")
