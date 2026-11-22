#!/usr/bin/env python3
"""[QuadRix] Entity, living and player damage-immunity predicate ordering.

Port of horizon/crates/horizon-world/src/damage_immunity.rs (Minecraft 26.3).
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol

__all__ = [
    "ImmunityTag",
    "DamageRule",
    "ImmunityWorld",
    "entity_invulnerable",
    "base_immunity",
    "living_immunity",
    "player_immunity",
    "server_player_immunity",
]


class ImmunityTag(Enum):
    """``ImmunityTag`` (damage_immunity.rs:3)."""

    BypassesInvulnerability = auto()
    Fire = auto()
    Fall = auto()
    Drowning = auto()
    Freezing = auto()


class DamageRule(Enum):
    """``DamageRule`` (damage_immunity.rs:11)."""

    Drowning = auto()
    Fall = auto()
    Fire = auto()
    Freeze = auto()


class ImmunityWorld(Protocol):
    """``ImmunityWorld`` (damage_immunity.rs:17)."""

    def removed(self) -> bool:
        ...

    def permanently_invulnerable(self) -> bool:
        ...

    def temporarily_invulnerable(self) -> bool:
        ...

    def invulnerable(self) -> bool:
        ...

    def tag(self, tag: ImmunityTag) -> bool:
        ...

    def creative_source(self) -> bool:
        ...

    def fire_immune(self) -> bool:
        ...

    def fall_immune(self) -> bool:
        ...

    def enchantment_immunity(self) -> bool:
        ...

    def damage_rule(self, rule: DamageRule) -> bool:
        ...

    def changing_dimension(self) -> bool:
        ...

    def ender_pearl(self) -> bool:
        ...

    def client_loaded(self) -> bool:
        ...


def entity_invulnerable(world: ImmunityWorld) -> bool:
    """``entity_invulnerable`` (damage_immunity.rs:35)."""
    return world.permanently_invulnerable() or world.temporarily_invulnerable()


def base_immunity(world: ImmunityWorld) -> bool:
    """``base_immunity`` (damage_immunity.rs:38)."""
    if world.removed():
        return True
    if (
        world.invulnerable()
        and not world.tag(ImmunityTag.BypassesInvulnerability)
        and not world.creative_source()
    ):
        return True
    if world.tag(ImmunityTag.Fire) and world.fire_immune():
        return True
    return world.tag(ImmunityTag.Fall) and world.fall_immune()


def living_immunity(world: ImmunityWorld) -> bool:
    """``living_immunity`` (damage_immunity.rs:50)."""
    return base_immunity(world) or world.enchantment_immunity()


def player_immunity(world: ImmunityWorld) -> bool:
    """``player_immunity`` (damage_immunity.rs:53)."""
    if living_immunity(world):
        return True
    for tag, rule in (
        (ImmunityTag.Drowning, DamageRule.Drowning),
        (ImmunityTag.Fall, DamageRule.Fall),
        (ImmunityTag.Fire, DamageRule.Fire),
        (ImmunityTag.Freezing, DamageRule.Freeze),
    ):
        if world.tag(tag):
            return not world.damage_rule(rule)
    return False


def server_player_immunity(world: ImmunityWorld) -> bool:
    """``server_player_immunity`` (damage_immunity.rs:69)."""
    return (
        player_immunity(world)
        or (world.changing_dimension() and not world.ender_pearl())
        or not world.client_loaded()
    )
