#!/usr/bin/env python3
"""[QuadRix] Persistent pinned-fluid collision/ray shapes, with caching.

Port of horizon/crates/horizon-world/src/fluid_shape.rs (Minecraft 26.3).
"""

from __future__ import annotations

from typing import List, Optional

from quadrix.core.geometry import BlockPos, Vec3
from quadrix.world.collision.block_collision import VoxelShape
from quadrix.world.fluid import FluidHeightWorld, FluidKind, FluidState

__all__ = ["FluidShapeCache"]


class FluidShapeCache:
    """``FluidShapeCache`` (fluid_shape.rs:11).

    Share this cache across world views using the same fluid registry. The
    pinned registry has no amount-nine state; amounts are zero through eight.
    """

    def __init__(self) -> None:
        self.shapes: List[Optional[VoxelShape]] = [None] * (5 * 18)

    def cached_states(self) -> int:
        """``FluidShapeCache::cached_states`` (fluid_shape.rs:22)."""
        return sum(1 for shape in self.shapes if shape is not None)

    def shape(
        self,
        world: FluidHeightWorld,
        state: FluidState,
        position: BlockPos,
    ) -> VoxelShape:
        """``FluidShapeCache::shape`` (fluid_shape.rs:25)."""
        if state.kind == FluidKind.Empty:
            return VoxelShape.empty()
        index = (
            state.kind.value * 18
            + (1 if state.falling else 0) * 9
            + state.amount
        )
        cached = self.shapes[index]
        if cached is not None:
            return cached
        height = float(
            state.height_at(world, (position.x, position.y, position.z))
        )
        # FluidState validates all amounts and height_at returns [0,1].
        if height <= 0.0:
            shape = VoxelShape.empty()
        else:
            shape = VoxelShape.from_grid(
                ((0.0, 1.0), (0.0, height), (0.0, 1.0)),
                (True,),
            )
        self.shapes[index] = shape
        return shape
