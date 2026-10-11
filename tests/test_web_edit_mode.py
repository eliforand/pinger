"""Два режима страницы: просмотр (/pages/{id}) и редактирование (/pages/{id}/edit)."""

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


def _seed_page(app):
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id, "row")
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    conn.close()
    return page_id, target_id, address_id


def test_view_mode_is_readonly(admin_client):
    client, app = admin_client
    page_id, _, _ = _seed_page(app)
    body = client.get(f"/pages/{page_id}").text
    assert "10.0.0.1" in body
    assert f"/pages/{page_id}/edit" in body  # ссылка в режим редактирования
    # в просмотре нет форм изменения состава страницы
    assert f'action="/pages/{page_id}/targets"' not in body
    assert "/delete" not in body


def test_edit_mode_shows_forms(admin_client):
    client, app = admin_client
    page_id, target_id, address_id = _seed_page(app)
    response = client.get(f"/pages/{page_id}/edit")
    assert response.status_code == 200
    body = response.text
    assert f'action="/pages/{page_id}/targets"' in body
    assert f'action="/addresses/{address_id}/delete"' in body
    assert f'action="/targets/{target_id}/rename"' in body


def test_edit_forbidden_without_edit_right(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()
    add_user(app.state.db_path, "bob", role="user", access_mode="all")
    login(client, "bob")

    assert client.get(f"/pages/{page_id}").status_code == 200
    assert client.get(f"/pages/{page_id}/edit").status_code == 403


def test_edit_allowed_with_edit_right(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    bob = add_user(app.state.db_path, "bob", role="user", access_mode="all")
    conn.execute(
        "INSERT INTO user_page_edit (user_id, page_id) VALUES (?, ?)",
        (bob, page_id),
    )
    conn.commit()
    conn.close()
    login(client, "bob")

    response = client.get(f"/pages/{page_id}/edit")
    assert response.status_code == 200
    # кнопка «Редактировать» — внутри экрана просмотра страницы
    view = client.get(f"/pages/{page_id}").text
    assert f"/pages/{page_id}/edit" in view


def test_editor_link_hidden_for_readonly_user(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    conn.close()
    add_user(app.state.db_path, "bob", role="user", access_mode="all")
    login(client, "bob")

    assert f"/pages/{page_id}/edit" not in client.get(f"/pages/{page_id}").text


def test_mutation_from_edit_mode_returns_edit_fragment(admin_client):
    client, app = admin_client
    page_id, _, _ = _seed_page(app)
    token = get_csrf(client, f"/pages/{page_id}/edit")
    response = client.post(
        f"/pages/{page_id}/targets",
        data={"csrf_token": token, "name": "second"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.text.strip().startswith('<div id="page-body"')
    assert "second" in response.text
    # диалог добавления строки живёт в полной странице (вне фрагмента)
    assert 'id="dialog-new-row"' in client.get(f"/pages/{page_id}/edit").text


def test_mutation_without_htmx_redirects_to_edit(admin_client):
    client, app = admin_client
    page_id, _, _ = _seed_page(app)
    token = get_csrf(client, f"/pages/{page_id}/edit")
    response = client.post(
        f"/pages/{page_id}/targets",
        data={"csrf_token": token, "name": "third"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/pages/{page_id}/edit"


def test_rename_target(admin_client):
    client, app = admin_client
    page_id, target_id, _ = _seed_page(app)
    token = get_csrf(client, f"/pages/{page_id}/edit")
    response = client.post(
        f"/targets/{target_id}/rename",
        data={"csrf_token": token, "name": "renamed"},
    )
    assert response.status_code == 303
    conn = db.connect(app.state.db_path)
    assert hosts.get_target(conn, target_id)["name"] == "renamed"
    conn.close()


def test_admin_updates_page_settings(admin_client):
    client, app = admin_client
    page_id, _, _ = _seed_page(app)
    token = get_csrf(client, "/")
    response = client.post(
        f"/pages/{page_id}/update",
        data={"csrf_token": token, "name": "newname", "description": "d"},
    )
    assert response.status_code == 303
    conn = db.connect(app.state.db_path)
    page = hosts.get_page(conn, page_id)
    assert page["name"] == "newname"
    assert page["description"] == "d"
    assert page["enabled"] == 0  # чекбокс не прислан -> выключена
    conn.close()


def test_admin_deletes_page(admin_client):
    client, app = admin_client
    page_id, _, _ = _seed_page(app)
    token = get_csrf(client, "/")
    response = client.post(
        f"/pages/{page_id}/delete", data={"csrf_token": token}
    )
    assert response.status_code == 303
    conn = db.connect(app.state.db_path)
    assert hosts.get_page(conn, page_id) is None
    conn.close()


def test_user_cannot_update_or_delete_page(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    conn = db.connect(app.state.db_path)
    page_id = hosts.create_page(conn, "p")
    bob = add_user(app.state.db_path, "bob", role="user", access_mode="all")
    conn.execute(
        "INSERT INTO user_page_edit (user_id, page_id) VALUES (?, ?)",
        (bob, page_id),
    )
    conn.commit()
    conn.close()
    login(client, "bob")

    token = get_csrf(client, f"/pages/{page_id}/edit")
    assert (
        client.post(
            f"/pages/{page_id}/update",
            data={"csrf_token": token, "name": "x"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/pages/{page_id}/delete", data={"csrf_token": token}
        ).status_code
        == 403
    )


def test_main_edit_mode_admin_only(tmp_path):
    client, app = make_client(tmp_path)
    add_user(app.state.db_path, "admin", role="admin")
    add_user(app.state.db_path, "bob", role="user", access_mode="all")

    login(client, "bob")
    assert client.get("/edit").status_code == 403
    token = get_csrf(client, "/")
    assert " /edit" not in client.get("/").text  # нет кнопки редактирования

    client.post("/logout", data={"csrf_token": token})
    login(client, "admin")
    body = client.get("/edit").text
    assert client.get("/edit").status_code == 200
    assert 'id="dialog-new-page"' in body  # добавление через модальное окно


def test_index_cards_have_no_buttons(admin_client):
    client, app = admin_client
    page_id, _, _ = _seed_page(app)
    body = client.get("/").text
    assert f'href="/pages/{page_id}"' in body  # карточка кликабельна
    assert "<button" not in body.split('<div id="page-list"')[1]


def test_create_page_dialog_and_update_via_edit_index(admin_client):
    client, app = admin_client
    token = get_csrf(client, "/edit")
    response = client.post(
        "/pages", data={"csrf_token": token, "name": "dialog page"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/edit"
    assert "dialog page" in client.get("/edit").text

    conn = db.connect(app.state.db_path)
    page_id = hosts.list_pages(conn)[0]["id"]
    conn.close()
    token = get_csrf(client, "/edit")
    response = client.post(
        f"/pages/{page_id}/update",
        data={"csrf_token": token, "name": "renamed", "enabled": "on"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/edit"
    conn = db.connect(app.state.db_path)
    page = hosts.get_page(conn, page_id)
    assert page["name"] == "renamed" and page["enabled"] == 1
    conn.close()


def test_static_css_is_served(admin_client):
    client, _ = admin_client
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert ".chip" in response.text
    assert client.get("/static/bootstrap.min.css").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200
    # никаких внешних CDN в разметке
    assert "unpkg.com" not in client.get("/").text


def test_view_shows_uptime_percent(admin_client):
    client, app = admin_client
    page_id, _, address_id = _seed_page(app)
    from datetime import datetime, timedelta

    now = datetime.now()
    conn = db.connect(app.state.db_path)
    conn.execute(
        "INSERT INTO host_events (address_id, state, started_at, ended_at, probes)"
        " VALUES (?, 'up', ?, ?, 3)",
        (
            address_id,
            (now - timedelta(hours=2)).isoformat(timespec="seconds"),
            (now - timedelta(hours=1)).isoformat(timespec="seconds"),
        ),
    )
    conn.execute(
        "INSERT INTO host_status (address_id, ts, alive, state_since,"
        " consecutive_ok, consecutive_fail, checks_total, checks_failed)"
        " VALUES (?, ?, 1, ?, 2, 0, 2, 0)",
        (
            address_id,
            (now - timedelta(hours=1)).isoformat(timespec="seconds"),
            (now - timedelta(hours=1)).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()
    body = client.get(f"/pages/{page_id}").text
    assert 'class="uptime"' in body
