"""Подключение к SQLite, схема и инициализация БД.

Одна база на сервис пинга и веб-часть. Путь задаётся через env ``PINGER_DB``
(по умолчанию ``data/pinger.db``). Схема инициализируется идемпотентно.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = "data/pinger.db"

#: Дефолтные значения таблицы ``settings`` (сидируются при init).
DEFAULT_SETTINGS: dict[str, str] = {
    "timeout_ms": "1000",
    "packets": "3",
    "interval_ms": "200",
    "round_interval_s": "10",
    "ui_refresh_s": "5",
    "max_targets": "256",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS targets (
    id         INTEGER PRIMARY KEY,
    page_id    INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    name       TEXT,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (page_id, id)
);

CREATE TABLE IF NOT EXISTS addresses (
    id         INTEGER PRIMARY KEY,
    page_id    INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    address    TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (page_id, target_id)
        REFERENCES targets(page_id, id) ON DELETE CASCADE,
    UNIQUE (page_id, address)
);

CREATE TABLE IF NOT EXISTS host_status (
    address_id       INTEGER PRIMARY KEY
                     REFERENCES addresses(id) ON DELETE CASCADE,
    ts               TEXT NOT NULL,
    alive            INTEGER NOT NULL,
    state_since      TEXT NOT NULL,
    consecutive_ok   INTEGER NOT NULL DEFAULT 0,
    consecutive_fail INTEGER NOT NULL DEFAULT 0,
    checks_total     INTEGER NOT NULL DEFAULT 0,
    checks_failed    INTEGER NOT NULL DEFAULT 0,
    last_avg_ms      REAL
);

CREATE TABLE IF NOT EXISTS host_events (
    id         INTEGER PRIMARY KEY,
    address_id INTEGER NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    state      TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT NOT NULL,
    probes     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_host_events_address_started
    ON host_events (address_id, started_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    access_mode   TEXT NOT NULL DEFAULT 'all'
                  CHECK (access_mode IN ('all', 'except', 'only')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_page_access (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, page_id)
);

CREATE TABLE IF NOT EXISTS user_page_edit (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, page_id)
);
"""


def now_iso() -> str:
    """Текущее локальное время в ISO-8601 (без перевода в UTC)."""
    return datetime.now().isoformat(timespec="seconds")


def db_path() -> Path:
    """Путь к БД: env ``PINGER_DB`` или ``data/pinger.db``."""
    return Path(os.environ.get("PINGER_DB", DEFAULT_DB_PATH))


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Открыть соединение и применить прагмы."""
    if path is None:
        path = db_path()
    is_memory = str(path) == ":memory:" or str(path).startswith("file::memory:")
    if not is_memory:
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(
    path: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Connection:
    """Инициализировать схему и засидировать дефолты. Идемпотентно.

    Если ``conn`` не задан, соединение открывается (и возвращается).
    """
    if conn is None:
        conn = connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS.items(),
    )
    conn.commit()
    return conn