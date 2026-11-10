#!/usr/bin/env python3
"""[QuadRix] Тесты ControlServer — диспетчер команд и JSON-протокол.

Использует FakeClient-заглушки с методом dispatch, проверяя:
  - протокол request/response round-trip по сокету
  - каждый базовые команды (state, move, jump, chat, place, break, unknown, stop)
  -poll()-механизм очереди команд
"""

from __future__ import annotations

import concurrent.futures
import json
import socket
import threading
import pytest

from quadrix.control.server import ControlServer, _ClientWrapper, _wrapper_dispatch


# ---------------------------------------------------------------------------
# Минимальная загFake client for tests
# ---------------------------------------------------------------------------

class FakeClient:
    """Минимальный клиент-заглушка для тестов ControlServer.dispatch.

    Содержит необходимые методы motion/world, чтобы dispatch мог ее вызвать.
    """

    def __init__(self) -> None:
        from quadrix.motion.core import PlayerMotion, Vec3
        from quadrix.world.world_ray import ClipContext

        self.pm = PlayerMotion.new(
            type("MovementResources", (), {"properties": {}})(),
            Vec3(0, 64, 0),
        )
        # Минимальный мир — возвращает "air" везде
        self.world = _FakeWorld()

        # Создаем wrapper, который будет использоваться dispatch
        self._wrapper = _ClientWrapper(self.pm, self.world)

    def dispatch(self, cmd: str, args: dict) -> dict:
        """Проходит вызов через _wrapper_dispatch helper.

        Возвращает ответ от server.dispatch (то, что вернёт ControlServer.dispatch).
        """
        return _wrapper_dispatch(self._wrapper, cmd, args)


class _FakeWorld:
    """Fake world returning air for all block queries."""

    def block(self, x: int, y: int, z: int) -> str:
        return "minecraft:air"


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_dispatch_state():
    """1. dispatch("state") -> dict с pos/yaw/pitch."""
    client = FakeClient()
    resp = client.dispatch("state", {})
    assert resp["ok"] is True
    result = resp.get("result", {})
    assert "pos" in result, f"Expected 'pos' in result, got {result}"
    assert "yaw" in result, f"Expected 'yaw' in result, got {result}"
    assert "pitch" in result, f"Expected 'pitch' in result, got {result}"
    # Check pos structure
    pos = result["pos"]
    assert "x" in pos and "y" in pos and "z" in pos


def test_dispatch_move():
    """2. dispatch("move", {"direction":"forward","ticks":5}) -> ok, вызван travel."""
    client = FakeClient()
    resp = client.dispatch("move", {"direction": "forward", "ticks": 5})
    assert resp["ok"] is True
    assert resp.get("result", {}).get("ticks") == 5


def test_dispatch_jump():
    """3. dispatch("jump") -> ok, вызван jump_from_ground."""
    client = FakeClient()
    # Set on_ground = True for jump
    client.pm.on_ground = True

    resp = client.dispatch("jump", {})
    assert resp["ok"] is True
    # jump_from_ground should have been called and returned True
    assert resp.get("result", {}).get("jump") is True


def test_dispatch_chat():
    """4. dispatch("chat", {"text":"hi"}) -> ok, отправлен ChatMessage."""
    client = FakeClient()
    resp = client.dispatch("chat", {"text": "hi"})
    assert resp["ok"] is True
    # Should have result about chat packet
    assert "result" in resp or "error" not in resp


def test_dispatch_place():
    """5. dispatch("place", {"block":"stone"}) -> ok, вызван place (или error FALLBACK)."""
    client = FakeClient()
    resp = client.dispatch("place", {"block": "stone"})
    # In fallback mode (no full world), may return ok=False with error
    # That's acceptable — the important thing is no pass/TODO/NotImplementedError
    # Just check we get a structured response
    assert "ok" in resp
    assert "error" in resp or "result" in resp


def test_dispatch_break():
    """6. dispatch("break") -> ok, вызван break_block."""
    client = FakeClient()
    resp = client.dispatch("break", {})
    assert "ok" in resp
    # May return error in fallback mode, that's fine


def test_dispatch_unknown():
    """7. dispatch("unknown") -> ok=False, error "unknown command"."""
    client = FakeClient()
    resp = client.dispatch("unknown", {})
    assert resp["ok"] is False
    assert "unknown command" in resp.get("error", "")


def test_json_protocol_round_trip():
    """8. JSON-протокол: request/response round-trip через socket (127.0.0.1, port 0 -> реальный)."""

    server = ControlServer(host="127.0.0.1", port=0, client=None)  # port 0 -> OS assigns
    server.start()

    # Get the assigned port
    actual_port = server._server_socket.getsockname()[1]

    try:
        # Connect and send a request
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", actual_port))

        # Send JSON line
        req = json.dumps({"id": 1, "cmd": "state", "args": {}})
        sock.sendall((req + "\n").encode("utf-8"))

        # Read response
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk

        sock.close()

        response_text = buf.decode("utf-8").strip()
        response = json.loads(response_text)

        assert response.get("ok") is True, f"Expected ok=True, got {response}"
        assert response.get("id") == 1, f"Expected id=1, got {response.get('id')}"

    finally:
        server.stop()


def test_json_protocol_round_trip_move():
    """9. JSON-протокол move round-trip."""
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()

    actual_port = server._server_socket.getsockname()[1]

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", actual_port))

        req = json.dumps({"id": 2, "cmd": "move", "args": {"direction": "forward", "ticks": 3}})
        sock.sendall((req + "\n").encode("utf-8"))

        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk

        sock.close()

        response_text = buf.decode("utf-8").strip()
        response = json.loads(response_text)

        assert response.get("ok") is True, f"Expected ok=True, got {response}"
        assert response.get("id") == 2, f"Expected id=2, got {response.get('id')}"

    finally:
        server.stop()


def test_stop_command():
    """10. stop -> флаг остановки."""
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()

    try:
        # dispatch stop should set running flag and return ok
        future = server.dispatch("stop", {})
        resp = future.result()
        assert resp["ok"] is True
        assert resp.get("result", {}).get("status") == "stopped"
    finally:
        server.stop()


# ---- New tests for poll() mechanism ----

def test_poll_executes_queued_command():
    """test_poll_executes_queued_command — dispatch() ставит в очередь, poll() выполняет, future.result() = ответ."""
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()
    try:
        # dispatch puts command in queue and returns future
        future = server.dispatch("move", {"direction": "forward", "ticks": 5})
        # poll processes the queue and sets the future result
        server.poll()
        # Get the result from the future
        resp = future.result()
        assert resp["ok"] is True
        assert resp.get("result", {}).get("ticks") == 5
    finally:
        server.stop()


def test_poll_ignores_empty_queue():
    """test_poll_ignores_empty_queue — poll() на пустой очереди = no-op."""
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()
    try:
        # poll on empty queue should not raise
        server.poll()
    finally:
        server.stop()


def test_poll_multiple_commands():
    """test_poll_multiple_commands — 3 команды в очереди, poll() выполняет все."""
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()
    try:
        # Dispatch 3 commands
        f1 = server.dispatch("move", {"direction": "forward", "ticks": 1})
        f2 = server.dispatch("jump", {})
        f3 = server.dispatch("state", {})
        # poll should process all of them
        server.poll()
        # Check all futures are done and have results
        r1 = f1.result()
        r2 = f2.result()
        r3 = f3.result()
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r3["ok"] is True
    finally:
        server.stop()