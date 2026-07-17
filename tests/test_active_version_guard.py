from __future__ import annotations

from test_filter_mvp_contract import _education, _employment, _facts
from test_resume_flow import create_candidate, replace_page_evidence, upload_text_resume


def test_saving_historical_ready_version_cannot_reactivate_it(client) -> None:
    candidate_id = create_candidate(client)
    first_resume_id = upload_text_resume(client, candidate_id)
    replace_page_evidence(
        client,
        first_resume_id,
        "Education \u6e05\u534e\u5927\u5b66 Computer Science \u5de5\u4f5c\u7ecf\u5386 Acme Python Engineer Python SQL",
    )
    first_save = client.put(
        f"/v1/resumes/{first_resume_id}/facts",
        json=_facts(
            educations=[_education("\u6e05\u534e\u5927\u5b66", "bachelor", "Computer Science")],
            experiences=[_employment("Acme", "Python Engineer")],
        ),
    )
    assert first_save.status_code == 200, first_save.text

    second_resume_id = upload_text_resume(client, candidate_id)
    replace_page_evidence(
        client,
        second_resume_id,
        "Education \u6e05\u534e\u5927\u5b66 Computer Science \u5de5\u4f5c\u7ecf\u5386 Beta Python Engineer Python SQL",
    )
    second_save = client.put(
        f"/v1/resumes/{second_resume_id}/facts",
        json=_facts(
            educations=[_education("\u6e05\u534e\u5927\u5b66", "master", "Computer Science")],
            experiences=[_employment("Beta", "Python Engineer")],
        ),
    )
    assert second_save.status_code == 200, second_save.text

    blocked = client.put(
        f"/v1/resumes/{first_resume_id}/facts",
        json=_facts(
            educations=[_education("\u6e05\u534e\u5927\u5b66", "bachelor", "Computer Science")],
            experiences=[_employment("Acme", "Python Engineer")],
        ),
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "inactive_ready_resume_requires_explicit_activation"
    assert client.get(f"/v1/resumes/{second_resume_id}").json()["is_active"] is True

    activated = client.post(
        f"/v1/resumes/{first_resume_id}/activate",
        json={"note": "Reverting to the prior verified version."},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["is_active"] is True
    assert client.get(f"/v1/resumes/{second_resume_id}").json()["is_active"] is False


def test_separator_only_keyword_is_rejected(client) -> None:
    response = client.post(
        "/v1/candidates/search",
        json={"keywords_all_of": ["---"]},
    )
    assert response.status_code == 422
    assert "searchable characters" in response.text
