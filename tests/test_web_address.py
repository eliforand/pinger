from __future__ import annotations

import pytest

from pinger import db, hosts
from web_utils import add_user, login, make_client


@pytest.fixture()
def admin_client(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    assert login(client, "admin").status_code == 303
    return client, app


def _seed(conn, address_id):
    conn.execute(
        "INSERT INTO host_events (address_id, state, started_at, ended_at, probes)"
        " VALUES (?, 'up', '2024-01-01T00:00:00', '2024-01-01T06:00:00', 3)",
        (address_id,),
    )
    conn.execute(
        "INSERT INTO host_events (address_id, state, started_at, ended_at, probes)"
        " VALUES (?, 'down', '2024-01-01T06:00:00', '2024-01-01T09:00:00', 3)",
        (address_id,),
    )
    conn.execute(
        "INSERT INTO host_status (address_id, ts, alive, state_since,"
        " consecutive_ok, consecutive_fail, checks_total, checks_failed)"
        " VALUES (?, '2024-01-01T09:00:00', 1, '2024-01-01T09:00:00', 2, 0, 2, 0)",
        (address_id,),
    )
    conn.commit()


def test_address_page_shows_uptime_and_ranges(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    _seed(conn, address_id)
    conn.close()

    response = client.get(f"/addresses/{address_id}")
    assert response.status_code == 200
    assert "10.0.0.1" in response.text
    assert "Uptime" in response.text
    assert "1 час" in response.text and "всё" in response.text
    assert "доступен" in response.text


def test_address_page_range_param(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    _seed(conn, address_id)
    conn.close()

    response = client.get(f"/addresses/{address_id}?range=1h")
    assert response.status_code == 200

    bad = client.get(f"/addresses/{address_id}?range=nonsense")
    assert bad.status_code == 200


def test_address_no_data(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    conn.close()
    response = client.get(f"/addresses/{address_id}")
    assert response.status_code == 200
    assert "данных ещё нет" in response.text


def test_address_404(admin_client):
    client, app = admin_client
    assert client.get("/addresses/424242").status_code == 404


def test_address_forbidden_without_page_access(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "private")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    add_user(app.state.db_path, "bob", role="user", access_mode="only")
    conn.commit()
    conn.close()

    login(client, "bob")
    assert client.get(f"/addresses/{address_id}").status_code == 403