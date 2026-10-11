from __future__ import annotations

import pytest

from pinger import db, hosts
from web_utils import add_user, get_csrf, login, make_client


@pytest.fixture()
def admin_client(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    response = login(client, "admin")
    assert response.status_code == 303
    return client, app


def test_main_lists_visible_pages(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    p1 = hosts.create_page(conn, "alpha")
    hosts.create_page(conn, "beta")
    conn.close()

    response = client.get("/")
    assert response.status_code == 200
    assert "alpha" in response.text and "beta" in response.text
    assert f"/pages/{p1}" in response.text


def test_create_page(admin_client):
    client, app = admin_client
    token = get_csrf(client, "/")
    response = client.post(
        "/pages", data={"csrf_token": token, "name": "new page"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/edit"
    assert client.get("/").text.count("new page") >= 1


def test_create_page_duplicate_shows_error(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    hosts.create_page(conn, "dup")
    conn.close()
    token = get_csrf(client, "/")
    response = client.post(
        "/pages", data={"csrf_token": token, "name": "dup"}
    )
    assert response.status_code == 200
    assert "уже существует" in response.text


def test_non_admin_cannot_create_page(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    add_user(app.state.db_path, "bob", role="user")
    login(client, "bob")
    token = get_csrf(client, "/")
    response = client.post(
        "/pages", data={"csrf_token": token, "name": "nope"}
    )
    assert response.status_code == 403


def test_page_hidden_from_user(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    p1 = hosts.create_page(conn, "vis_page")
    p2 = hosts.create_page(conn, "hid_page")
    bob = add_user(app.state.db_path, "bob", role="user", access_mode="only")
    conn.execute(
        "INSERT INTO user_page_access (user_id, page_id) VALUES (?, ?)",
        (bob, p1),
    )
    conn.commit()
    conn.close()

    login(client, "bob")
    home = client.get("/")
    assert "vis_page" in home.text
    assert "hid_page" not in home.text
    assert client.get(f"/pages/{p1}").status_code == 200
    assert client.get(f"/pages/{p2}").status_code == 403


def test_add_row_and_address_with_colors(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()

    token = get_csrf(client, f"/pages/{page_id}")
    response = client.post(
        f"/pages/{page_id}/targets",
        data={"csrf_token": token, "name": "row1"},
    )
    assert response.status_code == 303

    conn = db.connect(app.state.db_path)
    target_id = hosts.list_targets(conn, page_id)[0]["id"]
    conn.close()

    token = get_csrf(client, f"/pages/{page_id}")
    response = client.post(
        f"/pages/{page_id}/addresses",
        data={
            "csrf_token": token,
            "target_id": str(target_id),
            "address": "10.0.0.1",
        },
    )
    assert response.status_code == 303

    conn = db.connect(app.state.db_path)
    address_id = hosts.list_addresses(conn, page_id)[0]["id"]
    conn.execute(
        "INSERT INTO host_status (address_id, ts, alive, state_since)"
        " VALUES (?, ?, 1, ?)",
        (address_id, db.now_iso(), db.now_iso()),
    )
    conn.commit()
    conn.close()

    body = client.get(f"/pages/{page_id}").text
    assert "row1" in body
    assert "10.0.0.1" in body
    assert "ip up" in body


def test_no_data_address_has_no_color(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    hosts.create_address(conn, page_id, target_id, "10.0.0.7")
    conn.close()
    body = client.get(f"/pages/{page_id}").text
    assert "ip unknown" in body


def test_duplicate_ip_reports_owner_row(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    t1 = hosts.create_target(conn, page_id, "first")
    t2 = hosts.create_target(conn, page_id, "second")
    hosts.create_address(conn, page_id, t1, "10.0.0.5")
    conn.close()

    token = get_csrf(client, f"/pages/{page_id}")
    response = client.post(
        f"/pages/{page_id}/addresses",
        data={
            "csrf_token": token,
            "target_id": str(t2),
            "address": "10.0.0.5",
        },
    )
    assert response.status_code == 200
    assert "уже есть на этой странице" in response.text
    assert "first" in response.text


def test_same_ip_allowed_on_different_pages(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    p1 = hosts.create_page(conn, "p1")
    p2 = hosts.create_page(conn, "p2")
    t2 = hosts.create_target(conn, p2, "row2")
    hosts.create_address(conn, p1, hosts.create_target(conn, p1, "row1"), "10.0.0.5")
    conn.close()

    token = get_csrf(client, f"/pages/{p2}")
    response = client.post(
        f"/pages/{p2}/addresses",
        data={
            "csrf_token": token,
            "target_id": str(t2),
            "address": "10.0.0.5",
        },
    )
    assert response.status_code == 303


def test_delete_address_and_target(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.9")
    conn.close()

    token = get_csrf(client, f"/pages/{page_id}")
    response = client.post(
        f"/addresses/{address_id}/delete", data={"csrf_token": token}
    )
    assert response.status_code == 303
    conn = db.connect(app.state.db_path)
    assert hosts.list_addresses(conn, page_id) == []
    conn.close()

    token = get_csrf(client, f"/pages/{page_id}")
    response = client.post(
        f"/targets/{target_id}/delete", data={"csrf_token": token}
    )
    assert response.status_code == 303
    conn = db.connect(app.state.db_path)
    assert hosts.list_targets(conn, page_id) == []
    conn.close()


def test_toggle_address(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    conn.close()

    token = get_csrf(client, f"/pages/{page_id}")
    client.post(f"/addresses/{address_id}/toggle", data={"csrf_token": token})
    conn = db.connect(app.state.db_path)
    assert hosts.get_address(conn, address_id)["enabled"] == 0
    conn.close()


def test_editor_can_edit_granted_page_only(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    p1 = hosts.create_page(conn, "editable")
    p2 = hosts.create_page(conn, "readonly")
    bob = add_user(app.state.db_path, "bob", role="user", access_mode="all")
    conn.execute(
        "INSERT INTO user_page_edit (user_id, page_id) VALUES (?, ?)",
        (bob, p1),
    )
    conn.commit()
    conn.close()

    login(client, "bob")
    token = get_csrf(client, f"/pages/{p1}")
    assert (
        client.post(
            f"/pages/{p1}/targets",
            data={"csrf_token": token, "name": "ok"},
        ).status_code
        == 303
    )

    token = get_csrf(client, f"/pages/{p2}")
    assert (
        client.post(
            f"/pages/{p2}/targets",
            data={"csrf_token": token, "name": "no"},
        ).status_code
        == 403
    )


def test_readonly_user_cannot_mutate(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    conn.close()

    # выходим из админа и входим обычным пользователем без права редактирования
    token = get_csrf(client, "/")
    client.post("/logout", data={"csrf_token": token})
    add_user(app.state.db_path, "bob", role="user", access_mode="all")
    login(client, "bob")

    token = get_csrf(client, f"/pages/{page_id}")
    for path, data in (
        (f"/pages/{page_id}/targets", {"name": "x"}),
        (
            f"/pages/{page_id}/addresses",
            {"target_id": str(target_id), "address": "10.0.0.1"},
        ),
        (f"/targets/{target_id}/delete", {}),
    ):
        assert (
            client.post(path, data={"csrf_token": token, **data}).status_code
            == 403
        )


def test_mutation_requires_csrf(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()
    response = client.post(f"/pages/{page_id}/targets", data={"name": "x"})
    assert response.status_code == 400


def test_htmx_add_row_returns_fragment(admin_client):
    client, app = admin_client
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()
    token = get_csrf(client, f"/pages/{page_id}")
    response = client.post(
        f"/pages/{page_id}/targets",
        data={"csrf_token": token, "name": "hxrow"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.text.strip().startswith('<div id="page-body"')
    assert "hxrow" in response.text


def test_page_404(admin_client):
    client, app = admin_client
    assert client.get("/pages/9999").status_code == 404