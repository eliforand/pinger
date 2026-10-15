from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYSTEMD = ROOT / "deploy" / "systemd"
INSTALL = SYSTEMD / "install.sh"
RENDER = SYSTEMD / "render.py"

VALUES = {
    "PROJECT_DIR": "/srv/pinger",
    "SERVICE_USER": "pinger",
    "SERVICE_GROUP": "pinger",
    "PYTHON": "/srv/pinger/.venv/bin/python",
    "DATA_DIR": "/var/lib/pinger",
    "ENV_FILE": "/etc/pinger/pinger.env",
    "WEB_HOST": "127.0.0.1",
    "WEB_PORT": "9000",
}


def _load_render():
    spec = importlib.util.spec_from_file_location("pinger_systemd_render", RENDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_templates_exist():
    for name in ("pinger.service.in", "pinger-web.service.in", "pinger.env.example"):
        assert (SYSTEMD / name).is_file()


def test_render_substitutes_all_placeholders(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--project-dir",
            VALUES["PROJECT_DIR"],
            "--service-user",
            VALUES["SERVICE_USER"],
            "--service-group",
            VALUES["SERVICE_GROUP"],
            "--python",
            VALUES["PYTHON"],
            "--data-dir",
            VALUES["DATA_DIR"],
            "--env-file",
            VALUES["ENV_FILE"],
            "--web-host",
            VALUES["WEB_HOST"],
            "--web-port",
            VALUES["WEB_PORT"],
            "--out-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    service = (tmp_path / "pinger.service").read_text(encoding="utf-8")
    web = (tmp_path / "pinger-web.service").read_text(encoding="utf-8")

    assert "@" not in service
    assert "@" not in web
    assert f"ExecStart={VALUES['PYTHON']} -m pinger" in service
    assert "AmbientCapabilities=CAP_NET_RAW" in service
    assert f"Environment=PINGER_DB={VALUES['DATA_DIR']}/pinger.db" in service
    assert f"EnvironmentFile=-{VALUES['ENV_FILE']}" in service
    assert (
        f"ExecStart={VALUES['PYTHON']} -m uvicorn pinger.web:app "
        f"--host {VALUES['WEB_HOST']} --port {VALUES['WEB_PORT']}" in web
    )
    assert "WantedBy=multi-user.target" in service
    assert "WantedBy=multi-user.target" in web
    assert str(tmp_path / "pinger.service") in result.stdout


def test_render_rejects_unknown_placeholder():
    module = _load_render()
    with pytest.raises(module.RenderError):
        module.render("Description=@NOPE@", {})


def _run_install(tmp_path, mode, **overrides):
    env = os.environ.copy()
    env.update(
        {
            "PROJECT_DIR": str(ROOT),
            "PYTHON": sys.executable,
            "DATA_DIR": str(tmp_path / "data"),
            "ENV_FILE": str(tmp_path / ".env"),
            "SYSTEMD_DIR": str(tmp_path / "units"),
            "SUDO": "",
            "DAEMON_RELOAD": "0",
            "ENABLE": "0",
        }
    )
    for key, value in overrides.items():
        env[key] = str(value)
    return subprocess.run(
        [str(INSTALL), mode], env=env, capture_output=True, text=True
    )


def test_install_writes_units_and_uninstall_removes(tmp_path):
    result = _run_install(tmp_path, "install")
    assert result.returncode == 0, result.stderr

    units = tmp_path / "units"
    assert (units / "pinger.service").is_file()
    assert (units / "pinger-web.service").is_file()
    assert (units / "pinger.service").stat().st_mode & 0o777 == 0o644
    assert str(ROOT) in (units / "pinger.service").read_text(encoding="utf-8")
    assert (tmp_path / "data").is_dir()

    result = _run_install(tmp_path, "uninstall")
    assert result.returncode == 0, result.stderr
    assert not (units / "pinger.service").exists()
    assert not (units / "pinger-web.service").exists()


def test_install_forwards_overrides(tmp_path):
    result = _run_install(
        tmp_path,
        "install",
        SERVICE_USER="alice",
        SERVICE_GROUP="ops",
        WEB_PORT="9999",
        WEB_HOST="10.0.0.1",
        DATA_DIR="/srv/data",
    )
    assert result.returncode == 0, result.stderr
    web = (tmp_path / "units" / "pinger-web.service").read_text(encoding="utf-8")
    assert "User=alice" in web
    assert "Group=ops" in web
    assert "--host 10.0.0.1 --port 9999" in web
    assert "PINGER_DB=/srv/data/pinger.db" in web


def test_install_requires_existing_python(tmp_path):
    result = _run_install(tmp_path, "install", PYTHON=str(tmp_path / "missing-python"))
    assert result.returncode == 1
    assert "не найден python venv" in result.stderr


def test_install_rejects_bad_mode(tmp_path):
    result = _run_install(tmp_path, "frobnicate")
    assert result.returncode == 2


def test_help_lists_service_targets():
    result = subprocess.run(
        ["make", "help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for target in (
        "service-install",
        "service-uninstall",
        "service-start",
        "service-stop",
        "service-restart",
        "service-status",
        "service-logs",
        "service-env",
    ):
        assert target in result.stdout

def test_install_defaults_to_sudo_user(tmp_path):
    """`sudo make service-install` должен ставить юниты от исходного юзера."""
    result = _run_install(tmp_path, "install", SUDO_USER="root")
    assert result.returncode == 0, result.stderr
    service = (tmp_path / "units" / "pinger.service").read_text(encoding="utf-8")
    assert "User=root" in service
    assert "Group=root" in service
