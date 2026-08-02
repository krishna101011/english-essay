import sqlite3
import threading

from sqlalchemy import create_engine, text

from app.db.session import connect_args, enable_sqlite_wal


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


def test_connect_args_set_a_busy_timeout_longer_than_the_pysqlite_default():
    # pysqlite's own connect() default timeout is 5s, so a contention test
    # alone can pass even with no explicit timeout at all. Assert directly
    # that the app configures something more generous, so a regression that
    # drops the "timeout" key (falling back to that 5s default) is caught
    # even if it wouldn't happen to blow the assertion below.
    assert connect_args.get("timeout", 0) >= 15


def test_write_survives_brief_lock_contention(tmp_path):
    # Regression test for "database is locked": a second connection holding
    # a write transaction (e.g. another worker mid-request during a
    # uvicorn --reload restart) must not immediately blow up the app's
    # INSERT - the busy_timeout in connect_args should make it wait out the
    # contention instead of erroring right away. The test above pins the
    # actual timeout value; this one exercises the real retry behavior
    # end-to-end against the app's engine + WAL setup.
    db_path = tmp_path / "contention-test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args=connect_args)
    enable_sqlite_wal(engine)

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT)"))

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_write_lock():
        # isolation_level=None (autocommit) so we control BEGIN/COMMIT
        # exactly, rather than fighting sqlite3's implicit transactions.
        blocker = sqlite3.connect(str(db_path), timeout=15, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute("INSERT INTO documents (title) VALUES ('blocker')")
        lock_acquired.set()
        release_lock.wait(timeout=5)
        blocker.execute("COMMIT")
        blocker.close()

    blocker_thread = threading.Thread(target=hold_write_lock)
    blocker_thread.start()
    assert lock_acquired.wait(timeout=5), "blocker thread never acquired the write lock"

    threading.Timer(0.5, release_lock.set).start()

    # Without a busy_timeout this raises sqlite3.OperationalError /
    # sqlalchemy.exc.OperationalError: database is locked, immediately.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO documents (title) VALUES ('essay')"))

    blocker_thread.join(timeout=5)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()
    assert count == 2
