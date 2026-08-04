from app.ai.crypto import encrypt_api_key
from app.ai.schemas import EssayFeedback
from app.auth.security import hash_password
from app.db import models
from app.documents import service


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


class ContextCapturingProvider:
    calls = []

    def __init__(self, api_key, base_url, model):
        pass

    def analyze(self, essay_text, local_findings, context):
        ContextCapturingProvider.calls.append(context)
        return EssayFeedback(
            corrections=[],
            overall_score=80,
            grammar_score=75,
            vocab_score=70,
            structure_score=85,
            clarity_score=90,
            feedback_summary="Thoughtful reflection.",
        )


def test_book_chapter_document_passes_book_context_to_ai(db_session, user, monkeypatch):
    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", ContextCapturingProvider)
    ContextCapturingProvider.calls.clear()

    ai_settings = models.AISettings(
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)

    doc = models.Document(
        user_id=user.id,
        type=models.DocumentType.book_chapter,
        title="Chapter 3 reflection",
        book_title="Great Expectations",
        author="Charles Dickens",
    )
    db_session.add(doc)
    db_session.commit()

    service.submit_version(db_session, doc, "Pip's journey continues to surprise me.")

    assert len(ContextCapturingProvider.calls) == 1
    context = ContextCapturingProvider.calls[0]
    assert context["type"] == "book_chapter"
    assert context["book_title"] == "Great Expectations"
    assert context["author"] == "Charles Dickens"


def test_oversized_book_title_is_rejected(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/",
        data={
            "title": "Chapter reflection",
            "content": "word " * 25,
            "doc_type": "book_chapter",
            "book_title": "x" * 256,
            "author": "Someone",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Book title must be" in response.text


def test_oversized_author_is_rejected(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/",
        data={
            "title": "Chapter reflection",
            "content": "word " * 25,
            "doc_type": "book_chapter",
            "book_title": "Great Expectations",
            "author": "x" * 256,
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Author must be" in response.text
