"""Права доступа к страницам: видимость и редактирование.

- ``admin`` видит и редактирует всё.
- ``user`` с ``access_mode``:
    - ``all``    — видны все страницы (строк в ``user_page_access`` нет);
    - ``except`` — видны все, кроме перечисленных;
    - ``only``   — видны только перечисленные.
- Редактирование: страница из ``user_page_edit`` И видимая → полное
  редактирование. Иначе read-only.
"""

from __future__ import annotations

import sqlite3

from .. import hosts


def _ids(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> set[int]:
    return {int(row[0]) for row in conn.execute(sql, params)}


def _all_page_ids(conn: sqlite3.Connection) -> set[int]:
    return _ids(conn, "SELECT id FROM pages")


def _access_rows(conn: sqlite3.Connection, user_id: int) -> set[int]:
    return _ids(
        conn,
        "SELECT page_id FROM user_page_access WHERE user_id=?",
        (user_id,),
    )


def visible_page_ids(
    conn: sqlite3.Connection, user: sqlite3.Row
) -> set[int] | None:
    """Множество видимых page_id или None, если видно всё (админ)."""
    if user["role"] == "admin":
        return None
    all_ids = _all_page_ids(conn)
    mode = user["access_mode"]
    if mode == "all":
        return all_ids
    granted = _access_rows(conn, int(user["id"]))
    if mode == "only":
        return granted & all_ids
    # except
    return all_ids - granted


def visible_pages(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    *,
    only_enabled: bool = False,
) -> list[sqlite3.Row]:
    """Отсортированные видимые страницы."""
    rows = hosts.list_pages(conn, only_enabled=only_enabled)
    if user["role"] == "admin":
        return rows
    allowed = visible_page_ids(conn, user)
    assert allowed is not None
    return [row for row in rows if int(row["id"]) in allowed]


def can_view(
    conn: sqlite3.Connection, user: sqlite3.Row, page_id: int
) -> bool:
    if user["role"] == "admin":
        return True
    allowed = visible_page_ids(conn, user)
    return allowed is not None and page_id in allowed


def edit_page_ids(
    conn: sqlite3.Connection, user: sqlite3.Row
) -> set[int] | None:
    """Страницы, доступные на редактирование (None — всё)."""
    if user["role"] == "admin":
        return None
    return _ids(
        conn,
        "SELECT page_id FROM user_page_edit WHERE user_id=?",
        (int(user["id"]),),
    )


def can_edit(
    conn: sqlite3.Connection, user: sqlite3.Row, page_id: int
) -> bool:
    if user["role"] == "admin":
        return True
    if not can_view(conn, user, page_id):
        return False
    editing = edit_page_ids(conn, user)
    return editing is not None and page_id in editing