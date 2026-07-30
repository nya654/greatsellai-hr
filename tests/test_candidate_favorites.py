"""Private candidate-favorite API coverage for #140.

Favorites are intentionally an association between the signed-in user and a
candidate in one workspace.  These tests exercise the public API boundary as
well as the candidate-data lifecycle worker so a future implementation cannot
quietly turn the feature into a shared talent pool or leave orphaned records.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import (
    Candidate,
    CandidateDataDeletionBatch,
    CandidateDataPurgeJob,
    CandidateFavorite,
    OrganizationMembership,
    Resume,
    UserAccount,
    utcnow,
)
from app.services.candidate_data_purge_service import run_candidate_data_purge_worker_once
from app.services.identity_service import hash_password
from app.tenant_scope import bypass_organization_scope, set_organization_context
from test_tenant_isolation import (
    _create_candidate_and_resume,
    _pdf_with_text,
    _register_and_login,
    workspace_clients,
)


def _upload_resume_for_candidate(
    client: TestClient,
    *,
    candidate_id: str,
    filename: str,
) -> str:
    uploaded = client.post(
        f"/v1/candidates/{candidate_id}/resumes",
        files={
            "file": (
                filename,
                _pdf_with_text("Favorite fixture Python SQL experience " * 8),
                "application/pdf",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    return str(uploaded.json()["resume_id"])


def _create_same_workspace_member_client(
    owner_client: TestClient,
    *,
    organization_id: str,
    email: str,
) -> TestClient:
    """Create a second verified recruiter in the owner's existing workspace.

    Product invitation acceptance is independently covered by identity tests.
    This narrow setup keeps the favorite test focused on the crucial fact that
    two authenticated users can occupy the *same* workspace while still having
    distinct private collections.
    """

    password = "favorite-member-password"
    database = owner_client.app.state.database
    with database.session_factory() as session:
        set_organization_context(session, organization_id)
        member = UserAccount(
            email=email,
            email_key=email.casefold(),
            full_name="Favorite workspace recruiter",
            password_hash=hash_password(password),
            email_verified_at=utcnow(),
        )
        session.add(member)
        session.flush()
        session.add(
            OrganizationMembership(
                organization_id=organization_id,
                user_id=member.id,
                role="recruiter",
            )
        )
        session.commit()

    member_client = TestClient(owner_client.app)
    logged_in = member_client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert logged_in.status_code == 200, logged_in.text
    return member_client


def _favorite(client: TestClient, candidate_id: str) -> dict[str, object]:
    response = client.put(f"/v1/candidates/{candidate_id}/favorite")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidate_id"] == candidate_id
    assert payload["is_favorited"] is True
    assert payload["favorited_at"]
    return payload


def _favorite_list(client: TestClient) -> dict[str, object]:
    response = client.get("/v1/candidate-favorites")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload["items"], list)
    return payload


def _library_item(client: TestClient, *, resume_id: str) -> dict[str, object]:
    response = client.get("/v1/resume-library")
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resume_id"] == resume_id)


def _mark_resume_searchable(
    client: TestClient,
    *,
    organization_id: str,
    resume_id: str,
) -> None:
    """Make the upload fixture eligible for the no-filter search projection."""

    database = client.app.state.database
    with database.session_factory() as session:
        set_organization_context(session, organization_id)
        resume = session.get(Resume, resume_id)
        assert resume is not None
        resume.extraction_status = "ready"
        resume.is_active = True
        resume.quality_flags = []
        session.commit()


def _search_item(client: TestClient, *, resume_id: str) -> dict[str, object]:
    response = client.post("/v1/candidates/search", json={"limit": 20})
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resume_id"] == resume_id)


def _count_favorites(client: TestClient, *, candidate_id: str) -> int:
    database = client.app.state.database
    with database.session_factory() as session:
        # The assertion is deliberately raw: lifecycle queries normally hide
        # a soft-deleted candidate through its root, while this proves the
        # durable association is retained until restore or physical purge.
        with bypass_organization_scope(session):
            count = session.scalar(
                select(func.count(CandidateFavorite.id)).where(
                    CandidateFavorite.candidate_id == candidate_id
                )
            )
    return int(count or 0)


def _force_purge_due(client: TestClient, *, deletion_batch_id: str) -> None:
    """Move one deletion batch's worker lease into the past for test timing."""

    database = client.app.state.database
    due = utcnow() - timedelta(seconds=1)
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            batch = session.scalar(
                select(CandidateDataDeletionBatch).where(
                    CandidateDataDeletionBatch.id == deletion_batch_id
                )
            )
            job = session.scalar(
                select(CandidateDataPurgeJob).where(
                    CandidateDataPurgeJob.deletion_batch_id == deletion_batch_id
                )
            )
            assert batch is not None
            assert job is not None
            batch.purge_after_at = due
            batch.recovery_deadline_at = due
            job.next_attempt_at = due
            session.commit()


def test_favorites_are_private_to_current_user_within_one_workspace(
    workspace_clients: tuple[TestClient, TestClient],
) -> None:
    owner_client, _ = workspace_clients
    owner_session = _register_and_login(
        owner_client,
        organization_name="Favorite privacy workspace",
        full_name="Favorite owner",
        email="favorite-owner@example.test",
        password="favorite-owner-password",
    )
    organization_id = str(owner_session["organization"]["organization_id"])
    candidate_id, resume_id = _create_candidate_and_resume(
        owner_client,
        display_name="Favorite privacy fixture",
    )
    _mark_resume_searchable(
        owner_client,
        organization_id=organization_id,
        resume_id=resume_id,
    )
    colleague_client = _create_same_workspace_member_client(
        owner_client,
        organization_id=organization_id,
        email="favorite-colleague@example.test",
    )
    try:
        _favorite(owner_client, candidate_id)

        owner_favorites = _favorite_list(owner_client)
        assert owner_favorites["total"] == 1
        assert [item["candidate_id"] for item in owner_favorites["items"]] == [candidate_id]

        # The colleague can see the same candidate through normal workspace
        # reads, but never through the owner's private collection or state.
        colleague_favorites = _favorite_list(colleague_client)
        assert colleague_favorites["total"] == 0
        assert colleague_favorites["items"] == []
        assert _library_item(owner_client, resume_id=resume_id)["is_favorited"] is True
        assert _library_item(colleague_client, resume_id=resume_id)["is_favorited"] is False
        assert _search_item(owner_client, resume_id=resume_id)["is_favorited"] is True
        assert _search_item(colleague_client, resume_id=resume_id)["is_favorited"] is False

        owner_review = owner_client.get(f"/v1/resumes/{resume_id}/review")
        colleague_review = colleague_client.get(f"/v1/resumes/{resume_id}/review")
        assert owner_review.status_code == colleague_review.status_code == 200
        assert owner_review.json()["is_favorited"] is True
        assert colleague_review.json()["is_favorited"] is False
    finally:
        colleague_client.close()


def test_favorite_routes_do_not_distinguish_foreign_candidate_from_missing(
    workspace_clients: tuple[TestClient, TestClient],
) -> None:
    client_a, client_b = workspace_clients
    _register_and_login(
        client_a,
        organization_name="Favorite alpha workspace",
        full_name="Favorite alpha",
        email="favorite-alpha@example.test",
        password="favorite-alpha-password",
    )
    _register_and_login(
        client_b,
        organization_name="Favorite beta workspace",
        full_name="Favorite beta",
        email="favorite-beta@example.test",
        password="favorite-beta-password",
    )
    candidate_b_id, _ = _create_candidate_and_resume(
        client_b,
        display_name="Foreign favorite fixture",
    )
    missing_candidate_id = "not-a-real-candidate"

    for method in ("put", "delete"):
        foreign = getattr(client_a, method)(f"/v1/candidates/{candidate_b_id}/favorite")
        missing = getattr(client_a, method)(f"/v1/candidates/{missing_candidate_id}/favorite")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json()["detail"] == missing.json()["detail"] == "candidate_not_found"

    foreign_versions = client_a.get(f"/v1/candidates/{candidate_b_id}/resume-versions")
    missing_versions = client_a.get(f"/v1/candidates/{missing_candidate_id}/resume-versions")
    assert foreign_versions.status_code == missing_versions.status_code == 404
    assert (
        foreign_versions.json()["detail"]
        == missing_versions.json()["detail"]
        == "candidate_not_found"
    )
    assert _favorite_list(client_a)["items"] == []
    assert _favorite_list(client_b)["items"] == []


def test_repeated_favorite_and_unfavorite_are_idempotent(
    workspace_clients: tuple[TestClient, TestClient],
) -> None:
    client, _ = workspace_clients
    session_payload = _register_and_login(
        client,
        organization_name="Favorite idempotency workspace",
        full_name="Favorite idempotency owner",
        email="favorite-idempotency@example.test",
        password="favorite-idempotency-password",
    )
    candidate_id, _ = _create_candidate_and_resume(
        client,
        display_name="Favorite idempotency fixture",
    )

    first = _favorite(client, candidate_id)
    second = _favorite(client, candidate_id)
    assert second["favorited_at"] == first["favorited_at"]

    database = client.app.state.database
    with database.session_factory() as session:
        set_organization_context(
            session,
            str(session_payload["organization"]["organization_id"]),
        )
        count = session.scalar(
            select(func.count(CandidateFavorite.id)).where(
                CandidateFavorite.candidate_id == candidate_id,
                CandidateFavorite.user_id == str(session_payload["user"]["user_id"]),
            )
        )
        assert count == 1

    first_delete = client.delete(f"/v1/candidates/{candidate_id}/favorite")
    second_delete = client.delete(f"/v1/candidates/{candidate_id}/favorite")
    assert first_delete.status_code == second_delete.status_code == 204
    assert _favorite_list(client)["total"] == 0
    assert _count_favorites(client, candidate_id=candidate_id) == 0


def test_favorite_list_groups_all_resume_versions_under_one_candidate(client: TestClient) -> None:
    created = client.post("/v1/candidates", json={"display_name": "Versioned favorite fixture"})
    assert created.status_code == 200, created.text
    candidate_id = str(created.json()["candidate_id"])
    first_resume_id = _upload_resume_for_candidate(
        client,
        candidate_id=candidate_id,
        filename="favorite-version-one.pdf",
    )
    second_resume_id = _upload_resume_for_candidate(
        client,
        candidate_id=candidate_id,
        filename="favorite-version-two.pdf",
    )
    _favorite(client, candidate_id)

    favorites = _favorite_list(client)
    assert favorites["total"] == 1
    assert len(favorites["items"]) == 1
    favorite = favorites["items"][0]
    assert favorite["candidate_id"] == candidate_id
    assert favorite["current_resume_id"] in {first_resume_id, second_resume_id}
    assert {version["resume_id"] for version in favorite["resume_versions"]} == {
        first_resume_id,
        second_resume_id,
    }

    versions = client.get(f"/v1/candidates/{candidate_id}/resume-versions")
    assert versions.status_code == 200, versions.text
    versions_payload = versions.json()
    assert versions_payload["candidate_id"] == candidate_id
    assert {version["resume_id"] for version in versions_payload["items"]} == {
        first_resume_id,
        second_resume_id,
    }


def test_favorite_survives_single_resume_version_delete(client: TestClient) -> None:
    """A bookmark follows the candidate, not a disposable resume version."""

    created = client.post(
        "/v1/candidates",
        json={"display_name": "Version deletion favorite fixture"},
    )
    assert created.status_code == 200, created.text
    candidate_id = str(created.json()["candidate_id"])
    first_resume_id = _upload_resume_for_candidate(
        client,
        candidate_id=candidate_id,
        filename="favorite-delete-version-one.pdf",
    )
    second_resume_id = _upload_resume_for_candidate(
        client,
        candidate_id=candidate_id,
        filename="favorite-delete-version-two.pdf",
    )
    _favorite(client, candidate_id)

    deleted = client.request(
        "DELETE",
        f"/v1/resumes/{first_resume_id}",
        json={"reason": "duplicate"},
    )
    assert deleted.status_code == 202, deleted.text
    assert deleted.json()["affected_candidate_count"] == 0

    favorite = _favorite_list(client)["items"][0]
    assert favorite["candidate_id"] == candidate_id
    assert favorite["current_resume_id"] == second_resume_id
    assert [version["resume_id"] for version in favorite["resume_versions"]] == [
        second_resume_id
    ]
    assert _count_favorites(client, candidate_id=candidate_id) == 1


def test_favorite_hides_on_delete_resurfaces_on_restore_and_is_purged(client: TestClient) -> None:
    candidate_id, resume_id = _create_candidate_and_resume(
        client,
        display_name="Favorite lifecycle fixture",
    )
    _favorite(client, candidate_id)
    assert _count_favorites(client, candidate_id=candidate_id) == 1

    deleted = client.request(
        "DELETE",
        f"/v1/candidates/{candidate_id}",
        json={"reason": "duplicate"},
    )
    assert deleted.status_code == 202, deleted.text
    deletion_batch_id = str(deleted.json()["deletion_batch_id"])
    assert _favorite_list(client)["items"] == []
    # A soft delete hides the candidate from ordinary reads but deliberately
    # retains the personal association so a restore does not lose user intent.
    assert _count_favorites(client, candidate_id=candidate_id) == 1
    assert client.get(f"/v1/resumes/{resume_id}").status_code == 404

    restored = client.post(f"/v1/candidate-data/deletions/{deletion_batch_id}/restore")
    assert restored.status_code == 200, restored.text
    restored_favorites = _favorite_list(client)
    assert restored_favorites["total"] == 1
    assert restored_favorites["items"][0]["candidate_id"] == candidate_id

    deleted_again = client.request(
        "DELETE",
        f"/v1/candidates/{candidate_id}",
        json={"reason": "duplicate"},
    )
    assert deleted_again.status_code == 202, deleted_again.text
    _force_purge_due(
        client,
        deletion_batch_id=str(deleted_again.json()["deletion_batch_id"]),
    )
    assert run_candidate_data_purge_worker_once(
        client.app.state.database,
        settings=client.app.state.settings,
        worker_id="candidate-favorite-purge-test",
    )
    assert _count_favorites(client, candidate_id=candidate_id) == 0

    database = client.app.state.database
    with database.session_factory() as session:
        with bypass_organization_scope(session):
            assert session.scalar(select(Candidate).where(Candidate.id == candidate_id)) is None
            assert session.scalar(select(Resume).where(Resume.id == resume_id)) is None
