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


def test_login_rejects_request_with_no_csrf_cookie(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")

    response = client.post(
        "/login",
        data={
            "email": user.email,
            "password": "correct-horse-battery-staple",
            "csrf_token": "attacker-supplied-value",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_login_rejects_csrf_token_that_does_not_match_cookie(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")

    client.get("/login")  # picks up a real csrf_token cookie
    response = client.post(
        "/login",
        data={
            "email": user.email,
            "password": "correct-horse-battery-staple",
            "csrf_token": "some-other-value-not-the-cookie",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_login_succeeds_with_csrf_token_matching_cookie(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")

    response = _login(client, user.email, "correct-horse-battery-staple")

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_vocab_toggle_mastered_rejects_mismatched_csrf_token(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    word = models.VocabWord(
        user_id=user.id,
        word="meticulous",
        definition="Showing great attention to detail.",
        example_sentence="She kept meticulous notes.",
    )
    db_session.add(word)
    db_session.commit()
    db_session.refresh(word)

    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post(
        f"/vocab/{word.id}/toggle-mastered",
        data={"csrf_token": "not-the-real-token"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    db_session.refresh(word)
    assert word.mastered is False


def test_vocab_toggle_mastered_succeeds_with_matching_csrf_token(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    word = models.VocabWord(
        user_id=user.id,
        word="meticulous",
        definition="Showing great attention to detail.",
        example_sentence="She kept meticulous notes.",
    )
    db_session.add(word)
    db_session.commit()
    db_session.refresh(word)

    _login(client, user.email, "correct-horse-battery-staple")

    token = client.cookies.get("csrf_token")
    response = client.post(
        f"/vocab/{word.id}/toggle-mastered",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(word)
    assert word.mastered is True


def test_settings_save_rejects_mismatched_csrf_token(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post(
        "/settings",
        data={
            "provider": "groq",
            "model_name": "llama-3.3-70b-versatile",
            "base_url": "",
            "api_key": "sk-fake-key",
            "csrf_token": "not-the-real-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_signup_rejects_mismatched_csrf_token(client, db_session):
    client.get("/signup")

    response = client.post(
        "/signup",
        data={
            "email": "new-user@example.com",
            "password": "correct-horse-battery-staple",
            "csrf_token": "not-the-real-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403
    created = db_session.query(models.User).filter(models.User.email == "new-user@example.com").first()
    assert created is None


def test_essay_submit_rejects_mismatched_csrf_token(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post(
        "/",
        data={
            "title": "My essay",
            "content": "Some essay text.",
            "csrf_token": "not-the-real-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_essay_submit_succeeds_with_matching_csrf_token(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    token = client.cookies.get("csrf_token")
    response = client.post(
        "/",
        data={
            "title": "My essay",
            "content": "Some essay text.",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
