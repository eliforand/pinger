from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from pinger import db, hosts
from pinger.web.app import create_app
from pinger.web.security import hash_password

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def make_client(tmp_path, **kwargs):
    app = create_app(db_path=tmp_path / "web.db", secret_key="test-secret", **kwargs)
    return TestClient(app, follow_redirects=False), app


def add_admin(dbfile, username="admin", password="secret123", role="admin"):
    conn = db.connect(dbfile)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, access_mode, is_active, created_at)"
        " VALUES (?, ?, ?, 'all', 1, ?)",
        (username, hash_password(password), role, db.now_iso()),
    )
    conn.commit()
    uid = int(cur.lastrowid)
    conn.close()
    return uid


def get_csrf(client, path):
    response = client.get(path)
    match = CSRF_RE.search(response.text)
    assert match, response.text
    return match.group(1)


def test_setup_creates_first_admin_and_logs_in(tmp_path):
    client, app = make_client(tmp_path)
    token = get_csrf(client, "/setup")
    response = client.post(
        "/setup",
        data={"csrf_token": token, "username": "root", "password": "password1"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    conn = db.connect(app.state.db_path)
    user = conn.execute("SELECT * FROM users WHERE username='root'").fetchone()
    conn.close()
    assert user["role"] == "admin"

    home = client.get("/")
    assert home.status_code == 200
    assert "root" in home.text


def test_setup_short_password_rejected(tmp_path):
    client, app = make_client(tmp_path)
    token = get_csrf(client, "/setup")
    response = client.post(
        "/setup",
        data={"csrf_token": token, "username": "root", "password": "short"},
    )
    assert response.status_code == 200
    assert "не короче 8" in response.text
    conn = db.connect(app.state.db_path)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    conn.close()


def test_setup_closed_after_admin_exists(tmp_path):
    client, app = make_client(tmp_path)
    add_admin(app.state.db_path)
    response = client.get("/setup")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_guard_redirects_to_setup_when_no_admin(tmp_path):
    client, app = make_client(tmp_path)
    for path in ("/", "/login"):
        response = client.get(path)
        assert response.status_code == 303
        assert response.headers["location"] == "/setup"


def test_home_requires_login(tmp_path):
    client, app = make_client(tmp_path)
    add_admin(app.state.db_path)
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_and_logout(tmp_path):
    client, app = make_client(tmp_path)
    add_admin(app.state.db_path, "admin", "secret123")

    token = get_csrf(client, "/login")
    bad = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "wrong"},
    )
    assert bad.status_code == 200
    assert "Неверный логин или пароль" in bad.text

    token = get_csrf(client, "/login")
    good = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "secret123"},
    )
    assert good.status_code == 303
    assert good.headers["location"] == "/"
    assert client.get("/").status_code == 200

    token = get_csrf(client, "/")
    logout = client.post("/logout", data={"csrf_token": token})
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert client.get("/").status_code == 303


def test_csrf_missing_rejected(tmp_path):
    client, app = make_client(tmp_path)
    add_admin(app.state.db_path)
    client.get("/login")  # получаем сессию
    response = client.post(
        "/login", data={"username": "admin", "password": "secret123"}
    )
    assert response.status_code == 400


def test_csrf_wrong_token_rejected(tmp_path):
    client, app = make_client(tmp_path)
    add_admin(app.state.db_path)
    client.get("/login")
    response = client.post(
        "/login",
        data={
            "csrf_token": "definitely-wrong",
            "username": "admin",
            "password": "secret123",
        },
    )
    assert response.status_code == 400


def test_setup_token_required(tmp_path, monkeypatch):
    monkeypatch.setenv("PINGER_SETUP_TOKEN", "letmein")
    client, app = make_client(tmp_path)
    token = get_csrf(client, "/setup")

    missing = client.post(
        "/setup",
        data={"csrf_token": token, "username": "root", "password": "password1"},
    )
    assert missing.status_code == 200
    assert "setup-токен" in missing.text

    token = get_csrf(client, "/setup")
    ok = client.post(
        "/setup",
        data={
            "csrf_token": token,
            "username": "root",
            "password": "password1",
            "setup_token": "letmein",
        },
    )
    assert ok.status_code == 303


def test_inactive_user_cannot_login(tmp_path):
    client, app = make_client(tmp_path)
    add_admin(app.state.db_path, "root", "supersecret")
    uid = add_admin(app.state.db_path, "admin", "secret123")
    conn = db.connect(app.state.db_path)
    conn.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
    conn.commit()
    conn.close()

    token = get_csrf(client, "/login")
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "secret123"},
    )
    assert response.status_code == 200
    assert "Неверный логин или пароль" in response.text