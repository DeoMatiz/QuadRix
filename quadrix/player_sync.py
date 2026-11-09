# Порт horizon/crates/horizon-client/src/player_sync.rs.
#
# Rust-файл содержит две вещи:
#   * PositionSender::update — LocalPlayer.sendPosition: решает, какой из
#     ServerboundMovePlayerPacket отправить в этом такте;
#   * teleport_velocity — PositionMoveRotation.calculateAbsolute: поворот
#     старой скорости и применение относительных компонент delta.
#
# Имена полей, порог 2.0e-4, счётчик reminder >= 20 и упаковка flags
# (1 — on_ground, 2 — collision) сохранены дословно.
#
# Дополнительно (по заданию) здесь лежат два адаптера для PlayerMotion:
#   * sync_client_to_server — снять позицию/углы с PlayerMotion и вызвать
#     PositionSender::update;
#   * apply_server_position — применить входящий PlayerPosition (в Rust это
#     ClientboundPlayerPositionPacket) или TeleportEntity к PlayerMotion.
# Сами пакеты и их encode/decode берутся только из play.py.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

from quadrix.core.geometry import Vec3
from quadrix.protocol.buf import Writer
from quadrix.protocol.packets.play import (
    MovePlayerPos,
    MovePlayerPosRot,
    MovePlayerRot,
    MovePlayerStatus,
    PlayerPosition,
    TeleportEntity,
)

__all__ = [
    "relative",
    "PositionSender",
    "PlayerSyncState",
    "teleport_velocity",
    "sync_client_to_server",
    "apply_server_position",
]


# play.rs:47-58 — Relative.pack (X, Y, Z, Y_ROT, X_ROT, DELTA_X/Y/Z,
# ROTATE_DELTA). В play.py константы не экспортированы, поэтому повторяем
# их здесь один в один, как отдельный модуль relative из Rust.
class relative:
    X: int = 1
    Y: int = 2
    Z: int = 4
    Y_ROT: int = 8
    X_ROT: int = 16
    DELTA_X: int = 32
    DELTA_Y: int = 64
    DELTA_Z: int = 128
    ROTATE_DELTA: int = 256


# player_sync.rs:5-14 — только обновления движения сдвигают baseline.
# Подтверждение телепорта сюда не попадает и не подавляет следующий такт.
@dataclass
class PositionSender:
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float] = (0.0, 0.0)
    on_ground: bool = False
    collision: bool = False
    reminder: int = 0
    # Отдельный признак «baseline уже отправлялся»: в Rust его заменяет
    # Default с нулевой позицией. Нужен только для удобного last_pos.
    _has_position: bool = field(default=False, repr=False)

    @property
    def last_pos(self) -> Optional[Tuple[float, float, float]]:
        """Последняя отправленная позиция или None до первой отправки."""
        return self.position if self._has_position else None

    def update(
        self,
        position: Tuple[float, float, float],
        rotation: Tuple[float, float],
        on_ground: bool,
        collision: bool,
    ) -> Optional[object]:
        """Вернуть нужный ServerboundMovePlayerPacket или None."""
        self.reminder += 1
        delta = [position[i] - self.position[i] for i in range(3)]
        moved = (
            delta[0] * delta[0] + delta[1] * delta[1] + delta[2] * delta[2]
            > 2.0e-4 * 2.0e-4
            or self.reminder >= 20
        )
        rotated = (
            rotation[0] - self.rotation[0] != 0.0
            or rotation[1] - self.rotation[1] != 0.0
        )
        flags = int(on_ground) | int(collision) << 1
        x, y, z = position
        yaw, pitch = rotation

        packet: Optional[object]
        if moved and rotated:
            packet = MovePlayerPosRot(
                x=x, y=y, z=z, yaw=yaw, pitch=pitch, flags=flags
            )
        elif moved:
            packet = MovePlayerPos(x=x, y=y, z=z, flags=flags)
        elif rotated:
            packet = MovePlayerRot(yaw=yaw, pitch=pitch, flags=flags)
        elif self.on_ground != on_ground or self.collision != collision:
            packet = MovePlayerStatus(flags=flags)
        else:
            packet = None

        if moved:
            self.position = (position[0], position[1], position[2])
            self._has_position = True
            self.reminder = 0
        if rotated:
            self.rotation = (rotation[0], rotation[1])
        self.on_ground = on_ground
        self.collision = collision
        return packet


# Имя из задания; в Rust класс называется PositionSender.
PlayerSyncState = PositionSender


def teleport_velocity(
    velocity: Vec3,
    old_rotation: Tuple[float, float],
    new_rotation: Tuple[float, float],
    packet: PlayerPosition | TeleportEntity,
) -> Vec3:
    """Повернуть старую скорость, затем прибавить относительные delta."""
    if packet.relatives & relative.ROTATE_DELTA != 0:
        # Java: f64::from(f32).to_radians() as f32 — считаем в double и
        # передаём радианы в Vec3.rotate_x / rotate_y, как glam.
        pitch = math.radians(float(old_rotation[1] - new_rotation[1]))
        yaw = math.radians(float(old_rotation[0] - new_rotation[0]))
        velocity = velocity.rotate_x(pitch).rotate_y(yaw)

    old = [velocity.x, velocity.y, velocity.z]
    flags = [relative.DELTA_X, relative.DELTA_Y, relative.DELTA_Z]
    result = [
        old[i] + packet.delta[i] if packet.relatives & flags[i] != 0
        else packet.delta[i]
        for i in range(3)
    ]
    return Vec3.new(result[0], result[1], result[2])


def sync_client_to_server(
    pm: object,
    state: PositionSender,
    writer: Optional[Writer] = None,
) -> Optional[object]:
    """Снять состояние с PlayerMotion и, если нужно, отправить пакет.

    Возвращает отправленный пакет (или None). Если передан writer, тело
    пакета пишется в него через encode() из play.py — без дублирования
    кодеков.
    """
    collision = bool(
        getattr(pm, "horizontal_collision", getattr(pm, "collision", False))
    )
    packet = state.update(
        pm.position.components(),
        (float(pm.yaw), float(getattr(pm, "pitch", 0.0))),
        bool(pm.on_ground),
        collision,
    )
    if packet is not None and writer is not None:
        writer.bytes(packet.encode())
    return packet


def apply_server_position(
    pm: object,
    packet: PlayerPosition | TeleportEntity,
) -> None:
    """Применить серверную позицию/телепорт к PlayerMotion.

    Relative-флаги позиции и углов раскрываются здесь, скорость считается
    через teleport_velocity (та же арифметика Relative.pack, что в Rust).
    Отдельного подтверждения в player_sync.rs нет — поэтому ничего не
    отправляем.
    """
    if not isinstance(packet, (PlayerPosition, TeleportEntity)):
        raise TypeError(
            f"[QuadRix] apply_server_position: неподдерживаемый пакет "
            f"{type(packet).__name__}"
        )

    relatives = int(packet.relatives)
    old_position = pm.position.components()
    old_rotation = (float(pm.yaw), float(getattr(pm, "pitch", 0.0)))

    position = list(packet.position)
    for i, flag in enumerate((relative.X, relative.Y, relative.Z)):
        if relatives & flag != 0:
            position[i] = old_position[i] + position[i]

    yaw = (
        old_rotation[0] + packet.yaw
        if relatives & relative.Y_ROT != 0
        else packet.yaw
    )
    pitch = (
        old_rotation[1] + packet.pitch
        if relatives & relative.X_ROT != 0
        else packet.pitch
    )

    velocity = teleport_velocity(
        pm.velocity, old_rotation, (yaw, pitch), packet
    )

    pm.position = Vec3.new(position[0], position[1], position[2])
    pm.velocity = velocity
    pm.yaw = float(yaw)
    pm.pitch = float(pitch)
    pm.fall_distance = 0.0
    if isinstance(packet, TeleportEntity):
        pm.on_ground = bool(packet.on_ground)