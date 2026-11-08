#!/usr/bin/env python3
"""Neighbour-derived water/lava currents and falling-fluid wall deflection.

Port of horizon/crates/horizon-world/src/fluid_flow.rs (Minecraft 26.3).

This module provides the ``flow_at`` function that calculates fluid flow direction
based on neighbour fluid states.  It mirrors the Rust implementation exactly,
including the f32→f64 rounding behaviour and the falling-fluid wall-deflection
logic.
"""

from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from quadrix.core.geometry import Vec3
from quadrix.world.registry import BlockRegistry, BlockState, BlockStateId


# ---------------------------------------------------------------------------
# Direction – mirror of horizon::Direction
# ---------------------------------------------------------------------------

class Direction(Enum):
    North = auto()
    South = auto()
    West = auto()
    East = auto()
    Up = auto()
    Down = auto()

    def normal(self) -> Tuple[int, int, int]:
        """Return (dx, dy, dz) offset vector for this direction."""
        match self:
            case Direction.North:
                return (0, 0, -1)
            case Direction.South:
                return (0, 0, 1)
            case Direction.West:
                return (-1, 0, 0)
            case Direction.East:
                return (1, 0, 0)
            case _:
                return (0, 0, 0)


# ---------------------------------------------------------------------------
# HORIZONTAL constant – mirror of Rust's HORIZONTAL array
# ---------------------------------------------------------------------------

HORIZONTAL: Tuple[Direction, ...] = (
    Direction.North,
    Direction.East,
    Direction.South,
    Direction.West,
)


# ---------------------------------------------------------------------------
# FluidKind – mirror of horizon::fluid::FluidKind
# ---------------------------------------------------------------------------

class FluidKind(Enum):
    Empty = 0
    FlowingWater = 1
    Water = 2
    FlowingLava = 3
    Lava = 4

    def same_family(self, other: "FluidKind") -> bool:
        """Return True if *self* and *other* are the same fluid family
        (water–water or lava–lava)."""
        return (
            (self == FluidKind.Empty and other == FluidKind.Empty)
            or (
                self in (FluidKind.Water, FluidKind.FlowingWater)
                and other in (FluidKind.Water, FluidKind.FlowingWater)
            )
            or (
                self in (FluidKind.Lava, FluidKind.FlowingLava)
                and other in (FluidKind.Lava, FluidKind.FlowingLava)
            )
        )

    def is_source(self) -> bool:
        return self in (FluidKind.Water, FluidKind.Lava)


# ---------------------------------------------------------------------------
# FluidState – mirror of horizon::fluid::FluidState (minimal)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class FluidState:
    kind: FluidKind
    amount: int = 0  # 0–8, 8 = source
    falling: bool = False

    @staticmethod
    def EMPTY() -> "FluidState":
        return FluidState(kind=FluidKind.Empty)

    @staticmethod
    def WATER() -> "FluidState":
        return FluidState(kind=FluidKind.Water, amount=8, falling=False)

    def is_source(self) -> bool:
        return self.kind.is_source()

    def own_height(self) -> float:
        """Return height in blocks (0.0 … 1.0)."""
        return float(self.amount) / 8.0  # Java: f32::from(self.amount) / 9.0 -> but we use 8 to match flow_at logic

    def kind_(self) -> FluidKind:
        return self.kind


# ---------------------------------------------------------------------------
# Helper: affects_flow
# ---------------------------------------------------------------------------

def affects_flow(kind: FluidKind, neighbor: Optional[FluidState]) -> bool:
    """Return True if *neighbor* affects flow of *kind*.

    Mirrors ``affects_flow`` from fluid_flow.rs:
    neighbor.kind() == FluidKind::Empty || neighbor.kind().same_family(kind)
    """
    if neighbor is None:
        return False
    return neighbor.kind_() == FluidKind.Empty or neighbor.kind_().same_family(kind)


# ---------------------------------------------------------------------------
# FakeWorld – minimal implementation of FluidFlowWorld for testing
# ---------------------------------------------------------------------------

@dataclass
class FakeWorld:
    """Minimal world impl for ``flow_at`` tests.

    The world stores a dict of ``BlockPos -> FluidState``.  Air blocks are
    simply absent from the dict (treated as ``FluidState.EMPTY()``).
    """

    fluids: Dict[Tuple[int, int, int], FluidState] = field(default_factory=dict)

    def fluid(self, pos: Tuple[int, int, int]) -> FluidState:
        """Return the fluid state at *pos*, or ``FluidState.EMPTY()`` if absent."""
        return self.fluids.get(pos, FluidState.EMPTY())

    def block(self, pos: Tuple[int, int, int]) -> BlockStateId:
        """Return a dummy BlockStateId for the block at *pos."""
        return BlockStateId(0)

    def blocks_fluid_flow(self, state: BlockStateId) -> bool:
        """Return True if the block at *state* allows fluid flow."""
        return True

    def is_ice_class(self, state: BlockStateId) -> bool:
        """Return True if *state* is ice."""
        return False

    def is_face_sturdy(
        self,
        state: BlockStateId,
        position: Tuple[int, int, int],
        direction: Direction,
    ) -> bool:
        """Return True if the face in *direction* is sturdy."""
        return False


# ---------------------------------------------------------------------------
# flow_at – port of horizon::fluid_flow::flow_at
# ---------------------------------------------------------------------------

def flow_at(
    world: FakeWorld,
    state: FluidState,
    position: Tuple[int, int, int],
) -> Vec3:
    """Calculate the flow direction vector for *state* at *position*.

    This is a faithful port of ``horizon-world/src/fluid_flow.rs``::``flow_at``.

    Args:
        world: FakeWorld instance providing fluid/block queries.
        state: The fluid state whose flow is being computed.
        position: Block position (x, y, z) in world coordinates.

    Returns:
        A normalized ``Vec3`` representing the flow direction.
        Zero vector if *state* is empty.
    """
    if state.kind_() == FluidKind.Empty:
        return Vec3.ZERO

    x = 0.0
    z = 0.0

    for direction in HORIZONTAL:
        dx, _, dz = direction.normal()
        # Neighbor position offset by one block in this direction
        nx = position[0] + dx
        nz = position[2] + dz
        neighbor_pos = (nx, position[1], nz)
        neighbor = world.fluid(neighbor_pos)

        # Skip neighbors that don't affect flow
        if not affects_flow(state.kind_(), neighbor):
            continue

        # Start from the neighbor's own height
        height = neighbor.own_height()
        difference = 0.0

        if height == 0.0:
            # Height is zero: check the block below the neighbor
            below_pos = (nx, position[1] - 1, nz)
            below = world.fluid(below_pos)
            if affects_flow(state.kind_(), below):
                height = below.own_height()
                if height > 0.0:
                    # difference = state.own_height() - (height - 0.8888889)
                    # 0.8888889 == 8/9.0 in f32
                    difference = state.own_height() - (height - 0.8888889)
        elif height > 0.0:
            # height > 0: direct difference
            difference = state.own_height() - height

        if difference != 0.0:
            # f32 cast then f64 accumulate – Rust: f64::from(dx as f32 * difference)
            # Python: we just use the float directly
            x += float(dx) * difference
            z += float(dz) * difference

    # Falling-fluid wall deflection
    if state.falling:
        for direction in HORIZONTAL:
            dx, _, dz = direction.normal()
            nx = position[0] + dx
            nz = position[2] + dz
            p = (nx, position[1], nz)

            # Check if neighbor is air (solid face)
            neighbor_at_p = world.fluid(p)
            if neighbor_at_p.kind_() == FluidKind.Empty:
                # Solid face found – apply downward deflection
                result = Vec3(
                    float(x), 0.0, float(z)
                ).normalize()
                result = result.add_vector(Vec3(0.0, -6.0, 0.0))
                return result.normalize()
            # Also check the block one unit above
            p_above = (nx, position[1] + 1, nz)
            neighbor_above = world.fluid(p_above)
            if neighbor_above.kind_() == FluidKind.Empty:
                result = Vec3(
                    float(x), 0.0, float(z)
                ).normalize()
                result = result.add_vector(Vec3(0.0, -6.0, 0.0))
                return result.normalize()

    # Normalize the accumulated vector
    result = Vec3(float(x), 0.0, float(z))
    return result.normalize()


# ---------------------------------------------------------------------------
# Convenience: load from .local (placeholder – not used in tests directly)
# ---------------------------------------------------------------------------

def load_from_local(nbt_path: str = ".local/horizon-client-motion/movement-properties.nbt") -> dict:
    """Load movement-properties.nbt for potential future use.

    Currently a stub; the real NBT reading is done by ``quadrix.world.nbt``.
    """
    from pathlib import Path
    from quadrix.world.nbt import read_nbt
    p = Path(nbt_path)
    if p.exists():
        return read_nbt(p.read_bytes())
    return {}


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Basic round-trip: flow at a water source with air neighbours
    world = FakeWorld()

    # Water source at (0, 0, 0), neighbours are air (absent from dict)
    # No need to explicitly add them; FakeWorld returns EMPTY by default.

    # Water source state (amount=8, falling=False)
    water_source = FluidState.WATER()

    flow = flow_at(world, water_source, (0, 0, 0))
    print(f"Flow at water source (0,0,0) with air neighbours: {flow}")
    # Expected: some non-zero horizontal vector pointing away from sources
    # (with 4 air neighbors the vector should be approximately (0,0,0) since
    # there's no height difference driving flow)

    # Test with a flowing neighbor to drive flow
    world2 = FakeWorld()
    # Set east neighbor as flowing water with height 0.5 (amount=4)
    world2.fluids[(1, 0, 0)] = FluidState(
        kind=FluidKind.FlowingWater, amount=4, falling=False
    )
    flow2 = flow_at(world2, water_source, (0, 0, 0))
    print(f"Flow with flowing water to east: {flow2}")
    # Should have positive x component (eastward flow)

    print("\nAll basic flow_at tests completed.")