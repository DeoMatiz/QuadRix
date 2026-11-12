#!/usr/bin/env python3
"""Тесты состояния ввода QuadRix (порт ``input.rs`` / ``held.rs``).

Проверяем WASD → ``(strafe, forward)`` ровно как
``input::keyboard_direction`` в Rust, сборку :class:`PlayerInput` и прыжок
(``key.jump`` из Rust = space).
"""

from __future__ import annotations

import math

import pytest

from quadrix.input.input_state import InputState, keyboard_direction
from quadrix.input.keybinds import KeyBinds


def test_input_state_wasd() -> None:
    """W/S/A/D → направление как в ``input::keyboard_direction`` (Rust)."""
    state = InputState()
    binds = KeyBinds()

    # Ничего не нажато — нет движения.
    assert state.direction(binds) == (0.0, 0.0)

    # W: forward = +1 (юг, +Z при yaw 0).
    assert state.press("key.keyboard.w") is True
    assert state.to_player_input(binds).forward == pytest.approx(1.0)
    assert state.direction(binds) == (0.0, 1.0)

    # S гасит W (обе оси положительная+отрицательная → 0).
    assert state.press("key.keyboard.s") is True
    assert state.direction(binds) == (0.0, 0.0)
    state.release("key.keyboard.w")
    assert state.direction(binds) == (0.0, -1.0)
    state.release("key.keyboard.s")

    # A: strafe = +1 (влево), D: strafe = -1 (вправо) — как impulse(left, right).
    assert state.press("key.keyboard.a") is True
    assert state.direction(binds) == (1.0, 0.0)
    assert state.press("key.keyboard.d") is True
    assert state.direction(binds) == (0.0, 0.0)
    state.release("key.keyboard.a")
    assert state.direction(binds) == (-1.0, 0.0)

    # Диагональ нормализуется (не быстрее прямой): W+D.
    state.release("key.keyboard.d")
    state.press("key.keyboard.w")
    state.press("key.keyboard.d")
    strafe, forward = state.direction(binds)
    assert strafe == pytest.approx(-1.0 / math.sqrt(2.0))
    assert forward == pytest.approx(1.0 / math.sqrt(2.0))

    # Прямая проверка самой функции (без KeyBinds).
    assert keyboard_direction(False, False, False, False) == (0.0, 0.0)
    assert keyboard_direction(True, False, False, False) == (0.0, 1.0)
    assert keyboard_direction(False, True, False, False) == (0.0, -1.0)
    assert keyboard_direction(False, False, True, False) == (1.0, 0.0)
    assert keyboard_direction(False, False, False, True) == (-1.0, 0.0)


def test_input_state_jump() -> None:
    """space → ``key.jump`` → :attr:`PlayerInput.jump` (порт ``held.rs``)."""
    state = InputState()
    binds = KeyBinds()

    assert state.to_player_input(binds).jump is False
    assert state.press("key.keyboard.space") is True
    assert state.to_player_input(binds).jump is True
    # Повторное нажатие той же клавиши ничего не меняет.
    assert state.press("key.keyboard.space") is False
    assert state.is_down("key.keyboard.space") is True
    assert state.release("key.keyboard.space") is True
    assert state.to_player_input(binds).jump is False


def test_input_state_sneak_and_sprint() -> None:
    """shift → sneak, ctrl → sprint (поля из ``sprint.rs::Keys``)."""
    state = InputState()
    binds = KeyBinds()

    state.press("key.keyboard.left.shift")
    state.press("key.keyboard.left.control")
    player_input = state.to_player_input(binds)
    assert player_input.sneak is True
    assert player_input.sprint is True
    assert player_input.jump is False

    state.release("key.keyboard.left.shift")
    assert state.to_player_input(binds).sneak is False
    assert state.to_player_input(binds).sprint is True
