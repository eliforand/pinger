"""Общие помощники для веб-тестов."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from pinger import db
from pinger.web.app import create_app
from pinger.web.security import hash_password

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def make_client(tmp_path, name="web.db", **kwargs):
    app = create_app(
        db_path=tmp_path / name, secret_key="test-secret", **kwargs
    )
    return TestClient(app, follow_redirects=False), app


def add_user(
    dbfile,
    username,
    password="secret123",
    role="user",
    access_mode="all",
    is_active=1,
):
    conn = db.connect(dbfile)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, access_mode,"
        " is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            username,
            hash_password(password),
            role,
            access_mode,
            is_active,
            db.now_iso(),
        ),
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


def login(client, username, password="secret123"):
    token = get_csrf(client, "/login")
    return client.post(
        "/login",
        data={"csrf_token": token, "username": username, "password": password},
    )


def post(client, path, csrf_path=None, **data):
    token = get_csrf(client, csrf_path or path)
    return client.post(path, data={"csrf_token": token, **data})