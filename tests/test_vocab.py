from sqlalchemy.exc import IntegrityError

from app.ai.crypto import encrypt_api_key
from app.ai.schemas import EssayFeedback, LLMCorrection
from app.auth.security import hash_password
from app.db import models
from app.documents import service
from app.vocab.service import (
    VocabValidationError,
    add_word_manually,
    delete_word,
    edit_word,
    mark_reviewed,
    search_words,
    upsert_suggested_word,
)


def _canned_feedback(corrections=None):
    return EssayFeedback(
        corrections=corrections or [],
        overall_score=80,
        grammar_score=75,
        vocab_score=70,
        structure_score=85,
        clarity_score=90,
        feedback_summary="Solid draft with room to grow.",
    )


class VocabSuggestingProvider:
    """Stands in for OpenAICompatibleProvider; always suggests one vocab word."""

    def __init__(self, api_key, base_url, model):
        pass

    def analyze(self, essay_text, local_findings, context):
        return _canned_feedback(
            [
                LLMCorrection(
                    category="vocab",
                    start_offset=0,
                    end_offset=4,
                    original_text="good",
                    suggested_text="commendable",
                    explanation="A stronger word choice.",
                    definition="Deserving praise or approval.",
                    example_sentence="Her commendable effort earned top marks.",
                )
            ]
        )


def _add_ai_settings(db_session, document):
    ai_settings = models.AISettings(
        user_id=document.user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)
    db_session.commit()


def test_upsert_suggested_word_creates_new_word(db_session, user):
    word = upsert_suggested_word(
        db_session,
        user_id=user.id,
        source_document_id=None,
        word="Meticulous",
        definition="Showing great attention to detail.",
        example_sentence="She kept meticulous notes.",
    )
    db_session.commit()

    assert word.times_suggested == 1
    assert word.mastered is False


def test_upsert_suggested_word_is_case_insensitive_and_bumps_count(db_session, user):
    upsert_suggested_word(
        db_session,
        user_id=user.id,
        source_document_id=None,
        word="Meticulous",
        definition="Showing great attention to detail.",
        example_sentence="She kept meticulous notes.",
    )
    db_session.commit()

    second = upsert_suggested_word(
        db_session,
        user_id=user.id,
        source_document_id=None,
        word="meticulous",
        definition="Showing great attention to detail.",
        example_sentence="A different example.",
    )
    db_session.commit()

    words = db_session.query(models.VocabWord).filter(models.VocabWord.user_id == user.id).all()
    assert len(words) == 1
    assert second.times_suggested == 2


def test_pipeline_adds_vocab_suggestion_to_library(db_session, document, monkeypatch):
    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", VocabSuggestingProvider)
    _add_ai_settings(db_session, document)

    service.submit_version(db_session, document, "good essay text")

    words = db_session.query(models.VocabWord).filter(models.VocabWord.user_id == document.user_id).all()
    assert len(words) == 1
    assert words[0].word == "commendable"
    assert words[0].definition == "Deserving praise or approval."
    assert words[0].source_document_id == document.id


def test_pipeline_skips_vocab_word_when_definition_missing(db_session, document, monkeypatch):
    class BareVocabProvider:
        def __init__(self, api_key, base_url, model):
            pass

        def analyze(self, essay_text, local_findings, context):
            return _canned_feedback(
                [
                    LLMCorrection(
                        category="vocab",
                        start_offset=0,
                        end_offset=4,
                        original_text="good",
                        suggested_text="commendable",
                        explanation="A stronger word choice.",
                    )
                ]
            )

    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", BareVocabProvider)
    _add_ai_settings(db_session, document)

    service.submit_version(db_session, document, "good essay text")

    words = db_session.query(models.VocabWord).filter(models.VocabWord.user_id == document.user_id).all()
    assert words == []


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def test_case_insensitive_dedup_is_enforced_at_the_db_level(db_session, user):
    db_session.add(
        models.VocabWord(user_id=user.id, word="Meticulous", definition="d", example_sentence="e")
    )
    db_session.commit()

    db_session.add(
        models.VocabWord(user_id=user.id, word="meticulous", definition="d2", example_sentence="e2")
    )
    try:
        db_session.commit()
        raise AssertionError("expected the case-insensitive unique index to reject the second row")
    except IntegrityError:
        db_session.rollback()


def test_add_word_manually_creates_and_dedupes(db_session, user):
    word, created = add_word_manually(db_session, user.id, "Meticulous", "Showing care.", "She was meticulous.")
    assert created is True

    word2, created2 = add_word_manually(db_session, user.id, "meticulous", "Showing care.", "Another example.")
    assert created2 is False
    assert word2.id == word.id
    assert word2.times_suggested == 2


def test_add_word_manually_validates_length(db_session, user):
    try:
        add_word_manually(db_session, user.id, "x" * 101, "d", "e")
        raise AssertionError("expected VocabValidationError")
    except VocabValidationError:
        pass


def test_edit_word_is_owner_scoped(db_session, user):
    word, _ = add_word_manually(db_session, user.id, "lucid", "clear", "A lucid explanation.")
    other = models.User(email="other-vocab-edit@example.com", password_hash="x", email_verified=True)
    db_session.add(other)
    db_session.commit()

    assert edit_word(db_session, other.id, word.id, "new def", "new example", None) is None
    assert edit_word(db_session, user.id, word.id, "new def", "new example", "note") is not None
    db_session.refresh(word)
    assert word.definition == "new def"
    assert word.notes == "note"


def test_mark_reviewed_sets_timestamp(db_session, user):
    word, _ = add_word_manually(db_session, user.id, "lucid", "clear", "A lucid explanation.")
    assert word.last_reviewed_at is None
    mark_reviewed(db_session, user.id, word.id)
    db_session.refresh(word)
    assert word.last_reviewed_at is not None


def test_delete_word_is_owner_scoped(db_session, user):
    word, _ = add_word_manually(db_session, user.id, "lucid", "clear", "A lucid explanation.")
    other = models.User(email="other-vocab-delete@example.com", password_hash="x", email_verified=True)
    db_session.add(other)
    db_session.commit()

    assert delete_word(db_session, other.id, word.id) is False
    assert delete_word(db_session, user.id, word.id) is True
    assert db_session.query(models.VocabWord).filter_by(id=word.id).first() is None


def test_search_words_paginates_and_filters(db_session, user):
    for i in range(30):
        add_word_manually(db_session, user.id, f"word{i:02d}", "d", "e")
    add_word_manually(db_session, user.id, "special", "d", "e")

    page1, total = search_words(db_session, user.id, "word", page=1, page_size=10)
    assert total == 30
    assert len(page1) == 10

    page4, total4 = search_words(db_session, user.id, "word", page=4, page_size=10)
    assert total4 == 30
    assert len(page4) == 0  # past the last page

    filtered, total_filtered = search_words(db_session, user.id, "special", page=1)
    assert total_filtered == 1
    assert filtered[0].word == "special"


def test_vocab_routes_require_login(client):
    response = client.get("/vocab", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    client.get("/login")  # acquire a valid CSRF cookie so the redirect check (not CSRF) is what's under test
    token = client.cookies.get("csrf_token")
    response = client.post(
        "/vocab",
        data={"word": "lucid", "definition": "clear", "example_sentence": "e", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_add_word_route_requires_csrf(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post(
        "/vocab",
        data={"word": "lucid", "definition": "clear", "example_sentence": "e", "csrf_token": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_add_word_route_creates_word(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/vocab",
        data={"word": "lucid", "definition": "clear", "example_sentence": "A lucid explanation.", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db_session.query(models.VocabWord).filter_by(user_id=user.id, word="lucid").count() == 1


def test_edit_and_delete_routes_are_owner_scoped(client, db_session, user):
    other = models.User(email="other-vocab-route@example.com", password_hash=hash_password("z"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_word, _ = add_word_manually(db_session, other.id, "opaque", "unclear", "An opaque answer.")

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    edit_response = client.post(
        f"/vocab/{other_word.id}/edit",
        data={"definition": "hacked", "example_sentence": "hacked", "csrf_token": token},
        follow_redirects=False,
    )
    delete_response = client.post(f"/vocab/{other_word.id}/delete", data={"csrf_token": token}, follow_redirects=False)

    assert edit_response.status_code == 303
    assert delete_response.status_code == 303
    db_session.refresh(other_word)
    assert other_word.definition == "unclear"  # untouched by another user's edit attempt
    assert db_session.query(models.VocabWord).filter_by(id=other_word.id).first() is not None  # not deleted


def test_vocab_search_route_paginates(client, db_session, user):
    for i in range(30):
        add_word_manually(db_session, user.id, f"word{i:02d}", "d", "e")

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/vocab?q=word&page=1")
    assert response.status_code == 200
    assert "Page 1 of 2" in response.text  # 30 matches at 25/page
