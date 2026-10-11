"""Страница настроек сервиса (/settings, только админ)."""

from __future__ import annotations

import pytest

from pinger import db, settings
from web_utils import add_user, get_csrf, login, make_client


@pytest.fixture()
def admin_client(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    assert login(client, "admin").status_code == 303
    return client, app


def test_settings_page_shows_current_values(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    settings.update(conn, {"round_interval_s": 42})
    conn.close()

    response = client.get("/settings")
    assert response.status_code == 200
    assert 'name="round_interval_s"' in response.text
    assert 'value="42"' in response.text
    assert 'name="timeout_ms"' in response.text


def test_settings_update(admin_client):
    client, app = admin_client
    token = get_csrf(client, "/settings")
    response = client.post(
        "/settings",
        data={
            "csrf_token": token,
            "timeout_ms": "500",
            "packets": "5",
            "interval_ms": "100",
            "round_interval_s": "20",
            "ui_refresh_s": "10",
            "max_targets": "128",
        },
    )
    assert response.status_code == 200
    assert "Настройки сохранены" in response.text

    conn = db.connect(app.state.db_path)
    loaded = settings.load(conn)
    conn.close()
    assert loaded.timeout_ms == 500
    assert loaded.packets == 5
    assert loaded.round_interval_s == 20
    assert loaded.max_targets == 128


def test_settings_invalid_value_shows_error(admin_client):
    client, app = admin_client
    token = get_csrf(client, "/settings")
    response = client.post(
        "/settings",
        data={
            "csrf_token": token,
            "timeout_ms": "500",
            "packets": "0",  # меньше минимума
            "interval_ms": "100",
            "round_interval_s": "20",
            "ui_refresh_s": "10",
            "max_targets": "128",
        },
    )
    assert response.status_code == 200
    assert "packets" in response.text

    conn = db.connect(app.state.db_path)
    assert settings.load(conn).packets == 3  # не изменилось
    conn.close()


def test_settings_forbidden_for_user(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    add_user(app.state.db_path, "bob", role="user", access_mode="all")
    login(client, "bob")

    assert client.get("/settings").status_code == 403
    token = get_csrf(client, "/")
    assert (
        client.post(
            "/settings", data={"csrf_token": token, "packets": "9"}
        ).status_code
        == 403
    )


def test_settings_link_in_navbar_for_admin_only(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    add_user(app.state.db_path, "bob", role="user", access_mode="all")

    login(client, "bob")
    assert 'href="/settings"' not in client.get("/").text

    token = get_csrf(client, "/")
    client.post("/logout", data={"csrf_token": token})
    login(client, "admin")
    assert 'href="/settings"' in client.get("/").text
