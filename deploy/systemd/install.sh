#!/usr/bin/env bash
# Установка/удаление systemd-юнитов pinger.
#
# Использование:
#   deploy/systemd/install.sh [install|uninstall]
#
# Переопределяемые переменные окружения:
#   PROJECT_DIR   каталог проекта        (по умолчанию — корень репозитория)
#   SERVICE_USER  пользователь сервисов  (по умолчанию — текущий)
#   SERVICE_GROUP группа сервисов        (по умолчанию — текущая)
#   PYTHON        python из venv         (по умолчанию $PROJECT_DIR/.venv/bin/python)
#   DATA_DIR      каталог с pinger.db    (по умолчанию $PROJECT_DIR/data)
#   ENV_FILE      EnvironmentFile        (по умолчанию $PROJECT_DIR/.env)
#   WEB_HOST      адрес веб-сервиса      (по умолчанию 0.0.0.0)
#   WEB_PORT      порт веб-сервиса       (по умолчанию 8000)
#   SYSTEMD_DIR   каталог юнитов         (по умолчанию /etc/systemd/system)
#   SUDO          префикс команд         (по умолчанию sudo; пусто — без прав)
#   ENABLE       1 — включить юниты в автозапуск
#   DAEMON_RELOAD 0 — не звать systemctl daemon-reload
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_DIR="${PROJECT_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
DATA_DIR="${DATA_DIR:-$PROJECT_DIR/data}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-8000}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SUDO="${SUDO-sudo}"
ENABLE="${ENABLE:-0}"
DAEMON_RELOAD="${DAEMON_RELOAD:-1}"

MODE="${1:-install}"

run() {
    if [ -n "$SUDO" ]; then
        # shellcheck disable=SC2086
        $SUDO "$@"
    else
        "$@"
    fi
}

units=(pinger.service pinger-web.service)

case "$MODE" in
    install)
        if [ ! -x "$PYTHON" ]; then
            echo "ошибка: не найден python venv: $PYTHON" >&2
            echo "подсказка: сначала выполните 'make install' или задайте PYTHON=..." >&2
            exit 1
        fi

tmp="$(mktemp -d)"
        trap 'rm -rf "$tmp"' EXIT

# Каталог с БД должен существовать: ReadWritePaths на него ссылается.
        if [ ! -d "$DATA_DIR" ]; then
            if ! mkdir -p "$DATA_DIR" 2>/dev/null; then
                if ! run install -d "$DATA_DIR" 2>/dev/null; then
                    echo "предупреждение: не удалось создать $DATA_DIR" >&2
                fi
            fi
        fi
        python3 "$SCRIPT_DIR/render.py" \
            --project-dir "$PROJECT_DIR" \
            --service-user "$SERVICE_USER" \
            --service-group "$SERVICE_GROUP" \
            --python "$PYTHON" \
            --data-dir "$DATA_DIR" \
            --env-file "$ENV_FILE" \
            --web-host "$WEB_HOST" \
            --web-port "$WEB_PORT" \
            --out-dir "$tmp"

        run install -d "$SYSTEMD_DIR"
        for unit in "${units[@]}"; do
            run install -m 0644 "$tmp/$unit" "$SYSTEMD_DIR/$unit"
            echo "установлен $SYSTEMD_DIR/$unit"
        done

        if [ "$DAEMON_RELOAD" = "1" ]; then
            run systemctl daemon-reload
        fi
        if [ "$ENABLE" = "1" ]; then
            run systemctl enable pinger.service pinger-web.service
        fi
        ;;
    uninstall)
        for unit in "${units[@]}"; do
            if [ -e "$SYSTEMD_DIR/$unit" ]; then
                run rm -f "$SYSTEMD_DIR/$unit"
                echo "удалён $SYSTEMD_DIR/$unit"
            fi
        done
        if [ "$DAEMON_RELOAD" = "1" ]; then
            run systemctl daemon-reload
        fi
        ;;
    *)
        echo "использование: $0 [install|uninstall]" >&2
        exit 2
        ;;
esac
