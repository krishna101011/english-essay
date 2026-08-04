import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import IS_PRODUCTION

MAX_REQUEST_BODY_BYTES = 100_000
_SENSITIVE_QUERY_VALUE = re.compile(r"((?:token|api_key|password|csrf_token)=)[^&\s\"]+", re.IGNORECASE)


class SensitiveLogFilter(logging.Filter):
    """Redact sensitive query values before an access logger formats them."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _SENSITIVE_QUERY_VALUE.sub(r"\1[REDACTED]", value) if isinstance(value, str) else value
                for value in record.args
            )
        return True


def install_sensitive_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SensitiveLogFilter) for item in logger.filters):
        logger.addFilter(SensitiveLogFilter())


class RequestSafetyMiddleware(BaseHTTPMiddleware):
    """Reject obviously oversized form bodies before form parsing allocates them."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                {"detail": "Request is too large. Essays must be 50,000 characters or fewer."}, status_code=413
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Tailwind is still loaded from its official CDN in this phase. Scripts
        # remain self-only: no inline event handlers or inline executable code.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Frame-Options"] = "DENY"
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
