"""Типизированные настройки сервиса: загрузка, валидация и запись.

Настройки хранятся в таблице ``settings`` (key/value), чтобы не плодить
миграции. Значения проверяются при записи и при чтении.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, fields
from typing import Mapping

from . import db
from .db import DEFAULT_SETTINGS


class SettingsError(ValueError):
    """Некорректное значение настройки."""


@dataclass(frozen=True)
class Settings:
    """Типизированный снимок настроек с валидацией значений."""

    timeout_ms: int = 1000
    packets: int = 3
    interval_ms: int = 200
    round_interval_s: int = 10
    ui_refresh_s: int = 5
    max_targets: int = 256

    def __post_init__(self) -> None:
        for name, minimum in (
            ("timeout_ms", 1),
            ("packets", 1),
            ("interval_ms", 1),
            ("round_interval_s", 1),
            ("ui_refresh_s", 1),
            ("max_targets", 1),
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise SettingsError(f"{name}: ожидалось целое число")
            if value < minimum:
                raise SettingsError(f"{name}: должно быть >= {minimum}")


def _coerce_int(key: str, value: object) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{key}: ожидалось целое число, получено {value!r}") from exc
    return number


def parse(name: str, value: object) -> int:
    """Проверить и привести одно значение настройки к int."""
    if name not in DEFAULT_SETTINGS:
        raise SettingsError(f"неизвестная настройка: {name}")
    number = _coerce_int(name, value)
    # Переиспользуем проверки dataclass через одно поле.
    try:
        Settings(**{name: number})  # type: ignore[arg-type]
    except SettingsError:
        raise
    except TypeError as exc:  # pragma: no cover - защитная ветка
        raise SettingsError(str(exc)) from exc
    return number


def ensure_defaults(conn: sqlite3.Connection) -> None:
    """Засидировать отсутствующие дефолты (идемпотентно)."""
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS.items(),
    )
    conn.commit()


def load(conn: sqlite3.Connection) -> Settings:
    """Прочитать настройки из БД, дополнив отсутствующие дефолтами."""
    ensure_defaults(conn)
    rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    kwargs = {}
    for field in fields(Settings):
        kwargs[field.name] = parse(field.name, rows[field.name])
    return Settings(**kwargs)


def raw(conn: sqlite3.Connection) -> dict[str, str]:
    """Сырые значения всех настроек."""
    ensure_defaults(conn)
    return dict(conn.execute("SELECT key, value FROM settings").fetchall())


def update(conn: sqlite3.Connection, values: Mapping[str, object]) -> Settings:
    """Проверить и записать набор настроек одной транзакцией."""
    checked = {name: parse(name, value) for name, value in values.items()}
    if not checked:
        return load(conn)
    ensure_defaults(conn)
    with conn:  # транзакция
        for name, number in checked.items():
            conn.execute(
                "UPDATE settings SET value=? WHERE key=?", (str(number), name)
            )
    return load(conn)


def as_dict(settings: Settings) -> dict[str, str]:
    """Сериализовать настройки в key/value для таблицы ``settings``."""
    return {key: str(value) for key, value in asdict(settings).items()}