"""
Unit tests: booking confirmation and cancellation.
"""
import pytest


def _get_token(client, email, password="pass123"):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _lock(client, show_id, seats, token):
    return client.post(f"/shows/{show_id}/lock", json={"seats": seats}, headers=_auth(token))


def _confirm(client, show_id, seats, token):
    return client.post(
        "/bookings/confirm",
        json={"show_id": show_id, "seats": seats, "payment_token": "fake"},
        headers=_auth(token),
    )


class TestConfirmBooking:
    def test_confirm_after_lock(self, client, seeded_db):
        """Lock D1, confirm → 200, seat becomes BOOKED."""
        token = _get_token(client, "alice@test.com")
        show_id = seeded_db["show_id"]
        _lock(client, show_id, ["D1"], token)
        res = _confirm(client, show_id, ["D1"], token)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "CONFIRMED"
        assert "BK-" in data["booking_reference"]

        seats = client.get(f"/shows/{show_id}/seats").json()
        d1 = next(s for s in seats if s["seat_label"] == "D1")
        assert d1["status"] == "BOOKED"

    def test_confirm_without_lock_fails(self, client, seeded_db):
        """Attempting to confirm a seat that was never locked → 409."""
        token = _get_token(client, "alice@test.com")
        res = _confirm(client, seeded_db["show_id"], ["E1"], token)
        assert res.status_code == 409

    def test_confirm_other_users_lock_fails(self, client, seeded_db):
        """User1 locks D2; User2 cannot confirm it."""
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        _lock(client, seeded_db["show_id"], ["D2"], t1)
        res = _confirm(client, seeded_db["show_id"], ["D2"], t2)
        assert res.status_code == 409

    def test_confirm_expired_lock_fails(self, client, seeded_db, db):
        """Confirm on an expired lock → 409."""
        from datetime import datetime, timedelta, timezone
        from backend.app.models import ShowSeat

        token = _get_token(client, "alice@test.com")
        show_id = seeded_db["show_id"]
        _lock(client, show_id, ["F1"], token)

        # Manually expire the lock
        seat = db.query(ShowSeat).filter_by(show_id=show_id, seat_label="F1").first()
        seat.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        res = _confirm(client, show_id, ["F1"], token)
        assert res.status_code == 409
        assert "expired" in res.json()["detail"].lower()

    def test_double_booking_rejected(self, client, seeded_db):
        """Two separate users each confirm the same seat; only one succeeds."""
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        show_id = seeded_db["show_id"]

        # User1 locks and confirms G1
        _lock(client, show_id, ["G1"], t1)
        res1 = _confirm(client, show_id, ["G1"], t1)
        assert res1.status_code == 200

        # User2 cannot confirm same seat (already BOOKED)
        res2 = _confirm(client, show_id, ["G1"], t2)
        assert res2.status_code == 409


class TestGetMyBookings:
    def test_returns_only_own_bookings(self, client, seeded_db):
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        show_id = seeded_db["show_id"]

        _lock(client, show_id, ["H1"], t1)
        _confirm(client, show_id, ["H1"], t1)

        bookings_alice = client.get("/bookings/me", headers=_auth(t1)).json()
        bookings_bob = client.get("/bookings/me", headers=_auth(t2)).json()

        assert len(bookings_alice) == 1
        assert len(bookings_bob) == 0
        assert bookings_alice[0]["seat_label"] == "H1"

    def test_unauthenticated_returns_401(self, client):
        res = client.get("/bookings/me")
        assert res.status_code == 401


class TestCancelBooking:
    def test_cancel_restores_seat(self, client, seeded_db):
        """Cancel → seat back to AVAILABLE."""
        token = _get_token(client, "alice@test.com")
        show_id = seeded_db["show_id"]
        _lock(client, show_id, ["I1"], token)
        _confirm(client, show_id, ["I1"], token)

        bookings = client.get("/bookings/me", headers=_auth(token)).json()
        booking_id = next(b["id"] for b in bookings if b["seat_label"] == "I1")

        cancel_res = client.post(f"/bookings/{booking_id}/cancel", headers=_auth(token))
        assert cancel_res.status_code == 200

        seats = client.get(f"/shows/{show_id}/seats").json()
        i1 = next(s for s in seats if s["seat_label"] == "I1")
        assert i1["status"] == "AVAILABLE"

    def test_cancel_another_users_booking_fails(self, client, seeded_db):
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        show_id = seeded_db["show_id"]
        _lock(client, show_id, ["J1"], t1)
        _confirm(client, show_id, ["J1"], t1)

        bookings = client.get("/bookings/me", headers=_auth(t1)).json()
        booking_id = bookings[0]["id"]

        res = client.post(f"/bookings/{booking_id}/cancel", headers=_auth(t2))
        assert res.status_code == 404

    def test_cancel_already_cancelled_fails(self, client, seeded_db):
        token = _get_token(client, "alice@test.com")
        show_id = seeded_db["show_id"]
        _lock(client, show_id, ["J2"], token)
        _confirm(client, show_id, ["J2"], token)

        bookings = client.get("/bookings/me", headers=_auth(token)).json()
        booking_id = bookings[0]["id"]
        client.post(f"/bookings/{booking_id}/cancel", headers=_auth(token))

        # Second cancel
        res = client.post(f"/bookings/{booking_id}/cancel", headers=_auth(token))
        assert res.status_code == 400
