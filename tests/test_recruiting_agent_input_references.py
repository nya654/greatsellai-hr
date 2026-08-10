from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    RecruitingAgentCandidateSet,
    RecruitingAgentCandidateSetItem,
    Resume,
    TalentSearchProfile,
    TalentSearchProfileRevision,
    utcnow,
)
from app.services import recruiting_agent_service
from app.tenant_scope import (
    bypass_organization_scope,
    clear_organization_context,
    set_organization_context,
)
from test_recruiting_agent_context_retention import _save_ready_agent_resume
from test_tenant_isolation import _register_and_login, workspace_clients


def _input_references(payload: dict[str, object]) -> list[dict[str, str]]:
    active_context = payload["active_context"]
    assert isinstance(active_context, dict)
    references = active_context["input_references"]
    assert isinstance(references, list)
    return references


def _reference_by_kind(
    payload: dict[str, object],
    kind: str,
) -> dict[str, str]:
    return next(item for item in _input_references(payload) if item["kind"] == kind)


def _workspace_id(client: TestClient) -> str:
    session = client.get("/v1/auth/session")
    assert session.status_code == 200, session.text
    return str(session.json()["organization"]["organization_id"])


def _seed_current_profile(client: TestClient) -> tuple[str, str]:
    """Create an ordinary workspace-scoped profile with a non-public source."""

    organization_id = _workspace_id(client)
    database = client.app.state.database
    with database.session_factory() as session:
        set_organization_context(session, organization_id)
        try:
            profile = TalentSearchProfile(
                title="Reference profile title",
                original_request="PROFILE_ORIGINAL_SECRET_MUST_NOT_BE_ECHOED",
                status="confirmed",
                current_revision_number=1,
                confirmed_revision_number=1,
            )
            session.add(profile)
            session.flush()
            revision = TalentSearchProfileRevision(
                profile_id=profile.id,
                revision_number=1,
                status="confirmed",
                title="Reference profile title",
                summary="Synthetic reference profile.",
                hard_filters={},
                verification_requirements=[],
                preferred_requirements=[],
                aliases=[],
                clarifying_questions=[],
                confirmed_at=utcnow(),
            )
            session.add(revision)
            session.commit()
            return profile.id, revision.id
        finally:
            clear_organization_context(session)


def test_candidate_scope_chip_carries_display_name_but_not_identifiers(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    """A composer candidate bind surfaces the picked person's display name, but never raw identifiers."""

    candidate_id, resume_id = _save_ready_agent_resume(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.raw_text = "RESUME_ORIGINAL_SECRET_MUST_NOT_BE_ECHOED"
            session.commit()

    monkeypatch.setattr(
        recruiting_agent_service,
        "_model_completion",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("candidate scope binding must not invoke the model")
        ),
    )
    bound = ai_client.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={"candidate_id": candidate_id},
    )

    assert bound.status_code == 200, bound.text
    payload = bound.json()
    assert payload["active_context"]["candidate_set_source"] == "candidate"
    assert payload["active_context"]["candidate_count"] == 1
    reference = _reference_by_kind(payload, "candidate")
    # The one explicitly picked candidate is the person in focus: the chip
    # carries their display name so the Agent knows who is being discussed.
    assert reference["label"] == "测试候选人"
    assert reference["reference_id"] not in {candidate_id, resume_id}
    serialized = json.dumps(payload, ensure_ascii=False)
    assert candidate_id not in serialized
    assert resume_id not in serialized
    assert "RESUME_ORIGINAL_SECRET_MUST_NOT_BE_ECHOED" not in serialized

    with database.session_factory() as session:
        with bypass_organization_scope(session):
            candidate_set = session.get(
                RecruitingAgentCandidateSet,
                reference["reference_id"],
            )
            assert candidate_set is not None
            assert candidate_set.source_kind == "candidate"
            assert candidate_set.source_ref_id is None
            assert session.scalar(
                select(RecruitingAgentCandidateSetItem.resume_id).where(
                    RecruitingAgentCandidateSetItem.candidate_set_id
                    == candidate_set.id
                )
            ) == resume_id


def test_candidate_scope_rejects_an_ineligible_current_resume(
    ai_client: TestClient,
) -> None:
    """A direct candidate reference must pass the same screening gate as search."""

    candidate_id, resume_id = _save_ready_agent_resume(ai_client)
    database = ai_client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            resume = session.get(Resume, resume_id)
            assert resume is not None
            resume.quality_flags = ["source_text_unreliable"]
            session.commit()

    rejected = ai_client.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={"candidate_id": candidate_id},
    )

    assert rejected.status_code == 404, rejected.text
    assert rejected.json()["detail"] == "agent_context_reference_not_found"


def test_context_input_reference_chips_bind_and_clear_without_turn_payloads(
    ai_client: TestClient,
) -> None:
    """Candidate, JD, filter, and profile chips are server-owned work state."""

    candidate_id, resume_id = _save_ready_agent_resume(ai_client)
    job = ai_client.post(
        "/v1/jobs",
        json={
            "title": "Reference-safe JD",
            "jd_text": "Python service development.",
            "requirements": {"must_have": ["Python"], "preferred": []},
        },
    )
    assert job.status_code == 200, job.text
    job_version_id = str(job.json()["job_version_id"])

    job_bound = ai_client.post(
        "/v1/recruiting-agent/conversations/context",
        json={"job_version_id": job_version_id},
    )
    assert job_bound.status_code == 200, job_bound.text
    job_payload = job_bound.json()
    assert _reference_by_kind(job_payload, "job") == {
        "reference_id": job_version_id,
        "kind": "job",
        "label": "关联 JD",
    }

    candidate_bound = ai_client.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={
            "candidate_id": candidate_id,
            "conversation_id": job_payload["conversation_id"],
            "context_version": job_payload["context_version"],
        },
    )
    assert candidate_bound.status_code == 200, candidate_bound.text
    candidate_payload = candidate_bound.json()
    assert {item["kind"] for item in _input_references(candidate_payload)} == {
        "candidate",
        "job",
    }
    assert candidate_payload["context_version"] > job_payload["context_version"]

    candidate_reference = _reference_by_kind(candidate_payload, "candidate")
    serialized_candidate = json.dumps(candidate_payload, ensure_ascii=False)
    assert candidate_id not in serialized_candidate
    assert resume_id not in serialized_candidate
    assert candidate_reference["reference_id"] not in {candidate_id, resume_id}

    profile_id, revision_id = _seed_current_profile(ai_client)
    profile_bound = ai_client.post(
        "/v1/recruiting-agent/conversations/context",
        json={
            "context_ref": {
                "kind": "talent_search_profile",
                "profile_id": profile_id,
                "revision_id": revision_id,
            },
            "conversation_id": candidate_payload["conversation_id"],
            "context_version": candidate_payload["context_version"],
        },
    )
    assert profile_bound.status_code == 200, profile_bound.text
    profile_payload = profile_bound.json()
    assert {item["kind"] for item in _input_references(profile_payload)} == {
        "candidate",
        "job",
        "talent_profile",
    }
    assert _reference_by_kind(profile_payload, "talent_profile") == {
        "reference_id": revision_id,
        "kind": "talent_profile",
        "label": "人才画像",
    }
    assert "PROFILE_ORIGINAL_SECRET_MUST_NOT_BE_ECHOED" not in json.dumps(
        profile_payload,
        ensure_ascii=False,
    )

    cleared_candidate = ai_client.post(
        "/v1/recruiting-agent/conversations/context/clear",
        json={
            "target": "candidate_scope",
            "conversation_id": profile_payload["conversation_id"],
            "context_version": profile_payload["context_version"],
        },
    )
    assert cleared_candidate.status_code == 200, cleared_candidate.text
    cleared_candidate_payload = cleared_candidate.json()
    assert {item["kind"] for item in _input_references(cleared_candidate_payload)} == {
        "job",
        "talent_profile",
    }
    assert (
        cleared_candidate_payload["context_version"]
        > profile_payload["context_version"]
    )

    stale_clear = ai_client.post(
        "/v1/recruiting-agent/conversations/context/clear",
        json={
            "target": "job",
            "conversation_id": profile_payload["conversation_id"],
            "context_version": profile_payload["context_version"],
        },
    )
    assert stale_clear.status_code == 409, stale_clear.text
    assert stale_clear.json()["detail"] == "agent_conversation_stale"

    cleared_profile = ai_client.post(
        "/v1/recruiting-agent/conversations/context/clear",
        json={
            "target": "talent_profile",
            "conversation_id": cleared_candidate_payload["conversation_id"],
            "context_version": cleared_candidate_payload["context_version"],
        },
    )
    assert cleared_profile.status_code == 200, cleared_profile.text
    cleared_profile_payload = cleared_profile.json()
    assert {item["kind"] for item in _input_references(cleared_profile_payload)} == {
        "job",
    }

    cleared_job = ai_client.post(
        "/v1/recruiting-agent/conversations/context/clear",
        json={
            "target": "job",
            "conversation_id": cleared_profile_payload["conversation_id"],
            "context_version": cleared_profile_payload["context_version"],
        },
    )
    assert cleared_job.status_code == 200, cleared_job.text
    assert _input_references(cleared_job.json()) == []

    filter_bound = ai_client.post(
        "/v1/recruiting-agent/conversations/filter-scope",
        json={
            "filter": {},
            "conversation_id": cleared_job.json()["conversation_id"],
            "context_version": cleared_job.json()["context_version"],
        },
    )
    assert filter_bound.status_code == 200, filter_bound.text
    filter_payload = filter_bound.json()
    filter_reference = _reference_by_kind(filter_payload, "filter")
    assert filter_reference["label"] == "当前筛选"
    filter_serialized = json.dumps(filter_payload, ensure_ascii=False)
    assert candidate_id not in filter_serialized
    assert resume_id not in filter_serialized


def test_candidate_scope_rejects_foreign_and_stale_contexts(
    workspace_clients: tuple[TestClient, TestClient],
) -> None:
    """Candidate binding checks owner/workspace before a scope is replaced."""

    client_a, client_b = workspace_clients
    _register_and_login(
        client_a,
        organization_name="Input reference workspace A",
        full_name="Input reference A",
        email="input-reference-a@example.test",
        password="tenant-test-password",
    )
    _register_and_login(
        client_b,
        organization_name="Input reference workspace B",
        full_name="Input reference B",
        email="input-reference-b@example.test",
        password="tenant-test-password",
    )
    candidate_id, _ = _save_ready_agent_resume(client_a)
    bound = client_a.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={"candidate_id": candidate_id},
    )
    assert bound.status_code == 200, bound.text
    payload = bound.json()

    foreign_candidate = client_b.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={"candidate_id": candidate_id},
    )
    assert foreign_candidate.status_code == 404, foreign_candidate.text
    assert foreign_candidate.json()["detail"] == "agent_context_reference_not_found"

    foreign_conversation = client_b.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={
            "candidate_id": candidate_id,
            "conversation_id": payload["conversation_id"],
            "context_version": payload["context_version"],
        },
    )
    assert foreign_conversation.status_code == 404, foreign_conversation.text
    assert foreign_conversation.json()["detail"] == "agent_conversation_not_found"

    stale = client_a.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={
            "candidate_id": candidate_id,
            "conversation_id": payload["conversation_id"],
            "context_version": payload["context_version"] - 1,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"] == "agent_conversation_stale"


def test_agent_turn_rejects_candidate_resume_text_and_history_fields(
    client: TestClient,
) -> None:
    """The turn transport remains limited to the request plus opaque session IDs."""

    response = client.post(
        "/v1/recruiting-agent/turns",
        json={
            "message": "Compare the attached candidate.",
            "candidate_id": "browser-candidate-id",
            "resume_id": "browser-resume-id",
            "resume_text": "BROWSER_RESUME_SECRET",
            "chat_history": [{"role": "user", "content": "browser history"}],
        },
    )

    assert response.status_code == 422, response.text
    locations = {tuple(item["loc"]) for item in response.json()["detail"]}
    assert ("body", "candidate_id") in locations
    assert ("body", "resume_id") in locations
    assert ("body", "resume_text") in locations
    assert ("body", "chat_history") in locations


def test_candidate_scope_resume_read_skips_confirm_and_selection_markers(
    ai_client: TestClient,
    monkeypatch,
) -> None:
    """A composer-picked single candidate is readable without markers or a name.

    The recruiter already chose this exact person in the composer, so a bare
    follow-up like "介绍一下他" may resolve the one candidate in focus without
    re-confirming a resume read or re-selecting among several people.
    """

    candidate_id, resume_id = _save_ready_agent_resume(ai_client)
    bound = ai_client.post(
        "/v1/recruiting-agent/conversations/candidate-scope",
        json={"candidate_id": candidate_id},
    )
    assert bound.status_code == 200, bound.text
    bound_payload = bound.json()
    assert bound_payload["active_context"]["candidate_set_source"] == "candidate"
    assert bound_payload["active_context"]["candidate_count"] == 1
    assert _reference_by_kind(bound_payload, "candidate")["label"] == "测试候选人"

    calls = 0
    captured: dict[str, object] = {}

    def fake_completion(*, settings, messages, tools_enabled=True):
        nonlocal calls
        del settings
        calls += 1
        if calls == 1:
            assert tools_enabled is True
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "read-scoped-candidate",
                        "type": "function",
                        "function": {
                            "name": "read_candidate_resume_content",
                            "arguments": json.dumps({}),
                        },
                    }
                ],
            }
        assert calls == 2
        assert tools_enabled is False
        captured["tool_payload"] = json.loads(messages[-1]["content"])
        return {"content": "已阅读这位候选人的简历正文。"}

    monkeypatch.setattr(
        "app.services.recruiting_agent_service._model_completion",
        fake_completion,
    )

    response = ai_client.post(
        "/v1/recruiting-agent/turns",
        json={
            # No "简历" marker, no name, no ordinal: the picked person is scope.
            "message": "介绍一下他。",
            "conversation_id": bound_payload["conversation_id"],
            "context_version": bound_payload["context_version"],
        },
    )

    assert response.status_code == 200, response.text
    turn_payload = response.json()
    assert turn_payload["intent"] == "read_resume_content"
    assert [item["tool"] for item in turn_payload["tool_trace"]] == ["完整简历原文"]
    tool_payload = captured["tool_payload"]
    assert isinstance(tool_payload, dict)
    assert tool_payload["candidate_name"] == "测试候选人"
    assert tool_payload["page_count"] == 1
    assert "北京大学" in tool_payload["resume_pages"][0]["text"]
    serialized = json.dumps(turn_payload, ensure_ascii=False)
    assert candidate_id not in serialized
    assert resume_id not in serialized
    assert "北京大学" not in serialized
