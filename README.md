# SeatLock

[![Live Demo](https://img.shields.io/badge/demo-online-success?style=flat&logo=render)](https://seatlock-yahk.onrender.com)
![Tests](https://img.shields.io/badge/tests-32%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![React](https://img.shields.io/badge/React-18-61DAFB)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

> **BookMyShow-style seat booking that guarantees exactly one booking succeeds when 1,000 users race for the same seat -- no Redis, no Celery, no message queue required.**

🚀 **Live Application:** [https://seatlock-yahk.onrender.com](https://seatlock-yahk.onrender.com)  
📖 **Interactive API Docs (Swagger):** [https://seatlock-yahk.onrender.com/docs](https://seatlock-yahk.onrender.com/docs)

---

## Table of Contents

1. [Key Features](#key-features)
2. [Architecture Overview](#architecture-overview)
3. [How Locking Works](#how-locking-works)
4. [Quick Start](#quick-start)
5. [API Reference](#api-reference)
6. [Running Tests](#running-tests)
7. [Load Test](#load-test)
8. [Design Decisions](#design-decisions)
9. [Tech Stack](#tech-stack)
10. [Roadmap](#roadmap)

---

## Key Features

- **Concurrency-safe locking** -- `SELECT FOR UPDATE` with sorted seat labels prevents deadlocks and double-bookings under any level of concurrent load.
- **All-or-none seat batches** -- if any seat in a requested batch is already locked, the entire request is rejected with `409 Conflict`.
- **5-minute lock expiry** -- locks automatically expire so seats are never permanently held by abandoned sessions.
- **Zero external dependencies** -- SQLite WAL mode handles local development and CI; swap in PostgreSQL for production with a single env var.
- **32 automated tests** -- covers auth, lock logic, booking flows, cancellation, and a 100-thread concurrency scenario.
- **1,000-user load test** -- asyncio + httpx hammers a single seat; exactly one booking succeeds every time.
- **Full-stack, single process** -- FastAPI serves the React/Vite/Tailwind frontend from `/` so there is nothing extra to deploy.
- **Real-time seat grid** -- frontend polls every 3 seconds to reflect seat availability changes.
- **Cancel-friendly UNIQUE constraint** -- cancelled bookings rewrite the seat label to free the database constraint without deleting rows.

---

## Architecture Overview

```mermaid
flowchart LR
    subgraph Client
        B[Browser\nReact + Vite]
    end

    subgraph Server["FastAPI Process (uvicorn)"]
        direction TB
        API[FastAPI Router]
        LOCK["POST /shows/{id}/lock\nSELECT FOR UPDATE"]
        BOOK["POST /bookings/confirm\nUNIQUE constraint"]
        AUTH[POST /auth/*]
        BROWSE[GET /movies\nGET /shows\nGET /shows/{id}/seats]
    end

    subgraph DB["Database Layer (SQLAlchemy)"]
        direction TB
        PG[(PostgreSQL 16\nport 5432)]
        SQ[(SQLite WAL\nfallback)]
    end

    B -->|HTTP / JSON| API
    API --> LOCK
    API --> BOOK
    API --> AUTH
    API --> BROWSE
    LOCK -->|BEGIN\nSELECT FOR UPDATE\nCOMMIT| PG
    LOCK -->|BEGIN IMMEDIATE\nSELECT\nCOMMIT| SQ
    BOOK --> PG
    BOOK --> SQ
    AUTH --> PG
    AUTH --> SQ
    BROWSE --> PG
    BROWSE --> SQ
    PG -.->|auto-detect port 5432| DB
    SQ -.->|fallback when port closed| DB
```

**Request lifecycle for a seat lock:**

```
Browser                    FastAPI                       Database
  |                           |                              |
  |-- POST /shows/1/lock ---> |                              |
  |   { seats: ["A1","A2"] }  |                              |
  |                           |-- BEGIN (sorted seat order)->|
  |                           |-- SELECT ... FOR UPDATE  --> |
  |                           |<- rows locked or 409      -- |
  |                           |-- UPDATE ShowSeat.status --> |
  |                           |-- COMMIT                 --> |
  |<-- 200 OK (lock held) --- |                              |
  |   (expires in 5 min)      |                              |
```

---

## How Locking Works

SeatLock uses the database itself as the concurrency primitive -- no external lock manager is needed.

### 1. SELECT FOR UPDATE

When a user requests a seat, the server opens a transaction and issues `SELECT ... FOR UPDATE` on the relevant `ShowSeat` rows. Any other transaction trying to lock the same rows will block until the first transaction commits or rolls back. This is a hard serialisation point enforced by the database engine.

### 2. Sorted Seat Labels (Deadlock Prevention)

All seat labels in a batch are **sorted lexicographically before locking**. This means two concurrent requests for seats `["A1", "B2"]` and `["B2", "A1"]` will always acquire locks in the same order (`A1` then `B2`), eliminating the circular-wait condition that causes deadlocks.

### 3. All-or-None Semantics

After acquiring the row-level locks, the server checks whether any seat in the batch is already in `LOCKED` or `BOOKED` status. If even one seat is unavailable, the **entire batch is rejected** with `409 Conflict` and the transaction is rolled back immediately. No partial locks are ever committed.

### 4. 5-Minute Lock Expiry

Each `ShowSeat` row stores a `locked_until` timestamp when it enters `LOCKED` status. A background check at booking time (and at lock time) treats any row whose `locked_until` is in the past as `AVAILABLE`, regardless of the stored status. This prevents seats from being permanently held by users who close the browser without confirming.

### 5. UNIQUE Constraint as Final Safety Net

The `bookings` table has a `UNIQUE(show_id, seat_label)` constraint. Even if two requests somehow pass the `SELECT FOR UPDATE` check (e.g., in a degraded isolation scenario), the database will reject the second `INSERT` with an integrity error, which FastAPI catches and returns as `409`.

### 6. Cancel Without Losing History

When a booking is cancelled, the `seat_label` column is rewritten to `CANCELLED_{booking_id}_{original_label}`. This releases the `UNIQUE` constraint so the seat can be re-booked, while the original booking row is preserved for audit purposes.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend build only)
- PostgreSQL 16 (optional -- SQLite is used automatically if PostgreSQL is not running)

### 1. Clone and create a virtual environment

```powershell
git clone https://github.com/RohanDeshmukh-2004/Seatlock-zero-double-booking-system.git
cd Seatlock-zero-double-booking-system
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install Python dependencies

```powershell
pip install -r backend/requirements.txt
```

### 3. Build the frontend

```powershell
cd frontend
npm install
npm run build
cd ..
```

> The built assets are placed in `frontend/dist/`. FastAPI serves this directory at `/` automatically -- no separate frontend server is needed.

### 4. Seed the database

```powershell
python -m backend.app.seed
```

This creates:
- 3 movies
- 5 shows (each with 100 seats, labelled A1-A10 through J1-J10)
- 2 test users (see below)

**Seeded test accounts:**

| Email | Password | Role |
|-------|----------|------|
| admin@seatlock.com | admin123 | admin |
| user@seatlock.com | user123 | user |

### 5. Start the server

```powershell
.\venv\Scripts\uvicorn.exe backend.app.main:app --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

The API docs (Swagger UI) are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Using PostgreSQL (optional)

Start a PostgreSQL 16 instance on the default port `5432`. The app auto-detects whether port 5432 is reachable and connects to it. No additional configuration is required beyond setting the standard `DATABASE_URL` environment variable if you want a custom connection string.

If PostgreSQL is not running, the app silently falls back to a local `seatlock.db` SQLite file with WAL mode enabled.

---

## API Reference

All endpoints (except `GET /health`) return JSON. Protected endpoints require a `Bearer` token in the `Authorization` header, obtained from `/auth/login` or `/auth/register`.

### Authentication

| Method | Endpoint | Auth | Request Body | Response |
|--------|----------|------|--------------|----------|
| `POST` | `/auth/register` | No | `{ "email": "...", "password": "..." }` | `201 { "access_token": "..." }` |
| `POST` | `/auth/login` | No | `{ "email": "...", "password": "..." }` | `200 { "access_token": "..." }` |
| `GET` | `/auth/me` | Yes | -- | `200 { "id", "email", "role" }` |

### Browse

| Method | Endpoint | Auth | Query Params | Response |
|--------|----------|------|--------------|----------|
| `GET` | `/movies` | No | -- | `200 [{ "id", "title", "genre", ... }]` |
| `GET` | `/shows` | No | `?movie_id=<id>` | `200 [{ "id", "starts_at", "venue", ... }]` |
| `GET` | `/shows/{id}/seats` | No | -- | `200 [{ "label", "status", ... }]` |

### Locking

| Method | Endpoint | Auth | Request Body | Response |
|--------|----------|------|--------------|----------|
| `POST` | `/shows/{id}/lock` | Yes | `{ "seats": ["A1", "A2"] }` | `200 OK` or `409 Conflict` |
| `POST` | `/shows/{id}/unlock` | Yes | `{ "seats": ["A1", "A2"] }` | `200 OK` |

A `409` response means at least one requested seat is already locked or booked. The entire batch is rejected -- no seats are locked.

### Bookings

| Method | Endpoint | Auth | Request Body | Response |
|--------|----------|------|--------------|----------|
| `POST` | `/bookings/confirm` | Yes | `{ "show_id": 1, "seats": ["A1"], "payment_token": "tok_..." }` | `201 { "booking_id", ... }` |
| `GET` | `/bookings/me` | Yes | -- | `200 [{ "id", "show_id", "seats", "status" }]` |
| `POST` | `/bookings/{id}/cancel` | Yes | -- | `200 OK` |

### Health

| Method | Endpoint | Auth | Response |
|--------|----------|------|----------|
| `GET` | `/health` | No | `200 { "status": "ok" }` |

---

## Running Tests

The test suite uses `pytest` and requires no running server -- it spins up an in-memory SQLite database for each test session.

```powershell
.\venv\Scripts\pytest.exe -v
```

Expected output summary:

```
32 passed in X.XXs
```

### Test categories

| Module | Count | What it covers |
|--------|-------|----------------|
| `tests/test_auth.py` | ~6 | Register, login, duplicate email, bad password |
| `tests/test_locks.py` | ~8 | Lock, unlock, expiry, 409 on conflict |
| `tests/test_bookings.py` | ~10 | Confirm, list, cancel, re-book after cancel |
| `tests/test_concurrency.py` | ~8 | 100-thread race -- exactly 1 booking succeeds |

### CI

Tests run automatically on every push via GitHub Actions (`.github/workflows/ci.yml`) with a real PostgreSQL 16 service container, so both database backends are tested in CI.

---

## Load Test

The load test fires **1,000 concurrent HTTP requests** at a single seat to prove the concurrency guarantee holds at scale.

### Prerequisites

The server must be running and the database must be seeded before running the load test.

```powershell
# Terminal 1 -- start the server
.\venv\Scripts\uvicorn.exe backend.app.main:app --port 8000

# Terminal 2 -- run the load test
python loadtest/run.py
```

### What it does

1. Authenticates 1,000 virtual users (reusing the seeded `user@seatlock.com` credentials or registering new ones).
2. Each user sends `POST /shows/1/lock` for seat `A1`, then immediately `POST /bookings/confirm`.
3. All 1,000 requests are dispatched concurrently via `asyncio` + `httpx.AsyncClient`.

### Expected result

```
Total requests : 1000
Bookings created : 1
Conflicts (409) : 999
Errors : 0
```

Exactly **one** booking is created. All other requests receive a clean `409 Conflict`. No data corruption, no duplicate bookings, no server errors.

---

## Design Decisions

### 1. SELECT FOR UPDATE with Sorted Seat Labels

Acquiring row-level locks in a consistent order (lexicographic sort on seat label) eliminates the circular-wait condition that causes deadlocks when two transactions try to lock the same rows in opposite orders. This is a classical concurrency technique and requires no application-level coordination.

### 2. All-or-None Locking

Partial locks create a poor user experience (user thinks they have `A1` and `A2` but only `A1` was locked) and complicate booking confirmation logic. SeatLock rejects the entire batch if any seat is unavailable, keeping the state machine simple and the UI feedback unambiguous.

### 3. UNIQUE(show_id, seat_label) as Final Safety Net

The database constraint is the last line of defence against any edge case that slips past the application-level lock check (e.g., a clock skew on lock expiry). An integrity error at the `INSERT` level is always caught and surfaced as `409`.

### 4. Cancel Rewrites seat_label

SQL `UNIQUE` constraints cannot be "partially released" -- the only way to free a unique slot while keeping the row is to change the value. Prefixing cancelled rows with `CANCELLED_{id}_` is a deterministic, collision-free convention that preserves booking history for auditing without requiring a separate `cancelled_bookings` table.

### 5. No Redis, No Celery

Redis and Celery add operational overhead (extra services to deploy, monitor, and restart). SQLite WAL mode provides sufficient concurrency for development and small-scale production, while PostgreSQL `SELECT FOR UPDATE` handles high-concurrency production workloads. The lock expiry is enforced lazily at read time rather than by a scheduled task, eliminating the need for a background worker.

### 6. Docker Only for PostgreSQL

Running the full application in Docker would add complexity without benefit for a demonstration project. Only a PostgreSQL container is provided for developers who prefer not to install PostgreSQL natively. The application itself runs directly in a Python virtual environment for fast iteration.

### 7. Frontend Polling (No WebSocket)

WebSockets require additional server infrastructure (connection state, ping/pong, reconnect logic) and complicate load balancing. Polling every 3 seconds is sufficient for seat availability updates, keeps the server stateless, and works correctly behind any HTTP proxy or CDN.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI 0.110+ |
| ASGI server | Uvicorn |
| ORM | SQLAlchemy 2.x (async-compatible) |
| Primary database | PostgreSQL 16 |
| Fallback database | SQLite 3 (WAL mode) |
| Auth | JWT (python-jose + passlib bcrypt) |
| Frontend framework | React 18 |
| Frontend build tool | Vite 5 |
| Styling | Tailwind CSS 3 |
| HTTP client (load test) | httpx (async) |
| Test framework | pytest + httpx (TestClient) |
| CI | GitHub Actions |

---

## Roadmap

The following improvements are planned for future releases:

- **WebSockets for real-time seat updates** -- replace the 3-second polling loop with a WebSocket broadcast so all connected clients see seat status changes instantly without extra HTTP overhead.
- **Redis distributed locking** -- for multi-process or multi-node deployments where a single PostgreSQL `SELECT FOR UPDATE` may not be sufficient, integrate Redis `SET NX PX` (or Redlock) as an optional distributed lock layer in front of the database transaction.
- **Real payment gateway integration** -- replace the placeholder `payment_token` field with a full Stripe or Razorpay checkout flow, including webhook handling for async payment confirmation and automatic seat release on payment failure.
- **Seat hold timer UI** -- display a countdown in the browser showing how long the user's 5-minute lock has remaining, with an automatic unlock if they navigate away.
- **Admin dashboard** -- show occupancy rates, revenue, and cancellation stats per show, accessible only to users with the `admin` role.
- **Alembic migrations** -- replace the current `Base.metadata.create_all` approach with versioned Alembic migrations for safe schema evolution in production.
