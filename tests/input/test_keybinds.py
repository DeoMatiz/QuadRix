#!/usr/bin/env python3
"""Тесты биндов QuadRix (порт ``keybinds.rs``).

Проверяем, что стандартные бинды движения совпадают с Rust-таблицей
MAPPINGS и что ``KeyBinds`` переводит физическую клавишу в действие.
"""

from __future__ import annotations

from quadrix.input.keybinds import (
    KEY_UNKNOWN,
    MAPPINGS,
    MOVE_ACTIONS,
    KeyBinds,
)


def test_keybinds_default() -> None:
    """Стандартные бинды движения — ровно как в ``keybinds.rs``."""
    binds = KeyBinds()

    # Точные привязки из Rust (AGENTS.md: WASD/space/shift/ctrl как есть).
    assert binds.get("key.forward") == "key.keyboard.w"
    assert binds.get("key.left") == "key.keyboard.a"
    assert binds.get("key.back") == "key.keyboard.s"
    assert binds.get("key.right") == "key.keyboard.d"
    assert binds.get("key.jump") == "key.keyboard.space"
    assert binds.get("key.sneak") == "key.keyboard.left.shift"
    assert binds.get("key.sprint") == "key.keyboard.left.control"

    # Таблица default_of совпадает с текущими значениями.
    for action in MOVE_ACTIONS:
        assert binds.is_default(action) is True
        assert binds.get(action) == binds.default_of(action)

    # MAPPINGS содержит все действия движения.
    mapped = {name for name, _key, _cat in MAPPINGS}
    assert set(MOVE_ACTIONS) <= mapped

    # Неизвестный бинд → unknown.
    assert binds.get("key.does.not.exist") == KEY_UNKNOWN
    assert KEY_UNKNOWN not in {binds.get(a) for a in MOVE_ACTIONS}


def test_keybinds_rebind_and_reset() -> None:
    """``set`` перепривязывает, ``reset_all`` возвращает стандарт."""
    binds = KeyBinds()
    assert binds.mapping_for("key.keyboard.w") == "key.forward"

    binds.set("key.forward", "key.keyboard.up")
    assert binds.get("key.forward") == "key.keyboard.up"
    assert binds.is_default("key.forward") is False
    assert binds.mapping_for("key.keyboard.up") == "key.forward"

    # Несуществующий бинд молча игнорируется.
    binds.set("key.not.a.bind", "key.keyboard.up")
    assert binds.get("key.not.a.bind") == KEY_UNKNOWN

    binds.reset_all()
    assert binds.get("key.forward") == "key.keyboard.w"
    assert binds.is_default("key.forward") is True
