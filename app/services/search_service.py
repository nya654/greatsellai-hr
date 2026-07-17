from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Candidate, Resume
from app.schemas import (
    CandidateSearchItem,
    CandidateSearchMatch,
    CandidateSearchRequest,
    CandidateSearchResponse,
    EducationFilter,
    ExperienceFilter,
)
from app.services.normalization import normalized_contains, normalized_key


def _matches_any_text(value: str | None, expected_values: list[str]) -> bool:
    return not expected_values or any(
        normalized_contains(value, expected) for expected in expected_values
    )


def _matches_education(filter_item: EducationFilter, education: object) -> bool:
    degree_in = filter_item.degree_in
    return (
        (not degree_in or education.degree in degree_in)
        and _matches_any_text(education.school_name_raw, filter_item.school_name_contains)
        and _matches_any_text(education.major_raw, filter_item.major_contains)
    )


def _matches_experience(filter_item: ExperienceFilter, experience: object) -> bool:
    return (
        experience.experience_type in filter_item.experience_types
        and _matches_any_text(
            experience.organization_name_raw,
            filter_item.organization_name_contains,
        )
        and _matches_any_text(experience.title_raw, filter_item.title_contains)
    )


class SearchValidationError(ValueError):
    pass


@dataclass(frozen=True)
class _SearchResult:
    item: CandidateSearchItem
    updated_at: datetime


def _encode_cursor(*, updated_at: datetime, resume_id: str) -> str:
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "resume_id": resume_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw_payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw_payload)
        updated_at = datetime.fromisoformat(payload["updated_at"])
        resume_id = payload["resume_id"]
    except (binascii.Error, KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise SearchValidationError("invalid_cursor") from exc
    if not isinstance(resume_id, str) or len(resume_id) != 36:
        raise SearchValidationError("invalid_cursor")
    return updated_at, resume_id


def _matches_keywords(resume: Resume, *, all_of: list[str], any_of: list[str]) -> bool:
    if not all_of and not any_of:
        return True
    source_text = "\n".join(block.text for block in resume.source_blocks)
    normalized_source = normalized_key(source_text)
    all_keys = {normalized_key(value) for value in all_of}
    any_keys = {normalized_key(value) for value in any_of}
    return (
        (not all_keys or all(key in normalized_source for key in all_keys))
        and (not any_keys or any(key in normalized_source for key in any_keys))
    )


def _matching_keyword_block_ids(resume: Resume, keywords: list[str]) -> list[str]:
    keys = {normalized_key(keyword) for keyword in keywords}
    return sorted(
        block.block_id
        for block in resume.source_blocks
        if any(key in normalized_key(block.text) for key in keys)
    )


def search_candidates(
    session: Session,
    request: CandidateSearchRequest,
) -> CandidateSearchResponse:
    statement = (
        select(Resume)
        .join(Resume.candidate)
        .options(
            selectinload(Resume.educations),
            selectinload(Resume.experiences),
            selectinload(Resume.skills),
            selectinload(Resume.source_blocks),
            selectinload(Resume.candidate),
        )
        .where(Resume.is_active.is_(True), Resume.extraction_status == "ready")
        .order_by(Resume.updated_at.desc(), Resume.id.desc())
    )
    if request.is_985_211 is not None:
        statement = statement.where(Resume.is_985_211.is_(request.is_985_211))
    if request.min_employment_months is not None:
        statement = statement.where(
            Resume.employment_months >= request.min_employment_months
        )
    if request.min_employment_or_internship_months is not None:
        statement = statement.where(
            Resume.employment_or_internship_months
            >= request.min_employment_or_internship_months
        )
    if request.cursor is not None:
        cursor_updated_at, cursor_resume_id = _decode_cursor(request.cursor)
        statement = statement.where(
            or_(
                Resume.updated_at < cursor_updated_at,
                and_(
                    Resume.updated_at == cursor_updated_at,
                    Resume.id < cursor_resume_id,
                ),
            )
        )

    results: list[_SearchResult] = []
    for resume in session.scalars(statement).all():
        matched_filters: list[str] = []
        matched_evidence: list[CandidateSearchMatch] = []

        if request.is_985_211 is not None:
            matched_filters.append(f"is_985_211={str(request.is_985_211).lower()}")
            matched_evidence.append(
                CandidateSearchMatch(
                    filter_key="is_985_211",
                    label=f"985/211={str(request.is_985_211).lower()}",
                    fact_type="aggregate",
                    evidence_block_ids=[],
                )
            )
        if request.min_employment_months is not None:
            matched_filters.append(
                f"employment_months>={request.min_employment_months}"
            )
            matched_evidence.append(
                CandidateSearchMatch(
                    filter_key="min_employment_months",
                    label=f"employment_months>={request.min_employment_months}",
                    fact_type="aggregate",
                    evidence_block_ids=[],
                )
            )
        if request.min_employment_or_internship_months is not None:
            matched_filters.append(
                "employment_or_internship_months"
                f">={request.min_employment_or_internship_months}"
            )
            matched_evidence.append(
                CandidateSearchMatch(
                    filter_key="min_employment_or_internship_months",
                    label=(
                        "employment_or_internship_months"
                        f">={request.min_employment_or_internship_months}"
                    ),
                    fact_type="aggregate",
                    evidence_block_ids=[],
                )
            )

        if request.education_any_of:
            matching_education = [
                education
                for filter_item in request.education_any_of
                for education in resume.educations
                if _matches_education(filter_item, education)
            ]
            if not matching_education:
                continue
            matched_filters.append("education")
            matched_evidence.extend(
                CandidateSearchMatch(
                    filter_key="education",
                    label=" | ".join(
                        value
                        for value in (
                            education.school_name_raw,
                            education.degree,
                            education.major_raw,
                        )
                        if value
                    ),
                    fact_type="education",
                    evidence_block_ids=education.evidence_block_ids or [],
                )
                for education in matching_education
            )

        if request.experience_any_of:
            matching_experience = [
                experience
                for filter_item in request.experience_any_of
                for experience in resume.experiences
                if _matches_experience(filter_item, experience)
            ]
            if not matching_experience:
                continue
            matched_filters.append("experience")
            matched_evidence.extend(
                CandidateSearchMatch(
                    filter_key="experience",
                    label=" | ".join(
                        value
                        for value in (
                            experience.organization_name_raw,
                            experience.title_raw,
                            experience.experience_type,
                        )
                        if value
                    ),
                    fact_type="experience",
                    evidence_block_ids=experience.evidence_block_ids or [],
                )
                for experience in matching_experience
            )

        skill_keys = {skill.skill_key for skill in resume.skills}
        required_skill_keys = {normalized_key(item) for item in request.skills_all_of}
        optional_skill_keys = {normalized_key(item) for item in request.skills_any_of}
        if required_skill_keys and not required_skill_keys.issubset(skill_keys):
            continue
        if optional_skill_keys and not optional_skill_keys.intersection(skill_keys):
            continue
        if required_skill_keys:
            matched_filters.append("skills_all_of")
            matched_evidence.extend(
                CandidateSearchMatch(
                    filter_key="skills_all_of",
                    label=skill.skill_display,
                    fact_type="skill",
                    evidence_block_ids=skill.evidence_block_ids or [],
                )
                for skill in resume.skills
                if skill.skill_key in required_skill_keys
            )
        if optional_skill_keys:
            matched_filters.append("skills_any_of")
            matched_evidence.extend(
                CandidateSearchMatch(
                    filter_key="skills_any_of",
                    label=skill.skill_display,
                    fact_type="skill",
                    evidence_block_ids=skill.evidence_block_ids or [],
                )
                for skill in resume.skills
                if skill.skill_key in optional_skill_keys
            )

        if not _matches_keywords(
            resume,
            all_of=request.keywords_all_of,
            any_of=request.keywords_any_of,
        ):
            continue
        if request.keywords_all_of:
            matched_filters.append("keywords_all_of")
            matched_evidence.append(
                CandidateSearchMatch(
                    filter_key="keywords_all_of",
                    label=", ".join(request.keywords_all_of),
                    fact_type="keyword",
                    evidence_block_ids=_matching_keyword_block_ids(
                        resume,
                        request.keywords_all_of,
                    ),
                )
            )
        if request.keywords_any_of:
            matched_filters.append("keywords_any_of")
            matched_evidence.append(
                CandidateSearchMatch(
                    filter_key="keywords_any_of",
                    label=", ".join(request.keywords_any_of),
                    fact_type="keyword",
                    evidence_block_ids=_matching_keyword_block_ids(
                        resume,
                        request.keywords_any_of,
                    ),
                )
            )

        candidate: Candidate = resume.candidate
        results.append(
            _SearchResult(
                item=CandidateSearchItem(
                candidate_id=candidate.id,
                display_name=candidate.display_name,
                resume_id=resume.id,
                is_985_211=bool(resume.is_985_211),
                highest_degree=resume.highest_degree,
                employment_months=resume.employment_months,
                matched_filters=matched_filters,
                matched_evidence=matched_evidence,
                ),
                updated_at=resume.updated_at,
            )
        )
    page_results = results[: request.limit]
    page_items = [result.item for result in page_results]
    next_cursor = (
        _encode_cursor(
            updated_at=page_results[-1].updated_at,
            resume_id=page_results[-1].item.resume_id,
        )
        if len(results) > len(page_results) and page_results
        else None
    )
    needs_review_count = session.scalar(
        select(func.count(func.distinct(Resume.candidate_id))).where(
            Resume.extraction_status == "needs_review"
        )
    )
    return CandidateSearchResponse(
        items=page_items,
        next_cursor=next_cursor,
        needs_review_count=int(needs_review_count or 0),
    )
