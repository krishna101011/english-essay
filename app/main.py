import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.ai.routes import router as ai_router
from app.auth.csrf import CSRFCookieMiddleware
from app.auth.routes import router as auth_router
from app.config import IS_PRODUCTION, SESSION_SECRET_KEY
from app.documents.routes import router as documents_router
from app.learning.routes import router as learning_router
from app.public.routes import router as public_router
from app.rate_limit import limiter, rate_limit_exceeded_handler
from app.security import RequestSafetyMiddleware, SecurityHeadersMiddleware, install_sensitive_log_filter
from app.vocab.routes import router as vocab_router

# Without this, app.* loggers (e.g. ConsoleEmailSender logging verification/
# reset links) have no handler and are silently dropped - uvicorn's own
# logging setup only configures its "uvicorn.*" loggers, not the root
# logger. Runs at import time so it applies under `uvicorn --reload` too,
# since the reloader worker re-imports this module fresh.
logging.basicConfig(level=logging.INFO)
install_sensitive_log_filter()

app = FastAPI(
    title="English Essay Coach",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(CSRFCookieMiddleware)
app.add_middleware(RequestSafetyMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    same_site="lax",
    https_only=IS_PRODUCTION,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(documents_router)
app.include_router(vocab_router)
app.include_router(learning_router)
app.include_router(public_router)
