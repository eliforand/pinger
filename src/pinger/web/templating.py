"""Общие шаблоны и помощники рендеринга."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .security import get_csrf_token

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _fmt_time(value: object) -> str:
    """Короткое человекочитаемое время (без секунд)."""
    text = str(value or "")
    return text[11:16] if len(text) >= 16 else text


templates.env.filters["fmt_time"] = _fmt_time


def render(request: Request, name: str, /, **context) -> HTMLResponse:
    context.setdefault("user", None)
    context["csrf_token"] = get_csrf_token(request)
    return templates.TemplateResponse(request, name, context)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"