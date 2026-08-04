from app.ai.crypto import encrypt_api_key
from app.ai.registry import available_providers, resolve_provider_base_url
from app.auth.security import hash_password
from app.db import models


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_security_headers_are_sent(client):
    response = client.get("/login")

    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_custom_providers_are_disabled_by_default():
    assert "custom" not in available_providers()
    try:
        resolve_provider_base_url("custom", "https://example.com/v1")
    except ValueError as exc:
        assert "disabled" in str(exc)
    else:  # pragma: no cover - documents the security boundary clearly
        raise AssertionError("custom endpoints must be disabled by default")


def test_approved_provider_ignores_tampered_base_url():
    assert resolve_provider_base_url("groq", "http://127.0.0.1:8000") == "https://api.groq.com/openai/v1"


def test_oversized_title_is_rejected_and_draft_is_preserved(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")
    content = "A draft the student should not lose."

    response = client.post(
        "/",
        data={"title": "x" * 201, "content": content, "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Title must be 200 characters or fewer." in response.text
    assert content in response.text


def test_essay_submission_is_rate_limited(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    statuses = [
        client.post(
            "/",
            data={"title": "x" * 201, "content": "Draft", "csrf_token": token},
            follow_redirects=False,
        ).status_code
        for _ in range(13)
    ]

    assert statuses[:12] == [400] * 12
    assert statuses[12] == 429


def test_settings_save_uses_server_approved_url(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/settings",
        data={
            "provider": "groq",
            "model_name": "llama-3.3-70b-versatile",
            "base_url": "http://127.0.0.1:8000/metadata",
            "api_key": "sk-safe-test-key",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    settings = db_session.query(models.AISettings).filter_by(user_id=user.id).one()
    assert settings.base_url == "https://api.groq.com/openai/v1"
