from datetime import timedelta

from app.auth.security import hash_password
from app.db import models
from app.db.models import CorrectionCategory, CorrectionSource, utcnow
from app.learning.progress import MISTAKE_THRESHOLD, has_scored_history, recurring_mistakes, score_trend


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def _add_version_with_score(db_session, document, overall_score, submitted_at=None, version_number=1):
    version = models.DocumentVersion(
        document_id=document.id,
        content="word " * 25,
        version_number=version_number,
        submitted_at=submitted_at or utcnow(),
    )
    db_session.add(version)
    db_session.flush()
    db_session.add(
        models.Score(
            version_id=version.id,
            overall_score=overall_score,
            grammar_score=overall_score,
            vocab_score=overall_score,
            structure_score=overall_score,
            clarity_score=overall_score,
            feedback_summary="ok",
        )
    )
    db_session.commit()
    return version


def _add_corrections(db_session, version, category, count):
    for i in range(count):
        db_session.add(
            models.Correction(
                version_id=version.id,
                category=category,
                start_offset=i,
                end_offset=i + 1,
                original_text="a",
                suggested_text="b",
                explanation="because",
                source=CorrectionSource.local,
            )
        )
    db_session.commit()


def test_has_scored_history_counts_only_own_scores(db_session, user, document):
    assert has_scored_history(db_session, user.id) == 0
    _add_version_with_score(db_session, document, 80)
    assert has_scored_history(db_session, user.id) == 1


def test_score_trend_aggregates_in_sql_and_is_bounded(db_session, user, document):
    _add_version_with_score(db_session, document, 60, version_number=1)
    _add_version_with_score(db_session, document, 80, version_number=2)

    trend = score_trend(db_session, user.id, "UTC", weeks=12)

    assert len(trend) == 1  # both submissions land in the current week bucket
    assert trend[0]["avg_score"] == 70.0
    assert trend[0]["submissions"] == 2


def test_score_trend_keeps_the_most_recent_week_when_more_weeks_exist_than_the_cap(db_session, user, document):
    # 13 distinct weeks of history (one scored submission per week), one
    # more than the requested cap of 12. A SQL LIMIT applied after
    # ascending order would keep the 12 *oldest* buckets and silently drop
    # the current week - exactly the one a just-submitted essay would land
    # in. The most recent week must survive the cap instead.
    for i in range(13):
        _add_version_with_score(
            db_session, document, overall_score=50 + i,
            submitted_at=utcnow() - timedelta(weeks=i), version_number=i + 1,
        )

    trend = score_trend(db_session, user.id, "UTC", weeks=12)

    assert len(trend) == 12
    # i=0 (submitted "now", score 50) must be present...
    assert any(abs(point["avg_score"] - 50) < 0.5 for point in trend)
    # ...and it's the oldest one (i=12, score 62) that got trimmed instead.
    assert not any(abs(point["avg_score"] - 62) < 0.5 for point in trend)


def test_score_trend_excludes_other_users_data(db_session, user, document):
    other = models.User(email="other-trend@example.com", password_hash="x", email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_doc = models.Document(user_id=other.id, type=models.DocumentType.essay, title="Other")
    db_session.add(other_doc)
    db_session.commit()
    _add_version_with_score(db_session, other_doc, 10)

    assert score_trend(db_session, user.id, "UTC") == []
    assert has_scored_history(db_session, user.id) == 0


def test_recurring_mistakes_requires_threshold_before_flagging(db_session, user, document):
    version = _add_version_with_score(db_session, document, 70)
    _add_corrections(db_session, version, CorrectionCategory.grammar, MISTAKE_THRESHOLD - 1)

    assert recurring_mistakes(db_session, user.id) == []  # below threshold - not yet "recurring"

    _add_corrections(db_session, version, CorrectionCategory.grammar, 1)  # now exactly at threshold

    assert recurring_mistakes(db_session, user.id) == [{"category": "grammar", "count": MISTAKE_THRESHOLD}]


def test_recurring_mistakes_ignores_corrections_outside_the_window(db_session, user, document):
    old_version = _add_version_with_score(db_session, document, 70, submitted_at=utcnow() - timedelta(days=60))
    _add_corrections(db_session, old_version, CorrectionCategory.spelling, MISTAKE_THRESHOLD + 2)

    assert recurring_mistakes(db_session, user.id) == []


def test_recurring_mistakes_never_flags_a_single_correction(db_session, user, document):
    version = _add_version_with_score(db_session, document, 70)
    _add_corrections(db_session, version, CorrectionCategory.punctuation, 1)

    assert recurring_mistakes(db_session, user.id) == []


def test_progress_page_requires_login(client):
    response = client.get("/progress", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_progress_page_shows_empty_state_with_no_scored_history(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/progress")

    assert response.status_code == 200
    assert "No scored essays yet" in response.text


def test_progress_page_never_shows_another_users_mistakes(client, db_session, user, document):
    other = models.User(email="other-progress@example.com", password_hash=hash_password("x"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    other_doc = models.Document(user_id=other.id, type=models.DocumentType.essay, title="Other essay")
    db_session.add(other_doc)
    db_session.commit()
    other_version = _add_version_with_score(db_session, other_doc, 55)
    _add_corrections(db_session, other_version, CorrectionCategory.grammar, MISTAKE_THRESHOLD + 3)

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/progress")

    assert response.status_code == 200
    assert "No scored essays yet" in response.text  # user has no scored history of their own
