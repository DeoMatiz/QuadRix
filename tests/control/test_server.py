#!/usr/bin/env python3
"""[QuadRix] Тесты ControlServer — диспетчер команд и JSON-протокол.

Использует FakeClient с настоящим PlayerMotion, проверяя:
  - протокол request/response round-trip по сокету
  - state читает client.motion (а не кэш wrapper)
  - move/jump взводят pending_input, а не двигают PlayerMotion напрямую
  - sneak/sprint/fly/look меняют motion
  - poll()-механизм очереди команд
"""

from __future__ import annotations

import json
import socket

import pytest

from quadrix.control.server import ControlServer, _ClientWrapper, _wrapper_dispatch


# ---------------------------------------------------------------------------
# Минимальный fake client for tests
# ---------------------------------------------------------------------------

class FakeClient:
    """Минимальный клиент-заглушка для тестов ControlServer.dispatch."""

    def __init__(self) -> None:
        from quadrix.motion.core import PlayerMotion, Vec3

        self.motion = PlayerMotion.new(
            type("MovementResources", (), {"properties": {}})(),
            Vec3(0, 64, 0),
        )
        # Минимальный мир — возвращает "air" везде
        self.world = _FakeWorld()
        self.pending_input = None
        self.pending_input_ticks = 0
        self.health = None

    def _send(self, body: bytes) -> None:
        """Минимальная реализация _send для тестов (пакеты не отправляются)."""
        self.sent = getattr(self, "sent", [])
        self.sent.append(body)


class _FakeHealth:
    """Заглушка PlayerHealth: health — метод, как в quadrix/health.py."""

    def __init__(self, value: float) -> None:
        self._value = value

    def health(self) -> float:
        return self._value


class _FakeWorld:
    """Fake world returning air for all block queries."""

    def block(self, x: int, y: int, z: int) -> str:
        return "minecraft:air"


def _make_server() -> tuple[ControlServer, FakeClient]:
    client = FakeClient()
    server = ControlServer(host="127.0.0.1", port=0, client=client)
    return server, client


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def test_state_reads_client_motion():
    """state читает client.motion, а не кэш wrapper."""
    from quadrix.motion.core import Vec3

    server, client = _make_server()
    client.motion.position = Vec3(1.0, 2.0, 3.0)
    client.motion.on_ground = True
    client.motion.yaw = 90.0

    resp = server.dispatch_internal("state", {})
    assert resp["ok"] is True
    pos = resp["result"]["pos"]
    assert (pos["x"], pos["y"], pos["z"]) == (1.0, 2.0, 3.0)
    assert resp["result"]["on_ground"] is True
    assert resp["result"]["yaw"] == 90.0


def test_state_late_motion_attachment():
    """ControlServer создан до prepare(): motion появился позже — wrapper видит его."""
    server = ControlServer(host="127.0.0.1", port=0, client=FakeClient())
    client = server.client
    client.motion = None
    assert server.dispatch_internal("state", {})["ok"] is False

    from quadrix.motion.core import PlayerMotion, Vec3

    client.motion = PlayerMotion.new(
        type("MovementResources", (), {"properties": {}})(), Vec3(4.0, 70.0, 8.0)
    )
    result = server.dispatch_internal("state", {})["result"]
    assert result["pos"] == {"x": 4.0, "y": 70.0, "z": 8.0}


def test_state_reads_client_health():
    """health берётся из client.health.health() (метод PlayerHealth)."""
    server, client = _make_server()
    client.health = _FakeHealth(12.5)
    resp = server.dispatch_internal("state", {})
    assert resp["result"]["health"] == 12.5


def test_state_without_health_defaults_to_20():
    server, client = _make_server()
    client.health = None
    resp = server.dispatch_internal("state", {})
    assert resp["result"]["health"] == 20.0


# ---------------------------------------------------------------------------
# move / jump
# ---------------------------------------------------------------------------


def test_move_sets_pending_input():
    """move forward 20 (2 блока) -> forward == 1.0, ticks == 10."""
    server, client = _make_server()
    resp = server.dispatch_internal("move", {"direction": "forward", "ticks": 20})
    assert resp["ok"] is True
    assert client.pending_input is not None
    assert client.pending_input.forward == 1.0
    assert client.pending_input.strafe == 0.0
    assert client.pending_input_ticks == 10
    assert resp["result"]["blocks"] == 2.0
    assert resp["result"]["ticks"] == 10


def test_move_ticks_from_decimals():
    """move forward 10 = 1 блок -> 5 тиков (10 десятых / 2)."""
    server, client = _make_server()
    resp = server.dispatch_internal("move", {"direction": "forward", "ticks": 10})
    assert resp["ok"] is True
    assert client.pending_input_ticks == 5
    assert resp["result"]["blocks"] == 1.0
    assert resp["result"]["ticks"] == 5


def test_move_directions_map_to_input():
    server, client = _make_server()
    cases = {
        "back": (-1.0, 0.0),
        "left": (0.0, -1.0),
        "right": (0.0, 1.0),
    }
    for direction, (fwd, strafe) in cases.items():
        server.dispatch_internal("move", {"direction": direction, "ticks": 2})
        assert client.pending_input.forward == fwd
        assert client.pending_input.strafe == strafe


def test_move_does_not_move_motion_directly():
    """move не должен двигать PlayerMotion: это делает Client.tick()."""
    from quadrix.motion.core import Vec3

    server, client = _make_server()
    start = client.motion.position
    server.dispatch_internal("move", {"direction": "forward", "ticks": 5})
    assert client.motion.position == start


def test_move_requires_motion():
    server, client = _make_server()
    client.motion = None
    resp = server.dispatch_internal("move", {"direction": "forward", "ticks": 1})
    assert resp["ok"] is False
    assert "motion not ready" in resp["error"]


def test_jump_sets_pending_input():
    server, client = _make_server()
    resp = server.dispatch_internal("jump", {})
    assert resp["ok"] is True
    assert client.pending_input.jump is True
    assert client.pending_input.forward == 0.0
    assert client.pending_input_ticks == 1


def test_jump_requires_motion():
    server, client = _make_server()
    client.motion = None
    resp = server.dispatch_internal("jump", {})
    assert resp["ok"] is False
    assert "motion not ready" in resp["error"]


# ---------------------------------------------------------------------------
# sneak / sprint / fly / look
# ---------------------------------------------------------------------------


def test_sneak_updates_motion():
    server, client = _make_server()
    server.dispatch_internal("sneak", {"value": True})
    assert client.motion.sneaking is True


def test_sprint_updates_motion():
    server, client = _make_server()
    server.dispatch_internal("sprint", {"value": True})
    assert client.motion.sprinting is True


def test_fly_updates_motion():
    server, client = _make_server()
    server.dispatch_internal("fly", {"value": True})
    assert client.motion.flying is True


def test_look_updates_motion():
    server, client = _make_server()
    resp = server.dispatch_internal("look", {"yaw": 45.0, "pitch": -10.0})
    assert resp["ok"] is True
    assert client.motion.yaw == 45.0
    assert client.motion.pitch == -10.0


def test_look_applies():
    """look 90 45 -> yaw=90, pitch=45 прямо в client.motion."""
    server, client = _make_server()
    resp = server.dispatch_internal("look", {"yaw": 90.0, "pitch": 45.0})
    assert resp["ok"] is True
    assert client.motion.yaw == 90.0
    assert client.motion.pitch == 45.0
    assert resp["result"] == {"yaw": 90.0, "pitch": 45.0}


def test_turn_left():
    """turn left 15 -> yaw увеличивается на 15."""
    server, client = _make_server()
    client.motion.yaw = 0.0
    resp = server.dispatch_internal("turn", {"axis": "left", "degrees": 15})
    assert resp["ok"] is True
    assert client.motion.yaw == 15.0
    assert resp["result"]["yaw"] == 15.0


def test_turn_right():
    server, client = _make_server()
    client.motion.yaw = 30.0
    resp = server.dispatch_internal("turn", {"axis": "right", "degrees": 15})
    assert resp["ok"] is True
    assert client.motion.yaw == 15.0


def test_turn_up():
    """turn up 15 -> pitch уменьшается (в Horizon +pitch смотрит вниз)."""
    server, client = _make_server()
    client.motion.pitch = 0.0
    resp = server.dispatch_internal("turn", {"axis": "up", "degrees": 15})
    assert resp["ok"] is True
    assert client.motion.pitch == -15.0


def test_turn_down_clamps():
    server, client = _make_server()
    client.motion.pitch = 85.0
    resp = server.dispatch_internal("turn", {"axis": "down", "degrees": 15})
    assert resp["ok"] is True
    assert client.motion.pitch == 90.0


def test_turn_unknown_axis():
    server, _client = _make_server()
    resp = server.dispatch_internal("turn", {"axis": "sideways", "degrees": 15})
    assert resp["ok"] is False
    assert "unknown axis" in resp["error"]


def test_turn_default_degrees_is_15():
    server, client = _make_server()
    client.motion.yaw = 10.0
    resp = server.dispatch_internal("turn", {"axis": "left"})
    assert resp["ok"] is True
    assert client.motion.yaw == 25.0


# ---------------------------------------------------------------------------
# quadrixctl aliases
# ---------------------------------------------------------------------------


def test_ctl_wasd_aliases_one_block():
    from quadrixctl import build_request

    cases = {
        "w": "forward",
        "s": "back",
        "a": "left",
        "d": "right",
        "forward": "forward",
        "back": "back",
        "left": "left",
        "right": "right",
    }
    for alias, direction in cases.items():
        req = build_request(alias, 1)
        assert req is not None
        assert req["cmd"] == "move"
        assert req["args"]["direction"] == direction
        assert req["args"]["ticks"] == 10  # 1 блок
    # w 20 — 2 блока
    assert build_request("w 20", 1)["args"]["ticks"] == 20


def test_ctl_turn_aliases():
    from quadrixctl import build_request

    cases = {"tl": "left", "tr": "right", "tu": "up", "td": "down"}
    for alias, axis in cases.items():
        req = build_request(alias, 1)
        assert req["cmd"] == "turn"
        assert req["args"]["axis"] == axis
        assert req["args"]["degrees"] == 15.0
    assert build_request("turn down 30", 1)["args"]["degrees"] == 30.0


def test_ctl_space_alias_is_jump():
    from quadrixctl import build_request

    req = build_request("space", 1)
    assert req["cmd"] == "jump"


# ---------------------------------------------------------------------------
# wrapper helper / chat / place / break / unknown / stop
# ---------------------------------------------------------------------------


def test_wrapper_dispatch_state():
    client = FakeClient()
    wrapper = _ClientWrapper(client.motion, client.world, client=client)
    resp = _wrapper_dispatch(wrapper, "state", {})
    assert resp["ok"] is True
    assert "pos" in resp["result"]


def test_dispatch_chat():
    server, client = _make_server()
    resp = server.dispatch_internal("chat", {"text": "hi"})
    assert resp["ok"] is True
    assert resp["result"]["text"] == "hi"
    assert client.sent


def test_dispatch_place_and_break_return_structured():
    server, _client = _make_server()
    for cmd, args in (("place", {"block": "stone"}), ("break", {})):
        resp = server.dispatch_internal(cmd, args)
        assert "ok" in resp
        assert "error" in resp or "result" in resp


def test_dispatch_unknown():
    server, _client = _make_server()
    resp = server.dispatch_internal("unknown", {})
    assert resp["ok"] is False
    assert "unknown command" in resp["error"]


def test_stop_command():
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()
    try:
        resp = server.dispatch("stop", {}).result()
        assert resp["ok"] is True
        assert resp["result"]["status"] == "stopped"
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# JSON-протокол через сокет
# ---------------------------------------------------------------------------


def _round_trip(server: ControlServer, request: dict) -> dict:
    port = server._server_socket.getsockname()[1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", port))
    try:
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    finally:
        sock.close()
    return json.loads(buf.decode("utf-8").strip())


def test_json_protocol_round_trip_state():
    server, client = _make_server()
    server.start()
    try:
        response = _round_trip(server, {"id": 1, "cmd": "state", "args": {}})
        assert response["ok"] is True
        assert response["id"] == 1
        assert "pos" in response["result"]
    finally:
        server.stop()


def test_json_protocol_round_trip_move():
    server, client = _make_server()
    server.start()
    try:
        response = _round_trip(
            server, {"id": 2, "cmd": "move", "args": {"direction": "forward", "ticks": 3}}
        )
        assert response["ok"] is True
        assert response["id"] == 2
        assert client.pending_input_ticks == 2
    finally:
        server.stop()


# ---- poll() mechanism ----

def test_poll_executes_queued_command():
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()
    try:
        future = server.dispatch("move", {"direction": "forward", "ticks": 5})
        server.poll()
        resp = future.result()
        assert resp["ok"] is True
        assert resp["result"]["ticks"] == 2
    finally:
        server.stop()


def test_poll_ignores_empty_queue():
    server = ControlServer(host="127.0.0.1", port=0, client=None)
    server.start()
    try:
        server.poll()
    finally:
        server.stop()


def test_poll_multiple_commands():
    server, client = _make_server()
    try:
        f1 = server.dispatch("move", {"direction": "forward", "ticks": 1})
        f2 = server.dispatch("jump", {})
        f3 = server.dispatch("state", {})
        server.poll()
        assert f1.result()["ok"] is True
        assert f2.result()["ok"] is True
        assert f3.result()["ok"] is True
    finally:
        server.stop()
