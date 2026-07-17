from __future__ import annotations

import argparse

from app.ai_extraction_worker import _create_worker_database
from app.config import AppSettings
from app.services.ai_extraction_job_service import backfill_unnamed_candidate_names


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill empty candidate names with source-grounded AI extraction."
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    settings = AppSettings.from_env()
    database = _create_worker_database(settings)
    try:
        updated, skipped = backfill_unnamed_candidate_names(
            database,
            settings=settings,
            limit=max(args.limit, 0),
        )
    finally:
        database.dispose()
    print(f"candidate_name_backfill updated={updated} skipped={skipped}")


if __name__ == "__main__":
    main()
