#!/usr/bin/env python3
"""Интеграционные тесты CLI-клиента quadrix.py (entry point).

Тест с реальным соединением опционален: если локальный Horizon LAN на
127.0.0.1:25565 не отвечает, он пропускается через
``pytest.mark.skipif``. Те части, которым сервер не нужен (загрузка
``.local``-данных, разбор CLI), проверяются всегда и дают сигнал даже
без запущенного сервера.

Поток реального теста повторяет Rust-порядок:
    connect -> handshake -> login -> configuration -> play
и ждёт первый ``PlayerPosition`` (сервер телепортирует игрока при входе).
"""

from __future__ import annotations

import importlib.util
import socket
import time
from pathlib import Path
from types import ModuleType

import pytest

#: Корень репозитория: tests/integration/test_real_connection.py -> ../..
ROOT = Path(__file__).resolve().parents[2]

HOST = "127.0.0.1"
PORT = 25565
CONNECT_TIMEOUT = 0.5
PLAY_TIMEOUT = 15.0


def _load_entry() -> ModuleType:
    """Загрузить quadrix.py по пути (не как пакет ``quadrix``)."""
    spec = importlib.util.spec_from_file_location(
        "quadrix_entry", ROOT / "quadrix.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("не удалось загрузить quadrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Модуль entry point: Client, ClientError, ClientWorld, build_parser.
entry = _load_entry()


def _server_running(host: str = HOST, port: int = PORT) -> bool:
    """Есть ли слушающий сервер (socket.connect в 0.5 c таймауте)."""
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


#: Определяется один раз при импорте: этим управляет skipif ниже.
SERVER_RUNNING = _server_running()


def test_cli_help_lists_connection_options() -> None:
    """argparse обязан показывать --host, --port и --name."""
    parser = entry.build_parser()
    text = parser.format_help()
    assert "--host" in text
    assert "--port" in text
    assert "--name" in text


def test_client_prepare_loads_local_data() -> None:
    """Client.prepare читает .local и собирает motion/world/health."""
    client = entry.Client(host=HOST, port=PORT, name="TestPlayer")
    client.prepare()

    assert client.motion is not None
    # Без пришедших чанков мир отдаёт воздух.
    assert client.world.block(0, 0, 0) == "minecraft:air"
    assert client.health is not None
    assert client.health.health() == 20.0


@pytest.mark.skipif(
    not SERVER_RUNNING,
    reason="нет локального Horizon LAN на 127.0.0.1:25565",
)
def test_real_connection_reaches_play_and_position() -> None:
    """Полный путь до play и первый PlayerPosition."""
    client = entry.Client(host=HOST, port=PORT, name="TestPlayer")
    try:
        client.connect()
        client.handshake()
        client.login()
        client.configure()
        client.enter_play()

        # В тесте читаем пакеты блокирующе с запасом по времени.
        client.conn.set_read_timeout(5.0)
        deadline = time.monotonic() + PLAY_TIMEOUT
        while client.last_position is None and time.monotonic() < deadline:
            if not client.read_one():
                continue

        assert client.last_position is not None

        # Дальше тикаем: клиент должен получить чанки, отправить
        # PlayerLoaded и MovePlayerPos + ClientTickEnd. Раньше без
        # ClientTickEnd сервер отключал на втором пакете перемещения за
        # один тик (invalid_player_movement) — здесь это проверяется тем,
        # что ClientError не всплывает, а такты идут.
        deadline = time.monotonic() + PLAY_TIMEOUT
        while client.ticks < 30 and time.monotonic() < deadline:
            client.read_one()
            client.tick()

        assert client.chunks_seen > 0
        assert client.ticks >= 30
    finally:
        client.close()
