from __future__ import annotations

from test_resume_flow import create_candidate, replace_page_evidence, upload_text_resume


def _save_v2_resume(client) -> str:
    candidate_id = create_candidate(client)
    resume_id = upload_text_resume(client, candidate_id)
    replace_page_evidence(
        client,
        resume_id,
        "教育经历 北京大学 计算机 本科 2022-09 至 2026-06，"
        "GPA 3.8/4.0，专业排名 5/100。获得国家奖学金。"
        "英语四级 520 分。全国大学生技能竞赛一等奖，担任项目组组长。"
        "技能 Python SQL。",
    )
    response = client.put(
        f"/v1/resumes/{resume_id}/facts",
        json={
            "facts": {
                "schema_version": "resume_facts.v2",
                "education": [
                    {
                        "school_name_raw": "北京大学",
                        "degree": "bachelor",
                        "major_raw": "计算机",
                        "start_month": "2022-09",
                        "end_month": "2026-06",
                        "institution_tiers": ["211", "985"],
                        "gpa_value": 3.8,
                        "gpa_scale": 4.0,
                        "rank_position": 5,
                        "rank_total": 100,
                        "evidence_block_ids": ["page-001"],
                    }
                ],
                "experiences": [
                    {
                        "experience_type": "competition",
                        "experience_name_raw": "全国大学生技能竞赛",
                        "title_raw": "组长",
                        "leadership_context": "project_team",
                        "leadership_role": "组长",
                        "award_level": "national",
                        "award_result_raw": "一等奖",
                        "evidence_block_ids": ["page-001"],
                    }
                ],
                "skills": [
                    {
                        "skill_display": "Python",
                        "skill_category": "software",
                        "evidence_block_ids": ["page-001"],
                    }
                ],
                "language_credentials": [
                    {
                        "credential_code": "cet4",
                        "credential_name_raw": "英语四级",
                        "score": 520,
                        "passed": True,
                        "evidence_block_ids": ["page-001"],
                    }
                ],
                "scholarships": [
                    {
                        "scholarship_name_raw": "国家奖学金",
                        "scholarship_level": "national",
                        "evidence_block_ids": ["page-001"],
                    }
                ],
            }
        },
    )
    assert response.status_code == 200, response.text
    return resume_id


def test_filter_options_use_confirmed_order_and_bilingual_english_names(client) -> None:
    response = client.get("/v1/filter-options")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["label"] for item in payload["degrees"]] == [
        "博士", "硕士", "本科", "大专", "高中", "中专/职高及以下"
    ]
    assert [item["label"] for item in payload["institution_tiers"][:3]] == [
        "211", "985", "双一流"
    ]
    assert [item["label"] for item in payload["language_credentials"][:4]] == [
        "大学英语四级（CET-4）",
        "大学英语六级（CET-6）",
        "雅思（IELTS）",
        "托福（TOEFL）",
    ]


def test_v2_filters_match_same_grounded_facts_and_school_alias(client) -> None:
    resume_id = _save_v2_resume(client)
    response = client.post(
        "/v1/candidates/search",
        json={
            "highest_degree_in": ["bachelor"],
            "graduation_status": "fresh",
            "fresh_graduate_start_month": "2026-01",
            "fresh_graduate_end_month": "2027-12",
            "education_any_of": [
                {
                    "school_name_contains": ["北大"],
                    "major_contains": ["计算机"],
                    "institution_tiers_any_of": ["985"],
                    "min_gpa_percent": 90,
                    "max_rank_percent": 10,
                }
            ],
            "skill_categories_any_of": ["software"],
            "language_credentials_any_of": [
                {"credential_code": "cet4", "min_score": 500}
            ],
            "scholarship_status": "present",
            "scholarship_levels_any_of": ["national"],
            "competition_status": "present",
            "competition_award_status": "present",
            "leadership_any_of": [
                {"contexts_any_of": ["project_team"], "roles_any_of": ["组长"]}
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert [item["resume_id"] for item in response.json()["items"]] == [resume_id]
    evidence_types = {
        match["fact_type"] for match in response.json()["items"][0]["matched_evidence"]
    }
    assert {"education", "skill", "language", "scholarship", "experience"} <= evidence_types


def test_english_aliases_are_or_for_broad_keywords_but_precise_stays_literal(client) -> None:
    resume_id = _save_v2_resume(client)

    broad = client.post(
        "/v1/candidates/search",
        json={"keywords": ["CET-4"], "keyword_match_mode": "broad"},
    )
    assert broad.status_code == 200, broad.text
    assert [item["resume_id"] for item in broad.json()["items"]] == [resume_id]

    precise = client.post(
        "/v1/candidates/search",
        json={"keywords": ["大学英语四级"], "keyword_match_mode": "precise"},
    )
    assert precise.status_code == 200, precise.text
    assert precise.json()["items"] == []


def test_language_minimum_score_does_not_match_missing_or_lower_score(client) -> None:
    _save_v2_resume(client)
    response = client.post(
        "/v1/candidates/search",
        json={
            "language_credentials_any_of": [
                {"credential_code": "cet4", "min_score": 600},
                {"credential_code": "ielts", "min_score": 6.5},
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
