"""
Shared pytest fixtures for SeatLock backend tests.

Uses an in-memory SQLite database (reset between tests) so no external
PostgreSQL instance is required.
"""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Point to in-memory SQLite before importing the app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import User, Movie, Show, ShowSeat
from backend.app.auth import hash_password

# ---------------------------------------------------------------------------
# In-memory database engine (shared for the entire test session)
# ---------------------------------------------------------------------------
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """Provide a DB session for direct model manipulation in tests."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """FastAPI TestClient with the DB override applied."""
    return TestClient(app)


@pytest.fixture
def seeded_db(db):
    """
    Seed a minimal dataset: 1 movie, 1 show, 10x10 seats, 2 users.
    Returns a dict with useful IDs and tokens.
    """
    # Users
    user = User(email="alice@test.com", password_hash=hash_password("pass123"), role="user")
    admin = User(email="bob@test.com", password_hash=hash_password("pass123"), role="admin")
    db.add_all([user, admin])
    db.flush()

    # Movie + Show
    movie = Movie(
        title="Test Movie",
        description="A test film",
        duration_minutes=120,
    )
    db.add(movie)
    db.flush()

    from datetime import datetime, timedelta, timezone
    show = Show(
        movie_id=movie.id,
        screen_name="Screen Alpha",
        start_time=datetime.now(timezone.utc) + timedelta(hours=4),
        price=200.0,
    )
    db.add(show)
    db.flush()

    # 10 x 10 seats
    seats = []
    for row in "ABCDEFGHIJ":
        for col in range(1, 11):
            seats.append(ShowSeat(
                show_id=show.id,
                seat_label=f"{row}{col}",
                status="AVAILABLE",
            ))
    db.bulk_save_objects(seats)
    db.commit()

    return {
        "user_id": user.id,
        "admin_id": admin.id,
        "movie_id": movie.id,
        "show_id": show.id,
    }
