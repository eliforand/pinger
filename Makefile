# pinger — Makefile
# Все цели работают через uv. Справка: make help

UV      ?= uv
PYTEST  ?= $(UV) run pytest
TEST    ?= tests/

.PHONY: help install sync test test-one run web docker-build docker-up docker-down docker-logs clean check

help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

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

check: ## Тесты + проверка импорта веб-приложения
	$(PYTEST) -q
	$(UV) run python -c "from pinger.web.app import app; print('web ok')"

clean: ## Удалить кэши и артефакты сборки
	rm -rf .pytest_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
