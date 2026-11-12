#!/usr/bin/env python3
"""Тесты обзора мышью QuadRix (порт ``mouse.rs``).

Чувствительность по умолчанию (0.5) даёт ``sens = 1.0``, то есть 0.15°
поворота на единицу движения мыши; pitch зажат в -90..90.
"""

from __future__ import annotations

import pytest

from quadrix.input.mouse import (
    LookOptions,
    MouseLook,
    Rotation,
    degrees_per_count,
    java_signum,
)


def test_mouse_look() -> None:
    """Движение мыши → yaw/pitch как в ``MouseLook`` + ``Rotation.turn``."""
    look = LookOptions(sensitivity=0.5)
    # sens = (0.5*0.6+0.2)^3*8 = 1.0 → 0.15°/ед.
    assert degrees_per_count(look) == pytest.approx(0.15)

    mouse = MouseLook(look=look)
    mouse.add_motion(10.0, 5.0)
    turn = mouse.handle_accumulated_movement(0.0, True, True)
    assert turn is not None
    xo, yo = turn
    assert xo == pytest.approx(10.0)
    assert yo == pytest.approx(5.0)
    # Накопитель очищен после кадра.
    assert mouse.accumulated() == (0.0, 0.0)

    rotation = Rotation()
    rotation.turn(xo, yo)
    # yaw += xo*0.15, pitch += yo*0.15.
    assert rotation.y_rot == pytest.approx(1.5)
    assert rotation.x_rot == pytest.approx(0.75)


def test_mouse_look_pitch_clamped() -> None:
    """Pitch зажат в -90..90 (как ``Mth.clamp`` в Rust)."""
    rotation = Rotation()

    # yo = 2000 → x_delta = 300 (> 90) → зажим на 90.
    rotation.turn(0.0, 2000.0)
    assert rotation.x_rot == pytest.approx(90.0)

    # Резкое движение вниз: 90 - 300 = -210; Rust ``% 360`` = fmod (знак
    # делимого) даёт -210 → зажим -90. Python ``%`` дал бы 150 → 90.
    rotation.turn(0.0, -2000.0)
    assert rotation.x_rot == pytest.approx(-90.0)

    # Обратное движение возвращает из зажима в допустимый диапазон.
    rotation2 = Rotation()
    rotation2.turn(0.0, 100.0)  # pitch = 15.0
    assert rotation2.x_rot == pytest.approx(15.0)


def test_mouse_look_invert_and_sensitivity() -> None:
    """Инверсия осей и другая чувствительность (``turn_player``)."""
    inverted = LookOptions(sensitivity=0.5, invert_x=True, invert_y=True)
    mouse = MouseLook(look=inverted)
    mouse.add_motion(4.0, 2.0)
    xo, yo = mouse.turn_player(inverted)
    assert xo == pytest.approx(-4.0)
    assert yo == pytest.approx(-2.0)

    # Нулевая чувствительность: sens = 0.2^3 * 8 = 0.064.
    low = LookOptions(sensitivity=0.0)
    assert degrees_per_count(low) == pytest.approx(0.15 * 0.064)

    # java_signum: знак без потери -0.0/NaN.
    assert java_signum(5.0) == 1.0
    assert java_signum(-3.0) == -1.0
    assert java_signum(0.0) == 0.0
