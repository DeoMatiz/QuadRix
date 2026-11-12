#!/usr/bin/env python3
"""Бинды клавиш QuadRix (порт ``horizon-client-input/src/keybinds.rs``).

MAPPINGS — ванильный список ``Options.keyMappings`` в его порядке
(``(имя, клавиша по умолчанию, категория)``); HORIZON_MAPPINGS — бинды
самого Horizon.  ``KeyBinds`` — текущие привязки и перевод физической
клавиши в действие.

Правило проекта: WASD/space/shift/ctrl берём из Rust как есть:
    key.forward -> key.keyboard.w
    key.left    -> key.keyboard.a
    key.back    -> key.keyboard.s
    key.right   -> key.keyboard.d
    key.jump    -> key.keyboard.space
    key.sneak   -> key.keyboard.left.shift
    key.sprint  -> key.keyboard.left.control
"""

from __future__ import annotations

from typing import Iterator, Optional

__all__ = [
    "CATEGORIES",
    "HORIZON_MAPPINGS",
    "KEY_UNKNOWN",
    "MAPPINGS",
    "MOVE_ACTIONS",
    "KeyBinds",
    "all_mappings",
    "is_toggle",
]

#: Клавиша без привязки (``KeyBinds::get`` по умолчанию).
KEY_UNKNOWN = "key.keyboard.unknown"

#: ``MAPPINGS`` из keybinds.rs — (имя, ключ по умолчанию, категория).
MAPPINGS: tuple[tuple[str, str, str], ...] = (
    ("key.attack", "key.mouse.left", "gameplay"),
    ("key.use", "key.mouse.right", "gameplay"),
    ("key.forward", "key.keyboard.w", "movement"),
    ("key.left", "key.keyboard.a", "movement"),
    ("key.back", "key.keyboard.s", "movement"),
    ("key.right", "key.keyboard.d", "movement"),
    ("key.jump", "key.keyboard.space", "movement"),
    ("key.sneak", "key.keyboard.left.shift", "movement"),
    ("key.sprint", "key.keyboard.left.control", "movement"),
    ("key.drop", "key.keyboard.q", "inventory"),
    ("key.inventory", "key.keyboard.e", "inventory"),
    ("key.chat", "key.keyboard.t", "multiplayer"),
    ("key.playerlist", "key.keyboard.tab", "multiplayer"),
    ("key.pickItem", "key.mouse.middle", "gameplay"),
    ("key.command", "key.keyboard.slash", "multiplayer"),
    ("key.friends", "key.keyboard.o", "multiplayer"),
    ("key.socialInteractions", "key.keyboard.p", "multiplayer"),
    ("key.toggleGui", "key.keyboard.f1", "misc"),
    ("key.toggleSpectatorShaderEffects", "key.keyboard.f4", "misc"),
    ("key.screenshot", "key.keyboard.f2", "misc"),
    ("key.togglePerspective", "key.keyboard.f5", "misc"),
    ("key.smoothCamera", "key.keyboard.unknown", "misc"),
    ("key.fullscreen", "key.keyboard.f11", "misc"),
    ("key.spectatorOutlines", "key.keyboard.unknown", "spectator"),
    ("key.spectatorHotbar", "key.mouse.middle", "spectator"),
    ("key.swapOffhand", "key.keyboard.f", "inventory"),
    ("key.saveToolbarActivator", "key.keyboard.c", "creative"),
    ("key.loadToolbarActivator", "key.keyboard.x", "creative"),
    ("key.advancements", "key.keyboard.l", "misc"),
    ("key.quickActions", "key.keyboard.g", "misc"),
    ("key.debug.overlay", "key.keyboard.f3", "debug"),
    ("key.debug.modifier", "key.keyboard.f3", "debug"),
    ("key.hotbar.1", "key.keyboard.1", "inventory"),
    ("key.hotbar.2", "key.keyboard.2", "inventory"),
    ("key.hotbar.3", "key.keyboard.3", "inventory"),
    ("key.hotbar.4", "key.keyboard.4", "inventory"),
    ("key.hotbar.5", "key.keyboard.5", "inventory"),
    ("key.hotbar.6", "key.keyboard.6", "inventory"),
    ("key.hotbar.7", "key.keyboard.7", "inventory"),
    ("key.hotbar.8", "key.keyboard.8", "inventory"),
    ("key.hotbar.9", "key.keyboard.9", "inventory"),
)

#: ``HORIZON_MAPPINGS`` — собственные бинды Horizon (emote wheel).
HORIZON_MAPPINGS: tuple[tuple[str, str, str], ...] = (
    ("key.emote", "key.keyboard.b", "multiplayer"),
)

#: Категории в порядке ``KeyMapping.Category``.
CATEGORIES: tuple[str, ...] = (
    "movement",
    "misc",
    "multiplayer",
    "gameplay",
    "inventory",
    "creative",
    "spectator",
    "debug",
)

#: Действия движения, которые читает PlayerMotion (порт ``sprint.rs::Keys``).
MOVE_ACTIONS: tuple[str, ...] = (
    "key.forward",
    "key.back",
    "key.left",
    "key.right",
    "key.jump",
    "key.sneak",
    "key.sprint",
)


def all_mappings() -> Iterator[tuple[str, str, str]]:
    """Все бинды игры: ванильные, затем бинды Horizon."""
    yield from MAPPINGS
    yield from HORIZON_MAPPINGS


def is_toggle(name: str) -> bool:
    """``keybinds::is_toggle``: hold или toggle (зависит от опции)."""
    return name in ("key.sneak", "key.sprint", "key.use", "key.attack")


class KeyBinds:
    """Текущие привязки по имени бинда (порт ``KeyBinds``)."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {name: key for name, key, _ in all_mappings()}

    def get(self, name: str) -> str:
        """Клавиша, привязанная к ``name`` (или ``key.keyboard.unknown``)."""
        return self.keys.get(name, KEY_UNKNOWN)

    @staticmethod
    def default_of(name: str) -> str:
        """Клавиша по умолчанию для ``name``."""
        for n, key, _ in all_mappings():
            if n == name:
                return key
        return KEY_UNKNOWN

    def is_default(self, name: str) -> bool:
        return self.get(name) == self.default_of(name)

    def set(self, name: str, key: str) -> None:
        """Перепривязать ``name`` на ``key`` (только существующие бинды)."""
        if any(n == name for n, _, _ in all_mappings()):
            self.keys[name] = key

    def reset_all(self) -> None:
        self.keys = {name: key for name, key, _ in all_mappings()}

    def mappings_for(self, key: str) -> Iterator[str]:
        """Все бинды, привязанные к физической клавише ``key``, по порядку."""
        for n, _, _ in all_mappings():
            if self.get(n) == key:
                yield n

    def mapping_for(self, key: str) -> Optional[str]:
        """Первый бинд, привязанный к ``key`` (порт ``KeyBinds::mapping_for``)."""
        return next(self.mappings_for(key), None)

    def conflicts(self, name: str) -> list[str]:
        """Бинды, делящие клавишу с ``name`` (для пометок конфликта)."""
        key = self.get(name)
        if key == KEY_UNKNOWN:
            return []
        return [
            n
            for n, _, _ in all_mappings()
            if n != name
            and self.get(n) == key
            and (not self.is_default(n) or not self.is_default(name))
        ]
