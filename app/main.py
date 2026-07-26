from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.ai.routes import router as ai_router
from app.auth.routes import router as auth_router
from app.config import IS_PRODUCTION, SESSION_SECRET_KEY
from app.documents.routes import router as documents_router
from app.vocab.routes import router as vocab_router

app = FastAPI(
    title="English Essay Coach",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

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
