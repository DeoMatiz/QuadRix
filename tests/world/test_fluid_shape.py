#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/fluid_shape.py (horizon-world/src/fluid_shape.rs)."""

from __future__ import annotations

import pytest

from quadrix.core.geometry import BlockPos
from quadrix.world.fluid import FluidKind, FluidState
from quadrix.world.fluid_shape import FluidShapeCache


class _World:
    def __init__(self, above: FluidState) -> None:
        self.above = above

    def fluid(self, position) -> FluidState:
        return self.above

    def sturdy_down(self, position) -> bool:
        return False


def test_empty_state_yields_empty_shape():
    cache = FluidShapeCache()
    shape = cache.shape(_World(FluidState.EMPTY()), FluidState.EMPTY(), BlockPos(0, 0, 0))
    assert shape.is_empty()
    assert cache.cached_states() == 0


def test_source_shape_uses_surface_height():
    cache = FluidShapeCache()
    world = _World(FluidState.EMPTY())
    shape = cache.shape(world, FluidState.WATER(), BlockPos(0, 0, 0))
    assert not shape.is_empty()
    boxes = shape.boxes_list()
    assert len(boxes) == 1
    assert boxes[0].max.y == pytest.approx(FluidState.WATER().own_height())


def test_cache_is_reused_and_indexed_by_falling_and_amount():
    cache = FluidShapeCache()
    world = _World(FluidState.EMPTY())
    first = cache.shape(world, FluidState.WATER(), BlockPos(0, 0, 0))
    assert cache.cached_states() == 1
    again = cache.shape(world, FluidState.WATER(), BlockPos(4, 4, 4))
    assert again is first  # cached, same object

    falling = FluidState(kind=FluidKind.FlowingWater, amount=4, falling=True)
    cache.shape(world, falling, BlockPos(0, 0, 0))
    assert cache.cached_states() == 2

    plain = FluidState(kind=FluidKind.FlowingWater, amount=4, falling=False)
    cache.shape(world, plain, BlockPos(0, 0, 0))
    assert cache.cached_states() == 3


def test_full_height_when_water_above():
    cache = FluidShapeCache()
    world = _World(FluidState(kind=FluidKind.FlowingWater, amount=2))
    shape = cache.shape(world, FluidState.WATER(), BlockPos(0, 0, 0))
    assert shape.boxes_list()[0].max.y == pytest.approx(1.0)
