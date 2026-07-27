from app.db import models


def test_signup_with_honeypot_filled_is_silently_rejected(client, db_session, fake_email_sender):
    client.get("/signup")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/signup",
        data={
            "email": "bot@example.com",
            "password": "correct-horse-battery-staple",
            "website": "https://spam.example.com",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    created = db_session.query(models.User).filter(models.User.email == "bot@example.com").first()
    assert created is None
    assert len(fake_email_sender.sent) == 0


def test_signup_with_honeypot_field_present_but_empty_still_signs_up(client, db_session):
    client.get("/signup")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/signup",
        data={
            "email": "real-person@example.com",
            "password": "correct-horse-battery-staple",
            "website": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    created = db_session.query(models.User).filter(models.User.email == "real-person@example.com").first()
    assert created is not None


def test_signup_form_renders_honeypot_field(client):
    response = client.get("/signup")

    assert 'name="website"' in response.text
