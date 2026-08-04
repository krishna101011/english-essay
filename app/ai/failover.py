import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

from openai import RateLimitError
from sqlalchemy.orm import Session

from app.ai.provider import AIProviderTimeoutError
from app.db.models import AISettings, utcnow

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Used when a 429 response has no (or an unparseable) Retry-After header.
DEFAULT_RATE_LIMIT_COOLDOWN = timedelta(seconds=60)


class NoAIProviderConfiguredError(RuntimeError):
    """No active AI provider is configured for this user at all."""


class AllProvidersUnavailableError(RuntimeError):
    """Every configured provider was tried and none of them worked."""

    def __init__(self, message: str, *, timed_out: bool):
        super().__init__(message)
        # True only if every attempt failed by timing out - lets callers
        # keep their existing "timed out" vs "unavailable" user messages.
        self.timed_out = timed_out


def _is_cooling_down(settings: AISettings, now: datetime) -> bool:
    if settings.rate_limited_until is None:
        return False
    until = settings.rate_limited_until
    if until.tzinfo is None:  # SQLite round-trips DateTime(timezone=True) as naive
        until = until.replace(tzinfo=timezone.utc)
    return until > now


def ordered_providers(db: Session, user_id: int) -> list[AISettings]:
    """A user's active AI providers, in the order failover should try them:
    lowest `priority` first, ties broken by insertion order. Providers still
    inside their rate-limit cooldown window are pushed to the back rather
    than dropped outright - if every provider happens to be cooling down,
    trying the least-recently-limited one is still better than failing
    immediately."""
    now = utcnow()
    rows = (
        db.query(AISettings)
        .filter(AISettings.user_id == user_id, AISettings.is_active.is_(True))
        .order_by(AISettings.priority.asc(), AISettings.id.asc())
        .all()
    )
    ready = [r for r in rows if not _is_cooling_down(r, now)]
    cooling = [r for r in rows if _is_cooling_down(r, now)]
    return ready + cooling


def has_active_provider(db: Session, user_id: int) -> bool:
    return (
        db.query(AISettings.id)
        .filter(AISettings.user_id == user_id, AISettings.is_active.is_(True))
        .first()
        is not None
    )


def _retry_after_seconds(exc: RateLimitError) -> int:
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header:
        try:
            return max(1, int(float(header)))
        except ValueError:
            pass
    return int(DEFAULT_RATE_LIMIT_COOLDOWN.total_seconds())


def _mark_rate_limited(db: Session, settings: AISettings, exc: RateLimitError) -> None:
    settings.rate_limited_until = utcnow() + timedelta(seconds=_retry_after_seconds(exc))
    # A small, immediate, single-row write - safe to commit here even from
    # call sites that otherwise delay all writes until after the AI call
    # returns, since it happens between provider attempts rather than
    # holding a lock open during one.
    db.commit()


def call_with_failover(
    db: Session,
    user_id: int,
    provider_factory: Callable[[AISettings], object],
    operation: Callable[[object], T],
) -> T:
    """Try a user's configured AI providers in priority order until one
    succeeds. `provider_factory(settings)` builds the client for a given
    row (left to the caller so tests can keep monkeypatching their own
    module's OpenAICompatibleProvider reference); `operation(provider)` runs
    the actual call and returns its result.

    A rate-limit response (429) puts that provider on cooldown (using its
    Retry-After header when present) and moves on; a timeout or any other
    error also moves on to the next provider, since one misconfigured or
    temporarily-down provider shouldn't block a request when another
    configured one might work. Raises NoAIProviderConfiguredError if the
    user has no active provider at all, or AllProvidersUnavailableError if
    every configured provider was tried and failed.
    """
    providers = ordered_providers(db, user_id)
    if not providers:
        raise NoAIProviderConfiguredError("No AI provider configured.")

    last_exc: Exception | None = None
    timed_out_only = True
    for settings in providers:
        try:
            provider = provider_factory(settings)
            return operation(provider)
        except AIProviderTimeoutError as exc:
            logger.warning(
                "call_with_failover: provider id=%s (%s) timed out, trying next", settings.id, settings.provider
            )
            last_exc = exc
        except RateLimitError as exc:
            logger.warning(
                "call_with_failover: provider id=%s (%s) rate-limited, trying next", settings.id, settings.provider
            )
            _mark_rate_limited(db, settings, exc)
            last_exc = exc
            timed_out_only = False
        except Exception as exc:  # noqa: BLE001 - deliberately broad: fall through to the next configured provider
            logger.exception("call_with_failover: provider id=%s (%s) failed, trying next", settings.id, settings.provider)
            last_exc = exc
            timed_out_only = False

    raise AllProvidersUnavailableError(
        "All configured AI providers are currently unavailable.", timed_out=timed_out_only
    ) from last_exc
