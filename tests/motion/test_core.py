#!/usr/bin/env python3
"""Tests for motion/core.py – PART 1 of the Horizon → QuadRix port.

Verifies PlayerMotion basics and MovementResources loading from .local data.
"""

from __future__ import annotations

import pytest

from quadrix.core.geometry import Vec3, Aabb
from quadrix.motion.core import (
    EntityDimensions,
    BlockMovementProperties,
    MovementResources,
    PlayerMotion,
    FluidTagId,
)


# ── Fake world for unit tests ──────────────────────────────────────


class FakeWorld:
    """Minimal fake world for PlayerMotion tick/move_entity tests.

    Provides ``block(x, y, z) -> str``; returns ``"minecraft:air"`` by default.
    Solid blocks are anything that is not air, cave_air, or void_air.
    """

    def __init__(self, solid_blocks: dict | None = None) -> None:
        self._solid = solid_blocks or {}

    def block(self, x: int, y: int, z: int) -> str:
        return self._solid.get((x, y, z), "minecraft:air")


# ── MovementResources loading ──────────────────────────────────────

def test_movement_resources_loads_many_blocks():
    """MovementResources.load() should return >1000 block entries."""
    mr = MovementResources.load(".local/horizon-client-motion")
    assert len(mr.properties) > 1000


def test_cactus_friction_default():
    """Default friction for cactus is 0.6 (Rust default)."""
    mr = MovementResources.load(".local/horizon-client-motion")
    prop = mr.properties["minecraft:cactus"]
    assert prop.friction == pytest.approx(0.6, abs=1e-6)


def test_ice_friction():
    """Ice has low friction 0.98."""
    mr = MovementResources.load(".local/horizon-client-motion")
    prop = mr.properties["minecraft:ice"]
    assert prop.friction == pytest.approx(0.98, abs=1e-6)


def test_honey_block_speed_factor():
    """Honey block speed factor is 0.4."""
    mr = MovementResources.load(".local/horizon-client-motion")
    prop = mr.properties["minecraft:honey_block"]
    assert prop.speed_factor == pytest.approx(0.4, abs=1e-6)


def test_oak_fence_gate():
    """Oak fence gate has fence_gate = 1."""
    mr = MovementResources.load(".local/horizon-client-motion")
    prop = mr.properties["minecraft:oak_fence_gate"]
    assert prop.fence_gate == 1


# ── PlayerMotion construction ──────────────────────────────────────

def test_player_motion_new_position():
    """PlayerMotion.new() sets position correctly."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    assert pm.position == Vec3(0, 64, 0)


def test_player_motion_bounds():
    """PlayerMotion.bounds() returns an Aabb with min < max."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    bounds = pm.bounds()
    assert isinstance(bounds, Aabb)
    # min < max for a valid box
    assert bounds.min.x < bounds.max.x
    assert bounds.min.y < bounds.max.y
    assert bounds.min.z < bounds.max.z


def test_player_motion_eye_height():
    """PlayerMotion.eye_height() returns the eye height (> 0)."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    eh = pm.eye_height()
    assert eh > 0


def test_player_motion_is_in_lava():
    """PlayerMotion.is_in_lava() is False for a player on ground at y=64."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    assert pm.is_in_lava() is False


def test_player_motion_gravity_constant():
    """GRAVITY constant from motion.rs (0.08) is available."""
    from quadrix.motion.core import GRAVITY
    assert GRAVITY == 0.08  # motion.rs: effective_gravity base value


# ── PART 2: tick & move_entity tests ───────────────────────────────


def test_player_motion_tick_gravity():
    """Gravity accelerates player downward; velocity.y ≈ -GRAVITY * dt after one tick."""
    world = FakeWorld()  # all air
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 100, 0))
    pm.tick(dt=0.05, world=world)
    # velocity.y should be approximately -0.08 * 0.05 = -0.004
    expected = -0.08 * 0.05
    assert pm.velocity.y == pytest.approx(expected, abs=1e-4)


def test_player_motion_tick_terminal_velocity():
    """Terminal velocity clamp limits fall speed; after many ticks velocity.y >= -3.92."""
    world = FakeWorld()  # all air
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 200, 0))
    for _ in range(200):
        pm.tick(dt=0.05, world=world)
    # velocity.y should not be less than -3.92
    assert pm.velocity.y >= -3.92 - 1e-4


def test_player_motion_tick_lands_on_ground():
    """Player falling onto solid ground: on_ground becomes True, velocity.y == 0 after landing.
    
    Solid blocks at y <= 50 (player starts at y=70, falls ~20 blocks to land).
    """
    # Solid blocks at y <= 50 (player starts at y=70, needs to fall ~20 blocks to land)
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(-5, 51) for z in range(-5, 6)})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 70, 0))
    landed = False
    for _ in range(500):
        pm.tick(dt=0.05, world=world)
        if pm.on_ground:
            landed = True
            break
    # Player should have landed within 500 ticks
    assert landed is True, "Player did not land on ground within 500 ticks"
    # Position should have dropped below 70
    assert pm.position.y < 70
    # Velocity should be zero after landing
    assert pm.velocity.y == 0.0


def test_player_motion_move_entity_against_wall():
    """move_entity stops player before a solid wall; velocity.x is zeroed."""
    world = FakeWorld(solid_blocks={(1, y, z): "minecraft:stone" for y in range(60, 70) for z in range(-5, 6)})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.move_entity(world, Vec3(2, 0, 0))
    # Player should not have passed through the wall at x=1
    assert pm.position.x < 1.0
    # Horizontal velocity should be zero after collision
    assert pm.velocity.x == 0.0