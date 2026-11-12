#!/usr/bin/env python3
"""Обзор мышью QuadRix (порт ``horizon-client-input/src/mouse.rs``).

``MouseLook`` накапливает относительное движение мыши и раз в кадр
превращает его в ``(xo, yo)`` для ``Entity.turn``.  ``Rotation`` хранит
yaw/pitch игрока; pitch зажат в -90..90.

Формула (Rust, без изменений):
    ss = sensitivity * 0.6 + 0.2
    sens = ss^3 * 8
    turn: yaw += xo * 0.15; pitch += yo * 0.15 (clamp -90..90)
При sensitivity = 0.5 (значение по умолчанию) sens = 1.0, то есть 0.15
градуса на единицу движения.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "LookOptions",
    "MouseLook",
    "Rotation",
    "Sensitivity",
    "degrees_per_count",
    "java_signum",
]


def java_signum(value: float) -> float:
    """``Math.signum(double)`` (как ``mouse::java_signum``)."""
    if value == 0.0 or math.isnan(value):
        return value
    return math.copysign(1.0, value)


def mth_clamp(value: float, low: float, high: float) -> float:
    """``Mth.clamp(float, float, float)``."""
    if value < low:
        return low
    if math.isnan(value) or math.isnan(high):
        return math.nan
    return min(value, high)


@dataclass
class Rotation:
    """Поворот сущности (порт ``mouse::Rotation`` / ``Entity``).

    ``y_rot`` — yaw (не зажата), ``x_rot`` — pitch (зажат -90..90).
    ``*_o`` — предыдущие значения (для интерполяции кадра).
    """

    x_rot: float = 0.0
    y_rot: float = 0.0
    x_rot_o: float = 0.0
    y_rot_o: float = 0.0

    def set_x_rot(self, x_rot: float) -> None:
        if math.isfinite(x_rot):
            # Rust ``x_rot % 360.0`` — это fmod (знак делимого), не Python %;
            # math.fmod сохраняет поведение Rust для отрицательных углов.
            self.x_rot = mth_clamp(math.fmod(x_rot, 360.0), -90.0, 90.0)

    def set_y_rot(self, y_rot: float) -> None:
        if math.isfinite(y_rot):
            self.y_rot = y_rot

    def turn(self, xo: float, yo: float) -> None:
        """``Entity.turn(xo, yo)``: 0.15 градуса на единицу движения.

        ``xo`` (движение мыши по X) меняет yaw, ``yo`` (по Y) — pitch.
        """
        x_delta = float(yo) * 0.15
        y_delta = float(xo) * 0.15
        self.set_x_rot(self.x_rot + x_delta)
        self.set_y_rot(self.y_rot + y_delta)
        self.set_x_rot(mth_clamp(self.x_rot, -90.0, 90.0))
        self.x_rot_o += x_delta
        self.y_rot_o += y_delta
        self.x_rot_o = mth_clamp(self.x_rot_o, -90.0, 90.0)


@dataclass
class LookOptions:
    """Опции ``MouseHandler.turnPlayer`` (порт ``LookOptions``)."""

    sensitivity: float = 0.5
    smooth_camera: bool = False
    scoping: bool = False
    invert_x: bool = False
    invert_y: bool = False


@dataclass
class Sensitivity:
    """Разложенные масштабы чувствительности (``sensitivity_scales``)."""

    sensitivity_mod: float
    sens: float


def _sensitivity_scales(sensitivity: float) -> Sensitivity:
    """``sensitivityMod = (s*0.6+0.2)^3``, ``sens = sensitivityMod * 8``."""
    ss = float(sensitivity) * 0.6 + 0.2
    sensitivity_mod = ss * ss * ss
    return Sensitivity(sensitivity_mod=sensitivity_mod, sens=sensitivity_mod * 8.0)


def degrees_per_count(look: LookOptions) -> float:
    """Сколько градусов поворота даёт одна единица движения мыши."""
    scales = _sensitivity_scales(look.sensitivity)
    scale = (
        scales.sensitivity_mod
        if look.scoping and not look.smooth_camera
        else scales.sens
    )
    return 0.15 * scale


@dataclass
class MouseLook:
    """Накопитель движения мыши (порт ``MouseLook``)."""

    look: LookOptions = None  # type: ignore[assignment]
    ignore_first_move: bool = True
    _accumulated_dx: float = 0.0
    _accumulated_dy: float = 0.0
    _last_time: float = 0.0

    def __post_init__(self) -> None:
        if self.look is None:
            self.look = LookOptions()

    def set_ignore_first_move(self) -> None:
        self.ignore_first_move = True

    def add_motion(self, dx: float, dy: float) -> None:
        """Добавить относительное движение (порт ``MouseLook::add_motion``)."""
        self._accumulated_dx += float(dx)
        self._accumulated_dy += float(dy)

    def on_move(
        self,
        xpos: float,
        ypos: float,
        xrel: float,
        yrel: float,
        window_active: bool,
        grabbed: bool,
    ) -> None:
        """``onMove``: при захваченном курсоре — относительное движение.

        Первое событие только запоминает позицию (``ignore_first_move``).
        """
        if self.ignore_first_move:
            self.ignore_first_move = False
            return
        if window_active:
            if grabbed:
                self._accumulated_dx += float(xrel)
                self._accumulated_dy += float(yrel)

    def accumulated(self) -> tuple[float, float]:
        return self._accumulated_dx, self._accumulated_dy

    def handle_accumulated_movement(self, time: float, window_active: bool, grabbed: bool):
        """Раз в кадр: ``(xo, yo)`` для ``Rotation.turn`` или ``None``.

        Накопитель очищается в любом случае (порт
        ``MouseLook::handle_accumulated_movement``).
        """
        turn = None
        if window_active and grabbed:
            turn = self.turn_player(self.look)
        self._last_time = float(time)
        self._accumulated_dx = 0.0
        self._accumulated_dy = 0.0
        return turn

    def turn_player(self, look: LookOptions) -> tuple[float, float]:
        """``turnPlayer``: масштаб чувствительности и инверсия осей."""
        scales = _sensitivity_scales(look.sensitivity)
        if look.scoping and not look.smooth_camera:
            sens = scales.sensitivity_mod
        else:
            sens = scales.sens
        xo = self._accumulated_dx * sens
        yo = self._accumulated_dy * sens
        if look.invert_x:
            xo = -xo
        if look.invert_y:
            yo = -yo
        return xo, yo
