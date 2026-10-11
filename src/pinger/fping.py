"""Запуск ``fping`` и парсинг его вывода.

С ``-q`` fping печатает результаты каждого адреса в **stderr** (stdout пуст):
``addr : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1.2/1.5/1.8``.

Парсер :func:`parse_output` — чистая функция и тестируется отдельно от запуска.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
from dataclasses import dataclass

#: Запас к таймауту процесса на запуск, резолв DNS и т.п.
PROCESS_TIMEOUT_RESERVE_S = 5.0

_RESULT_RE = re.compile(
    r"^(?P<address>\S+)\s*:\s*"
    r"xmt/rcv/%loss\s*=\s*(?P<sent>\d+)/(?P<received>\d+)/(?P<loss>\d+(?:\.\d+)?)%"
    r"(?:,\s*min/avg/max\s*=\s*"
    r"(?P<min>\d+(?:\.\d+)?)/(?P<avg>\d+(?:\.\d+)?)/(?P<max>\d+(?:\.\d+)?)"
    r")?\s*$"
)


class FpingError(RuntimeError):
    """fping недоступен или завершился с сетевым сбоем/таймаутом."""


@dataclass(frozen=True)
class PingResult:
    """Результат опроса одного адреса за раунд."""

    address: str
    sent: int
    received: int
    loss_pct: float
    min_ms: float | None
    avg_ms: float | None
    max_ms: float | None
    alive: bool
    raw: str


def parse_output(text: str) -> list[PingResult]:
    """Разобрать вывод fping. Нераспознанные строки игнорируются."""
    results: list[PingResult] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _RESULT_RE.match(line)
        if not match:
            continue
        received = int(match.group("received"))
        min_ms = match.group("min")
        avg_ms = match.group("avg")
        max_ms = match.group("max")
        results.append(
            PingResult(
                address=match.group("address"),
                sent=int(match.group("sent")),
                received=received,
                loss_pct=float(match.group("loss")),
                min_ms=float(min_ms) if min_ms is not None else None,
                avg_ms=float(avg_ms) if avg_ms is not None else None,
                max_ms=float(max_ms) if max_ms is not None else None,
                alive=received > 0,
                raw=line,
            )
        )
    return results


def process_timeout_s(packets: int, interval_ms: int, timeout_ms: int) -> float:
    """Таймаут процесса по формуле из плана + запас."""
    per_target_ms = (packets - 1) * max(interval_ms, timeout_ms) + timeout_ms
    return per_target_ms / 1000.0 + PROCESS_TIMEOUT_RESERVE_S


def build_command(
    *,
    packets: int,
    interval_ms: int,
    timeout_ms: int,
) -> list[str]:
    """Аргументы fping для батч-режима (цели читаются из stdin, ``-f -``)."""
    return [
        "fping",
        "-c",
        str(packets),
        "-p",
        str(interval_ms),
        "-t",
        str(timeout_ms),
        "-q",
        "-f",
        "-",
    ]


def ensure_available(fping_path: str | None = None) -> str:
    """Проверить наличие fping; вернуть путь к исполняемому файлу."""
    path = fping_path or shutil.which("fping")
    if not path:
        raise FpingError(
            "fping не найден в PATH. Установите fping (например, `apt install fping`)."
        )
    return path
def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Убить процесс и его группу (запускается с ``start_new_session``)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # уже завершился
        proc.kill()


async def run(
    targets: list[str],
    *,
    packets: int,
    interval_ms: int,
    timeout_ms: int,
    fping_path: str | None = None,
) -> list[PingResult]:
    """Опросить адреса одним батчем fping и вернуть разобранные результаты."""
    path = ensure_available(fping_path)
    if not targets:
        return []

    cmd = build_command(
        packets=packets, interval_ms=interval_ms, timeout_ms=timeout_ms
    )
    cmd[0] = path
    payload = ("\n".join(targets) + "\n").encode()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    timeout = process_timeout_s(packets, interval_ms, timeout_ms)
    task = asyncio.ensure_future(proc.communicate(input=payload))
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task in done:
        stdout, stderr = task.result()
    else:
        # fping завис: убиваем всю группу процессов, иначе дочерние процессы
        # (например, sleep/DNS) держат пайпы и communicate не завершится.
        _kill_process_group(proc)
        try:
            await asyncio.wait_for(task, timeout=PROCESS_TIMEOUT_RESERVE_S)
        except asyncio.TimeoutError:  # pragma: no cover - защитная ветка
            task.cancel()
        await proc.wait()
        raise FpingError(f"fping не ответил за {timeout:.1f} с")

    # Код возврата fping (0/1/2) не определяет доступность — только парсинг.
    text = (stderr + b"\n" + stdout).decode(errors="replace")
    return parse_output(text)