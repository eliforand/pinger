from __future__ import annotations

import sqlite3

import pytest

from pinger import db


def test_init_creates_schema(tmp_path):
    path = tmp_path / "pinger.db"
    conn = db.connect(path)
    db.init_db(conn=conn)

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "pages",
        "targets",
        "addresses",
        "host_status",
        "host_events",
        "settings",
        "users",
        "user_page_access",
        "user_page_edit",
    } <= tables
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_init_is_idempotent(tmp_path):
    path = tmp_path / "pinger.db"
    db.init_db(path=path)
    conn = db.init_db(path=path)  # повторный init не падает
    assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == len(
        db.DEFAULT_SETTINGS
    )
    conn.close()


def test_wal_mode_enabled(tmp_path):
    path = tmp_path / "pinger.db"
    conn = db.init_db(path=path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_defaults_seeded(tmp_path):
    path = tmp_path / "pinger.db"
    conn = db.init_db(path=path)
    rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    assert rows == db.DEFAULT_SETTINGS
    conn.close()


def test_defaults_seed_does_not_override(tmp_path):
    path = tmp_path / "pinger.db"
    conn = db.init_db(path=path)
    conn.execute("UPDATE settings SET value='9999' WHERE key='timeout_ms'")
    conn.commit()
    conn2 = db.init_db(path=path)
    value = conn2.execute(
        "SELECT value FROM settings WHERE key='timeout_ms'"
    ).fetchone()[0]
    assert value == "9999"
    conn.close()
    conn2.close()


def test_env_db_path(tmp_path, monkeypatch):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("PINGER_DB", str(target))
    assert db.db_path() == target
    conn = db.init_db()
    assert target.exists()
    conn.close()


def test_cascade_address_delete_removes_status_and_events(tmp_path):
    conn = db.init_db(path=tmp_path / "pinger.db")
    now = db.now_iso()
    page_id = conn.execute(
        "INSERT INTO pages (name, created_at) VALUES ('p', ?)", (now,)
    ).lastrowid
    target_id = conn.execute(
        "INSERT INTO targets (page_id, name, created_at) VALUES (?, 't', ?)",
        (page_id, now),
    ).lastrowid
    addr_id = conn.execute(
        "INSERT INTO addresses (page_id, target_id, address, created_at)"
        " VALUES (?, ?, '10.0.0.1', ?)",
        (page_id, target_id, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO host_status (address_id, ts, alive, state_since)"
        " VALUES (?, ?, 1, ?)",
        (addr_id, now, now),
    )
    conn.execute(
        "INSERT INTO host_events (address_id, state, started_at, ended_at, probes)"
        " VALUES (?, 'down', ?, ?, 3)",
        (addr_id, now, now),
    )
    conn.commit()

    conn.execute("DELETE FROM addresses WHERE id=?", (addr_id,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM host_status").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM host_events").fetchone()[0] == 0
    conn.close()


def test_cascade_target_delete_removes_addresses(tmp_path):
    conn = db.init_db(path=tmp_path / "pinger.db")
    now = db.now_iso()
    page_id = conn.execute(
        "INSERT INTO pages (name, created_at) VALUES ('p', ?)", (now,)
    ).lastrowid
    target_id = conn.execute(
        "INSERT INTO targets (page_id, name, created_at) VALUES (?, 't', ?)",
        (page_id, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO addresses (page_id, target_id, address, created_at)"
        " VALUES (?, ?, '10.0.0.2', ?)",
        (page_id, target_id, now),
    )
    conn.commit()

    conn.execute("DELETE FROM targets WHERE id=?", (target_id,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM addresses").fetchone()[0] == 0
    conn.close()


def test_unique_address_per_page(tmp_path):
    conn = db.init_db(path=tmp_path / "pinger.db")
    now = db.now_iso()
    page_id = conn.execute(
        "INSERT INTO pages (name, created_at) VALUES ('p', ?)", (now,)
    ).lastrowid
    t1 = conn.execute(
        "INSERT INTO targets (page_id, name, created_at) VALUES (?, 't1', ?)",
        (page_id, now),
    ).lastrowid
    t2 = conn.execute(
        "INSERT INTO targets (page_id, name, created_at) VALUES (?, 't2', ?)",
        (page_id, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO addresses (page_id, target_id, address, created_at)"
        " VALUES (?, ?, '10.0.0.3', ?)",
        (page_id, t1, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO addresses (page_id, target_id, address, created_at)"
            " VALUES (?, ?, '10.0.0.3', ?)",
            (page_id, t2, now),
        )
    conn.close()