# pinger

Мониторинг доступности хостов.

## Установка

Docker (нужен `docker compose` v2):

```bash
cp .env.example .env   # при необходимости поправить WEB_PORT/SECRET_KEY
make docker-up         # собрать и запустить
```

Веб: `http://localhost:8000` (порт — `WEB_PORT` в `.env`), первый админ
создаётся на `/setup`. База — в `./data`.

Без Docker (Python 3.14, [`uv`](https://docs.astral.sh/uv/), `fping`):

```bash
make install
make run    # сервис пинга
make web    # веб на http://localhost:8000
```
