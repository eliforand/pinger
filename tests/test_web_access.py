from __future__ import annotations

import pytest

from pinger import db, hosts
from pinger.web import access


@pytest.fixture()
def env(tmp_path):
    conn = db.init_db(path=tmp_path / "access.db")
    p1 = hosts.create_page(conn, "p1")
    p2 = hosts.create_page(conn, "p2")
    p3 = hosts.create_page(conn, "p3")

    def add_user(username, role, mode="all"):
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, access_mode,"
            " is_active, created_at) VALUES (?, 'x', ?, ?, 1, ?)",
            (username, role, mode, db.now_iso()),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM users WHERE id=?", (cur.lastrowid,)
        ).fetchone()

    def grant_access(user, *page_ids):
        conn.executemany(
            "INSERT OR IGNORE INTO user_page_access (user_id, page_id)"
            " VALUES (?, ?)",
            [(user["id"], pid) for pid in page_ids],
        )
        conn.commit()

    def grant_edit(user, *page_ids):
        conn.executemany(
            "INSERT OR IGNORE INTO user_page_edit (user_id, page_id)"
            " VALUES (?, ?)",
            [(user["id"], pid) for pid in page_ids],
        )
        conn.commit()

    yield {
        "conn": conn,
        "pages": [p1, p2, p3],
        "add_user": add_user,
        "grant_access": grant_access,
        "grant_edit": grant_edit,
    }
    conn.close()


def _visible(env, user):
    return {p["id"] for p in access.visible_pages(env["conn"], user)}


def test_admin_sees_and_edits_all(env):
    conn = env["conn"]
    admin = env["add_user"]("admin", "admin")
    assert access.visible_page_ids(conn, admin) is None
    assert _visible(env, admin) == set(env["pages"])
    for page_id in env["pages"]:
        assert access.can_view(conn, admin, page_id)
        assert access.can_edit(conn, admin, page_id)


def test_mode_all_visible_but_no_edit(env):
    conn = env["conn"]
    user = env["add_user"]("u", "user", "all")
    assert _visible(env, user) == set(env["pages"])
    assert not access.can_edit(conn, user, env["pages"][0])

    env["grant_edit"](user, env["pages"][0])
    assert access.can_edit(conn, user, env["pages"][0])
    assert not access.can_edit(conn, user, env["pages"][1])


def test_mode_except(env):
    conn = env["conn"]
    p1, p2, p3 = env["pages"]
    user = env["add_user"]("u", "user", "except")
    env["grant_access"](user, p2)
    assert _visible(env, user) == {p1, p3}
    assert not access.can_view(conn, user, p2)
    assert access.can_view(conn, user, p1)


def test_mode_only(env):
    conn = env["conn"]
    p1, p2, p3 = env["pages"]
    user = env["add_user"]("u", "user", "only")
    env["grant_access"](user, p1, p3)
    assert _visible(env, user) == {p1, p3}
    assert not access.can_view(conn, user, p2)


def test_edit_requires_visible(env):
    conn = env["conn"]
    p1, p2, p3 = env["pages"]
    user = env["add_user"]("u", "user", "except")
    env["grant_access"](user, p1)  # p1 скрыта
    env["grant_edit"](user, p1)
    assert not access.can_edit(conn, user, p1)


def test_edit_page_ids_for_admin_is_none(env):
    admin = env["add_user"]("admin", "admin")
    assert access.edit_page_ids(env["conn"], admin) is None


def test_only_enabled_filter(env):
    conn = env["conn"]
    p1, p2, p3 = env["pages"]
    hosts.update_page(conn, p2, enabled=False)
    admin = env["add_user"]("admin", "admin")
    visible = {p["id"] for p in access.visible_pages(conn, admin, only_enabled=True)}
    assert visible == {p1, p3}