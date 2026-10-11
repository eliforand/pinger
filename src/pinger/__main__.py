"""Сервис пинга: ``python -m pinger``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from . import db
from .service import PingService


def _configure_logging() -> None:
    level = os.environ.get("PINGER_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def serve(service: PingService) -> None:
    service.install_signal_handlers()
    await service.run_forever()


def main() -> int:
    _configure_logging()
    logger = logging.getLogger("pinger")
    conn = db.init_db()
    logger.info("база готова: %s", db.db_path())
    service = PingService(conn)
    try:
        asyncio.run(serve(service))
    except KeyboardInterrupt:  # pragma: no cover - дублирует SIGINT
        logger.info("прерывание с клавиатуры")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())