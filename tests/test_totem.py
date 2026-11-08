"""Tests for quadrix.totem: the Totem of Undying death-protection path."""

from quadrix.totem import (
    TOTEM,
    TOTEM_EFFECTS,
    TOTEM_EVENT,
    TotemEffect,
    totem_effect_ids,
    try_use_totem,
    use_totem,
)


class TestTryUseTotem:
    def test_without_a_totem_returns_false(self):
        assert try_use_totem(has_totem=False) is False

    def test_with_a_totem_returns_true(self):
        assert try_use_totem(has_totem=True) is True

    def test_bypasses_invulnerability_ignores_totem(self):
        assert (
            try_use_totem(has_totem=True, bypasses_invulnerability=True)
            is False
        )


class TestUseTotem:
    def test_preserves_player_at_one_health(self):
        result = use_totem(has_totem=True)
        assert result is not None
        assert result.health == 1.0

    def test_emits_totem_entity_event(self):
        result = use_totem(has_totem=True)
        assert result is not None
        assert result.event == TOTEM_EVENT == 35
        assert result.item == TOTEM == "minecraft:totem_of_undying"

    def test_main_hand_is_consumed_first(self):
        result = use_totem(has_totem=True, main_hand=True)
        assert result is not None
        assert result.hand == "main_hand"

    def test_offhand_is_used_when_main_hand_is_empty(self):
        result = use_totem(has_totem=True, main_hand=False)
        assert result is not None
        assert result.hand == "off_hand"

    def test_no_use_returns_none(self):
        assert use_totem(has_totem=False) is None


class TestTotemEffects:
    def test_contains_the_three_vanilla_effects(self):
        ids = totem_effect_ids()
        assert ids == ("regeneration", "absorption", "fire_resistance")

    def test_durations_and_amplifiers_match_rust(self):
        by_id = {effect.id: effect for effect in TOTEM_EFFECTS}
        assert by_id["regeneration"] == TotemEffect("regeneration", 900, 1)
        assert by_id["absorption"] == TotemEffect("absorption", 100, 1)
        assert by_id["fire_resistance"] == TotemEffect(
            "fire_resistance", 800, 0
        )

    def test_a_used_totem_applies_all_effects(self):
        result = use_totem(has_totem=True)
        assert result is not None
        assert [effect.id for effect in result.effects] == [
            "regeneration",
            "absorption",
            "fire_resistance",
        ]
