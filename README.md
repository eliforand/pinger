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
### systemd (без Docker)

Для работы нужны `fping` (пакет `fping`) и виртуальное окружение проекта:

```bash
sudo apt-get install -y fping   # Debian/Ubuntu
make install                    # uv sync -> .venv
make service-env                # создать .env из примера (если ещё нет)
sudo make service-install       # отрендерить и установить юниты
sudo make service-enable        # автозапуск (по желанию)
sudo make service-start
```

Устанавливаются два юнита:

- `pinger.service` — сервис пинга (`python -m pinger`), получает `CAP_NET_RAW`
  для ICMP-сокетов `fping`;
- `pinger-web.service` — веб-интерфейс (`uvicorn pinger.web:app`).

Оба читают `.env` проекта и пишут БД в `./data`. Переопределить пути и порт
можно переменными `make`: `make service-install DATA_DIR=/var/lib/pinger
WEB_PORT=9000 ENV_FILE=/etc/pinger/pinger.env`. Управление: `make
service-{start,stop,restart,status,logs}`, удаление — `make service-uninstall`.
