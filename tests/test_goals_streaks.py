from datetime import date, timedelta

from app.auth.security import hash_password
from app.db import models
from app.learning.streaks import GoalValidationError, current_streak, set_goal, week_progress


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def _version(db_session, document, number):
    v = models.DocumentVersion(document_id=document.id, content="word " * 25, version_number=number)
    db_session.add(v)
    db_session.commit()
    return v


def _activity(db_session, user_id, version, local_date, timezone_name="UTC"):
    db_session.add(
        models.WritingActivity(
            user_id=user_id,
            version_id=version.id,
            local_activity_date=local_date,
            timezone_at_creation=timezone_name,
        )
    )
    db_session.commit()


def test_set_goal_rejects_invalid_timezone(db_session, user):
    try:
        set_goal(db_session, user.id, 3, "Not/AZone", True)
        raise AssertionError("expected GoalValidationError")
    except GoalValidationError:
        pass


def test_set_goal_rejects_out_of_range_target(db_session, user):
    for bad_target in (0, 15):
        try:
            set_goal(db_session, user.id, bad_target, "UTC", True)
            raise AssertionError("expected GoalValidationError")
        except GoalValidationError:
            pass


def test_set_goal_persists_valid_values(db_session, user):
    goal = set_goal(db_session, user.id, 4, "America/New_York", True)
    assert goal.target_submissions == 4
    assert goal.timezone == "America/New_York"


def test_current_streak_counts_consecutive_local_days(db_session, user, document):
    today = date.today()
    for offset in range(3):
        v = _version(db_session, document, offset + 1)
        _activity(db_session, user.id, v, today - timedelta(days=offset))
    assert current_streak(db_session, user.id, "UTC") == 3


def test_current_streak_breaks_on_a_missed_day(db_session, user, document):
    today = date.today()
    _activity(db_session, user.id, _version(db_session, document, 1), today)
    _activity(db_session, user.id, _version(db_session, document, 2), today - timedelta(days=2))  # gap
    assert current_streak(db_session, user.id, "UTC") == 1


def test_current_streak_counts_through_yesterday_if_not_written_today(db_session, user, document):
    today = date.today()
    _activity(db_session, user.id, _version(db_session, document, 1), today - timedelta(days=1))
    _activity(db_session, user.id, _version(db_session, document, 2), today - timedelta(days=2))
    assert current_streak(db_session, user.id, "UTC") == 2


def test_current_streak_is_zero_once_broken_for_more_than_a_day(db_session, user, document):
    _activity(db_session, user.id, _version(db_session, document, 1), date.today() - timedelta(days=5))
    assert current_streak(db_session, user.id, "UTC") == 0


def test_multiple_submissions_same_local_day_count_as_one_streak_day(db_session, user, document):
    today = date.today()
    _activity(db_session, user.id, _version(db_session, document, 1), today)
    _activity(db_session, user.id, _version(db_session, document, 2), today)  # second submission, same day

    assert current_streak(db_session, user.id, "UTC") == 1
    assert week_progress(db_session, user.id, "UTC")["days_written"] == 1


def test_week_progress_uses_monday_boundary(db_session, user, document):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    last_sunday = monday - timedelta(days=1)

    _activity(db_session, user.id, _version(db_session, document, 1), last_sunday)  # previous week
    _activity(db_session, user.id, _version(db_session, document, 2), monday)

    progress = week_progress(db_session, user.id, "UTC")
    assert progress["week_start"] == monday
    assert progress["days_written"] == 1


def test_timezone_change_does_not_recompute_historical_activity_dates(db_session, user, document):
    v = _version(db_session, document, 1)
    _activity(db_session, user.id, v, date(2024, 1, 1), timezone_name="America/New_York")

    set_goal(db_session, user.id, 3, "Asia/Kolkata", True)  # change timezone after the fact

    activity = db_session.query(models.WritingActivity).filter(models.WritingActivity.user_id == user.id).one()
    assert activity.local_activity_date == date(2024, 1, 1)
    assert activity.timezone_at_creation == "America/New_York"


def test_goals_page_requires_login(client):
    response = client.get("/goals", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_save_goal_route_rejects_invalid_timezone(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/goals",
        data={"target_submissions": 3, "timezone_name": "Not/AZone", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "valid timezone" in response.text


def test_save_goal_route_persists_and_redirects(client, db_session, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")
    token = client.cookies.get("csrf_token")

    response = client.post(
        "/goals",
        data={"target_submissions": 5, "timezone_name": "UTC", "enabled": "true", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    goal = db_session.query(models.WeeklyWritingGoal).filter_by(user_id=user.id).one()
    assert goal.target_submissions == 5


def test_goals_page_is_scoped_to_the_signed_in_user(client, db_session, user):
    other = models.User(email="other-goals@example.com", password_hash=hash_password("y"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    set_goal(db_session, other.id, 7, "UTC", True)

    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/goals")

    assert response.status_code == 200
    assert 'value="7"' not in response.text
