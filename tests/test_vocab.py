from app.ai.crypto import encrypt_api_key
from app.ai.schemas import EssayFeedback, LLMCorrection
from app.db import models
from app.documents import service
from app.vocab.service import upsert_suggested_word


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
