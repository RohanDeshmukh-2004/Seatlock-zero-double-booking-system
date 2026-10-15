"""
Unit tests: authentication routes (register, login, me).
"""
import pytest


def _register(client, email="test@test.com", password="password123", role="user"):
    return client.post("/auth/register", json={"email": email, "password": password, "role": role})


def _login(client, email="test@test.com", password="password123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


class TestRegister:
    def test_register_success(self, client):
        res = _register(client)
        assert res.status_code == 201
        data = res.json()
        assert "access_token" in data
        assert data["user"]["email"] == "test@test.com"
        assert data["user"]["role"] == "user"

    def test_register_duplicate_email(self, client):
        _register(client)
        res = _register(client)
        assert res.status_code == 400
        assert "already registered" in res.json()["detail"].lower()

    def test_register_short_password(self, client):
        res = _register(client, password="abc")
        assert res.status_code == 400

    def test_register_invalid_email(self, client):
        res = _register(client, email="notanemail")
        assert res.status_code == 400


class TestLogin:
    def test_login_success(self, client):
        _register(client)
        res = _login(client)
        assert res.status_code == 200
        assert "access_token" in res.json()

    def test_login_wrong_password(self, client):
        _register(client)
        res = _login(client, password="wrongpassword")
        assert res.status_code == 401

    def test_login_unknown_email(self, client):
        res = _login(client, email="nobody@test.com")
        assert res.status_code == 401


class TestMe:
    def test_me_authenticated(self, client):
        token = _register(client).json()["access_token"]
        res = client.get("/auth/me", headers=_auth_header(token))
        assert res.status_code == 200
        assert res.json()["email"] == "test@test.com"

    def test_me_unauthenticated(self, client):
        res = client.get("/auth/me")
        assert res.status_code == 401

    def test_me_invalid_token(self, client):
        res = client.get("/auth/me", headers=_auth_header("this.is.invalid"))
        assert res.status_code == 401
