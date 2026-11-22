#!/usr/bin/env python3
"""[QuadRix] Native section-ordered liquid occupancy over resident block states.

Port of horizon/crates/horizon-world/src/fluid_occupancy.rs (Minecraft 26.3).
"""

from __future__ import annotations

import math
from typing import List, Optional, Protocol

from quadrix.core.geometry import Aabb, BlockPos
from quadrix.world.fluid import FluidState
from quadrix.world.registry import BlockRegistry, BlockStateId

__all__ = [
    "FluidPresence",
    "FluidOccupancyWorld",
    "FluidOccupancyError",
    "WorldError",
    "DataError",
    "NonFiniteBounds",
    "BudgetExceeded",
    "contains_any_liquid",
]


# ---------------------------------------------------------------------------
# Errors — fluid_occupancy.rs:46
# ---------------------------------------------------------------------------

class FluidOccupancyError(Exception):
    """Base for ``FluidOccupancyError<E>``."""


class WorldError(FluidOccupancyError):
    """``FluidOccupancyError::World`` — a world query failed."""


class DataError(FluidOccupancyError):
    """``FluidOccupancyError::Data`` — a data invariant failed."""


class NonFiniteBounds(FluidOccupancyError):
    """``FluidOccupancyError::NonFiniteBounds``."""

    def __init__(self) -> None:
        super().__init__("nonfinite fluid query bounds")


class BudgetExceeded(FluidOccupancyError):
    """``FluidOccupancyError::BudgetExceeded``."""

    def __init__(self) -> None:
        super().__init__("fluid query budget exceeded")


# ---------------------------------------------------------------------------
# FluidPresence — fluid_occupancy.rs:11
# ---------------------------------------------------------------------------

class FluidPresence:
    """Per-registry-state liquid presence bitmap."""

    def __init__(self, registry: BlockRegistry, present: List[bool]) -> None:
        self._registry = registry
        self.present = present

    @classmethod
    def new(cls, registry: BlockRegistry) -> "FluidPresence":
        """``FluidPresence::new`` (fluid_occupancy.rs:16)."""
        present: List[bool] = []
        for i in range(registry.len()):
            state = registry.state(BlockStateId(i))
            if state is None:
                raise DataError("fluid presence state outside registry")
            present.append(FluidState.from_block(state) != FluidState.EMPTY())
        return cls(registry, present)

    def registry_ref(self) -> BlockRegistry:
        return self._registry

    def has_fluid(self, state: BlockStateId) -> bool:
        """``FluidPresence::has_fluid`` (fluid_occupancy.rs:28)."""
        index = state.id
        if 0 <= index < len(self.present):
            return self.present[index]
        raise DataError("fluid presence state outside registry")


# ---------------------------------------------------------------------------
# FluidOccupancyWorld — fluid_occupancy.rs:35
# ---------------------------------------------------------------------------

class FluidOccupancyWorld(Protocol):
    def minimum_section_y(self) -> int:
        ...

    def maximum_section_y(self) -> int:
        ...

    def chunk(self, x: int, z: int):
        ...

    def section(self, chunk, y: int):
        ...

    def minimum_y(self) -> int:
        ...

    def maximum_y(self) -> int:
        ...


# ---------------------------------------------------------------------------
# contains_any_liquid — fluid_occupancy.rs:74
# ---------------------------------------------------------------------------

class _Budget:
    """Mutable budget counter; exhaustion is an explicit error."""

    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value

    def spend(self) -> None:
        if self.value == 0:
            raise BudgetExceeded()
        self.value -= 1


def _floor_i32(value: float) -> int:
    if math.isnan(value):
        return 0
    return int(math.floor(value))


def contains_any_liquid(
    world: FluidOccupancyWorld,
    registry: FluidPresence,
    bounds: Aabb,
    budget: int,
) -> bool:
    """``contains_any_liquid`` (fluid_occupancy.rs:74).

    Inclusive floored AABB endpoints, as in ``LevelReader.findBlocksIn``.
    ``budget`` counts chunk requests, section requests and inspected cells.
    """
    a = bounds.min_position
    b = bounds.max_position
    if any(
        not math.isfinite(v)
        for v in (a.x, a.y, a.z, b.x, b.y, b.z)
    ):
        raise NonFiniteBounds()

    ax, ay, az = _floor_i32(a.x), _floor_i32(a.y), _floor_i32(a.z)
    bx, by, bz = _floor_i32(b.x), _floor_i32(b.y), _floor_i32(b.z)
    low_x, low_y, low_z = min(ax, bx), min(ay, by), min(az, bz)
    high_x, high_y, high_z = max(ax, bx), max(ay, by), max(az, bz)

    try:
        min_section_y = world.minimum_section_y()
        max_section_y = world.maximum_section_y()
    except FluidOccupancyError:
        raise
    except Exception as exc:  # noqa: BLE001 - wrap foreign world errors
        raise WorldError(str(exc)) from exc

    min_y = max(min_section_y, low_y >> 4)
    max_y = min(max_section_y, high_y >> 4)

    counter = _Budget(budget)
    for x in range(low_x >> 4, (high_x >> 4) + 1):
        for z in range(low_z >> 4, (high_z >> 4) + 1):
            counter.spend()
            try:
                chunk = world.chunk(x, z)
            except Exception as exc:  # noqa: BLE001
                raise WorldError(str(exc)) from exc
            for y in range(min_y, max_y + 1):
                counter.spend()
                try:
                    section = world.section(chunk, y)
                except Exception as exc:  # noqa: BLE001
                    raise WorldError(str(exc)) from exc
                if section.registry is not registry.registry_ref():
                    raise DataError("fluid query section registry mismatch")
                if not section.any_state(lambda state_id: registry.present[state_id.id]):
                    continue
                origin_x = x << 4
                origin_y = y << 4
                origin_z = z << 4
                sx_min = max(origin_x, low_x) & 15
                sy_min = max(origin_y, low_y) & 15
                sz_min = max(origin_z, low_z) & 15
                sx_max = min(origin_x + 15, high_x) & 15
                sy_max = min(origin_y + 15, high_y) & 15
                sz_max = min(origin_z + 15, high_z) & 15
                for sy in range(sy_min, sy_max + 1):
                    for sz in range(sz_min, sz_max + 1):
                        for sx in range(sx_min, sx_max + 1):
                            counter.spend()
                            try:
                                state_id = section.get(sy * 256 + sz * 16 + sx)
                            except Exception as exc:  # noqa: BLE001
                                raise DataError(str(exc)) from exc
                            if registry.present[state_id.id]:
                                return True

    # Native scans outside world height only if the predicate accepts air; it
    # still evaluates both height guards. The liquid predicate rejects air.
    try:
        world.minimum_y()
        world.maximum_y()
    except Exception as exc:  # noqa: BLE001
        raise WorldError(str(exc)) from exc
    return False
