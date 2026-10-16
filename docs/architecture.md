# SeatLock Architecture & Concurrency Design

This document describes the architectural decisions, database models, and concurrency control mechanisms employed by SeatLock.

---

## 1. High-Level Architecture

SeatLock is built as a single-binary deployable unit:

```
[ Client: Browser (React + Tailwind) ]
                    │
                    ▼ HTTP / JSON (REST + 3s Polling)
[ FastAPI Application Server (Uvicorn) ]
    ├── /auth/*           (JWT authentication)
    ├── /movies, /shows   (Public catalog & seat grid)
    ├── /shows/{id}/lock  (Deadlock-safe locking)
    └── /bookings/*       (Confirmation & cancellations)
                    │
                    ▼ SQLAlchemy ORM
[ Database Engine ]
    ├── Primary: PostgreSQL 16 (Row-level SELECT FOR UPDATE)
    └── Fallback: SQLite WAL (Transaction-level BEGIN IMMEDIATE)
```

FastAPI also serves the pre-built React Single Page Application directly from `frontend/dist/` at the root path `/`, removing the need for a separate reverse proxy in development and lightweight deployments.

---

## 2. Concurrency Control Mechanisms

Preventing double bookings across distributed or concurrent clients requires coordination at the database storage layer. SeatLock achieves this with zero external dependencies (no Redis, no distributed locking services).

### 2.1 Lexicographical Row Ordering (Deadlock Prevention)

When booking multiple seats (e.g., `["B2", "A1"]`), different clients might request the same seats in reverse order (`Client 1: [B2, A1]` vs `Client 2: [A1, B2]`). If transaction 1 locks `B2` and attempts to lock `A1`, while transaction 2 locks `A1` and attempts to lock `B2`, a database deadlock occurs.

**Solution:**
SeatLock sorts all seat labels lexicographically before issuing database locks:
```python
sorted_seat_labels = sorted(list(set(requested_labels)))
```
All concurrent transactions acquire row locks in the exact same sequence (`A1` then `B2`), eliminating the circular wait condition.

### 2.2 Row-Level Locking (`SELECT ... FOR UPDATE`)

On PostgreSQL, the locking route issues:
```python
db.query(ShowSeat)
  .filter(ShowSeat.show_id == id, ShowSeat.seat_label.in_(sorted_seat_labels))
  .order_by(ShowSeat.seat_label.asc())
  .with_for_update()
  .all()
```
`SELECT ... FOR UPDATE` acquires an exclusive lock on the matching rows in `show_seats`. Any competing transaction attempting to inspect or lock these same seats blocks until the first transaction commits or rolls back.

### 2.3 All-or-None Lock Validation

Partial bookings lead to inconsistent user state. Once exclusive locks are acquired:
1. Every requested seat is inspected.
2. If **any** seat is already `LOCKED` (unexpired) or `BOOKED`, the transaction immediately rolls back and returns `409 Conflict`.
3. Only if **all** seats are `AVAILABLE` or have expired locks does the transaction transition them to `LOCKED` with `locked_until = now + 5 minutes`.

### 2.4 Final Safety Net: Database UNIQUE Constraint

The `bookings` table enforces a composite unique constraint:
```sql
CONSTRAINT uq_show_seat UNIQUE (show_id, seat_label)
```
Even if application logic fails or isolation is degraded, the database rejects any attempt to insert a second confirmed booking for the same seat and show.

---

## 3. Database Schema

### `users`
- `id` (INTEGER, Primary Key)
- `email` (VARCHAR, Unique, Indexed)
- `password_hash` (VARCHAR)
- `role` (VARCHAR: 'user' | 'admin')
- `created_at` (TIMESTAMP)

### `movies`
- `id` (INTEGER, Primary Key)
- `title` (VARCHAR)
- `description` (TEXT)
- `duration_minutes` (INTEGER)

### `shows`
- `id` (INTEGER, Primary Key)
- `movie_id` (INTEGER, Foreign Key -> `movies.id`)
- `screen_name` (VARCHAR)
- `start_time` (TIMESTAMP)
- `price` (FLOAT)

### `show_seats`
- `id` (INTEGER, Primary Key)
- `show_id` (INTEGER, Foreign Key -> `shows.id`)
- `seat_label` (VARCHAR: e.g., 'A1', 'J10')
- `status` (VARCHAR: 'AVAILABLE' | 'LOCKED' | 'BOOKED')
- `locked_by` (INTEGER, Nullable Foreign Key -> `users.id`)
- `locked_until` (TIMESTAMP, Nullable)

### `bookings`
- `id` (INTEGER, Primary Key)
- `user_id` (INTEGER, Foreign Key -> `users.id`)
- `show_id` (INTEGER, Foreign Key -> `shows.id`)
- `seat_label` (VARCHAR)
- `booking_reference` (VARCHAR)
- `status` (VARCHAR: 'CONFIRMED' | 'CANCELLED')
- `created_at` (TIMESTAMP)
- *Unique Constraint:* `(show_id, seat_label)`

---

## 4. Cancellation & Auditing Strategy

When a user cancels a booking:
1. The row in `bookings` is updated to `status = 'CANCELLED'`.
2. To allow the seat to be reserved again without violating `UNIQUE(show_id, seat_label)`, the `seat_label` is rewritten to `CANCELLED_{booking_id}_{seat_label}`.
3. The corresponding `show_seats` entry is reset to `status = 'AVAILABLE'`, with `locked_by = NULL` and `locked_until = NULL`.

This preserves complete audit history without requiring separate archive tables.
