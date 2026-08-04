import json
from datetime import date

from app.ai.crypto import encrypt_api_key
from app.ai.schemas import PracticeExerciseBatch, PracticeExerciseItem
from app.auth.security import hash_password
from app.db import models
from app.db.models import CorrectionCategory, CorrectionSource
from app.learning import practice as practice_module
from app.learning.practice import DEFAULT_CATEGORIES, MAX_EXERCISES_PER_BATCH, generate_ai_exercises, generate_local_exercises, submit_completion
from app.learning.progress import MISTAKE_THRESHOLD

FIXED_DAY = date(2024, 5, 1)


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def _ai_settings(db_session, user):
    settings = models.AISettings(
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    db_session.add(settings)
    db_session.commit()
    return settings


def test_generate_local_exercises_is_deterministic_and_idempotent(db_session, user):
    first = generate_local_exercises(db_session, user.id, today=FIXED_DAY)
    second = generate_local_exercises(db_session, user.id, today=FIXED_DAY)

    assert [e.id for e in first] == [e.id for e in second]
    total = db_session.query(models.PracticeExercise).filter_by(user_id=user.id).count()
    assert total == len(first)  # regenerating the same day did not create duplicates


def test_generate_local_exercises_falls_back_to_default_categories_with_no_history(db_session, user):
    exercises = generate_local_exercises(db_session, user.id, today=FIXED_DAY)
    categories = {json.loads(e.source_categories_json)[0] for e in exercises}
    assert categories == set(DEFAULT_CATEGORIES)


def test_generate_local_exercises_respects_batch_size_cap(db_session, user, document):
    version = models.DocumentVersion(document_id=document.id, content="word " * 25, version_number=1)
    db_session.add(version)
    db_session.commit()
    for category in CorrectionCategory:
        for i in range(MISTAKE_THRESHOLD):
            db_session.add(
                models.Correction(
                    version_id=version.id,
                    category=category,
                    start_offset=i,
                    end_offset=i + 1,
                    original_text="a",
                    suggested_text="b",
                    explanation="x",
                    source=CorrectionSource.local,
                )
            )
    db_session.commit()

    exercises = generate_local_exercises(db_session, user.id, today=FIXED_DAY)
    assert len(exercises) <= MAX_EXERCISES_PER_BATCH


class _FakePracticeProvider:
    call_count = 0

    def __init__(self, api_key, base_url, model):
        pass

    def generate_practice_exercises(self, categories):
        _FakePracticeProvider.call_count += 1
        return PracticeExerciseBatch(
            exercises=[
                PracticeExerciseItem(category=c, prompt=f"Prompt for {c}", answer="answer", explanation="because")
                for c in categories
            ]
        )


class _MalformedPracticeProvider:
    def __init__(self, api_key, base_url, model):
        pass

    def generate_practice_exercises(self, categories):
        raise ValueError("malformed JSON from provider")


def test_generate_ai_exercises_stores_only_validated_fields(db_session, user, monkeypatch):
    monkeypatch.setattr(practice_module, "OpenAICompatibleProvider", _FakePracticeProvider)
    _ai_settings(db_session, user)

    rows, error = generate_ai_exercises(db_session, user.id, categories=["grammar", "vocab"], today=FIXED_DAY)

    assert error is None
    assert {r.prompt for r in rows} == {"Prompt for grammar", "Prompt for vocab"}
    assert all(r.ai_generated for r in rows)


def test_generate_ai_exercises_handles_malformed_output_gracefully(db_session, user, monkeypatch):
    monkeypatch.setattr(practice_module, "OpenAICompatibleProvider", _MalformedPracticeProvider)
    _ai_settings(db_session, user)

    rows, error = generate_ai_exercises(db_session, user.id, categories=["grammar"], today=FIXED_DAY)

    assert rows == []
    assert error is not None
    assert db_session.query(models.PracticeExercise).filter_by(user_id=user.id).count() == 0


def test_generate_ai_exercises_is_idempotent_and_does_not_recall_provider(db_session, user, monkeypatch):
    _FakePracticeProvider.call_count = 0
    monkeypatch.setattr(practice_module, "OpenAICompatibleProvider", _FakePracticeProvider)
    _ai_settings(db_session, user)

    generate_ai_exercises(db_session, user.id, categories=["grammar"], today=FIXED_DAY)
    assert _FakePracticeProvider.call_count == 1

    generate_ai_exercises(db_session, user.id, categories=["grammar"], today=FIXED_DAY)
    assert _FakePracticeProvider.call_count == 1  # retried request reused the existing row instead of re-calling


def test_generate_ai_exercises_with_no_provider_configured(db_session, user):
    rows, error = generate_ai_exercises(db_session, user.id, categories=["grammar"], today=FIXED_DAY)

    assert rows == []
    assert error == "Add an AI provider in Settings to generate AI practice exercises."


def test_submit_completion_grades_case_insensitively(db_session, user):
    exercise = generate_local_exercises(db_session, user.id, today=FIXED_DAY)[0]

    _, correct = submit_completion(db_session, user.id, exercise.id, exercise.answer.upper())
    assert correct is True

    _, correct = submit_completion(db_session, user.id, exercise.id, "definitely wrong")
    assert correct is False


def test_submit_completion_rejects_other_users_exercise(db_session, user):
    other = models.User(email="other-practice@example.com", password_hash="x", email_verified=True)
    db_session.add(other)
    db_session.commit()
    exercise = generate_local_exercises(db_session, other.id, today=FIXED_DAY)[0]

    result, correct = submit_completion(db_session, user.id, exercise.id, "anything")
    assert result is None
    assert correct is None


def test_practice_page_requires_login(client):
    response = client.get("/practice", follow_redirects=False)
    assert response.status_code == 303


def test_generate_local_practice_route_requires_csrf(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post("/practice/generate", data={"csrf_token": "wrong"}, follow_redirects=False)
    assert response.status_code == 403


def test_generate_local_practice_route_creates_exercises(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post("/practice/generate", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert db_session.query(models.PracticeExercise).filter_by(user_id=user.id).count() > 0


def test_complete_practice_route_is_owner_scoped(client, db_session, user):
    other = models.User(email="other-practice-route@example.com", password_hash=hash_password("z"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_exercise = generate_local_exercises(db_session, other.id, today=FIXED_DAY)[0]

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/practice/{other_exercise.id}/complete",
        data={"response": "x", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        db_session.query(models.PracticeCompletion)
        .filter_by(exercise_id=other_exercise.id, user_id=user.id)
        .count()
        == 0
    )


def test_generate_local_exercises_tolerates_a_concurrently_inserted_duplicate(db_session, user):
    # Simulates a second, concurrent request already having inserted the
    # row for one of these categories (same idempotency_key) between this
    # call's existence-check query and its insert - a plain add_all()+commit
    # would raise an uncaught IntegrityError here (PracticeExercise has a DB
    # unique constraint on (user_id, idempotency_key)) instead of gracefully
    # reusing the winning row.
    categories = DEFAULT_CATEGORIES
    key = practice_module._exercise_idempotency_key(user.id, categories[0], FIXED_DAY.isoformat(), "local")
    winning_row = models.PracticeExercise(
        user_id=user.id,
        idempotency_key=key,
        template_version="local-v1",
        source_categories_json=json.dumps([categories[0]]),
        input_summary="concurrent winner",
        prompt="already inserted by another request",
        answer="a",
        explanation="e",
        ai_generated=False,
    )
    db_session.add(winning_row)
    db_session.commit()

    results = generate_local_exercises(db_session, user.id, today=FIXED_DAY)

    # No crash, and the pre-existing row for that category is reused
    # rather than a duplicate being attempted.
    matching = [r for r in results if r.idempotency_key == key]
    assert len(matching) == 1
    assert matching[0].id == winning_row.id
    assert matching[0].prompt == "already inserted by another request"


def test_generate_ai_exercises_tolerates_a_concurrently_inserted_duplicate(db_session, user, monkeypatch):
    monkeypatch.setattr(practice_module, "OpenAICompatibleProvider", _FakePracticeProvider)
    _ai_settings(db_session, user)

    key = practice_module._exercise_idempotency_key(user.id, "grammar", FIXED_DAY.isoformat(), "ai")
    winning_row = models.PracticeExercise(
        user_id=user.id,
        idempotency_key=key,
        template_version="ai-v1",
        source_categories_json=json.dumps(["grammar"]),
        input_summary="concurrent winner",
        prompt="already inserted by another request",
        answer="a",
        explanation="e",
        ai_generated=True,
    )
    db_session.add(winning_row)
    db_session.commit()

    rows, error = generate_ai_exercises(db_session, user.id, categories=["grammar", "vocab"], today=FIXED_DAY)

    assert error is None
    grammar_rows = [r for r in rows if r.idempotency_key == key]
    assert len(grammar_rows) == 1
    assert grammar_rows[0].id == winning_row.id
    # The non-colliding category in the same batch still succeeds instead
    # of being lost to an uncaught IntegrityError from the other one.
    assert any(r.prompt == "Prompt for vocab" for r in rows)
