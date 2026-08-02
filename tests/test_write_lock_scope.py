import sqlite3
import threading
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.crypto import encrypt_api_key
from app.ai.schemas import EssayFeedback
from app.db.base import Base
from app.db import models
from app.db.session import connect_args, enable_sqlite_wal
from app.documents import service


class SlowProvider:
    """Stands in for OpenAICompatibleProvider, simulating a slow external AI
    call so tests never make real API calls while still exercising realistic
    timing."""

    delay = 0

    def __init__(self, api_key, base_url, model):
        pass

    def analyze(self, essay_text, local_findings, context):
        time.sleep(SlowProvider.delay)
        return EssayFeedback(
            corrections=[],
            overall_score=80,
            grammar_score=80,
            vocab_score=80,
            structure_score=80,
            clarity_score=80,
            feedback_summary="Solid draft.",
        )


def test_submit_version_does_not_hold_write_lock_across_the_ai_call(tmp_path, monkeypatch):
    # Regression test: submit_version() used to call db.flush() (inserting
    # the new DocumentVersion row, which takes SQLite's write lock) BEFORE
    # calling the AI provider, then held that lock through the entire
    # external call until commit. Here a separate connection grabs the
    # write lock first and holds it for less time than the mocked AI call
    # takes, so by the time submit_version's own (now-deferred) write
    # happens, that external lock has already been released. If the write
    # transaction were still opened early, submit_version would have to
    # wait out the external hold *before* even starting the AI call,
    # pushing total time past ai_delay + external_hold - i.e. this proves
    # the request succeeds quickly because it was never blocked on that
    # lock in the first place, not because busy_timeout waited it out.
    db_path = tmp_path / "lock-scope-test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args=connect_args)
    enable_sqlite_wal(engine)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()

    user = models.User(email="tester@example.com", password_hash="x", email_verified=True)
    db.add(user)
    db.flush()
    ai_settings = models.AISettings(
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
    )
    document = models.Document(user_id=user.id, type=models.DocumentType.essay, title="My essay")
    db.add_all([ai_settings, document])
    db.commit()
    db.refresh(document)
    document.versions  # load before timing starts; no previous version exists

    monkeypatch.setattr(service, "check_text", lambda text: [])
    monkeypatch.setattr(service, "OpenAICompatibleProvider", SlowProvider)
    SlowProvider.delay = 2.0
    external_hold = 1.5

    def hold_external_write_lock():
        # isolation_level=None (autocommit) so we control BEGIN/COMMIT
        # exactly, rather than fighting sqlite3's implicit transactions.
        conn = sqlite3.connect(str(db_path), timeout=15, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO users (email, password_hash, email_verified, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("other@example.com", "x", 0),
        )
        time.sleep(external_hold)
        conn.execute("COMMIT")
        conn.close()

    writer_thread = threading.Thread(target=hold_external_write_lock)
    writer_thread.start()
    time.sleep(0.05)  # let the external writer grab the lock first

    start = time.monotonic()
    result = service.submit_version(db, document, "Some essay content for timing test.")
    elapsed = time.monotonic() - start

    writer_thread.join(timeout=10)

    assert result.ai_error is None
    # Broken behavior would total roughly external_hold + delay (~3.5s: wait
    # out the external lock, then hold our own through the AI call). Fixed
    # behavior should track delay alone (~2.0-2.5s even under load). The
    # margin below is comfortably under external_hold so the two scenarios
    # can't be confused even with some scheduling jitter.
    assert elapsed < SlowProvider.delay + 1.0
