import os

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.routes as auth_routes
from app.db.base import Base
from app.db import models  # noqa: F401 - registers models on Base.metadata
from app.db.session import get_db
from app.main import app
from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # The limiter is a module-level singleton keyed by remote address, and
    # every TestClient request reports the same address ("testclient") -
    # without resetting, request counts would leak across test functions and
    # tests unrelated to rate limiting could start failing once enough
    # earlier tests hit the same endpoint.
    limiter.reset()
    yield


class FakeEmailSender:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture()
def fake_email_sender(monkeypatch):
    sender = FakeEmailSender()
    monkeypatch.setattr(auth_routes, "get_email_sender", lambda: sender)
    return sender


@pytest.fixture()
def db_session():
    # StaticPool keeps every checkout on the one physical connection - without
    # it, TestClient's ASGI dispatch can grab a second connection to the same
    # ":memory:" URL, which SQLite treats as a brand new, table-less database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user(db_session):
    # email_verified=True by default: most tests exercise document/vocab
    # creation and shouldn't have to care about the verification gate.
    # Tests for that gate itself use the unverified_user fixture below.
    u = models.User(
        email="tester@example.com",
        password_hash="irrelevant-for-these-tests",
        email_verified=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def unverified_user(db_session):
    u = models.User(
        email="unverified@example.com",
        password_hash="irrelevant-for-these-tests",
        email_verified=False,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def document(db_session, user):
    doc = models.Document(user_id=user.id, type=models.DocumentType.essay, title="Test essay")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


@pytest.fixture()
def client(db_session):
    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
