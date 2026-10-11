from __future__ import annotations

import asyncio

import pytest

from pinger import hosts, settings, status
from pinger.service import PingService


FAKE_FPING = """#!/bin/sh
while IFS= read -r line; do
  [ -z "$line" ] && continue
  if [ "$FAKE_MODE" = "down" ]; then
    echo "$line : xmt/rcv/%loss = 3/0/100%" >&2
  elif [ "$FAKE_MODE" = "partial" ]; then
    echo "$line : xmt/rcv/%loss = 3/1/66%, min/avg/max = 1.0/1.0/1.0" >&2
  else
    echo "$line : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1.0/1.5/2.0" >&2
  fi
done
"""


def make_fake_fping(tmp_path, monkeypatch, mode="up"):
    script = tmp_path / "fping"
    script.write_text(FAKE_FPING)
    script.chmod(0o755)
    monkeypatch.setenv("FAKE_MODE", mode)
    return script


def add_address(conn, page_id, target_id, address):
    return hosts.create_address(conn, page_id, target_id, address)


async def test_run_once_upserts_status(conn, sample, tmp_path, monkeypatch):
    script = make_fake_fping(tmp_path, monkeypatch, "up")
    svc = PingService(conn, fping_path=str(script))
    stats = await svc.run_once()

    assert stats.skipped is False
    assert stats.targets == 1
    assert stats.alive == 1
    assert stats.failed == 0
    row = status.get_status(conn, sample["address_id"])
    assert row["alive"] == 1
    assert row["last_avg_ms"] == 1.5
    assert status.events_for(conn, sample["address_id"]) == []


async def test_run_once_down(conn, sample, tmp_path, monkeypatch):
    script = make_fake_fping(tmp_path, monkeypatch, "down")
    svc = PingService(conn, fping_path=str(script))
    stats = await svc.run_once()
    assert stats.failed == 1
    assert status.get_status(conn, sample["address_id"])["alive"] == 0


async def test_partial_loss_is_alive(conn, sample, tmp_path, monkeypatch):
    script = make_fake_fping(tmp_path, monkeypatch, "partial")
    svc = PingService(conn, fping_path=str(script))
    await svc.run_once()
    assert status.get_status(conn, sample["address_id"])["alive"] == 1


async def test_transition_writes_one_interval(conn, sample, tmp_path, monkeypatch):
    script = make_fake_fping(tmp_path, monkeypatch, "up")
    svc = PingService(conn, fping_path=str(script))
    await svc.run_once()
    monkeypatch.setenv("FAKE_MODE", "down")
    stats = await svc.run_once()

    events = status.events_for(conn, sample["address_id"])
    assert len(events) == 1
    assert events[0]["state"] == "up"
    assert len(stats.changes) == 1
    assert stats.changes[0].to_alive is False


async def test_missing_result_treated_as_down(conn, sample, tmp_path, monkeypatch):
    # Скрипт ничего не печатает (аналог DNS-ошибки, когда строки нет).
    script = tmp_path / "fping"
    script.write_text("#!/bin/sh\nexit 2\n")
    script.chmod(0o755)
    svc = PingService(conn, fping_path=str(script))
    stats = await svc.run_once()
    assert stats.failed == 1
    assert status.get_status(conn, sample["address_id"])["alive"] == 0


async def test_run_once_no_targets(conn, tmp_path, monkeypatch):
    script = make_fake_fping(tmp_path, monkeypatch)
    svc = PingService(conn, fping_path=str(script))
    stats = await svc.run_once()
    assert stats.skipped is True
    assert stats.targets == 0


async def test_same_ip_on_two_pages_polled_once(conn, tmp_path, monkeypatch):
    p1 = hosts.create_page(conn, "p1")
    p2 = hosts.create_page(conn, "p2")
    t1 = hosts.create_target(conn, p1)
    t2 = hosts.create_target(conn, p2)
    a1 = hosts.create_address(conn, p1, t1, "10.0.0.1")
    a2 = hosts.create_address(conn, p2, t2, "10.0.0.1")

    calls = {"n": 0}

    async def runner(targets, **kwargs):
        calls["n"] += 1
        assert targets == ["10.0.0.1"]
        from pinger import fping as fping_mod

        return fping_mod.parse_output(
            "10.0.0.1 : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1/1/1\n"
        )

    svc = PingService(conn, runner=runner)
    stats = await svc.run_once()
    assert calls["n"] == 1
    assert stats.targets == 1
    assert stats.alive == 2  # оба address_id получили статус
    assert status.get_status(conn, a1)["alive"] == 1
    assert status.get_status(conn, a2)["alive"] == 1


async def test_max_targets_truncates(conn, sample, tmp_path, monkeypatch):
    for i in range(5):
        add_address(conn, sample["page_id"], sample["target_id"], f"10.0.9.{i}")
    settings.update(conn, {"max_targets": 2})
    script = make_fake_fping(tmp_path, monkeypatch)
    svc = PingService(conn, fping_path=str(script))
    stats = await svc.run_once()
    assert stats.targets == 2


async def test_fping_error_does_not_crash(conn, sample, monkeypatch):
    async def broken_runner(targets, **kwargs):
        from pinger import fping as fping_mod

        raise fping_mod.FpingError("boom")

    svc = PingService(conn, runner=broken_runner)
    stats = await svc.run_once()
    assert stats.skipped is True
    assert status.get_status(conn, sample["address_id"]) is None


async def test_run_forever_stops_immediately_when_stopped(conn, sample):
    svc = PingService(conn, runner=lambda *a, **k: None)
    svc.stop()
    await asyncio.wait_for(svc.run_forever(), timeout=2)
    assert svc.stopped


async def test_run_forever_round_then_stop(conn, sample, tmp_path, monkeypatch):
    script = make_fake_fping(tmp_path, monkeypatch)
    holder = {}

    async def runner(targets, **kwargs):
        from pinger import fping as fping_mod

        holder["svc"].stop()
        return fping_mod.parse_output(
            f"{targets[0]} : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1/1/1\n"
        )

    svc = PingService(conn, runner=runner)
    holder["svc"] = svc
    settings.update(conn, {"round_interval_s": 30})
    await asyncio.wait_for(svc.run_forever(), timeout=5)
    assert svc.stopped
    assert status.get_status(conn, sample["address_id"])["alive"] == 1