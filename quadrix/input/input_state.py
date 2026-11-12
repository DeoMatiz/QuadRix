#!/usr/bin/env python3
"""Состояние ввода QuadRix (порт ``horizon-client-input/src/held.rs`` +
``input.rs``).

``InputState`` хранит нажатые клавиши по ванильным именам
(``key.keyboard.w`` и т.п.) и накопленное движение мыши.  Из этого
состояния собирается :class:`quadrix.motion.core.PlayerInput` — ровно так
же, как ``remote.rs`` собирает ``sprint::Keys`` из ``Keys::held``.

Направление ``(strafe, forward)`` считается ``input::keyboard_direction``:
обе оси нормализуются, диагональ не быстрее прямой.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from quadrix.input.keybinds import KeyBinds, MOVE_ACTIONS
from quadrix.motion.core import PlayerInput

__all__ = [
    "InputState",
    "keyboard_direction",
]


def keyboard_direction(
    forward: bool, backward: bool, left: bool, right: bool
) -> tuple[float, float]:
    """``input::keyboard_direction``: возвращает ``(strafe, forward)``.

    ``impulse`` даёт 1, если нажата только положительная ось, -1 — только
    отрицательная, 0 — если обе или ни одной. Вектор нормализуется
    (диагональ не быстрее прямой); при нуле — ``(0, 0)``.
    """
    def impulse(positive: bool, negative: bool) -> float:
        if positive == negative:
            return 0.0
        return 1.0 if positive else -1.0

    strafe = impulse(left, right)
    fwd = impulse(forward, backward)
    magnitude = math.sqrt(strafe * strafe + fwd * fwd)
    if magnitude < 1.0e-4:
        return 0.0, 0.0
    return strafe / magnitude, fwd / magnitude


@dataclass
class InputState:
    """Нажатые клавиши + движение мыши (порт ``HeldKeys`` + ``MouseLook``)."""

    #: Нажатые клавиши по ванильным именам (``key.keyboard.w``).
    keys: set[str] = field(default_factory=set)
    #: Накопленный сдвиг мыши за кадр (порт ``MouseLook.accumulated``).
    mouse_dx: float = 0.0
    mouse_dy: float = 0.0

    # -- клавиши --------------------------------------------------------

    def press(self, key: str) -> bool:
        """Нажать клавишу. ``True``, если она не была нажата раньше."""
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    def release(self, key: str) -> bool:
        """Отпустить клавишу. ``True``, если она была нажата."""
        if key not in self.keys:
            return False
        self.keys.discard(key)
        return True

    def is_down(self, key: str) -> bool:
        return key in self.keys

    def held(self, action: str, keybinds: KeyBinds | None = None) -> bool:
        """Нажат ли бинд ``action`` (порт ``HeldKeys::held``).

        ``keybinds`` — текущие привязки (по умолчанию — стандартные).
        """
        binds = keybinds if keybinds is not None else KeyBinds()
        key = binds.get(action)
        if key == "key.keyboard.unknown":
            return False
        return self.is_down(key)

    # -- мышь -----------------------------------------------------------

    def add_mouse(self, dx: float, dy: float) -> None:
        """Добавить сдвиг мыши в накопитель кадра."""
        self.mouse_dx += float(dx)
        self.mouse_dy += float(dy)

    def take_mouse_delta(self) -> tuple[float, float]:
        """Забрать накопленный сдвиг мыши и очистить его."""
        delta = (self.mouse_dx, self.mouse_dy)
        self.mouse_dx = 0.0
        self.mouse_dy = 0.0
        return delta

    # -- сборка ввода ---------------------------------------------------

    def direction(self, keybinds: KeyBinds | None = None) -> tuple[float, float]:
        """``(strafe, forward)`` из нажатых клавиш (порт ``Keys::direction``)."""
        return keyboard_direction(
            self.held("key.forward", keybinds),
            self.held("key.back", keybinds),
            self.held("key.left", keybinds),
            self.held("key.right", keybinds),
        )

    def to_player_input(self, keybinds: KeyBinds | None = None) -> PlayerInput:
        """Собрать :class:`PlayerInput` из нажатых клавиш.

        Порт ``remote.rs``: ``forward/back/left/right`` → направление,
        ``jump/sneak/sprint`` — отдельными флагами.
        """
        strafe, forward = self.direction(keybinds)
        return PlayerInput(
            forward=forward,
            strafe=strafe,
            jump=self.held("key.jump", keybinds),
            sneak=self.held("key.sneak", keybinds),
            sprint=self.held("key.sprint", keybinds),
        )
