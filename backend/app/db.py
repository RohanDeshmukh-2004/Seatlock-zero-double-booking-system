import os
import socket
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DEFAULT_PG_URL = "postgresql://seatlock:seatlock@localhost:5432/seatlock"
DATABASE_URL = os.getenv("DATABASE_URL")

# Auto-detect if PostgreSQL is available on localhost:5432 when no explicit URL is given
if not DATABASE_URL:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("127.0.0.1", 5432))
        sock.close()
        DATABASE_URL = DEFAULT_PG_URL
    except (socket.error, OSError):
        print("[*] Note: PostgreSQL not detected on localhost:5432.")
        print("[*] Falling back to local SQLite database (sqlite:///./seatlock.db).")
        print("[*] Run 'docker compose up -d' anytime to switch to PostgreSQL container.")
        DATABASE_URL = "sqlite:///./seatlock.db"

is_sqlite = DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30}
    )
    # Enable WAL mode for better concurrency in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
else:
    # High-concurrency connection pool tuned for PostgreSQL
    engine = create_engine(
        DATABASE_URL,
        pool_size=50,
        max_overflow=100,
        pool_timeout=60,
        pool_pre_ping=True
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
