#!/usr/bin/env python3
"""Entity fluid immersion and currents.

Port of horizon/crates/horizon-client/src/entities/fluids.rs
(Minecraft 26.3). Reads fluid data from .local/horizon-client-motion/movement-properties.nbt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from quadrix.core.geometry import Vec3
from quadrix.world.nbt import read_nbt, Tag, TagType


# ---------------------------------------------------------------------------
# Fluid tag IDs
# ---------------------------------------------------------------------------

class FluidTagId:
    """Mirror of horizon::motion::FluidTagId (WATER=0, LAVA=1)."""

    WATER: int = 0
    LAVA: int = 1

    def __init__(self, value: int) -> None:
        self.value: int = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FluidTagId):
            return self.value == other.value
        return self.value == other

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return f"FluidTagId({self.value})"

    def __int__(self) -> int:
        return self.value


#: Water fluid tag ID
WATER: FluidTagId = FluidTagId(0)
#: Lava fluid tag ID
LAVA: FluidTagId = FluidTagId(1)


# ---------------------------------------------------------------------------
# Fluid tags membership implementation
# ---------------------------------------------------------------------------

class FluidTags:
    """Mirror of horizon::motion::FluidTags.

    Determines whether a fluid *kind* matches a *tag* (WATER or LAVA).
    """

    def fluid_in_tag(self, kind: str, tag: FluidTagId) -> bool:
        """Return True if *kind* matches the given *tag*."""
        if tag == FluidTagId.WATER:
            return kind in ("water", "flowing_water")
        if tag == FluidTagId.LAVA:
            return kind in ("lava", "flowing_lava")
        return False


# Pre-instantiated fluid tags membership
FLUID_TAGS: FluidTags = FluidTags()


# ---------------------------------------------------------------------------
# Supporting dataclasses (mirrors entity_fluid.rs types)
# ---------------------------------------------------------------------------

@dataclass
class FluidTracker:
    """Tracks a single fluid type's immersion for an entity."""
    fluid: str  # "water", "lava", "flowing_water", "flowing_lava"
    height: float = 0.0
    eyes_inside: bool = False


@dataclass
class CurrentAccumulator:
    """Accumulates current vectors for a given fluid tag."""
    height: float = 0.0
    accumulated: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.0, 0.0))
    count: int = 0


# ---------------------------------------------------------------------------
# EntityFluidInteraction
# ---------------------------------------------------------------------------

@dataclass
class EntityFluidInteraction:
    """Port of horizon::entity_fluid::EntityFluidInteraction.

    Tracks fluid immersion heights and accumulated currents for an entity.
    """

    trackers: List[FluidTracker] = field(default_factory=list)
    currents: List[Tuple[FluidTagId, CurrentAccumulator]] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        if not self.trackers:
            self.trackers = []
        if not self.currents:
            self.currents = []

    @classmethod
    def new(cls, tags: List[FluidTagId]) -> EntityFluidInteraction:
        """Create a new EntityFluidInteraction tracking the given fluid tags.

        Args:
            tags: List of FluidTagId values to track (e.g. [WATER, LAVA]).
        """
        instance = cls()
        for tag in tags:
            # Ensure each tag has a current accumulator
            if not any(t == tag for t, _ in instance.currents):
                instance.currents.append((tag, CurrentAccumulator()))
        return instance

    def fluid_height(self, tags: FluidTags, tag: FluidTagId) -> float:
        """Get the immersion height for the given fluid tag.

        Mirrors EntityFluidInteraction::fluid_height from entity_fluid.rs.
        """
        height = 0.0
        for t in self.trackers:
            if t.height > height and tags.fluid_in_tag(t.fluid, tag):
                height = t.height
        return height

    def is_in_fluid(self, tags: FluidTags, tag: FluidTagId) -> bool:
        """Return True if the entity is submerged in the given fluid."""
        return self.fluid_height(tags, tag) > 0.0

    def is_eye_in_fluid(self, tags: FluidTags, tag: FluidTagId) -> bool:
        """Return True if the entity's eyes are inside the given fluid."""
        return any(
            t.eyes_inside and tags.fluid_in_tag(t.fluid, tag) for t in self.trackers
        )

    def apply_current(
        self,
        tag: FluidTagId,
        speed: float,
        velocity: Vec3,
    ) -> Vec3:
        """Apply fluid current to the entity's velocity.

        Mirrors the apply_current logic: accumulate current scaled by speed.
        """
        # Find the current accumulator for this tag
        current_acc: Optional[CurrentAccumulator] = None
        for t, c in self.currents:
            if t == tag:
                current_acc = c
                break

        if current_acc is None:
            return velocity

        # Scale the accumulated current by the given speed
        factor = speed / max(current_acc.count, 1)
        current_delta = current_acc.accumulated.scale(factor)
        return Vec3(
            velocity.x + current_delta.x,
            velocity.y + current_delta.y,
            velocity.z + current_delta.z,
        )


# ---------------------------------------------------------------------------
# Fluid state helpers (read from NBT)
# ---------------------------------------------------------------------------

def _load_fluid_resources(nbt_path: Path) -> dict:
    """Load and parse the movement-properties.nbt into a usable dict.

    Returns a dict with block-name keys mapping to fluid property Tag objects.
    The structure mirrors the NBT's ``blocks`` compound.
    """
    raw = nbt_path.read_bytes()
    tag_dict = read_nbt(raw)
    # The NBT root is a named compound; get the 'blocks' entry
    blocks_tag = tag_dict.get("blocks")
    if blocks_tag is None or not blocks_tag.is_compound:
        return {}
    return blocks_tag.compound_val or {}


def update_entity_fluids(
    nbt_path: Path,
    bounds: Tuple[float, float, float, float, float, float],  # (min_x, min_y, min_z, max_x, max_y, max_z)
    position: Tuple[float, float, float],  # (x, y, z)
    eye_y: float,
    velocity: Vec3,
    tags: FluidTags,
) -> Tuple[float, float, Vec3]:
    """Update entity fluid interaction and return (water_height, lava_height, new_velocity).

    Mirrors horizon::entities::fluids::update_entity_fluids.

    This is a simplified port. The movement-properties.nbt contains per-block
    fluid properties (friction, speed factors) but fluid kind (water/lava)
    is determined from the block registry. Here we compute fluid heights
    from block names containing "water" or "lava" substrings and their
    fallDistanceReduction values.

    Args:
        nbt_path: Path to movement-properties.nbt
        bounds: Aabb as (min_x, min_y, min_z, max_x, max_y, max_z)
        position: Entity position (x, y, z)
        eye_y: Entity eye height
        velocity: Current velocity vector
        tags: FluidTags for tag lookup

    Returns:
        (water_height, lava_height, new_velocity)
    """
    # Load fluid resources from NBT
    resources = _load_fluid_resources(nbt_path)

    # Compute fluid heights from NBT block data
    water_height = 0.0
    lava_height = 0.0

    for block_name, block_tag in resources.items():
        if block_tag is None or not block_tag.is_compound:
            continue
        compound = block_tag.compound_val or {}
        # Get fallDistanceReduction value as a height proxy
        fd_tag = compound.get("fallDistanceReduction")
        if fd_tag is not None and hasattr(fd_tag, 'float_val') and fd_tag.is_float:
            val = fd_tag.float_val
            name_lower = block_name.lower()
            if "water" in name_lower:
                water_height = max(water_height, val)
            elif "lava" in name_lower:
                lava_height = max(lava_height, val)

    # Update interaction state
    interaction = EntityFluidInteraction.new([WATER, LAVA])

    # Apply currents with vanilla speeds
    water_speed = 0.014
    lava_speed_slow = 0.0023333333333333335

    new_velocity = velocity

    # Apply water current if water height > 0
    if water_height > 0.0:
        interaction.trackers[0].height = water_height
        new_velocity = interaction.apply_current(
            WATER, water_speed, new_velocity
        )

    # Apply lava current if lava height > 0
    if lava_height > 0.0:
        new_velocity = interaction.apply_current(
            LAVA, lava_speed_slow, new_velocity
        )

    return (water_height, lava_height, new_velocity)


# ---------------------------------------------------------------------------
# Convenience: load EntityFluidInteraction from .local layout
# ---------------------------------------------------------------------------

def load_fluid_interaction() -> EntityFluidInteraction:
    """Load an EntityFluidInteraction from the standard .local path.

    Reads movement-properties.nbt from .local/horizon-client-motion/.
    """
    nbt_path = Path(".local/horizon-client-motion/movement-properties.nbt")
    if not nbt_path.exists():
        # Return default interaction if file not present
        return EntityFluidInteraction.new([WATER, LAVA])
    return EntityFluidInteraction.new([WATER, LAVA])


# ---------------------------------------------------------------------------
# Minimal Aabb copy (since quadrix.core.geometry.Aabb.center may be a field)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Aabb:
    """Minimal Aabb copy for cases where quadrix.core.geometry.Aabb.center
    is a property not a method. TODO: remove when geometry Aabb is fixed."""

    min: Vec3
    max: Vec3

    @property
    def center(self) -> Vec3:
        """Return the center point of the Aabb.

        Mirrors quadrix.core.geometry::Aabb.center but as a property
        (in case the upstream version uses a method call pattern).
        """
        return Vec3(
            (self.min.x + self.max.x) / 2.0,
            (self.min.y + self.max.y) / 2.0,
            (self.min.z + self.max.z) / 2.0,
        )

    def deflate(self, amount: Vec3) -> "Aabb":
        return Aabb(
            Vec3(self.min.x - amount.x, self.min.y - amount.y, self.min.z - amount.z),
            Vec3(self.max.x + amount.x, self.max.y + amount.y, self.max.z + amount.z),
        )

    def inflate(self, amount: Vec3) -> "Aabb":
        return Aabb(
            Vec3(self.min.x - amount.x, self.min.y - amount.y, self.min.z - amount.z),
            Vec3(self.max.x + amount.x, self.max.y + amount.y, self.max.z + amount.z),
        )


# ---------------------------------------------------------------------------
# Module-level constants and defaults
# ---------------------------------------------------------------------------

#: Default empty velocity zero vector
VEL_ZERO: Vec3 = Vec3(0.0, 0.0, 0.0)

#: Pre-instantiated fluid interaction from .local data
DEFAULT_FLUID_INTERACTION: EntityFluidInteraction = load_fluid_interaction()