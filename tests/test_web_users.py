from __future__ import annotations

import pytest

from pinger import db, hosts
from web_utils import add_user, get_csrf, login, make_client


@pytest.fixture()
def admin_client(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    assert login(client, "admin").status_code == 303
    return client, app


def test_users_page_requires_admin(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    add_user(app.state.db_path, "bob", role="user")
    login(client, "bob")
    assert client.get("/users").status_code == 403


def test_users_page_lists_users(admin_client):
    client, app = admin_client
    add_user(app.state.db_path, "bob", role="user")
    response = client.get("/users")
    assert response.status_code == 200
    assert "admin" in response.text and "bob" in response.text


def test_create_user_and_login(admin_client):
    client, app = admin_client
    token = get_csrf(client, "/users")
    response = client.post(
        "/users",
        data={
            "csrf_token": token,
            "username": "carol",
            "password": "password1",
            "role": "user",
            "access_mode": "all",
        },
    )
    assert response.status_code == 303

    # логин новым пользователем в отдельном клиенте
    client2, _ = make_client(app.state.db_path.parent)
    client2.get("/login")
    token = get_csrf(client2, "/login")
    resp = client2.post(
        "/login",
        data={
            "csrf_token": token,
            "username": "carol",
            "password": "password1",
        },
    )
    assert resp.status_code == 303


def test_create_user_short_password(admin_client):
    client, app = admin_client
    token = get_csrf(client, "/users")
    response = client.post(
        "/users",
        data={
            "csrf_token": token,
            "username": "carol",
            "password": "short",
            "role": "user",
            "access_mode": "all",
        },
    )
    assert response.status_code == 200
    assert "не короче 8" in response.text


def test_create_user_duplicate(admin_client):
    client, app = admin_client
    add_user(app.state.db_path, "carol", role="user")
    token = get_csrf(client, "/users")
    response = client.post(
        "/users",
        data={
            "csrf_token": token,
            "username": "carol",
            "password": "password1",
            "role": "user",
            "access_mode": "all",
        },
    )
    assert response.status_code == 200
    assert "уже существует" in response.text


def test_update_user_permissions(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    p1 = hosts.create_page(conn, "p1")
    p2 = hosts.create_page(conn, "p2")
    conn.close()
    uid = add_user(app.state.db_path, "carol", role="user", access_mode="all")

    token = get_csrf(client, "/users")
    response = client.post(
        f"/users/{uid}/update",
        data={
            "csrf_token": token,
            "role": "user",
            "access_mode": "only",
            "is_active": "on",
            "access_page": [str(p1)],
            "edit_page": [str(p1)],
        },
    )
    assert response.status_code == 303

    conn = db.connect(app.state.db_path)
    access = {
        row["page_id"]
        for row in conn.execute(
            "SELECT page_id FROM user_page_access WHERE user_id=?", (uid,)
        )
    }
    edit = {
        row["page_id"]
        for row in conn.execute(
            "SELECT page_id FROM user_page_edit WHERE user_id=?", (uid,)
        )
    }
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    assert access == {p1}
    assert edit == {p1}
    assert user["access_mode"] == "only"
    assert p2 not in access


def test_cannot_remove_last_admin(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    admin_id = conn.execute(
        "SELECT id FROM users WHERE username='admin'"
    ).fetchone()["id"]
    conn.close()

    token = get_csrf(client, "/users")
    response = client.post(
        f"/users/{admin_id}/update",
        data={"csrf_token": token, "role": "user", "access_mode": "all"},
    )
    assert response.status_code == 200
    assert "последнего активного администратора" in response.text


def test_admin_reset_password(admin_client):
    client, app = admin_client
    uid = add_user(app.state.db_path, "carol", password="oldpass123", role="user")

    token = get_csrf(client, "/users")
    response = client.post(
        f"/users/{uid}/password",
        data={"csrf_token": token, "password": "newpass123"},
    )
    assert response.status_code == 303

    client2, _ = make_client(app.state.db_path.parent)
    login(client2, "carol", "newpass123")
    assert client2.get("/").status_code == 200


def test_profile_change_password(admin_client):
    client, app = admin_client

    token = get_csrf(client, "/profile")
    wrong = client.post(
        "/profile",
        data={
            "csrf_token": token,
            "current_password": "wrong",
            "new_password": "newpass123",
        },
    )
    assert wrong.status_code == 200
    assert "Неверный текущий пароль" in wrong.text

    token = get_csrf(client, "/profile")
    ok = client.post(
        "/profile",
        data={
            "csrf_token": token,
            "current_password": "secret123",
            "new_password": "newpass123",
        },
    )
    assert ok.status_code == 200
    assert "Пароль обновлён" in ok.text

    client2, _ = make_client(app.state.db_path.parent)
    login(client2, "admin", "newpass123")
    assert client2.get("/").status_code == 200


def test_profile_requires_login(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    response = client.get("/profile")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"