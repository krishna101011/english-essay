from datetime import timedelta, timezone

import httpx
import pytest
from openai import RateLimitError

from app.ai.crypto import encrypt_api_key
from app.ai.failover import (
    AllProvidersUnavailableError,
    NoAIProviderConfiguredError,
    call_with_failover,
    has_active_provider,
    ordered_providers,
)
from app.ai.provider import AIProviderTimeoutError
from app.db import models
from app.db.models import utcnow


def _add_settings(db_session, user, provider="groq", priority=0, is_active=True, rate_limited_until=None, model_name="m"):
    settings = models.AISettings(
        user_id=user.id,
        provider=provider,
        encrypted_api_key=encrypt_api_key("sk-fake"),
        model_name=model_name,
        base_url="https://api.groq.com/openai/v1",
        priority=priority,
        is_active=is_active,
        rate_limited_until=rate_limited_until,
    )
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    return settings


def _rate_limit_error(retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(429, headers=headers, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_ordered_providers_sorts_by_priority(db_session, user):
    third = _add_settings(db_session, user, priority=2, model_name="third")
    first = _add_settings(db_session, user, priority=0, model_name="first")
    second = _add_settings(db_session, user, priority=1, model_name="second")

    ordered = ordered_providers(db_session, user.id)

    assert [p.id for p in ordered] == [first.id, second.id, third.id]


def test_ordered_providers_excludes_inactive(db_session, user):
    _add_settings(db_session, user, priority=0, is_active=False, model_name="disabled")
    active = _add_settings(db_session, user, priority=1, model_name="active")

    ordered = ordered_providers(db_session, user.id)

    assert [p.id for p in ordered] == [active.id]


def test_ordered_providers_pushes_cooling_down_to_the_back(db_session, user):
    cooling = _add_settings(
        db_session, user, priority=0, model_name="cooling", rate_limited_until=utcnow() + timedelta(seconds=60)
    )
    ready = _add_settings(db_session, user, priority=1, model_name="ready")

    ordered = ordered_providers(db_session, user.id)

    assert [p.id for p in ordered] == [ready.id, cooling.id]


def test_ordered_providers_ignores_expired_cooldown(db_session, user):
    expired = _add_settings(
        db_session, user, priority=0, model_name="expired", rate_limited_until=utcnow() - timedelta(seconds=1)
    )

    ordered = ordered_providers(db_session, user.id)

    assert [p.id for p in ordered] == [expired.id]


def test_has_active_provider(db_session, user):
    assert has_active_provider(db_session, user.id) is False
    _add_settings(db_session, user)
    assert has_active_provider(db_session, user.id) is True


def test_call_with_failover_raises_when_no_provider_configured(db_session, user):
    with pytest.raises(NoAIProviderConfiguredError):
        call_with_failover(db_session, user.id, lambda s: object(), lambda p: "unused")


def test_call_with_failover_succeeds_on_first_provider(db_session, user):
    _add_settings(db_session, user, priority=0, model_name="only")

    result = call_with_failover(db_session, user.id, lambda s: s.model_name, lambda name: f"used {name}")

    assert result == "used only"


def test_call_with_failover_moves_to_next_on_rate_limit_and_marks_cooldown(db_session, user):
    first = _add_settings(db_session, user, priority=0, model_name="first")
    second = _add_settings(db_session, user, priority=1, model_name="second")

    def operation(settings_model_name):
        if settings_model_name == "first":
            raise _rate_limit_error(retry_after=45)
        return f"used {settings_model_name}"

    result = call_with_failover(db_session, user.id, lambda s: s.model_name, operation)

    assert result == "used second"
    db_session.refresh(first)
    assert first.rate_limited_until is not None
    # Retry-After header (45s) should drive the cooldown window, not the
    # default - SQLite round-trips DateTime(timezone=True) as naive, so
    # reattach UTC before comparing against an aware "now".
    stored_until = first.rate_limited_until.replace(tzinfo=timezone.utc)
    assert stored_until > utcnow() + timedelta(seconds=30)
    db_session.refresh(second)
    assert second.rate_limited_until is None


def test_call_with_failover_moves_to_next_on_timeout_without_marking_cooldown(db_session, user):
    first = _add_settings(db_session, user, priority=0, model_name="first")
    _add_settings(db_session, user, priority=1, model_name="second")

    def operation(name):
        if name == "first":
            raise AIProviderTimeoutError("timed out")
        return f"used {name}"

    result = call_with_failover(db_session, user.id, lambda s: s.model_name, operation)

    assert result == "used second"
    db_session.refresh(first)
    assert first.rate_limited_until is None  # timeouts are transient, not a persistent cooldown


def test_call_with_failover_moves_to_next_on_any_other_error(db_session, user):
    _add_settings(db_session, user, priority=0, model_name="first")
    _add_settings(db_session, user, priority=1, model_name="second")

    def operation(name):
        if name == "first":
            raise ValueError("bad request / incompatible model")
        return f"used {name}"

    result = call_with_failover(db_session, user.id, lambda s: s.model_name, operation)

    assert result == "used second"


def test_call_with_failover_exhausts_all_and_reports_timeout_only_when_all_timed_out(db_session, user):
    _add_settings(db_session, user, priority=0, model_name="first")
    _add_settings(db_session, user, priority=1, model_name="second")

    def always_times_out(name):
        raise AIProviderTimeoutError("timed out")

    with pytest.raises(AllProvidersUnavailableError) as excinfo:
        call_with_failover(db_session, user.id, lambda s: s.model_name, always_times_out)

    assert excinfo.value.timed_out is True


def test_call_with_failover_reports_not_timed_out_when_mixed_failures(db_session, user):
    _add_settings(db_session, user, priority=0, model_name="first")
    _add_settings(db_session, user, priority=1, model_name="second")

    def operation(name):
        if name == "first":
            raise AIProviderTimeoutError("timed out")
        raise _rate_limit_error()

    with pytest.raises(AllProvidersUnavailableError) as excinfo:
        call_with_failover(db_session, user.id, lambda s: s.model_name, operation)

    assert excinfo.value.timed_out is False


def test_call_with_failover_skips_a_provider_still_cooling_down_from_a_previous_call(db_session, user):
    first = _add_settings(db_session, user, priority=0, model_name="first")
    _add_settings(db_session, user, priority=1, model_name="second")

    calls = []

    def operation(name):
        calls.append(name)
        if name == "first":
            raise _rate_limit_error(retry_after=120)
        return f"used {name}"

    # First call: "first" gets rate-limited and cools down; "second" serves the request.
    call_with_failover(db_session, user.id, lambda s: s.model_name, operation)
    assert calls == ["first", "second"]

    # Second, independent call: "first" is still cooling down, so it should
    # never even be attempted this time - it's pushed behind "second" in
    # ordered_providers(), and "second" alone satisfies the request.
    calls.clear()
    call_with_failover(db_session, user.id, lambda s: s.model_name, operation)
    assert calls == ["second"]
    db_session.refresh(first)
    assert first.rate_limited_until is not None
