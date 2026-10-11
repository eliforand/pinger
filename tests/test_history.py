from __future__ import annotations

from datetime import datetime

from pinger import history


NOW = datetime(2024, 1, 1, 12, 0, 0)


def _add_event(conn, address_id, state, started, ended, probes=1):
    conn.execute(
        "INSERT INTO host_events (address_id, state, started_at, ended_at, probes)"
        " VALUES (?, ?, ?, ?, ?)",
        (address_id, state, started, ended, probes),
    )


def _set_status(conn, address_id, alive, state_since, ok=1, fail=1):
    conn.execute(
        "INSERT INTO host_status"
        " (address_id, ts, alive, state_since, consecutive_ok, consecutive_fail,"
        "  checks_total, checks_failed)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            address_id,
            state_since,
            alive,
            state_since,
            ok,
            fail,
            ok + fail,
            fail,
        ),
    )


def _seed(conn, address_id):
    # up 00:00-06:00, down 06:00-09:00, up 09:00-11:00, затем down (открытый с 11:00)
    _add_event(conn, address_id, "up", "2024-01-01T00:00:00", "2024-01-01T06:00:00")
    _add_event(conn, address_id, "down", "2024-01-01T06:00:00", "2024-01-01T09:00:00")
    _add_event(conn, address_id, "up", "2024-01-01T09:00:00", "2024-01-01T11:00:00")
    _set_status(conn, address_id, 0, "2024-01-01T11:00:00", ok=0, fail=1)
    conn.commit()


def test_intervals_all_range(conn, sample):
    aid = sample["address_id"]
    _seed(conn, aid)
    intervals = history.intervals_for(conn, aid, range_key="all", now=NOW)
    assert [(i.state, i.open) for i in intervals] == [
        ("up", False),
        ("down", False),
        ("up", False),
        ("down", True),
    ]


def test_uptime_all_range(conn, sample):
    aid = sample["address_id"]
    _seed(conn, aid)
    # up 8ч, down 4ч -> 66.7%
    assert history.uptime_pct(conn, aid, range_key="all", now=NOW) == 66.7


def test_range_1h_only_open_interval(conn, sample):
    aid = sample["address_id"]
    _seed(conn, aid)
    intervals = history.intervals_for(conn, aid, range_key="1h", now=NOW)
    assert len(intervals) == 1
    assert intervals[0].state == "down"
    assert intervals[0].open is True
    assert intervals[0].duration_s == 3600
    assert history.uptime_pct(conn, aid, range_key="1h", now=NOW) == 0.0


def test_range_clips_event(conn, sample):
    aid = sample["address_id"]
    _seed(conn, aid)
    # 12ч: начало 00:00 -> всё, кроме... up 6ч + down 3ч + up 2ч + down 1ч
    intervals = history.intervals_for(conn, aid, range_key="12h", now=NOW)
    assert [i.state for i in intervals] == ["up", "down", "up", "down"]
    assert history.uptime_pct(conn, aid, range_key="12h", now=NOW) == 66.7


def test_no_data_returns_none(conn, sample):
    aid = sample["address_id"]
    assert history.intervals_for(conn, aid, now=NOW) == []
    assert history.uptime_pct(conn, aid, now=NOW) is None


def test_only_status_no_events(conn, sample):
    aid = sample["address_id"]
    _set_status(conn, aid, 1, "2024-01-01T11:30:00")
    conn.commit()
    intervals = history.intervals_for(conn, aid, range_key="1h", now=NOW)
    assert len(intervals) == 1
    assert intervals[0].state == "up"
    assert intervals[0].duration_s == 1800
    assert history.uptime_pct(conn, aid, range_key="1h", now=NOW) == 100.0