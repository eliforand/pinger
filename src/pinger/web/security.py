"""Пароли (argon2) и CSRF-токены."""

from __future__ import annotations

import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from fastapi import HTTPException, Request

MIN_PASSWORD_LENGTH = 8

_hasher = PasswordHasher()

_CSRF_SESSION_KEY = "csrf_token"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password(password: str) -> str | None:
    """Вернуть текст ошибки или None, если пароль допустим."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
    return None


def get_csrf_token(request: Request) -> str:
    token = request.session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_CSRF_SESSION_KEY] = token
    return token


def _form_token(form: Any) -> str:
    token = form.get("csrf_token")
    return str(token) if token is not None else ""


def check_csrf(request: Request, form: Any) -> None:
    """Сверить CSRF-токен формы с токеном сессии."""
    expected = request.session.get(_CSRF_SESSION_KEY, "")
    received = _form_token(form)
    if not expected or not received or not secrets.compare_digest(
        expected, received
    ):
        raise HTTPException(status_code=400, detail="CSRF token mismatch")