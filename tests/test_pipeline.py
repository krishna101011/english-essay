from app.ai.crypto import encrypt_api_key
from app.ai.schemas import EssayFeedback, LLMCorrection
from app.db import models
from app.documents import service


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


class FakeProvider:
    """Stands in for OpenAICompatibleProvider so tests never make real API calls."""

    calls = []

    def __init__(self, api_key, base_url, model):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def analyze(self, essay_text, local_findings, context):
        FakeProvider.calls.append({"essay_text": essay_text, "local_findings": local_findings, "context": context})
        return _canned_feedback(
            [
                LLMCorrection(
                    category="sentence_structure",
                    start_offset=0,
                    end_offset=len(essay_text),
                    original_text=essay_text,
                    suggested_text=essay_text,
                    explanation="Consider varying sentence length.",
                )
            ]
        )


class FailingProvider:
    def __init__(self, api_key, base_url, model):
        pass

    def analyze(self, essay_text, local_findings, context):
        raise RuntimeError("provider unreachable")


class DuplicatingProvider:
    """Returns multiple corrections for the exact same span in a single
    response, the way a real AI response sometimes does."""

    def __init__(self, api_key, base_url, model):
        pass

    def analyze(self, essay_text, local_findings, context):
        return _canned_feedback(
            [
                LLMCorrection(
                    category="vocab",
                    start_offset=10,
                    end_offset=25,
                    original_text="very very good",
                    suggested_text="delightful",
                    explanation="Replacing repetitive modifiers improves the sophistication of your writing.",
                ),
                LLMCorrection(
                    category="vocab",
                    start_offset=10,
                    end_offset=25,
                    original_text="very very good",
                    suggested_text="delightful",
                    explanation="Replacing informal, repeated modifiers makes your writing sound more sophisticated.",
                ),
            ]
        )


class QueuedProvider:
    """Hands out one canned EssayFeedback per call, in order, so a test can
    simulate what a real provider would do differently across submissions
    (e.g. only flagging within the changed-paragraph range on a revision)."""

    responses = []

    def __init__(self, api_key, base_url, model):
        pass

    def analyze(self, essay_text, local_findings, context):
        return QueuedProvider.responses.pop(0)


def test_submit_version_without_java_or_ai_settings_degrades_gracefully(db_session, document, monkeypatch):
    def fake_check_text(text):
        raise service.JavaNotFoundError("java not found")

    monkeypatch.setattr(service, "check_text", fake_check_text)

    result = service.submit_version(db_session, document, "Some essay text.")

    assert result.local_error == "java not found"
    assert result.ai_error == (
        "No AI provider configured. Add one in Settings to get sentence-structure and vocabulary feedback."
    )
    assert result.version.version_number == 1
    assert result.version.corrections == []
    assert result.version.score is None


def test_submit_version_saves_local_findings_as_corrections(db_session, document, monkeypatch):
    monkeypatch.setattr(
        service,
        "check_text",
        lambda text: [
            {
                "category": "spelling",
                "start_offset": 0,
                "end_offset": 4,
                "original_text": "Helo",
                "suggested_text": "Hello",
                "explanation": "Possible spelling mistake.",
            }
        ],
    )

    result = service.submit_version(db_session, document, "Helo world.")

    assert len(result.version.corrections) == 1
    correction = result.version.corrections[0]
    assert correction.category == models.CorrectionCategory.spelling
    assert correction.source == models.CorrectionSource.local
    assert correction.suggested_text == "Hello"


def test_submit_version_with_configured_ai_provider_saves_llm_corrections_and_score(
    db_session, document, monkeypatch
):
    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FakeProvider)
    FakeProvider.calls.clear()

    ai_settings = models.AISettings(
        user_id=document.user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)
    db_session.commit()

    result = service.submit_version(db_session, document, "An essay about dogs.")

    assert result.ai_error is None
    assert len(FakeProvider.calls) == 1
    assert result.version.score is not None
    assert result.version.score.overall_score == 80
    llm_corrections = [c for c in result.version.corrections if c.source == models.CorrectionSource.llm]
    assert len(llm_corrections) == 1
    assert llm_corrections[0].category == models.CorrectionCategory.sentence_structure


def test_submit_version_ai_failure_still_keeps_local_results(db_session, document, monkeypatch):
    monkeypatch.setattr(
        service,
        "check_text",
        lambda text: [
            {
                "category": "grammar",
                "start_offset": 0,
                "end_offset": 3,
                "original_text": "Foo",
                "suggested_text": "Bar",
                "explanation": "Grammar issue.",
            }
        ],
    )
    monkeypatch.setattr(service, "OpenAICompatibleProvider", FailingProvider)

    ai_settings = models.AISettings(
        user_id=document.user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)
    db_session.commit()

    result = service.submit_version(db_session, document, "Foo essay.")

    assert result.ai_error is not None
    assert "provider unreachable" in result.ai_error
    assert result.version.score is None
    assert len(result.version.corrections) == 1
    assert result.version.corrections[0].source == models.CorrectionSource.local


def test_revision_carries_forward_llm_corrections_for_unchanged_paragraphs(db_session, document, monkeypatch):
    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", QueuedProvider)

    ai_settings = models.AISettings(
        user_id=document.user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)
    db_session.commit()

    first_content = "Short intro.\n\nUnchanged paragraph stays the same."
    unchanged_start_v1 = first_content.index("Unchanged paragraph")
    unchanged_end_v1 = unchanged_start_v1 + len("Unchanged paragraph")

    # v1: the provider flags a vocab issue inside the paragraph that will
    # later remain untouched. v2: it finds nothing new in the changed range.
    QueuedProvider.responses = [
        _canned_feedback(
            [
                LLMCorrection(
                    category="vocab",
                    start_offset=unchanged_start_v1,
                    end_offset=unchanged_end_v1,
                    original_text="Unchanged paragraph",
                    suggested_text="Static paragraph",
                    explanation="Consider a stronger word choice.",
                )
            ]
        ),
        _canned_feedback([]),
    ]

    first_result = service.submit_version(db_session, document, first_content)
    assert first_result.version.version_number == 1
    assert len(first_result.version.corrections) == 1

    second_content = "Much longer introductory paragraph now.\n\nUnchanged paragraph stays the same."
    second_result = service.submit_version(db_session, document, second_content)

    assert second_result.version.version_number == 2
    llm_corrections = [c for c in second_result.version.corrections if c.source == models.CorrectionSource.llm]
    assert len(llm_corrections) == 1

    carried = llm_corrections[0]
    assert carried.suggested_text == "Static paragraph"
    unchanged_start_v2 = second_content.index("Unchanged paragraph")
    assert carried.start_offset == unchanged_start_v2
    assert carried.start_offset != unchanged_start_v1  # offset was remapped, not just copied verbatim


def test_submit_version_deduplicates_repeated_corrections_from_a_single_ai_response(db_session, document, monkeypatch):
    # Regression test: a single AI response returning two corrections for
    # the exact same span (same start_offset/end_offset/category, different
    # wording) must collapse to one persisted Correction row, not two.
    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", DuplicatingProvider)

    ai_settings = models.AISettings(
        user_id=document.user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)
    db_session.commit()

    result = service.submit_version(db_session, document, "An essay with very very good writing in it.")

    llm_corrections = [c for c in result.version.corrections if c.source == models.CorrectionSource.llm]
    assert len(llm_corrections) == 1
    assert llm_corrections[0].suggested_text == "delightful"


def test_submit_version_deduplicates_carried_forward_correction_against_fresh_duplicate(
    db_session, document, monkeypatch
):
    # Regression test for the actual bug found in production data: the AI
    # doesn't always honor "only emit corrections within
    # changed_paragraph_ranges" for unchanged paragraphs, so a revision can
    # carry forward a correction for an unchanged span AND receive a fresh
    # AI suggestion for that same span in the same response. Without
    # dedup, both get persisted - and since the next revision carries
    # forward whatever this version just persisted, the duplicate would
    # compound on every subsequent submission.
    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", QueuedProvider)

    ai_settings = models.AISettings(
        user_id=document.user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(ai_settings)
    db_session.commit()

    first_content = "Short intro.\n\nUnchanged paragraph stays the same, it is very very good."
    span_start_v1 = first_content.index("very very good")
    span_end_v1 = span_start_v1 + len("very very good")

    QueuedProvider.responses = [
        _canned_feedback(
            [
                LLMCorrection(
                    category="vocab",
                    start_offset=span_start_v1,
                    end_offset=span_end_v1,
                    original_text="very very good",
                    suggested_text="delightful",
                    explanation="Replacing repetitive modifiers improves the sophistication of your writing.",
                )
            ]
        ),
    ]
    first_result = service.submit_version(db_session, document, first_content)
    assert len(first_result.version.corrections) == 1

    second_content = "Much longer introductory paragraph now.\n\nUnchanged paragraph stays the same, it is very very good."
    span_start_v2 = second_content.index("very very good")
    span_end_v2 = span_start_v2 + len("very very good")

    # v2's fresh AI response re-suggests the same span (worded differently)
    # even though it falls inside the untouched paragraph - exactly what
    # was observed happening against the real provider.
    QueuedProvider.responses = [
        _canned_feedback(
            [
                LLMCorrection(
                    category="vocab",
                    start_offset=span_start_v2,
                    end_offset=span_end_v2,
                    original_text="very very good",
                    suggested_text="delightful",
                    explanation="Replacing informal, repeated modifiers makes your writing sound more sophisticated.",
                )
            ]
        ),
    ]
    second_result = service.submit_version(db_session, document, second_content)

    llm_corrections = [c for c in second_result.version.corrections if c.source == models.CorrectionSource.llm]
    assert len(llm_corrections) == 1
    assert llm_corrections[0].start_offset == span_start_v2
