from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import WeeklyWritingGoal, WritingActivity, utcnow
from app.learning.timezone_utils import DEFAULT_TIMEZONE, is_valid_iana_timezone

MIN_TARGET_SUBMISSIONS = 1
MAX_TARGET_SUBMISSIONS = 14

# Bounded lookback for streak computation: a year-plus unbroken streak is
# already an extreme case, and this caps how many distinct dates the query
# (and the short Python walk over them) ever has to consider.
STREAK_LOOKBACK_DAYS = 400


class GoalValidationError(ValueError):
    pass


def get_goal(db: Session, user_id: int) -> WeeklyWritingGoal | None:
    return db.get(WeeklyWritingGoal, user_id)


def set_goal(
    db: Session,
    user_id: int,
    target_submissions: int,
    timezone_name: str,
    enabled: bool,
) -> WeeklyWritingGoal:
    """Create or update the user's weekly goal.

    Changing `timezone_name` only affects how *future* writing days are
    bucketed. WritingActivity.local_activity_date is computed once, at
    submission time, from whatever timezone was current then (see
    app/learning/activities.py) - it is never recomputed retroactively, so
    a timezone change does not alter historical streaks or past week
    totals. This is a deliberate choice: silently rewriting history every
    time a user's timezone setting changes would make streaks feel
    arbitrary and unauditable.
    """
    if not is_valid_iana_timezone(timezone_name):
        raise GoalValidationError("Choose a valid timezone.")
    if not MIN_TARGET_SUBMISSIONS <= target_submissions <= MAX_TARGET_SUBMISSIONS:
        raise GoalValidationError(
            f"Weekly target must be between {MIN_TARGET_SUBMISSIONS} and {MAX_TARGET_SUBMISSIONS}."
        )

    goal = db.get(WeeklyWritingGoal, user_id)
    if goal is None:
        goal = WeeklyWritingGoal(
            user_id=user_id,
            target_submissions=target_submissions,
            timezone=timezone_name,
            enabled=enabled,
        )
        db.add(goal)
    else:
        goal.target_submissions = target_submissions
        goal.timezone = timezone_name
        goal.enabled = enabled
    db.commit()
    db.refresh(goal)
    return goal


def _today_local(timezone_name: str) -> date:
    return utcnow().astimezone(ZoneInfo(timezone_name)).date()


def _week_start(day: date) -> date:
    """Monday-anchored week boundary."""
    return day - timedelta(days=day.weekday())


def week_progress(db: Session, user_id: int, timezone_name: str) -> dict:
    """Distinct local writing days so far in the current Monday-Sunday week."""
    timezone_name = timezone_name if is_valid_iana_timezone(timezone_name) else DEFAULT_TIMEZONE
    today = _today_local(timezone_name)
    week_start = _week_start(today)
    days_written = (
        db.query(func.count(func.distinct(WritingActivity.local_activity_date)))
        .filter(
            WritingActivity.user_id == user_id,
            WritingActivity.local_activity_date >= week_start,
            WritingActivity.local_activity_date <= today,
        )
        .scalar()
        or 0
    )
    return {"week_start": week_start, "today": today, "days_written": days_written}


def current_streak(db: Session, user_id: int, timezone_name: str) -> int:
    """Consecutive local calendar days with at least one submission, ending
    today or yesterday. Several versions submitted the same local day still
    count as one day, since WritingActivity.local_activity_date is deduped
    with DISTINCT here rather than counted per-version."""
    timezone_name = timezone_name if is_valid_iana_timezone(timezone_name) else DEFAULT_TIMEZONE
    today = _today_local(timezone_name)
    cutoff = today - timedelta(days=STREAK_LOOKBACK_DAYS)

    rows = (
        db.query(WritingActivity.local_activity_date)
        .filter(
            WritingActivity.user_id == user_id,
            WritingActivity.local_activity_date >= cutoff,
            WritingActivity.local_activity_date <= today,
        )
        .distinct()
        .order_by(WritingActivity.local_activity_date.desc())
        .all()
    )
    dates = [d for (d,) in rows]
    if not dates or dates[0] not in (today, today - timedelta(days=1)):
        return 0  # no activity, or most recent writing day was more than a day ago - streak is broken

    streak = 0
    expected = dates[0]
    for d in dates:
        if d != expected:
            break
        streak += 1
        expected -= timedelta(days=1)
    return streak
