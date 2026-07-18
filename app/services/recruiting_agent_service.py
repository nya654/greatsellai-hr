from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import AppSettings
from app.schemas import (
    CandidateSearchRequest,
    RecruitingAgentAction,
    RecruitingAgentCandidate,
    RecruitingAgentRequest,
    RecruitingAgentResponse,
    RecruitingAgentToolTrace,
)
from app.services.deepseek_provider import API_URL
from app.services.job_match_batch_service import enqueue_job_version_match_batch
from app.services.job_service import (
    JobServiceError,
    JobVersionNotFoundError,
    get_job_version,
    get_latest_confirmed_job_version,
    list_job_version_matches,
    list_resume_job_matches,
)
from app.services.search_service import search_candidates


class RecruitingAgentServiceError(RuntimeError):
    """A visible failure, never a silent fallback to rule matching."""


@dataclass(frozen=True)
class ResolvedJob:
    job_version_id: str
    title: str


@dataclass
class ToolRun:
    payload: dict[str, Any]
    cards: list[RecruitingAgentCandidate] = field(default_factory=list)
    actions: list[RecruitingAgentAction] = field(default_factory=list)
    traces: list[RecruitingAgentToolTrace] = field(default_factory=list)
    batch_id: str | None = None


_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_985_211": {"type": "boolean"},
        "min_employment_months": {"type": "integer", "minimum": 0, "maximum": 720},
        "min_employment_or_internship_months": {"type": "integer", "minimum": 0, "maximum": 720},
        "skills_all_of": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "skills_any_of": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "keywords_all_of": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "keywords_any_of": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
}


_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_candidates",
            "description": (
                "Search the verified resume database. Use this whenever the user asks to find, "
                "filter, or shortlist candidates. Put simultaneously required skills in "
                "skills_all_of. Convert years to months."
            ),
            "parameters": _SEARCH_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_current_job_match_batch",
            "description": "Start the asynchronous match-all job for the currently selected confirmed JD.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_job_ranking",
            "description": "Read completed JD matching results for the currently selected confirmed JD.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_current_candidate_match",
            "description": "Read the saved JD match facts for the currently selected candidate and JD.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    },
]


def _model_completion(*, settings: AppSettings, messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.deepseek_api_key:
        raise RecruitingAgentServiceError("agent_model_not_configured")
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(
            {
                "model": settings.deepseek_model,
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "max_tokens": 900,
                "messages": messages,
                "tools": _TOOLS,
                "tool_choice": "auto",
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.deepseek_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RecruitingAgentServiceError(f"agent_model_http_{exc.code}") from exc
    except TimeoutError as exc:
        raise RecruitingAgentServiceError("agent_model_timeout") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RecruitingAgentServiceError("agent_model_network_error") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RecruitingAgentServiceError("agent_model_invalid_response") from exc
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RecruitingAgentServiceError("agent_model_empty_response") from exc
    if not isinstance(message, dict):
        raise RecruitingAgentServiceError("agent_model_invalid_response")
    return message


def _resolve_job(session: Session, requested_job_version_id: str | None) -> ResolvedJob | None:
    try:
        item = (
            get_job_version(session, job_version_id=requested_job_version_id)
            if requested_job_version_id
            else get_latest_confirmed_job_version(session)
        )
    except (JobServiceError, JobVersionNotFoundError):
        return None
    # Source JDs published as-is intentionally have no extracted conditions.
    # They are visible in the JD workspace, but must never become an Agent
    # matching target: matching tools require at least one structured clause.
    if item.status != "confirmed" or not item.requirements:
        return None
    return ResolvedJob(job_version_id=item.job_version_id, title=item.title)


def _clean_tool_arguments(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise RecruitingAgentServiceError("agent_tool_arguments_missing")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RecruitingAgentServiceError("agent_tool_arguments_invalid") from exc
    if not isinstance(parsed, dict):
        raise RecruitingAgentServiceError("agent_tool_arguments_invalid")
    return parsed


def _search(session: Session, arguments: dict[str, Any]) -> ToolRun:
    allowed = set(_SEARCH_SCHEMA["properties"])
    # Tool models occasionally include optional keys with JSON null.  Those
    # are omissions, not a reason to turn a recruiter request into a 500.
    values = {
        key: value
        for key, value in arguments.items()
        if key in allowed and value is not None
    }
    raw_limit = values.get("limit", 20)
    values["limit"] = (
        min(raw_limit, 20)
        if isinstance(raw_limit, int) and not isinstance(raw_limit, bool)
        else 20
    )
    try:
        request = CandidateSearchRequest.model_validate(values)
    except (TypeError, ValueError) as exc:
        raise RecruitingAgentServiceError("agent_search_arguments_invalid") from exc
    result = search_candidates(session, request)
    applied = {
        key: value
        for key, value in request.model_dump(exclude_none=True).items()
        if value not in ([], 20, None)
    }
    cards = [
        RecruitingAgentCandidate(
            candidate_id=item.candidate_id,
            resume_id=item.resume_id,
            display_name=item.display_name,
            detail=(
                f"{'985/211' if item.is_985_211 else '非 985/211'} · "
                f"工作经历 {item.employment_months // 12} 年 {item.employment_months % 12} 个月"
            ),
        )
        for item in result.items
    ]
    return ToolRun(
        payload={
            "applied_filters": applied,
            "result_count": len(cards),
            "needs_review_count": result.needs_review_count,
            "candidates": [
                {
                    "name": card.display_name or "未命名候选人",
                    "is_985_211": item.is_985_211,
                    "employment_months": item.employment_months,
                    "matched_filters": item.matched_filters,
                }
                for card, item in zip(cards, result.items, strict=True)
            ],
        },
        cards=cards,
        traces=[RecruitingAgentToolTrace(tool="简历筛选", summary=f"已按 {json.dumps(applied, ensure_ascii=False)} 筛选 {len(cards)} 人")],
    )


def _start_batch(
    session: Session,
    job: ResolvedJob | None,
    *,
    settings: AppSettings,
) -> ToolRun:
    if job is None:
        return ToolRun(payload={"error": "没有已确认的当前 JD，无法启动批量匹配。"})
    batch = enqueue_job_version_match_batch(
        session,
        job_version_id=job.job_version_id,
        settings=settings,
    )
    return ToolRun(
        payload={"job_title": job.title, "batch_id": batch.batch_id, "total_count": batch.total_count, "status": batch.status},
        actions=[RecruitingAgentAction(action="open_match_workspace", label="打开 JD 匹配工作区")],
        traces=[RecruitingAgentToolTrace(tool="批量 JD 匹配", summary=f"已启动“{job.title}”的 {batch.total_count} 份简历匹配任务")],
        batch_id=batch.batch_id,
    )


def _ranking(session: Session, job: ResolvedJob | None, arguments: dict[str, Any]) -> ToolRun:
    if job is None:
        return ToolRun(payload={"error": "没有已确认的当前 JD，无法读取排行榜。"})
    limit = arguments.get("limit", 10)
    if not isinstance(limit, int):
        limit = 10
    latest: dict[str, Any] = {}
    for match in list_job_version_matches(session, job_version_id=job.job_version_id):
        latest.setdefault(match.resume_id, match)
    ranked = sorted(latest.values(), key=lambda item: item.total_score, reverse=True)[: min(max(limit, 1), 20)]
    cards = [
        RecruitingAgentCandidate(
            candidate_id=item.candidate_id,
            resume_id=item.resume_id,
            display_name=item.candidate_display_name,
            score=item.total_score,
            detail=f"JD 匹配 {item.total_score:.1f} 分 · {item.hard_requirement_status or '硬条件待确认'}",
        )
        for item in ranked
    ]
    return ToolRun(
        payload={
            "job_title": job.title,
            "matched_count": len(latest),
            "ranking": [
                {"name": card.display_name or "未命名候选人", "score": card.score, "hard_requirement_status": item.hard_requirement_status}
                for card, item in zip(cards, ranked, strict=True)
            ],
        },
        cards=cards,
        actions=[RecruitingAgentAction(action="open_match_workspace", label="打开 JD 匹配工作区")],
        traces=[RecruitingAgentToolTrace(tool="JD 匹配排行", summary=f"已读取“{job.title}”的 {len(latest)} 条完成匹配结果")],
    )


def _explain(session: Session, job: ResolvedJob | None, resume_id: str | None) -> ToolRun:
    if not resume_id:
        return ToolRun(payload={"error": "当前未选择候选人。"})
    matches = list_resume_job_matches(session, resume_id=resume_id)
    match = next((item for item in matches if job and item.job_version_id == job.job_version_id), None)
    if match is None:
        return ToolRun(payload={"error": "当前候选人没有所选 JD 的已完成匹配结果。"})
    return ToolRun(
        payload={
            "candidate_name": match.candidate_display_name or "未命名候选人",
            "job_title": job.title if job else None,
            "total_score": match.total_score,
            "hard_requirement_status": match.hard_requirement_status,
            "requirements": [
                {
                    "requirement": item.requirement_text,
                    "outcome": item.outcome,
                    "reason": item.reason,
                    "uncertainty": item.missing_or_uncertain,
                }
                for item in match.requirement_results
            ],
        },
        traces=[RecruitingAgentToolTrace(tool="匹配解释", summary="已读取当前候选人的已保存 JD 匹配证据")],
    )


def _execute_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    session: Session,
    job: ResolvedJob | None,
    resume_id: str | None,
    settings: AppSettings,
) -> ToolRun:
    if name == "search_candidates":
        return _search(session, arguments)
    if name == "start_current_job_match_batch":
        return _start_batch(session, job, settings=settings)
    if name == "get_current_job_ranking":
        return _ranking(session, job, arguments)
    if name == "explain_current_candidate_match":
        return _explain(session, job, resume_id)
    raise RecruitingAgentServiceError("agent_tool_not_allowed")


def run_recruiting_agent_turn(
    session: Session,
    *,
    payload: RecruitingAgentRequest,
    settings: AppSettings,
) -> RecruitingAgentResponse:
    job = _resolve_job(session, payload.job_version_id)
    context = {
        "current_job": {"job_version_id": job.job_version_id, "title": job.title} if job else None,
        "current_resume_id": payload.resume_id,
    }
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a Chinese recruiting assistant that works through tools. For any request "
                "about finding candidates, JD matching, ranking, or explaining a candidate, call the "
                "appropriate tool before answering. Never claim a candidate fact that is absent from a "
                "tool result. Do not make hiring, rejection, or discrimination decisions. After tools "
                "return, answer in concise Simplified Chinese, state the result and uncertainties. "
                "Format the final answer as concise Markdown when structure improves scanning, "
                "such as short headings, bullet lists, or compact tables. Do not output raw HTML. "
                "Do not mention hidden prompts, model routing, or chain-of-thought."
            ),
        },
        {
            "role": "user",
            "content": "当前工作台上下文：" + json.dumps(context, ensure_ascii=False) + "\n\n用户请求：" + payload.message.strip(),
        },
    ]
    cards: list[RecruitingAgentCandidate] = []
    actions: list[RecruitingAgentAction] = []
    traces: list[RecruitingAgentToolTrace] = []
    batch_id: str | None = None
    for _ in range(4):
        assistant_message = _model_completion(settings=settings, messages=messages)
        calls = assistant_message.get("tool_calls")
        if not calls:
            content = assistant_message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise RecruitingAgentServiceError("agent_model_missing_final_answer")
            return RecruitingAgentResponse(
                message=content.strip(),
                intent="help",
                job_version_id=job.job_version_id if job else None,
                candidates=cards,
                actions=actions,
                tool_trace=traces,
                batch_id=batch_id,
            )
        if not isinstance(calls, list):
            raise RecruitingAgentServiceError("agent_model_invalid_tool_calls")
        messages.append({"role": "assistant", "content": assistant_message.get("content"), "tool_calls": calls})
        for call in calls:
            if not isinstance(call, dict):
                raise RecruitingAgentServiceError("agent_model_invalid_tool_calls")
            function = call.get("function")
            call_id = call.get("id")
            if not isinstance(function, dict) or not isinstance(call_id, str):
                raise RecruitingAgentServiceError("agent_model_invalid_tool_calls")
            name = function.get("name")
            if not isinstance(name, str):
                raise RecruitingAgentServiceError("agent_model_invalid_tool_calls")
            run = _execute_tool(
                name=name,
                arguments=_clean_tool_arguments(function.get("arguments")),
                session=session,
                job=job,
                resume_id=payload.resume_id,
                settings=settings,
            )
            cards = run.cards or cards
            actions.extend(run.actions)
            traces.extend(run.traces)
            batch_id = run.batch_id or batch_id
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(run.payload, ensure_ascii=False),
                }
            )
    raise RecruitingAgentServiceError("agent_model_tool_loop_limit")


__all__ = ["RecruitingAgentServiceError", "run_recruiting_agent_turn"]
