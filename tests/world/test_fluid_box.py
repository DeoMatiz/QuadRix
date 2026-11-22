#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/fluid_box.py (horizon-world/src/fluid_box.rs)."""

from __future__ import annotations

from typing import Optional

import pytest

from quadrix.core.geometry import Aabb, Vec3
from quadrix.world.fluid_box import boat_passenger_box, interaction_box


def _boxed(min_y: float, max_y: float) -> Aabb:
    return Aabb.new(Vec3(-0.3, min_y, -0.3), Vec3(0.3, max_y, 0.3))


def _eq(a: Optional[Aabb], b: Optional[Aabb]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.min == b.min and a.max == b.max


class _Boat:
    def __init__(self, under_water: bool, bounds: Aabb) -> None:
        self.under_water = under_water
        self.bounds = bounds

    def is_under_water(self) -> bool:
        return self.under_water

    def boat_bounds(self) -> Aabb:
        return self.bounds


class _BoxWorld:
    def __init__(self, box: Aabb, vehicle=None) -> None:
        self.box = box
        self.vehicle_value = vehicle

    def bounding_box(self) -> Aabb:
        return self.box

    def vehicle(self):
        return self.vehicle_value

    def modify_passenger_box(self, vehicle, bounds: Aabb):
        return bounds.intersect(vehicle)


def test_interaction_box_deflates_without_vehicle():
    world = _BoxWorld(Aabb.new(Vec3(0.0, 0.0, 0.0), Vec3(0.6, 1.8, 0.6)))
    result = interaction_box(world)
    assert result is not None
    assert result.min.x == pytest.approx(0.001)
    assert result.max.y == pytest.approx(1.799)
    assert result.size().x == pytest.approx(0.598)


def test_interaction_box_delegates_to_vehicle():
    vehicle = Aabb.new(Vec3(-0.2, -1.0, -0.2), Vec3(0.2, 1.0, 0.2))
    world = _BoxWorld(Aabb.new(Vec3(0.0, 0.0, 0.0), Vec3(0.6, 1.8, 0.6)), vehicle=vehicle)
    result = interaction_box(world)
    assert result is not None
    # intersect(clamped bounds, vehicle)
    assert result.max.y == 1.0


def test_submerged_boat_keeps_passenger_box():
    passenger = _boxed(0.0, 1.8)
    boat = _Boat(True, _boxed(0.0, 0.6))
    assert _eq(boat_passenger_box(boat, passenger), passenger)


def test_boat_reaching_top_removes_box():
    passenger = _boxed(0.0, 1.8)
    for top in (1.8, 2.0):
        boat = _Boat(False, _boxed(0.0, top))
        assert boat_passenger_box(boat, passenger) is None


def test_floating_boat_trims_to_its_top():
    boat = _Boat(False, _boxed(0.0, 0.6))
    assert _eq(boat_passenger_box(boat, _boxed(0.0, 1.8)), _boxed(0.6, 1.8))
    low = _Boat(False, _boxed(-2.0, -1.0))
    assert _eq(boat_passenger_box(low, _boxed(0.0, 1.8)), _boxed(0.0, 1.8))
