from app.ai.crypto import encrypt_api_key
from app.ai.schemas import EssayFeedback
from app.db import models
from app.documents import service


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
