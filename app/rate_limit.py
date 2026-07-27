from slowapi import Limiter
from slowapi import _rate_limit_exceeded_handler as rate_limit_exceeded_handler
from slowapi.util import get_remote_address

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

limiter = Limiter(key_func=get_remote_address)
