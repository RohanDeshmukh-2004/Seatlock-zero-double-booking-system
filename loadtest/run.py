"""Race 1,000 distinct authenticated users for one seat.

Start the API with the same environment and database URL as this script, seed
the database, then run ``python loadtest/run.py`` from the project root.
"""

import asyncio
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).parents[1]))

from backend.app.auth import create_access_token
from backend.app.db import SessionLocal, engine
from backend.app.models import Booking, ShowSeat, User

BASE_URL = "http://127.0.0.1:8000"
SHOW_ID = 1
SEAT_LABEL = "A1"
TOTAL_REQUESTS = 1000
RESULTS_FILE = Path(__file__).parents[1] / "docs" / "loadtest-results.md"


def prepare_users() -> list[str]:
    """Create/reuse 1,000 fixture users and return their distinct JWTs."""
    db = SessionLocal()
    try:
        existing_users = {
            u.email: u for u in db.query(User).filter(User.email.like("loadtest-%")).all()
        }
        users = []
        new_users = []
        for number in range(TOTAL_REQUESTS):
            email = f"loadtest-{number:04d}@example.invalid"
            user = existing_users.get(email)
            if user is None:
                user = User(email=email, password_hash="load-test-account-no-login", role="user")
                new_users.append(user)
            users.append(user)
        if new_users:
            db.add_all(new_users)
            db.commit()
            for u in new_users:
                db.refresh(u)
        return [
            create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
            for user in users
        ]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_seat() -> None:
    """Reset seat between runs and clear any existing bookings for clean test."""
    db = SessionLocal()
    try:
        seat = (
            db.query(ShowSeat)
            .filter(ShowSeat.show_id == SHOW_ID, ShowSeat.seat_label == SEAT_LABEL)
            .one_or_none()
        )
        if seat is None:
            raise RuntimeError(f"Seat {SEAT_LABEL} was not found for show {SHOW_ID}; run the seed script.")
        seat.status = "AVAILABLE"
        seat.locked_by = None
        seat.locked_until = None
        db.query(Booking).filter(
            Booking.show_id == SHOW_ID,
            Booking.seat_label == SEAT_LABEL,
        ).delete()
        db.commit()
        print(f"[reset] Seat {SEAT_LABEL} for show {SHOW_ID} reset to AVAILABLE.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def fire_lock(client: httpx.AsyncClient, token: str, start: asyncio.Event) -> tuple[int, float]:
    await start.wait()
    began = time.perf_counter()
    try:
        response = await client.post(
            f"{BASE_URL}/shows/{SHOW_ID}/lock",
            json={"seats": [SEAT_LABEL]},
            headers={"Authorization": f"Bearer {token}"},
        )
        return response.status_code, (time.perf_counter() - began) * 1000
    except Exception:
        return -1, (time.perf_counter() - began) * 1000


def percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percent - 1]


def count_double_bookings() -> int:
    db = SessionLocal()
    try:
        groups = (
            db.query(func.count(Booking.id))
            .filter(
                Booking.show_id == SHOW_ID,
                Booking.seat_label == SEAT_LABEL,
                Booking.status == "CONFIRMED",
            )
            .group_by(Booking.show_id, Booking.seat_label)
            .all()
        )
        return sum(max(count - 1, 0) for (count,) in groups)
    finally:
        db.close()


async def main() -> None:
    print(f"Targeting: {BASE_URL}")
    print(f"Database dialect: {engine.dialect.name}")

    async with httpx.AsyncClient(
        timeout=120,
        limits=httpx.Limits(max_connections=TOTAL_REQUESTS, max_keepalive_connections=100),
    ) as client:
        try:
            health = await client.get(f"{BASE_URL}/health")
            health.raise_for_status()
        except Exception as exc:
            print(f"Server at {BASE_URL} not reachable: {exc}")
            print("Please run the backend server first: uvicorn backend.app.main:app --port 8000")
            sys.exit(1)

        reset_seat()
        print(f"Preparing {TOTAL_REQUESTS} authenticated users...")
        tokens = prepare_users()
        print("Ready. Firing 1000 concurrent lock requests...")
        start = asyncio.Event()
        tasks = [asyncio.create_task(fire_lock(client, token, start)) for token in tokens]
        started = time.perf_counter()
        start.set()
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - started

    errors = [result for result in responses if isinstance(result, Exception) or (isinstance(result, tuple) and result[0] == -1)]
    outcomes = [result for result in responses if not isinstance(result, Exception) and (isinstance(result, tuple) and result[0] != -1)]
    successes = sum(status == 200 for status, _ in outcomes)
    rejections = sum(status == 409 for status, _ in outcomes)
    other_responses = len(outcomes) - successes - rejections
    latencies = [latency for _, latency in outcomes]
    double_bookings = count_double_bookings()

    print()
    print("=" * 60)
    print("  Load Test Summary")
    print("=" * 60)
    print(f"  Requests: {TOTAL_REQUESTS}")
    print(f"  Successes (200): {successes}")
    print(f"  Rejections (409): {rejections}")
    print(f"  Other HTTP responses: {other_responses}")
    print(f"  Request errors: {len(errors)}")
    print(f"  Double bookings: {double_bookings}")
    print(f"  p50 latency: {percentile(latencies, 50):.1f} ms" if latencies else "  p50 latency: n/a")
    print(f"  p95 latency: {percentile(latencies, 95):.1f} ms" if latencies else "  p95 latency: n/a")
    print(f"  Elapsed: {elapsed:.2f} s")
    print("=" * 60)

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(
        f"""# SeatLock 1,000-request concurrency test

**Run at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  
**Database:** {engine.dialect.name}  
**Target:** `POST /shows/{SHOW_ID}/lock` for `{SEAT_LABEL}`  
**Concurrency:** {TOTAL_REQUESTS} distinct authenticated users

| Metric | Result |
|---|---:|
| Requests | {TOTAL_REQUESTS} |
| Successful locks | {successes} |
| Rejections (409) | {rejections} |
| Other HTTP responses | {other_responses} |
| Request errors | {len(errors)} |
| Double bookings | {double_bookings} |
| p50 latency | {percentile(latencies, 50):.1f} ms |
| p95 latency | {percentile(latencies, 95):.1f} ms |
| Elapsed | {elapsed:.2f} s |

Expected: 1 success, 999 rejections, 0 double bookings, and 0 errors.
""",
        encoding="utf-8",
    )
    print(f"Results saved to {RESULTS_FILE}")

    if (successes, rejections, other_responses, len(errors), double_bookings) != (1, 999, 0, 0, 0):
        print("Note: Concurrency result differed from (1, 999, 0, 0, 0).")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
