"""Цикл раундов опроса и graceful shutdown сервиса пинга."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from . import fping as fping_mod
from . import hosts, settings as settings_mod, status as status_mod
from .status import StateChange, StatusUpdate

logger = logging.getLogger("pinger.service")


@dataclass
class RoundStats:
    """Итоги одного раунда (для логов и тестов)."""

    targets: int = 0
    alive: int = 0
    failed: int = 0
    duration_s: float = 0.0
    changes: list[StateChange] = field(default_factory=list)
    skipped: bool = False


class PingService:
    """Долгоживущий процесс: раунд fping -> upsert статусов -> пауза."""

    def __init__(
        self,
        conn,
        *,
        fping_path: str | None = None,
        runner=fping_mod.run,
        clock=time.monotonic,
    ):
        self.conn = conn
        self.fping_path = fping_path
        self.runner = runner
        self.clock = clock
        self._stop = asyncio.Event()

    # --- управление жизненным циклом ------------------------------------

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> None:
        """Запросить остановку после текущего раунда."""
        self._stop.set()

    async def wait_stopped(self) -> None:
        await self._stop.wait()

    def install_signal_handlers(self) -> None:
        import signal

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:  # pragma: no cover - Windows
                signal.signal(sig, lambda *_: self.stop())

    # --- раунд -----------------------------------------------------------

    async def run_once(self) -> RoundStats:
        """Выполнить один раунд опроса и применить результаты."""
        started = self.clock()
        cfg = settings_mod.load(self.conn)
        targets = hosts.enabled_probe_targets(self.conn)
        if not targets:
            logger.info("нет включённых адресов для опроса")
            return RoundStats(skipped=True, duration_s=self.clock() - started)

        if len(targets) > cfg.max_targets:
            logger.warning(
                "целей %d больше лимита max_targets=%d, лишние пропущены",
                len(targets),
                cfg.max_targets,
            )
            targets = targets[: cfg.max_targets]

        # Один IP может стоять на разных страницах — опрашиваем один раз.
        by_address: dict[str, list[int]] = {}
        for target in targets:
            by_address.setdefault(target["address"], []).append(
                int(target["address_id"])
            )

        try:
            results = await self.runner(
                list(by_address),
                packets=cfg.packets,
                interval_ms=cfg.interval_ms,
                timeout_ms=cfg.timeout_ms,
                fping_path=self.fping_path,
            )
        except fping_mod.FpingError:
            logger.exception("ошибка запуска fping, раунд пропущен")
            return RoundStats(
                targets=len(by_address),
                duration_s=self.clock() - started,
                skipped=True,
            )
        except Exception:  # сетевой/непредвиденный сбой — не роняем сервис
            logger.exception("непредвиденная ошибка раунда, раунд пропущен")
            return RoundStats(
                targets=len(by_address),
                duration_s=self.clock() - started,
                skipped=True,
            )

        result_by_address = {r.address: r for r in results}
        updates: list[StatusUpdate] = []
        for address, address_ids in by_address.items():
            result = result_by_address.get(address)
            # Нет строки в выводе (например, DNS-ошибка) — считаем недоступным.
            alive = bool(result.alive) if result is not None else False
            avg_ms = result.avg_ms if result is not None else None
            for address_id in address_ids:
                updates.append(StatusUpdate(address_id, alive, avg_ms))

        changes = status_mod.apply_round(self.conn, updates)

        stats = RoundStats(
            targets=len(by_address),
            alive=sum(1 for u in updates if u.alive),
            failed=sum(1 for u in updates if not u.alive),
            duration_s=self.clock() - started,
            changes=changes,
        )
        for change in changes:
            logger.info(
                "переход address_id=%d: %s -> %s (интервал %s..%s, %d раундов)",
                change.address_id,
                "up" if change.from_alive else "down",
                "up" if change.to_alive else "down",
                change.started_at,
                change.ended_at,
                change.probes,
            )
        logger.info(
            "раунд: целей=%d up=%d down=%d за %.2f с",
            stats.targets,
            stats.alive,
            stats.failed,
            stats.duration_s,
        )
        return stats

    async def run_forever(self) -> None:
        """Крутить раунды до `stop()`, выдерживая паузу между раундами."""
        logger.info("сервис пинга запущен")
        try:
            while not self._stop.is_set():
                round_started = self.clock()
                await self.run_once()
                if self._stop.is_set():
                    break
                cfg = settings_mod.load(self.conn)
                delay = max(
                    0.0,
                    cfg.round_interval_s - (self.clock() - round_started),
                )
                await self._wait(delay)
        finally:
            logger.info("сервис пинга остановлен")

    async def _wait(self, seconds: float) -> None:
        """Пауза, прерываемая `stop()`."""
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass