#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/fluid_occupancy.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.core.geometry import Aabb, Vec3
from quadrix.world.chunk import BlockSection
from quadrix.world.fluid_occupancy import (
    BudgetExceeded,
    DataError,
    FluidPresence,
    NonFiniteBounds,
    contains_any_liquid,
)
from quadrix.world.registry import BlockRegistry, BlockStateId

REGISTRY = Path(".local/horizon-client-motion/block-registry.nbt")


class _FakeWorld:
    def __init__(self, registry: BlockRegistry, section: BlockSection) -> None:
        self.registry = registry
        self._section = section

    def minimum_section_y(self) -> int:
        return 0

    def maximum_section_y(self) -> int:
        return 23

    def chunk(self, x: int, z: int):
        return ("chunk", x, z)

    def section(self, chunk, y: int) -> BlockSection:
        return self._section

    def minimum_y(self) -> int:
        return -64

    def maximum_y(self) -> int:
        return 319


def _registry() -> BlockRegistry:
    assert REGISTRY.exists()
    return BlockRegistry.load(REGISTRY)


def test_presence_tracks_liquid_blocks():
    registry = _registry()
    presence = FluidPresence.new(registry)
    assert presence.has_fluid(registry.default_state("minecraft:water"))
    assert presence.has_fluid(registry.default_state("minecraft:lava"))
    assert not presence.has_fluid(registry.default_state("minecraft:stone"))
    assert presence.registry_ref() is registry


def test_contains_any_liquid_false_for_air():
    registry = _registry()
    presence = FluidPresence.new(registry)
    air_section = BlockSection.uniform(registry.default_state("minecraft:air"), registry)
    world = _FakeWorld(registry, air_section)
    bounds = Aabb.new(Vec3(0.0, 64.0, 0.0), Vec3(1.0, 65.0, 1.0))
    assert contains_any_liquid(world, presence, bounds, 10_000) is False


def test_contains_any_liquid_true_for_water():
    registry = _registry()
    presence = FluidPresence.new(registry)
    water_section = BlockSection.uniform(registry.default_state("minecraft:water"), registry)
    world = _FakeWorld(registry, water_section)
    bounds = Aabb.new(Vec3(0.0, 64.0, 0.0), Vec3(1.0, 65.0, 1.0))
    assert contains_any_liquid(world, presence, bounds, 10_000) is True


def test_nonfinite_bounds_raise():
    registry = _registry()
    presence = FluidPresence.new(registry)
    air_section = BlockSection.uniform(registry.default_state("minecraft:air"), registry)
    world = _FakeWorld(registry, air_section)
    bounds = Aabb(Vec3(float("nan"), 64.0, 0.0), Vec3(1.0, 65.0, 1.0))
    with pytest.raises(NonFiniteBounds):
        contains_any_liquid(world, presence, bounds, 100)


def test_budget_exceeded_raises():
    registry = _registry()
    presence = FluidPresence.new(registry)
    air_section = BlockSection.uniform(registry.default_state("minecraft:air"), registry)
    world = _FakeWorld(registry, air_section)
    bounds = Aabb.new(Vec3(0.0, 64.0, 0.0), Vec3(1.0, 65.0, 1.0))
    with pytest.raises(BudgetExceeded):
        contains_any_liquid(world, presence, bounds, 0)


def test_registry_mismatch_raises_data_error():
    registry = _registry()
    presence = FluidPresence.new(registry)
    other = BlockRegistry.load(REGISTRY)
    section = BlockSection.uniform(other.default_state("minecraft:stone"), other)
    world = _FakeWorld(other, section)
    bounds = Aabb.new(Vec3(0.0, 64.0, 0.0), Vec3(1.0, 65.0, 1.0))
    with pytest.raises(DataError):
        contains_any_liquid(world, presence, bounds, 10_000)
