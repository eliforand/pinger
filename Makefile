# pinger — Makefile
# Все цели работают через uv. Справка: make help

UV      ?= uv
PYTEST  ?= $(UV) run pytest
TEST    ?= tests/

# --- systemd (см. deploy/systemd) ---------------------------------------
PROJECT_DIR   ?= $(CURDIR)
SERVICE_USER  ?= $(or $(SUDO_USER),$(shell id -un))
SERVICE_GROUP ?= $(shell id -gn $(SERVICE_USER))
DATA_DIR      ?= $(PROJECT_DIR)/data
ENV_FILE      ?= $(PROJECT_DIR)/.env
WEB_HOST      ?= 0.0.0.0
WEB_PORT      ?= 8000
SYSTEMD_DIR   ?= /etc/systemd/system
SUDO          ?= sudo
DAEMON_RELOAD ?= 1
ENABLE        ?= 0
SYSTEMD_ENV = PROJECT_DIR="$(PROJECT_DIR)" SERVICE_USER="$(SERVICE_USER)" \
	SERVICE_GROUP="$(SERVICE_GROUP)" DATA_DIR="$(DATA_DIR)" \
	ENV_FILE="$(ENV_FILE)" WEB_HOST="$(WEB_HOST)" WEB_PORT="$(WEB_PORT)" \
	SYSTEMD_DIR="$(SYSTEMD_DIR)" SUDO="$(SUDO)" \
	DAEMON_RELOAD="$(DAEMON_RELOAD)" ENABLE="$(ENABLE)"

.PHONY: help install sync test test-one run web docker-build docker-up docker-down docker-logs clean check \
	service-env service-install service-uninstall service-enable service-disable \
	service-start service-stop service-restart service-status service-logs

help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости (uv sync, включая dev-группу)
	$(UV) sync

sync: install ## Синоним install

test: ## Прогнать все тесты: make test
	$(PYTEST) -q

test-one: ## Прогнать один файл/тест: make test-one TEST=tests/test_fping.py
	$(PYTEST) $(TEST) -q

run: ## Запустить сервис пинга локально: make run
	PINGER_DB=data/pinger.db $(UV) run python -m pinger

web: ## Запустить веб локально: make web (http://localhost:8000)
	PINGER_DB=data/pinger.db SECRET_KEY=dev-secret $(UV) run uvicorn pinger.web:app --host 0.0.0.0 --port 8000

docker-build: ## Пересобрать образ: make docker-build
	docker compose build

docker-up: ## Собрать и поднять оба сервиса: make docker-up
	docker compose up -d --build

docker-down: ## Остановить и удалить контейнеры: make docker-down
	docker compose down

docker-logs: ## Логи сервисов: make docker-logs
	docker compose logs -f

# --- systemd -----------------------------------------------------------

service-env: ## Создать .env из примера (если ещё нет)
	@test -f "$(ENV_FILE)" || { cp deploy/systemd/pinger.env.example "$(ENV_FILE)"; echo "создан $(ENV_FILE)"; }

service-install: ## Установить systemd-юниты pinger (нужен sudo)
	@$(SYSTEMD_ENV) deploy/systemd/install.sh install

service-uninstall: ## Удалить systemd-юниты pinger
	@$(SYSTEMD_ENV) deploy/systemd/install.sh uninstall

service-enable: ## Включить юниты в автозапуск
	$(SUDO) systemctl enable pinger.service pinger-web.service

service-disable: ## Отключить юниты от автозапуска
	$(SUDO) systemctl disable pinger.service pinger-web.service

service-start: ## Запустить сервисы
	$(SUDO) systemctl start pinger.service pinger-web.service

service-stop: ## Остановить сервисы
	$(SUDO) systemctl stop pinger.service pinger-web.service

service-restart: ## Перезапустить сервисы
	$(SUDO) systemctl restart pinger.service pinger-web.service

service-status: ## Статус сервисов
	-$(SUDO) systemctl status --no-pager pinger.service pinger-web.service

service-logs: ## Смотреть логи сервисов (journalctl -f)
	$(SUDO) journalctl -f -u pinger.service -u pinger-web.service

check: ## Тесты + проверка импорта веб-приложения
	$(PYTEST) -q
	$(UV) run python -c "from pinger.web.app import app; print('web ok')"

clean: ## Удалить кэши и артефакты сборки
	rm -rf .pytest_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
