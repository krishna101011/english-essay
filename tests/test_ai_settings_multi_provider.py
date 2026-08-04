from app.ai.crypto import encrypt_api_key, mask_api_key
from app.ai.registry import MAX_AI_PROVIDERS_PER_USER
from app.auth.security import hash_password
from app.db import models


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def _add_settings(db_session, user, provider="groq", priority=0, model_name="m"):
    settings = models.AISettings(
        user_id=user.id,
        provider=provider,
        encrypted_api_key=encrypt_api_key("sk-fake"),
        model_name=model_name,
        base_url="https://api.groq.com/openai/v1",
        priority=priority,
    )
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    return settings


def test_add_provider_route_creates_row_with_next_priority(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    for i in range(2):
        response = client.post(
            "/settings",
            data={
                "provider": "groq",
                "model_name": f"model-{i}",
                "base_url": "",
                "api_key": "sk-fake",
                "label": f"key {i}",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    rows = db_session.query(models.AISettings).filter_by(user_id=user.id).order_by(models.AISettings.priority).all()
    assert [r.model_name for r in rows] == ["model-0", "model-1"]
    assert [r.priority for r in rows] == [0, 1]


def test_add_provider_enforces_max_cap(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    for i in range(MAX_AI_PROVIDERS_PER_USER):
        _add_settings(db_session, user, priority=i, model_name=f"existing-{i}")

    response = client.post(
        "/settings",
        data={"provider": "groq", "model_name": "one-too-many", "base_url": "", "api_key": "sk-fake", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert f"at most {MAX_AI_PROVIDERS_PER_USER}" in response.text
    assert db_session.query(models.AISettings).filter_by(user_id=user.id).count() == MAX_AI_PROVIDERS_PER_USER


def test_add_provider_requires_api_key(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/settings",
        data={"provider": "groq", "model_name": "m", "base_url": "", "api_key": "", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "API key is required" in response.text


def test_edit_provider_updates_fields_and_is_owner_scoped(client, db_session, user):
    other = models.User(email="other-ai-settings@example.com", password_hash=hash_password("z"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_row = _add_settings(db_session, other, model_name="other-model")

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    cross_user_response = client.post(
        f"/settings/{other_row.id}/edit",
        data={"model_name": "hacked", "base_url": "", "label": "", "csrf_token": token},
        follow_redirects=False,
    )
    assert cross_user_response.status_code == 303
    db_session.refresh(other_row)
    assert other_row.model_name == "other-model"  # untouched

    own_row = _add_settings(db_session, user, model_name="my-model")
    response = client.post(
        f"/settings/{own_row.id}/edit",
        data={"model_name": "my-model-v2", "base_url": "", "label": "primary", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(own_row)
    assert own_row.model_name == "my-model-v2"
    assert own_row.label == "primary"


def test_edit_provider_blank_api_key_keeps_existing_key(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")
    row = _add_settings(db_session, user)
    original_key = row.encrypted_api_key

    client.post(
        f"/settings/{row.id}/edit",
        data={"model_name": "m2", "base_url": "", "api_key": "", "label": "", "csrf_token": token},
        follow_redirects=False,
    )

    db_session.refresh(row)
    assert row.encrypted_api_key == original_key


def test_delete_provider_is_owner_scoped(client, db_session, user):
    other = models.User(email="other-ai-delete@example.com", password_hash=hash_password("z"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_row = _add_settings(db_session, other)

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(f"/settings/{other_row.id}/delete", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert db_session.query(models.AISettings).filter_by(id=other_row.id).first() is not None  # not deleted

    own_row = _add_settings(db_session, user)
    client.post(f"/settings/{own_row.id}/delete", data={"csrf_token": token}, follow_redirects=False)
    assert db_session.query(models.AISettings).filter_by(id=own_row.id).first() is None


def test_toggle_active_flips_state_and_is_owner_scoped(client, db_session, user):
    row = _add_settings(db_session, user)
    assert row.is_active is True

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    client.post(f"/settings/{row.id}/toggle-active", data={"csrf_token": token}, follow_redirects=False)
    db_session.refresh(row)
    assert row.is_active is False

    client.post(f"/settings/{row.id}/toggle-active", data={"csrf_token": token}, follow_redirects=False)
    db_session.refresh(row)
    assert row.is_active is True


def test_move_provider_swaps_priority_with_neighbor(client, db_session, user):
    first = _add_settings(db_session, user, priority=0, model_name="first")
    second = _add_settings(db_session, user, priority=1, model_name="second")

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    client.post(f"/settings/{second.id}/move", data={"direction": "up", "csrf_token": token}, follow_redirects=False)

    db_session.refresh(first)
    db_session.refresh(second)
    assert second.priority < first.priority


def test_move_provider_is_a_noop_at_the_boundary(client, db_session, user):
    first = _add_settings(db_session, user, priority=0, model_name="first")

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(f"/settings/{first.id}/move", data={"direction": "up", "csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    db_session.refresh(first)
    assert first.priority == 0


def test_test_connection_route_is_owner_scoped(client, db_session, user):
    other = models.User(email="other-ai-test@example.com", password_hash=hash_password("z"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_row = _add_settings(db_session, other)

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(f"/settings/{other_row.id}/test", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 400
    assert "no longer exists" in response.text


def test_settings_mutation_routes_require_csrf(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    row = _add_settings(db_session, user)

    for path, data in [
        ("/settings", {"provider": "groq", "model_name": "m", "base_url": "", "api_key": "sk-fake"}),
        (f"/settings/{row.id}/edit", {"model_name": "m2", "base_url": ""}),
        (f"/settings/{row.id}/delete", {}),
        (f"/settings/{row.id}/toggle-active", {}),
        (f"/settings/{row.id}/move", {"direction": "up"}),
        (f"/settings/{row.id}/test", {}),
    ]:
        response = client.post(path, data={**data, "csrf_token": "wrong"}, follow_redirects=False)
        assert response.status_code == 403, path


def test_settings_page_lists_masked_key_and_priority_order(client, db_session, user):
    _add_settings(db_session, user, priority=1, model_name="second")
    _add_settings(db_session, user, priority=0, model_name="first")

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/settings")

    assert response.status_code == 200
    assert mask_api_key("sk-fake") in response.text
    first_pos = response.text.index("first")
    second_pos = response.text.index("second")
    assert first_pos < second_pos  # priority 0 renders before priority 1
