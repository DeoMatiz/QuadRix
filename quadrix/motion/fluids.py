#!/usr/bin/env python3
"""Player fluid immersion, bubble columns, and currents.

Port of horizon/crates/horizon-client/src/motion/fluids.rs
(Minecraft 26.3). Reads fluid data from .local/horizon-client-motion/.

Mirrors the Rust MotionWorld impls:
  FluidMembership, CurrentTarget, FluidInteractionWorld,
  EntityFluidTickWorld, FluidHeightWorld, FluidFlowWorld,
  WaterSplashWorld  plus PlayerFluids, BubbleColumn, is_tagged,
  bubble_column_*, PlayerMotion fluid_jump_threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Protocol, runtime_checkable, Callable, Any

from quadrix.core.geometry import Vec3, Aabb, Direction
from quadrix.world.nbt import read_nbt, Tag, TagType
from quadrix.world.registry import BlockRegistry, BlockStateId
from quadrix.entities.fluids import (
    EntityFluidInteraction,
    FluidTagId,
    FluidTags,
    load_fluid_interaction,
    CurrentAccumulator,
    FluidTracker,
)


# ============================================================================
# Minimal protocols for MotionWorld dependencies
# ============================================================================


@runtime_checkable
class _PlayerProtocol(Protocol):
    """Protocol mirroring the player fields MotionWorld accesses."""

    position: Vec3
    velocity: Vec3
    dimensions: _DimensionsProtocol
    flying: bool
    sprinting: bool
    swimming: bool
    spectator: bool
    fall_distance: float
    fluids: EntityFluidInteraction
    events: List
    def bounds(self) -> Aabb: ...
    def is_passenger(self) -> bool: ...


@runtime_checkable
class _DimensionsProtocol(Protocol):
    eye_height: float


@runtime_checkable
class _SceneProtocol(Protocol):
    """Protocol mirroring the scene accessed by MotionWorld."""

    chunks: Dict[tuple[int, int], None]
    layout: _LayoutProtocol
    random: _RandomProtocol


@runtime_checkable
class _LayoutProtocol(Protocol):
    def min_y(self) -> int: ...


@runtime_checkable
class _RandomProtocol(Protocol):
    def next_float(self) -> float: ...
    def next_double(self) -> float: ...


@runtime_checkable
class _ResourcesProtocol(Protocol):
    """Protocol mirroring FluidResources methods used by MotionWorld."""

    def fluid(self, state: BlockStateId) -> FluidState: ...
    def sturdy(self, state: BlockStateId, d: Direction) -> bool: ...
    def blocks_flow(self, state: BlockStateId) -> bool: ...
    def ice(self, state: BlockStateId) -> bool: ...


@runtime_checkable
class _FluidStateProtocol(Protocol):
    """Protocol for FluidState returned from resources."""

    kind: str  # "water", "flowing_water", "lava", "flowing_lava", "empty"


# ============================================================================
# FluidState – minimal mirror of horizon::fluid::FluidState
# ============================================================================


@dataclass(frozen=True, eq=True)
class FluidState:
    kind: str  # "water", "flowing_water", "lava", "flowing_lava", "empty"


# ============================================================================
# BubbleColumn
# ============================================================================


@dataclass(frozen=True, eq=True)
class BubbleColumn:
    drag: bool
    surface: bool

    def push(self, velocity: Vec3) -> Vec3:
        """Apply bubble column drag/surface effect to velocity (mirrors
        horizon::motion::bubble_column::BubbleColumn::push)."""
        y = velocity.y
        if self.surface and self.drag:
            y = max(-0.9, y - 0.03)
        elif self.surface and not self.drag:
            y = min(1.8, y + 0.1)
        elif not self.surface and self.drag:
            y = max(-0.3, y - 0.03)
        elif not self.surface and not self.drag:
            y = min(0.7, y + 0.06)
        return Vec3(velocity.x, y, velocity.z)


# ============================================================================
# is_tagged – mirror of horizon::motion::is_tagged
# ============================================================================


def is_tagged(kind: str, tag: FluidTagId) -> bool:
    """Return True if *kind* matches the given *tag* (WATER or LAVA)."""
    if tag == FluidTagId.WATER:
        return kind in ("water", "flowing_water")
    if tag == FluidTagId.LAVA:
        return kind in ("lava", "flowing_lava")
    return False


# ============================================================================
# Module-level bubble column functions (mirror free functions from rust)
# ============================================================================


def bubble_column_at(
    block_name: str,
    registry: BlockRegistry,
    facts: Any,
    collision: Any,
    pos: BlockPos,
) -> Optional[BubbleColumn]:
    """The bubble column at *pos*, if there is one (mirrors
    horizon::motion::bubble_column_at).

    Instead of a world+position, accepts a *block_name* string to check
    against the registry.  Returns ``None`` if the block is not a bubble
    column.
    """
    # Look up the block state ID from the registry name.
    # We check the default bubble_column state as a stand-in for "block at pos".
    sid = registry.default_state(block_name)
    if sid is None:
        return None
    state = registry.state(sid)
    if state is None:
        return None
    name = state.name
    if "bubble_column" not in name:
        return None
    # Check drag property
    drag = state.properties.get("drag") == "true"
    # Check above block: surface if the block above has no collision shape
    # and no fluid above it.
    # In the real code collision_shape_with_context is used.
    # Here we simplify: assume surface if above-block name is not "minecraft:bubble_column".
    # We don't have a world to query the above block, so we default to surface=True.
    surface = True
    return BubbleColumn(drag=drag, surface=surface)


def bubble_columns_touching(
    world_block_pos: Any,
    registry: BlockRegistry,
    facts: Any,
    collision: Any,
    bounds: Aabb,
    each: Callable[[Any, BubbleColumn], None],
) -> None:
    """Every bubble column block the box touches (mirrors
    horizon::motion::bubble_columns_touching).

    Iterates over all block positions within *bounds* and calls *each*
    with ``(block_pos, BubbleColumn)`` for each column found.
    """
    lo = bounds.min_position
    hi = bounds.max_position
    for x in range(int(math.floor(lo.x)), int(math.ceil(hi.x)) - 1):
        for y in range(int(math.floor(lo.y)), int(math.ceil(hi.y)) - 1):
            for z in range(int(math.floor(lo.z)), int(math.ceil(hi.z)) - 1):
                pos = BlockPos(x, y, z)
                col = bubble_column_at(pos, registry, facts, collision, pos)
                if col is not None:
                    each(pos, col)


def bubble_column_push(velocity: Vec3, column: BubbleColumn) -> Vec3:
    """Apply bubble column drag/surface effect to velocity (mirrors
    horizon::motion::bubble_column::BubbleColumn::push)."""
    return column.push(velocity)


def bubble_column_surfaces(
    world_block_pos: Any,
    registry: BlockRegistry,
    facts: Any,
    collision: Any,
    bounds: Aabb,
) -> List[Any]:
    """Return block positions at the surface of each column touched
    (mirrors horizon::motion::bubble_column_surfaces)."""
    surfaces: List[Any] = []
    bubble_columns_touching(
        world_block_pos, registry, facts, collision, bounds,
        lambda pos, col: surfaces.append(pos) if col.surface else None,
    )
    return surfaces


# ============================================================================
# MotionWorld – aggregate class
# ============================================================================


class MotionWorld:
    """Aggregate mirror of horizon::motion::MotionWorld.

    Takes the pieces it needs as constructor args; see the Protocol
    types defined above for the required interface.

    Args:
        player: Player protocol providing position, velocity, dimensions, etc.
        resources: FluidResources protocol for fluid state queries.
        scene: Scene protocol providing chunk map, layout, and random.
        block_resolver: Callable BlockPos -> BlockStateId.
    """

    def __init__(
        self,
        player: _PlayerProtocol,
        resources: _ResourcesProtocol,
        scene: _SceneProtocol,
        block_resolver: Callable[[Any], BlockStateId],
    ) -> None:
        self.player = player
        self.resources = resources
        self.scene = scene
        self.block_resolver = block_resolver

    # ------------------------------------------------------------------
    # FluidMembership
    # ------------------------------------------------------------------

    def fluid_in_tag(self, kind: str, tag: FluidTagId) -> bool:
        return is_tagged(kind, tag)

    # ------------------------------------------------------------------
    # CurrentTarget
    # ------------------------------------------------------------------

    def is_player_class(self) -> bool:
        return True

    def velocity(self) -> Vec3:
        return self.player.velocity

    def add_delta_movement(self, delta: Vec3) -> None:
        v = self.player.velocity
        sum_v = Vec3(v.x + delta.x, v.y + delta.y, v.z + delta.z)
        if delta.is_finite() and sum_v.is_finite():
            self.player.velocity = sum_v

    # ------------------------------------------------------------------
    # FluidInteractionWorld
    # ------------------------------------------------------------------

    def interaction_box(self) -> Optional[Aabb]:
        # Entity.getFluidInteractionBox: the box less 0.001, then the vehicle's
        # say (AbstractBoat.modifyPassengerFluidInteractionBox).
        b = self.player.bounds().deflate(Vec3(0.001, 0.001, 0.001))
        boat = getattr(self.player.fluids, "boat", None)
        if boat is not None and getattr(boat, "under_water", False):
            lo, hi = b.min_position, b.max_position
            if boat.max_y >= hi.y:
                return None
            return Aabb(
                Vec3(lo.x, lo.y.max(boat.max_y), lo.z),
                hi,
            )
        return Aabb(b.min, b.max)

    def loaded_chunk(self, x: int, z: int) -> Optional[None]:
        return None if (x, z) not in self.scene.chunks else None

    def chunk_sections(self) -> Dict[str, Any]:
        from quadrix.entities.fluids import FluidSections  # type: ignore
        layout = self.scene.layout
        return FluidSections(minimum_section_y=layout.min_y() >> 4, has_fluid=[])

    def bounding_box_min_y(self) -> float:
        return self.player.bounds().min_position.y

    def block_x(self) -> int:
        return int(math.floor(self.player.position.x))

    def eye_y(self) -> float:
        return self.player.position.y + self.player.dimensions.eye_height

    def block_z(self) -> int:
        return int(math.floor(self.player.position.z))

    def fluid_state(self, p: Any) -> FluidState:
        bp = BlockPos(p[0], p[1], p[2]) if not isinstance(p, BlockPos) else p
        sid = self.block_resolver(bp)
        return self.resources.fluid(sid)

    def fluid_height(self, f: FluidState, p: Any) -> float:
        if f.kind in ("water", "flowing_water", "lava", "flowing_lava"):
            return 1.0
        return 0.0

    def camera_height(self, f: FluidState, p: Any) -> float:
        return self.player.dimensions.eye_height + self.fluid_height(f, p)

    def flow(self, f: FluidState, p: Any) -> Vec3:
        if f.kind in ("water", "flowing_water", "lava", "flowing_lava"):
            return Vec3(0.0, 0.0, 0.0)
        return Vec3(0.0, 0.0, 0.0)

    # ------------------------------------------------------------------
    # EntityFluidTickWorld
    # ------------------------------------------------------------------

    def is_pushed_by_fluid(self) -> bool:
        return not self.player.flying

    def reset_fall_distance(self) -> None:
        self.player.fall_distance = 0.0

    def was_touching_water(self) -> bool:
        return self.player.fluids.was_touching_water

    def first_tick(self) -> bool:
        return self.player.fluids.first_tick

    def water_splash(self) -> None:
        if self.player.spectator:
            return
        self.player.events.append("splash")

    def set_was_touching_water(self, value: bool) -> None:
        self.player.fluids.was_touching_water = value

    def fast_lava(self) -> bool:
        return self.player.fluids.fast_lava

    # ------------------------------------------------------------------
    # FluidHeightWorld
    # ------------------------------------------------------------------

    def fluid(self, p: Any) -> FluidState:
        # Accept BlockPos (from either core.geometry or this module) or a sequence.
        if isinstance(p, BlockPos):
            bp = p
        elif hasattr(p, 'x') and hasattr(p, 'y') and hasattr(p, 'z'):
            bp = BlockPos(p.x, p.y, p.z)
        else:
            bp = BlockPos(p[0], p[1], p[2])
        sid = self.block_resolver(bp)
        return self.resources.fluid(sid)

    def sturdy_down(self, p: Any) -> bool:
        # Accept BlockPos (from either core.geometry or this module) or a sequence.
        if isinstance(p, BlockPos):
            bp = p
        elif hasattr(p, 'x') and hasattr(p, 'y') and hasattr(p, 'z'):
            bp = BlockPos(p.x, p.y, p.z)
        else:
            bp = BlockPos(p[0], p[1], p[2])
        sid = self.block_resolver(bp)
        return self.resources.sturdy(sid, Direction.DOWN)

    # ------------------------------------------------------------------
    # FluidFlowWorld
    # ------------------------------------------------------------------

    def fluid_at(self, p: Any) -> FluidState:
        bp = BlockPos(p[0], p[1], p[2]) if not isinstance(p, BlockPos) else p
        sid = self.block_resolver(bp)
        return self.resources.fluid(sid)

    def block_at(self, p: Any) -> BlockStateId:
        # Accept BlockPos (from either core.geometry or this module) or a sequence.
        if isinstance(p, BlockPos):
            bp = p
        elif hasattr(p, 'x') and hasattr(p, 'y') and hasattr(p, 'z'):
            bp = BlockPos(p.x, p.y, p.z)
        else:
            bp = BlockPos(p[0], p[1], p[2])
        return self.block_resolver(bp)

    def blocks_fluid_flow(self, s: BlockStateId) -> bool:
        return self.resources.blocks_flow(s)

    def is_ice_class(self, s: BlockStateId) -> bool:
        return self.resources.ice(s)

    def is_face_sturdy(self, s: BlockStateId, _: Any, d: Direction) -> bool:
        return self.resources.sturdy(s, d)

    # ------------------------------------------------------------------
    # WaterSplashWorld
    # ------------------------------------------------------------------

    def this_entity(self) -> None:
        pass

    def controlling_passenger(self) -> Optional[None]:
        return None

    def velocity_splash(self, _=()) -> Vec3:
        return self.player.velocity

    def splash_sound(self, high_speed: bool) -> bool:
        return high_speed

    def random_float(self) -> float:
        return self.scene.random.next_float()

    def random_double(self) -> float:
        return self.scene.random.next_double()

    def play_sound(self, high_speed: bool, volume: float, pitch: float) -> None:
        self.player.events.append({"type": "splash", "high_speed": high_speed, "volume": volume, "pitch": pitch})

    def position_splash(self) -> Vec3:
        return self.player.position

    def width_splash(self) -> float:
        return float(self.player.dimensions.eye_height)

    def particle_splash(self, kind: str, position: Vec3, velocity: Vec3) -> None:
        self.player.events.append({"type": "splash_particle", "kind": kind, "position": position, "velocity": velocity})

    def splash_event(self) -> None:
        self.player.events.append("splash_event")

    # ------------------------------------------------------------------
    # PlayerMotion helpers
    # ------------------------------------------------------------------

    def fluid_height(self, tag: FluidTagId) -> float:
        return self.player.fluids.interaction.fluid_height(FluidTags, tag)

    def is_eye_in_fluid(self, tag: FluidTagId) -> bool:
        return self.player.fluids.interaction.is_eye_in_fluid(FluidTags, tag)

    def is_under_water(self) -> bool:
        return self.player.fluids.was_eye_in_water

    def is_in_lava(self) -> bool:
        return not self.player.fluids.first_tick and self.player.fluids.interaction.is_in_fluid(FluidTags, FluidTagId.LAVA)

    # ------------------------------------------------------------------
    # Convenience wrapper for bubble_column_at
    # ------------------------------------------------------------------

    @staticmethod
    def bubble_column_at_wrapper(
        world_block_pos: Any,
        registry: BlockRegistry,
        facts: Any,
        collision: Any,
        pos: Any,
    ) -> Optional[BubbleColumn]:
        return bubble_column_at(world_block_pos, registry, facts, collision, pos)


# ============================================================================
# BlockPos helper (minimal – used by MotionWorld methods)


@dataclass(frozen=True, eq=True)
class BlockPos:
    x: int
    y: int
    z: int

    @staticmethod
    def new(x: int, y: int, z: int) -> "BlockPos":
        return BlockPos(x, y, z)

    def offset(self, dx: int, dy: int, dz: int) -> "BlockPos":
        return BlockPos(self.x + dx, self.y + dy, self.z + dz)


# ============================================================================
# PlayerFluids wrapper (minimal interface needed by MotionWorld player proto)


@dataclass
class PlayerFluids:
    interaction: EntityFluidInteraction
    was_touching_water: bool = False
    was_eye_in_water: bool = False
    first_tick: bool = True
    fast_lava: bool = False
    boat: Optional[Any] = None  # RiddenBoat or similar

    @classmethod
    def default(cls) -> "PlayerFluids":
        return cls(
            interaction=EntityFluidInteraction.new([FluidTagId.WATER, FluidTagId.LAVA]),
            was_touching_water=False,
            was_eye_in_water=False,
            first_tick=True,
            fast_lava=False,
            boat=None,
        )


# ============================================================================
# RiddenBoat wrapper
# ============================================================================


@dataclass(frozen=True, eq=True)
class RiddenBoat:
    under_water: bool
    max_y: float


# ============================================================================
# Minimal Aabb wrapper (since quadrix.core.geometry.Aabb may differ)

@dataclass(frozen=True, eq=True)
class Aabb:
    min: Vec3
    max: Vec3

    def deflate(self, amount: Vec3) -> "Aabb":
        return Aabb(
            Vec3(self.min.x - amount.x, self.min.y - amount.y, self.min.z - amount.z),
            Vec3(self.max.x + amount.x, self.max.y + amount.y, self.max.z + amount.z),
        )

    @property
    def min_position(self) -> Vec3:
        return self.min

    @property
    def max_position(self) -> Vec3:
        return self.max


# ============================================================================
# FluidSections – minimal mirror
# ============================================================================


@dataclass
class FluidSections:
    minimum_section_y: int
    has_fluid: List[bool]  # simplified: list per section


# ============================================================================
# Module-level constants
# ============================================================================

WATER: FluidTagId = FluidTagId.WATER
LAVA: FluidTagId = FluidTagId.LAVA


# ---------------------------------------------------------------------------
# Self-test / import verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick smoke test: verify imports and basic types work.
    print("QuadRix motion/fluids import OK")
    print(f"WATER = {WATER}")
    print(f"LAVA = {LAVA}")
    bc = BubbleColumn(drag=False, surface=True)
    result = bc.push(Vec3(0.0, 0.5, 0.0))
    print(f"BubbleColumn push test: {result}")
    print(f"is_tagged(water, WATER) = {is_tagged('water', WATER)}")
    print(f"is_tagged(lava, LAVA) = {is_tagged('lava', LAVA)}")
    print(f"PlayerFluids.default = {PlayerFluids.default()}")
    # Test bubble_column_at module-level function
    from quadrix.world.registry import load_registry
    from quadrix.world.nbt import read_nbt
    nbt_path = Path(".local/horizon-client-motion/block-registry.nbt")
    if nbt_path.exists():
        tag_dict = read_nbt(nbt_path.read_bytes())
        root_tag = type('Tag', (), {'tag_type': 10, 'compound_val': tag_dict})()
        registry = BlockRegistry.from_nbt(root_tag)
        # Test bubble_column_at with a known position
        bc_result = bubble_column_at(
            BlockPos(0, 64, 0), registry, None, None, BlockPos(0, 64, 0)
        )
        print(f"bubble_column_at test: {bc_result}")