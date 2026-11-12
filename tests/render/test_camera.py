#!/usr/bin/env python3
"""Тесты камеры QuadRix (порт ``camera.rs``).

Базис камеры, view-матрица и проекция. Поворот проверяем по Rust-тесту
``rotation_faces_south_at_zero_yaw``: yaw = 0 → взгляд (0, 0, +1) (юг),
yaw = 90 → (-1, 0, 0) (запад).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from quadrix.render.camera import Camera, perspective


def test_camera_view() -> None:
    """Базис и view-матрица совпадают с Rust ``Camera``."""
    cam = Camera(position=(0.0, 0.0, 0.0), yaw=0.0, pitch=0.0)

    # yaw = 0 → forward = (0, 0, +1), up = (0, 1, 0).
    assert cam.forward() == pytest.approx(np.array([0.0, 0.0, 1.0]), abs=1e-6)
    assert cam.up() == pytest.approx(np.array([0.0, 1.0, 0.0]), abs=1e-6)

    # yaw = 90 → forward = (-1, 0, 0) (запад); right = -left.
    cam.yaw = 90.0
    assert cam.forward() == pytest.approx(np.array([-1.0, 0.0, 0.0]), abs=1e-6)

    # pitch = 90 → взгляд вниз (0, -1, 0).
    cam.yaw = 0.0
    cam.pitch = 90.0
    assert cam.forward() == pytest.approx(np.array([0.0, -1.0, 0.0]), abs=1e-6)

    # view: поворот переводит мировой forward в (0, 0, -1) (камера смотрит в -Z).
    cam.pitch = 0.0
    view = cam.view_matrix()
    rot = view[:3, :3].astype(np.float64)
    assert rot @ cam.forward() == pytest.approx(
        np.array([0.0, 0.0, -1.0]), abs=1e-6
    )
    assert rot @ cam.up() == pytest.approx(np.array([0.0, 1.0, 0.0]), abs=1e-6)

    # Смещение позиции: view переводит точку камеры в начало координат.
    cam.position = (5.0, 6.0, 7.0)
    view = cam.view_matrix()
    point = np.array([5.0, 6.0, 7.0, 1.0], dtype=np.float64)
    assert view @ point == pytest.approx(
        np.array([0.0, 0.0, 0.0, 1.0]), abs=1e-6
    )


def test_camera_projection() -> None:
    """``perspective`` — OpenGL-проекция (NDC z в -1..1)."""
    cam = Camera(fov=70.0, near=0.05, far=1024.0)
    width, height = 800.0, 600.0
    proj = cam.projection(width, height)

    assert proj.shape == (4, 4)
    h = math.tan(math.radians(70.0) * 0.5)
    aspect = width / height
    assert proj[0, 0] == pytest.approx(1.0 / (h * aspect), rel=1e-5)
    assert proj[1, 1] == pytest.approx(1.0 / h, rel=1e-5)
    assert proj[3, 2] == pytest.approx(-1.0, abs=1e-6)
    # z-строка OpenGL: (far+near)/(near-far) и 2*far*near/(near-far).
    assert proj[2, 2] == pytest.approx(
        (1024.0 + 0.05) / (0.05 - 1024.0), rel=1e-5
    )
    assert proj[2, 3] == pytest.approx(
        (1024.0 + 1024.0) * 0.05 / (0.05 - 1024.0), rel=1e-5
    )

    # Vulkan/zero-to-one: другая z-строка.
    vk = perspective(70.0, width, height, 0.05, 1024.0, zero_to_one=True)
    assert vk[2, 2] == pytest.approx(1024.0 / (0.05 - 1024.0), rel=1e-5)

    # view_projection = projection @ view.
    expected = cam.projection(width, height) @ cam.view_matrix()
    assert cam.view_projection(width, height) == pytest.approx(expected, rel=1e-6)
