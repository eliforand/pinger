from __future__ import annotations

import os
import tempfile

import pytest

# Модуль pinger.web создаёт приложение на импорте (для uvicorn pinger.web:app).
# Уводим дефолтную БД в temp, чтобы тесты не трогали data/.
os.environ.setdefault(
    "PINGER_DB",
    os.path.join(tempfile.mkdtemp(prefix="pinger-test-"), "default.db"),
)

from pinger import db, hosts


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(path=tmp_path / "pinger.db")
    yield c
    c.close()


@pytest.fixture()
def sample(conn):
    """Одна страница, одна строка, один адрес. Возвращает id-шники."""
    page_id = hosts.create_page(conn, "page", now="2024-01-01T00:00:00")
    target_id = hosts.create_target(conn, page_id, "row", now="2024-01-01T00:00:00")
    addr_id = hosts.create_address(
        conn,
        page_id,
        target_id,
        "10.0.0.1",
        now="2024-01-01T00:00:00",
    )
    return {"page_id": page_id, "target_id": target_id, "address_id": addr_id}