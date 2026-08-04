import pytest

import app.auth.routes as auth_routes
from app.auth.security import hash_password
from app.auth.tokens import create_email_verification_token
from app.db import models


def _get_csrf(client, path):
    client.get(path)
    return client.cookies.get("csrf_token")


def test_signup_rolls_back_user_if_sending_verification_email_fails(client, db_session, monkeypatch):
    class BoomSender:
        def send(self, to, subject, body):
            raise RuntimeError("smtp boom")

    monkeypatch.setattr(auth_routes, "get_email_sender", lambda: BoomSender())

    token = _get_csrf(client, "/signup")

    with pytest.raises(RuntimeError):
        client.post(
            "/signup",
            data={
                "email": "smoketest-persist@example.com",
                "password": "correct-horse-battery-staple",
                "website": "",
                "csrf_token": token,
            },
            follow_redirects=False,
        )

    orphaned_user = (
        db_session.query(models.User).filter(models.User.email == "smoketest-persist@example.com").first()
    )
    assert orphaned_user is None


def test_signup_sends_verification_email(client, db_session, fake_email_sender):
    token = _get_csrf(client, "/signup")

    response = client.post(
        "/signup",
        data={
            "email": "new-user@example.com",
            "password": "correct-horse-battery-staple",
            "website": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(fake_email_sender.sent) == 1
    message = fake_email_sender.sent[0]
    assert message["to"] == "new-user@example.com"
    assert "verify-email?token=" in message["body"]

    new_user = db_session.query(models.User).filter(models.User.email == "new-user@example.com").first()
    assert new_user is not None
    assert new_user.email_verified is False


def test_verify_email_with_valid_token_marks_user_verified(client, db_session, unverified_user):
    token = create_email_verification_token(db_session, unverified_user.id)
    db_session.commit()

    response = client.get(f"/verify-email?token={token.token}")

    assert response.status_code == 200
    assert "Email verified" in response.text
    db_session.refresh(unverified_user)
    assert unverified_user.email_verified is True


def test_verify_email_with_invalid_token_fails(client, unverified_user):
    response = client.get("/verify-email?token=not-a-real-token")

    assert response.status_code == 400
    assert "invalid" in response.text.lower() or "expired" in response.text.lower()


def test_verify_email_token_cannot_be_reused(client, db_session, unverified_user):
    token = create_email_verification_token(db_session, unverified_user.id)
    db_session.commit()

    first = client.get(f"/verify-email?token={token.token}")
    second = client.get(f"/verify-email?token={token.token}")

    assert first.status_code == 200
    assert second.status_code == 400


def _login(client, email, password):
    token = _get_csrf(client, "/login")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_unverified_user_cannot_create_essay(client, unverified_user):
    unverified_user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, unverified_user.email, "correct-horse-battery-staple")

    token = client.cookies.get("csrf_token")
    response = client.post(
        "/",
        data={"title": "My essay", "content": "Some essay text.", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_unverified_user_sees_verification_banner_on_editor_page(client, unverified_user):
    unverified_user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, unverified_user.email, "correct-horse-battery-staple")

    response = client.get("/")

    assert response.status_code == 200
    assert "Verify your email" in response.text


def test_unverified_user_can_still_log_in(client, unverified_user):
    unverified_user.password_hash = hash_password("correct-horse-battery-staple")

    response = _login(client, unverified_user.email, "correct-horse-battery-staple")

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_resend_verification_sends_a_new_email(client, db_session, unverified_user, fake_email_sender):
    unverified_user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, unverified_user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post("/resend-verification", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/?verification=sent"
    assert len(fake_email_sender.sent) == 1


def test_resend_verification_is_rate_limited_by_cooldown(client, db_session, unverified_user, fake_email_sender):
    unverified_user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, unverified_user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    client.post("/resend-verification", data={"csrf_token": token}, follow_redirects=False)
    second = client.post("/resend-verification", data={"csrf_token": token}, follow_redirects=False)

    assert second.status_code == 303
    assert second.headers["location"] == "/?verification=cooldown"
    assert len(fake_email_sender.sent) == 1  # cooldown blocked the second send


def test_resend_verification_requires_login(client):
    token = _get_csrf(client, "/login")
    response = client.post("/resend-verification", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_resend_verification_is_a_noop_for_already_verified_users(client, user, fake_email_sender):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post("/resend-verification", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert len(fake_email_sender.sent) == 0


def test_verified_user_can_create_essay(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    token = client.cookies.get("csrf_token")
    response = client.post(
        "/",
        data={"title": "My essay", "content": "Some essay text.", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 200
