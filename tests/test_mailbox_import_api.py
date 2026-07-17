from __future__ import annotations


def test_mailbox_configuration_never_returns_the_authorization_code(client) -> None:
    initial = client.get("/v1/mailbox/config")
    assert initial.status_code == 200, initial.text
    assert initial.json()["configured"] is False

    saved = client.put(
        "/v1/mailbox/config",
        json={
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "email_address": "recruiting@example.test",
            "mailbox": "INBOX",
            "password": "test-authorization-code",
            "enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["configured"] is True
    assert payload["password_configured"] is True
    assert "password" not in payload
    assert "test-authorization-code" not in saved.text

    fetched = client.get("/v1/mailbox/config")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["email_address"] == "recruiting@example.test"
    assert "test-authorization-code" not in fetched.text


def test_html_resume_upload_is_preserved_and_served_as_html(client) -> None:
    response = client.post(
        "/v1/resumes/upload",
        files={
            "file": (
                "candidate.html",
                b"<html><body><h1>Candidate</h1><p>Python FastAPI machine learning engineer</p></body></html>",
                "text/html",
            )
        },
    )
    assert response.status_code == 200, response.text
    resume_id = response.json()["resume_id"]

    original = client.get(f"/v1/resumes/{resume_id}/original-file")
    assert original.status_code == 200, original.text
    assert original.headers["content-type"].startswith("text/html")
    assert b"Candidate" in original.content
