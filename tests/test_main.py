from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time

from pinger import db, hosts

FAKE_FPING = """#!/bin/sh
while IFS= read -r line; do
  [ -z "$line" ] && continue
  echo "$line : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1.0/1.5/2.0" >&2
done
"""


def _wait_status(dbfile, address_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        conn = sqlite3.connect(dbfile)
        try:
            row = conn.execute(
                "SELECT alive, checks_total FROM host_status WHERE address_id=?",
                (address_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            return row
        time.sleep(0.1)
    return None


def test_python_m_pinger_runs_round_and_stops(tmp_path):
    dbfile = tmp_path / "pinger.db"
    conn = db.init_db(path=dbfile)
    page_id = hosts.create_page(conn, "p")
    target_id = hosts.create_target(conn, page_id)
    address_id = hosts.create_address(conn, page_id, target_id, "10.0.0.1")
    conn.close()

    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "fping"
    script.write_text(FAKE_FPING)
    script.chmod(0o755)

    env = dict(os.environ)
    env["PINGER_DB"] = str(dbfile)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["PINGER_LOG_LEVEL"] = "INFO"

    proc = subprocess.Popen(
        [sys.executable, "-m", "pinger"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        row = _wait_status(dbfile, address_id)
        assert row is not None, "сервис не обновил статус"
        assert row[0] == 1

        proc.send_signal(signal.SIGTERM)
        output, _ = proc.communicate(timeout=10)
        assert proc.returncode == 0, output
        assert "остановлен" in output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()