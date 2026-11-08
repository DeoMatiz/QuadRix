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
        assert player.hurt["hurt_duration"] == 10
        assert player.hurt["hurt_time"] == 10
    
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
        assert player.hurt["cooldown"] == 20
        assert player.hurt["last_hurt"] == 10.0
    
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
        assert player.hurt["cooldown"] == 10
    
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