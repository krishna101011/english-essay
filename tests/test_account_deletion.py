from app.ai.crypto import encrypt_api_key
from app.auth.security import hash_password
from app.auth.tokens import create_email_verification_token, create_password_reset_token
from app.db import models


def _csrf(client, path):
    client.get(path)
    return client.cookies.get("csrf_token")


def _login(client, email, password):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _seed_full_account(db_session, user):
    settings = models.AISettings(
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake"),
        model_name="llama-3.3-70b-versatile",
        is_active=True,
    )
    document = models.Document(user_id=user.id, type=models.DocumentType.essay, title="My essay")
    db_session.add_all([settings, document])
    db_session.flush()

    version = models.DocumentVersion(document_id=document.id, content="Some content.", version_number=1)
    db_session.add(version)
    db_session.flush()

    correction = models.Correction(
        version_id=version.id,
        category=models.CorrectionCategory.grammar,
        start_offset=0,
        end_offset=4,
        original_text="Some",
        suggested_text="Some",
        explanation="looks fine",
        source=models.CorrectionSource.local,
    )
    score = models.Score(
        version_id=version.id,
        overall_score=80,
        grammar_score=80,
        vocab_score=80,
        structure_score=80,
        clarity_score=80,
        feedback_summary="Good work.",
    )
    vocab_word = models.VocabWord(
        user_id=user.id,
        word="meticulous",
        definition="Showing great attention to detail.",
        example_sentence="She kept meticulous notes.",
    )
    goal = models.WeeklyWritingGoal(user_id=user.id, target_submissions=3, timezone="UTC", enabled=True)
    activity = models.WritingActivity(
        user_id=user.id,
        version_id=version.id,
        local_activity_date=models.utcnow().date(),
        timezone_at_creation="UTC",
    )
    draft = models.WritingDraft(user_id=user.id, context_key="new", content="draft text")
    db_session.add_all([correction, score, vocab_word, goal, activity, draft])
    db_session.commit()

    exercise = models.PracticeExercise(
        user_id=user.id,
        idempotency_key="test-key",
        template_version="local-v1",
        source_categories_json="[\"grammar\"]",
        input_summary="Practice for: grammar",
        prompt="p",
        answer="a",
        explanation="e",
        ai_generated=False,
    )
    db_session.add(exercise)
    db_session.flush()
    db_session.add(models.PracticeCompletion(exercise_id=exercise.id, user_id=user.id, response="a"))
    db_session.commit()

    create_email_verification_token(db_session, user.id)
    create_password_reset_token(db_session, user.id)
    db_session.commit()

    return document.id, version.id


def test_delete_account_requires_correct_password(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    _login(client, user.email, "correct-horse-battery-staple")

    token = client.cookies.get("csrf_token")
    response = client.post(
        "/settings/delete-account",
        data={"password": "wrong-password", "confirm_email": user.email, "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert db_session.query(models.User).filter(models.User.id == user.id).first() is not None


def test_delete_account_requires_matching_typed_email(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    _login(client, user.email, "correct-horse-battery-staple")

    token = client.cookies.get("csrf_token")
    response = client.post(
        "/settings/delete-account",
        data={
            "password": "correct-horse-battery-staple",
            "confirm_email": "someone-else@example.com",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "match your account email" in response.text
    assert db_session.query(models.User).filter(models.User.id == user.id).first() is not None


def test_delete_account_cascades_through_all_user_data(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    document_id, version_id = _seed_full_account(db_session, user)
    user_id = user.id

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")
    response = client.post(
        "/settings/delete-account",
        data={"password": "correct-horse-battery-staple", "confirm_email": user.email, "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/signup"

    assert db_session.query(models.User).filter(models.User.id == user_id).first() is None
    assert db_session.query(models.AISettings).filter(models.AISettings.user_id == user_id).count() == 0
    assert db_session.query(models.Document).filter(models.Document.id == document_id).first() is None
    assert db_session.query(models.DocumentVersion).filter(models.DocumentVersion.id == version_id).first() is None
    assert db_session.query(models.Correction).filter(models.Correction.version_id == version_id).count() == 0
    assert db_session.query(models.Score).filter(models.Score.version_id == version_id).count() == 0
    assert db_session.query(models.VocabWord).filter(models.VocabWord.user_id == user_id).count() == 0
    assert (
        db_session.query(models.EmailVerificationToken).filter(models.EmailVerificationToken.user_id == user_id).count()
        == 0
    )
    assert (
        db_session.query(models.PasswordResetToken).filter(models.PasswordResetToken.user_id == user_id).count() == 0
    )
    assert db_session.query(models.WeeklyWritingGoal).filter(models.WeeklyWritingGoal.user_id == user_id).count() == 0
    assert db_session.query(models.WritingActivity).filter(models.WritingActivity.user_id == user_id).count() == 0
    assert db_session.query(models.WritingDraft).filter(models.WritingDraft.user_id == user_id).count() == 0
    assert db_session.query(models.PracticeExercise).filter(models.PracticeExercise.user_id == user_id).count() == 0
    assert db_session.query(models.PracticeCompletion).filter(models.PracticeCompletion.user_id == user_id).count() == 0


def test_delete_account_requires_login(client):
    token = _csrf(client, "/login")
    response = client.post(
        "/settings/delete-account",
        data={"password": "irrelevant", "confirm_email": "irrelevant@example.com", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
