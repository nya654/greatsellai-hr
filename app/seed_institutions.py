"""Explicit, idempotent institution-registry bootstrap command.

Run this after ``alembic upgrade head`` in production.  It is intentionally
separate from the web lifespan so multiple web replicas never race to mutate
reference data during startup.
"""

from app.config import AppSettings
from app.database import Database
from app.services.institution_service import (
    is_institution_registry_seeded,
    seed_institution_registry,
)


def main() -> None:
    settings = AppSettings.from_env()
    settings.validate_runtime()
    database = Database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    try:
        with database.session_factory() as session:
            seed_institution_registry(session)
            session.commit()
            if not is_institution_registry_seeded(session):
                raise RuntimeError("institution_registry_seed_verification_failed")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
