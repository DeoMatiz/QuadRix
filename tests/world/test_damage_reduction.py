#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/damage_reduction.py.

Port of horizon-world/src/damage_reduction.rs and combat_rules.rs helpers.
"""

from __future__ import annotations

import math

import pytest

from quadrix.world.damage_reduction import (
    Bypass,
    after_armor,
    after_magic,
    armor_from_attribute,
    combat_after_armor,
    combat_after_magic,
)


class _World:
    def __init__(self, **overrides) -> None:
        self._bypasses: set[Bypass] = set()
        self._armor_value = 0
        self._toughness = 0.0
        self._has_resistance = False
        self._resistance_amplifier = 0
        self._victim_is_server_player = False
        self._attacker_is_server_player = False
        self._damage_protection_value = 0.0
        self._weapon = None
        self._server_level = None
        self.hurt_calls: list[float] = []
        self.resisted: list[int] = []
        self.dealt_resisted: list[int] = []
        self.modified: list[tuple] = []
        for key, value in overrides.items():
            setattr(self, "_" + key, value)

    def bypasses(self, kind: Bypass) -> bool:
        return kind in self._bypasses

    def hurt_armor(self, damage: float) -> None:
        self.hurt_calls.append(damage)

    def armor_value(self) -> int:
        return self._armor_value

    def toughness_attribute(self) -> float:
        return self._toughness

    def has_resistance(self) -> bool:
        return self._has_resistance

    def resistance_amplifier(self) -> int:
        return self._resistance_amplifier

    def victim_is_server_player(self) -> bool:
        return self._victim_is_server_player

    def award_resisted(self, amount: int) -> None:
        self.resisted.append(amount)

    def attacker_is_server_player(self) -> bool:
        return self._attacker_is_server_player

    def award_dealt_resisted(self, amount: int) -> None:
        self.dealt_resisted.append(amount)

    def damage_protection(self, level) -> float:
        return self._damage_protection_value

    def weapon(self):
        return self._weapon

    def server_level(self):
        return self._server_level

    def modify_armor_effectiveness(self, level, weapon, effectiveness: float) -> float:
        self.modified.append((level, weapon, effectiveness))
        return effectiveness


def test_armor_from_attribute_floors():
    assert armor_from_attribute(0.0) == 0
    assert armor_from_attribute(10.9) == 10
    assert armor_from_attribute(-1.5) == -2


def test_combat_after_armor_vanilla_formula():
    # armor=20, toughness=0, damage=10:
    #   divisor = 2; protection = clamp(20 - 5, 4, 20) = 15
    #   effectiveness = 0.6; remaining = 10 * 0.4 = 4
    world = _World()
    result = combat_after_armor(world, 10.0, 20.0, 0.0)
    assert result == pytest.approx(4.0, abs=1e-5)


def test_combat_after_armor_passes_through_server_weapon_modifier():
    world = _World(weapon="minecraft:trident", server_level="overworld")
    result = combat_after_armor(world, 10.0, 20.0, 0.0)
    assert world.modified, "server weapon should trigger effectiveness modifier"
    assert result == pytest.approx(4.0, abs=1e-5)


def test_after_armor_bypasses_and_hurts():
    world = _World(armor_value=20)
    assert after_armor(world, 10.0) == pytest.approx(4.0, abs=1e-5)
    assert world.hurt_calls == [10.0]

    bypass = _World(bypasses={Bypass.Armor}, armor_value=20)
    assert after_armor(bypass, 10.0) == 10.0
    assert bypass.hurt_calls == []


def test_after_magic_resistance_reduces_and_awards_stats():
    world = _World(
        has_resistance=True,
        resistance_amplifier=1,
        victim_is_server_player=True,
    )
    # reduction = (1 + 1) * 5 = 10; remainder = 15; 10 * 15/25 = 6
    assert after_magic(world, 10.0) == pytest.approx(6.0, abs=1e-5)
    assert world.resisted == [40]

    attacker = _World(
        has_resistance=True,
        resistance_amplifier=1,
        attacker_is_server_player=True,
    )
    after_magic(attacker, 10.0)
    assert attacker.resisted == []
    assert attacker.dealt_resisted == [40]


def test_after_magic_bypasses_effects_and_resistance():
    effects = _World(bypasses={Bypass.Effects}, has_resistance=True)
    assert after_magic(effects, 10.0) == 10.0

    resistance = _World(
        bypasses={Bypass.Resistance}, has_resistance=True, resistance_amplifier=1
    )
    assert after_magic(resistance, 10.0) == pytest.approx(10.0)


def test_after_magic_protection_enchantment_and_clamp():
    world = _World(damage_protection_value=5.0, server_level="overworld")
    assert after_magic(world, 10.0) == pytest.approx(8.0, abs=1e-5)
    # Protection clamps to 20, leaving 10 * (1 - 20/25) = 2.
    assert combat_after_magic(10.0, 25.0) == pytest.approx(2.0, abs=1e-5)
    assert combat_after_magic(10.0, -5.0) == pytest.approx(10.0)


def test_after_magic_non_positive_damage_short_circuits():
    world = _World(damage_protection_value=5.0)
    assert after_magic(world, 0.0) == 0.0
    assert after_magic(world, -3.0) == 0.0


def test_after_magic_enchantment_bypass_skips_protection():
    world = _World(
        bypasses={Bypass.Enchantments},
        damage_protection_value=5.0,
        server_level="overworld",
    )
    assert after_magic(world, 10.0) == pytest.approx(10.0)