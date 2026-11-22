#!/usr/bin/env python3
"""[QuadRix] Living damage-source bypass, armor and resistance protection.

Port of horizon/crates/horizon-world/src/damage_reduction.rs (Minecraft 26.3).
Also ports the two ``combat_rules`` damage arithmetic functions it dispatches
to (``combat_rules::after_armor`` / ``combat_rules::after_magic``).
"""

from __future__ import annotations

import math
import struct
from enum import Enum, auto
from typing import Optional, Protocol

__all__ = [
    "Bypass",
    "DamageReductionWorld",
    "armor_from_attribute",
    "after_armor",
    "after_magic",
    "combat_after_armor",
    "combat_after_magic",
]

#: ``living_damage::STAT_LIMIT``.
STAT_LIMIT: float = 3.4028235e37
MAX_F32: float = 3.4028235e38


# ---------------------------------------------------------------------------
# f32 helpers
# ---------------------------------------------------------------------------

def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _clamp_f32(value: float, minimum: float, maximum: float) -> float:
    value = float(value)
    if value < minimum:
        return float(minimum)
    if value != value or maximum != maximum:
        return float("nan")
    if value == 0.0 and maximum == 0.0:
        bits = struct.unpack("<I", struct.pack("<f", value))[0] | struct.unpack(
            "<I", struct.pack("<f", maximum)
        )[0]
        return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]
    return value if value < maximum else float(maximum)


def _wrap_i32(value: int) -> int:
    """Rust ``i32`` wrapping."""
    return ((int(value) + 2**31) % 2**32) - 2**31


def _positive(value: float) -> float:
    """``living_damage::positive``."""
    if value != value:
        return value
    if value <= 0.0:
        return 0.0
    return value


def _stat_amount(value: float) -> int:
    """``living_damage::stat_amount`` (Java ``Math.round(float)``)."""
    scaled = value * 10.0
    if scaled != scaled or math.isinf(scaled):
        return 0
    rounded = math.floor(scaled + 0.5)
    if rounded > 2_147_483_647:
        return 2_147_483_647
    if rounded < -2_147_483_648:
        return -2_147_483_648
    return int(rounded)


# ---------------------------------------------------------------------------
# Bypass — damage_reduction.rs:7
# ---------------------------------------------------------------------------

class Bypass(Enum):
    Armor = auto()
    Effects = auto()
    Resistance = auto()
    Enchantments = auto()


class DamageReductionWorld(Protocol):
    """``DamageReductionWorld`` (damage_reduction.rs:13)."""

    def bypasses(self, kind: Bypass) -> bool:
        ...

    def hurt_armor(self, damage: float) -> None:
        ...

    def armor_value(self) -> int:
        ...

    def toughness_attribute(self) -> float:
        ...

    def has_resistance(self) -> bool:
        ...

    def resistance_amplifier(self) -> int:
        ...

    def victim_is_server_player(self) -> bool:
        ...

    def award_resisted(self, amount: int) -> None:
        ...

    def attacker_is_server_player(self) -> bool:
        ...

    def award_dealt_resisted(self, amount: int) -> None:
        ...

    def damage_protection(self, level) -> float:
        ...

    # ArmorWorld (combat_rules.rs:13)
    def weapon(self):
        ...

    def server_level(self):
        ...

    def modify_armor_effectiveness(self, level, weapon, effectiveness: float) -> float:
        ...


# ---------------------------------------------------------------------------
# combat_rules.rs
# ---------------------------------------------------------------------------

def armor_from_attribute(value: float) -> int:
    """``damage_reduction::armor_from_attribute`` (damage_reduction.rs:27)."""
    return int(math.floor(float(value)))


def combat_after_armor(
    world: DamageReductionWorld,
    damage: float,
    armor: float,
    toughness: float,
) -> float:
    """``combat_rules::after_armor`` (combat_rules.rs:28)."""
    damage = _f32(damage)
    armor = _f32(armor)
    toughness = _f32(toughness)
    divisor = _f32(2.0 + _f32(toughness / 4.0))
    protection = _clamp_f32(
        _f32(armor - _f32(damage / divisor)), _f32(armor * 0.2), 20.0
    )
    effectiveness = _f32(protection / 25.0)
    weapon = world.weapon()
    if weapon is not None:
        level = world.server_level()
        if level is not None:
            effectiveness = _clamp_f32(
                world.modify_armor_effectiveness(level, weapon, effectiveness), 0.0, 1.0
            )
    return _f32(damage * _f32(1.0 - effectiveness))


def combat_after_magic(damage: float, protection: float) -> float:
    """``combat_rules::after_magic`` (combat_rules.rs:48)."""
    damage = _f32(damage)
    protection = _clamp_f32(protection, 0.0, 20.0)
    return _f32(damage * _f32(1.0 - _f32(protection / 25.0)))


# ---------------------------------------------------------------------------
# after_armor / after_magic — damage_reduction.rs:30, :39
# ---------------------------------------------------------------------------

def after_armor(world: DamageReductionWorld, damage: float) -> float:
    """``after_armor`` (damage_reduction.rs:30)."""
    if world.bypasses(Bypass.Armor):
        return damage
    world.hurt_armor(damage)
    armor = _f32(float(world.armor_value()))
    toughness = _f32(float(world.toughness_attribute()))
    return combat_after_armor(world, damage, armor, toughness)


def after_magic(world: DamageReductionWorld, damage: float) -> float:
    """``after_magic`` (damage_reduction.rs:39)."""
    if world.bypasses(Bypass.Effects):
        return damage
    if world.has_resistance() and not world.bypasses(Bypass.Resistance):
        reduction = _wrap_i32(_wrap_i32(world.resistance_amplifier() + 1) * 5)
        remainder = _wrap_i32(25 - reduction)
        original = damage
        damage = _positive(_f32(_f32(damage * remainder) / 25.0))
        resisted = _f32(original - damage)
        if 0.0 < resisted < STAT_LIMIT:
            if world.victim_is_server_player():
                world.award_resisted(_stat_amount(resisted))
            elif world.attacker_is_server_player():
                world.award_dealt_resisted(_stat_amount(resisted))
    if damage <= 0.0:
        return 0.0
    if world.bypasses(Bypass.Enchantments):
        return damage
    level = world.server_level()
    protection = world.damage_protection(level) if level is not None else 0.0
    if protection > 0.0:
        damage = combat_after_magic(damage, protection)
    return damage
