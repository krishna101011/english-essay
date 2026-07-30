from app.ai.crypto import mask_api_key
from app.auth.security import hash_password


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


def test_api_key_saved_in_one_session_loads_back_in_a_separate_session(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()

    _login(client, user.email, "correct-horse-battery-staple")
    save_token = _csrf(client, "/settings")
    response = client.post(
        "/settings",
        data={
            "provider": "groq",
            "model_name": "llama-3.3-70b-versatile",
            "base_url": "",
            "api_key": "sk-persisted-secret-key",
            "csrf_token": save_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Simulate a separate request/session: drop all cookies (session +
    # csrf) and log back in from scratch, then confirm the key the first
    # session saved is still there and decrypts correctly.
    client.cookies.clear()
    _login(client, user.email, "correct-horse-battery-staple")

    page = client.get("/settings")
    assert page.status_code == 200
    assert mask_api_key("sk-persisted-secret-key") in page.text
