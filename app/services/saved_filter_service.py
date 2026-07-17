from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedFilter
from app.schemas import SavedFilterCreate, SavedFilterResponse


class SavedFilterNotFoundError(RuntimeError):
    pass


def _response(saved_filter: SavedFilter) -> SavedFilterResponse:
    return SavedFilterResponse(
        saved_filter_id=saved_filter.id,
        name=saved_filter.name,
        filters=saved_filter.filters,
        created_at=saved_filter.created_at.isoformat(),
        updated_at=saved_filter.updated_at.isoformat(),
    )


def create_saved_filter(
    session: Session,
    *,
    payload: SavedFilterCreate,
) -> SavedFilterResponse:
    saved_filter = SavedFilter(
        name=payload.name.strip(),
        filters=payload.filters.model_dump(exclude={"cursor"}),
    )
    session.add(saved_filter)
    session.flush()
    return _response(saved_filter)


def list_saved_filters(session: Session) -> list[SavedFilterResponse]:
    saved_filters = session.scalars(
        select(SavedFilter).order_by(SavedFilter.updated_at.desc(), SavedFilter.id.desc())
    ).all()
    return [_response(saved_filter) for saved_filter in saved_filters]


def delete_saved_filter(session: Session, *, saved_filter_id: str) -> None:
    saved_filter = session.get(SavedFilter, saved_filter_id)
    if saved_filter is None:
        raise SavedFilterNotFoundError("saved_filter_not_found")
    session.delete(saved_filter)
