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
    PlayerInput,
    FluidTagId,
)


# ── Fake world for unit tests ──────────────────────────────────────

class FakeWorld:
    """Minimal fake world for PlayerMotion tick/move_entity tests.

    Provides ``block(x, y, z) -> str``; returns ``"minecraft:air"`` by default.
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


# ── PART 3: travel, movement_speed, get_friction tests ─────────────

def test_player_motion_movement_speed():
    """movement_speed() returns the base speed of 0.1."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    speed = pm.movement_speed()
    assert speed == 0.1


def test_player_motion_get_friction():
    """get_friction() returns the friction for the block under the player's feet."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    # On cactus, friction should be 0.6
    world = FakeWorld()
    world._solid = {(0, -1, 0): "minecraft:cactus"}
    friction = pm.get_friction(world)
    assert friction == pytest.approx(0.6, abs=1e-6)


def test_player_motion_travel_forward_yaw_zero():
    """Travel with forward=1.0, yaw=0 moves in +z direction (yaw=0 usually +z).

    After travel, tick several times to integrate position.
    """
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(60, 62) for z in range(-5, 6)})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.travel(PlayerInput(forward=1.0), world)
    # Tick several times to integrate position from the set velocity
    for _ in range(3):
        pm.tick(dt=0.05, world=world)
    # After tick(s), position should have changed
    assert pm.position.z != 0.0 or pm.position.x != 0.0, f"Expected position to change after ticks, got {pm.position}"
    # Velocity should be non-zero (set by travel)
    assert pm.velocity.x != 0.0 or pm.velocity.z != 0.0, "Expected non-zero velocity after travel"


def test_player_motion_sprint_faster_than_walk():
    """Sprint speed is greater than walk speed with same input.

    After travel+tick, sprint position should be greater than walk position.
    """
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(60, 62) for z in range(-5, 6)})
    
    pm_walk = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm_walk.travel(PlayerInput(forward=1.0, sprint=False), world)
    for _ in range(10):
        pm_walk.tick(dt=0.05, world=world)
    walk_pos = pm_walk.position.z
    
    pm_sprint = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm_sprint.travel(PlayerInput(forward=1.0, sprint=True), world)
    for _ in range(10):
        pm_sprint.tick(dt=0.05, world=world)
    sprint_pos = pm_sprint.position.z
    
    assert sprint_pos > walk_pos, f"Sprint position ({sprint_pos}) should be greater than walk position ({walk_pos})"


def test_player_motion_sneak_slower_than_walk():
    """Sneak speed is less than walk speed with same input.

    After travel+tick, sneak position should be less than walk position.
    """
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(60, 62) for z in range(-5, 6)})
    
    pm_walk = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm_walk.travel(PlayerInput(forward=1.0, sneak=False), world)
    for _ in range(10):
        pm_walk.tick(dt=0.05, world=world)
    walk_pos = pm_walk.position.z
    
    pm_sneak = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm_sneak.travel(PlayerInput(forward=1.0, sneak=True), world)
    for _ in range(10):
        pm_sneak.tick(dt=0.05, world=world)
    sneak_pos = pm_sneak.position.z
    
    assert sneak_pos < walk_pos, f"Sneak position ({sneak_pos}) should be less than walk position ({walk_pos})"


def test_player_motion_friction_decays_velocity():
    """After releasing input, velocity.x/z exponentially decays with friction=0.6 per tick."""
    world = FakeWorld()  # all air, no solid blocks
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    
    # Start with some velocity by traveling with input
    pm.travel(PlayerInput(forward=1.0, sprint=False), world)
    _ = pm.tick(dt=0.05, world=world)  # integrate once
    initial_vel_z = pm.velocity.z
    
    # Next tick with no input: friction should decay velocity
    pm.travel(PlayerInput(), world)
    _ = pm.tick(dt=0.05, world=world)  # integrate with friction applied
    
    # Velocity should have decayed (be smaller in magnitude)
    assert abs(pm.velocity.z) < abs(initial_vel_z), \
        f"Velocity should decay with friction, initial={initial_vel_z}, after= {pm.velocity.z}"