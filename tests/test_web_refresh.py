"""Автообновление статусов: JSON-эндпоинты + data-атрибуты для status.js."""

from __future__ import annotations

import pytest

from pinger import db, hosts, settings
from web_utils import add_user, login, make_client


@pytest.fixture()
def admin_client(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    assert login(client, "admin").status_code == 303
    return client, app


def test_index_has_json_polling_with_default_refresh(admin_client):
    client, app = admin_client
    response = client.get("/")
    assert 'data-status-url="/index.json"' in response.text
    assert 'data-refresh-s="5"' in response.text
    # никакого HTMX-поллинга HTML на главном экране
    assert "hx-trigger" not in response.text


def test_refresh_interval_from_settings(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    settings.update(conn, {"ui_refresh_s": 7})
    conn.close()
    response = client.get("/")
    assert 'data-refresh-s="7"' in response.text


def test_page_has_json_polling(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()
    response = client.get(f"/pages/{page_id}")
    assert f'data-status-url="/pages/{page_id}/status.json"' in response.text
    assert 'data-refresh-s="5"' in response.text
    assert "hx-trigger" not in response.text


def test_htmx_page_still_returns_body_partial(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    hosts.create_target(conn, page_id, "row")
    conn.close()
    response = client.get(
        f"/pages/{page_id}", headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert response.text.strip().startswith('<div id="page-body"')
    assert "row" in response.text
    assert "<html" not in response.text


# --- JSON-эндпоинты --------------------------------------------------------


def _seed(conn):
    page_id = hosts.create_page(conn, "p")
    t1 = hosts.create_target(conn, page_id, "row1")
    a1 = hosts.create_address(conn, page_id, t1, "10.0.0.1")
    a2 = hosts.create_address(conn, page_id, t1, "10.0.0.2")
    conn.execute(
        "INSERT INTO host_status (address_id, ts, alive, state_since,"
        " consecutive_ok, consecutive_fail, checks_total, checks_failed)"
        " VALUES (?, ?, 1, ?, 3, 0, 3, 0)",
        (a1, db.now_iso(), db.now_iso()),
    )
    conn.execute(
        "INSERT INTO host_status (address_id, ts, alive, state_since,"
        " consecutive_ok, consecutive_fail, checks_total, checks_failed)"
        " VALUES (?, ?, 0, ?, 0, 2, 2, 2)",
        (a2, db.now_iso(), db.now_iso()),
    )
    conn.commit()
    return page_id, t1, a1, a2


def test_page_status_json(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id, t1, a1, a2 = _seed(conn)
    conn.close()

    response = client.get(f"/pages/{page_id}/status.json")
    assert response.status_code == 200
    data = response.json()
    assert data["stats"] == {"total": 2, "up": 1, "down": 1, "no_data": 0}
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["target_id"] == t1
    cells = {c["address_id"]: c for c in row["cells"]}
    assert cells[a1]["state"] == "up"
    assert cells[a2]["state"] == "down"
    assert cells[a1]["enabled"] is True


def test_page_status_json_no_data(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    t1 = hosts.create_target(conn, page_id, "row")
    hosts.create_address(conn, page_id, t1, "10.0.0.9")
    conn.close()

    data = client.get(f"/pages/{page_id}/status.json").json()
    assert data["stats"]["no_data"] == 1
    assert data["rows"][0]["cells"][0]["state"] is None
    assert data["rows"][0]["cells"][0]["uptime"] is None


def test_index_json(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    _seed(conn)
    conn.close()

    response = client.get("/index.json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["pages"]) == 1
    card = data["pages"][0]
    assert card["total"] == 2 and card["up"] == 1 and card["down"] == 1
    assert card["enabled"] is True


def test_page_status_json_404(admin_client):
    client, _ = admin_client
    assert client.get("/pages/9999/status.json").status_code == 404


def test_status_json_requires_login(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()

    assert client.get("/index.json").status_code == 303
    assert client.get(f"/pages/{page_id}/status.json").status_code == 303


def test_status_json_respects_visibility(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    visible = hosts.create_page(conn, "vis")
    hidden = hosts.create_page(conn, "hid")
    bob = add_user(app.state.db_path, "bob", role="user", access_mode="only")
    conn.execute(
        "INSERT INTO user_page_access (user_id, page_id) VALUES (?, ?)",
        (bob, visible),
    )
    conn.commit()
    conn.close()

    login(client, "bob")
    assert client.get(f"/pages/{hidden}/status.json").status_code == 403
    assert client.get(f"/pages/{visible}/status.json").status_code == 200
    ids = [p["id"] for p in client.get("/index.json").json()["pages"]]
    assert visible in ids and hidden not in ids


def test_status_js_is_served(admin_client):
    client, _ = admin_client
    response = client.get("/static/status.js")
    assert response.status_code == 200
    assert "data-status-url" in response.text
