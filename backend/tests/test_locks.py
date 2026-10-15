"""
Unit tests: seat locking, unlocking, and expiry behaviour.
"""
from datetime import datetime, timedelta, timezone
import pytest


def _get_token(client, email, password="pass123"):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _lock(client, show_id, seats, token):
    return client.post(f"/shows/{show_id}/lock", json={"seats": seats}, headers=_auth(token))


def _unlock(client, show_id, seats, token):
    return client.post(f"/shows/{show_id}/unlock", json={"seats": seats}, headers=_auth(token))


class TestLock:
    def test_lock_available_seat(self, client, seeded_db):
        token = _get_token(client, "alice@test.com")
        res = _lock(client, seeded_db["show_id"], ["A1"], token)
        assert res.status_code == 200
        data = res.json()
        assert "A1" in data["seats"]
        assert "locked_until" in data

    def test_lock_conflict_returns_409(self, client, seeded_db):
        """User 1 locks A1; User 2 tries same seat → 409."""
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        _lock(client, seeded_db["show_id"], ["A1"], t1)
        res = _lock(client, seeded_db["show_id"], ["A1"], t2)
        assert res.status_code == 409
        assert "not available" in res.json()["detail"].lower()

    def test_lock_same_user_conflict(self, client, seeded_db):
        """Same user cannot re-lock a seat they already hold."""
        token = _get_token(client, "alice@test.com")
        _lock(client, seeded_db["show_id"], ["A1"], token)
        res = _lock(client, seeded_db["show_id"], ["A1"], token)
        assert res.status_code == 409

    def test_lock_all_or_none(self, client, seeded_db):
        """
        A2 is free; A1 is locked by user1.
        User2 requests [A1, A2] → 409 and A2 must remain AVAILABLE.
        """
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        _lock(client, seeded_db["show_id"], ["A1"], t1)

        res = _lock(client, seeded_db["show_id"], ["A1", "A2"], t2)
        assert res.status_code == 409

        # A2 must still be AVAILABLE (transaction rolled back)
        seats = client.get(f"/shows/{seeded_db['show_id']}/seats").json()
        a2 = next(s for s in seats if s["seat_label"] == "A2")
        assert a2["status"] == "AVAILABLE"

    def test_lock_expired_seat_becomes_free(self, client, seeded_db, db):
        """Manually expire a lock; another user should be able to lock it."""
        from backend.app.models import ShowSeat
        # Mark A3 as locked with a past expiry
        seat = db.query(ShowSeat).filter_by(
            show_id=seeded_db["show_id"], seat_label="A3"
        ).first()
        seat.status = "LOCKED"
        seat.locked_by = seeded_db["user_id"]
        seat.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        # User2 should now be able to lock A3
        t2 = _get_token(client, "bob@test.com")
        res = _lock(client, seeded_db["show_id"], ["A3"], t2)
        assert res.status_code == 200

    def test_lock_unauthenticated(self, client, seeded_db):
        res = client.post(f"/shows/{seeded_db['show_id']}/lock", json={"seats": ["A1"]})
        assert res.status_code == 401

    def test_lock_invalid_show(self, client, seeded_db):
        token = _get_token(client, "alice@test.com")
        res = _lock(client, 99999, ["A1"], token)
        assert res.status_code == 404

    def test_lock_invalid_seat(self, client, seeded_db):
        token = _get_token(client, "alice@test.com")
        res = _lock(client, seeded_db["show_id"], ["Z99"], token)
        assert res.status_code == 400


class TestUnlock:
    def test_unlock_own_lock(self, client, seeded_db):
        token = _get_token(client, "alice@test.com")
        _lock(client, seeded_db["show_id"], ["B1"], token)
        res = _unlock(client, seeded_db["show_id"], ["B1"], token)
        assert res.status_code == 200
        assert "B1" in res.json()["unlocked_seats"]

    def test_unlock_makes_seat_available(self, client, seeded_db):
        token = _get_token(client, "alice@test.com")
        show_id = seeded_db["show_id"]
        _lock(client, show_id, ["B2"], token)
        _unlock(client, show_id, ["B2"], token)

        seats = client.get(f"/shows/{show_id}/seats").json()
        b2 = next(s for s in seats if s["seat_label"] == "B2")
        assert b2["status"] == "AVAILABLE"

    def test_unlock_other_users_lock_is_noop(self, client, seeded_db):
        """Unlocking a seat locked by another user should silently do nothing."""
        t1 = _get_token(client, "alice@test.com")
        t2 = _get_token(client, "bob@test.com")
        _lock(client, seeded_db["show_id"], ["C1"], t1)
        # User2 tries to unlock C1 (they don't hold it)
        res = _unlock(client, seeded_db["show_id"], ["C1"], t2)
        assert res.status_code == 200
        assert res.json()["unlocked_seats"] == []
