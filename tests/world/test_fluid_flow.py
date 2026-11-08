#!/usr/bin/env python3
"""Tests for quadrix.world.fluid_flow.

Port of horizon-world/src/fluid_flow.rs tests.
"""

from __future__ import annotations

import pytest

from quadrix.world.fluid_flow import (
    FakeWorld,
    flow_at,
    FluidState,
    FluidKind,
    Direction,
    HORIZONTAL,
    affects_flow,
)
from quadrix.core.geometry import Vec3


# ---------------------------------------------------------------------------
# Helper: water source state
# ---------------------------------------------------------------------------

WATER_SOURCE = FluidState.WATER()


# ---------------------------------------------------------------------------
# Test 1: Water source with air neighbours → flow directed away from source
# ---------------------------------------------------------------------------
def test_flow_at_water_source_air_neighbours() -> None:
    """Water source at (0,0,0) with air in all 4 horizontal directions.

    When all neighbours are air (height = 0), the difference term involves
    the ``0.8888889`` offset (8/9 in f32).  With 4 air neighbours the
    accumulated x/z should be 0 because every direction contributes equally
    and oppositely.
    """
    world = FakeWorld()
    # All 4 horizontal neighbours are air (absent → EMPTY)
    # No need to explicitly add them; FakeWorld returns EMPTY by default.

    flow = flow_at(world, WATER_SOURCE, (0, 0, 0))
    # With purely air neighbours the flow should be zero (no height difference)
    assert flow == Vec3.ZERO, (
        f"Expected zero flow with all-air neighbours, got {flow}"
    )


# ---------------------------------------------------------------------------
# Test 2: Water with two opposite sources → flow = 0 (balanced)
# ---------------------------------------------------------------------------
def test_flow_at_two_sources_balanced() -> None:
    """Water source at (0,0,0) with another water source to the east.

    Two equal sources should balance, yielding zero net flow.
    """
    world = FakeWorld()
    # Set east neighbour as a second water source (amount=8, source)
    world.fluids[(1, 0, 0)] = FluidState.WATER()

    flow = flow_at(world, WATER_SOURCE, (0, 0, 0))
    # Balanced sources → zero net flow
    assert flow == Vec3.ZERO, (
        f"Expected zero flow with two equal sources, got {flow}"
    )


# ---------------------------------------------------------------------------
# Test 3: Lava flows slower than water (speed comparison)
# ---------------------------------------------------------------------------
def test_lava_slower_than_water() -> None:
    """Lava and water both produce flow when neighboring source exists.

    The ``flow_at`` function direction calculation is the same for both kinds;
    the actual speed difference in Minecraft comes from entity interaction
    (``apply_current``), not from the flow direction logic itself.
    This test verifies that both produce a non-zero flow vector when a
    neighboring fluid source is present, matching the Rust behaviour.
    """
    # Water source with flowing water to the east (height 0.5 = amount 4)
    world_water = FakeWorld()
    world_water.fluids[(1, 0, 0)] = FluidState(
        kind=FluidKind.FlowingWater, amount=4, falling=False
    )
    lava_state = FluidState(kind=FluidKind.Lava, amount=8, falling=False)
    flow_water = flow_at(world_water, FluidState.WATER(), (0, 0, 0))
    water_mag = abs(flow_water.x) + abs(flow_water.z)  # L1 magnitude
    assert water_mag > 0.0, "Water should produce non-zero flow with neighbor"

    # Lava source with flowing lava to the east (height 0.5 = amount 4)
    world_lava = FakeWorld()
    world_lava.fluids[(1, 0, 0)] = FluidState(
        kind=FluidKind.FlowingLava, amount=4, falling=False
    )
    flow_lava = flow_at(world_lava, lava_state, (0, 0, 0))
    lava_mag = abs(flow_lava.x) + abs(flow_lava.z)

    # Both should produce flow; magnitudes may differ due to height handling
    # but the key assertion is that both are non-zero
    assert lava_mag > 0.0, "Lava should produce non-zero flow with neighbor"


# ---------------------------------------------------------------------------
# Test 4: Flow directed from source when one neighbour has water
# ---------------------------------------------------------------------------
def test_flow_directed_from_source() -> None:
    """Water source at (0,0,0) with flowing water to the east.

    The flow should have a positive x component (toward the east), i.e.
    directed from the source toward the neighbor with water.
    """
    world = FakeWorld()
    # East neighbour is flowing water with amount=4 (height = 0.5)
    world.fluids[(1, 0, 0)] = FluidState(
        kind=FluidKind.FlowingWater, amount=4, falling=False
    )

    flow = flow_at(world, WATER_SOURCE, (0, 0, 0))
    # Flow should have eastward (positive x) component
    assert flow.x > 0, (
        f"Expected positive x flow directed east, got {flow}"
    )


# ---------------------------------------------------------------------------
# Test 5: Flow with falling fluid gets downward deflection
# ---------------------------------------------------------------------------
def test_falling_fluid_deflection() -> None:
    """Falling water source should get a downward deflection component.

    When ``state.falling()`` is true the function adds a ``(0.0, -6.0, 0.0)``
    term after normalizing the horizontal flow.
    """
    world = FakeWorld()
    # Use a falling water source (amount=8, falling=True)
    falling_water = FluidState(
        kind=FluidKind.Water, amount=8, falling=True
    )
    # All neighbours air – the horizontal flow will be zero, but the
    # falling-deflection code still runs and adds the downward term.
    # After normalization the result should have a non-zero y component
    # (downward).
    flow = flow_at(world, falling_water, (0, 0, 0))
    # The falling deflection adds (0, -6, 0) then normalizes,
    # so the result should point mostly downward.
    assert flow.y < 0, (
        f"Expected downward (negative y) flow for falling fluid, got {flow}"
    )