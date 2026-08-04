from app.db import models
from app.learning.activities import MINIMUM_COMPLETED_WORDS, record_writing_activity


def _version(db_session, document, number=1):
    v = models.DocumentVersion(document_id=document.id, content="word " * 25, version_number=number)
    db_session.add(v)
    db_session.commit()
    return v


def test_record_writing_activity_is_idempotent_on_retry(db_session, user, document):
    version = _version(db_session, document)

    record_writing_activity(db_session, user.id, version.id, "word " * 25)
    db_session.commit()
    record_writing_activity(db_session, user.id, version.id, "word " * 25)  # simulated retry of the same submission
    db_session.commit()

    count = db_session.query(models.WritingActivity).filter_by(version_id=version.id).count()
    assert count == 1


def test_record_writing_activity_skips_short_submissions(db_session, user, document):
    version = _version(db_session, document)
    short_content = " ".join(["word"] * (MINIMUM_COMPLETED_WORDS - 1))

    record_writing_activity(db_session, user.id, version.id, short_content)
    db_session.commit()

    assert db_session.query(models.WritingActivity).filter_by(version_id=version.id).count() == 0


def test_record_writing_activity_falls_back_to_utc_for_invalid_goal_timezone(db_session, user, document):
    db_session.add(models.WeeklyWritingGoal(user_id=user.id, target_submissions=3, timezone="Not/AZone", enabled=True))
    db_session.commit()
    version = _version(db_session, document)

    record_writing_activity(db_session, user.id, version.id, "word " * 25)
    db_session.commit()

    activity = db_session.query(models.WritingActivity).filter_by(version_id=version.id).one()
    assert activity.timezone_at_creation == "UTC"
