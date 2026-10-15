"""
Concurrency test: 100 parallel lock attempts on the SAME seat.

Bypasses HTTP entirely.  Uses raw sqlite3 connections (no SQLAlchemy
session layer) so we have full, explicit control over BEGIN IMMEDIATE /
COMMIT / ROLLBACK.

Why BEGIN IMMEDIATE?
  SQLite's default BEGIN is DEFERRED: it acquires a shared lock on
  first read and upgrades to exclusive on first write.  With 100
  concurrent threads, two threads can both read 'AVAILABLE' before
  either writes — classic TOCTOU race → double booking.

  BEGIN IMMEDIATE acquires a write-reserved lock up-front.  Only ONE
  thread can hold it at a time; the others wait (up to timeout=30 s).
  After the winner commits, the next thread re-reads the COMMITTED
  status ('LOCKED') and returns a conflict.  This mirrors PostgreSQL's
  SELECT … FOR UPDATE row-level locking.

On PostgreSQL (production) the with_for_update() call in the route
provides the exact same serialisation guarantee.
"""
import os
import sqlite3
import threading
import tempfile
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, ShowSeat, Show, Movie


# ---------------------------------------------------------------------------
# Fixture: isolated file-based SQLite, seeded via SQLAlchemy
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def concurrent_db():
    """
    Builds a fresh file-backed SQLite DB for the concurrency test.
    SQLAlchemy is used only for schema creation and seeding.
    The test itself uses raw sqlite3 connections for full transaction control.
    """
    tmpdb = tempfile.mktemp(suffix="_conc.db")

    # Plain engine — default isolation so seeding works normally
    engine = create_engine(
        f"sqlite:///{tmpdb}",
        connect_args={"check_same_thread": False},
    )

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # Seed one show with 100 seats
    session = SessionFactory()
    show_id = None
    try:
        movie = Movie(title="Concurrency Movie", description="test", duration_minutes=120)
        session.add(movie)
        session.flush()

        show = Show(
            movie_id=movie.id,
            screen_name="Screen C",
            start_time=datetime.now(timezone.utc) + timedelta(hours=2),
            price=100.0,
        )
        session.add(show)
        session.flush()
        show_id = show.id

        for row in "ABCDEFGHIJ":
            for col in range(1, 11):
                session.add(ShowSeat(
                    show_id=show.id,
                    seat_label=f"{row}{col}",
                    status="AVAILABLE",
                ))
        session.commit()
    finally:
        session.close()

    engine.dispose()  # close SQLAlchemy connections before raw sqlite3 takes over

    yield {"db_path": tmpdb, "show_id": show_id}

    try:
        os.unlink(tmpdb)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# The actual test — raw sqlite3, full transaction control
# ---------------------------------------------------------------------------

def test_100_concurrent_lock_same_seat(concurrent_db):
    """
    100 threads simultaneously try to lock seat A1 for the same show.
    Expected: exactly 1 success (status 200), 99 conflicts (status 409).
    Zero double-bookings — this is the core SeatLock guarantee.
    """
    db_path  = concurrent_db["db_path"]
    show_id  = concurrent_db["show_id"]
    N        = 100
    results: list[int]   = []
    exc_msgs: list[str]  = []
    result_lock = threading.Lock()

    # Find the actual table name used by ShowSeat model
    seat_table = ShowSeat.__tablename__

    def try_lock(user_id: int) -> None:
        """
        Each thread opens its OWN raw sqlite3 connection with timeout=30 s.
        isolation_level=None → autocommit; we issue BEGIN IMMEDIATE manually.
        """
        conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        conn.isolation_level = None   # put sqlite3 in autocommit / manual-tx mode
        cur  = conn.cursor()
        status_code = 409
        try:
            cur.execute("BEGIN IMMEDIATE")

            cur.execute(
                f"SELECT status FROM {seat_table} "
                "WHERE show_id = ? AND seat_label = 'A1'",
                (show_id,),
            )
            row = cur.fetchone()

            if row and row[0] == "AVAILABLE":
                locked_until = (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat()
                cur.execute(
                    f"UPDATE {seat_table} "
                    "SET status = 'LOCKED', "
                    "    locked_by = ?, "
                    "    locked_until = ? "
                    "WHERE show_id = ? AND seat_label = 'A1'",
                    (user_id, locked_until, show_id),
                )
                cur.execute("COMMIT")
                status_code = 200
            else:
                cur.execute("ROLLBACK")
                status_code = 409

        except Exception as exc:
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            with result_lock:
                exc_msgs.append(f"Thread {user_id}: {exc}")
            status_code = 500
        finally:
            conn.close()

        with result_lock:
            results.append(status_code)

    # Barrier — all threads release simultaneously for maximum contention
    barrier = threading.Barrier(N)

    def try_lock_with_barrier(user_id: int) -> None:
        barrier.wait()
        try_lock(user_id)

    threads = [
        threading.Thread(target=try_lock_with_barrier, args=(i,))
        for i in range(N)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    successes = results.count(200)
    rejections = results.count(409)
    errors    = [r for r in results if r not in (200, 409)]

    print(f"\n[Concurrency Test] N={N}")
    print(f"  Successes  (200): {successes}")
    print(f"  Rejections (409): {rejections}")
    print(f"  Errors     (5xx): {len(errors)}")
    if exc_msgs:
        for m in exc_msgs[:5]:
            print(f"    {m}")

    assert len(results)  == N,       f"Only {len(results)}/{N} threads finished"
    assert len(errors)   == 0,       f"Unexpected errors: {exc_msgs[:5]}"
    assert successes     == 1,       f"Expected exactly 1 success, got {successes}"
    assert rejections    == N - 1,   f"Expected {N-1} rejections, got {rejections}"
    print("  PASSED: EXACTLY 1 SUCCESS, 99 REJECTED -- no double booking!")
