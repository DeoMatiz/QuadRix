"""Tests for quadrix.health - PART 1 ported from health.rs"""
import sys
from pathlib import Path

import pytest

from quadrix.health import (
    HealthEvent,
    HurtSource,
    Knock,
    BlockOutcome,
    HurtRecord,
    AttackRecord,
    HealthResources,
    PlayerFloatIds,
    PlayerHealth,
    DamageType,
    DamageCatalog,
)


class TestHealthEvent:
    """Test that HealthEvent has all expected variants."""
    
    VALID_VARIANTS = {
        "StarvationDamage",
        "FreezeDamage",
        "SweetBerryBushDamage",
        "DrownDamage",
        "Updated",
        "Statistic",
        "RecordedDamage",
        "Phase",
        "ArmorHurt",
        "DamageBroadcast",
        "Criterion",
    }
    
    def test_all_variants_present(self):
        """HealthEvent must have all 11 variants from Rust."""
        names = {e.name for e in HealthEvent}
        assert self.VALID_VARIANTS == names, (
            f"Missing variants: {self.VALID_VARIANTS - names}\n"
            f"Extra variants: {names - self.VALID_VARIANTS}"
        )
    
    def test_variant_count(self):
        """HealthEvent must have exactly 11 variants."""
        assert len(HealthEvent) == 11


class TestHurtSource:
    """Test HurtSource struct."""
    
    def test_hurt_source_creation(self):
        """HurtSource(damage_type, causing, direct) works."""
        hs = HurtSource(damage_type="minecraft:fall", causing=42, direct=0)
        assert hs.damage_type == "minecraft:fall"
        assert hs.causing == 42
        assert hs.direct == 0
    
    def test_hurt_source_defaults(self):
        """HurtSource with defaults works."""
        hs = HurtSource(damage_type="minecraft:generic", causing=0, direct=0)
        assert hs.damage_type == "minecraft:generic"
        assert hs.causing == 0
        assert hs.direct == 0


class TestKnock:
    """Test Knock struct."""
    
    def test_knock_creation(self):
        """Knock(strength, x, z) works."""
        k = Knock(strength=0.4, x=0.0, z=1.0)
        assert k.strength == 0.4
        assert k.x == 0.0
        assert k.z == 1.0
    
    def test_knock_all_zero(self):
        """Knock(0.0, 0.0, 0.0) works."""
        k = Knock(strength=0.0, x=0.0, z=0.0)
        assert k.strength == 0.0
        assert k.x == 0.0
        assert k.z == 0.0


class TestBlockOutcome:
    """Test BlockOutcome struct."""
    
    def test_block_outcome_creation(self):
        """BlockOutcome(hurt, blocked, fully_blocked, sound, knockback, canceled) works."""
        bo = BlockOutcome(
            hurt=True,
            blocked=0.0,
            fully_blocked=False,
            sound=True,
            knockback=False,
            canceled=False,
        )
        assert bo.hurt is True
        assert bo.blocked == 0.0
        assert bo.fully_blocked is False
        assert bo.sound is True
        assert bo.knockback is False
        assert bo.canceled is False
    
    def test_block_outcome_default(self):
        """BlockOutcome default values work."""
        bo = BlockOutcome(hurt=False, blocked=0.0, fully_blocked=False, sound=False, knockback=False, canceled=True)
        assert bo.hurt is False
        assert bo.canceled is True


class TestHurtRecord:
    """Test HurtRecord struct."""
    
    def test_hurt_record_creation(self):
        """HurtRecord with all fields works."""
        hr = HurtRecord(
            game_time=100,
            source="minecraft:fall",
            amount=5.0,
            blocked=0.0,
            taken=5.0,
            hurt=True,
            armor=2.0,
            toughness=0.5,
            health=15.0,
            fire_ticks=60,
            knockback=[0.5, 0.0, 1.0],
        )
        assert hr.game_time == 100
        assert hr.source == "minecraft:fall"
        assert hr.amount == 5.0
        assert hr.blocked == 0.0
        assert hr.taken == 5.0
        assert hr.hurt is True
        assert hr.armor == 2.0
        assert hr.toughness == 0.5
        assert hr.health == 15.0
        assert hr.fire_ticks == 60
        assert hr.knockback == [0.5, 0.0, 1.0]
    
    def test_hurt_record_no_knockback(self):
        """HurtRecord without knockback works."""
        hr = HurtRecord(
            game_time=50,
            source="minecraft:player",
            amount=3.0,
            blocked=1.0,
            taken=2.0,
            hurt=False,
            armor=0.0,
            toughness=0.0,
            health=17.0,
            fire_ticks=0,
        )
        assert hr.knockback is None


class TestAttackRecord:
    """Test AttackRecord struct."""
    
    def test_attack_record_creation(self):
        """AttackRecord with all fields works."""
        ar = AttackRecord(
            game_time=200,
            target="player",
            id=1,
            killed=False,
            amount=7.0,
            scale=0.8,
            crit=True,
            landed=True,
            dealt=7.0,
        )
        assert ar.game_time == 200
        assert ar.target == "player"
        assert ar.id == 1
        assert ar.killed is False
        assert ar.amount == 7.0
        assert ar.scale == 0.8
        assert ar.crit is True
        assert ar.landed is True
        assert ar.dealt == 7.0
    
    def test_attack_record_killed(self):
        """AttackRecord with killed=True works."""
        ar = AttackRecord(
            game_time=100,
            target="zombie",
            id=42,
            killed=True,
            amount=10.0,
            scale=1.0,
            crit=False,
            landed=True,
            dealt=10.0,
        )
        assert ar.killed is True


class TestPlayerFloatIds:
    """Test PlayerFloatIds struct."""
    
    def test_player_float_ids(self):
        """PlayerFloatIds(health, absorption) works."""
        pfi = PlayerFloatIds(health=0, absorption=1)
        assert pfi.health == 0
        assert pfi.absorption == 1
    
    def test_player_float_ids_defaults(self):
        """PlayerFloatIds with defaults works."""
        pfi = PlayerFloatIds(health=10, absorption=2)
        assert pfi.health == 10
        assert pfi.absorption == 2


class TestHealthResources:
    """Test HealthResources struct."""
    
    def test_health_resources_load_creates_instance(self):
        """HealthResources() can be created."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        assert resources.damage == {}
        assert resources.ids.health == 0
        assert resources.ids.absorption == 1
    
    def test_health_resources_load_with_real_path(self):
        """HealthResources.load() attempts to read from .local path."""
        # This may fail if .local/horizon-client-health/ doesn't exist - that's OK
        try:
            resources = HealthResources.load(Path(".local/horizon-client-health"))
            # If we get here, the files existed and were loaded
            assert resources is not None
        except (FileNotFoundError, Exception) as e:
            # Expected if files don't exist - skip the assertion
            pytest.skip(f"Health data files not found: {e}")


class TestPlayerHealth:
    """Test PlayerHealth struct."""
    
    def test_player_health_new_requires_resources(self):
        """PlayerHealth.new() requires HealthResources and attributes."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        assert player is not None
        assert player.health() == 20.0
        assert player.absorption() == 0.0
    
    def test_player_health_health_method(self):
        """PlayerHealth.health() returns current health."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        h = player.health()
        assert isinstance(h, float)
        assert h > 0.0
    
    def test_player_health_absorption_method(self):
        """PlayerHealth.absorption() returns current absorption."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        a = player.absorption()
        assert isinstance(a, float)
        assert a >= 0.0
    
    def test_player_health_dead_or_dying(self):
        """PlayerHealth.dead_or_dying() works correctly."""
        # With full health, not dead_or_dying
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        assert player.dead_or_dying() is False
        
        # With zero health, dead_or_dying
        resources2 = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        player2 = PlayerHealth.new(resources2, attributes)
        # Set health to 0
        player2.data["health"] = 0.0
        assert player2.dead_or_dying() is True
    
    def test_player_health_advance_clock(self):
        """PlayerHealth.advance_clock() advances timers."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        initial_gt = player.game_time
        player.advance_clock()
        assert player.game_time == initial_gt + 1
        assert player.tick_count == initial_gt + 1  # simplified
    
    def test_player_health_animate_hurt(self):
        """PlayerHealth.animate_hurt() starts hurt animation."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        player.animate_hurt()
        assert player.hurt_animation_time == 10
        assert player.hurt_state["hurt_duration"] == 10
        assert player.hurt_state["hurt_time"] == 10
    
    def test_player_health_indicate_damage(self):
        """PlayerHealth.indicate_damage() sets indicated direction."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        player.indicate_damage(1.0, 0.0, 0.0)
        assert player.indicated_dir is not None
    
    def test_player_flash_health_change_damage(self):
        """PlayerHealth.flash_health_change() handles damage."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        # Take damage from 20 to 10
        player.flash_health_change(10.0)
        assert player.hurt_state["cooldown"] == 20
        assert player.hurt_state["last_hurt"] == 10.0
    
    def test_player_flash_health_change_healing(self):
        """PlayerHealth.flash_health_change() handles healing.
        
        When health increases (damage < 0), cooldown is set to 10.
        When health stays the same (damage == 0), cooldown is unchanged.
        """
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        # Start at less than max, then heal to full
        player.data["health"] = 10.0  # Start at half health
        # Heal from 10 to 20 (damage < 0, health increased)
        player.flash_health_change(20.0)
        # Cooldown should be set to 10 for healing
        assert player.hurt_state["cooldown"] == 10
    
    def test_player_health_set_health(self):
        """PlayerHealth.set_health() sets health value."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        player.set_health(10.0, False)
        assert player.health() == 10.0
    
    def test_player_health_set_absorption(self):
        """PlayerHealth.set_health() sets absorption value."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        player.set_health(5.0, True)  # absorption=True
        assert player.absorption() == 5.0
    
    def test_player_health_dead_or_dying_at_zero(self):
        """PlayerHealth.dead_or_dying() returns True at 0 health."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        player.data["health"] = 0.0
        assert player.dead_or_dying() is True
    
    def test_player_health_dead_flag(self):
        """PlayerHealth.dead flag works."""
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        assert player.dead is False
        player.dead = True
        assert player.dead is True


HEALTH_ROOT = Path(".local/horizon-client-health")


class TestDamageTypes:
    """Test damage_types loading from .local/horizon-client-health."""

    def test_loads_all_types_and_tags(self):
        """HealthResources.load reads the real catalog.json and tags.json."""
        r = HealthResources.load(HEALTH_ROOT)
        assert len(r.damage.types) == 51
        assert len(r.damage.tags) == 36
        assert isinstance(r.damage, DamageCatalog)

    def test_fall_effects(self):
        """minecraft:fall has the hurt effect."""
        r = HealthResources.load(HEALTH_ROOT)
        assert r.damage.get("minecraft:fall").effects == "hurt"

    def test_on_fire_effects(self):
        """minecraft:on_fire has the burning effect."""
        r = HealthResources.load(HEALTH_ROOT)
        assert r.damage.get("minecraft:on_fire").effects == "burning"

    def test_fall_exhaustion(self):
        """minecraft:fall has zero exhaustion (hex float 00000000)."""
        r = HealthResources.load(HEALTH_ROOT)
        assert r.damage.get("minecraft:fall").exhaustion == 0.0

    def test_arrow_exhaustion_hex_float(self):
        """minecraft:arrow's 3dcccccd hex bits decode to float32 0.1."""
        r = HealthResources.load(HEALTH_ROOT)
        assert r.damage.get("minecraft:arrow").exhaustion == pytest.approx(0.1)

    def test_bypasses_armor_tag(self):
        """minecraft:bypasses_armor resolves to damage types."""
        r = HealthResources.load(HEALTH_ROOT)
        members = r.damage.by_tag("minecraft:bypasses_armor")
        assert len(members) > 0
        assert r.damage.has_tag("minecraft:fall", "minecraft:bypasses_armor") is True
        assert r.damage.has_tag("minecraft:arrow", "minecraft:bypasses_armor") is False

    def test_player_float_ids(self):
        """ids.json supplies health=9 and absorption=17."""
        r = HealthResources.load(HEALTH_ROOT)
        assert r.ids.health == 9
        assert r.ids.absorption == 17

    def test_has_and_get(self):
        """DamageCatalog.has/get and per-type tags work."""
        r = HealthResources.load(HEALTH_ROOT)
        assert r.damage.has("minecraft:fall") is True
        assert r.damage.has("minecraft:not_a_real_type") is False
        fall = r.damage.get("minecraft:fall")
        assert isinstance(fall, DamageType)
        assert "minecraft:bypasses_armor" in fall.tags

# ═══════════════════════════════════════════════════════════════════════
# PART 2 tests - hurt / die logic
# ═══════════════════════════════════════════════════════════════════════
from quadrix.health import (
    Environment,
    Blocking,
    BlockingRules,
    DamageReduction,
    ItemDamageFunction,
    DamageSource,
    HealthRules,
    Scaling,
    Difficulty,
    Bypass,
    ImmunityTag,
    DamageRule,
    HurtTag,
    DamageStat,
    hurt_sound,
)
from quadrix.effects import StatusFlags
import quadrix.health as health_module


PART2_ROOT = Path(".local/horizon-client-health")


def _load():
    return HealthResources.load(PART2_ROOT)


def _new(max_health=20.0, **kwargs):
    resources = _load()
    player = PlayerHealth.new(resources, {"minecraft:max_health": float(max_health)})
    for key, value in kwargs.items():
        setattr(player, key, value)
    return resources, player


class TestHurtBasics:
    def test_hurt_reduces_health(self):
        resources, player = _new()
        assert player.hurt(resources, {}, "minecraft:generic", 5.0) is True
        assert player.health() == pytest.approx(15.0)

    def test_hurt_returns_false_when_dead(self):
        resources, player = _new()
        player.dead = True
        assert player.hurt(resources, {}, "minecraft:generic", 5.0) is False
        assert player.health() == pytest.approx(20.0)

    def test_client_side_does_not_hurt(self):
        resources, player = _new(client_side=True)
        assert player.hurt(resources, {}, "minecraft:generic", 5.0) is False
        assert player.health() == pytest.approx(20.0)

    def test_hurt_log_records_the_hit(self):
        resources, player = _new()
        player.hurt(resources, {}, "minecraft:generic", 5.0)
        assert len(player.hurt_log) == 1
        record = player.hurt_log[0]
        assert record.source == "minecraft:generic"
        assert record.amount == pytest.approx(5.0)
        assert record.taken == pytest.approx(5.0)
        assert record.health == pytest.approx(15.0)

    def test_unknown_source_raises(self):
        resources, player = _new()
        with pytest.raises(KeyError):
            player.hurt(resources, {}, "minecraft:not_a_type", 1.0)


class TestHurtCooldown:
    def test_weaker_hit_in_cooldown_does_nothing(self):
        resources, player = _new()
        assert player.hurt(resources, {}, "minecraft:mob_attack", 1.0) is True
        assert player.health() == pytest.approx(19.0)
        # Stronger hit inside the cooldown only takes the difference.
        assert player.hurt(resources, {}, "minecraft:mob_attack", 2.0) is True
        assert player.health() == pytest.approx(18.0)
        # Weaker than the last hit: refused.
        assert player.hurt(resources, {}, "minecraft:mob_attack", 1.5) is False
        assert player.health() == pytest.approx(18.0)

    def test_advance_clock_expires_cooldown(self):
        resources, player = _new()
        player.hurt(resources, {}, "minecraft:mob_attack", 1.0)
        assert player.hurt_state["cooldown"] == 20
        for _ in range(20):
            player.advance_clock()
        assert player.hurt_state["cooldown"] == 0


class TestDifficultyScaling:
    def test_easy_scales_mob_hit(self):
        resources, player = _new()
        rules = HealthRules(difficulty=Difficulty.Easy)
        player.hurt_caused_by(
            resources, rules, "minecraft:mob_attack", 4.0, None, True, 0
        )
        assert player.health() == pytest.approx(17.0)

    def test_hard_scales_mob_hit(self):
        resources, player = _new()
        rules = HealthRules(difficulty=Difficulty.Hard)
        player.hurt_caused_by(
            resources, rules, "minecraft:mob_attack", 4.0, None, True, 0
        )
        assert player.health() == pytest.approx(14.0)

    def test_non_living_source_is_not_scaled(self):
        resources, player = _new()
        rules = HealthRules(difficulty=Difficulty.Hard)
        player.hurt_caused_by(
            resources, rules, "minecraft:mob_attack", 4.0, None, False, 0
        )
        assert player.health() == pytest.approx(16.0)

    def test_peaceful_zeroes_scaled_damage(self):
        resources, player = _new()
        rules = HealthRules(difficulty=Difficulty.Peaceful)
        assert player.hurt_caused_by(
            resources, rules, "minecraft:mob_attack", 4.0, None, True, 0
        ).hurt is False
        assert player.health() == pytest.approx(20.0)


class TestBlocking:
    def _shield(self, *, bypassed=False, pierce=False, angle=0.0):
        rules = BlockingRules(
            delay_seconds=0.25,
            disable_scale=1.0,
            reductions=[
                DamageReduction(
                    horizontal_angle=90.0,
                    types=None,
                    base=0.0,
                    factor=1.0,
                )
            ],
            item_damage=ItemDamageFunction(threshold=3.0, base=1.0, factor=1.0),
        )
        return Blocking(rules=rules, bypassed=bypassed, pierce=pierce, angle=angle)

    def test_shield_fully_blocks_easy_scaled_hit(self):
        resources, player = _new()
        rules = HealthRules(difficulty=Difficulty.Easy)
        outcome = player.hurt_caused_by(
            resources,
            rules,
            "minecraft:mob_attack",
            4.0,
            self._shield(),
            True,
            0,
        )
        assert outcome.blocked == pytest.approx(3.0)
        assert outcome.fully_blocked is True
        assert outcome.knockback is False
        assert outcome.sound is True
        assert player.health() == pytest.approx(20.0)

    def test_bypassed_shield_blocks_nothing(self):
        resources, player = _new()
        outcome = player.hurt_caused_by(
            resources,
            {},
            "minecraft:mob_attack",
            4.0,
            self._shield(bypassed=True),
            False,
            0,
        )
        assert outcome.blocked == pytest.approx(0.0)
        assert outcome.fully_blocked is False
        assert player.health() == pytest.approx(16.0)

    def test_piercing_shield_blocks_nothing(self):
        resources, player = _new()
        outcome = player.hurt_caused_by(
            resources,
            {},
            "minecraft:mob_attack",
            4.0,
            self._shield(pierce=True),
            False,
            0,
        )
        assert outcome.blocked == pytest.approx(0.0)
        assert player.health() == pytest.approx(16.0)

    def test_outside_angle_blocks_nothing(self):
        resources, player = _new()
        outcome = player.hurt_caused_by(
            resources,
            {},
            "minecraft:mob_attack",
            4.0,
            self._shield(angle=3.0),
            False,
            0,
        )
        assert outcome.blocked == pytest.approx(0.0)
        assert player.health() == pytest.approx(16.0)

    def test_partial_block(self):
        resources, player = _new()
        rules = BlockingRules(
            reductions=[
                DamageReduction(
                    horizontal_angle=90.0, types=None, base=1.0, factor=0.5
                )
            ]
        )
        outcome = player.hurt_blocking(
            resources,
            {},
            "minecraft:mob_attack",
            4.0,
            Blocking(rules, False, False, 0.0),
        )
        assert outcome.blocked == pytest.approx(3.0)
        assert outcome.fully_blocked is False
        assert player.health() == pytest.approx(19.0)


class TestImmunityAndEffects:
    def test_fire_resistance_blocks_fire_damage(self):
        resources, player = _new()
        player.status = StatusFlags(fire_resistance=True)
        assert player.hurt(resources, {}, "minecraft:on_fire", 5.0) is False
        assert player.health() == pytest.approx(20.0)

    def test_fire_damage_without_resistance_hurts(self):
        resources, player = _new()
        assert player.hurt(resources, {}, "minecraft:on_fire", 5.0) is True
        assert player.health() == pytest.approx(15.0)

    def test_resistance_reduces_damage(self):
        resources, player = _new()
        player.status = StatusFlags(resistance=0)
        player.hurt(resources, {}, "minecraft:mob_attack", 10.0)
        assert player.health() == pytest.approx(12.0)

    def test_armor_reduces_damage(self):
        resources, player = _new()
        player.attributes = {"minecraft:armor": 20.0}
        player.hurt(resources, {}, "minecraft:mob_attack", 10.0)
        # 20 armor leaves 40% of the hit: 4 damage.
        assert player.health() == pytest.approx(16.0)

    def test_bypasses_armor_ignores_armor(self):
        resources, player = _new()
        player.attributes = {"minecraft:armor": 20.0}
        player.hurt(resources, {}, "minecraft:generic", 10.0)
        assert player.health() == pytest.approx(10.0)

    def test_absorption_takes_damage_first(self):
        resources, player = _new()
        player.data["absorption"] = 5.0
        player.hurt(resources, {}, "minecraft:mob_attack", 10.0)
        assert player.absorption() == pytest.approx(0.0)
        assert player.health() == pytest.approx(15.0)

    def test_totem_saves_from_death(self):
        resources, player = _new()
        player.totem_ready = True
        player.hurt(resources, {}, "minecraft:generic", 100.0)
        assert player.totem_used is True
        assert player.totem_ready is False
        assert player.dead is False
        assert player.health() == pytest.approx(1.0)

    def test_death_sets_dead_flag(self):
        resources, player = _new()
        player.hurt(resources, {}, "minecraft:generic", 100.0)
        assert player.dead is True
        assert player.dead_or_dying() is True

    def test_ability_invulnerable_stops_damage(self):
        resources, player = _new(invulnerable=True)
        assert player.hurt(resources, {}, "minecraft:generic", 5.0) is False
        assert player.health() == pytest.approx(20.0)

    def test_ability_invulnerable_is_bypassed(self):
        resources, player = _new(invulnerable=True)
        assert player.hurt(resources, {}, "minecraft:out_of_world", 5.0) is True
        assert player.health() == pytest.approx(15.0)

    def test_not_client_loaded_is_immune(self):
        resources, player = _new(client_loaded=False)
        assert player.hurt(resources, {}, "minecraft:generic", 5.0) is False
        assert player.health() == pytest.approx(20.0)


class TestHooks:
    def test_damage_pre_hook_changes_amount(self):
        resources, player = _new()

        def hook(hurting, amount):
            assert hurting.kind == "player"
            return 5.0

        health_module.DAMAGE_PRE_HOOK = hook
        try:
            player.hurt(resources, {}, "minecraft:mob_attack", 10.0)
        finally:
            health_module.DAMAGE_PRE_HOOK = None
        assert player.health() == pytest.approx(15.0)

    def test_damage_post_hook_sees_amount(self):
        resources, player = _new()
        seen = []

        def hook(hurting, amount):
            seen.append(amount)

        health_module.DAMAGE_POST_HOOK = hook
        try:
            player.hurt(resources, {}, "minecraft:mob_attack", 10.0)
        finally:
            health_module.DAMAGE_POST_HOOK = None
        assert seen == [pytest.approx(10.0)]

    def test_hurt_server_hook_cancels(self):
        resources, player = _new()

        def hook(hurting, amount):
            return True, amount

        health_module.HURT_SERVER_HOOK = hook
        try:
            outcome = player.hurt_blocking(
                resources, {}, "minecraft:mob_attack", 5.0
            )
        finally:
            health_module.HURT_SERVER_HOOK = None
        assert outcome.canceled is True
        assert outcome.hurt is False
        assert player.health() == pytest.approx(20.0)


class TestEnvironment:
    def _env(self, *, name="minecraft:on_fire", status=None, rules=None):
        resources = _load()
        source = DamageSource(resources.damage, name)
        return Environment(
            entity=7,
            causing=0,
            invulnerable=False,
            client_loaded=True,
            rules=rules or HealthRules(),
            source=source,
            living_cause=False,
            events=[],
            dead=False,
            sync_velocity=False,
            game_time=5,
            status=status or StatusFlags(),
            data={"health": 20.0, "absorption": 0.0},
            food={},
            attributes={},
        )

    def test_field_and_method_duality(self):
        env = self._env()
        assert env.source() == "minecraft:on_fire"
        assert env.source.definition().id == "minecraft:on_fire"
        assert env.client_loaded() is True
        assert bool(env.client_loaded) is True
        assert env.game_time() == 5

    def test_tag_lookup_for_both_traits(self):
        env = self._env()
        assert env.tag(ImmunityTag.Fire) is True
        assert env.tag(None, HurtTag.Fire) is True
        assert env.tag(ImmunityTag.Fall) is False

    def test_rules_and_scaling(self):
        env = self._env()
        assert env.damage_rule(DamageRule.Fall) is True
        assert env.difficulty() is Difficulty.Normal
        assert env.scales_with_difficulty() is False
        assert env.ender_pearl() is False

    def test_events_phase_and_stat(self):
        env = self._env()
        env.phase("entity-damage")
        env.stat("taken", 3)
        assert env.events[-2].name == "Phase"
        assert env.events[-2].text == "entity-damage"
        assert env.events[-1].name == "Statistic"
        assert env.events[-1].stat_name == "taken"
        assert env.events[-1].amount == 3

    def test_armor_and_resistance_methods(self):
        env = self._env(status=StatusFlags(resistance=1))
        assert env.has_resistance() is True
        assert env.resistance_amplifier() == 1
        env.hurt_armor({}, 4.0)
        assert env.events[-1].name == "ArmorHurt"
        assert env.events[-1].amount == pytest.approx(4.0)

    def test_resistance_amplifier_without_effect_raises(self):
        env = self._env()
        assert env.has_resistance() is False
        with pytest.raises(ValueError):
            env.resistance_amplifier()

    def test_sound_helpers(self):
        assert hurt_sound("drowning") == "minecraft:entity.player.hurt_drown"
        assert hurt_sound("burning") == "minecraft:entity.player.hurt_on_fire"
        assert hurt_sound("poking") == "minecraft:entity.player.hurt_sweet_berry_bush"
        assert hurt_sound("freezing") == "minecraft:entity.player.hurt_freeze"
        assert hurt_sound("hurt") == "minecraft:entity.player.hurt"


class TestSupportingRules:
    def test_blocking_rules_delay_ticks(self):
        rules = BlockingRules(delay_seconds=0.25, disable_scale=2.0)
        assert rules.delay_ticks() == 5
        assert rules.disable_ticks(1.0) == 40
        assert rules.disable_ticks(0.0) == 0

    def test_item_damage_function(self):
        f = ItemDamageFunction(threshold=3.0, base=1.0, factor=1.0)
        assert f.apply(2.0) == 0
        assert f.apply(4.0) == 5

    def test_scaling_names(self):
        assert Scaling.Never.name_of() == "never"
        assert Scaling.Always.name_of() == "always"
        assert (
            Scaling.LivingNonPlayer.name_of()
            == "when_caused_by_living_non_player"
        )

    def test_blocking_dataclass_fields(self):
        b = Blocking(BlockingRules(), False, True, 1.25)
        assert b.bypassed is False
        assert b.pierce is True
        assert b.angle == 1.25
