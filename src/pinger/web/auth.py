"""Аутентификация, зависимость соединения с БД и проверка прав."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Depends, Request

from .. import db


class AuthRequired(Exception):
    """Нужен вход — редирект на /login."""


class Forbidden(Exception):
    """Недостаточно прав — 403."""


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """Соединение с БД на каждый запрос."""
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    request: Request, conn: sqlite3.Connection
) -> sqlite3.Row | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    row = conn.execute(
        "SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)
    ).fetchone()
    if row is None:
        request.session.pop("user_id", None)
    return row


def require_user(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> sqlite3.Row:
    user = get_current_user(request, conn)
    if user is None:
        raise AuthRequired()
    return user


def require_admin(
    user: sqlite3.Row = Depends(require_user),
) -> sqlite3.Row:
    if user["role"] != "admin":
        raise Forbidden()
    return user


def has_admin(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM users WHERE role='admin' AND is_active=1 LIMIT 1"
    ).fetchone()
    return row is not None