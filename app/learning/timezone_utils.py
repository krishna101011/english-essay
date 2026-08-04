from zoneinfo import available_timezones

# Computed once: available_timezones() walks the tzdata package each call.
_VALID_TIMEZONES = available_timezones()

DEFAULT_TIMEZONE = "UTC"


def is_valid_iana_timezone(name: str) -> bool:
    return bool(name) and name in _VALID_TIMEZONES
