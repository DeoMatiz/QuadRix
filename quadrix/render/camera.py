#!/usr/bin/env python3
"""Камера QuadRix (порт ``horizon-client-render/src/camera.rs``).

Считает view/projection-матрицы и направление взгляда из yaw/pitch.
Формулы — из Rust, без изменений:

    rotation = Quat.rotation_yxz(PI - yaw*deg, -pitch*deg, 0)
    forwards = rotation.transform([0, 0, -1])
    up       = rotation.transform([0, 1, 0])
    left     = rotation.transform([-1, 0, 0])

Следствие (Rust-тест ``rotation_faces_south_at_zero_yaw``):
    yaw = 0   -> forwards = (0, 0, +1)   (юг, +Z)
    yaw = 90  -> forwards = (-1, 0, 0)   (запад, -X)

Проекция — ``camera::perspective`` (OpenGL, NDC z в -1..1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "Basis",
    "Camera",
    "perspective",
    "rotation_yxz",
]

PI = math.pi
DEG_TO_RAD = math.pi / 180.0
TAU = 2.0 * math.pi


def _cos_from_sin(sin_value: float, angle: float) -> float:
    """``joml::cos_from_sin``: cos по уже посчитанному sin и углу."""
    cos = math.sqrt(max(0.0, 1.0 - sin_value * sin_value))
    a = angle + math.pi / 2.0
    b = a - float(int(a / TAU)) * TAU
    if b < 0.0:
        b += TAU
    return -cos if b >= PI else cos


def rotation_yxz(angle_y: float, angle_x: float, angle_z: float) -> tuple[float, float, float, float]:
    """``Quat::rotation_yxz`` — кватернион ``(x, y, z, w)``."""
    sx = math.sin(angle_x * 0.5)
    cx = _cos_from_sin(sx, angle_x * 0.5)
    sy = math.sin(angle_y * 0.5)
    cy = _cos_from_sin(sy, angle_y * 0.5)
    sz = math.sin(angle_z * 0.5)
    cz = _cos_from_sin(sz, angle_z * 0.5)
    x = cy * sx
    y = sy * cx
    z = sy * sx
    w = cy * cx
    return (
        x * cz + y * sz,
        y * cz - x * sz,
        w * sz - z * cz,
        w * cz + z * sz,
    )


def _quat_transform(quat: tuple[float, float, float, float], v: tuple[float, float, float]):
    """``Quat::transform`` — повернуть вектор ``v`` кватернионом."""
    qx, qy, qz, qw = quat
    x, y, z = v
    xx = qx * qx
    yy = qy * qy
    zz = qz * qz
    ww = qw * qw
    xy = qx * qy
    xz = qx * qz
    yz = qy * qz
    xw = qx * qw
    zw = qz * qw
    yw = qy * qw
    k = 1.0 / (xx + yy + zz + ww)
    return np.array(
        [
            (xx - yy - zz + ww) * k * x
            + (2.0 * (xy - zw) * k * y + 2.0 * (xz + yw) * k * z),
            2.0 * (xy + zw) * k * x
            + ((yy - xx - zz + ww) * k * y + 2.0 * (yz - xw) * k * z),
            2.0 * (xz - yw) * k * x
            + (2.0 * (yz + xw) * k * y + (zz - xx - yy + ww) * k * z),
        ],
        dtype=np.float64,
    )


@dataclass(frozen=True)
class Basis:
    """Ортонормированный базис камеры: forwards / up / left."""

    forwards: np.ndarray
    up: np.ndarray
    left: np.ndarray


def camera_basis(yaw: float, pitch: float) -> Basis:
    """Базис камеры для ``yaw``/``pitch`` (порт ``Camera::set_rotation``)."""
    quat = rotation_yxz(PI - yaw * DEG_TO_RAD, -pitch * DEG_TO_RAD, 0.0)
    return Basis(
        forwards=_quat_transform(quat, (0.0, 0.0, -1.0)),
        up=_quat_transform(quat, (0.0, 1.0, 0.0)),
        left=_quat_transform(quat, (-1.0, 0.0, 0.0)),
    )


def perspective(
    fov_degrees: float,
    width: float,
    height: float,
    near: float,
    far: float,
    zero_to_one: bool = False,
) -> np.ndarray:
    """``camera::perspective`` — матрица перспективы 4x4 (row-major).

    ``zero_to_one=False`` — OpenGL (NDC z в -1..1), как нужен moderngl.
    """
    h = math.tan(fov_degrees * DEG_TO_RAD * 0.5)
    aspect = width / height
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = 1.0 / (h * aspect)
    m[1, 1] = 1.0 / h
    m[2, 2] = (far if zero_to_one else far + near) / (near - far)
    m[2, 3] = (far if zero_to_one else far + far) * near / (near - far)
    m[3, 2] = -1.0
    return m


@dataclass
class Camera:
    """Камера первого лица (позиция + yaw/pitch + FOV)."""

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    yaw: float = 0.0
    pitch: float = 0.0
    fov: float = 70.0
    near: float = 0.05
    far: float = 1024.0

    def basis(self) -> Basis:
        return camera_basis(self.yaw, self.pitch)

    def forward(self) -> np.ndarray:
        """Направление взгляда в мировых координатах (``Camera.forwards``)."""
        return self.basis().forwards

    def up(self) -> np.ndarray:
        return self.basis().up

    def left(self) -> np.ndarray:
        return self.basis().left

    def view_matrix(self) -> np.ndarray:
        """World → view (row-major 4x4).

        Строки поворота: ``(-left, up, -forwards)`` — следствие того, что
        ``view * forwards == (0, 0, -1)``, ``view * up == (0, 1, 0)``,
        ``view * left == (-1, 0, 0)`` (Rust-тест камеры).
        """
        b = self.basis()
        view = np.eye(4, dtype=np.float32)
        view[0, :3] = -b.left
        view[1, :3] = b.up
        view[2, :3] = -b.forwards
        t = np.array(self.position, dtype=np.float64)
        rot = view[:3, :3].astype(np.float64)
        view[:3, 3] = -(rot @ t)
        return view

    def projection(self, width: float, height: float) -> np.ndarray:
        return perspective(
            self.fov, width, height, self.near, self.far, zero_to_one=False
        )

    def view_projection(self, width: float, height: float) -> np.ndarray:
        """``projection @ view`` — то, что кладётся в uniform ``mvp``."""
        return self.projection(width, height) @ self.view_matrix()
