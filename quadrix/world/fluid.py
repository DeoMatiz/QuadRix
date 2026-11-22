#!/usr/bin/env python3
"""[QuadRix] Fluid states carried by the pinned vanilla block-state registry.

Port of horizon/crates/horizon-world/src/fluid.rs (Minecraft 26.3).

Provides :class:`FluidKind`, :class:`FluidState`, :class:`FluidStateTable` and
:class:`FluidBlockBindings`.  Flow updates, spreading and entity interaction are
separate simulation work (see ``quadrix/world/fluid_flow.py``).

Numeric fidelity: ``own_height`` reproduces Rust's ``f32::from(amount) / 9.0``
by rounding the division to an IEEE-754 single (see :func:`_f32_div`).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Protocol

from quadrix.world.registry import (
    BlockProperties,
    BlockRegistry,
    BlockState,
    BlockStateId,
)

__all__ = [
    "FluidKind",
    "FluidState",
    "FluidStateTable",
    "FluidBlockBindings",
    "FluidHeightWorld",
    "java_integer",
]


# ---------------------------------------------------------------------------
# f32 helpers — Rust arithmetic here is single precision
# ---------------------------------------------------------------------------

def _f32(value: float) -> float:
    """Round ``value`` to the nearest IEEE-754 single."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _f32_div(a: float, b: float) -> float:
    """Approximate ``f32 / f32``: divide then round the result to single."""
    return _f32(float(a) / float(b))


def _wrapping_add(a: int, b: int) -> int:
    """Rust ``i32::wrapping_add``."""
    return ((a + b + 2**31) % 2**32) - 2**31


# ---------------------------------------------------------------------------
# FluidKind — fluid.rs:12
# ---------------------------------------------------------------------------

class FluidKind(Enum):
    Empty = 0
    FlowingWater = 1
    Water = 2
    FlowingLava = 3
    Lava = 4

    #: ``FluidKind::ALL`` (fluid.rs:20) — declaration order.
    def fluid_name(self) -> str:
        """``FluidKind::name`` (fluid.rs:27)."""
        return _FLUID_NAMES[self]

    @staticmethod
    def from_name(name: str) -> Optional["FluidKind"]:
        """``FluidKind::from_name`` (fluid.rs:36)."""
        return _FLUID_BY_NAME.get(name)

    def same_family(self, other: "FluidKind") -> bool:
        """``FluidKind::same_family`` (fluid.rs:39)."""
        if self == FluidKind.Empty or other == FluidKind.Empty:
            return self == FluidKind.Empty and other == FluidKind.Empty
        if self in (FluidKind.Water, FluidKind.FlowingWater):
            return other in (FluidKind.Water, FluidKind.FlowingWater)
        return other in (FluidKind.Lava, FluidKind.FlowingLava)

    def mask(self) -> int:
        """``FluidKind::mask`` (fluid.rs:53)."""
        return 1 << self.value


_FLUID_NAMES = {
    FluidKind.Empty: "minecraft:empty",
    FluidKind.FlowingWater: "minecraft:flowing_water",
    FluidKind.Water: "minecraft:water",
    FluidKind.FlowingLava: "minecraft:flowing_lava",
    FluidKind.Lava: "minecraft:lava",
}
_FLUID_BY_NAME = {name: kind for kind, name in _FLUID_NAMES.items()}

#: ``FluidKind::ALL`` in declaration order.
FLUID_KIND_ALL: tuple[FluidKind, ...] = (
    FluidKind.Empty,
    FluidKind.FlowingWater,
    FluidKind.Water,
    FluidKind.FlowingLava,
    FluidKind.Lava,
)


# ---------------------------------------------------------------------------
# java_integer — registry::java_integer (accepts optional sign + digits)
# ---------------------------------------------------------------------------

def java_integer(text: str) -> Optional[int]:
    """Parse a Java-style base-10 integer, or ``None`` if malformed.

    Mirrors the permissive ``registry::java_integer`` helper used by
    ``FluidState::from_json`` for the ``level`` property.
    """
    if not text:
        return None
    index = 0
    negative = False
    if text[index] in "+-":
        negative = text[index] == "-"
        index += 1
    if index >= len(text):
        return None
    value = 0
    digits = 0
    while index < len(text):
        char = text[index]
        if not ("0" <= char <= "9"):
            return None
        value = value * 10 + (ord(char) - 48)
        digits += 1
        index += 1
    if digits == 0:
        return None
    return -value if negative else value


# ---------------------------------------------------------------------------
# FluidHeightWorld — fluid.rs:258
# ---------------------------------------------------------------------------

class FluidHeightWorld(Protocol):
    """Queries required by fluid surface height and camera immersion."""

    def fluid(self, position) -> "FluidState":
        ...

    def sturdy_down(self, position) -> bool:
        ...


# ---------------------------------------------------------------------------
# FluidState — fluid.rs:57
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class FluidState:
    kind: FluidKind
    amount: int = 0
    falling: bool = False

    # -- constructors -------------------------------------------------------

    @staticmethod
    def new(kind: FluidKind, amount: int, falling: bool) -> "FluidState":
        """``FluidState::new`` (fluid.rs:131) — empty ignores amount/falling."""
        if kind == FluidKind.Empty:
            return FluidState.EMPTY()
        return FluidState(kind=kind, amount=int(amount), falling=bool(falling))

    @staticmethod
    def EMPTY() -> "FluidState":
        return FluidState(kind=FluidKind.Empty, amount=0, falling=False)

    @staticmethod
    def WATER() -> "FluidState":
        return FluidState(kind=FluidKind.Water, amount=8, falling=False)

    # -- accessors ----------------------------------------------------------

    def kind_(self) -> FluidKind:
        return self.kind

    def amount_(self) -> int:
        return self.amount

    def falling_(self) -> bool:
        return self.falling

    def is_source(self) -> bool:
        """``FluidState::is_source`` (fluid.rs:160)."""
        return self.kind in (FluidKind.Water, FluidKind.Lava)

    def is_full(self) -> bool:
        """``FluidState::is_full`` (fluid.rs:163)."""
        return self.amount == 8

    # -- height -------------------------------------------------------------

    def own_height(self) -> float:
        """``FluidState::own_height`` (fluid.rs:194): ``f32::from(amount)/9.0``."""
        return _f32_div(float(self.amount), 9.0)

    def height_at(self, world: FluidHeightWorld, position) -> float:
        """``FluidState::height_at`` (fluid.rs:166)."""
        if self.kind == FluidKind.Empty:
            return 0.0
        x, y, z = position[0], position[1], position[2]
        above_state = world.fluid((x, _wrapping_add(y, 1), z))
        if self.kind.same_family(above_state.kind_()):
            return 1.0
        return self.own_height()

    def camera_height_at(self, world: FluidHeightWorld, position) -> float:
        """``FluidState::camera_height_at`` (fluid.rs:181)."""
        if self.is_source():
            x, y, z = position[0], position[1], position[2]
            above = (x, _wrapping_add(y, 1), z)
            if world.sturdy_down(above):
                return 1.0
        return self.height_at(world, position)

    # -- block <-> fluid conversion ----------------------------------------

    @staticmethod
    def from_block(state: BlockState) -> "FluidState":
        """``FluidState::from_block`` (fluid.rs:197)."""
        name = state.name
        water = name == "minecraft:water"
        if water or name == "minecraft:lava":
            raw = state.properties.get("level")
            level = None
            if raw is not None:
                try:
                    parsed = int(raw)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None and parsed <= 15:
                    level = parsed
            if level is None:
                raise ValueError("invalid liquid block level")
            if water and level == 0:
                kind = FluidKind.Water
            elif water:
                kind = FluidKind.FlowingWater
            elif level == 0:
                kind = FluidKind.Lava
            else:
                kind = FluidKind.FlowingLava
            amount = 8 if (level == 0 or level >= 8) else 8 - level
            return FluidState(kind=kind, amount=amount, falling=level >= 8)
        if name in (
            "minecraft:kelp",
            "minecraft:kelp_plant",
            "minecraft:seagrass",
            "minecraft:tall_seagrass",
            "minecraft:bubble_column",
        ):
            return FluidState.WATER()
        waterlogged = state.properties.get("waterlogged")
        if waterlogged == "true":
            # The pinned copper-grate blocks use falling source water.
            falling = name in (
                "minecraft:copper_grate",
                "minecraft:exposed_copper_grate",
                "minecraft:weathered_copper_grate",
                "minecraft:oxidized_copper_grate",
                "minecraft:waxed_copper_grate",
                "minecraft:waxed_exposed_copper_grate",
                "minecraft:waxed_weathered_copper_grate",
                "minecraft:waxed_oxidized_copper_grate",
            )
            return FluidState(kind=FluidKind.Water, amount=8, falling=falling)
        if waterlogged is None or waterlogged == "false":
            return FluidState.EMPTY()
        raise ValueError("invalid waterlogged block property")

    # -- JSON --------------------------------------------------------------

    @staticmethod
    def from_json(text: str) -> "FluidState":
        """``FluidState::from_json`` (fluid.rs:65)."""
        value = json.loads(text)
        if not isinstance(value, dict) or "id" not in value:
            raise ValueError("missing fluid identifier")
        name = value["id"]
        if not isinstance(name, str):
            raise ValueError("missing fluid identifier")
        if ":" in name:
            namespace, path = name.split(":", 1)
        else:
            namespace, path = "minecraft", name
        if namespace == "":
            namespace = "minecraft"
        canon = f"{namespace}:{path}"
        kind = FluidKind.from_name(canon)
        if kind is None:
            raise ValueError("unknown fluid identifier")
        if kind == FluidKind.Empty:
            return FluidState.EMPTY()
        flowing = kind in (FluidKind.FlowingWater, FluidKind.FlowingLava)
        state = FluidState(
            kind=kind,
            amount=1 if flowing else 8,
            falling=True,
        )
        props = value.get("properties")
        if isinstance(props, dict):
            falling = props.get("falling")
            if isinstance(falling, str):
                if falling == "true":
                    state = FluidState(kind=state.kind, amount=state.amount, falling=True)
                elif falling == "false":
                    state = FluidState(kind=state.kind, amount=state.amount, falling=False)
            if flowing:
                raw_level = props.get("level")
                if isinstance(raw_level, str):
                    parsed = java_integer(raw_level)
                    if parsed is not None and 1 <= parsed <= 8:
                        state = FluidState(
                            kind=state.kind,
                            amount=int(parsed),
                            falling=state.falling,
                        )
        return state

    def to_json(self) -> str:
        """``FluidState::to_json`` (fluid.rs:119)."""
        value = {"id": self.kind.fluid_name()}
        if self.kind != FluidKind.Empty:
            properties = {"falling": "true" if self.falling else "false"}
            if not self.is_source():
                properties["level"] = str(self.amount)
            value["properties"] = properties
        return json.dumps(value)


# ---------------------------------------------------------------------------
# FluidStateTable — fluid.rs:263
# ---------------------------------------------------------------------------

class FluidStateTable:
    """Per-registry-state :class:`FluidState`, indexed by ``BlockStateId``."""

    def __init__(self, states: List[FluidState]) -> None:
        self._states = states

    @classmethod
    def new(cls, registry: BlockRegistry) -> "FluidStateTable":
        """``FluidStateTable::new`` (fluid.rs:266)."""
        states: List[FluidState] = []
        for i in range(registry.len()):
            state = registry.state(BlockStateId(i))
            if state is None:
                raise ValueError("fluid table: state outside registry")
            states.append(FluidState.from_block(state))
        return cls(states)

    def get(self, state: BlockStateId) -> Optional[FluidState]:
        """``FluidStateTable::get`` (fluid.rs:272)."""
        index = state.id
        if 0 <= index < len(self._states):
            return self._states[index]
        return None


# ---------------------------------------------------------------------------
# FluidBlockBindings — fluid.rs:278
# ---------------------------------------------------------------------------

class FluidBlockBindings:
    """Bound identities converting fluid states into their legacy liquid blocks."""

    def __init__(
        self,
        air: BlockStateId,
        water: List[BlockStateId],
        lava: List[BlockStateId],
    ) -> None:
        self.air = air
        self.water = water
        self.lava = lava

    @classmethod
    def new(cls, registry: BlockRegistry) -> "FluidBlockBindings":
        """``FluidBlockBindings::new`` (fluid.rs:284)."""

        def levels(name: str) -> List[BlockStateId]:
            default = registry.default_state(name)
            if default is None:
                raise ValueError("missing liquid block")
            base = registry.state(default)
            if base is None:
                raise ValueError("missing liquid block")
            result: List[BlockStateId] = []
            for level in range(16):
                merged = dict(base.properties.properties)
                merged["level"] = str(level)
                candidate = BlockState(
                    name=base.name, properties=BlockProperties(merged)
                )
                found = registry.id(candidate)
                if found is None:
                    raise ValueError("missing liquid block level")
                result.append(found)
            return result

        air = registry.default_state("minecraft:air")
        if air is None:
            raise ValueError("missing air block")
        return cls(air=air, water=levels("minecraft:water"), lava=levels("minecraft:lava"))

    def block(self, state: FluidState) -> BlockStateId:
        """``FluidBlockBindings::block`` (fluid.rs:307)."""
        if state.kind == FluidKind.Empty:
            return self.air
        if state.is_source():
            level = 0
        else:
            level = 8 - min(state.amount, 8) + (8 if state.falling else 0)
        if state.kind.same_family(FluidKind.Water):
            return self.water[level]
        return self.lava[level]
