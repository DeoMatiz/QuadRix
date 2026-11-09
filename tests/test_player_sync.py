#!/usr/bin/env python3
"""Тесты порта quadrix/player_sync.py.

Источник: horizon/crates/horizon-client/src/player_sync.rs.

Проверяем наблюдаемое поведение PositionSender::update (выбор пакета,
flags, baseline и reminder) и применение серверных PlayerPosition /
TeleportEntity к PlayerMotion. Пакеты берутся из play.py, .local-файлы
здесь не нужны.
"""

from __future__ import annotations

import pytest

from quadrix.core.geometry import Vec3
from quadrix.motion.core import PlayerMotion
from quadrix.player_sync import (
    PlayerSyncState,
    PositionSender,
    apply_server_position,
    relative,
    sync_client_to_server,
    teleport_velocity,
)
from quadrix.protocol.packets.play import (
    MovePlayerPos,
    MovePlayerPosRot,
    MovePlayerRot,
    MovePlayerStatus,
    PlayerPosition,
    TeleportEntity,
)


def _motion(x: float = 0.0, y: float = 64.0, z: float = 0.0) -> PlayerMotion:
    return PlayerMotion(position=Vec3.new(x, y, z))


def test_initial_state_and_first_sync_send_position() -> None:
    state = PlayerSyncState()
    assert state.last_pos is None

    pm = _motion(0.0, 64.0, 0.0)
    packet = sync_client_to_server(pm, state)

    assert isinstance(packet, MovePlayerPos)
    assert (packet.x, packet.y, packet.z) == (0.0, 64.0, 0.0)
    assert packet.flags == 0  # не на земле, коллизии нет
    assert state.last_pos == (0.0, 64.0, 0.0)


def test_no_movement_sends_nothing() -> None:
    state = PositionSender()
    pm = _motion()

    first = sync_client_to_server(pm, state)
    second = sync_client_to_server(pm, state)

    assert isinstance(first, MovePlayerPos)
    assert second is None


def test_movement_sends_position_with_on_ground_flag() -> None:
    state = PositionSender()
    pm = _motion()
    sync_client_to_server(pm, state)

    pm.position = Vec3.new(1.0, 64.0, 0.0)
    pm.on_ground = True
    packet = sync_client_to_server(pm, state)

    assert isinstance(packet, MovePlayerPos)
    assert (packet.x, packet.y, packet.z) == (1.0, 64.0, 0.0)
    assert packet.flags == 1  # ON_GROUND
    assert state.last_pos == (1.0, 64.0, 0.0)


def test_rotation_only_sends_rotation_packet() -> None:
    state = PositionSender()
    pm = _motion()
    sync_client_to_server(pm, state)

    pm.yaw = 90.0
    packet = sync_client_to_server(pm, state)

    assert isinstance(packet, MovePlayerRot)
    assert packet.yaw == 90.0
    assert packet.pitch == 0.0
    assert packet.flags == 0


def test_move_and_rotate_sends_pos_rot() -> None:
    state = PositionSender()
    pm = _motion()
    sync_client_to_server(pm, state)

    pm.position = Vec3.new(2.0, 65.0, 3.0)
    pm.yaw = 45.0
    pm.pitch = 10.0
    packet = sync_client_to_server(pm, state)

    assert isinstance(packet, MovePlayerPosRot)
    assert (packet.x, packet.y, packet.z) == (2.0, 65.0, 3.0)
    assert (packet.yaw, packet.pitch) == (45.0, 10.0)


def test_status_only_sends_status_packet() -> None:
    state = PositionSender(on_ground=False, collision=False)
    packet = state.update((0.0, 64.0, 0.0), (0.0, 0.0), True, False)

    # Первый вызов двигает baseline из (0,0,0), поэтому это Pos.
    assert isinstance(packet, MovePlayerPos)
    packet = state.update((0.0, 64.0, 0.0), (0.0, 0.0), False, False)
    assert isinstance(packet, MovePlayerStatus)
    assert packet.flags == 0


def test_apply_server_position_absolute() -> None:
    pm = _motion(4.0, 65.0, -2.0)
    pm.velocity = Vec3.new(1.0, 2.0, 3.0)
    pm.pitch = 5.0
    pm.fall_distance = 12.0

    packet = PlayerPosition(
        teleport=7,
        position=(10.0, 70.0, 0.0),
        delta=(0.0, 0.0, 0.0),
        yaw=90.0,
        pitch=0.0,
        relatives=0,
    )
    apply_server_position(pm, packet)

    assert pm.position == Vec3.new(10.0, 70.0, 0.0)
    assert pm.yaw == 90.0
    assert pm.pitch == 0.0
    assert pm.velocity == Vec3.new(0.0, 0.0, 0.0)
    assert pm.fall_distance == 0.0


def test_apply_teleport_entity_resets_velocity_and_position() -> None:
    pm = _motion(3.0, 65.0, 4.0)
    pm.velocity = Vec3.new(0.5, -0.2, 0.1)
    pm.yaw = 10.0
    pm.pitch = 5.0

    packet = TeleportEntity(
        id=123,
        position=(100.0, 80.0, -5.0),
        delta=(0.0, 0.0, 0.0),
        yaw=180.0,
        pitch=-10.0,
        relatives=0,
        on_ground=True,
    )
    apply_server_position(pm, packet)

    assert pm.position == Vec3.new(100.0, 80.0, -5.0)
    assert pm.yaw == 180.0
    assert pm.pitch == -10.0
    assert pm.velocity == Vec3.new(0.0, 0.0, 0.0)
    assert pm.on_ground is True


def test_relative_position_and_rotation_flags() -> None:
    pm = _motion(1.0, 64.0, 2.0)
    pm.yaw = 10.0
    pm.pitch = 5.0
    pm.velocity = Vec3.new(0.0, 0.0, 0.0)

    packet = PlayerPosition(
        teleport=1,
        position=(1.0, 2.0, 3.0),
        delta=(0.0, 0.0, 0.0),
        yaw=90.0,
        pitch=10.0,
        relatives=relative.X | relative.Y | relative.Z
        | relative.Y_ROT | relative.X_ROT,
    )
    apply_server_position(pm, packet)

    assert pm.position == Vec3.new(2.0, 66.0, 5.0)
    assert pm.yaw == 100.0
    assert pm.pitch == 15.0


def test_teleport_velocity_rotates_and_adds_relative_delta() -> None:
    velocity = Vec3.new(1.0, 0.0, 0.0)
    packet = PlayerPosition(
        teleport=1,
        position=(0.0, 0.0, 0.0),
        delta=(0.5, 0.0, 0.0),
        yaw=0.0,
        pitch=0.0,
        relatives=relative.DELTA_X,
    )

    result = teleport_velocity(
        velocity, (0.0, 0.0), (0.0, 0.0), packet
    )
    assert result.x == pytest.approx(1.5)
    assert result.y == 0.0
    assert result.z == 0.0

    # Без DELTA-флага компонента берётся из пакета как абсолютная.
    absolute = teleport_velocity(
        Vec3.new(9.0, 9.0, 9.0),
        (0.0, 0.0),
        (0.0, 0.0),
        PlayerPosition(1, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0, 0.0, 0),
    )
    assert absolute == Vec3.new(0.0, 0.0, 0.0)


def test_rejects_non_position_packet() -> None:
    pm = _motion()
    with pytest.raises(TypeError):
        apply_server_position(pm, object())