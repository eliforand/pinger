"""Маршруты веб-интерфейса: главный экран, просмотр и редактирование страниц."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import history, hosts, settings, status
from . import access
from .auth import Forbidden, get_conn, require_admin, require_user
from .security import check_csrf
from .templating import is_htmx, render

router = APIRouter()

PAGE_STATS_SQL = """
SELECT p.id, p.name, p.description, p.position, p.enabled,
       COUNT(a.id) AS total,
       COALESCE(SUM(CASE WHEN s.alive=1 THEN 1 ELSE 0 END), 0) AS up,
       COALESCE(SUM(CASE WHEN s.alive=0 THEN 1 ELSE 0 END), 0) AS down
FROM pages p
LEFT JOIN addresses a ON a.page_id = p.id
LEFT JOIN host_status s ON s.address_id = a.id
GROUP BY p.id
ORDER BY p.position, p.id
"""


def page_cards(conn: sqlite3.Connection, user: sqlite3.Row) -> list[dict]:
    """Карточки видимых страниц со статистикой адресов."""
    allowed = access.visible_page_ids(conn, user)
    edit_ids = access.edit_page_ids(conn, user)
    cards = []
    for row in conn.execute(PAGE_STATS_SQL):
        if allowed is not None and int(row["id"]) not in allowed:
            continue
        card = dict(row)
        card["no_data"] = card["total"] - card["up"] - card["down"]
        card["can_edit"] = (
            edit_ids is None or int(row["id"]) in edit_ids
        )
        cards.append(card)
    return cards


def _int_uptime(value: float | None) -> int | None:
    """Uptime в целых процентах для отображения."""
    return None if value is None else int(round(value))


def page_rows(conn: sqlite3.Connection, page_id: int) -> list[dict]:
    """Строки таблицы страницы: target + ячейки адресов со статусом."""
    targets = hosts.list_targets(conn, page_id)
    addresses = hosts.list_addresses(conn, page_id)
    by_target: dict[int, list[sqlite3.Row]] = {}
    for address in addresses:
        by_target.setdefault(int(address["target_id"]), []).append(address)
    statuses = status.status_map(conn, [int(a["id"]) for a in addresses])

    rows = []
    for target in targets:
        cells = []
        for address in by_target.get(int(target["id"]), []):
            aid = int(address["id"])
            st = statuses.get(aid)
            state = None if st is None else ("up" if st["alive"] else "down")
            cells.append(
                {
                    "address": address,
                    "state": state,
                    "uptime": _int_uptime(
                        history.uptime_pct(conn, aid, range_key="24h")
                    ),
                }
            )
        rows.append({"target": target, "cells": cells})
    return rows


def page_stats(rows: list[dict]) -> dict:
    """Сводка up/down/нет данных по строкам страницы."""
    total = up = down = 0
    for row in rows:
        for cell in row["cells"]:
            total += 1
            if cell["state"] == "up":
                up += 1
            elif cell["state"] == "down":
                down += 1
    return {"total": total, "up": up, "down": down, "no_data": total - up - down}


def _get_page(conn: sqlite3.Connection, page_id: int) -> sqlite3.Row:
    page = hosts.get_page(conn, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    return page


def _page_context(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    page: sqlite3.Row,
    error: str | None = None,
) -> dict:
    rows = page_rows(conn, int(page["id"]))
    return {
        "user": user,
        "page": page,
        "rows": rows,
        "stats": page_stats(rows),
        "can_edit": access.can_edit(conn, user, int(page["id"])),
        "is_admin": user["role"] == "admin",
        "error": error,
        "ui_refresh_s": settings.load(conn).ui_refresh_s,
    }


def _view_response(
    request: Request,
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    page: sqlite3.Row,
) -> HTMLResponse:
    """Режим просмотра: HTMX -> фрагмент, иначе полная страница."""
    context = _page_context(conn, user, page)
    template = "partials/page_view.html" if is_htmx(request) else "page.html"
    return render(request, template, **context)


def _edit_response(
    request: Request,
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    page: sqlite3.Row,
    *,
    error: str | None = None,
) -> HTMLResponse:
    """Режим редактирования: HTMX -> фрагмент, иначе полная страница."""
    context = _page_context(conn, user, page, error)
    template = "partials/page_edit.html" if is_htmx(request) else "page_edit.html"
    return render(request, template, **context)


def _after_mutation(
    request: Request,
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    page: sqlite3.Row,
    *,
    error: str | None = None,
) -> HTMLResponse | RedirectResponse:
    """Ответ после изменения: редакторам — фрагмент/страница редактирования."""
    if error is not None or is_htmx(request):
        return _edit_response(request, conn, user, page, error=error)
    return RedirectResponse(f"/pages/{page['id']}/edit", status_code=303)


def _index_context(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    error: str | None = None,
) -> dict:
    return {
        "user": user,
        "pages": page_cards(conn, user),
        "is_admin": user["role"] == "admin",
        "ui_refresh_s": settings.load(conn).ui_refresh_s,
        "error": error,
    }


# --- главный экран -------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    context = _index_context(conn, user)
    template = "partials/page_list.html" if is_htmx(request) else "index.html"
    return render(request, template, **context)

@router.get("/edit", response_class=HTMLResponse)
def edit_index(
    request: Request,
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Режим редактирования главной: создание/удаление/настройки страниц."""
    return render(request, "index_edit.html", **_index_context(conn, user))


@router.post("/pages")
async def create_page(
    request: Request,
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    form = await request.form()
    check_csrf(request, form)
    name = (form.get("name") or "").strip()
    description = (form.get("description") or "").strip() or None
    error = None
    if not name:
        error = "Укажите название страницы"
    else:
        try:
            hosts.create_page(conn, name, description)
        except sqlite3.IntegrityError:
            error = f"Страница «{name}» уже существует"

    if error:
        return render(
            request, "index_edit.html", **_index_context(conn, user, error)
        )
    return RedirectResponse("/edit", status_code=303)


@router.post("/pages/{page_id}/update")
async def update_page(
    page_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    page = _get_page(conn, page_id)
    form = await request.form()
    check_csrf(request, form)
    name = (form.get("name") or "").strip()
    description = (form.get("description") or "").strip()
    enabled = bool(form.get("enabled"))
    error = None
    if not name:
        error = "Укажите название страницы"
    else:
        try:
            hosts.update_page(
                conn,
                page_id,
                name=name,
                description=description or None,
                enabled=enabled,
            )
        except sqlite3.IntegrityError:
            error = f"Страница «{name}» уже существует"
    if error:
        return render(
            request, "index_edit.html", **_index_context(conn, user, error)
        )
    return RedirectResponse("/edit", status_code=303)

@router.post("/pages/{page_id}/delete")
async def delete_page(
    page_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    _get_page(conn, page_id)
    form = await request.form()
    check_csrf(request, form)
    hosts.delete_page(conn, page_id)
    return RedirectResponse("/edit", status_code=303)


# --- экран страницы: просмотр --------------------------------------------


@router.get("/pages/{page_id}", response_class=HTMLResponse)
def show_page(
    page_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    page = _get_page(conn, page_id)
    if not access.can_view(conn, user, page_id):
        raise Forbidden()
    return _view_response(request, conn, user, page)

@router.get("/pages/{page_id}/status.json")
def page_status_json(
    page_id: int,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """JSON-срез статусов страницы для автообновления без HTML."""
    page = _get_page(conn, page_id)
    if not access.can_view(conn, user, page_id):
        raise Forbidden()
    rows = page_rows(conn, page_id)
    return {
        "stats": page_stats(rows),
        "rows": [
            {
                "target_id": int(row["target"]["id"]),
                "cells": [
                    {
                        "address_id": int(cell["address"]["id"]),
                        "state": cell["state"],
                        "uptime": cell["uptime"],
                        "enabled": bool(cell["address"]["enabled"]),
                    }
                    for cell in row["cells"]
                ],
            }
            for row in rows
        ],
    }


@router.get("/index.json")
def index_json(
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """JSON-срез карточек главной для автообновления без HTML."""
    return {
        "pages": [
            {
                "id": int(card["id"]),
                "enabled": bool(card["enabled"]),
                "total": card["total"],
                "up": card["up"],
                "down": card["down"],
                "no_data": card["no_data"],
            }
            for card in page_cards(conn, user)
        ],
    }



# --- экран страницы: редактирование ---------------------------------------


@router.get("/pages/{page_id}/edit", response_class=HTMLResponse)
def edit_page(
    page_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    page = _get_page(conn, page_id)
    if not access.can_view(conn, user, page_id):
        raise Forbidden()
    if not access.can_edit(conn, user, page_id):
        raise Forbidden()
    return _edit_response(request, conn, user, page)


@router.post("/pages/{page_id}/targets")
async def create_target(
    page_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    page = _get_page(conn, page_id)
    if not access.can_edit(conn, user, page_id):
        raise Forbidden()
    form = await request.form()
    check_csrf(request, form)
    name = (form.get("name") or "").strip() or None
    hosts.create_target(conn, page_id, name)
    return _after_mutation(request, conn, user, page)


@router.post("/targets/{target_id}/rename")
async def rename_target(
    target_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    target = hosts.get_target(conn, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")
    page = _get_page(conn, int(target["page_id"]))
    if not access.can_edit(conn, user, page["id"]):
        raise Forbidden()
    form = await request.form()
    check_csrf(request, form)
    name = (form.get("name") or "").strip() or None
    hosts.update_target(conn, target_id, name=name)
    return _after_mutation(request, conn, user, page)


@router.post("/pages/{page_id}/addresses")
async def create_address(
    page_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    page = _get_page(conn, page_id)
    if not access.can_edit(conn, user, page_id):
        raise Forbidden()
    form = await request.form()
    check_csrf(request, form)

    try:
        target_id = int(form.get("target_id") or 0)
    except (TypeError, ValueError):
        target_id = 0
    address = (form.get("address") or "").strip()

    target = hosts.get_target(conn, target_id)
    error = None
    if target is None or int(target["page_id"]) != page_id:
        error = "Строка не найдена"
    elif not address:
        error = "Укажите IP-адрес"
    else:
        existing = hosts.find_address_in_page(conn, page_id, address)
        if existing is not None:
            owner = hosts.get_target(conn, int(existing["target_id"]))
            owner_name = (
                owner["name"] if owner and owner["name"] else "без названия"
            )
            error = (
                f"Адрес {address} уже есть на этой странице"
                f" в строке «{owner_name}»"
            )
        else:
            hosts.create_address(conn, page_id, target_id, address)

    return _after_mutation(request, conn, user, page, error=error)


@router.post("/targets/{target_id}/delete")
async def delete_target(
    target_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    target = hosts.get_target(conn, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Строка не найдена")
    page = _get_page(conn, int(target["page_id"]))
    if not access.can_edit(conn, user, page["id"]):
        raise Forbidden()
    form = await request.form()
    check_csrf(request, form)
    hosts.delete_target(conn, target_id)
    return _after_mutation(request, conn, user, page)


@router.post("/addresses/{address_id}/delete")
async def delete_address(
    address_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    address = hosts.get_address(conn, address_id)
    if address is None:
        raise HTTPException(status_code=404, detail="Адрес не найден")
    page = _get_page(conn, int(address["page_id"]))
    if not access.can_edit(conn, user, page["id"]):
        raise Forbidden()
    form = await request.form()
    check_csrf(request, form)
    hosts.delete_address(conn, address_id)
    return _after_mutation(request, conn, user, page)


@router.post("/addresses/{address_id}/toggle")
async def toggle_address(
    address_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    address = hosts.get_address(conn, address_id)
    if address is None:
        raise HTTPException(status_code=404, detail="Адрес не найден")
    page = _get_page(conn, int(address["page_id"]))
    if not access.can_edit(conn, user, page["id"]):
        raise Forbidden()
    form = await request.form()
    check_csrf(request, form)
    hosts.update_address(
        conn, address_id, enabled=not bool(address["enabled"])
    )
    return _after_mutation(request, conn, user, page)


# --- экран адреса ----------------------------------------------------------

RANGE_LABELS = {
    "1h": "1 час",
    "12h": "12 часов",
    "24h": "сутки",
    "7d": "неделя",
    "all": "всё",
}


@router.get("/addresses/{address_id}", response_class=HTMLResponse)
def show_address(
    address_id: int,
    request: Request,
    range: str = history.DEFAULT_RANGE,
    user: sqlite3.Row = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    address = hosts.get_address(conn, address_id)
    if address is None:
        raise HTTPException(status_code=404, detail="Адрес не найден")
    page = _get_page(conn, int(address["page_id"]))
    if not access.can_view(conn, user, page["id"]):
        raise Forbidden()
    if range not in history.RANGES:
        range = history.DEFAULT_RANGE

    now = datetime.now()
    intervals = history.intervals_for(
        conn, address_id, range_key=range, now=now
    )
    total = sum(i.duration_s for i in intervals) or 1.0
    blocks = [
        {
            "state": interval.state,
            "open": interval.open,
            "pct": interval.duration_s / total * 100.0,
            "started_at": interval.started_at,
            "ended_at": interval.ended_at,
            "probes": interval.probes,
            "duration_s": interval.duration_s,
        }
        for interval in intervals
    ]
    st = status.get_status(conn, address_id)
    return render(
        request,
        "address.html",
        user=user,
        page=page,
        address=address,
        st=st,
        state=None if st is None else ("up" if st["alive"] else "down"),
        range_key=range,
        ranges=list(history.RANGES),
        range_labels=RANGE_LABELS,
        blocks=blocks,
        uptime=_int_uptime(
            history.uptime_pct(conn, address_id, range_key=range, now=now)
        ),
    )
