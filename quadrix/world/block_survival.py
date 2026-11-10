#!/usr/bin/env python3
"""[QuadRix] Правила выживания блоков и разрушение (`can_survive`).

Порт ``horizon/crates/horizon-world/src/block_survival.rs`` (Minecraft 26.3)
и вспомогательных данных, на которые он опирается:

  * ``block_properties.rs`` — флаги определений (``force_solid_on/off``,
    ``replaceable``, ``liquid``, ``can_occlude``) и ``calculate_solid``/
    ``calculate_solid_render``. Мини-реестр встроен сюда, потому что
    отдельного ``block_properties.py`` нет.
  * ``block_support.rs`` — ``SupportType`` (``Full``/``Center``/``Rigid``) и
    кэш опорных форм (``cached-support.nbt``, ``Kind = block_support``).
  * ``horizon-core`` ``shape/face.rs`` (``face_shape``/``calculate_face``) и
    ``shape/join.rs`` (``ShapeOp``) — из них выводится проверка опоры.

Харднесс/сопротивление/добыча берутся из подготовленных данных
(``gameplay-facts.json``, ``loot_table/blocks/*.json``) — это тот клиентский
API, который нужен разрушению блока; в самом ``block_survival.rs`` этих
величин нет.

Имена, поля и константы сохранены как в Rust. Пути ``.local`` фиксированы
AGENTS.md и переиспользуются один-в-один. Логи начинаются с ``[QuadRix]``.
"""

from __future__ import annotations

import json
import logging
import math
import random as _random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple, Union

from quadrix.core.geometry import Direction
from quadrix.items.items import ITEM_REGISTRY, ItemStack
from quadrix.world.block_placement import default_registry
from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    collision_shape,
    read_collision_nbt,
)
from quadrix.world.registry import BlockState, BlockStateId

__all__ = [
    "SupportType",
    "FluidKind",
    "FluidState",
    "SurvivalError",
    "SurvivalRule",
    "Rule",
    "SurvivalDefinitions",
    "BlockDefinitionProperties",
    "BoundBlockProperty",
    "BlockPropertiesRegistry",
    "BlockSupportRegistry",
    "BlockSurvivalRegistry",
    "SurvivalWorld",
    "default_survival",
    "can_survive",
    "block_hardness",
    "block_resistance",
    "requires_tool",
    "is_harvestable",
    "can_harvest",
    "get_drops",
    "break_block",
]

LOG = logging.getLogger("quadrix.block_survival")

# ---------------------------------------------------------------------------
# .local — пути как в AGENTS.md (не выдумываем новые)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BEHAVIOR_ROOT = _REPO_ROOT / ".local" / "horizon-client-block-behavior"
_RESOURCE_ROOT = _REPO_ROOT / ".local" / "horizon-client" / "26.3"
_MOTION_ROOT = _REPO_ROOT / ".local" / "horizon-client-motion"

# collision.rs — допуск сравнения координат (COLLISION_EPSILON).
COLLISION_EPSILON: float = 1.0e-7

# block_properties.rs:56 — порог «солидности» (calculate_solid).
SOLID_MIN_AVERAGE_SIZE: float = 0.7291666666666666
SOLID_MIN_HEIGHT: float = 1.0

# block_properties.rs — биты флагов определения.
FLAG_FORCE_SOLID_ON = 1
FLAG_FORCE_SOLID_OFF = 2
FLAG_REPLACEABLE = 4
FLAG_LIQUID = 8
FLAG_CAN_OCCLUDE = 16

AIR_NAMES = frozenset(
    {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
)

_FACE_AXIS: Dict[Direction, Tuple[int, bool]] = {
    Direction.DOWN: (1, False),
    Direction.UP: (1, True),
    Direction.NORTH: (2, False),
    Direction.SOUTH: (2, True),
    Direction.WEST: (0, False),
    Direction.EAST: (0, True),
}

_DIRECTION_NAMES: Dict[Direction, str] = {
    Direction.DOWN: "down",
    Direction.UP: "up",
    Direction.NORTH: "north",
    Direction.SOUTH: "south",
    Direction.WEST: "west",
    Direction.EAST: "east",
}


# ---------------------------------------------------------------------------
# Ошибки
# ---------------------------------------------------------------------------

class SurvivalError(Exception):
    """``SurvivalError``: мир/опора/столкновение/данные/неизвестное состояние."""


# ---------------------------------------------------------------------------
# SupportType (block_support.rs:5)
# ---------------------------------------------------------------------------

class SupportType(Enum):
    """block_support.rs:5 — вид проверки опорной грани."""

    FULL = "full"
    CENTER = "center"
    RIGID = "rigid"


# ---------------------------------------------------------------------------
# FluidKind / FluidState (fluid.rs:12)
# ---------------------------------------------------------------------------

class FluidKind(Enum):
    """fluid.rs:12 — вид жидкости (порядок = значение ``repr(u8)``)."""

    EMPTY = 0
    FLOWING_WATER = 1
    WATER = 2
    FLOWING_LAVA = 3
    LAVA = 4

    def name_(self) -> str:
        return {
            FluidKind.EMPTY: "minecraft:empty",
            FluidKind.FLOWING_WATER: "minecraft:flowing_water",
            FluidKind.WATER: "minecraft:water",
            FluidKind.FLOWING_LAVA: "minecraft:flowing_lava",
            FluidKind.LAVA: "minecraft:lava",
        }[self]

    @staticmethod
    def from_name(name: str) -> Optional["FluidKind"]:
        for kind in FluidKind:
            if kind.name_() == name:
                return kind
        return None

    def mask(self) -> int:
        """fluid.rs:53 — ``1 << self as u8``."""
        return 1 << self.value


@dataclass(frozen=True)
class FluidState:
    """fluid.rs:58 — состояние жидкости (kind/amount/falling)."""

    kind: FluidKind = FluidKind.EMPTY
    amount: int = 0
    falling: bool = False

    def is_full(self) -> bool:
        """fluid.rs:163 — ``amount == 8``."""
        return self.amount == 8

    @staticmethod
    def empty() -> "FluidState":
        return _FLUID_EMPTY

    @staticmethod
    def coerce(value: Union["FluidState", str, "FluidKind", None]) -> "FluidState":
        """Приводит значение мира к ``FluidState`` (None → пусто)."""
        if value is None:
            return _FLUID_EMPTY
        if isinstance(value, FluidState):
            return value
        if isinstance(value, FluidKind):
            amount = 0 if value is FluidKind.EMPTY else 8
            return FluidState(value, amount, False)
        if isinstance(value, str):
            kind = FluidKind.from_name(value)
            if kind is None:
                raise SurvivalError(f"unknown fluid identifier {value!r}")
            amount = 0 if kind is FluidKind.EMPTY else 8
            return FluidState(kind, amount, False)
        # Объект с полями kind/amount: принимаем как есть.
        kind = getattr(value, "kind", None)
        if isinstance(kind, str):
            kind = FluidKind.from_name(kind)
        if isinstance(kind, FluidKind):
            return FluidState(kind, int(getattr(value, "amount", 0) or 0), bool(getattr(value, "falling", False)))
        raise SurvivalError(f"unsupported fluid value {value!r}")


_FLUID_EMPTY = FluidState(FluidKind.EMPTY, 0, False)


# ---------------------------------------------------------------------------
# SurvivalRule / Rule (block_survival.rs:18, :78)
# ---------------------------------------------------------------------------

class SurvivalRule(Enum):
    """block_survival.rs:18 — вариант правила из ``survival-rules.json``."""

    FIRE = "Fire"
    CACTUS = "Cactus"
    PATH = "Path"
    MUSHROOM = "Mushroom"
    MULTIFACE = "Multiface"
    VINE = "Vine"
    HANGING_MOSS = "HangingMoss"
    SNOW_LAYER = "SnowLayer"
    SEA_PICKLE = "SeaPickle"
    BELL = "Bell"
    GROWING_PLANT = "GrowingPlant"
    MANGROVE_PROPAGULE = "MangrovePropagule"
    SPELEOTHEM = "Speleothem"
    SCAFFOLDING = "Scaffolding"
    PISTON_HEAD = "PistonHead"
    CHORUS_PLANT = "ChorusPlant"
    CHORUS_FLOWER = "ChorusFlower"
    PITCHER_CROP = "PitcherCrop"
    SUGAR_CANE = "SugarCane"
    LILY_PAD = "LilyPad"
    FROGSPAWN = "Frogspawn"
    SPORE_BLOSSOM = "SporeBlossom"
    SMALL_DRIPLEAF = "SmallDripleaf"
    TALL_SEAGRASS = "TallSeagrass"
    BIG_DRIPLEAF = "BigDripleaf"
    BIG_DRIPLEAF_STEM = "BigDripleafStem"
    FARMLAND = "Farmland"
    COCOA = "Cocoa"
    CROP = "Crop"
    DOUBLE_PLANT = "DoublePlant"
    DOOR = "Door"
    CACTUS_FLOWER = "CactusFlower"
    SEAGRASS = "Seagrass"
    BUBBLE_COLUMN = "BubbleColumn"
    REDSTONE_WIRE = "RedstoneWire"
    ALWAYS = "Always"
    SOLID_BELOW = "SolidBelow"
    SOLID_BEHIND = "SolidBehind"
    NON_AIR_BELOW = "NonAirBelow"
    MOSS_CARPET = "MossCarpet"
    CENTER_BELOW = "CenterBelow"
    LANTERN = "Lantern"
    FULL_ABOVE = "FullAbove"
    FULL_BEHIND = "FullBehind"
    RIGID_OR_CENTER_BELOW = "RigidOrCenterBelow"
    RIGID_BELOW = "RigidBelow"
    FULL_BELOW = "FullBelow"
    CENTER_ABOVE = "CenterAbove"
    FACE_ATTACHED = "FaceAttached"
    SUPPORTS_BAMBOO = "SupportsBamboo"


@dataclass(frozen=True)
class Rule:
    """block_survival.rs:78 — разобранное по состоянию правило (payload)."""

    name: str
    faces: int = 0
    face: Optional[Direction] = None
    kind: Optional[SupportType] = None
    center_restriction: bool = False
    head: Optional[BlockStateId] = None
    body: Optional[BlockStateId] = None
    direction: Optional[Direction] = None
    flag: bool = False
    tag_index: int = -1


@dataclass
class SurvivalDefinitions:
    """block_survival.rs:73 — входные данные версии."""

    rules: Dict[str, SurvivalRule] = field(default_factory=dict)
    ignition_odds: Dict[str, int] = field(default_factory=dict)
    fence_gates: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# block_properties.rs — встроенный мини-реестр
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlockDefinitionProperties:
    """block_properties.rs:18 — флаги определения блока."""

    force_solid_on: bool
    force_solid_off: bool
    replaceable: bool
    liquid: bool
    can_occlude: bool

    def calculate_solid(self, cached_shape) -> bool:
        """block_properties.rs:46 — солидность по кэшу формы."""
        if self.force_solid_on:
            return True
        if self.force_solid_off:
            return False
        if cached_shape is None or cached_shape.is_empty():
            return False
        dx = cached_shape.max(0) - cached_shape.min(0)
        dy = cached_shape.max(1) - cached_shape.min(1)
        dz = cached_shape.max(2) - cached_shape.min(2)
        average = (dx + dy + dz) / 3.0
        return average >= SOLID_MIN_AVERAGE_SIZE or dy >= SOLID_MIN_HEIGHT

    def calculate_solid_render(self, occlusion) -> bool:
        """block_properties.rs:40 — полный куб скрытия."""
        return self.can_occlude and occlusion is not None and occlusion.is_block()


class BoundBlockProperty:
    """block_properties.rs:80 — привязка флага к состояниям."""

    def __init__(self, states: Sequence[bool]) -> None:
        self.states = tuple(bool(v) for v in states)

    def contains(self, state: Union[BlockStateId, int]) -> bool:
        idx = state.id if isinstance(state, BlockStateId) else int(state)
        if 0 <= idx < len(self.states):
            return self.states[idx]
        return False


class BlockPropertiesRegistry:
    """block_properties.rs:109 — флаги состояний из ``block-properties.nbt``."""

    def __init__(self, registry, definitions, solid, liquid, solid_render) -> None:
        self.registry = registry
        self.definitions = definitions
        self._solid = solid
        self._liquid = liquid
        self._solid_render = solid_render

    @classmethod
    def load(cls, registry, collision: CachedCollisionRegistry, path: Optional[Path] = None) -> "BlockPropertiesRegistry":
        file_path = Path(path) if path is not None else _BEHAVIOR_ROOT / "block-properties.nbt"
        raw = file_path.read_bytes()
        tag = read_collision_nbt(raw)
        blocks_tag = tag.get("blocks")
        if blocks_tag is None or not blocks_tag.is_compound:
            raise SurvivalError("[QuadRix] block-properties.nbt: missing blocks")
        occlusion_tag = tag.get("occlusion")
        if occlusion_tag is None:
            raise SurvivalError("[QuadRix] block-properties.nbt: missing occlusion")
        occlusion = CachedCollisionRegistry.from_table(
            occlusion_tag, registry, verify_states=False
        )
        definitions: Dict[str, BlockDefinitionProperties] = {}
        for name, flags_tag in blocks_tag.compound_val.items():
            flags = int(flags_tag.byte_val)
            definitions[str(name)] = BlockDefinitionProperties(
                force_solid_on=bool(flags & FLAG_FORCE_SOLID_ON),
                force_solid_off=bool(flags & FLAG_FORCE_SOLID_OFF),
                replaceable=bool(flags & FLAG_REPLACEABLE),
                liquid=bool(flags & FLAG_LIQUID),
                can_occlude=bool(flags & FLAG_CAN_OCCLUDE),
            )
        solid: List[bool] = []
        liquid: List[bool] = []
        solid_render: List[bool] = []
        for idx in range(registry.len()):
            state = registry.states[idx]
            props = definitions.get(state.name)
            if props is None:
                raise SurvivalError(
                    f"[QuadRix] missing block definition properties for {state.name}"
                )
            cached = collision.cached_shape(BlockStateId(idx))
            occ = occlusion.cached_shape(BlockStateId(idx))
            solid.append(props.calculate_solid(cached))
            liquid.append(props.liquid)
            solid_render.append(props.calculate_solid_render(occ))
        return cls(registry, definitions, solid, liquid, solid_render)

    def bind_solid(self) -> BoundBlockProperty:
        return BoundBlockProperty(self._solid)

    def bind_liquid(self) -> BoundBlockProperty:
        return BoundBlockProperty(self._liquid)

    def bind_solid_render(self) -> BoundBlockProperty:
        return BoundBlockProperty(self._solid_render)

    def definition(self, name: str) -> Optional[BlockDefinitionProperties]:
        return self.definitions.get(name)


# ---------------------------------------------------------------------------
# Formа: find_index / face / покрытие (horizon-core shape/face.rs)
# ---------------------------------------------------------------------------

def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _cube_like_along(shape, axis: int) -> bool:
    coords = shape.coords[axis]
    return (
        len(coords) == 2
        and abs(coords[0]) <= COLLISION_EPSILON
        and abs(coords[1] - 1.0) <= COLLISION_EPSILON
    )


def _find_index(shape, axis: int, value: float) -> int:
    """shape.rs:374 — ``find_index`` (включая внешний индекс за последней гранью)."""
    size = shape.sizes[axis]
    if shape.cube:
        return int(math.floor(max(-1.0, min(value * size, float(size)))))
    coords = shape.coords[axis]
    start = 0
    end = len(coords)
    while start < end:
        middle = (start + end) // 2
        if value < coords[middle]:
            end = middle
        else:
            start = middle + 1
    return start - 1


def _is_full(shape, x: int, y: int, z: int) -> bool:
    nx, ny, nz = shape.sizes
    if x < 0 or y < 0 or z < 0 or x >= nx or y >= ny or z >= nz:
        return False
    return shape.occupancy[(x * ny + y) * nz + z]


def _face_rects(shape, direction: Direction) -> List[Tuple[float, float, float, float]]:
    """Плоские прямоугольники грани (проекция ``face_shape`` на две оси)."""
    if shape is None or shape.is_empty():
        return []
    axis, positive = _FACE_AXIS[direction]
    others = [a for a in (0, 1, 2) if a != axis]
    o0, o1 = others
    coords = shape.coords
    if _cube_like_along(shape, axis):
        rects: List[Tuple[float, float, float, float]] = []
        for box in shape.boxes_list():
            lo = (box.min.x, box.min.y, box.min.z)
            hi = (box.max.x, box.max.y, box.max.z)
            rects.append((lo[o0], hi[o0], lo[o1], hi[o1]))
        return rects
    value = 0.9999999 if positive else COLLISION_EPSILON
    index = _find_index(shape, axis, value)
    starts = [0, 0, 0]
    ends = [shape.sizes[0], shape.sizes[1], shape.sizes[2]]
    starts[axis] = index
    ends[axis] = index + 1
    minimum = [
        _clamp_int(shape.discrete_min[i], starts[i], ends[i]) - starts[i]
        for i in range(3)
    ]
    maximum = [
        _clamp_int(shape.discrete_max[i], starts[i], ends[i]) - starts[i]
        for i in range(3)
    ]
    if any(minimum[i] >= maximum[i] for i in range(3)):
        return []
    rects = []
    for i in range(shape.sizes[o0]):
        for j in range(shape.sizes[o1]):
            p = [0, 0, 0]
            p[o0] = i
            p[o1] = j
            p[axis] = index
            if _is_full(shape, p[0], p[1], p[2]):
                rects.append(
                    (coords[o0][i], coords[o0][i + 1], coords[o1][j], coords[o1][j + 1])
                )
    return rects


def _contains(rect: Tuple[float, float, float, float], x: float, y: float) -> bool:
    x0, x1, y0, y1 = rect
    return x0 - COLLISION_EPSILON <= x <= x1 + COLLISION_EPSILON and y0 - COLLISION_EPSILON <= y <= y1 + COLLISION_EPSILON


def _rects_cover(
    face_rects: Sequence[Tuple[float, float, float, float]],
    required: Sequence[Tuple[float, float, float, float]],
) -> bool:
    """Покрывают ли ``face_rects`` все точки объединения ``required``."""
    if not required:
        return True
    xs: Set[float] = set()
    ys: Set[float] = set()
    for r in list(face_rects) + list(required):
        xs.add(r[0])
        xs.add(r[1])
        ys.add(r[2])
        ys.add(r[3])
    xs_sorted = sorted(xs)
    ys_sorted = sorted(ys)
    for i in range(len(xs_sorted) - 1):
        cx = (xs_sorted[i] + xs_sorted[i + 1]) / 2.0
        for j in range(len(ys_sorted) - 1):
            cy = (ys_sorted[j] + ys_sorted[j + 1]) / 2.0
            if not any(_contains(r, cx, cy) for r in required):
                continue
            if not any(_contains(r, cx, cy) for r in face_rects):
                return False
    return True


# Центральная опора (block_support.rs:28) — коробка 0.4375..0.5625 × 0..0.625 × 0.4375..0.5625.
_CENTER_MIN = (0.4375, 0.0, 0.4375)
_CENTER_MAX = (0.5625, 0.625, 0.5625)


def _support_required(direction: Direction, kind: SupportType):
    """Проекция ``required`` shape на две не-гранные оси (FULL/RIGID — весь квадрат)."""
    axis, _ = _FACE_AXIS[direction]
    others = [a for a in (0, 1, 2) if a != axis]
    o0, o1 = others
    if kind in (SupportType.FULL, SupportType.RIGID):
        return [(0.0, 1.0, 0.0, 1.0)]
    if kind is SupportType.CENTER:
        return [(_CENTER_MIN[o0], _CENTER_MAX[o0], _CENTER_MIN[o1], _CENTER_MAX[o1])]
    raise SurvivalError(f"unknown support type {kind!r}")


def _is_supporting(shape, direction: Direction, kind: SupportType) -> bool:
    """block_support.rs:12 — ``SupportType::is_supporting`` над формой грани."""
    return _rects_cover(_face_rects(shape, direction), _support_required(direction, kind))


# ---------------------------------------------------------------------------
# Блок-теги (worldgen/tags.rs + .local/horizon-client-motion/tags.json)
# ---------------------------------------------------------------------------

def _canonical(name: str) -> str:
    if ":" not in name:
        return "minecraft:" + name
    namespace, path = name.split(":", 1)
    if namespace == "":
        namespace = "minecraft"
    return f"{namespace}:{path}"


class BlockTagResolver:
    """Разрешает теги блоков из ``tags.json`` (значения — JSON-строки с ``#``)."""

    def __init__(self, raw: Dict[str, str]) -> None:
        self.raw = raw
        self._cache: Dict[str, Set[str]] = {}
        self._resolving: Set[str] = set()

    def resolve(self, name: str) -> Set[str]:
        name = _canonical(name)
        if name in self._cache:
            return self._cache[name]
        if name in self._resolving:
            return set()
        self._resolving.add(name)
        out: Set[str] = set()
        text = self.raw.get(name)
        if text is not None:
            data = None
            if isinstance(text, str):
                try:
                    data = json.loads(text)
                except ValueError:
                    data = None
            else:
                data = text
            if isinstance(data, dict):
                for entry in data.get("values", []):
                    if isinstance(entry, str):
                        eid = entry
                    elif isinstance(entry, dict):
                        eid = entry.get("id")
                    else:
                        continue
                    if not isinstance(eid, str):
                        continue
                    if eid.startswith("#"):
                        out |= self.resolve(eid[1:])
                    else:
                        out.add(_canonical(eid))
        self._resolving.discard(name)
        self._cache[name] = out
        return out


# ---------------------------------------------------------------------------
# Реестр опор (block_support.rs:72)
# ---------------------------------------------------------------------------

class BlockSupportRegistry:
    """block_support.rs:155 — кэш опорных форм (``cached-support.nbt``)."""

    def __init__(self, registry, shapes: CachedCollisionRegistry, collision: CachedCollisionRegistry) -> None:
        self.registry = registry
        self._shapes = shapes
        self._collision = collision
        self._cache: Dict[Tuple[int, int, int], bool] = {}

    @classmethod
    def from_table(cls, table, registry, collision: CachedCollisionRegistry) -> "BlockSupportRegistry":
        kind = table.get("Kind") if isinstance(table, dict) else None
        if kind is not None and kind.is_string and kind.str_val != "block_support":
            raise SurvivalError("[QuadRix] wrong cached support data kind")
        shapes = CachedCollisionRegistry.from_table(table, registry, verify_states=False)
        return cls(registry, shapes, collision)

    @classmethod
    def load(cls, registry, collision: CachedCollisionRegistry, path: Optional[Path] = None) -> "BlockSupportRegistry":
        file_path = Path(path) if path is not None else _BEHAVIOR_ROOT / "cached-support.nbt"
        raw = file_path.read_bytes()
        return cls.from_table(read_collision_nbt(raw), registry, collision)

    def cached_state_count(self) -> int:
        return self._shapes.cached_state_count()

    def is_face_sturdy(
        self,
        state: Union[BlockStateId, int],
        direction: Direction,
        support: SupportType,
    ) -> Optional[bool]:
        """block_support.rs:131 — ``Some(bool)`` для кэша, ``None`` — нет формы."""
        sid = state.id if isinstance(state, BlockStateId) else int(state)
        key = (sid, direction.value, support.value)  # type: ignore[attr-defined]
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        shape = self._shapes.cached_shape(sid)
        if shape is None:
            # FALLBACK: динамические опоры не портированы — берём форму столкновения.
            shape = self._collision.cached_shape(sid)
        if shape is None:
            return None
        result = _is_supporting(shape, direction, support)
        self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Мир (block_survival.rs:135 SurvivalWorld)
# ---------------------------------------------------------------------------

class SurvivalWorld(Protocol):
    """block_survival.rs:135 — мир, который читает правила выживания."""

    def get_block(self, position: Tuple[int, int, int]):
        ...

    def fluid_state(self, position: Tuple[int, int, int]):
        ...

    def raw_brightness(self, position: Tuple[int, int, int], sky_darken: int) -> int:
        ...


class _PermanentProperty:
    """Простой контейнер множества (для ``BoundBlockProperty``-совместимости)."""

    def __init__(self, values: Set[int]) -> None:
        self.values = frozenset(values)

    def contains(self, state: Union[BlockStateId, int]) -> bool:
        idx = state.id if isinstance(state, BlockStateId) else int(state)
        return idx in self.values


# ---------------------------------------------------------------------------
# BlockSurvivalRegistry (block_survival.rs:160)
# ---------------------------------------------------------------------------

class BlockSurvivalRegistry:
    """block_survival.rs:160 — правила выживания, разобранные по состояниям."""

    def __init__(
        self,
        registry,
        properties: BlockPropertiesRegistry,
        support: BlockSupportRegistry,
        collision: CachedCollisionRegistry,
        rules: List[Optional[Rule]],
        *,
        solid: BoundBlockProperty,
        liquid: BoundBlockProperty,
        solid_render: BoundBlockProperty,
        flammable: Set[int],
        fence_gates: Set[int],
        cactus_support: Set[int],
        mushroom_light_override: Set[int],
        unstable_bottom_center: Set[int],
        supports_bamboo: Set[int],
        bound_tags: List[Set[int]],
        cactus_flower: Set[int],
        no_seagrass: Set[int],
        vegetation: Set[int],
        dripleaf: Set[int],
        maintains_farmland: Set[int],
        cocoa: Set[int],
        crops: Set[int],
        no_snow: Set[int],
        snow_override: Set[int],
        mangrove: Set[int],
        hanging_mangrove: Set[int],
        no_kelp: Set[int],
        chorus_plant: Set[int],
        chorus_flower: Set[int],
        lily_pad: Set[int],
        frogspawn: Set[int],
        small_dripleaf: Set[int],
        sugar_cane: Set[int],
        sugar_cane_adjacent: Set[int],
        fluid_tags: List[int],
        bubble_up: Set[int],
        bubble_down: Set[int],
    ) -> None:
        self.registry = registry
        self.properties = properties
        self.support = support
        self.collision = collision
        self.rules = rules
        self.solid = solid
        self.liquid = liquid
        self.solid_render = solid_render
        self.flammable = flammable
        self.fence_gates = fence_gates
        self.cactus_support = cactus_support
        self.mushroom_light_override = mushroom_light_override
        self.unstable_bottom_center = unstable_bottom_center
        self.supports_bamboo = supports_bamboo
        self.bound_tags = bound_tags
        self.cactus_flower = cactus_flower
        self.no_seagrass = no_seagrass
        self.vegetation = vegetation
        self.dripleaf = dripleaf
        self.maintains_farmland = maintains_farmland
        self.cocoa = cocoa
        self.crops = crops
        self.no_snow = no_snow
        self.snow_override = snow_override
        self.mangrove = mangrove
        self.hanging_mangrove = hanging_mangrove
        self.no_kelp = no_kelp
        self.chorus_plant = chorus_plant
        self.chorus_flower = chorus_flower
        self.lily_pad = lily_pad
        self.frogspawn = frogspawn
        self.small_dripleaf = small_dripleaf
        self.sugar_cane = sugar_cane
        self.sugar_cane_adjacent = sugar_cane_adjacent
        self.fluid_tags = fluid_tags
        self.bubble_up = bubble_up
        self.bubble_down = bubble_down
        self.tag_resolver: Optional[BlockTagResolver] = None

    # -- загрузка (block_survival.rs:198) --

    @classmethod
    def load(
        cls,
        registry=None,
        *,
        behavior_root: Optional[Path] = None,
        motion_root: Optional[Path] = None,
    ) -> "BlockSurvivalRegistry":
        if registry is None:
            registry = default_registry()
        base = Path(behavior_root) if behavior_root is not None else _BEHAVIOR_ROOT
        motion = Path(motion_root) if motion_root is not None else _MOTION_ROOT

        collision = CachedCollisionRegistry.from_table(
            read_collision_nbt((base / "cached-collision.nbt").read_bytes()),
            registry,
            verify_states=False,
        )
        properties = BlockPropertiesRegistry.load(registry, collision, base / "block-properties.nbt")
        support = BlockSupportRegistry.load(registry, collision, base / "cached-support.nbt")

        rules_raw = json.loads((base / "survival-rules.json").read_text())
        extra = json.loads((base / "survival-extra-definitions.json").read_text())
        definitions = SurvivalDefinitions(
            rules={},
            ignition_odds={str(k): int(v) for k, v in extra.get("ignition_odds", {}).items()},
            fence_gates={str(v) for v in extra.get("fence_gates", [])},
        )

        tags_raw = json.loads((motion / "tags.json").read_text())
        resolver = BlockTagResolver(tags_raw)

        # имя -> список id (для привязки тегов).
        name_ids: Dict[str, List[int]] = {}
        for idx in range(registry.len()):
            name_ids.setdefault(registry.states[idx].name, []).append(idx)

        def tag_states(name: str) -> Set[int]:
            out: Set[int] = set()
            for member in resolver.resolve(name):
                out.update(name_ids.get(member, ()))
            return out

        bound_tag_names: List[str] = []
        bound_tag_indices: Dict[str, int] = {}

        rules: List[Optional[Rule]] = [None] * registry.len()
        for idx in range(registry.len()):
            state = registry.states[idx]
            text = rules_raw.get(state.name)
            if text is None:
                continue
            rules[idx] = _bind_rule(
                registry, state, text, bound_tag_names, bound_tag_indices
            )

        bound_tags = [tag_states(name) for name in bound_tag_names]

        fluid_tag_defs: Dict[str, Set[str]] = {}
        for tag_name in (
            "water",
            "supports_lily_pad",
            "supports_frogspawn",
            "supports_sugar_cane_adjacently",
            "lava",
        ):
            path = _RESOURCE_ROOT / "data" / "minecraft" / "tags" / "fluid" / f"{tag_name}.json"
            data = json.loads(path.read_text())
            names: Set[str] = set()

            def collect(entries) -> None:
                for entry in entries:
                    if isinstance(entry, str):
                        eid = entry
                    elif isinstance(entry, dict):
                        eid = entry.get("id")
                    else:
                        continue
                    if not isinstance(eid, str):
                        continue
                    if eid.startswith("#"):
                        ref = eid[1:]
                        ref_path = _RESOURCE_ROOT / "data" / "minecraft" / "tags" / "fluid" / f"{ref.split(':')[-1]}.json"
                        if ref_path.exists():
                            ref_data = json.loads(ref_path.read_text())
                            collect(ref_data.get("values", []))
                    else:
                        names.add(_canonical(eid))

            collect(data.get("values", []))
            fluid_tag_defs[tag_name] = names

        def fluid_mask(tag_name: str) -> int:
            mask = 0
            for name in fluid_tag_defs.get(tag_name, ()):
                kind = FluidKind.from_name(name)
                if kind is None:
                    raise SurvivalError(f"[QuadRix] unknown fluid tag member {name}")
                mask |= kind.mask()
            return mask

        # Специальные множества тегов.
        flammable = {
            idx
            for idx in range(registry.len())
            if definitions.ignition_odds.get(registry.states[idx].name, 0) > 0
            and registry.states[idx].properties.get("waterlogged") != "true"
        }
        fence_gates = {
            idx
            for idx in range(registry.len())
            if registry.states[idx].name in definitions.fence_gates
        }

        result = cls(
            registry,
            properties,
            support,
            collision,
            rules,
            solid=properties.bind_solid(),
            liquid=properties.bind_liquid(),
            solid_render=properties.bind_solid_render(),
            flammable=flammable,
            fence_gates=fence_gates,
            cactus_support=tag_states("minecraft:supports_cactus"),
            mushroom_light_override=tag_states("minecraft:overrides_mushroom_light_requirement"),
            unstable_bottom_center=tag_states("minecraft:unstable_bottom_center"),
            supports_bamboo=tag_states("minecraft:supports_bamboo"),
            bound_tags=bound_tags,
            cactus_flower=tag_states("minecraft:support_override_cactus_flower"),
            no_seagrass=tag_states("minecraft:cannot_support_seagrass"),
            vegetation=tag_states("minecraft:supports_vegetation"),
            dripleaf=tag_states("minecraft:supports_big_dripleaf"),
            maintains_farmland=tag_states("minecraft:maintains_farmland"),
            cocoa=tag_states("minecraft:supports_cocoa"),
            crops=tag_states("minecraft:supports_crops"),
            no_snow=tag_states("minecraft:cannot_support_snow_layer"),
            snow_override=tag_states("minecraft:support_override_snow_layer"),
            mangrove=tag_states("minecraft:supports_mangrove_propagule"),
            hanging_mangrove=tag_states("minecraft:supports_hanging_mangrove_propagule"),
            no_kelp=tag_states("minecraft:cannot_support_kelp"),
            chorus_plant=tag_states("minecraft:supports_chorus_plant"),
            chorus_flower=tag_states("minecraft:supports_chorus_flower"),
            lily_pad=tag_states("minecraft:supports_lily_pad"),
            frogspawn=tag_states("minecraft:supports_frogspawn"),
            small_dripleaf=tag_states("minecraft:supports_small_dripleaf"),
            sugar_cane=tag_states("minecraft:supports_sugar_cane"),
            sugar_cane_adjacent=tag_states("minecraft:supports_sugar_cane_adjacently"),
            fluid_tags=[
                fluid_mask("water"),
                fluid_mask("supports_lily_pad"),
                fluid_mask("supports_frogspawn"),
                fluid_mask("supports_sugar_cane_adjacently"),
                fluid_mask("lava"),
            ],
            bubble_up=tag_states("minecraft:enables_bubble_column_push_up"),
            bubble_down=tag_states("minecraft:enables_bubble_column_drag_down"),
        )
        result.tag_resolver = resolver
        return result

    # -- запросы --

    def is_air(self, state: Union[BlockStateId, int]) -> bool:
        sid = state.id if isinstance(state, BlockStateId) else int(state)
        found = self.registry.state(BlockStateId(sid))
        return found is not None and found.name in AIR_NAMES

    def face_property(self, state: Union[BlockStateId, int], direction: Direction) -> bool:
        sid = state.id if isinstance(state, BlockStateId) else int(state)
        found = self.registry.state(BlockStateId(sid))
        if found is None:
            return False
        return found.properties.get(_DIRECTION_NAMES[direction]) == "true"

    def _name(self, state: Union[BlockStateId, int]) -> str:
        sid = state.id if isinstance(state, BlockStateId) else int(state)
        found = self.registry.state(BlockStateId(sid))
        if found is None:
            raise SurvivalError(f"[QuadRix] block state outside registry: {sid}")
        return found.name

    def _same_block(self, first: Union[BlockStateId, int], second: Union[BlockStateId, int]) -> bool:
        return self._name(first) == self._name(second)

    def _read(self, world: SurvivalWorld, position: Tuple[int, int, int]) -> BlockStateId:
        value = world.get_block(position)
        sid = _as_state_id(self.registry, value)
        return sid

    def _fluid(self, world: SurvivalWorld, position: Tuple[int, int, int]) -> FluidState:
        getter = getattr(world, "fluid_state", None)
        if getter is None:
            return _FLUID_EMPTY
        return FluidState.coerce(getter(position))

    def _brightness(self, world: SurvivalWorld, position: Tuple[int, int, int], sky_darken: int) -> int:
        getter = getattr(world, "raw_brightness", None)
        if getter is None:
            return 0
        return int(getter(position, sky_darken))

    def _fluid_matches(self, tag: int, fluid: FluidState) -> bool:
        return (self.fluid_tags[tag] & fluid.kind.mask()) != 0

    def _support(
        self,
        world: SurvivalWorld,
        position: Tuple[int, int, int],
        face: Direction,
        kind: SupportType,
        center_restriction: bool,
    ) -> bool:
        state = self._read(world, position)
        if center_restriction and face is Direction.DOWN and state.id in self.unstable_bottom_center:
            return False
        result = self.support.is_face_sturdy(state, face, kind)
        return bool(result)

    def _can_attach(
        self,
        world: SurvivalWorld,
        neighbor: BlockStateId,
        at: Tuple[int, int, int],
        direction: Direction,
    ) -> bool:
        face = direction.opposite()
        result = self.support.is_face_sturdy(neighbor, face, SupportType.FULL)
        if result:
            return True
        shape = collision_shape(self.registry, neighbor, self.collision)
        return _is_supporting(shape, face, SupportType.FULL)

    def can_attach_to(
        self,
        world: SurvivalWorld,
        position: Tuple[int, int, int],
        direction: Direction,
    ) -> bool:
        """block_survival.rs:575 — ``can_attach_to``."""
        at = _relative(position, direction)
        neighbor = self._read(world, at)
        return self._can_attach(world, neighbor, at, direction)

    def _scaffold_distance(self, state: BlockStateId) -> Optional[int]:
        if self._name(state) != "minecraft:scaffolding":
            return None
        found = self.registry.state(state)
        if found is None:
            return None
        raw = found.properties.get("distance")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise SurvivalError("[QuadRix] invalid scaffolding distance") from None
        if 0 <= value <= 7:
            return value
        raise SurvivalError("[QuadRix] invalid scaffolding distance")

    def _is_lower_half(self, below: BlockStateId, candidate: BlockStateId) -> bool:
        below_state = self.registry.state(below)
        candidate_state = self.registry.state(candidate)
        if below_state is None or candidate_state is None:
            return False
        return (
            below_state.name == candidate_state.name
            and below_state.properties.get("half") == "lower"
        )

    # -- can_survive (block_survival.rs:640) --

    def can_survive(
        self,
        world: SurvivalWorld,
        state: Union[BlockStateId, int, BlockState, str],
        position: Sequence[int],
    ) -> bool:
        sid = _as_state_id(self.registry, state)
        if sid.id < 0 or sid.id >= len(self.rules):
            raise SurvivalError(f"[QuadRix] survival candidate outside registry {sid.id}")
        rule = self.rules[sid.id]
        if rule is None:
            raise SurvivalError(f"[QuadRix] unsupported block survival state {sid.id}")
        pos = (int(position[0]), int(position[1]), int(position[2]))
        return self._dispatch(world, rule, sid, pos)

    def _dispatch(self, world: SurvivalWorld, rule: Rule, state: BlockStateId, position: Tuple[int, int, int]) -> bool:
        registry = self.registry
        name = rule.name

        if name == "Always":
            return True

        if name == "Fire":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            if self._support(world, below, Direction.UP, SupportType.FULL, False):
                return True
            for direction in Direction.ALL:
                if self._read(world, _relative(position, direction)).id in self.flammable:
                    return True
            return False

        if name == "Cactus":
            for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
                at = _relative(position, direction)
                neighbor = self._read(world, at)
                if self.solid.contains(neighbor) or self._fluid_matches(4, self._fluid(world, at)):
                    return False
            neighbor = self._read(world, _relative(position, Direction.DOWN))
            if not self._same_block(neighbor, state) and neighbor.id not in self.cactus_support:
                return False
            above = self._read(world, _relative(position, Direction.UP))
            return not self.liquid.contains(above)

        if name == "Path":
            above = self._read(world, _relative(position, Direction.UP))
            return (not self.solid.contains(above)) or above.id in self.fence_gates

        if name == "Mushroom":
            below = self._read(world, _relative(position, Direction.DOWN))
            if below.id in self.mushroom_light_override:
                return True
            return (
                self._brightness(world, position, 0) < 13
                and self.solid_render.contains(below)
            )

        if name == "Multiface":
            for direction in Direction.ALL:
                if rule.faces & (1 << direction.value):
                    at = _relative(position, direction)
                    neighbor = self._read(world, at)
                    if not self._can_attach(world, neighbor, at, direction):
                        return False
            return rule.faces != 0

        if name == "HangingMoss":
            at = _relative(position, Direction.UP)
            neighbor = self._read(world, at)
            return self._can_attach(world, neighbor, at, Direction.UP) or self._same_block(neighbor, state)

        if name == "Vine":
            above = _relative(position, Direction.UP)
            any_face = False
            cached_above: Optional[BlockStateId] = None
            if rule.faces & (1 << Direction.UP.value):
                neighbor = self._read(world, above)
                any_face = self._can_attach(world, neighbor, above, Direction.DOWN)
            for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
                if not (rule.faces & (1 << direction.value)):
                    continue
                at = _relative(position, direction)
                neighbor = self._read(world, at)
                valid = self._can_attach(world, neighbor, at, direction)
                if not valid:
                    neighbor = self._read(world, above)
                    valid = self._same_block(neighbor, state) and self.face_property(neighbor, direction)
                if not valid:
                    if cached_above is None:
                        cached_above = self._read(world, above)
                    neighbor = cached_above
                    valid = self._same_block(neighbor, state) and self.face_property(neighbor, direction)
                any_face = any_face or valid
            return any_face

        if name == "SnowLayer":
            at = _relative(position, Direction.DOWN)
            neighbor = self._read(world, at)
            if neighbor.id in self.no_snow:
                return False
            if neighbor.id in self.snow_override:
                return True
            shape = collision_shape(self.registry, neighbor, self.collision)
            if _is_supporting(shape, Direction.UP, SupportType.FULL):
                return True
            found = self.registry.state(neighbor)
            return (
                self._same_block(neighbor, state)
                and found is not None
                and found.properties.get("layers") == "8"
            )

        if name == "SeaPickle":
            at = _relative(position, Direction.DOWN)
            neighbor = self._read(world, at)
            shape = collision_shape(self.registry, neighbor, self.collision)
            if not _face_shape_empty(shape, Direction.UP):
                return True
            return self._support(world, at, Direction.UP, SupportType.FULL, False)

        if name == "GrowingPlant":
            at = _relative(position, rule.direction.opposite())
            neighbor = self._read(world, at)
            if rule.flag and neighbor.id in self.no_kelp:
                return False
            return (
                self._same_block(neighbor, rule.head)
                or self._same_block(neighbor, rule.body)
                or self._support(world, at, rule.direction, SupportType.FULL, False)
            )

        if name == "MangrovePropagule":
            hanging = rule.flag
            neighbor = self._read(
                world, _relative(position, Direction.UP if hanging else Direction.DOWN)
            )
            if hanging:
                return neighbor.id in self.hanging_mangrove
            return neighbor.id in self.mangrove

        if name == "Speleothem":
            at = _relative(position, rule.direction.opposite())
            neighbor = self._read(world, at)
            if self._support(world, at, rule.direction, SupportType.FULL, False):
                return True
            below_state = self.registry.state(neighbor)
            state_state = self.registry.state(state)
            return (
                self._same_block(neighbor, state)
                and below_state is not None
                and state_state is not None
                and below_state.properties.get("vertical_direction")
                == state_state.properties.get("vertical_direction")
            )

        if name == "Scaffolding":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            distance = self._scaffold_distance(neighbor)
            if distance is None:
                if self._support(world, below, Direction.UP, SupportType.FULL, False):
                    return True
                distance = 7
            for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
                adjacent_state = self._read(world, _relative(position, direction))
                adjacent = self._scaffold_distance(adjacent_state)
                if adjacent is not None:
                    distance = min(distance, adjacent + 1)
                    if distance == 1:
                        break
            return distance < 7

        if name == "PistonHead":
            neighbor = self._read(world, _relative(position, rule.direction.opposite()))
            definition = self.registry.state(neighbor)
            state_def = self.registry.state(state)
            if definition is None or state_def is None:
                return False
            base = "minecraft:sticky_piston" if rule.flag else "minecraft:piston"
            return (
                (
                    (definition.name == base and definition.properties.get("extended") == "true")
                    or definition.name == "minecraft:moving_piston"
                )
                and definition.properties.get("facing") == state_def.properties.get("facing")
            )

        if name == "ChorusPlant":
            below = self._read(world, _relative(position, Direction.DOWN))
            above = self._read(world, _relative(position, Direction.UP))
            crowded = (not self.is_air(above)) and (not self.is_air(below))
            for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
                at = _relative(position, direction)
                neighbor = self._read(world, at)
                if self._same_block(neighbor, state):
                    if crowded:
                        return False
                    support = self._read(world, _relative(at, Direction.DOWN))
                    if self._same_block(support, state) or support.id in self.chorus_plant:
                        return True
            return self._same_block(below, state) or below.id in self.chorus_plant

        if name == "ChorusFlower":
            below = self._read(world, _relative(position, Direction.DOWN))
            if self._name(below) == "minecraft:chorus_plant" or below.id in self.chorus_flower:
                return True
            if not self.is_air(below):
                return False
            found = False
            for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
                neighbor = self._read(world, _relative(position, direction))
                if self._name(neighbor) == "minecraft:chorus_plant":
                    if found:
                        return False
                    found = True
                elif not self.is_air(neighbor):
                    return False
            return found

        if name == "PitcherCrop":
            if not rule.flag and self._brightness(world, position, 0) < 8:
                return False
            below = self._read(world, _relative(position, Direction.DOWN))
            if rule.flag:
                return self._is_lower_half(below, state)
            return below.id in self.crops

        if name == "SugarCane":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            if self._name(neighbor) == self._name(state):
                return True
            if neighbor.id not in self.sugar_cane:
                return False
            for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
                at = _relative(below, direction)
                adjacent = self._read(world, at)
                fluid = self._fluid(world, at)
                if self._fluid_matches(3, fluid) or adjacent.id in self.sugar_cane_adjacent:
                    return True
            return False

        if name == "LilyPad":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            fluid_below = self._fluid(world, below)
            fluid_here = self._fluid(world, position)
            return (
                self._fluid_matches(1, fluid_below) or neighbor.id in self.lily_pad
            ) and fluid_here.kind is FluidKind.EMPTY

        if name == "Frogspawn":
            below = _relative(position, Direction.DOWN)
            fluid_below = self._fluid(world, below)
            fluid_here = self._fluid(world, position)
            return (
                self._fluid_matches(2, fluid_below)
                or self._read(world, below).id in self.frogspawn
            ) and fluid_here.kind is FluidKind.EMPTY

        if name == "SporeBlossom":
            return self._support(
                world, _relative(position, Direction.UP), Direction.DOWN, SupportType.CENTER, True
            ) and (not self._fluid_matches(0, self._fluid(world, position)))

        if name == "SmallDripleaf":
            neighbor = self._read(world, _relative(position, Direction.DOWN))
            if rule.flag:
                return self._is_lower_half(neighbor, state)
            return neighbor.id in self.small_dripleaf or (
                self._fluid(world, position).kind is FluidKind.WATER
                and neighbor.id in self.vegetation
            )

        if name == "TallSeagrass":
            below = _relative(position, Direction.DOWN)
            if rule.flag:
                return self._is_lower_half(self._read(world, below), state)
            fluid = self._fluid(world, position)
            neighbor = self._read(world, below)
            return (
                self._support(world, below, Direction.UP, SupportType.FULL, False)
                and neighbor.id not in self.no_seagrass
                and self._fluid_matches(0, fluid)
                and fluid.is_full()
            )

        if name == "BigDripleaf":
            below = self._read(world, _relative(position, Direction.DOWN))
            return self._name(below) in (
                "minecraft:big_dripleaf",
                "minecraft:big_dripleaf_stem",
            ) or below.id in self.dripleaf

        if name == "BigDripleafStem":
            below = self._read(world, _relative(position, Direction.DOWN))
            above = self._read(world, _relative(position, Direction.UP))
            return (
                self._name(below) == "minecraft:big_dripleaf_stem" or below.id in self.dripleaf
            ) and self._name(above) in (
                "minecraft:big_dripleaf",
                "minecraft:big_dripleaf_stem",
            )

        if name == "Farmland":
            above = self._read(world, _relative(position, Direction.UP))
            return (
                not self.solid.contains(above)
                or self.maintains_farmland.__contains__(above.id)
            )

        if name == "Cocoa":
            return self._read(world, _relative(position, rule.direction)).id in self.cocoa

        if name == "Crop":
            return self._brightness(world, position, 0) >= 8 and (
                self._read(world, _relative(position, Direction.DOWN)).id in self.crops
            )

        if name == "DoublePlant":
            below = self._read(world, _relative(position, Direction.DOWN))
            if not rule.flag:
                return below.id in self.vegetation
            below_state = self.registry.state(below)
            state_state = self.registry.state(state)
            return (
                below_state is not None
                and state_state is not None
                and below_state.name == state_state.name
                and below_state.properties.get("half") == "lower"
            )

        if name == "Door":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            if rule.flag:
                return self._name(neighbor) == self._name(state)
            return self._support(world, below, Direction.UP, SupportType.FULL, False)

        if name == "TagBelow":
            return self._read(world, _relative(position, Direction.DOWN)).id in self.bound_tags[rule.tag_index]

        if name == "CactusFlower":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            return neighbor.id in self.cactus_flower or self._support(
                world, below, Direction.UP, SupportType.CENTER, False
            )

        if name == "Seagrass":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            return self._support(
                world, below, Direction.UP, SupportType.FULL, False
            ) and (neighbor.id not in self.no_seagrass)

        if name == "BubbleColumn":
            below = self._read(world, _relative(position, Direction.DOWN))
            return (
                self._name(below) == self._name(state)
                or below.id in self.bubble_up
                or below.id in self.bubble_down
            )

        if name == "RedstoneWire":
            below = _relative(position, Direction.DOWN)
            neighbor = self._read(world, below)
            return self._support(
                world, below, Direction.UP, SupportType.FULL, False
            ) or self._name(neighbor) == "minecraft:hopper"

        if name == "Solid":
            return self.solid.contains(self._read(world, _relative(position, rule.face)))

        if name == "NonAirBelow":
            return not self.is_air(self._read(world, _relative(position, Direction.DOWN)))

        if name == "MossCarpet":
            below = self._read(world, _relative(position, Direction.DOWN))
            if rule.flag:
                return not self.is_air(below)
            below_state = self.registry.state(below)
            state_state = self.registry.state(state)
            return (
                below_state is not None
                and state_state is not None
                and below_state.name == state_state.name
                and below_state.properties.get("bottom") == "true"
            )

        if name == "Support":
            return self._support(
                world,
                _relative(position, rule.face.opposite()),
                rule.face,
                rule.kind,
                rule.center_restriction,
            )

        if name == "RigidOrCenterBelow":
            below = _relative(position, Direction.DOWN)
            return self._support(
                world, below, Direction.UP, SupportType.RIGID, False
            ) or self._support(world, below, Direction.UP, SupportType.CENTER, True)

        if name == "SupportsBamboo":
            return self._read(world, _relative(position, Direction.DOWN)).id in self.supports_bamboo

        raise SurvivalError(f"[QuadRix] unhandled survival rule {name!r}")


def _attach_resolver(registry: Optional[BlockSurvivalRegistry], resolver: BlockTagResolver) -> BlockSurvivalRegistry:
    """Внутренний помощник: сохранить резолвер тегов в реестре."""
    if registry is None:
        raise SurvivalError("[QuadRix] survival registry is not loaded")
    registry.tag_resolver = resolver
    return registry


# ---------------------------------------------------------------------------
# Разбор правила по состоянию (block_survival.rs:227-430)
# ---------------------------------------------------------------------------

def _bind_rule(
    registry,
    state: BlockState,
    text: str,
    tag_names: List[str],
    tag_indices: Dict[str, int],
) -> Rule:
    props = state.properties

    def prop(key: str) -> str:
        value = props.get(key)
        if value is None:
            raise SurvivalError(f"[QuadRix] missing survival property {key!r} for {state.name}")
        return value

    def facing() -> Direction:
        value = prop("facing")
        mapping = {
            "down": Direction.DOWN,
            "up": Direction.UP,
            "north": Direction.NORTH,
            "south": Direction.SOUTH,
            "west": Direction.WEST,
            "east": Direction.EAST,
        }
        if value not in mapping:
            raise SurvivalError(f"[QuadRix] invalid survival facing {value!r}")
        return mapping[value]

    def boolean(key: str) -> bool:
        value = prop(key)
        if value == "true":
            return True
        if value == "false":
            return False
        raise SurvivalError(f"[QuadRix] invalid survival boolean {value!r}")

    def upper_half() -> bool:
        value = prop("half")
        if value == "upper":
            return True
        if value == "lower":
            return False
        raise SurvivalError(f"[QuadRix] invalid survival half {value!r}")

    def full(face: Direction) -> Rule:
        return Rule("Support", face=face, kind=SupportType.FULL, center_restriction=False)

    def faces() -> int:
        mask = 0
        for direction in Direction.ALL:
            dname = _DIRECTION_NAMES[direction]
            if dname in props.properties and boolean(dname):
                mask |= 1 << direction.value
        return mask

    if text.startswith("TagBelow:"):
        tag = text[len("TagBelow:"):]
        return Rule("TagBelow", tag_index=_tag_index(tag, tag_names, tag_indices))

    if text == "Fire":
        return Rule("Fire")
    if text == "Cactus":
        return Rule("Cactus")
    if text == "Path":
        return Rule("Path")
    if text == "Mushroom":
        return Rule("Mushroom")
    if text == "Multiface":
        return Rule("Multiface", faces=faces())
    if text == "Vine":
        return Rule("Vine", faces=faces())
    if text == "HangingMoss":
        return Rule("HangingMoss")
    if text == "SnowLayer":
        return Rule("SnowLayer")
    if text == "SeaPickle":
        return Rule("SeaPickle")
    if text == "Bell":
        attachment = prop("attachment")
        if attachment == "floor":
            return Rule("Support", face=Direction.UP, kind=SupportType.FULL, center_restriction=False)
        if attachment == "ceiling":
            return Rule("Support", face=Direction.DOWN, kind=SupportType.CENTER, center_restriction=True)
        if attachment in ("single_wall", "double_wall"):
            return Rule("Support", face=facing().opposite(), kind=SupportType.FULL, center_restriction=False)
        raise SurvivalError(f"[QuadRix] invalid bell attachment {attachment!r}")
    if text == "GrowingPlant":
        families = {
            "minecraft:kelp": ("minecraft:kelp", "minecraft:kelp_plant", Direction.UP, True),
            "minecraft:kelp_plant": ("minecraft:kelp", "minecraft:kelp_plant", Direction.UP, True),
            "minecraft:cave_vines": ("minecraft:cave_vines", "minecraft:cave_vines_plant", Direction.DOWN, False),
            "minecraft:cave_vines_plant": ("minecraft:cave_vines", "minecraft:cave_vines_plant", Direction.DOWN, False),
            "minecraft:twisting_vines": ("minecraft:twisting_vines", "minecraft:twisting_vines_plant", Direction.UP, False),
            "minecraft:twisting_vines_plant": ("minecraft:twisting_vines", "minecraft:twisting_vines_plant", Direction.UP, False),
            "minecraft:weeping_vines": ("minecraft:weeping_vines", "minecraft:weeping_vines_plant", Direction.DOWN, False),
            "minecraft:weeping_vines_plant": ("minecraft:weeping_vines", "minecraft:weeping_vines_plant", Direction.DOWN, False),
        }
        family = families.get(state.name)
        if family is None:
            raise SurvivalError(f"[QuadRix] unknown growing plant family {state.name}")
        head_name, body_name, direction, kelp = family
        head = registry.default_state(head_name)
        body = registry.default_state(body_name)
        if head is None or body is None:
            raise SurvivalError("[QuadRix] missing growing plant head/body")
        return Rule("GrowingPlant", head=head, body=body, direction=direction, flag=kelp)
    if text == "MangrovePropagule":
        return Rule("MangrovePropagule", flag=boolean("hanging"))
    if text == "Speleothem":
        value = prop("vertical_direction")
        if value == "up":
            return Rule("Speleothem", direction=Direction.UP)
        if value == "down":
            return Rule("Speleothem", direction=Direction.DOWN)
        raise SurvivalError(f"[QuadRix] invalid speleothem direction {value!r}")
    if text == "Scaffolding":
        return Rule("Scaffolding")
    if text == "PistonHead":
        value = prop("type")
        if value == "normal":
            sticky = False
        elif value == "sticky":
            sticky = True
        else:
            raise SurvivalError(f"[QuadRix] invalid piston head type {value!r}")
        return Rule("PistonHead", direction=facing(), flag=sticky)
    if text == "ChorusPlant":
        return Rule("ChorusPlant")
    if text == "ChorusFlower":
        return Rule("ChorusFlower")
    if text == "PitcherCrop":
        return Rule("PitcherCrop", flag=upper_half())
    if text == "SugarCane":
        return Rule("SugarCane")
    if text == "LilyPad":
        return Rule("LilyPad")
    if text == "Frogspawn":
        return Rule("Frogspawn")
    if text == "SporeBlossom":
        return Rule("SporeBlossom")
    if text == "SmallDripleaf":
        return Rule("SmallDripleaf", flag=upper_half())
    if text == "TallSeagrass":
        return Rule("TallSeagrass", flag=upper_half())
    if text == "BigDripleaf":
        return Rule("BigDripleaf")
    if text == "BigDripleafStem":
        return Rule("BigDripleafStem")
    if text == "Farmland":
        return Rule("Farmland")
    if text == "Cocoa":
        return Rule("Cocoa", direction=facing())
    if text == "Crop":
        return Rule("Crop")
    if text == "DoublePlant":
        return Rule("DoublePlant", flag=upper_half())
    if text == "Door":
        return Rule("Door", flag=upper_half())
    if text == "CactusFlower":
        return Rule("CactusFlower")
    if text == "Seagrass":
        return Rule("Seagrass")
    if text == "BubbleColumn":
        return Rule("BubbleColumn")
    if text == "RedstoneWire":
        return Rule("RedstoneWire")
    if text == "Always":
        return Rule("Always")
    if text == "SolidBelow":
        return Rule("Solid", face=Direction.DOWN)
    if text == "SolidBehind":
        return Rule("Solid", face=facing().opposite())
    if text == "NonAirBelow":
        return Rule("NonAirBelow")
    if text == "MossCarpet":
        return Rule("MossCarpet", flag=boolean("bottom"))
    if text == "CenterBelow":
        return Rule("Support", face=Direction.UP, kind=SupportType.CENTER, center_restriction=True)
    if text == "Lantern":
        face = Direction.DOWN if boolean("hanging") else Direction.UP
        return Rule("Support", face=face, kind=SupportType.CENTER, center_restriction=True)
    if text == "FullAbove":
        return full(Direction.DOWN)
    if text == "FullBehind":
        return full(facing())
    if text == "RigidOrCenterBelow":
        return Rule("RigidOrCenterBelow")
    if text == "RigidBelow":
        return Rule("Support", face=Direction.UP, kind=SupportType.RIGID, center_restriction=False)
    if text == "FullBelow":
        return full(Direction.UP)
    if text == "CenterAbove":
        return Rule("Support", face=Direction.DOWN, kind=SupportType.CENTER, center_restriction=False)
    if text == "FaceAttached":
        value = prop("face")
        if value == "floor":
            return full(Direction.UP)
        if value == "ceiling":
            return full(Direction.DOWN)
        if value == "wall":
            return full(facing())
        raise SurvivalError(f"[QuadRix] invalid attachment face {value!r}")
    if text == "SupportsBamboo":
        return Rule("SupportsBamboo")
    raise SurvivalError(f"[QuadRix] unknown survival rule {text!r}")


def _tag_index(tag: str, tag_names: List[str], tag_indices: Dict[str, int]) -> int:
    index = tag_indices.get(tag)
    if index is None:
        index = len(tag_names)
        tag_names.append(tag)
        tag_indices[tag] = index
    return index


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _as_state_id(registry, value: Union[BlockStateId, int, BlockState, str]) -> BlockStateId:
    if isinstance(value, BlockStateId):
        return value
    if isinstance(value, BlockState):
        found = registry.id(value)
        if found is None:
            raise SurvivalError(f"[QuadRix] state not in registry: {value.name}")
        return found
    if isinstance(value, int):
        return BlockStateId(value)
    if isinstance(value, str):
        found = registry.default_state(value)
        if found is None:
            raise SurvivalError(f"[QuadRix] unknown block state name: {value!r}")
        return found
    raise SurvivalError(f"[QuadRix] unsupported state type: {type(value)!r}")


def _relative(position: Sequence[int], direction: Direction) -> Tuple[int, int, int]:
    """block_survival.rs:1206 — сосед с i32-wrapping-сложением."""
    normal = direction.normal()
    return (
        _wrap_i32(position[0] + normal[0]),
        _wrap_i32(position[1] + normal[1]),
        _wrap_i32(position[2] + normal[2]),
    )


def _wrap_i32(value: int) -> int:
    return ((value + 2**31) % 2**32) - 2**31


def _face_shape_empty(shape, direction: Direction) -> bool:
    return not _face_rects(shape, direction)


# ---------------------------------------------------------------------------
# Значения по умолчанию (.local зафиксирован AGENTS.md)
# ---------------------------------------------------------------------------

_DEFAULT_SURVIVAL: Optional[BlockSurvivalRegistry] = None
_DEFAULT_FACTS: Optional[List[dict]] = None
_DEFAULT_LOOT_ROOT = _RESOURCE_ROOT / "data" / "minecraft" / "loot_table" / "blocks"


def default_survival() -> BlockSurvivalRegistry:
    """Ленивый ``BlockSurvivalRegistry`` по данным ``.local``."""
    global _DEFAULT_SURVIVAL
    if _DEFAULT_SURVIVAL is None:
        LOG.debug("[QuadRix] load block survival registry from %s", _BEHAVIOR_ROOT)
        _DEFAULT_SURVIVAL = BlockSurvivalRegistry.load()
    return _DEFAULT_SURVIVAL


def _facts() -> List[dict]:
    global _DEFAULT_FACTS
    if _DEFAULT_FACTS is None:
        data = json.loads((_RESOURCE_ROOT / "gameplay-facts.json").read_text())
        _DEFAULT_FACTS = data["states"]
    return _DEFAULT_FACTS


# ---------------------------------------------------------------------------
# Модульные функции (клиентский API разрушения блока)
# ---------------------------------------------------------------------------

def can_survive(
    world: SurvivalWorld,
    state: Union[BlockStateId, int, BlockState, str],
    position: Sequence[int],
) -> bool:
    """``can_survive`` — правилом состояния (см. ``BlockSurvivalRegistry``)."""
    return default_survival().can_survive(world, state, position)


def _state_id(state: Union[BlockStateId, int, BlockState, str]) -> BlockStateId:
    return _as_state_id(default_survival().registry, state)


def block_hardness(state: Union[BlockStateId, int, BlockState, str]) -> float:
    """Факт ``hardness`` состояния (``gameplay-facts.json``)."""
    sid = _state_id(state)
    return float(_facts()[sid.id]["hardness"])


def block_resistance(state: Union[BlockStateId, int, BlockState, str]) -> float:
    """Факт ``explosion_resistance`` состояния."""
    sid = _state_id(state)
    return float(_facts()[sid.id]["explosion_resistance"])


def requires_tool(state: Union[BlockStateId, int, BlockState, str]) -> bool:
    """``requiresCorrectToolForDrops`` состояния (``requires_tool``)."""
    sid = _state_id(state)
    return bool(_facts()[sid.id]["requires_tool"])


def _tool_rule_matches(block_ref: str, block_name: str, resolver: BlockTagResolver) -> bool:
    if block_ref.startswith("#"):
        return block_name in resolver.resolve(block_ref[1:])
    return _canonical(block_ref) == block_name


def _tool_blocks_match(block_ref: str, block_name: str) -> bool:
    survival = default_survival()
    resolver = survival.tag_resolver or BlockTagResolver({})
    return _tool_rule_matches(block_ref, block_name, resolver)


def can_harvest(
    state: Union[BlockStateId, int, BlockState, str],
    tool_stack: Union[ItemStack, str, None],
) -> bool:
    """Можно ли добыть дроп этим инструментом (``canHarvestBlock``)."""
    if not requires_tool(state):
        return True
    sid = _state_id(state)
    found = default_survival().registry.state(sid)
    if found is None:
        return False
    block_name = found.name
    item = tool_stack.item if isinstance(tool_stack, ItemStack) else tool_stack
    if not item:
        return False
    info = ITEM_REGISTRY.get(item)
    if info is None or not info.tool:
        return False
    for rule in info.tool:
        for block_ref in rule.blocks:
            if _tool_blocks_match(block_ref, block_name):
                return bool(rule.correct)
    return False


def is_harvestable(
    state: Union[BlockStateId, int, BlockState, str],
    tool_stack: Union[ItemStack, str, None] = None,
) -> bool:
    """Синоним ``can_harvest`` (имя из ванильного ``isHarvestable``)."""
    return can_harvest(state, tool_stack)


# ---------------------------------------------------------------------------
# Loot-таблицы (минимальный вычислитель 26.3)
# ---------------------------------------------------------------------------

@dataclass
class LootContext:
    """Контекст дропа (``LootContextParams``) для условий/функций."""

    tool: Optional[ItemStack] = None
    silk_touch: bool = False
    fortune: int = 0
    random: Optional[_random.Random] = None
    world: object = None
    position: Tuple[int, int, int] = (0, 0, 0)

    def rng(self) -> _random.Random:
        if self.random is None:
            self.random = _random.Random()
        return self.random


def _enchant_level(tool: Optional[ItemStack], enchant: str) -> int:
    if not isinstance(tool, ItemStack) or tool.extra is None:
        return 0
    for component in ("minecraft:enchantments", "minecraft:enchantment"):
        value = tool.extra.get(component)
        if isinstance(value, dict):
            level = value.get(enchant)
            if isinstance(level, dict):
                level = level.get("level")
            if isinstance(level, (int, float)):
                return int(level)
    return 0


def _loot_conditions_ok(conditions, ctx: LootContext) -> bool:
    if conditions is None:
        return True
    if isinstance(conditions, str):
        return _loot_condition_ok({"type": conditions}, ctx)
    if isinstance(conditions, dict):
        return _loot_condition_ok(conditions, ctx)
    if isinstance(conditions, list):
        return all(_loot_conditions_ok(c, ctx) for c in conditions)
    return True


def _loot_condition_ok(condition: dict, ctx: LootContext) -> bool:
    ctype = condition.get("type")
    if ctype in ("minecraft:survives_explosion", "minecraft:explosion_decay"):
        return True
    if ctype == "minecraft:tool/can_silk_touch":
        return ctx.silk_touch
    if ctype == "minecraft:random_chance":
        return ctx.rng().random() < float(condition.get("chance", 1.0))
    if ctype == "minecraft:random_chance_with_looting":
        chance = float(condition.get("chance", 1.0))
        looting = _enchant_level(ctx.tool, "minecraft:looting")
        chance += float(condition.get("looting_multiplier", 0.0)) * looting
        return ctx.rng().random() < chance
    if ctype == "minecraft:table_bonus":
        enchant = str(condition.get("enchantment", "minecraft:fortune"))
        level = _enchant_level(ctx.tool, enchant)
        chances = condition.get("chances", [])
        if 0 <= level < len(chances):
            return ctx.rng().random() < float(chances[level])
        return False
    if ctype == "minecraft:inverted":
        return not _loot_conditions_ok(condition.get("term"), ctx)
    if ctype == "minecraft:any_of":
        return any(_loot_conditions_ok(t, ctx) for t in condition.get("terms", []))
    if ctype == "minecraft:all_of":
        return all(_loot_conditions_ok(t, ctx) for t in condition.get("terms", []))
    if ctype == "minecraft:killed_by_player":
        return False
    if ctype in (
        "minecraft:match_tool",
        "minecraft:block_state_property",
        "minecraft:location_check",
        "minecraft:entity_properties",
        "minecraft:entity_scores",
        "minecraft:time_check",
        "minecraft:value_check",
        "minecraft:weather_check",
        "minecraft:reference",
    ):
        return True
    LOG.warning("[QuadRix] unknown loot condition %r treated as true", ctype)
    return True


def _parse_count(count, ctx: LootContext) -> int:
    if count is None:
        return 1
    if isinstance(count, bool):
        return 1
    if isinstance(count, (int, float)):
        return int(count)
    if isinstance(count, dict):
        uniform = count.get("minecraft:uniform", count)
        if isinstance(uniform, dict) and "min" in uniform and "max" in uniform:
            return int(ctx.rng().randint(int(uniform["min"]), int(uniform["max"])))
    return 1


def _apply_bonus(function: dict, stack: ItemStack, ctx: LootContext) -> None:
    formula = function.get("formula")
    enchant = str(function.get("enchantment", "minecraft:fortune"))
    level = _enchant_level(ctx.tool, enchant)
    if level <= 0:
        return
    if formula == "minecraft:ore_drops":
        if ctx.rng().random() < (1.0 / (level + 1.0)):
            stack.count *= level + 1
    elif formula == "minecraft:uniform_bonus_count":
        bonus = int(function.get("bonusMultiplier", 1))
        stack.count += ctx.rng().randint(0, bonus * level)
    elif formula == "minecraft:binomial_with_bonus_count":
        extra = int(function.get("extraRounds", 0))
        probability = float(function.get("probability", 0.0))
        for _ in range(level + extra):
            if ctx.rng().random() < probability:
                stack.count += 1


def _apply_function(function: dict, stack: ItemStack, ctx: LootContext) -> None:
    ftype = function.get("function")
    if ftype == "minecraft:set_count":
        stack.count = _parse_count(function.get("count"), ctx)
    elif ftype == "minecraft:apply_bonus":
        _apply_bonus(function, stack, ctx)
    elif ftype == "minecraft:limit_count":
        limit = function.get("limit", {})
        if isinstance(limit, dict) and "max" in limit:
            stack.count = min(stack.count, int(limit["max"]))
    elif ftype in ("minecraft:explosion_decay", "minecraft:enchant_randomly", "minecraft:set_damage"):
        return
    else:
        LOG.warning("[QuadRix] unknown loot function %r ignored", ftype)


def _eval_loot_entry(entry: dict, ctx: LootContext) -> List[ItemStack]:
    if not _loot_conditions_ok(entry.get("condition", entry.get("conditions")), ctx):
        return []
    etype = entry.get("type")
    if etype == "minecraft:alternatives":
        for child in entry.get("children", []):
            if _loot_conditions_ok(child.get("condition", child.get("conditions")), ctx):
                return _eval_loot_entry(child, ctx)
        return []
    if etype in ("minecraft:group", "minecraft:sequence"):
        out: List[ItemStack] = []
        for child in entry.get("children", []):
            out.extend(_eval_loot_entry(child, ctx))
        return out
    if etype == "minecraft:loot_table":
        value = entry.get("value", entry.get("name"))
        if isinstance(value, str):
            table = _load_loot_table(value)
            return _eval_loot_table(table, ctx)
        return []
    if etype in ("minecraft:tag", "minecraft:dynamic"):
        return []
    name = entry.get("name")
    if not isinstance(name, str):
        return []
    count = _parse_count(entry.get("count"), ctx)
    stack = ItemStack.new(name, count)
    for function in entry.get("functions", []):
        _apply_function(function, stack, ctx)
    return [stack]


def _select_entry(entries: List[dict], ctx: LootContext) -> Optional[dict]:
    candidates = [e for e in entries if _loot_conditions_ok(e.get("condition", e.get("conditions")), ctx)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    total = 0.0
    weights = []
    for entry in candidates:
        weight = float(entry.get("weight", 1))
        weights.append(weight)
        total += weight
    pick = ctx.rng().random() * total
    acc = 0.0
    for entry, weight in zip(candidates, weights):
        acc += weight
        if pick < acc:
            return entry
    return candidates[-1]


def _eval_loot_table(table: Optional[dict], ctx: LootContext) -> List[ItemStack]:
    if not table:
        return []
    out: List[ItemStack] = []
    for pool in table.get("pools", []):
        if not _loot_conditions_ok(pool.get("condition", pool.get("conditions")), ctx):
            continue
        rolls = _parse_count(pool.get("rolls", 1), ctx)
        bonus_rolls = pool.get("bonus_rolls")
        if bonus_rolls:
            rolls += _parse_count(bonus_rolls, ctx)
        entries = pool.get("entries", [])
        for _ in range(max(rolls, 0)):
            entry = _select_entry(entries, ctx)
            if entry is None:
                continue
            out.extend(_eval_loot_entry(entry, ctx))
    return out


_LOOT_CACHE: Dict[str, Optional[dict]] = {}


def _load_loot_table(name: str) -> Optional[dict]:
    key = _canonical(name)
    if key in _LOOT_CACHE:
        return _LOOT_CACHE[key]
    path = _DEFAULT_LOOT_ROOT / f"{key.split(':', 1)[1]}.json"
    table: Optional[dict] = None
    if path.exists():
        table = json.loads(path.read_text())
    _LOOT_CACHE[key] = table
    return table


def get_drops(
    state: Union[BlockStateId, int, BlockState, str],
    tool_stack: Union[ItemStack, str, None] = None,
    world: object = None,
    position: Sequence[int] = (0, 0, 0),
    random: Optional[_random.Random] = None,
) -> List[ItemStack]:
    """Дроп блока по loot-таблице (фолбэк — факт ``item``)."""
    survival = default_survival()
    sid = _as_state_id(survival.registry, state)
    found = survival.registry.state(sid)
    if found is None:
        return []
    tool = tool_stack if isinstance(tool_stack, ItemStack) else (ItemStack.new(tool_stack, 1) if tool_stack else None)
    # Ваниль ``Block.playerDestroy``: для ``requiresCorrectToolForDrops`` блоков
    # дроп выдаётся только при подходящем инструменте (иначе — пусто).
    if requires_tool(sid) and not can_harvest(sid, tool):
        return []
    ctx = LootContext(
        tool=tool,
        silk_touch=_enchant_level(tool, "minecraft:silk_touch") > 0,
        fortune=_enchant_level(tool, "minecraft:fortune"),
        random=random,
        world=world,
        position=(int(position[0]), int(position[1]), int(position[2])),
    )
    table = _load_loot_table(found.name)
    if table is not None:
        return _eval_loot_table(table, ctx)
    item = _facts()[sid.id].get("item")
    if isinstance(item, str) and item:
        return [ItemStack.new(item, 1)]
    return []


def break_block(
    world,
    position: Sequence[int],
    tool_stack: Union[ItemStack, str, None] = None,
    random: Optional[_random.Random] = None,
) -> List[ItemStack]:
    """Разрушить блок: дроп + ``set_block(pos, air, 3)`` (vanilla destroyBlock)."""
    survival = default_survival()
    pos = (int(position[0]), int(position[1]), int(position[2]))
    state = world.get_block(pos)
    sid = _as_state_id(survival.registry, state)
    drops = get_drops(sid, tool_stack, world, pos, random)
    air = survival.registry.default_state("minecraft:air")
    if air is not None:
        setter = getattr(world, "set_block", None)
        if setter is not None:
            try:
                setter(pos, air, 3)
            except TypeError:
                setter(pos, air)
    return drops
