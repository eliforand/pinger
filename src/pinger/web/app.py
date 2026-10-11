"""FastAPI-приложение: каркас, аутентификация, /setup, /login."""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from .pages import router as pages_router
from .users import router as users_router
from .templating import render

from .. import db
from .auth import AuthRequired, Forbidden, get_conn, has_admin, require_user
from .security import (
    check_csrf,
    get_csrf_token,
    hash_password,
    validate_password,
    verify_password,
)


DEFAULT_SECRET = "dev-insecure-secret-change-me"




def create_app(
    db_path: str | Path | None = None,
    *,
    secret_key: str | None = None,
) -> FastAPI:
    app = FastAPI(title="pinger")
    if db_path is None:
        db_path = db.db_path()
    app.state.db_path = Path(db_path)
    db.init_db(path=app.state.db_path)

    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key or os.environ.get("SECRET_KEY", DEFAULT_SECRET),
        same_site="lax",
        https_only=False,
    )

    # --- обработчики исключений прав ---------------------------------

    @app.exception_handler(AuthRequired)
    async def _auth_required(request: Request, exc: AuthRequired):
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        return PlainTextResponse("Доступ запрещён", status_code=403)

    # --- первый запуск: единственная доступная страница /setup --------

    @app.middleware("http")
    async def setup_guard(request: Request, call_next):
        path = request.url.path
        if path == "/setup" or path.startswith("/static"):
            return await call_next(request)
        conn = db.connect(request.app.state.db_path)
        try:
            admin_exists = has_admin(conn)
        finally:
            conn.close()
        if not admin_exists:
            return RedirectResponse("/setup", status_code=303)
        return await call_next(request)

    # --- setup ---------------------------------------------------------

    def _setup_context(error: str | None = None) -> dict:
        return {
            "error": error,
            "setup_token_required": bool(os.environ.get("PINGER_SETUP_TOKEN")),
        }

    @app.get("/setup", response_class=HTMLResponse)
    def setup_form(
        request: Request, conn: sqlite3.Connection = Depends(get_conn)
    ):
        if has_admin(conn):
            return RedirectResponse("/login", status_code=303)
        return render(request, "setup.html", **_setup_context())

    @app.post("/setup", response_class=HTMLResponse)
    async def setup_submit(
        request: Request, conn: sqlite3.Connection = Depends(get_conn)
    ):
        if has_admin(conn):
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        check_csrf(request, form)

        username = (form.get("username") or "").strip()
        password = form.get("password") or ""
        required_token = os.environ.get("PINGER_SETUP_TOKEN")
        if required_token:
            supplied = str(form.get("setup_token") or "")
            if not secrets.compare_digest(supplied, required_token):
                return render(
                    request,
                    "setup.html",
                    **_setup_context("Неверный setup-токен"),
                )
        if not username:
            return render(
                request, "setup.html", **_setup_context("Укажите логин")
            )
        password_error = validate_password(password)
        if password_error:
            return render(
                request, "setup.html", **_setup_context(password_error)
            )

        try:
            cur = conn.execute(
                "INSERT INTO users"
                " (username, password_hash, role, access_mode, is_active, created_at)"
                " VALUES (?, ?, 'admin', 'all', 1, ?)",
                (username, hash_password(password), db.now_iso()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return render(
                request,
                "setup.html",
                **_setup_context("Такой пользователь уже существует"),
            )
        request.session["user_id"] = int(cur.lastrowid)
        return RedirectResponse("/", status_code=303)

    # --- login / logout ------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if request.session.get("user_id"):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html", error=None)

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request, conn: sqlite3.Connection = Depends(get_conn)
    ):
        form = await request.form()
        check_csrf(request, form)
        username = (form.get("username") or "").strip()
        password = form.get("password") or ""
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()
        if row is None or not verify_password(row["password_hash"], password):
            return render(
                request, "login.html", error="Неверный логин или пароль"
            )
        request.session["user_id"] = int(row["id"])
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        form = await request.form()
        check_csrf(request, form)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)



    app.include_router(pages_router)
    app.include_router(users_router)
    return app


app = create_app()