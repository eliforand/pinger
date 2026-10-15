"""Управление пользователями (/users) и профиль (/profile)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import db, hosts
from .auth import get_conn, require_admin, require_user
from .security import (
    check_csrf,
    get_csrf_token,
    hash_password,
    validate_password,
    verify_password,
)
from .templating import render

router = APIRouter()

VALID_ROLES = ("admin", "user")
VALID_MODES = ("all", "except", "only")


def _active_admins(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
    ).fetchone()[0]


def _user_access_rows(conn: sqlite3.Connection) -> dict[int, set[int]]:
    rows = conn.execute("SELECT user_id, page_id FROM user_page_access")
    result: dict[int, set[int]] = {}
    for row in rows:
        result.setdefault(int(row["user_id"]), set()).add(int(row["page_id"]))
    return result


def _user_edit_rows(conn: sqlite3.Connection) -> dict[int, set[int]]:
    rows = conn.execute("SELECT user_id, page_id FROM user_page_edit")
    result: dict[int, set[int]] = {}
    for row in rows:
        result.setdefault(int(row["user_id"]), set()).add(int(row["page_id"]))
    return result


def _users_context(
    conn: sqlite3.Connection, error: str | None = None
) -> dict:
    return {
        "users": conn.execute(
            "SELECT * FROM users ORDER BY role='user', username"
        ).fetchall(),
        "pages": hosts.list_pages(conn),
        "access_map": _user_access_rows(conn),
        "edit_map": _user_edit_rows(conn),
        "error": error,
        "valid_roles": VALID_ROLES,
        "valid_modes": VALID_MODES,
    }


@router.get("/users", response_class=HTMLResponse)
def list_users(
    request: Request,
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return render(request, "users.html", user=user, **_users_context(conn))


@router.post("/users")
async def create_user(
    request: Request,
    admin: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    form = await request.form()
    check_csrf(request, form)
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    role = form.get("role") or "user"
    access_mode = form.get("access_mode") or "all"

    error = None
    if not username:
        error = "Укажите логин"
    elif role not in VALID_ROLES:
        error = "Недопустимая роль"
    elif access_mode not in VALID_MODES:
        error = "Недопустимый режим доступа"
    else:
        error = validate_password(password)
    if error is None:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, role,"
                " access_mode, is_active, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (
                    username,
                    hash_password(password),
                    role,
                    access_mode,
                    db.now_iso(),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            error = f"Пользователь «{username}» уже существует"

    if error:
        return render(
            request, "users.html", user=admin, **_users_context(conn, error)
        )
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/update")
async def update_user(
    user_id: int,
    request: Request,
    admin: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    target = conn.execute(
        "SELECT * FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    form = await request.form()
    check_csrf(request, form)

    role = form.get("role") or target["role"]
    access_mode = form.get("access_mode") or target["access_mode"]
    is_active = 1 if form.get("is_active") else 0

    error = None
    if role not in VALID_ROLES:
        error = "Недопустимая роль"
    elif access_mode not in VALID_MODES:
        error = "Недопустимый режим доступа"
    elif (
        target["role"] == "admin"
        and (role != "admin" or not is_active)
        and _active_admins(conn) <= 1
    ):
        error = "Нельзя убрать последнего активного администратора"

    if error:
        return render(
            request, "users.html", user=admin, **_users_context(conn, error)
        )

    with conn:
        conn.execute(
            "UPDATE users SET role=?, access_mode=?, is_active=? WHERE id=?",
            (role, access_mode, is_active, user_id),
        )
        conn.execute(
            "DELETE FROM user_page_access WHERE user_id=?", (user_id,)
        )
        if access_mode in ("except", "only"):
            conn.executemany(
                "INSERT OR IGNORE INTO user_page_access (user_id, page_id)"
                " VALUES (?, ?)",
                [
                    (user_id, int(pid))
                    for pid in form.getlist("access_page")
                    if str(pid).isdigit()
                ],
            )
        conn.execute("DELETE FROM user_page_edit WHERE user_id=?", (user_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO user_page_edit (user_id, page_id)"
            " VALUES (?, ?)",
            [
                (user_id, int(pid))
                for pid in form.getlist("edit_page")
                if str(pid).isdigit()
            ],
        )
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/password")
async def reset_password(
    user_id: int,
    request: Request,
    admin: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    target = conn.execute(
        "SELECT * FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    form = await request.form()
    check_csrf(request, form)
    password = form.get("password") or ""
    error = validate_password(password)
    if error:
        return render(
            request, "users.html", user=admin, **_users_context(conn, error)
        )
    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (hash_password(password), user_id),
    )
    conn.commit()
    return RedirectResponse("/users", status_code=303)

@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    request: Request,
    admin: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    target = conn.execute(
        "SELECT * FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    form = await request.form()
    check_csrf(request, form)

    error = None
    if int(target["id"]) == int(admin["id"]):
        error = "Нельзя удалить собственную учётную запись"
    elif (
        target["role"] == "admin"
        and target["is_active"]
        and _active_admins(conn) <= 1
    ):
        error = "Нельзя удалить последнего активного администратора"
    if error:
        return render(
            request, "users.html", user=admin, **_users_context(conn, error)
        )

    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    return RedirectResponse("/users", status_code=303)

# --- профиль -------------------------------------------------------------


@router.get("/profile", response_class=HTMLResponse)
def profile(
    request: Request,
    user: sqlite3.Row = Depends(require_user),
):
    return render(request, "profile.html", user=user, error=None)


@router.post("/profile", response_class=HTMLResponse)
async def change_password(
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    form = await request.form()
    check_csrf(request, form)
    current = form.get("current_password") or ""
    new = form.get("new_password") or ""

    error = None
    if not verify_password(user["password_hash"], current):
        error = "Неверный текущий пароль"
    else:
        error = validate_password(new)
    if error:
        return render(request, "profile.html", user=user, error=error)

    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (hash_password(new), user["id"]),
    )
    conn.commit()
    return render(
        request,
        "profile.html",
        user=user,
        error=None,
        success="Пароль обновлён",
    )