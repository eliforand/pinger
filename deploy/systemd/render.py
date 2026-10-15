#!/usr/bin/env python3
"""Рендер systemd-юнитов pinger из ``*.service.in``.

Скрипт подставляет значения (путь к проекту, venv-python, порт и т.п.)
в шаблоны и пишет готовые unit-файлы в выходной каталог. Его вызывает
``make service-install``, но он же удобен и для тестов.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATES = HERE

#: шаблон -> имя готового файла
UNITS: dict[str, str] = {
    "pinger.service.in": "pinger.service",
    "pinger-web.service.in": "pinger-web.service",
}

_PLACEHOLDER = re.compile(r"@([A-Z_]+)@")


class RenderError(RuntimeError):
    """Не удалось отрендерить шаблон."""


def render(text: str, values: dict[str, str]) -> str:
    """Подставить ``@NAME@``-плейсхолдеры и проверить, что все известны."""
    missing: set[str] = set()

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            missing.add(name)
            return match.group(0)
        return values[name]

    rendered = _PLACEHOLDER.sub(_sub, text)
    if missing:
        raise RenderError(
            "не заданы значения для плейсхолдеров: " + ", ".join(sorted(missing))
        )
    return rendered


def render_all(
    values: dict[str, str], out_dir: Path, templates_dir: Path = DEFAULT_TEMPLATES
) -> list[Path]:
    """Отрендерить все юниты в ``out_dir``; вернуть записанные пути."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for template_name, unit_name in UNITS.items():
        template = templates_dir / template_name
        text = template.read_text(encoding="utf-8")
        target = out_dir / unit_name
        target.write_text(render(text, values), encoding="utf-8")
        written.append(target)
    return written


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        default=str(HERE.parent.parent),
        help="каталог проекта (по умолчанию — родитель deploy/systemd)",
    )
    parser.add_argument("--service-user", required=True)
    parser.add_argument("--service-group", required=True)
    parser.add_argument("--python", required=True, help="путь к python из venv")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--web-host", default="0.0.0.0")
    parser.add_argument("--web-port", default="8000")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--templates-dir", default=str(DEFAULT_TEMPLATES), help=argparse.SUPPRESS
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    values = {
        "PROJECT_DIR": args.project_dir,
        "SERVICE_USER": args.service_user,
        "SERVICE_GROUP": args.service_group,
        "PYTHON": args.python,
        "DATA_DIR": args.data_dir,
        "ENV_FILE": args.env_file,
        "WEB_HOST": args.web_host,
        "WEB_PORT": args.web_port,
    }
    try:
        written = render_all(
            values, Path(args.out_dir), Path(args.templates_dir)
        )
    except RenderError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
