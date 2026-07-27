from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL


def enable_sqlite_wal(engine) -> None:
    """WAL lets readers (e.g. the backup script's .backup command) run
    concurrently with writers instead of blocking on SQLite's default
    rollback-journal lock. No-op on an in-memory database - WAL requires a
    real file and SQLite silently ignores the pragma there anyway."""

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
if DATABASE_URL.startswith("sqlite") and ":memory:" not in DATABASE_URL:
    enable_sqlite_wal(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
