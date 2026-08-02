from app.auth.security import hash_password
from app.db import models


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _seed_document_with_version(db_session, user):
    document = models.Document(user_id=user.id, type=models.DocumentType.essay, title="My essay")
    db_session.add(document)
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
    db_session.add_all([correction, score])
    db_session.commit()

    return document.id, version.id


def test_delete_document_removes_document_and_cascades_to_versions_and_corrections(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    document_id, version_id = _seed_document_with_version(db_session, user)

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/documents/{document_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/history"
    assert db_session.query(models.Document).filter(models.Document.id == document_id).first() is None
    assert db_session.query(models.DocumentVersion).filter(models.DocumentVersion.id == version_id).first() is None
    assert db_session.query(models.Correction).filter(models.Correction.version_id == version_id).count() == 0
    assert db_session.query(models.Score).filter(models.Score.version_id == version_id).count() == 0


def test_delete_document_nulls_source_document_id_on_surviving_vocab_words(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    document_id, _ = _seed_document_with_version(db_session, user)

    vocab_word = models.VocabWord(
        user_id=user.id,
        word="meticulous",
        definition="Showing great attention to detail.",
        example_sentence="She kept meticulous notes.",
        source_document_id=document_id,
    )
    db_session.add(vocab_word)
    db_session.commit()
    vocab_word_id = vocab_word.id

    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/documents/{document_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db_session.query(models.Document).filter(models.Document.id == document_id).first() is None

    surviving_word = db_session.query(models.VocabWord).filter(models.VocabWord.id == vocab_word_id).first()
    assert surviving_word is not None
    assert surviving_word.source_document_id is None


def test_delete_document_rejects_mismatched_csrf_token(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    document_id, _ = _seed_document_with_version(db_session, user)

    _login(client, user.email, "correct-horse-battery-staple")

    response = client.post(
        f"/documents/{document_id}/delete",
        data={"csrf_token": "not-the-real-token"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert db_session.query(models.Document).filter(models.Document.id == document_id).first() is not None


def test_delete_document_rejects_request_for_another_users_document(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    db_session.commit()
    document_id, _ = _seed_document_with_version(db_session, user)

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
        f"/documents/{document_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/history"
    assert db_session.query(models.Document).filter(models.Document.id == document_id).first() is not None


def test_delete_document_requires_login(client, db_session, user):
    document_id, _ = _seed_document_with_version(db_session, user)
    client.get("/login")
    token = client.cookies.get("csrf_token")

    response = client.post(
        f"/documents/{document_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert db_session.query(models.Document).filter(models.Document.id == document_id).first() is not None
