from app.auth.security import hash_password


def _csrf(client, path):
    client.get(path)
    return client.cookies.get("csrf_token")


def test_login_is_rate_limited_per_ip(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    token = _csrf(client, "/login")

    statuses = []
    for _ in range(11):
        response = client.post(
            "/login",
            data={"email": user.email, "password": "wrong-password", "csrf_token": token},
            follow_redirects=False,
        )
        statuses.append(response.status_code)

    assert statuses[:10] == [400] * 10
    assert statuses[10] == 429


def test_signup_is_rate_limited_per_ip(client):
    token = _csrf(client, "/signup")

    statuses = []
    for i in range(6):
        response = client.post(
            "/signup",
            data={
                "email": f"user{i}@example.com",
                "password": "short",
                "website": "",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        statuses.append(response.status_code)

    assert statuses[:5] == [400] * 5
    assert statuses[5] == 429


def test_forgot_password_is_rate_limited_per_ip(client):
    token = _csrf(client, "/forgot-password")

    statuses = []
    for _ in range(6):
        response = client.post(
            "/forgot-password",
            data={"email": "nobody@example.com", "csrf_token": token},
            follow_redirects=False,
        )
        statuses.append(response.status_code)

    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429
