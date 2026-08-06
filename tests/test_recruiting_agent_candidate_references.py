from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Candidate,
    RecruitingAgentCandidateSet,
    RecruitingAgentCandidateSetItem,
    RecruitingAgentConversation,
    Resume,
    utcnow,
)
from app.tenant_scope import (
    clear_organization_context,
    set_organization_context,
)
from test_tenant_isolation import _register_and_login, workspace_clients


def _workspace_id(client: TestClient) -> str:
    response = client.get("/v1/auth/session")
    assert response.status_code == 200, response.text
    return str(response.json()["organization"]["organization_id"])


def _owner_user_id(client: TestClient) -> str:
    response = client.get("/v1/auth/session")
    assert response.status_code == 200, response.text
    return str(response.json()["user"]["user_id"])


def _seed_reference_scope(
    client: TestClient,
    *,
    display_names: list[str],
    mark_hidden: list[int] | None = None,
    source_kind: str = "candidate_filter",
) -> tuple[str, list[dict[str, str]]]:
    """Create distinct ready resumes and freeze them into one private scope.

    Returns ``(conversation_id, rows)`` where each row carries only
    ``candidate_id``, ``resume_id``, and ``display_name``.  Indexes listed in
    ``mark_hidden`` are made invisible (archived / not-ready / deleted) so the
    endpoint must omit them on read.
    """

    organization_id = _workspace_id(client)
    owner_user_id = _owner_user_id(client)
    hidden_indexes = set(mark_hidden or [])
    rows: list[dict[str, str]] = []
    database = client.app.state.database
    with database.session_factory() as session:
        set_organization_context(session, organization_id)
        try:
            for index, name in enumerate(display_names):
                candidate = Candidate(display_name=name)
                session.add(candidate)
                session.flush()
                resume = Resume(
                    candidate_id=candidate.id,
                    original_filename=f"candidate-references-{index}.pdf",
                    storage_key=f"candidate-references-{index}.pdf",
                    sha256=f"{index:064x}",
                    source_page_count=1,
                    parsed_page_count=1,
                    extraction_status="text_ready" if index in hidden_indexes else "ready",
                    quality_flags=[],
                    parser_version="candidate-references-test",
                    is_active=index not in hidden_indexes,
                    deleted_at=utcnow() if index in hidden_indexes else None,
                )
                session.add(resume)
                session.flush()
                rows.append(
                    {
                        "candidate_id": candidate.id,
                        "resume_id": resume.id,
                        "display_name": name,
                    }
                )
            conversation = RecruitingAgentConversation(
                owner_user_id=owner_user_id,
                expires_at=utcnow() + timedelta(hours=24),
            )
            session.add(conversation)
            session.flush()
            candidate_set = RecruitingAgentCandidateSet(
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                source_kind=source_kind,
                source_ref_id=None,
                expires_at=conversation.expires_at,
            )
            session.add(candidate_set)
            session.flush()
            session.add_all(
                RecruitingAgentCandidateSetItem(
                    organization_id=organization_id,
                    candidate_set_id=candidate_set.id,
                    resume_id=row["resume_id"],
                    ordinal=index + 1,
                )
                for index, row in enumerate(rows)
            )
            conversation.active_candidate_set_id = candidate_set.id
            session.commit()
            return conversation.id, rows
        finally:
            clear_organization_context(session)


def _list_references(
    client: TestClient,
    conversation_id: str,
    **params: Any,
) -> dict[str, Any]:
    response = client.get(
        f"/v1/recruiting-agent/conversations/{conversation_id}/candidate-references",
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_candidate_references_returns_working_scope_in_set_order(
    ai_client: TestClient,
) -> None:
    """The composer menu lists the frozen scope before any search has run."""

    conversation_id, rows = _seed_reference_scope(
        ai_client,
        display_names=["张伟", "李明", "王芳"],
    )
    payload = _list_references(ai_client, conversation_id)
    assert payload["next_cursor"] is None
    assert payload["items"] == [
        {
            "candidate_id": rows[0]["candidate_id"],
            "resume_id": rows[0]["resume_id"],
            "display_name": "张伟",
        },
        {
            "candidate_id": rows[1]["candidate_id"],
            "resume_id": rows[1]["resume_id"],
            "display_name": "李明",
        },
        {
            "candidate_id": rows[2]["candidate_id"],
            "resume_id": rows[2]["resume_id"],
            "display_name": "王芳",
        },
    ]


def test_candidate_references_pages_continuously_by_cursor(
    ai_client: TestClient,
) -> None:
    """Scroll pagination follows set order and ends with a null cursor."""

    conversation_id, rows = _seed_reference_scope(
        ai_client,
        display_names=["张三", "李四", "王五", "赵六", "钱七"],
    )
    collected: list[dict[str, str]] = []
    cursor: str | None = None
    pages = 0
    while pages < 10:
        payload = _list_references(
            ai_client,
            conversation_id,
            limit=2,
            cursor=cursor,
        )
        collected.extend(payload["items"])
        pages += 1
        if payload["next_cursor"] is None:
            break
        cursor = payload["next_cursor"]
    assert pages == 3
    assert payload["next_cursor"] is None
    assert [item["display_name"] for item in collected] == [
        "张三",
        "李四",
        "王五",
        "赵六",
        "钱七",
    ]
    assert [item["candidate_id"] for item in collected] == [
        row["candidate_id"] for row in rows
    ]


def test_candidate_references_name_search_filters_within_scope(
    ai_client: TestClient,
) -> None:
    """Typing a name narrows the menu to matching candidates only."""

    conversation_id, rows = _seed_reference_scope(
        ai_client,
        display_names=["张伟", "李张", "王伟", "Alice Chen"],
    )
    zh = _list_references(ai_client, conversation_id, query="张")
    assert [item["display_name"] for item in zh["items"]] == ["张伟", "李张"]

    latin = _list_references(ai_client, conversation_id, query="alice")
    assert [item["display_name"] for item in latin["items"]] == ["Alice Chen"]

    none = _list_references(ai_client, conversation_id, query="不存在的名字")
    assert none["items"] == []
    assert none["next_cursor"] is None


def test_candidate_references_omits_deleted_archived_and_not_ready(
    ai_client: TestClient,
) -> None:
    """Reads re-check resume visibility so hidden members never surface."""

    conversation_id, rows = _seed_reference_scope(
        ai_client,
        display_names=["可用甲", "已归档乙", "未就绪丙"],
        mark_hidden=[1, 2],
    )
    payload = _list_references(ai_client, conversation_id)
    assert [item["display_name"] for item in payload["items"]] == ["可用甲"]
    assert payload["items"][0]["candidate_id"] == rows[0]["candidate_id"]
    assert payload["items"][0]["resume_id"] == rows[0]["resume_id"]


def test_candidate_references_empty_without_an_active_scope(
    ai_client: TestClient,
) -> None:
    """A fresh conversation with no frozen set returns an empty page."""

    bound = ai_client.post(
        "/v1/recruiting-agent/conversations/filter-scope",
        json={"filter": {}},
    )
    assert bound.status_code == 200, bound.text
    conversation_id = bound.json()["conversation_id"]

    payload = _list_references(ai_client, conversation_id)
    assert payload == {"items": [], "next_cursor": None}


def test_candidate_references_empty_when_scope_is_expired(
    ai_client: TestClient,
) -> None:
    """A cleared or expired scope must not resurrect stale membership."""

    conversation_id, _ = _seed_reference_scope(
        ai_client,
        display_names=["即将过期"],
    )
    database = ai_client.app.state.database
    organization_id = _workspace_id(ai_client)
    with database.session_factory() as session:
        set_organization_context(session, organization_id)
        try:
            conversation = session.scalar(
                select(RecruitingAgentConversation).where(
                    RecruitingAgentConversation.id == conversation_id
                )
            )
            assert conversation is not None
            candidate_set = session.get(
                RecruitingAgentCandidateSet,
                conversation.active_candidate_set_id,
            )
            assert candidate_set is not None
            candidate_set.expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
        finally:
            clear_organization_context(session)

    payload = _list_references(ai_client, conversation_id)
    assert payload == {"items": [], "next_cursor": None}


def test_candidate_references_ignores_an_invalid_cursor_safely(
    ai_client: TestClient,
) -> None:
    """A malformed cursor falls back to the first page instead of erroring."""

    conversation_id, rows = _seed_reference_scope(
        ai_client,
        display_names=["第一位", "第二位"],
    )
    payload = _list_references(ai_client, conversation_id, cursor="not-a-cursor")
    assert [item["display_name"] for item in payload["items"]] == ["第一位", "第二位"]
    assert payload["items"][0]["candidate_id"] == rows[0]["candidate_id"]


def test_candidate_references_respects_owner_and_workspace_isolation(
    workspace_clients: tuple[TestClient, TestClient],
) -> None:
    """A private scope stays unreadable across workspaces and owners."""

    client_a, client_b = workspace_clients
    _register_and_login(
        client_a,
        organization_name="Candidate references workspace A",
        full_name="Candidate references A",
        email="candidate-references-a@example.test",
        password="tenant-test-password",
    )
    _register_and_login(
        client_b,
        organization_name="Candidate references workspace B",
        full_name="Candidate references B",
        email="candidate-references-b@example.test",
        password="tenant-test-password",
    )
    conversation_id, _ = _seed_reference_scope(
        client_a,
        display_names=["仅本工作区可见"],
    )

    cross_tenant = client_b.get(
        f"/v1/recruiting-agent/conversations/{conversation_id}/candidate-references",
    )
    assert cross_tenant.status_code == 404, cross_tenant.text
    assert cross_tenant.json()["detail"] == "agent_conversation_not_found"

    foreign_scope = client_a.get(
        "/v1/recruiting-agent/conversations/unknown-conversation/candidate-references",
    )
    assert foreign_scope.status_code == 404, foreign_scope.text
    assert foreign_scope.json()["detail"] == "agent_conversation_not_found"
