"""История доступности: интервалы для графика и uptime % за диапазон."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Диапазоны экрана адреса: ключ -> длительность в секундах (None = всё).
RANGES: dict[str, int | None] = {
    "1h": 3600,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "all": None,
}
DEFAULT_RANGE = "24h"


@dataclass(frozen=True)
class Interval:
    state: str  # 'up' | 'down'
    started_at: datetime
    ended_at: datetime
    probes: int
    open: bool = False

    @property
    def duration_s(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def range_start(range_key: str, now: datetime) -> datetime | None:
    seconds = RANGES.get(range_key, RANGES[DEFAULT_RANGE])
    if seconds is None:
        return None
    return now - timedelta(seconds=seconds)


def _clip(
    start: datetime,
    end: datetime,
    window_start: datetime | None,
    window_end: datetime,
) -> tuple[datetime, datetime] | None:
    if window_start is not None and start < window_start:
        start = window_start
    if end > window_end:
        end = window_end
    if end <= start:
        return None
    return start, end


def intervals_for(
    conn: sqlite3.Connection,
    address_id: int,
    *,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> list[Interval]:
    """Интервалы up/down, обрезанные до диапазона (включая открытый)."""
    now = now or datetime.now()
    start = range_start(range_key, now)
    result: list[Interval] = []

    rows = conn.execute(
        "SELECT state, started_at, ended_at, probes FROM host_events"
        " WHERE address_id=? ORDER BY started_at, id",
        (address_id,),
    ).fetchall()
    for row in rows:
        clipped = _clip(
            parse_ts(row["started_at"]), parse_ts(row["ended_at"]), start, now
        )
        if clipped is not None:
            result.append(
                Interval(
                    state=row["state"],
                    started_at=clipped[0],
                    ended_at=clipped[1],
                    probes=int(row["probes"]),
                )
            )

    st = conn.execute(
        "SELECT alive, state_since, consecutive_ok, consecutive_fail"
        " FROM host_status WHERE address_id=?",
        (address_id,),
    ).fetchone()
    if st is not None:
        clipped = _clip(parse_ts(st["state_since"]), now, start, now)
        if clipped is not None:
            result.append(
                Interval(
                    state="up" if st["alive"] else "down",
                    started_at=clipped[0],
                    ended_at=clipped[1],
                    probes=int(
                        st["consecutive_ok"]
                        if st["alive"]
                        else st["consecutive_fail"]
                    ),
                    open=True,
                )
            )
    return result


def uptime_pct(
    conn: sqlite3.Connection,
    address_id: int,
    *,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> float | None:
    """Uptime % за диапазон. None, если данных нет вовсе."""
    intervals = intervals_for(
        conn, address_id, range_key=range_key, now=now
    )
    up = sum(i.duration_s for i in intervals if i.state == "up")
    total = sum(i.duration_s for i in intervals)
    if total <= 0:
        return None
    return round(up / total * 100.0, 1)