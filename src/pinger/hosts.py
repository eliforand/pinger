"""CRUD для pages / targets / addresses — общее для сервиса и веба."""

from __future__ import annotations

import sqlite3

from .db import now_iso


# --- pages ---------------------------------------------------------------


def list_pages(
    conn: sqlite3.Connection, *, only_enabled: bool = False
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM pages"
    if only_enabled:
        sql += " WHERE enabled=1"
    sql += " ORDER BY position, id"
    return list(conn.execute(sql))


def get_page(conn: sqlite3.Connection, page_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()


def create_page(
    conn: sqlite3.Connection,
    name: str,
    description: str | None = None,
    *,
    position: int | None = None,
    enabled: bool = True,
    now: str | None = None,
) -> int:
    if position is None:
        position = _next_position(conn, "pages", None, ())
    cur = conn.execute(
        "INSERT INTO pages (name, description, position, enabled, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, description, position, int(enabled), now or now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_page(
    conn: sqlite3.Connection,
    page_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    position: int | None = None,
    enabled: bool | None = None,
) -> None:
    sets, params = [], []
    if name is not None:
        sets.append("name=?")
        params.append(name)
    if description is not None:
        sets.append("description=?")
        params.append(description)
    if position is not None:
        sets.append("position=?")
        params.append(position)
    if enabled is not None:
        sets.append("enabled=?")
        params.append(int(enabled))
    if not sets:
        return
    params.append(page_id)
    conn.execute(f"UPDATE pages SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_page(conn: sqlite3.Connection, page_id: int) -> None:
    conn.execute("DELETE FROM pages WHERE id=?", (page_id,))
    conn.commit()


# --- targets -------------------------------------------------------------


def list_targets(conn: sqlite3.Connection, page_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM targets WHERE page_id=? ORDER BY position, id",
            (page_id,),
        )
    )


def get_target(conn: sqlite3.Connection, target_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM targets WHERE id=?", (target_id,)
    ).fetchone()


def create_target(
    conn: sqlite3.Connection,
    page_id: int,
    name: str | None = None,
    *,
    position: int | None = None,
    now: str | None = None,
) -> int:
    if position is None:
        position = _next_position(
            conn, "targets", "page_id=?", (page_id,)
        )
    cur = conn.execute(
        "INSERT INTO targets (page_id, name, position, created_at)"
        " VALUES (?, ?, ?, ?)",
        (page_id, name, position, now or now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_target(
    conn: sqlite3.Connection,
    target_id: int,
    *,
    name: str | None = None,
    position: int | None = None,
) -> None:
    sets, params = [], []
    if name is not None:
        sets.append("name=?")
        params.append(name)
    if position is not None:
        sets.append("position=?")
        params.append(position)
    if not sets:
        return
    params.append(target_id)
    conn.execute(f"UPDATE targets SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_target(conn: sqlite3.Connection, target_id: int) -> None:
    conn.execute("DELETE FROM targets WHERE id=?", (target_id,))
    conn.commit()


# --- addresses -----------------------------------------------------------


def list_addresses(conn: sqlite3.Connection, page_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM addresses WHERE page_id=? ORDER BY position, id",
            (page_id,),
        )
    )


def get_address(conn: sqlite3.Connection, address_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM addresses WHERE id=?", (address_id,)
    ).fetchone()


def create_address(
    conn: sqlite3.Connection,
    page_id: int,
    target_id: int,
    address: str,
    *,
    enabled: bool = True,
    position: int | None = None,
    now: str | None = None,
) -> int:
    if position is None:
        position = _next_position(
            conn, "addresses", "page_id=?", (page_id,)
        )
    cur = conn.execute(
        "INSERT INTO addresses"
        " (page_id, target_id, address, enabled, position, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            page_id,
            target_id,
            address,
            int(enabled),
            position,
            now or now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_address(
    conn: sqlite3.Connection,
    address_id: int,
    *,
    address: str | None = None,
    target_id: int | None = None,
    enabled: bool | None = None,
    position: int | None = None,
) -> None:
    sets, params = [], []
    if address is not None:
        sets.append("address=?")
        params.append(address)
    if target_id is not None:
        sets.append("target_id=?")
        params.append(target_id)
    if enabled is not None:
        sets.append("enabled=?")
        params.append(int(enabled))
    if position is not None:
        sets.append("position=?")
        params.append(position)
    if not sets:
        return
    params.append(address_id)
    conn.execute(f"UPDATE addresses SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_address(conn: sqlite3.Connection, address_id: int) -> None:
    conn.execute("DELETE FROM addresses WHERE id=?", (address_id,))
    conn.commit()


def find_address_in_page(
    conn: sqlite3.Connection, page_id: int, address: str
) -> sqlite3.Row | None:
    """Найти адрес на странице (для сообщения об уникальности IP)."""
    return conn.execute(
        "SELECT * FROM addresses WHERE page_id=? AND address=?",
        (page_id, address),
    ).fetchone()


def enabled_probe_targets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Включённые адреса на включённых страницах — цели раунда пинга."""
    return list(
        conn.execute(
            "SELECT a.id AS address_id, a.address AS address"
            " FROM addresses a JOIN pages p ON p.id = a.page_id"
            " WHERE a.enabled=1 AND p.enabled=1"
            " ORDER BY a.id"
        )
    )


def _next_position(
    conn: sqlite3.Connection,
    table: str,
    where: str | None,
    params: tuple,
) -> int:
    sql = f"SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql, params).fetchone()["pos"])