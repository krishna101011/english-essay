from app.ai.crypto import encrypt_api_key
from app.auth.security import hash_password
from app.db import models
from app.documents import service


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


class FakeRewriteProvider:
    """Stands in for OpenAICompatibleProvider so tests never make real API calls."""

    calls = []

    def __init__(self, api_key, base_url, model):
        pass

    def rewrite(self, essay_text):
        FakeRewriteProvider.calls.append(essay_text)
        return f"Improved: {essay_text}"


def _add_ai_settings(db_session, user_id):
    settings = models.AISettings(
        user_id=user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(settings)
    db_session.commit()
    return settings


def _add_version(db_session, document, content="An essay about my summer vacation."):
    version = models.DocumentVersion(document_id=document.id, content=content, version_number=1)
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


def test_generate_rewrite_calls_ai_and_caches_result(client, db_session, user, document, monkeypatch):
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeRewriteProvider)
    FakeRewriteProvider.calls.clear()
    user.password_hash = hash_password("correct-horse-battery-staple")
    _add_ai_settings(db_session, user.id)
    version = _add_version(db_session, document)

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert len(FakeRewriteProvider.calls) == 1
    db_session.refresh(version)
    assert version.model_rewrite is not None
    assert version.model_rewrite.content == "Improved: An essay about my summer vacation."


def test_second_click_uses_cached_rewrite_without_calling_ai_again(client, db_session, user, document, monkeypatch):
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeRewriteProvider)
    FakeRewriteProvider.calls.clear()
    user.password_hash = hash_password("correct-horse-battery-staple")
    _add_ai_settings(db_session, user.id)
    version = _add_version(db_session, document)

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    first = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    second = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(FakeRewriteProvider.calls) == 1  # only the first click ever hit the AI


def test_regenerate_forces_a_new_ai_call(client, db_session, user, document, monkeypatch):
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeRewriteProvider)
    FakeRewriteProvider.calls.clear()
    user.password_hash = hash_password("correct-horse-battery-staple")
    _add_ai_settings(db_session, user.id)
    version = _add_version(db_session, document)

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    regenerate_response = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite/regenerate",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert regenerate_response.status_code == 200
    assert len(FakeRewriteProvider.calls) == 2  # explicit regenerate always re-calls the AI


def test_rewrite_rejects_mismatched_csrf_token(client, db_session, user, document, monkeypatch):
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeRewriteProvider)
    FakeRewriteProvider.calls.clear()
    user.password_hash = hash_password("correct-horse-battery-staple")
    _add_ai_settings(db_session, user.id)
    version = _add_version(db_session, document)

    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": "not-the-real-token"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert FakeRewriteProvider.calls == []
    db_session.refresh(version)
    assert version.model_rewrite is None


def test_rewrite_response_preserves_the_users_unsaved_draft(client, db_session, user, document, monkeypatch):
    # Regression test: generating (or regenerating) a model rewrite used to
    # re-render editor.html without the user's draft, so the textarea fell
    # back to the last *submitted* version's text - silently discarding any
    # edits made after submitting but before clicking the rewrite button.
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeRewriteProvider)
    FakeRewriteProvider.calls.clear()
    user.password_hash = hash_password("correct-horse-battery-staple")
    _add_ai_settings(db_session, user.id)
    version = _add_version(db_session, document, content="Submitted essay text.")

    db_session.add(
        models.WritingDraft(
            user_id=user.id,
            document_id=document.id,
            context_key=f"document:{document.id}",
            title=document.title,
            content="Edited essay text that was never resubmitted.",
            revision=1,
        )
    )
    db_session.commit()

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 200
    # The editable textarea should show the draft's content...
    assert ">Edited essay text that was never resubmitted.</textarea>" in response.text
    # ...not the last submitted version's content. (The submitted text
    # legitimately still appears elsewhere on the page, prefixed with
    # "Improved: ", inside the model-rewrite display - that's a different,
    # correct feature: rewrites are always of the submitted/scored version,
    # never an unsaved draft.)
    assert ">Submitted essay text.</textarea>" not in response.text


def test_editor_page_has_a_top_level_heading(client, db_session, user, document):
    # Regression test: editor.html (the app's primary screen, both for a
    # new essay and for an existing document) had no <h1> at all, jumping
    # straight to <h2>s - a screen-reader user navigating by heading level
    # got no page-level orientation.
    _add_version(db_session, document)
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    new_essay_page = client.get("/")
    assert "<h1" in new_essay_page.text

    existing_document_page = client.get(f"/documents/{document.id}")
    assert "<h1" in existing_document_page.text
    assert document.title in existing_document_page.text


def test_rewrite_rejects_request_for_another_users_document(client, db_session, user, document, monkeypatch):
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeRewriteProvider)
    FakeRewriteProvider.calls.clear()
    user.password_hash = hash_password("correct-horse-battery-staple")
    _add_ai_settings(db_session, user.id)
    version = _add_version(db_session, document)

    other_user = models.User(
        email="other@example.com",
        password_hash=hash_password("another-strong-password"),
        email_verified=True,
    )
    db_session.add(other_user)
    db_session.commit()

    _login(client, other_user.email, "another-strong-password")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/documents/{document.id}/versions/{version.id}/rewrite",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/history"
    assert FakeRewriteProvider.calls == []
    db_session.refresh(version)
    assert version.model_rewrite is None
