from sqlalchemy import create_engine, text

from app.db.session import enable_sqlite_wal


def test_enable_sqlite_wal_sets_wal_journal_mode(tmp_path):
    db_path = tmp_path / "wal-test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    enable_sqlite_wal(engine)

    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()

    assert mode.lower() == "wal"


def test_in_memory_database_is_not_touched_by_wal_setup():
    # WAL requires a real file; the app only calls enable_sqlite_wal for
    # file-based sqlite URLs (see app/db/session.py), never for ":memory:".
    # This just documents that enable_sqlite_wal itself doesn't blow up if
    # pointed at one, since the pragma is a no-op there.
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_wal(engine)

    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()

    assert mode.lower() in ("memory", "wal")
