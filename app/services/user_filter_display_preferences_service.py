"""Per-user filter display-column preference services.

The preference row is per ``(user_id, organization_id)`` and is created lazily
with an empty selection on first read.  An empty selection is the product
semantics for "fall back to auto-derived columns" in the search results pane;
a row only exists once the user has saved an explicit selection, but the
service never lets that distinction leak past the API boundary.

Both the read and write resolve the row by the *authenticated* member's user
and workspace, never by a caller-supplied ID, so a request cannot touch
another user's (or another workspace's) row even if it guesses a primary key.

The same row also carries ``filter_section_keys``: which "初筛条件板块" (filter
panel sections) the user keeps visible. An empty selection keeps the panel at
its product default (every section shown); the section keys mirror
``web/src/features/filter/filter-section-options.ts``.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserFilterDisplayPreference
from app.schemas import (
    DisplayFieldPreferencesResponse,
    FilterSectionPreferencesResponse,
)

# Exact 22-key set from ``web/src/types.ts`` ``CandidateSearchDisplayFieldKey``.
# A PUT rejects any key outside this set before persisting the selection.
VALID_DISPLAY_FIELD_KEYS = frozenset(
    {
        "institution_classifications",
        "highest_degree",
        "education_degree",
        "graduation",
        "employment_months",
        "employment_or_internship_months",
        "gender",
        "age",
        "school",
        "major",
        "academic_performance",
        "experience_type",
        "experience_name",
        "organization",
        "title",
        "experience_award",
        "skills",
        "language",
        "scholarship",
        "competition",
        "leadership",
        "keywords",
    }
)

# Exact 8-key set from ``web/src/features/filter/filter-section-options.ts``.
# Mirrors the sections rendered by FilterPanel so a PUT cannot persist a key
# the panel never renders.
VALID_FILTER_SECTION_KEYS = frozenset(
    {
        "condition_mode",
        "institution",
        "basic_profile",
        "academic",
        "graduation",
        "experience",
        "source_channel",
        "keywords",
    }
)


def _row_for_user(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
) -> UserFilterDisplayPreference:
    row = session.scalar(
        select(UserFilterDisplayPreference).where(
            UserFilterDisplayPreference.user_id == user_id,
            UserFilterDisplayPreference.organization_id == organization_id,
        )
    )
    if row is not None:
        return row
    row = UserFilterDisplayPreference(
        user_id=user_id,
        organization_id=organization_id,
        display_field_keys=[],
        filter_section_keys=[],
    )
    session.add(row)
    return row


def display_field_preferences_response(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
) -> DisplayFieldPreferencesResponse:
    row = _row_for_user(session, user_id=user_id, organization_id=organization_id)
    return DisplayFieldPreferencesResponse(
        display_field_keys=list(row.display_field_keys or [])
    )


def update_display_field_preferences(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
    field_keys: list[str],
) -> DisplayFieldPreferencesResponse:
    unknown = [key for key in field_keys if key not in VALID_DISPLAY_FIELD_KEYS]
    if unknown:
        raise ValueError("unknown_display_field_key")
    deduped = list(dict.fromkeys(field_keys))
    row = _row_for_user(session, user_id=user_id, organization_id=organization_id)
    row.display_field_keys = deduped
    session.flush()
    return DisplayFieldPreferencesResponse(display_field_keys=deduped)


def filter_section_preferences_response(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
) -> FilterSectionPreferencesResponse:
    row = _row_for_user(session, user_id=user_id, organization_id=organization_id)
    return FilterSectionPreferencesResponse(
        filter_section_keys=list(row.filter_section_keys or [])
    )


def update_filter_section_preferences(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
    section_keys: list[str],
) -> FilterSectionPreferencesResponse:
    unknown = [key for key in section_keys if key not in VALID_FILTER_SECTION_KEYS]
    if unknown:
        raise ValueError("unknown_filter_section_key")
    deduped = list(dict.fromkeys(section_keys))
    row = _row_for_user(session, user_id=user_id, organization_id=organization_id)
    row.filter_section_keys = deduped
    session.flush()
    return FilterSectionPreferencesResponse(filter_section_keys=deduped)
