from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.models import (
    Resume,
    ResumeFactSnapshot,
    ResumeReviewAction,
    ResumeScore,
    ScoreTemplate,
    ScoreTemplateDimension,
)
from app.schemas import (
    ResumeScoreCreate,
    ResumeScoreOverride,
    ResumeScoreResponse,
    ScoreDimensionInput,
    ScoreTemplateCreate,
    ScoreTemplateResponse,
)
from app.services.deepseek_provider import (
    DeepSeekProviderError,
    score_resume_fact_snapshot,
)


class ScoreServiceError(RuntimeError):
    pass


class ScoreTemplateNotFoundError(ScoreServiceError):
    pass


class ResumeScoreNotFoundError(ScoreServiceError):
    pass


def _dimension_input(dimension: ScoreTemplateDimension) -> ScoreDimensionInput:
    return ScoreDimensionInput(
        key=dimension.key,
        label=dimension.label,
        weight=dimension.weight,
        max_raw_score=dimension.max_raw_score,
        guidance=dimension.guidance,
    )


def _template_response(template: ScoreTemplate) -> ScoreTemplateResponse:
    return ScoreTemplateResponse(
        template_id=template.id,
        name=template.name,
        description=template.description,
        version=template.version,
        dimensions=[
            _dimension_input(dimension)
            for dimension in sorted(template.dimensions, key=lambda item: item.sort_order)
        ],
    )


def _score_response(score: ResumeScore) -> ResumeScoreResponse:
    return ResumeScoreResponse(
        score_id=score.id,
        resume_id=score.resume_id,
        fact_snapshot_id=score.fact_snapshot_id,
        template_id=score.template_id,
        facts_version=score.facts_version,
        template_version=score.template_version,
        total_score=score.total_score,
        ai_total_score=score.ai_total_score,
        dimension_scores=score.dimension_scores or [],
        analysis=score.analysis or {},
        status=score.status,
        model_name=score.model_name,
        created_at=score.created_at.isoformat(),
    )


def _require_valid_dimensions(dimensions: list[ScoreTemplateDimension]) -> None:
    if not dimensions:
        raise ScoreServiceError("score_template_has_no_dimensions")
    if sum(dimension.weight for dimension in dimensions) != 100:
        raise ScoreServiceError("score_template_weights_must_sum_to_100")
    if len({dimension.key for dimension in dimensions}) != len(dimensions):
        raise ScoreServiceError("score_template_dimension_keys_must_be_unique")


def create_score_template(
    session: Session,
    *,
    payload: ScoreTemplateCreate,
) -> ScoreTemplateResponse:
    template = ScoreTemplate(
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        version=1,
    )
    session.add(template)
    session.flush()
    for sort_order, dimension in enumerate(payload.dimensions):
        session.add(
            ScoreTemplateDimension(
                template_id=template.id,
                key=dimension.key,
                label=dimension.label.strip(),
                weight=dimension.weight,
                max_raw_score=dimension.max_raw_score,
                guidance=dimension.guidance.strip() if dimension.guidance else None,
                sort_order=sort_order,
            )
        )
    session.flush()
    template = session.get(ScoreTemplate, template.id)
    assert template is not None
    _require_valid_dimensions(template.dimensions)
    return _template_response(template)


def list_score_templates(session: Session) -> list[ScoreTemplateResponse]:
    templates = session.scalars(
        select(ScoreTemplate)
        .where(ScoreTemplate.is_archived.is_(False))
        .order_by(ScoreTemplate.updated_at.desc(), ScoreTemplate.id.desc())
    ).all()
    return [_template_response(template) for template in templates]


def _load_ready_resume_and_snapshot(
    session: Session,
    *,
    resume_id: str,
) -> tuple[Resume, ResumeFactSnapshot, dict[str, object]]:
    resume = session.get(Resume, resume_id)
    if resume is None:
        raise ScoreServiceError("resume_not_found")
    if resume.extraction_status != "ready" or not resume.is_active:
        raise ScoreServiceError("resume_must_be_active_and_ready_for_scoring")
    snapshot = session.scalar(
        select(ResumeFactSnapshot)
        .where(ResumeFactSnapshot.resume_id == resume.id)
        .order_by(ResumeFactSnapshot.facts_version.desc())
    )
    if snapshot is None or snapshot.facts_version != resume.facts_version:
        raise ScoreServiceError("resume_fact_snapshot_not_current")
    try:
        parsed_snapshot = json.loads(snapshot.canonical_facts_json)
    except json.JSONDecodeError as exc:
        raise ScoreServiceError("resume_fact_snapshot_invalid") from exc
    if not isinstance(parsed_snapshot, dict):
        raise ScoreServiceError("resume_fact_snapshot_invalid")
    return resume, snapshot, parsed_snapshot


def _dimension_records(
    *,
    dimensions: list[ScoreTemplateDimension],
    provider_result: dict[str, object],
) -> tuple[list[dict[str, object]], float]:
    result_by_key = {
        str(item["key"]): item
        for item in provider_result["dimension_scores"]
        if isinstance(item, dict)
    }
    records: list[dict[str, object]] = []
    total = 0.0
    for dimension in sorted(dimensions, key=lambda item: item.sort_order):
        provider_dimension = result_by_key.get(dimension.key)
        if provider_dimension is None:
            raise ScoreServiceError("score_provider_missing_dimension")
        raw_score = float(provider_dimension["raw_score"])
        weighted_score = raw_score / dimension.max_raw_score * dimension.weight
        total += weighted_score
        records.append(
            {
                "key": dimension.key,
                "label": dimension.label,
                "weight": dimension.weight,
                "max_raw_score": dimension.max_raw_score,
                "ai_raw_score": raw_score,
                "final_raw_score": raw_score,
                "weighted_score": round(weighted_score, 4),
                "rationale": provider_dimension["rationale"],
                "fact_ids": provider_dimension["fact_ids"],
                "uncertainties": provider_dimension["uncertainties"],
                "manual_reason": None,
                "adjusted_at": None,
            }
        )
    return records, round(total, 2)


def run_resume_score(
    session: Session,
    *,
    resume_id: str,
    payload: ResumeScoreCreate,
    settings: AppSettings,
) -> ResumeScoreResponse:
    if not settings.deepseek_api_key:
        raise ScoreServiceError("deepseek_api_key_not_configured")
    template = session.get(ScoreTemplate, payload.template_id)
    if template is None or template.is_archived:
        raise ScoreTemplateNotFoundError("score_template_not_found")
    dimensions = session.scalars(
        select(ScoreTemplateDimension)
        .where(ScoreTemplateDimension.template_id == template.id)
        .order_by(ScoreTemplateDimension.sort_order)
    ).all()
    _require_valid_dimensions(dimensions)
    resume, snapshot, fact_snapshot = _load_ready_resume_and_snapshot(
        session,
        resume_id=resume_id,
    )
    provider_result = score_resume_fact_snapshot(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        fact_snapshot=fact_snapshot,
        dimensions=[
            {
                "key": dimension.key,
                "label": dimension.label,
                "weight": dimension.weight,
                "max_raw_score": dimension.max_raw_score,
                "guidance": dimension.guidance,
            }
            for dimension in dimensions
        ],
    )
    dimension_scores, ai_total_score = _dimension_records(
        dimensions=dimensions,
        provider_result=provider_result,
    )
    analysis = {
        "schema_version": provider_result["schema_version"],
        "overall_summary": provider_result["overall_summary"],
        "risk_flags": provider_result["risk_flags"],
        "needs_human_review": provider_result["needs_human_review"],
    }
    score = ResumeScore(
        resume_id=resume.id,
        fact_snapshot_id=snapshot.id,
        template_id=template.id,
        facts_version=snapshot.facts_version,
        template_version=template.version,
        total_score=ai_total_score,
        ai_total_score=ai_total_score,
        dimension_scores=dimension_scores,
        analysis=analysis,
        status=("needs_review" if provider_result["needs_human_review"] else "succeeded"),
        model_name=settings.deepseek_model,
    )
    session.add(score)
    session.flush()
    return _score_response(score)


def get_resume_score(session: Session, *, score_id: str) -> ResumeScoreResponse:
    score = session.get(ResumeScore, score_id)
    if score is None:
        raise ResumeScoreNotFoundError("resume_score_not_found")
    return _score_response(score)


def list_resume_scores(
    session: Session,
    *,
    resume_id: str,
) -> list[ResumeScoreResponse]:
    if session.get(Resume, resume_id) is None:
        raise ScoreServiceError("resume_not_found")
    scores = session.scalars(
        select(ResumeScore)
        .where(ResumeScore.resume_id == resume_id)
        .order_by(ResumeScore.created_at.desc(), ResumeScore.id.desc())
    ).all()
    return [_score_response(score) for score in scores]


def _recalculate_final_total(dimension_scores: list[dict[str, object]]) -> float:
    total = 0.0
    for dimension in dimension_scores:
        max_raw_score = float(dimension["max_raw_score"])
        final_raw_score = float(dimension["final_raw_score"])
        weight = float(dimension["weight"])
        total += final_raw_score / max_raw_score * weight
    return round(total, 2)


def override_score_dimension(
    session: Session,
    *,
    score_id: str,
    dimension_key: str,
    payload: ResumeScoreOverride,
) -> ResumeScoreResponse:
    score = session.get(ResumeScore, score_id)
    if score is None:
        raise ResumeScoreNotFoundError("resume_score_not_found")
    records = [dict(record) for record in (score.dimension_scores or [])]
    target = next((record for record in records if record.get("key") == dimension_key), None)
    if target is None:
        raise ScoreServiceError("score_dimension_not_found")
    max_raw_score = float(target["max_raw_score"])
    if payload.raw_score > max_raw_score:
        raise ScoreServiceError("score_override_exceeds_dimension_max")
    old_value = target.get("final_raw_score")
    target["final_raw_score"] = float(payload.raw_score)
    target["manual_reason"] = payload.reason.strip()
    target["adjusted_at"] = datetime.now(timezone.utc).isoformat()
    score.dimension_scores = records
    score.total_score = _recalculate_final_total(records)
    score.status = "overridden"
    session.add(
        ResumeReviewAction(
            resume_id=score.resume_id,
            action="score_dimension_overridden",
            note=payload.reason.strip(),
            old_values={
                "score_id": score.id,
                "dimension_key": dimension_key,
                "final_raw_score": old_value,
            },
            new_values={
                "score_id": score.id,
                "dimension_key": dimension_key,
                "final_raw_score": float(payload.raw_score),
            },
        )
    )
    session.flush()
    return _score_response(score)


__all__ = [
    "DeepSeekProviderError",
    "ResumeScoreNotFoundError",
    "ScoreServiceError",
    "ScoreTemplateNotFoundError",
    "create_score_template",
    "get_resume_score",
    "list_resume_scores",
    "list_score_templates",
    "override_score_dimension",
    "run_resume_score",
]
