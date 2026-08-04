from slowapi import Limiter
from slowapi import _rate_limit_exceeded_handler as rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from app.config import RATE_LIMIT_STORAGE_URI

# Defaults, all per source IP:
#   - login: 10/minute - generous enough for a user fumbling their password
#     a few times, tight enough to make credential-stuffing impractical.
#   - signup: 5/hour - normal signup is a one-time action per person; this
#     just caps mass account creation from a single IP.
#   - password-reset-request: 5/hour - the request step sends an email, so
#     this also caps using the app to spam a target's inbox.
LOGIN_RATE_LIMIT = "10/minute"
SIGNUP_RATE_LIMIT = "5/hour"
PASSWORD_RESET_REQUEST_RATE_LIMIT = "5/hour"
RESEND_VERIFICATION_RATE_LIMIT = "5/hour"
ESSAY_SUBMISSION_RATE_LIMIT = "12/hour"
AI_REWRITE_RATE_LIMIT = "12/hour"
AI_SETTINGS_RATE_LIMIT = "10/hour"
# Practice-exercise AI generation is user-initiated and isolated from the
# main essay pipeline; a tighter cap than essay/rewrite limits since it's a
# secondary feature with no essay-submission cost attached to gate it.
AI_PRACTICE_GENERATION_RATE_LIMIT = "6/hour"


def get_user_or_ip(request) -> str:
    """Keep costly actions scoped to an account while retaining IP fallback."""
    user_id = request.session.get("user_id")
    if user_id is not None:
        return f"user:{user_id}:{get_remote_address(request)}"
    return f"ip:{get_remote_address(request)}"


# SlowAPI/limits uses the redis-py client when a redis(s) URI is supplied.
# Development deliberately falls back to memory://; production configuration
# rejects that fallback so limits are shared by every Uvicorn worker.
limiter = Limiter(key_func=get_remote_address, storage_uri=RATE_LIMIT_STORAGE_URI, headers_enabled=True)
