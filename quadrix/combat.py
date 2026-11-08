# Ported from horizon/crates/horizon-client/src/game/combat.rs
# ONLY the armor and knockback parts used by health.rs PART 2:
# - armor item stats (minecraft:armor / minecraft:armor_toughness)
# - vanilla armor damage reduction (combat_rules::after_armor)
# - knockback strength (Knockback enchantment / attack knockback)
# - armor durability loss (LivingEntity.hurtArmor -> doHurtEquipment)
#
# Not ported here: attacks, sweep, crit, shields, weapon damage,
# enchantments, sweeping edge and attack cooldown.

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

__all__ = [
    "ArmorItem",
    "KnockbackEnchantment",
    "armor_reduction",
    "armor_damage_blocked",
    "armor_toughness",
    "total_armor",
    "knockback_strength",
    "knockback_attack_power",
    "hurt_armor",
    "load_armor_item",
]


# The vanilla armor formula lives in horizon-world/src/combat_rules.rs:
#   divisor = 2.0 + toughness / 4.0
#   protection = clamp(armor - damage / divisor, armor * 0.2, 20.0)
#   effectiveness = protection / 25.0
#   damage * (1.0 - effectiveness)
ARMOR_MAX_PROTECTION = 20.0
ARMOR_EFFECTIVENESS_SCALE = 25.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Port of combat_rules::clamp (Java Math.clamp semantics)."""
    if value < minimum:
        return minimum
    if math.isnan(value) or math.isnan(maximum):
        return math.nan
    return min(value, maximum)


@dataclass(frozen=True)
class ArmorItem:
    """One worn armor piece's combat stats."""

    armor_points: float
    toughness: float = 0.0
    max_damage: int = 0
    item: str = ""


def armor_toughness(item: ArmorItem) -> float:
    """`minecraft:armor_toughness` contributed by a piece."""
    return float(item.toughness)


def total_armor(pieces: Iterable[ArmorItem]) -> tuple[float, float]:
    """Summed (armor, toughness) of the worn pieces.

    `LivingEntity.getArmorValue` floors the effective armor, while toughness
    converts directly (mobs/armor.rs::values).
    """
    armor = 0.0
    toughness = 0.0
    for piece in pieces:
        armor += float(piece.armor_points)
        toughness += float(piece.toughness)
    return float(math.floor(armor)), float(toughness)


def armor_reduction(armor: float, toughness: float, damage: float) -> float:
    """Damage left after the vanilla armor formula.

    Mirrors `combat_rules::after_armor` with no weapon armor-effectiveness
    modifier:
        divisor = 2 + toughness / 4
        protection = clamp(armor - damage / divisor, armor * 0.2, 20)
        effectiveness = protection / 25
        result = damage * (1 - effectiveness)

    With no armor this returns the damage unchanged.
    """
    armor = float(armor)
    toughness = float(toughness)
    damage = float(damage)

    divisor = 2.0 + toughness / 4.0
    protection = _clamp(
        armor - damage / divisor,
        armor * 0.2,
        ARMOR_MAX_PROTECTION,
    )
    effectiveness = protection / ARMOR_EFFECTIVENESS_SCALE
    return damage * (1.0 - effectiveness)


def armor_damage_blocked(armor: float, toughness: float, damage: float) -> float:
    """How much of `damage` the armor absorbed."""
    return float(damage) - armor_reduction(armor, toughness, damage)


@dataclass(frozen=True)
class KnockbackEnchantment:
    """The Knockback enchantment's added push."""

    level: int

    @property
    def strength(self) -> float:
        return knockback_strength(self.level)


def knockback_strength(level: int) -> float:
    """Vanilla base knockback plus 0.1 per Knockback enchantment level."""
    level = int(level)
    # Round away binary-float noise so level 2 is exactly 0.6, not
    # 0.6000000000000001.
    return round(0.4 + 0.1 * level, 10)


def knockback_attack_power(base: float, level: int = 0) -> float:
    """`LivingEntity.getKnockback`, halved for the melee push.

    Rust health.rs: `(attack_knockback + enchantment) / 2.0`.
    """
    return (float(base) + knockback_strength(level)) / 2.0


def hurt_armor(damage: float) -> int:
    """Durability a worn piece loses for a hit of `damage`.

    `LivingEntity.hurtArmor` -> `doHurtEquipment`:
        amount = max(1, damage / 4)  (integer division)
    A non-positive hit wears nothing. Unbreaking is applied by the caller's
    enchantment processing, not here.
    """
    if damage <= 0.0:
        return 0
    return max(1, int(damage / 4.0))


def load_armor_item(path: str | Path) -> ArmorItem:
    """Load an armor piece's stats from a vanilla item component report.

    Reads `minecraft:attribute_modifiers` entries of type
    `minecraft:armor` and `minecraft:armor_toughness`, as the Rust item
    resources expose them.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    components = data.get("components", data)
    modifiers = components.get("minecraft:attribute_modifiers", [])

    armor = 0.0
    toughness = 0.0
    for modifier in modifiers:
        if not isinstance(modifier, dict):
            continue
        kind = modifier.get("type")
        amount = float(modifier.get("amount", 0.0))
        if kind == "minecraft:armor":
            armor += amount
        elif kind == "minecraft:armor_toughness":
            toughness += amount

    max_damage = int(components.get("minecraft:max_damage", 0) or 0)
    return ArmorItem(
        armor_points=armor,
        toughness=toughness,
        max_damage=max_damage,
        item=path.stem,
    )
