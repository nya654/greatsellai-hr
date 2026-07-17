from __future__ import annotations

from sqlalchemy import select

from app.models import ResumeAiExtractionJob, ResumeSourceBlock
from app.services import resume_service
from app.services.text_extraction import ExtractedPage, PdfExtractionResult
from test_resume_flow import create_candidate, upload_text_resume


def test_reparse_replaces_source_evidence_and_resets_inactive_job(
    client,
    monkeypatch,
) -> None:
    candidate_id = create_candidate(client)
    resume_id = upload_text_resume(client, candidate_id)
    database = client.app.state.database

    monkeypatch.setattr(
        resume_service,
        "extract_pdf_text",
        lambda *args, **kwargs: PdfExtractionResult(
            source_page_count=1,
            parsed_page_count=1,
            pages=[
                ExtractedPage(
                    page_no=1,
                    text="OCR recovered education skills project experience",
                    non_whitespace_chars=48,
                )
            ],
            raw_text="--- PAGE 1 ---\nOCR recovered education skills project experience",
            quality_flags=[],
            parser_version="pypdf-test+tencent-ocr",
        ),
    )

    with database.session_factory() as session:
        resume = resume_service.reparse_inactive_resume_source_text(
            session,
            resume_id=resume_id,
            settings=client.app.state.settings,
        )
        session.commit()

        block = session.scalar(
            select(ResumeSourceBlock).where(
                ResumeSourceBlock.resume_id == resume_id,
                ResumeSourceBlock.block_id == "page-001",
            )
        )
        job = session.scalar(
            select(ResumeAiExtractionJob).where(
                ResumeAiExtractionJob.resume_id == resume_id
            )
        )

    assert resume.extraction_status == "text_ready"
    assert resume.parser_version == "pypdf-test+tencent-ocr"
    assert resume.facts_version == 1
    assert block is not None
    assert block.text == "OCR recovered education skills project experience"
    assert job is not None
    assert job.status == "unavailable"
    assert job.attempt_count == 0
