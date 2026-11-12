#!/usr/bin/env python3
"""[QuadRix] Мост GUI ↔ CLI-клиент + сетевой поток (Gameplay PART 3).

Здесь всё необходимое, чтобы GUI-экран игры подключился к серверу **не
блокируя рендер** и получал от него реальный мир. Это порт той части
Horizon, где титульный экран уходит в GameScreen на соединении с сервером:

    * ``horizon-client/src/title.rs`` (``Action::Connect``) →
      ``game.rs::connect_server_with_options`` →
      ``game/remote.rs::join_server`` — экран ``ConnectScreen`` запускает
      сетевой поток (``net.rs``), а окно тем временем уже показывает
      ``Screen::Playing`` (``join_server`` ставит ``self.screen = Playing``
      до прихода первого пакета);
    * ``game/remote.rs::poll_remote``/``handle_packet`` — чтение пакетов и
      разбор состояния мира в игровом потоке.

В QuadRix роль ``net.rs`` играет :class:`quadrix.Client` из ``quadrix.py``
(handshake → login → configuration → play уже порттированы).  ``Client``
синхронный, поэтому:

  * **подключение** (``prepare``…``enter_play``) и **непрерывное чтение**
    пакетов идут в отдельном демон-потоке (:class:`RemoteConnection`);
  * **тик** клиента (``Client.tick``: движение + ``sync_client_to_server``)
    остаётся на игровом потоке — ``GameScreen.update`` вызывает его 20 Гц,
    ровно как требует control-сервер (AGENTS.md: движение только через
    ``Client.tick``).

Поток и игровой поток делят сокет: чтение — в потоке, запись — в игровом
(и в самом :class:`Client` из обработчика ``KeepAlive``).  Чтобы кадры
записи не перемешались, ``Client._send`` защищён замком (см. ``quadrix.py``).
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

__all__ = ["RemoteConnection", "default_client_factory", "load_entry"]

#: Корень репозитория: quadrix/render/remote.py -> ../..
ROOT = Path(__file__).resolve().parents[2]

#: Загруженный по пути модуль ``quadrix.py`` (entry point, не пакет).
_ENTRY: Optional[ModuleType] = None


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] remote: " + message)


def load_entry() -> ModuleType:
    """Загрузить ``quadrix.py`` по пути (как это делают тесты).

    ``quadrix.py`` — исполняемый скрипт, а не модуль пакета, поэтому
    импортировать его по имени нельзя.  Загружаем один раз и запоминаем.
    """
    global _ENTRY
    if _ENTRY is None:
        spec = importlib.util.spec_from_file_location(
            "quadrix_entry_remote", ROOT / "quadrix.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            raise RuntimeError("не удалось загрузить quadrix.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ENTRY = module
    return _ENTRY


def default_client_factory(
    host: str,
    port: int,
    name: str = "Player",
    **kwargs: Any,
) -> Any:
    """Собрать :class:`Client` для GUI (фабрика по умолчанию).

    GUI подставляет её в ``App.client_factory``; тесты — свой фейк.
    """
    entry = load_entry()
    return entry.Client(host=host, port=int(port), name=name, **kwargs)


class RemoteConnection:
    """Подключение ``Client`` в отдельном потоке + чтение пакетов.

    Порт ``net.rs`` (сетевой поток) + ``ConnectScreen.startConnecting``:
    окно не ждёт сеть.  :meth:`connect` — синхронный путь (тесты и
    worker-поток), :meth:`start` — запускает поток.

    Атрибуты состояния:
      * ``connected`` — ``enter_play`` прошёл (можно тикать);
      * ``error`` — исключение подключения/чтения (иначе ``None``);
      * ``client`` — подключённый :class:`Client` (или ``None``).
    """

    #: Сколько ждать между чтениями, если пакетов нет (секунды).
    READ_TIMEOUT: float = 0.05

    def __init__(
        self,
        client: Any,
        *,
        on_disconnect: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        self.client = client
        self.connected = False
        self.error: Optional[BaseException] = None
        self.running = False
        self._on_disconnect = on_disconnect
        self._thread: Optional[threading.Thread] = None

    # -- синхронный путь (тесты) ----------------------------------------

    def connect(self) -> Any:
        """Подключиться синхронно: handshake → login → config → play.

        Порт ``join_server`` в сети: тот же порядок, что в ``quadrix.py``.
        Управление с клавиатуры GUI отключено (инпут даёт ``GameScreen``),
        поэтому stdin-поток ``Client._start_input`` не поднимаем.
        """
        client = self.client
        # GUI сам тикает клиента: интерактивный stdin не нужен.  Ставим
        # заглушку ДО enter_play, иначе он запустит stdin-поток (TTY).
        client._start_input = lambda: None  # type: ignore[method-assign]
        client.prepare()
        client.connect()
        client.handshake()
        client.login()
        client.configure()
        client.enter_play()
        self.connected = True
        _log(f"подключено: {getattr(client, 'host', '?')}:{getattr(client, 'port', '?')}")
        return client

    # -- поток -----------------------------------------------------------

    def start(self) -> "RemoteConnection":
        """Запустить подключение и чтение пакетов в фоновом потоке."""
        self.running = True
        self._thread = threading.Thread(
            target=self._run, name="quadrix-remote", daemon=True
        )
        self._thread.start()
        return self

    def _run(self) -> None:
        """Тело потока: подключиться, затем читать пакеты до остановки."""
        try:
            self.connect()
        except BaseException as exc:  # noqa: BLE001 — сообщаем наверх
            self.error = exc
            _log(f"подключение не удалось: {exc}")
            self._notify(exc)
            return
        while self.running:
            try:
                self.client.read_one()
            except BaseException as exc:  # noqa: BLE001 — разрыв/ошибка
                self.error = exc
                _log(f"соединение прервано: {exc}")
                break
        if self.error is not None:
            self._notify(self.error)

    def _notify(self, exc: BaseException) -> None:
        if self._on_disconnect is not None:
            self._on_disconnect(exc)

    def stop(self) -> None:
        """Остановить поток и закрыть соединение (идемпотентно)."""
        self.running = False
        self.connected = False
        client = self.client
        if client is not None:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001 — закрытие не критично
                _log(f"ошибка закрытия: {exc}")
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
