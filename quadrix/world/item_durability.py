#!/usr/bin/env python3
"""[QuadRix] Item-stack durability storage and mutation ordering.

Port of horizon/crates/horizon-world/src/item_durability.rs (Minecraft 26.3).

This is the durability projection of a stack, not a replacement for its
complete component map.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Optional, Protocol

__all__ = [
    "DurabilityStack",
    "DurabilityStorage",
    "DurabilityWorld",
    "unenchanted_change",
    "process_change",
    "apply_damage",
    "hurt_and_break",
    "hurt_without_breaking",
]

_I32_MIN = -2_147_483_648
_I32_MAX = 2_147_483_647


def _wrap_i32(value: int) -> int:
    return ((int(value) + 2**31) % 2**32) - 2**31


def _i32_from_f32(value: float) -> int:
    """Rust ``(amount as f32) as i32``: truncate toward zero, saturating."""
    rounded = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    if rounded != rounded:
        return 0
    if rounded >= _I32_MAX:
        return _I32_MAX
    if rounded <= _I32_MIN:
        return _I32_MIN
    return int(rounded)


# ---------------------------------------------------------------------------
# DurabilityStack — item_durability.rs:3
# ---------------------------------------------------------------------------

@dataclass
class DurabilityStack:
    count: int
    air: bool
    max_damage: Optional[int]
    damage: Optional[int]
    unbreakable: bool

    def is_empty(self) -> bool:
        return self.air or self.count <= 0

    def count_(self) -> int:
        return 0 if self.is_empty() else self.count

    def max_damage_(self) -> int:
        if self.is_empty():
            return 0
        return 0 if self.max_damage is None else self.max_damage

    def damage_(self) -> int:
        if self.is_empty():
            value = 0
        else:
            value = 0 if self.damage is None else self.damage
        return max(0, min(value, self.max_damage_()))

    def set_damage(self, value: int) -> None:
        self.damage = max(0, min(int(value), self.max_damage_()))

    def is_damageable(self) -> bool:
        return (
            not self.is_empty()
            and self.max_damage is not None
            and not self.unbreakable
            and self.damage is not None
        )

    def is_damaged(self) -> bool:
        return self.is_damageable() and self.damage_() > 0

    def is_broken(self) -> bool:
        return self.is_damageable() and self.damage_() >= self.max_damage_()

    def next_damage_will_break(self) -> bool:
        return self.is_damageable() and self.damage_() >= _wrap_i32(self.max_damage_() - 1)

    def grow(self, amount: int) -> None:
        self.count = _wrap_i32(self.count_() + int(amount))

    def shrink(self, amount: int) -> None:
        self.grow(_wrap_i32(-int(amount)))


class DurabilityStorage(Protocol):
    """``DurabilityStorage`` (item_durability.rs:59)."""

    def is_damageable(self) -> bool:
        ...

    def damage_(self) -> int:
        ...

    def max_damage_(self) -> int:
        ...

    def set_damage(self, value: int) -> None:
        ...

    def is_broken(self) -> bool:
        ...

    def shrink(self, amount: int) -> None:
        ...


class DurabilityWorld(Protocol):
    """``DurabilityWorld`` (item_durability.rs:90)."""

    def infinite_materials(self, stack) -> bool:
        ...

    def process_enchantments(self, stack, amount: int) -> int:
        ...

    def durability_changed(self, stack, damage: int) -> None:
        ...

    def broken(self, stack, copy) -> None:
        ...


# ---------------------------------------------------------------------------
# Durability algorithm — item_durability.rs:111
# ---------------------------------------------------------------------------

def unenchanted_change(amount: int) -> int:
    """``unenchanted_change`` (item_durability.rs:111)."""
    return _i32_from_f32(float(amount))


def process_change(
    stack, world: DurabilityWorld, amount: int, server_player: bool
) -> int:
    """``process_change`` (item_durability.rs:115)."""
    if not stack.is_damageable() or (server_player and world.infinite_materials(stack)):
        return 0
    if amount > 0:
        return world.process_enchantments(stack, amount)
    return amount


def apply_damage(
    stack, world: DurabilityWorld, damage: int, server_player: bool
) -> None:
    """``apply_damage`` (item_durability.rs:131)."""
    _apply_damage_with_break_callback(stack, world, damage, server_player, True)


def _apply_damage_with_break_callback(
    stack, world: DurabilityWorld, damage: int, server_player: bool, notify_break: bool
) -> None:
    """``apply_damage_with_break_callback`` (item_durability.rs:140)."""
    if server_player:
        world.durability_changed(stack, damage)
    stack.set_damage(damage)
    if stack.is_broken():
        copy = replace(stack)
        stack.shrink(1)
        if notify_break:
            world.broken(stack, copy)


def hurt_and_break(
    stack, world: DurabilityWorld, amount: int, server_player: bool
) -> None:
    """``hurt_and_break`` (item_durability.rs:162)."""
    amount = process_change(stack, world, amount, server_player)
    if amount != 0:
        damage = _wrap_i32(stack.damage_() + amount)
        apply_damage(stack, world, damage, server_player)


def hurt_without_breaking(stack, world: DurabilityWorld, amount: int) -> None:
    """``hurt_without_breaking`` (item_durability.rs:177)."""
    amount = process_change(stack, world, amount, True)
    if amount != 0:
        damage = min(
            _wrap_i32(stack.damage_() + amount),
            _wrap_i32(stack.max_damage_() - 1),
        )
        _apply_damage_with_break_callback(stack, world, damage, True, False)
