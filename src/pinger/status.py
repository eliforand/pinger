"""Обновление статусов ``host_status`` и закрытие интервалов ``host_events``.

История пишется только при смене состояния (up<->down). Открытый интервал
отдельно не хранится — он выводится из ``host_status.alive + state_since``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import now_iso


@dataclass(frozen=True)
class StatusUpdate:
    """Результат опроса одного адреса для применения к БД."""

    address_id: int
    alive: bool
    avg_ms: float | None = None


@dataclass(frozen=True)
class StateChange:
    """Зафиксированный переход состояния (для лога сервиса)."""

    address_id: int
    from_alive: bool
    to_alive: bool
    started_at: str
    ended_at: str
    probes: int


def get_status(
    conn: sqlite3.Connection, address_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM host_status WHERE address_id=?", (address_id,)
    ).fetchone()


def apply_round(
    conn: sqlite3.Connection,
    updates: list[StatusUpdate],
    *,
    now: str | None = None,
) -> list[StateChange]:
    """Применить результаты раунда одной транзакцией.

    Возвращает список произошедших переходов up/down.
    """
    ts = now or now_iso()
    changes: list[StateChange] = []
    with conn:  # одна транзакция на раунд
        for update in updates:
            row = conn.execute(
                "SELECT * FROM host_status WHERE address_id=?",
                (update.address_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO host_status"
                    " (address_id, ts, alive, state_since,"
                    "  consecutive_ok, consecutive_fail,"
                    "  checks_total, checks_failed, last_avg_ms)"
                    " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (
                        update.address_id,
                        ts,
                        int(update.alive),
                        ts,
                        1 if update.alive else 0,
                        0 if update.alive else 1,
                        0 if update.alive else 1,
                        update.avg_ms,
                    ),
                )
                continue

            prev_alive = bool(row["alive"])
            if update.alive == prev_alive:
                # Стабильное состояние — интервал в host_events не пишем.
                conn.execute(
                    "UPDATE host_status SET ts=?,"
                    " consecutive_ok=?, consecutive_fail=?,"
                    " checks_total=checks_total+1,"
                    " checks_failed=checks_failed+?, last_avg_ms=?"
                    " WHERE address_id=?",
                    (
                        ts,
                        row["consecutive_ok"] + 1 if update.alive else 0,
                        0 if update.alive else row["consecutive_fail"] + 1,
                        0 if update.alive else 1,
                        update.avg_ms,
                        update.address_id,
                    ),
                )
                continue

            # Смена состояния: закрываем текущий интервал и открываем новый.
            probes = (
                row["consecutive_ok"] if prev_alive else row["consecutive_fail"]
            )
            conn.execute(
                "INSERT INTO host_events"
                " (address_id, state, started_at, ended_at, probes)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    update.address_id,
                    "up" if prev_alive else "down",
                    row["state_since"],
                    ts,
                    probes,
                ),
            )
            conn.execute(
                "UPDATE host_status SET ts=?, alive=?, state_since=?,"
                " consecutive_ok=?, consecutive_fail=?,"
                " checks_total=checks_total+1,"
                " checks_failed=checks_failed+?, last_avg_ms=?"
                " WHERE address_id=?",
                (
                    ts,
                    int(update.alive),
                    ts,
                    1 if update.alive else 0,
                    0 if update.alive else 1,
                    0 if update.alive else 1,
                    update.avg_ms,
                    update.address_id,
                ),
            )
            changes.append(
                StateChange(
                    address_id=update.address_id,
                    from_alive=prev_alive,
                    to_alive=update.alive,
                    started_at=row["state_since"],
                    ended_at=ts,
                    probes=probes,
                )
            )
    return changes


def status_map(
    conn: sqlite3.Connection, address_ids: list[int]
) -> dict[int, sqlite3.Row]:
    """Статусы для набора адресов (для UI)."""
    if not address_ids:
        return {}
    placeholders = ",".join("?" * len(address_ids))
    rows = conn.execute(
        f"SELECT * FROM host_status WHERE address_id IN ({placeholders})",
        address_ids,
    )
    return {int(row["address_id"]): row for row in rows}


def events_for(
    conn: sqlite3.Connection, address_id: int
) -> list[sqlite3.Row]:
    """Закрытые интервалы адреса, от старых к новым."""
    return list(
        conn.execute(
            "SELECT * FROM host_events WHERE address_id=?"
            " ORDER BY started_at, id",
            (address_id,),
        )
    )