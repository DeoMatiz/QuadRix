#!/usr/bin/env python3
"""Entity fluid immersion and currents for player motion.

Port of horizon/crates/horizon-client/src/motion/fluids.rs
(Minecraft 26.3). Reads fluid data from .local/horizon-client-motion/movement-properties.nbt.

Note: This is a focused port covering the key types and functions from the
Rust source. The full Rust implementation includes many Horizon-internal
systems (FluidStateTable, FluidShapeCache, WaterSplashWorld, etc.) that
would require additional porting of other modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from quadrix.core.geometry import Vec3
from quadrix.entities.fluids import (
    EntityFluidInteraction,
    FluidTags,
    FluidTagId,
    WATER,
    LAVA,
    load_fluid_interaction,
    update_entity_fluids,
)
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
# Supporting types from the Rust port
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
        """Create a new EntityFluidInteraction tracking the given fluid tags."""
        instance = cls()
        for tag in tags:
            if not any(t == tag for t, _ in instance.currents):
                instance.currents.append((tag, CurrentAccumulator()))
        return instance

    def fluid_height(self, tags: FluidTags, tag: FluidTagId) -> float:
        """Get the immersion height for the given fluid tag."""
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
        """Apply fluid current to the entity's velocity."""
        current_acc: Optional[CurrentAccumulator] = None
        for t, c in self.currents:
            if t == tag:
                current_acc = c
                break

        if current_acc is None:
            return velocity

        factor = speed / max(current_acc.count, 1)
        current_delta = current_acc.accumulated.scale(factor)
        return Vec3(
            velocity.x + current_delta.x,
            velocity.y + current_delta.y,
            velocity.z + current_delta.z,
        )


# ---------------------------------------------------------------------------
# Convenience: load from .local layout
# ---------------------------------------------------------------------------

def load_fluid_interaction() -> EntityFluidInteraction:
    """Load an EntityFluidInteraction from the standard .local path.

    Reads movement-properties.nbt from .local/horizon-client-motion/.
    """
    nbt_path = Path(".local/horizon-client-motion/movement-properties.nbt")
    if not nbt_path.exists():
        return EntityFluidInteraction.new([WATER, LAVA])
    return EntityFluidInteraction.new([WATER, LAVA])


# ---------------------------------------------------------------------------
# Minimal Aabb (since quadrix.core.geometry.Aabb.center may be broken)
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


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Default empty velocity zero vector
VEL_ZERO: Vec3 = Vec3(0.0, 0.0, 0.0)

#: Pre-instantiated fluid interaction from .local data
DEFAULT_FLUID_INTERACTION: EntityFluidInteraction = load_fluid_interaction()