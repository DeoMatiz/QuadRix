"""Tests for quadrix.effects: StatusFlags data type and pure helpers."""

from quadrix.effects import (
    StatusFlags,
    damage_protection,
    has_fire_resistance,
    has_resistance,
    resistance_amplifier,
)


class TestStatusFlagsDefaults:
    def test_default_matches_derive_default(self):
        """StatusFlags() has no effects and no absorption."""
        status = StatusFlags()
        assert status.resistance is None
        assert status.fire_resistance is False
        assert status.absorption == 0.0

    def test_default_optional_amplifiers_are_none(self):
        status = StatusFlags()
        assert status.jump_boost is None
        assert status.levitation is None
        assert status.regeneration is None
        assert status.speed is None
        assert status.slowness is None

    def test_default_booleans_are_false(self):
        status = StatusFlags()
        assert status.slow_falling is False
        assert status.dolphins_grace is False
        assert status.weaving is False
        assert status.water_breathing is False
        assert status.breath_of_the_nautilus is False

    def test_default_protection_is_empty(self):
        assert StatusFlags().protection == []


class TestResistance:
    def test_resistance_amplifier_returns_amplifier(self):
        status = StatusFlags(resistance=1)
        assert resistance_amplifier(status) == 1

    def test_resistance_amplifier_level_zero(self):
        status = StatusFlags(resistance=0)
        assert resistance_amplifier(status) == 0

    def test_has_resistance_tracks_option(self):
        assert has_resistance(StatusFlags()) is False
        assert has_resistance(StatusFlags(resistance=2)) is True

    def test_resistance_amplifier_without_effect_raises(self):
        try:
            resistance_amplifier(StatusFlags())
        except ValueError as err:
            assert str(err) == "no resistance effect"
        else:
            raise AssertionError("expected ValueError without resistance")


class TestFireResistance:
    def test_has_fire_resistance_true(self):
        status = StatusFlags(fire_resistance=True)
        assert has_fire_resistance(status) is True

    def test_has_fire_resistance_false_by_default(self):
        assert has_fire_resistance(StatusFlags()) is False


class TestProtectionLookup:
    def test_returns_points_for_matching_damage_type(self):
        status = StatusFlags(
            protection=[("minecraft:fall", 4.0), ("minecraft:fire", 1.5)]
        )
        assert damage_protection(status, "minecraft:fall") == 4.0

    def test_returns_zero_for_unknown_damage_type(self):
        status = StatusFlags(protection=[("minecraft:fall", 4.0)])
        assert damage_protection(status, "minecraft:magic") == 0.0
