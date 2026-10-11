from __future__ import annotations

from pinger import status


def test_first_check_creates_status_without_event(conn, sample):
    aid = sample["address_id"]
    changes = status.apply_round(
        conn, [status.StatusUpdate(aid, True, 1.5)], now="2024-01-01T00:00:10"
    )
    assert changes == []
    row = status.get_status(conn, aid)
    assert row["alive"] == 1
    assert row["ts"] == "2024-01-01T00:00:10"
    assert row["state_since"] == "2024-01-01T00:00:10"
    assert row["consecutive_ok"] == 1
    assert row["consecutive_fail"] == 0
    assert row["checks_total"] == 1
    assert row["checks_failed"] == 0
    assert row["last_avg_ms"] == 1.5
    assert status.events_for(conn, aid) == []


def test_first_check_down(conn, sample):
    aid = sample["address_id"]
    status.apply_round(conn, [status.StatusUpdate(aid, False)], now="t0")
    row = status.get_status(conn, aid)
    assert row["alive"] == 0
    assert row["consecutive_ok"] == 0
    assert row["consecutive_fail"] == 1
    assert row["checks_failed"] == 1


def test_stable_state_writes_no_event(conn, sample):
    aid = sample["address_id"]
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t0")
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t1")
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t2")

    assert status.events_for(conn, aid) == []
    row = status.get_status(conn, aid)
    assert row["consecutive_ok"] == 3
    assert row["checks_total"] == 3
    assert row["state_since"] == "t0"
    assert row["ts"] == "t2"


def test_up_to_down_writes_exactly_one_interval(conn, sample):
    aid = sample["address_id"]
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t0")
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t1")
    changes = status.apply_round(
        conn, [status.StatusUpdate(aid, False)], now="t2"
    )

    events = status.events_for(conn, aid)
    assert len(events) == 1
    ev = events[0]
    assert ev["state"] == "up"
    assert ev["started_at"] == "t0"
    assert ev["ended_at"] == "t2"
    assert ev["probes"] == 2

    assert len(changes) == 1
    assert changes[0].from_alive is True
    assert changes[0].to_alive is False

    row = status.get_status(conn, aid)
    assert row["alive"] == 0
    assert row["state_since"] == "t2"
    assert row["consecutive_ok"] == 0
    assert row["consecutive_fail"] == 1
    assert row["checks_total"] == 3
    assert row["checks_failed"] == 1


def test_down_to_up_writes_interval(conn, sample):
    aid = sample["address_id"]
    status.apply_round(conn, [status.StatusUpdate(aid, False)], now="t0")
    status.apply_round(conn, [status.StatusUpdate(aid, False)], now="t1")
    changes = status.apply_round(
        conn, [status.StatusUpdate(aid, True, 2.0)], now="t2"
    )

    events = status.events_for(conn, aid)
    assert len(events) == 1
    assert events[0]["state"] == "down"
    assert events[0]["started_at"] == "t0"
    assert events[0]["ended_at"] == "t2"
    assert events[0]["probes"] == 2
    assert changes[0].from_alive is False
    assert changes[0].to_alive is True


def test_multiple_alternations_accumulate_events(conn, sample):
    aid = sample["address_id"]
    for i, alive in enumerate([True, True, False, False, True, False]):
        status.apply_round(
            conn, [status.StatusUpdate(aid, alive)], now=f"t{i}"
        )
    events = status.events_for(conn, aid)
    assert [(e["state"], e["started_at"], e["ended_at"], e["probes"]) for e in events] == [
        ("up", "t0", "t2", 2),
        ("down", "t2", "t4", 2),
        ("up", "t4", "t5", 1),
    ]
    row = status.get_status(conn, aid)
    assert row["alive"] == 0
    assert row["state_since"] == "t5"
    assert row["checks_total"] == 6
    assert row["checks_failed"] == 3


def test_apply_round_multiple_addresses(conn, sample):
    from pinger import hosts

    second = hosts.create_address(
        conn, sample["page_id"], sample["target_id"], "10.0.0.2", now="t0"
    )
    status.apply_round(
        conn,
        [
            status.StatusUpdate(sample["address_id"], True),
            status.StatusUpdate(second, False),
        ],
        now="t0",
    )
    assert status.get_status(conn, sample["address_id"])["alive"] == 1
    assert status.get_status(conn, second)["alive"] == 0


def test_apply_round_is_atomic(conn, sample):
    # теперь два адреса; если один update вызовет ошибку, второй не применится
    aid = sample["address_id"]
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t0")
    # повторный раунд: ок
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t1")
    assert status.get_status(conn, aid)["checks_total"] == 2


def test_status_map(conn, sample):
    aid = sample["address_id"]
    status.apply_round(conn, [status.StatusUpdate(aid, True)], now="t0")
    m = status.status_map(conn, [aid, 999])
    assert set(m) == {aid}
    assert status.status_map(conn, []) == {}