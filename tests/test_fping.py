from __future__ import annotations

import pytest

from pinger import fping

ALIVE_OUTPUT = "10.0.0.1 : xmt/rcv/%loss = 3/3/0%, min/avg/max = 0.072/0.096/0.126\n"

DOWN_OUTPUT = "10.0.0.2 : xmt/rcv/%loss = 3/0/100%\n"

MIXED_OUTPUT = ALIVE_OUTPUT + DOWN_OUTPUT


def test_parse_output_alive():
    results = fping.parse_output(ALIVE_OUTPUT)
    assert len(results) == 1
    r = results[0]
    assert r.address == "10.0.0.1"
    assert (r.sent, r.received) == (3, 3)
    assert r.loss_pct == 0.0
    assert (r.min_ms, r.avg_ms, r.max_ms) == (0.072, 0.096, 0.126)
    assert r.alive is True
    assert r.raw == ALIVE_OUTPUT.strip()


def test_parse_output_down():
    results = fping.parse_output(DOWN_OUTPUT)
    assert len(results) == 1
    r = results[0]
    assert r.address == "10.0.0.2"
    assert (r.sent, r.received) == (3, 0)
    assert r.loss_pct == 100.0
    assert r.min_ms is None and r.avg_ms is None and r.max_ms is None
    assert r.alive is False


def test_parse_output_mixed():
    results = fping.parse_output(MIXED_OUTPUT)
    assert [r.address for r in results] == ["10.0.0.1", "10.0.0.2"]
    assert [r.alive for r in results] == [True, False]


def test_parse_output_partial_loss_still_alive():
    # Ответил хотя бы 1 пакет — адрес доступен.
    results = fping.parse_output(
        "10.0.0.5 : xmt/rcv/%loss = 3/1/66%, min/avg/max = 1.0/1.0/1.0\n"
    )
    assert results[0].alive is True
    assert results[0].loss_pct == 66.0


def test_parse_output_ignores_noise():
    text = (
        "ICMP Host Unreachable from 10.0.0.1\n"
        "\n"
        "not a result line\n"
        "10.0.0.9 : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1/2/3\n"
    )
    results = fping.parse_output(text)
    assert len(results) == 1
    assert results[0].address == "10.0.0.9"


def test_parse_output_empty():
    assert fping.parse_output("") == []


def test_process_timeout_s():
    # (3-1)*max(200,1000) + 1000 = 3000 мс + запас 5 с
    timeout = fping.process_timeout_s(3, 200, 1000)
    assert timeout == pytest.approx(3.0 + fping.PROCESS_TIMEOUT_RESERVE_S)


def test_build_command():
    cmd = fping.build_command(packets=3, interval_ms=200, timeout_ms=1000)
    assert cmd == [
        "fping",
        "-c",
        "3",
        "-p",
        "200",
        "-t",
        "1000",
        "-q",
        "-f",
        "-",
    ]
    assert "-6" not in cmd


def test_ensure_available_missing(monkeypatch):
    monkeypatch.setattr(fping.shutil, "which", lambda name: None)
    with pytest.raises(fping.FpingError):
        fping.ensure_available()


def test_ensure_available_explicit_path():
    assert fping.ensure_available("/usr/bin/fping") == "/usr/bin/fping"


def _write_fake_fping(tmp_path, body: str = None):
    script = tmp_path / "fping"
    script.write_text(
        body
        or (
            "#!/bin/sh\n"
            "while IFS= read -r line; do\n"
            '  [ -z "$line" ] && continue\n'
            '  if [ "$line" = "10.0.0.1" ]; then\n'
            '    echo "$line : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1.0/1.5/2.0" >&2\n'
            "  else\n"
            '    echo "$line : xmt/rcv/%loss = 3/0/100%" >&2\n'
            "  fi\n"
            "done\n"
        )
    )
    script.chmod(0o755)
    return script


async def test_run_with_fake_fping_path(tmp_path):
    script = _write_fake_fping(tmp_path)
    results = await fping.run(
        ["10.0.0.1", "10.0.0.2"],
        packets=3,
        interval_ms=200,
        timeout_ms=1000,
        fping_path=str(script),
    )
    by_addr = {r.address: r for r in results}
    assert by_addr["10.0.0.1"].alive is True
    assert by_addr["10.0.0.2"].alive is False


async def test_run_with_fake_fping_in_path(tmp_path, monkeypatch):
    script = _write_fake_fping(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
    results = await fping.run(
        ["10.0.0.1"], packets=1, interval_ms=1, timeout_ms=1
    )
    assert len(results) == 1
    assert results[0].alive is True


async def test_run_empty_targets_returns_empty():
    assert await fping.run([], packets=1, interval_ms=1, timeout_ms=1) == []


async def test_run_timeout(tmp_path, monkeypatch):
    script = _write_fake_fping(tmp_path, body="#!/bin/sh\nsleep 5\n")
    monkeypatch.setattr(fping, "PROCESS_TIMEOUT_RESERVE_S", 0.1)
    with pytest.raises(fping.FpingError):
        await fping.run(
            ["10.0.0.1"],
            packets=1,
            interval_ms=1,
            timeout_ms=1,
            fping_path=str(script),
        )