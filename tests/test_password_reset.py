from app.auth.security import hash_password, verify_password
from app.auth.tokens import create_password_reset_token
from app.db import models


def _csrf(client, path):
    client.get(path)
    return client.cookies.get("csrf_token")


def _login(client, email, password):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_forgot_password_sends_email_for_existing_user(client, user, fake_email_sender):
    token = _csrf(client, "/forgot-password")

    response = client.post(
        "/forgot-password",
        data={"email": user.email, "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0]["to"] == user.email
    assert "reset-password?token=" in fake_email_sender.sent[0]["body"]


def test_forgot_password_gives_generic_message_for_unknown_email(client, fake_email_sender):
    token = _csrf(client, "/forgot-password")

    response = client.post(
        "/forgot-password",
        data={"email": "nobody-here@example.com", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "If an account with that email exists" in response.text
    assert len(fake_email_sender.sent) == 0


def test_reset_password_with_valid_token_changes_password(client, db_session, user):
    reset_token = create_password_reset_token(db_session, user.id)
    db_session.commit()

    token = _csrf(client, f"/reset-password?token={reset_token.token}")
    response = client.post(
        "/reset-password",
        data={"token": reset_token.token, "password": "brand-new-password", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    db_session.refresh(user)
    assert verify_password("brand-new-password", user.password_hash) is True


def test_reset_password_token_cannot_be_reused(client, db_session, user):
    reset_token = create_password_reset_token(db_session, user.id)
    db_session.commit()

    token = _csrf(client, f"/reset-password?token={reset_token.token}")
    client.post(
        "/reset-password",
        data={"token": reset_token.token, "password": "first-new-password", "csrf_token": token},
        follow_redirects=False,
    )
    second = client.post(
        "/reset-password",
        data={"token": reset_token.token, "password": "second-new-password", "csrf_token": token},
        follow_redirects=False,
    )

    assert second.status_code == 400
    db_session.refresh(user)
    assert verify_password("first-new-password", user.password_hash) is True


def test_reset_password_with_invalid_token_fails(client):
    token = _csrf(client, "/reset-password?token=bogus")
    response = client.post(
        "/reset-password",
        data={"token": "bogus", "password": "brand-new-password", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "invalid" in response.text.lower() or "expired" in response.text.lower()


def test_can_log_in_with_new_password_after_reset(client, db_session, user):
    user.password_hash = hash_password("old-password-123")
    db_session.commit()

    reset_token = create_password_reset_token(db_session, user.id)
    db_session.commit()

    token = _csrf(client, f"/reset-password?token={reset_token.token}")
    client.post(
        "/reset-password",
        data={"token": reset_token.token, "password": "shiny-new-password", "csrf_token": token},
        follow_redirects=False,
    )

    old_login = _login(client, user.email, "old-password-123")
    assert old_login.status_code == 400

    new_login = _login(client, user.email, "shiny-new-password")
    assert new_login.status_code == 303
    assert new_login.headers["location"] == "/"
