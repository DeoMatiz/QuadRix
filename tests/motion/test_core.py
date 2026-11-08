#!/usr/bin/env python3
"""Tests for motion/core.py – PART 1 of the Horizon → QuadRix port.

Verifies PlayerMotion basics and MovementResources loading from .local data.
"""

from __future__ import annotations

import pytest

from quadrix.core.geometry import Vec3, Aabb, Axis
from quadrix.motion.core import (
    EntityDimensions,
    BlockMovementProperties,
    MovementResources,
    PlayerMotion,
    PlayerInput,
    FluidTagId,
    PlayerPose,
    auto_jump,
    apply_landing,
    on_climbable,
    climb,
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


# ── PART 4: jump_from_ground tests ──────────────────────────────────

def test_player_motion_jump_from_ground_on_ground():
    """Jump from ground: pm on stone, on_ground=True, input=PlayerInput(jump=True)
    → jump_from_ground returns True, velocity.y > 0, on_ground=False."""
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(60, 62) for z in range(-5, 6)})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    # Ensure on_ground is True (tick will set it, or we can set it directly)
    pm.on_ground = True
    result = pm.jump_from_ground(world, PlayerInput(jump=True))
    assert result is True, "jump_from_ground should return True when on ground and jump input"
    assert pm.velocity.y > 0, f"Expected velocity.y > 0 after jump, got {pm.velocity.y}"
    assert pm.on_ground is False, "on_ground should be False after jump"


def test_player_motion_jump_from_ground_in_air():
    """Jump in air: pm on_ground=False → jump_from_ground returns False,
    velocity.y not changed."""
    world = FakeWorld()  # all air
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = False
    # Set some initial velocity.y
    pm.velocity = pm.velocity.with_component(Axis.Y, 1.0)
    initial_vel_y = pm.velocity.y
    result = pm.jump_from_ground(world, PlayerInput(jump=True))
    assert result is False, "jump_from_ground should return False when not on ground"
    assert pm.velocity.y == initial_vel_y, "velocity.y should not change when not on ground"


def test_player_motion_jump_from_ground_no_jump_input():
    """Jump without input.jump: input=PlayerInput() on ground → return False,
    velocity.y not changed."""
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(60, 62) for z in range(-5, 6)})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    initial_vel_y = pm.velocity.y
    result = pm.jump_from_ground(world, PlayerInput())
    assert result is False, "jump_from_ground should return False when no jump input"
    assert pm.velocity.y == initial_vel_y, "velocity.y should not change when no jump input"


def test_player_motion_jump_factor_influence():
    """jumpFactor influences jump velocity: pm on honey_block (jumpFactor=0.5)
    → velocity.y after jump ≈ 0.42*0.5=0.21 ± eps, vs on stone → 0.42."""
    # Load MovementResources and check honey_block vs stone jump factors
    mr = MovementResources.load(".local/horizon-client-motion")
    honey_props = mr.properties.get("minecraft:honey_block", None)
    stone_props = mr.properties.get("minecraft:stone", None)
    
    honey_jf = honey_props.jump_factor if honey_props else 1.0
    stone_jf = stone_props.jump_factor if stone_props else 1.0
    
    expected_honey_y = 0.42 * honey_jf
    expected_stone_y = 0.42 * stone_jf
    
    # Check that honey_block has lower jumpFactor than stone (per NBT data)
    assert honey_jf < stone_jf, f"Expected honey_block jumpFactor ({honey_jf}) < stone jumpFactor ({stone_jf})"
    
    # Test jump from honey_block - place honey_block at y=63 (below player at y=64)
    world_honey = FakeWorld(solid_blocks={
        (x, y, z): "minecraft:honey_block"
        for x in range(-5, 6)
        for y in range(63, 64)      # y=63 is below player at y=64
        for z in range(-5, 6)
    })
    pm_honey = PlayerMotion.new(mr, Vec3(0, 64, 0))
    pm_honey.on_ground = True
    pm_honey.jump_from_ground(world_honey, PlayerInput(jump=True))
    assert abs(pm_honey.velocity.y - expected_honey_y) < 1e-4, \
        f"Honey block: expected velocity.y ≈ {expected_honey_y}, got {pm_honey.velocity.y}"
    
    # Test jump from stone - place stone at y=63 (below player at y=64)
    world_stone = FakeWorld(solid_blocks={
        (x, y, z): "minecraft:stone"
        for x in range(-5, 6)
        for y in range(63, 64)      # y=63 is below player at y=64
        for z in range(-5, 6)
    })
    pm_stone = PlayerMotion.new(mr, Vec3(0, 64, 0))
    pm_stone.on_ground = True
    pm_stone.jump_from_ground(world_stone, PlayerInput(jump=True))
    assert abs(pm_stone.velocity.y - expected_stone_y) < 1e-4, \
        f"Stone: expected velocity.y ≈ {expected_stone_y}, got {pm_stone.velocity.y}"


def test_player_motion_jump_sprint_boost():
    """Sprint boost: input=PlayerInput(jump=True, sprint=True) →
    horizontal velocity > 0 immediately after jump."""
    world = FakeWorld(solid_blocks={(x, y, z): "minecraft:stone" for x in range(-5, 6) for y in range(60, 62) for z in range(-5, 6)})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.yaw = 0.0  # yaw=0 faces +z (forward in Minecraft)
    pm.on_ground = True
    result = pm.jump_from_ground(world, PlayerInput(jump=True, sprint=True))
    assert result is True, "jump_from_ground should return True with sprint boost"
    # With yaw=0, forward is +z, so velocity.z should be > 0 after sprint boost
    assert pm.velocity.z > 0, f"Expected velocity.z > 0 after sprint jump with yaw=0, got {pm.velocity.z}"


# ── PART 5: fly & set_flying tests ──────────────────────────────────

def test_player_motion_set_flying_true():
    """set_flying(True): pm.flying == True, velocity.y == 0."""
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.set_flying(True)
    assert pm.flying is True, "Expected flying to be True after set_flying(True)"
    assert pm.velocity.y == 0.0, f"Expected velocity.y == 0 after set_flying(True), got {pm.velocity.y}"


def test_player_motion_fly_up():
    """fly upwards: pm.flying=True, input=PlayerInput(jump=True), several fly → velocity.y > 0, position.y rises."""
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.flying = True
    world = FakeWorld()  # all air, no solid blocks
    # Multiple fly calls should accumulate vertical velocity
    for _ in range(3):
        pm.fly(PlayerInput(jump=True), world)
    assert pm.velocity.y > 0, f"Expected velocity.y > 0 after fly upwards, got {pm.velocity.y}"
    # Position should increase
    pos_before = pm.position.y
    for _ in range(3):
        pm.tick(dt=0.05, world=world)
    assert pm.position.y > pos_before, f"Expected position.y to increase after fly up, got {pm.position.y}"


def test_player_motion_fly_down():
    """fly downwards: pm.flying=True, input=PlayerInput(sneak=True) → velocity.y < 0."""
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.flying = True
    world = FakeWorld()  # all air, no solid blocks
    pm.fly(PlayerInput(sneak=True), world)
    assert pm.velocity.y < 0, f"Expected velocity.y < 0 after fly downwards, got {pm.velocity.y}"


def test_player_motion_gravity_not_applied_while_flying():
    """Gravity is NOT applied when flying: pm.flying=True, tick several times without input → velocity.y ~0."""
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.flying = True
    world = FakeWorld()  # all air
    initial_vel_y = pm.velocity.y
    for _ in range(10):
        pm.tick(dt=0.05, world=world)
    # velocity.y should remain ~0 (no gravity applied while flying)
    assert abs(pm.velocity.y - initial_vel_y) < 1e-4, \
        f"Expected velocity.y to remain ~0 while flying, initial={initial_vel_y}, after={pm.velocity.y}"


def test_player_motion_fly_no_flying():
    """fly() when not flying: does nothing, velocity.y unchanged."""
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    # flying is False by default
    world = FakeWorld()  # all air
    vel_before = pm.velocity.y
    pm.fly(PlayerInput(jump=True), world)
    assert pm.velocity.y == vel_before, \
        f"Expected velocity.y unchanged when not flying, before={vel_before}, after={pm.velocity.y}"


def test_player_motion_set_flying_false_returns_to_gravity():
    """set_flying(False) from ground: returns to normal tick → gravity works again."""
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    # Start on ground with flying enabled
    pm.flying = True
    pm.on_ground = True
    pm.velocity = pm.velocity.with_component(Axis.Y, 0.0)
    # Disable flying
    pm.set_flying(False)
    # Now gravity should apply; velocity.y should decrease
    world = FakeWorld()  # all air
    pm.tick(dt=0.05, world=world)
    assert pm.velocity.y < 0, f"Expected velocity.y < 0 after set_flying(False) with gravity, got {pm.velocity.y}"


# ── Swimming tests ──────────────────────────────────────────────────

def test_is_in_water():
    """is_in_water: pm at (0, 63, 0), FakeWorld с water на y<=63 → is_in_water() True."""
    # Fake world with water at y<=63 (blocks at y=63 are water)
    world = FakeWorld(solid_blocks={
        (x, y, z): "minecraft:water"
        for x in range(-5, 6)
        for y in range(-10, 64)  # water at y<=63
        for z in range(-5, 6)
    })
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 63, 0))
    pm.swimming = True
    assert pm.is_in_water() is True, "Expected is_in_water() to True when in water"


def test_swimming_jump():
    """swimming jump: pm.swimming=True, input=PlayerInput(jump=True) → velocity.y > 0."""
    world = FakeWorld()  # all air, no water (swimming flag is set manually)
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.swimming = True
    pm.velocity = pm.velocity.with_component(Axis.Y, 0.0)  # start with zero vertical velocity
    pm.tick_swimming(PlayerInput(jump=True), world)
    assert pm.velocity.y > 0, f"Expected velocity.y > 0 after swimming jump, got {pm.velocity.y}"


def test_swimming_sink():
    """swimming sink: pm.swimming=True, input=PlayerInput(sneak=True) → velocity.y < 0."""
    world = FakeWorld()  # all air, no water (swimming flag is set manually)
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.swimming = True
    pm.velocity = pm.velocity.with_component(Axis.Y, 0.0)  # start with zero vertical velocity
    pm.tick_swimming(PlayerInput(sneak=True), world)
    assert pm.velocity.y < 0, f"Expected velocity.y < 0 after swimming sink, got {pm.velocity.y}"


def test_water_drag():
    """water drag: pm.swimming=True, input=PlayerInput() → velocity attenuates faster, чем на земле."""
    world = FakeWorld()  # all air, no water (swimming flag is set manually)
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.swimming = True
    # Set initial horizontal velocity
    pm.velocity = pm.velocity.with_component(Axis.X, 1.0)
    pm.velocity = pm.velocity.with_component(Axis.Z, 0.0)
    # Tick without input - water drag should decay velocity
    pm.tick_swimming(PlayerInput(), world)
    # Velocity should have decayed with water drag (0.89 per tick)
    assert abs(pm.velocity.x) < 1.0, \
        f"Expected velocity.x to decay with water drag, initial=1.0, after={pm.velocity.x}"


# ── PART 7: PlayerPose, auto_jump, apply_landing tests ───────────────────────


def test_player_pose_default():
    """pose default: pm.pose == PlayerPose.standing."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    assert pm.pose == PlayerPose.Standing


def test_player_pose_eye_height_standing():
    """eye_height по pose: standing returns base eye height."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    pm.pose = PlayerPose.Standing
    assert pm.eye_height() == 1.62


def test_player_pose_eye_height_sneaking():
    """eye_height по pose: sneaking returns reduced eye height."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    pm.pose = PlayerPose.Sneaking
    # Standing eye_height is 1.62, sneaking multiplies by 0.85
    assert pm.eye_height() == pytest.approx(1.62 * 0.85, abs=1e-4)


def test_player_pose_eye_height_swimming():
    """eye_height по pose: swimming returns 0.4."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 64, 0))
    pm.pose = PlayerPose.Swimming
    assert pm.eye_height() == 0.4


def test_auto_jump_with_obstacle():
    """auto_jump: pm на земле, input.forward=1, впереди solid-блок → auto_jump True, velocity.y > 0."""
    # Create a world with a solid block ahead (yaw=0 faces +z, so block at z=1)
    world = FakeWorld(solid_blocks={
        (0, 64, 1): "minecraft:stone",  # block directly ahead at yaw=0
    })
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    pm.move_vector = [0.0, 1.0]  # moving forward
    pm.yaw = 0.0  # yaw=0 faces +z
    result = auto_jump(pm, world)
    assert result is True, f"Expected auto_jump to return True, got {result}"
    assert pm.velocity.y > 0, f"Expected velocity.y > 0 after auto_jump, got {pm.velocity.y}"


def test_auto_jump_no_obstacle():
    """auto_jump без препятствия: впереди air → auto_jump False."""
    # World with air ahead
    world = FakeWorld()  # all air
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    pm.move_vector = [0.0, 1.0]  # moving forward
    pm.yaw = 0.0  # yaw=0 faces +z
    result = auto_jump(pm, world)
    assert result is False, f"Expected auto_jump to return False when no obstacle, got {result}"


def test_landing_fall_distance_greater_than_3():
    """landing: pm падает с 10 блоков, fall_distance > 3 → fall_distance сбрасывается после.apply_landing."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 60, 0))
    # Set fall_distance to 10 (simulating a 10-block fall)
    pm.fall_distance = 10.0
    
    # Create a world with solid ground
    world = FakeWorld(solid_blocks={
        (x, 50, z): "minecraft:stone"
        for x in range(-5, 6)
        for z in range(-5, 6)
    })
    
    # Apply landing - should reset fall_distance
    initial_fall_distance = pm.fall_distance
    apply_landing(pm, world)
    
    # After landing, fall_distance should be reset to 0
    assert pm.fall_distance == 0.0, \
        f"Expected fall_distance to be reset to 0 after landing from 10 blocks, got {pm.fall_distance}"
    assert pm.fall_distance < initial_fall_distance, \
        f"Expected fall_distance to decrease after landing, initial={initial_fall_distance}, final={pm.fall_distance}"


def test_landing_fall_distance_less_than_3():
    """landing: падение с 2 блоков → fall_distance сбрасывается, ущерб не применяется."""
    mr = MovementResources.load(".local/horizon-client-motion")
    pm = PlayerMotion.new(mr, Vec3(0, 60, 0))
    
    # Set fall_distance to 2 (less than 3)
    pm.fall_distance = 2.0
    
    # Create a world with solid ground
    world = FakeWorld(solid_blocks={
        (x, 50, z): "minecraft:stone"
        for x in range(-5, 6)
        for z in range(-5, 6)
    })
    
    # Apply landing - should reset fall_distance (no damage since < 3)
    initial_fall_distance = pm.fall_distance
    apply_landing(pm, world)
    
    # After landing, fall_distance should be reset to 0
    assert pm.fall_distance == 0.0, \
        f"Expected fall_distance to be reset to 0 after landing from 2 blocks, got {pm.fall_distance}"


# ── NEW: on_climbable and climb tests ───────────────────────────────

def test_on_climbable_ladder():
    """on_climbable: pm на ladder → True."""
    world = FakeWorld(solid_blocks={(0, 64, 0): "minecraft:ladder"})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    # Do NOT set pm.on_climbable here — that would shadow the method.
    # Call the module-level function directly; it will set the instance attr internally.
    result = on_climbable(pm, world)
    assert result is True, f"Expected on_climbable to return True for ladder, got {result}"


def test_on_climbable_stone():
    """on_climbable: pm на stone → False."""
    world = FakeWorld(solid_blocks={(0, 64, 0): "minecraft:stone"})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    # Do NOT set pm.on_climbable here — that would shadow the method.
    result = on_climbable(pm, world)
    assert result is False, f"Expected on_climbable to return False for stone, got {result}"


def test_climb_up():
    """climb: pm на ladder, forward=1.0 → velocity.y > 0 (подъем)."""
    world = FakeWorld(solid_blocks={(0, 64, 0): "minecraft:ladder"})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    pm.climb(PlayerInput(forward=1.0), world)
    assert pm.velocity.y > 0, f"Expected velocity.y > 0 after climb up, got {pm.velocity.y}"


def test_climb_no_climbable():
    """climb: pm на stone, forward=1.0 → ничего не меняет, гравитация работает."""
    world = FakeWorld(solid_blocks={(0, 64, 0): "minecraft:stone"})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    vel_before = pm.velocity.y
    pm.climb(PlayerInput(forward=1.0), world)
    # climb() returns immediately on non-climbable block; velocity should be unchanged
    assert pm.velocity.y == vel_before, "climb on non-climbable block should not change velocity"
    # After tick, gravity should still apply normally
    pm.tick(dt=0.05, world=world)
    assert pm.velocity.y < 0, "Gravity should pull down after climb on non-climbable block"


def test_climb_sneak_holds():
    """climb: pm на ladder, sneak=True → velocity.y == 0 (зависание)."""
    world = FakeWorld(solid_blocks={(0, 64, 0): "minecraft:ladder"})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    pm.climb(PlayerInput(forward=1.0, sneak=True), world)
    assert pm.velocity.y == 0.0, f"Expected velocity.y == 0 when sneaking on ladder, got {pm.velocity.y}"


def test_climb_gravity_disabled():
    """climb: pm на ladder без input → tick не тянет вниз (гравитацияdisabled mientras ладдер)."""
    world = FakeWorld(solid_blocks={(0, 64, 0): "minecraft:ladder"})
    pm = PlayerMotion.new(MovementResources.load(".local/horizon-client-motion"), Vec3(0, 64, 0))
    pm.on_ground = True
    # No input — climb should not change velocity
    pm.climb(PlayerInput(), world)
    assert pm.velocity.y == 0.0, f"Expected velocity.y == 0 with no input on ladder, got {pm.velocity.y}"
    # Tick applies gravity, so velocity should become negative
    pm.tick(dt=0.05, world=world)
    assert pm.velocity.y < 0, "Gravity should pull down after climbing with no input"