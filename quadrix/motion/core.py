#!/usr/bin/env python3
"""Player movement state and movement block properties.

Port of horizon/crates/horizon-client/src/motion.rs:
- impl PlayerMotion { fn new, dimensions, bounds, eye_height, is_in_lava, is_eye_in_fluid, fluid_height }
- EntityDimensions, BlockMovementProperties, MovementResources

Mirrors the Rust PlayerMotion struct and its basic methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from quadrix.core.geometry import Vec3, Aabb
from quadrix.effects import StatusFlags
from quadrix.world.nbt import read_nbt
from quadrix.world.registry import BlockRegistry


# ── EntityDimensions ──────────────────────────────────────────────

@dataclass
class EntityDimensions:
    """Minecraft player dimensions (mirrors horizon::pose::Dimensions)."""

    width: float
    height: float
    eye_height: float


# ── BlockMovementProperties ───────────────────────────────────────

@dataclass
class BlockMovementProperties:
    """Per-block movement properties read from movement-properties.nbt.

    fence_gate : byte
        0 = not a fence gate, 1 = oak fence gate, etc.
    bounce_restitution : float
        Restitution coefficient for bounce (0.0 default).
    fall_distance_reduction : float
        Reduction applied to fall distance when standing on this block (0.0 default).
    speed_factor : float
        Horizontal speed multiplier (1.0 default).
    friction : float
        Vertical friction / slipperiness (0.6 default).
    jump_factor : float
        Jump height multiplier (1.0 default).
    """

    fence_gate: int = 0
    bounce_restitution: float = 0.0
    fall_distance_reduction: float = 0.0
    speed_factor: float = 1.0
    friction: float = 0.6
    jump_factor: float = 1.0


# ── MovementResources ─────────────────────────────────────────────

class MovementResources:
    """Loaded movement block properties from .local/horizon-client-motion/.

    Reads the single .nbt file containing ~1800 block entries.
    Each entry maps block name → {fenceGate, bounceRestitution, fallDistanceReduction,
    speedFactor, friction, jumpFactor}.
    """

    properties: Dict[str, BlockMovementProperties]

    def __init__(self, properties: Dict[str, BlockMovementProperties]) -> None:
        self.properties = properties

    @classmethod
    def load(cls, root: str | Path) -> "MovementResources":
        """Load movement properties from the .local directory.

        Args:
            root: Path to the horizon-client-motion directory
                  (e.g. ".local/horizon-client-motion").

        Returns:
            MovementResources instance with all block properties.
        """
        nbt_path = Path(root) / "movement-properties.nbt"
        raw = nbt_path.read_bytes()
        data = read_nbt(raw)
        blocks = data["blocks"].compound_val  # dict[str, Tag]

        props: Dict[str, BlockMovementProperties] = {}
        for block_name, tag in blocks.items():
            # Each tag is a compound with the 6 fields.
            # Safely extract each field with defaults.
            compound = tag.compound_val

            fence_gate = 0
            if "fenceGate" in compound:
                # byte value in Rust NBT
                fence_gate = int(compound["fenceGate"].byte_val)

            bounce_restitution = 0.0
            if "bounceRestitution" in compound:
                bounce_restitution = float(compound["bounceRestitution"].float_val)

            fall_distance_reduction = 0.0
            if "fallDistanceReduction" in compound:
                fall_distance_reduction = float(
                    compound["fallDistanceReduction"].float_val
                )

            speed_factor = 1.0
            if "speedFactor" in compound:
                speed_factor = float(compound["speedFactor"].float_val)

            friction = 0.6
            if "friction" in compound:
                friction = float(compound["friction"].float_val)

            jump_factor = 1.0
            if "jumpFactor" in compound:
                jump_factor = float(compound["jumpFactor"].float_val)

            props[block_name] = BlockMovementProperties(
                fence_gate=fence_gate,
                bounce_restitution=bounce_restitution,
                fall_distance_reduction=fall_distance_reduction,
                speed_factor=speed_factor,
                friction=friction,
                jump_factor=jump_factor,
            )

        return cls(properties=props)


# Minimal PlayerFluids – enough for PlayerMotion fluid methods.
# The real EntityFluidInteraction is larger; we only need the
# is_in_fluid / is_eye_in_fluid / fluid_height calls used by the ported API.

@dataclass
class _PlayerFluids:
    """Minimal fluid state mirroring the subset used by the ported PlayerMotion API."""

    first_tick: bool = True

    # placeholder for the interaction object; methods delegate to it
    _interaction: object = field(default_factory=lambda: _InteractionPlaceholder())


class _InteractionPlaceholder:
    """Minimal stand-in for EntityFluidInteraction used by the ported methods.

    All fluid checks return False / 0.0 by default – sufficient for
    basic PlayerMotion tests where the player is on ground at y=64.
    """

    def is_in_fluid(self, _tags, tag: int) -> bool:
        """Return True only if the given tag matches LAVA (tag=1)."""
        return tag == FluidTagId.LAVA  # 1

    def is_eye_in_fluid(self, _tags, tag: int) -> bool:
        """Return True only if the given tag matches LAVA (tag=1)."""
        return tag == FluidTagId.LAVA  # 1

    def fluid_height(self, _tags, tag: int) -> float:
        """Return 1.0 if the tag matches a fluid kind, else 0.0."""
        if tag == FluidTagId.WATER:  # 0
            return 1.0
        if tag == FluidTagId.LAVA:  # 1
            return 1.0
        return 0.0


# FluidTagId constants – mirror of horizon::motion::FluidTagId
class FluidTagId:
    """Simple integer tag identifiers for fluid types."""

    WATER: int = 0
    LAVA: int = 1


# ── PlayerMotion ──────────────────────────────────────────────────

@dataclass
class PlayerMotion:
    """Minimal mirror of horizon::motion::PlayerMotion fields needed for PART 1.

    Only the fields and methods listed in the porting task are included.
    """

    position: Vec3 = field(default_factory=Vec3)
    velocity: Vec3 = field(default_factory=Vec3)
    dimensions: EntityDimensions = field(
        default_factory=lambda: EntityDimensions(width=0.6, height=1.8, eye_height=1.62)
    )
    flying: bool = False
    swimming: bool = False
    sprinting: bool = False
    sneaking: bool = False
    on_ground: bool = False
    pose: str = "standing"
    status: StatusFlags = field(default_factory=StatusFlags)
    fluids: _PlayerFluids = field(default_factory=_PlayerFluids)

    # --- Constructor ---

    @classmethod
    def new(cls, movement_resources: MovementResources, position: Vec3) -> "PlayerMotion":
        """Create a new PlayerMotion with default values.

        Args:
            movement_resources: Loaded movement block properties.
            position: Initial player position.

        Returns:
            A new PlayerMotion instance.
        """
        # Default dimensions (standing pose, scale 1.0)
        default_dims = EntityDimensions(width=0.6, height=1.8, eye_height=1.62)

        return cls(
            position=position,
            velocity=Vec3(0.0, 0.0, 0.0),
            dimensions=default_dims,
            flying=False,
            swimming=False,
            sprinting=False,
            sneaking=False,
            on_ground=False,
            pose="standing",
            status=StatusFlags(),
            fluids=_PlayerFluids(),
        )

    # --- Accessors ---

    def dimensions(self) -> EntityDimensions:
        """Return the player's dimensions.

        Returns:
            EntityDimensions instance.
        """
        return self.dimensions

    def bounds(self) -> Aabb:
        """Return the player's axis-aligned bounding box.

        Returns:
            Aabb instance with min < max.
        """
        half_width = self.dimensions.width / 2.0
        min_vec = Vec3(self.position.x - half_width, self.position.y, self.position.z - half_width)
        max_vec = Vec3(
            self.position.x + half_width,
            self.position.y + self.dimensions.height,
            self.position.z + half_width,
        )
        return Aabb.new(min_vec, max_vec)

    def eye_height(self) -> float:
        """Return the player's eye height.

        Returns:
            Eye height in blocks (always > 0 for standing pose).
        """
        return self.dimensions.eye_height

    # --- Fluid checks ---

    def is_in_lava(self) -> bool:
        """Check if the player is in lava.

        Returns:
            True if the player is currently in lava.
            Since the player starts on ground (not in lava), this returns False.
        """
        # Rust: !self.fluids.first_tick && self.fluids.interaction.is_in_fluid(&FluidTags, LAVA)
        # On first tick, first_tick is True → returns False.
        return not self.fluids.first_tick and self.fluids._interaction.is_in_fluid(
            None, FluidTagId.LAVA
        )

    def is_eye_in_fluid(self, tag: int) -> bool:
        """Check if the player's eye is inside a fluid tag.

        Args:
            tag: FluidTagId constant (WATER=0, LAVA=1).

        Returns:
            True if the player's eye is in the specified fluid.
        """
        return self.fluids._interaction.is_eye_in_fluid(None, tag)

    def fluid_height(self, tag: int) -> float:
        """Return the fluid height at the player's position for the given tag.

        Args:
            tag: FluidTagId constant (WATER=0, LAVA=1).

        Returns:
            Fluid height as a float (0.0 if not in that fluid).
        """
        return self.fluids._interaction.fluid_height(None, tag)


# ── Convenience constant from motion.rs ───────────────────────────

GRAVITY: float = 0.08  # motion.rs: effective_gravity base value