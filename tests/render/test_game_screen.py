#!/usr/bin/env python3
"""Тесты игрового экрана QuadRix (Gameplay PART 1).

``GameScreen`` держит ввод, :class:`PlayerMotion`, камеру и плоский мир
(:class:`FlatWorld`, FALLBACK).  Проверяем: WASD двигает игрока, нажатия/
отпускания клавиш идут в :class:`InputState`, а движение мыши вращает
камеру.
"""

from __future__ import annotations

import pytest

from quadrix.render.app import GameScreen
from quadrix.render.game_world import FlatWorld
from quadrix.render.menu import Settings


def _game(**kwargs) -> GameScreen:
    """GameScreen на маленьком плоском мире (быстрый меш)."""
    kwargs.setdefault("world", FlatWorld(ground_top=1))
    kwargs.setdefault("width", 64.0)
    kwargs.setdefault("height", 48.0)
    return GameScreen(**kwargs)


def test_game_screen_motion() -> None:
    """W → ``travel`` + ``tick`` двигают игрока вперёд (+Z при yaw 0)."""
    game = _game()
    motion = game.player_motion
    z0 = motion.position.z

    # Ничего не нажато — движения нет.
    game.update(0.05)
    assert motion.position.z == pytest.approx(z0)

    assert game.handle_key_down("key.keyboard.w") is True
    for _ in range(10):
        game.update(0.05)

    assert motion.position.z > z0
    # Камера следует за игроком (позиция глаза = позиция + eye_height).
    assert game.camera.position[2] == pytest.approx(motion.position.z)
    assert game.camera.position[0] == pytest.approx(motion.position.x)
    assert game.camera.position[1] == pytest.approx(
        motion.position.y + motion.eye_height()
    )

    # Отпустили W — прирост за следующий тик существенно меньше.
    game.handle_key_up("key.keyboard.w")
    z1 = motion.position.z
    game.update(0.05)
    assert motion.position.z >= z1


def test_game_screen_handle_key() -> None:
    """keydown/keyup → :class:`InputState`; escape закрывает экран."""
    closed: list[int] = []
    game = _game(on_close=lambda: closed.append(1))

    # Ванильные клавиши идут в InputState (порт HeldKeys).
    assert game.handle_key_down("key.keyboard.w") is True
    assert game.input_state.is_down("key.keyboard.w") is True
    # Повторное нажатие уже нажатой клавиши — False.
    assert game.handle_key_down("key.keyboard.w") is False
    assert game.handle_key_up("key.keyboard.w") is True
    assert game.input_state.is_down("key.keyboard.w") is False
    # Отпускание ненажатой — False.
    assert game.handle_key_up("key.keyboard.w") is False

    # Короткое имя (меню): escape → on_close.
    assert game.handle_key("escape") is True
    assert closed == [1]
    assert game.handle_key("w") is False


def test_game_screen_handle_mouse() -> None:
    """Движение мыши вращает yaw/pitch (MouseLook → Rotation → камера)."""
    game = _game()

    assert game.handle_mouse_move(10.0, 5.0) is True
    # sensitivity 0.5 → 0.15°/ед: yaw += 10*0.15, pitch += 5*0.15.
    assert game.rotation.y_rot == pytest.approx(1.5)
    assert game.rotation.x_rot == pytest.approx(0.75)
    # yaw игрока и камера следуют за поворотом.
    assert game.player_motion.yaw == pytest.approx(1.5)
    assert game.camera.yaw == pytest.approx(1.5)
    assert game.camera.pitch == pytest.approx(0.75)

    # Пики накапливаются от кадра к кадру.
    game.handle_mouse_move(0.0, 5.0)
    assert game.rotation.y_rot == pytest.approx(1.5)
    assert game.rotation.x_rot == pytest.approx(1.5)


def test_game_screen_uses_settings_sensitivity() -> None:
    """Чувствительность берётся из Settings (mouse.rs чтит опцию)."""
    game = _game(settings=Settings(sensitivity=1.0))
    # sensitivity 1.0 → ss = 0.8, sens = 0.8^3*8 = 4.096 → 0.6144°/ед.
    game.handle_mouse_move(1.0, 0.0)
    assert game.rotation.y_rot == pytest.approx(0.15 * 4.096)
