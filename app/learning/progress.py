from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Correction, Document, DocumentVersion, Score, utcnow
from app.learning.timezone_utils import DEFAULT_TIMEZONE, is_valid_iana_timezone

TREND_WEEKS = 12
MIN_SCORED_VERSIONS_FOR_TREND = 2

# A single correction in a category is normal writing, not a pattern. Only
# flag a category once it recurs at least this many times within the
# lookback window - otherwise the tracker would call out an ordinary
# one-off typo as a "recurring weakness".
MISTAKE_WINDOW_DAYS = 30
MISTAKE_THRESHOLD = 3


def _local_utc_offset_minutes(timezone_name: str) -> int:
    """Offset (minutes) of `timezone_name` from UTC at the current moment.

    Used to shift SQLite's UTC-stored timestamps into local-calendar week
    buckets for GROUP BY. This is an approximation, not an exact per-row
    conversion: SQLite carries no IANA tzdata of its own, so a submission
    made near a DST transition may land in the bucket for the offset in
    effect *now* rather than the offset in effect *at submission time*. That
    is an acceptable trade-off for a weekly trend chart; nothing here is
    used where exactness matters (e.g. legal/billing timestamps).
    """
    now = utcnow()
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    offset = now.astimezone(zone).utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def _resolved_timezone(timezone_name: str) -> str:
    return timezone_name if is_valid_iana_timezone(timezone_name) else DEFAULT_TIMEZONE


def has_scored_history(db: Session, user_id: int) -> int:
    """Count of scored versions - bounded to what's needed for an empty-state
    check, not a full row fetch (COUNT happens in SQL)."""
    return (
        db.query(func.count(Score.id))
        .join(DocumentVersion, DocumentVersion.id == Score.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(Document.user_id == user_id)
        .scalar()
        or 0
    )


def score_trend(db: Session, user_id: int, timezone_name: str, weeks: int = TREND_WEEKS) -> list[dict]:
    """Weekly average overall score, aggregated entirely in SQL (func.avg /
    group_by) and bounded to the last `weeks` weeks - never loads raw
    DocumentVersion/Correction rows into Python."""
    timezone_name = _resolved_timezone(timezone_name)
    offset_modifier = f"{_local_utc_offset_minutes(timezone_name):+d} minutes"
    cutoff = utcnow() - timedelta(weeks=weeks)

    bucket = func.strftime("%Y-%W", DocumentVersion.submitted_at, offset_modifier)
    bucket_start = func.min(func.date(DocumentVersion.submitted_at, offset_modifier))

    rows = (
        db.query(
            bucket.label("bucket"),
            bucket_start.label("week_start"),
            func.avg(Score.overall_score).label("avg_score"),
            func.count(Score.id).label("submissions"),
        )
        .join(Score, Score.version_id == DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(Document.user_id == user_id, DocumentVersion.submitted_at >= cutoff)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    # The `cutoff` filter already bounds this to a handful of rows (at most
    # ~weeks+1, since it isn't Monday-aligned) - no separate SQL LIMIT here.
    # A LIMIT applied after this ascending sort would keep the *oldest*
    # buckets whenever the unaligned cutoff produces one more than `weeks`,
    # silently dropping the current week (the one a just-submitted essay
    # would land in) instead of some older one. Slicing the last `weeks`
    # entries in Python after the fact keeps the most recent ones instead.
    trimmed = rows[-weeks:]
    return [
        {"week_start": week_start, "avg_score": round(avg_score, 1), "submissions": submissions}
        for _, week_start, avg_score, submissions in trimmed
    ]


def recurring_mistakes(
    db: Session,
    user_id: int,
    window_days: int = MISTAKE_WINDOW_DAYS,
    threshold: int = MISTAKE_THRESHOLD,
) -> list[dict]:
    """Correction categories that recur at least `threshold` times within
    the last `window_days` days - a single hit never qualifies. One grouped
    aggregate query; the HAVING clause does the thresholding in SQL."""
    cutoff = utcnow() - timedelta(days=window_days)
    rows = (
        db.query(Correction.category, func.count(Correction.id).label("count"))
        .join(DocumentVersion, DocumentVersion.id == Correction.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(Document.user_id == user_id, DocumentVersion.submitted_at >= cutoff)
        .group_by(Correction.category)
        .having(func.count(Correction.id) >= threshold)
        .order_by(func.count(Correction.id).desc())
        .all()
    )
    return [{"category": category.value, "count": count} for category, count in rows]
