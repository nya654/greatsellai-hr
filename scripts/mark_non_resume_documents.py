"""Classify historical empty-facts extraction jobs as non-resume documents.

Run this only against the intended environment from inside its application
container, after reviewing the candidate count.  It is deliberately scoped to
jobs whose terminal error is exactly ``deepseek_empty_structured_facts``.
"""

from sqlalchemy import select, text

from app.config import AppSettings
from app.database import Database
from app.models import Resume, ResumeAiExtractionJob, utcnow
from app.services.ai_extraction_job_service import (
    AI_EXTRACTION_COMPLETED,
    AI_EXTRACTION_NEEDS_ATTENTION,
    NON_RESUME_DOCUMENT_FLAG,
)
from app.tenant_scope import clear_organization_context, set_organization_context


EMPTY_FACTS_ERROR = "deepseek_empty_structured_facts"


def main() -> None:
    settings = AppSettings.from_env()
    database = Database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )

    with database.session_factory() as session:
        candidates = session.execute(
            text(
                """
                SELECT j.resume_id, j.organization_id
                FROM resume_ai_extraction_jobs j
                JOIN resumes r ON r.id = j.resume_id
                WHERE j.status = 'needs_attention'
                  AND j.last_error = :error
                  AND r.is_active = false
                  AND r.extraction_status IN ('text_ready', 'needs_review')
                ORDER BY j.resume_id
                """
            ),
            {"error": EMPTY_FACTS_ERROR},
        ).all()

    print(f"CANDIDATES={len(candidates)}")
    marked = 0
    skipped = 0
    for resume_id, organization_id in candidates:
        with database.session_factory() as session:
            set_organization_context(session, organization_id)
            try:
                job = session.scalar(
                    select(ResumeAiExtractionJob).where(
                        ResumeAiExtractionJob.resume_id == resume_id,
                        ResumeAiExtractionJob.status == AI_EXTRACTION_NEEDS_ATTENTION,
                        ResumeAiExtractionJob.last_error == EMPTY_FACTS_ERROR,
                    )
                )
                resume = session.scalar(
                    select(Resume).where(Resume.id == resume_id)
                )
                if (
                    job is None
                    or resume is None
                    or resume.is_active
                    or resume.extraction_status not in {"text_ready", "needs_review"}
                ):
                    skipped += 1
                    continue

                flags = set(resume.quality_flags or [])
                flags.add(NON_RESUME_DOCUMENT_FLAG)
                resume.quality_flags = sorted(flags)
                job.status = AI_EXTRACTION_COMPLETED
                job.next_attempt_at = None
                job.completed_at = utcnow()
                job.lease_owner = None
                job.lease_expires_at = None
                session.commit()
                marked += 1
            except Exception:
                session.rollback()
                raise
            finally:
                clear_organization_context(session)

    print(f"MARKED={marked} SKIPPED={skipped}")


if __name__ == "__main__":
    main()
