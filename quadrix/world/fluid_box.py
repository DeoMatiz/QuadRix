#!/usr/bin/env python3
"""[QuadRix] Entity fluid scan bounds and the boat passenger waterline restriction.

Port of horizon/crates/horizon-world/src/fluid_box.rs (Minecraft 26.3).
"""

from __future__ import annotations

from typing import Optional, Protocol

from quadrix.core.geometry import Aabb, Vec3, java_max

__all__ = [
    "FluidBoxWorld",
    "interaction_box",
    "BoatFluidBoxWorld",
    "boat_passenger_box",
]


class FluidBoxWorld(Protocol):
    """``FluidBoxWorld`` (fluid_box.rs:3)."""

    def bounding_box(self) -> Aabb:
        ...

    def vehicle(self):
        ...

    def modify_passenger_box(self, vehicle, bounds: Aabb) -> Optional[Aabb]:
        ...


def interaction_box(world: FluidBoxWorld) -> Optional[Aabb]:
    """``interaction_box`` (fluid_box.rs:14)."""
    bounds = world.bounding_box().deflate(Vec3(0.001, 0.001, 0.001))
    vehicle = world.vehicle()
    if vehicle is None:
        return bounds
    return world.modify_passenger_box(vehicle, bounds)


class BoatFluidBoxWorld(Protocol):
    """``BoatFluidBoxWorld`` (fluid_box.rs:21)."""

    def is_under_water(self) -> bool:
        ...

    def boat_bounds(self) -> Aabb:
        ...


def boat_passenger_box(world: BoatFluidBoxWorld, bounds: Aabb) -> Optional[Aabb]:
    """``boat_passenger_box`` (fluid_box.rs:28).

    Submerged boats preserve the passenger bounds. Otherwise only the part
    strictly above the boat's top can interact with fluid; it may be absent.
    """
    if world.is_under_water():
        return bounds
    boat_top = world.boat_bounds().max_position.y
    min_v = bounds.min_position
    max_v = bounds.max_position
    if boat_top >= max_v.y:
        return None
    return Aabb.new(
        Vec3(min_v.x, java_max(min_v.y, boat_top), min_v.z),
        max_v,
    )
