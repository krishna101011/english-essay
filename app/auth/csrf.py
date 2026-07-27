import secrets

from fastapi import Form, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import IS_PRODUCTION

CSRF_COOKIE_NAME = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"


class CSRFCookieMiddleware(BaseHTTPMiddleware):
    """Issues a per-browser CSRF token cookie for the double-submit pattern.

    Every response gets a `csrf_token` cookie if the request didn't already
    carry one. Templates render that same value into a hidden form field via
    `request.state.csrf_token`; `verify_csrf` then checks the two match on
    state-changing POSTs. A cross-site attacker can make a victim's browser
    send the cookie, but can't read its value (blocked by same-origin
    policy) to also put it in the hidden field, so a forged cross-site form
    submission fails verification.
    """

    async def dispatch(self, request: Request, call_next):
        existing_token = request.cookies.get(CSRF_COOKIE_NAME)
        request.state.csrf_token = existing_token or secrets.token_urlsafe(32)

        response: Response = await call_next(request)

        if not existing_token:
            response.set_cookie(
                CSRF_COOKIE_NAME,
                request.state.csrf_token,
                httponly=True,
                samesite="lax",
                secure=IS_PRODUCTION,
            )
        return response


async def verify_csrf(request: Request, csrf_token: str = Form(...)) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token or not secrets.compare_digest(cookie_token, csrf_token):
        raise HTTPException(status_code=403, detail="Your session's security token expired. Please try again.")
