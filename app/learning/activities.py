from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models import WeeklyWritingGoal, WritingActivity, utcnow
from app.learning.timezone_utils import DEFAULT_TIMEZONE, is_valid_iana_timezone

MINIMUM_COMPLETED_WORDS = 20


def record_writing_activity(db: Session, user_id: int, version_id: int, content: str) -> None:
    """Called before the submission transaction commits; retries stay idempotent."""
    if len(content.split()) < MINIMUM_COMPLETED_WORDS:
        return
    if db.query(WritingActivity.id).filter(WritingActivity.version_id == version_id).first():
        return
    goal = db.get(WeeklyWritingGoal, user_id)
    timezone_name = goal.timezone if goal and is_valid_iana_timezone(goal.timezone) else DEFAULT_TIMEZONE
    now = utcnow()
    db.add(
        WritingActivity(
            user_id=user_id,
            version_id=version_id,
            completed_at_utc=now,
            local_activity_date=now.astimezone(ZoneInfo(timezone_name)).date(),
            timezone_at_creation=timezone_name,
        )
    )
