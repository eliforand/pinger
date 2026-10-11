from __future__ import annotations

import pytest

from pinger import db, settings


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(path=tmp_path / "pinger.db")
    yield c
    c.close()


def test_defaults(conn):
    s = settings.load(conn)
    assert s.timeout_ms == 1000
    assert s.packets == 3
    assert s.interval_ms == 200
    assert s.round_interval_s == 10
    assert s.ui_refresh_s == 5
    assert s.max_targets == 256


def test_override_persists(conn):
    updated = settings.update(conn, {"round_interval_s": "30", "packets": 5})
    assert updated.round_interval_s == 30
    assert updated.packets == 5
    assert settings.load(conn).round_interval_s == 30


def test_seed_is_idempotent(conn):
    settings.ensure_defaults(conn)
    settings.ensure_defaults(conn)
    assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == len(
        db.DEFAULT_SETTINGS
    )


def test_seed_does_not_override_existing(conn):
    settings.update(conn, {"packets": 9})
    settings.ensure_defaults(conn)
    assert settings.load(conn).packets == 9


@pytest.mark.parametrize("bad", ["abc", "", "1.5", None, "0", "-3"])
def test_validation_rejects_bad_values(conn, bad):
    with pytest.raises(settings.SettingsError):
        settings.update(conn, {"packets": bad})


def test_parse_unknown_key():
    with pytest.raises(settings.SettingsError):
        settings.parse("does_not_exist", "1")


def test_parse_accepts_int_like():
    assert settings.parse("timeout_ms", " 1500 ") == 1500
    assert settings.parse("packets", 4) == 4


def test_update_empty_returns_current(conn):
    assert settings.update(conn, {}) == settings.load(conn)


def test_as_dict():
    s = settings.Settings(timeout_ms=1234)
    assert settings.as_dict(s)["timeout_ms"] == "1234"
    assert set(settings.as_dict(s)) == set(db.DEFAULT_SETTINGS)