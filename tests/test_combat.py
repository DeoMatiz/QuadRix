"""Tests for quadrix.combat - armor and knockback (combat.rs port)."""

import math
from pathlib import Path

import pytest

from quadrix.combat import (
    ArmorItem,
    KnockbackEnchantment,
    armor_damage_blocked,
    armor_reduction,
    armor_toughness,
    hurt_armor,
    knockback_attack_power,
    knockback_strength,
    load_armor_item,
    total_armor,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHESTPLATE = (
    REPO_ROOT
    / ".local"
    / "datagen"
    / "out"
    / "reports"
    / "minecraft"
    / "components"
    / "item"
    / "diamond_chestplate.json"
)


class TestArmorReduction:
    def test_full_diamond_armor_reduces_damage(self):
        """20 armor, 8 toughness, 10 damage -> 3.0 (vanilla formula)."""
        result = armor_reduction(armor=20, toughness=8, damage=10)
        assert isinstance(result, float)
        assert 0.0 <= result <= 10.0
        assert result == pytest.approx(3.0)

    def test_no_armor_takes_full_damage(self):
        """No armor means no reduction: damage stays 10.0."""
        assert armor_reduction(0, 0, 10) == 10.0

    def test_iron_armor_without_toughness(self):
        """20 armor, 0 toughness: protection 15 -> 4.0 damage left."""
        assert armor_reduction(20, 0, 10) == pytest.approx(4.0)

    def test_protection_floor_is_twenty_percent_of_armor(self):
        """The formula clamps protection to at least 0.2 * armor."""
        # 40 armor is above vanilla's cap, but the floor still applies.
        # protection = clamp(40 - 100/2, 8, 20) = 8 -> effectiveness 0.32.
        assert armor_reduction(40, 0, 100) == pytest.approx(68.0)

    def test_blocked_amount_complements_remaining_damage(self):
        remaining = armor_reduction(20, 8, 10)
        blocked = armor_damage_blocked(20, 8, 10)
        assert blocked == pytest.approx(10.0 - remaining)
        assert blocked == pytest.approx(7.0)


class TestArmorItems:
    def test_armor_piece_stats_and_sum(self):
        helmet = ArmorItem(armor_points=3, toughness=2)
        chest = ArmorItem(armor_points=8, toughness=2)
        assert armor_toughness(chest) == 2.0
        # Armor floors, toughness converts directly.
        assert total_armor([helmet, chest]) == (11.0, 4.0)

    def test_fractional_armor_floors(self):
        pieces = [ArmorItem(armor_points=10.5, toughness=1.5)]
        assert total_armor(pieces) == (10.0, 1.5)

    def test_loads_real_diamond_chestplate_from_local(self):
        assert CHESTPLATE.exists(), f"missing vanilla data: {CHESTPLATE}"
        item = load_armor_item(CHESTPLATE)
        assert item.armor_points == 8.0
        assert item.toughness == 2.0
        assert item.max_damage == 528


class TestKnockback:
    def test_base_knockback_is_04(self):
        assert knockback_strength(0) == 0.4

    def test_level_two_knockback_is_06(self):
        assert knockback_strength(2) == 0.6

    def test_each_level_adds_point_one(self):
        assert knockback_strength(1) == pytest.approx(0.5)
        assert knockback_strength(3) == pytest.approx(0.7)

    def test_knockback_enchantment_wraps_strength(self):
        enchant = KnockbackEnchantment(level=2)
        assert enchant.strength == 0.6

    def test_attack_power_is_halved(self):
        # Rust health.rs: (attack_knockback + enchantment) / 2.0
        assert knockback_attack_power(0.0, 2) == pytest.approx(0.3)
        assert knockback_attack_power(0.4, 0) == pytest.approx(0.4)


class TestHurtArmor:
    def test_eight_damage_wears_two_durability(self):
        assert hurt_armor(8.0) == 2

    def test_small_hit_wears_at_least_one(self):
        assert hurt_armor(1.0) == 1
        assert hurt_armor(0.5) == 1

    def test_no_damage_wears_nothing(self):
        assert hurt_armor(0.0) == 0
        assert hurt_armor(-3.0) == 0

    def test_large_hit_uses_quarter_damage(self):
        assert hurt_armor(100.0) == 25
