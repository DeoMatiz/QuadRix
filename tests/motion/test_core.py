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