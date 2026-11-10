#!/usr/bin/env python3
"""[QuadRix] Установка блоков: `BlockItem.place`, `canBeReplaced` и
`getStateForPlacement` — то, чем клиент СТАВИТ блоки.

Порт (Minecraft 26.3):
  * ``horizon/crates/horizon-world/src/level/place.rs`` — ``PlaceContext``,
    ``PlacementContext``, ``Sim::can_be_replaced``, ``Behaviours::place_block``,
    ``placement_state``/``state_for_placement`` и вспомогательные функции
    (``from_y_rot``, ``rotation_segment``, ``ordered_by_nearest``);
  * ``horizon/crates/horizon-world/src/level/mod.rs`` — ``is_air``, ``is_solid``,
    ``is_replaceable`` (флаги состояний ``data::state_flags``);
  * ``horizon/crates/horizon-world/src/block_survival.rs`` /
    ``level/survive.rs`` — ``can_survive`` (в упрощённом виде, см. ниже);
  * ``horizon/crates/horizon-world/src/block_properties.rs`` —
    ``calculate_solid`` (через форму столкновения);
  * ``horizon/crates/horizon-world/src/worldgen/block_placement.rs`` —
    ``HORIZONTAL``, ``SIDE_NAMES``, ``relative``, ``Placement``, ``DoublePlant``,
    ``Moss`` (примитивы предкомпилированных переходов; сам ``place`` для
    worldgen-фич требует ``FeatureWorld``/``FluidStateTable`` и остаётся за
    сессией worldgen).

Что не портировано в этой сессии (отдельные модули):
  * ``item_use.rs``, ``world_ray.rs``.

``can_survive`` делегирует в :mod:`quadrix.world.block_survival`
(полный порт ``block_survival.rs`` этой сессии).

Имена и поля сохранены как в Rust. ``is_solid`` использует ту же формулу, что
``BlockDefinitionProperties::calculate_solid``, но флаги ``force_solid_on/off``
берутся из ``block_properties`` — модуль ПОКА НЕ ПОРТИРОВАН, поэтому включено
поведение по форме столкновения (fallback). Там, где нужен ``block_properties``,
стоит пометка ``# FALLBACK: block_properties pending``.
"""

from __future__ import annotations

import logging
import math
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Protocol, Tuple, Union

from quadrix.core.geometry import (
    Aabb,
    Axis,
    BlockPos,
    Direction,
    Vec3,
    cos_angle,
    sin_angle,
)
from quadrix.items.items import ItemStack
from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    collision_shape,
    default_collision_registry,
)
from quadrix.world.registry import (
    BlockProperties,
    BlockRegistry,
    BlockState,
    BlockStateId,
)

__all__ = [
    "HORIZONTAL",
    "SIDE_NAMES",
    "AIR_NAMES",
    "REPLACEABLE_NAMES",
    "SOLID_MIN_AVERAGE_SIZE",
    "SOLID_MIN_HEIGHT",
    "Placement",
    "DoublePlant",
    "Moss",
    "PlaceContext",
    "PlacementContext",
    "PlacementWorld",
    "BlockPlacement",
    "relative",
    "ordered_by_nearest",
    "from_y_rot",
    "rotation_segment",
    "is_air",
    "is_solid",
    "is_replaceable",
    "can_place_block",
    "get_placement_state",
    "default_registry",
    "default_placement",
]

LOG = logging.getLogger("quadrix.block_placement")

# ---------------------------------------------------------------------------
# Константы из worldgen/block_placement.rs и level/place.rs
# ---------------------------------------------------------------------------

# worldgen/block_placement.rs:15 — горизонтальные направления в этом порядке.
HORIZONTAL: Tuple[Direction, ...] = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)

# worldgen/block_placement.rs:21 — имена тех же сторон (свойства moss).
SIDE_NAMES: Tuple[str, ...] = ("north", "east", "south", "west")

# worldgen/block_placement.rs:185 — массив air-состояний
# ``[air, cave_air, void_air]``.
AIR_NAMES = frozenset(
    {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
)

# block_properties.rs:56 — порог «солидности» по среднему размеру и высоте.
SOLID_MIN_AVERAGE_SIZE: float = 0.7291666666666666
SOLID_MIN_HEIGHT: float = 1.0

# FALLBACK: block_properties pending — флаг ``replaceable`` приходит из
# block_properties.nbt (BlockDefinitionProperties.replaceable), который ещё не
# портирован. Здесь — ванильный набор заменяемых блоков (air/трава/снег/вода и
# т.п.). Когда block_properties появится, набор заменится на ``BoundBlockProperty``.
REPLACEABLE_NAMES = frozenset(
    {
        "minecraft:air",
        "minecraft:cave_air",
        "minecraft:void_air",
        "minecraft:water",
        "minecraft:lava",
        "minecraft:short_grass",
        "minecraft:grass",
        "minecraft:tall_grass",
        "minecraft:fern",
        "minecraft:large_fern",
        "minecraft:dead_bush",
        "minecraft:snow",
        "minecraft:vine",
        "minecraft:glow_lichen",
        "minecraft:fire",
        "minecraft:soul_fire",
        "minecraft:seagrass",
        "minecraft:tall_seagrass",
        "minecraft:light",
        "minecraft:structure_void",
        "minecraft:bubble_column",
        "minecraft:nether_portal",
        "minecraft:end_portal",
        "minecraft:end_gateway",
        "minecraft:powder_snow",
        "minecraft:warped_roots",
        "minecraft:crimson_roots",
        "minecraft:nether_sprouts",
        "minecraft:hanging_roots",
    }
)

# level/query.rs:46 — ``Direction.from2DDataValue`` (S, W, N, E).
_FROM_2D: Tuple[Direction, ...] = (
    Direction.SOUTH,
    Direction.WEST,
    Direction.NORTH,
    Direction.EAST,
)


def _f32(value: float) -> float:
    """Округление до f32 (Rust-константы и аргументы тригонометрии)."""
    return struct.unpack(">f", struct.pack(">f", value))[0]


# ---------------------------------------------------------------------------
# worldgen/block_placement.rs: enum Placement / DoublePlant / Moss
# ---------------------------------------------------------------------------

class Placement(Enum):
    """worldgen/block_placement.rs:24 — вид предкомпилированного перехода.

    Rust ``Placement::Double(usize)`` несёт индекс в ``doubles``; по таблице
    перевода payload вынесен в поле рядом (индекс берётся из ``BlockPlacement``).
    """

    SINGLE = "single"
    DOUBLE = "double"
    MOSS = "moss"


@dataclass(frozen=True)
class DoublePlant:
    """worldgen/block_placement.rs:30 — половины растения (lower/upper x water)."""

    halves: Tuple[Tuple[BlockStateId, BlockStateId], Tuple[BlockStateId, BlockStateId]]
    waterlogged: bool


@dataclass(frozen=True)
class Moss:
    """worldgen/block_placement.rs:35 — состояние pale moss carpet."""

    bottom: bool
    sides: Tuple[int, int, int, int]

    def code(self) -> int:
        """worldgen/block_placement.rs:40 — код 0..161 (base-3 по сторонам)."""
        code = int(self.bottom)
        for side in self.sides:
            code = code * 3 + int(side)
        return code

    def has_faces(self) -> bool:
        """worldgen/block_placement.rs:47 — есть ли хоть одна грань."""
        return self.bottom or any(side != 0 for side in self.sides)


# ---------------------------------------------------------------------------
# level/place.rs:19 — PlaceContext (вход use-on-block)
# ---------------------------------------------------------------------------

@dataclass
class PlaceContext:
    """``UseOnContext``: что игрок нажал и чем (level/place.rs:21)."""

    clicked_pos: BlockPos
    face: Direction
    hit: Vec3
    inside: bool
    yaw: float
    pitch: float
    sneaking: bool
    item: str
    can_use_game_master_blocks: bool = False


# ---------------------------------------------------------------------------
# level/place.rs:55 — PlacementContext (после разрешения позиции)
# ---------------------------------------------------------------------------

@dataclass
class PlacementContext:
    """``BlockPlaceContext``: что читает ``getStateForPlacement`` (place.rs:55).

    ``pos`` — куда сядет блок (сам кликнутый блок, если его можно заменить,
    иначе соседний), ``hit_pos`` — куда пришёлся клик.
    """

    pos: BlockPos
    hit_pos: BlockPos
    face: Direction
    hit: Vec3
    inside: bool = False
    yaw: float = 0.0
    pitch: float = 0.0
    sneaking: bool = False
    item: str = ""
    replace_clicked: bool = False

    # -- запросы (level/place.rs:152-186) --

    def horizontal_direction(self) -> Direction:
        """``getHorizontalDirection`` = ``Direction.fromYRot(yaw)``."""
        return from_y_rot(float(self.yaw))

    def nearest_looking_direction(self) -> Direction:
        """``getNearestLookingDirection`` (place.rs:169)."""
        return ordered_by_nearest(self.yaw, self.pitch)[0]

    def click_y(self) -> float:
        """``UseOnContext`` высота клика относительно ``pos`` (place.rs:179)."""
        return self.hit.y - float(self.pos.y)

    def half_from_click(self) -> bool:
        """Нижняя половина? (place.rs:183). ``True`` — bottom."""
        return self.face != Direction.DOWN and (
            self.face == Direction.UP or self.click_y() <= 0.5
        )

    def nearest_looking_directions(self) -> Tuple[Direction, ...]:
        """``nearestLookingDirections`` (place.rs:155)."""
        directions = list(ordered_by_nearest(self.yaw, self.pitch))
        if self.replace_clicked:
            return tuple(directions)
        target = self.face.opposite()
        if target in directions:
            index = directions.index(target)
            if index > 0:
                directions.pop(index)
                directions.insert(0, target)
        return tuple(directions)


# ---------------------------------------------------------------------------
# Мир, в который ставим блок (Rust: LevelAccess / FeatureWorld)
# ---------------------------------------------------------------------------

class PlacementWorld(Protocol):
    """Минимальный интерфейс мира для установки блока.

    Rust ``LevelAccess`` умеет куда больше; для решения «можно ли поставить»
    нужны ``getBlockState`` и (для самой установки) ``setBlock``.
    """

    def get_block(self, position: Tuple[int, int, int]) -> BlockStateId:
        ...

    def set_block(
        self, position: Tuple[int, int, int], state: BlockStateId, flags: int
    ) -> bool:
        ...


# ---------------------------------------------------------------------------
# Вспомогательные функции (level/query.rs, level/place.rs, block_placement.rs)
# ---------------------------------------------------------------------------

def relative(position: Tuple[int, int, int], direction: Direction) -> Tuple[int, int, int]:
    """worldgen/block_placement.rs:373 — сосед с i32-wrapping-сложением."""
    step = direction.normal()
    return (
        _wrap_i32(position[0] + step[0]),
        _wrap_i32(position[1] + step[1]),
        _wrap_i32(position[2] + step[2]),
    )


def _wrap_i32(value: int) -> int:
    """``i32::wrapping_add`` — сложение по модулю 2^32."""
    return ((value + 2**31) % 2**32) - 2**31


def from_y_rot(yaw: float) -> Direction:
    """level/place.rs:133 — ``Direction.fromYRot``."""
    value = int(math.floor(yaw / 90.0 + 0.5)) & 3
    return _FROM_2D[value]


def rotation_segment(degrees: float) -> int:
    """level/place.rs:139 — ``RotationSegment.convertToSegment(float)``."""
    return int(math.floor(_f32(degrees) * (16.0 / 360.0) + 0.5)) & 15


def ordered_by_nearest(yaw: float, pitch: float) -> Tuple[Direction, ...]:
    """level/place.rs:82 — ``Direction.orderedByNearest(entity)``."""
    pitch_rad = _f32(pitch * (math.pi / 180.0))
    yaw_rad = _f32(-yaw * (math.pi / 180.0))
    pitch_sin = sin_angle(pitch_rad)
    pitch_cos = cos_angle(pitch_rad)
    yaw_sin = sin_angle(yaw_rad)
    yaw_cos = cos_angle(yaw_rad)
    x_pos = yaw_sin > 0.0
    y_pos = pitch_sin < 0.0
    z_pos = yaw_cos > 0.0
    x_yaw = yaw_sin if x_pos else -yaw_sin
    y_mag = -pitch_sin if y_pos else pitch_sin
    z_yaw = yaw_cos if z_pos else -yaw_cos
    x_mag = x_yaw * pitch_cos
    z_mag = z_yaw * pitch_cos
    ax = Direction.EAST if x_pos else Direction.WEST
    ay = Direction.UP if y_pos else Direction.DOWN
    az = Direction.SOUTH if z_pos else Direction.NORTH

    def make(a: Direction, b: Direction, c: Direction) -> Tuple[Direction, ...]:
        return (a, b, c, c.opposite(), b.opposite(), a.opposite())

    if x_yaw > z_yaw:
        if y_mag > x_mag:
            return make(ay, ax, az)
        if z_mag > y_mag:
            return make(ax, az, ay)
        return make(ax, ay, az)
    if y_mag > z_mag:
        return make(ay, az, ax)
    if x_mag > y_mag:
        return make(az, ax, ay)
    return make(az, ay, ax)


# ---------------------------------------------------------------------------
# BlockPlacement — правила установки (Rust: Behaviours/Sim + BlockPlacement)
# ---------------------------------------------------------------------------

class BlockPlacement:
    """Правила установки блока для реестра ``registry``.

    Именовано как Rust ``BlockPlacement``. Здесь собраны запросы player-facing
    установки (level/place.rs + level/mod.rs) и примитивы worldgen-переходов.
    """

    def __init__(
        self,
        registry: BlockRegistry,
        collision: Optional[CachedCollisionRegistry] = None,
    ) -> None:
        self.registry = registry
        self._collision = collision

    # -- доступ к состояниям --

    @property
    def collision(self) -> CachedCollisionRegistry:
        if self._collision is None:
            self._collision = default_collision_registry(self.registry)
        return self._collision

    def state_name(self, state: Union[BlockStateId, int, BlockState, str]) -> str:
        """Имя блока для состояния/имени/id."""
        if isinstance(state, str):
            return state
        if isinstance(state, BlockState):
            return state.name
        if isinstance(state, int):
            state = BlockStateId(state)
        if isinstance(state, BlockStateId):
            found = self.registry.state(state)
            return found.name if found is not None else ""
        raise TypeError(f"unsupported state type: {type(state)!r}")

    # -- флаги состояний (level/mod.rs:875-883) --

    def is_air(self, state: Union[BlockStateId, int, BlockState, str]) -> bool:
        """``LevelFacts::is_air`` (level/mod.rs:875, флаг AIR)."""
        return self.state_name(state) in AIR_NAMES

    def is_solid(self, state: Union[BlockStateId, int, BlockState, str]) -> bool:
        """``LevelFacts::is_solid`` (level/mod.rs:878).

        Формула — ``BlockDefinitionProperties::calculate_solid``
        (block_properties.rs:46): по форме столкновения.
        ``# FALLBACK: block_properties pending`` — флаги force_solid_on/off
        появятся вместе с block_properties.
        """
        if isinstance(state, str) or isinstance(state, BlockState):
            resolved = self.registry.default_state(self.state_name(state))
            if resolved is None:
                return False
            state_id = resolved
        else:
            state_id = state if isinstance(state, BlockStateId) else BlockStateId(state)
        shape = collision_shape(self.registry, state_id, self.collision)
        if shape.is_empty():
            return False
        minimum = Vec3(shape.min(Axis.X), shape.min(Axis.Y), shape.min(Axis.Z))
        maximum = Vec3(shape.max(Axis.X), shape.max(Axis.Y), shape.max(Axis.Z))
        bounds = Aabb.new(minimum, maximum)
        return (
            bounds.average_size() >= SOLID_MIN_AVERAGE_SIZE
            or bounds.size().y >= SOLID_MIN_HEIGHT
        )

    def is_replaceable(self, state: Union[BlockStateId, int, BlockState, str]) -> bool:
        """``LevelFacts::is_replaceable`` (level/mod.rs:881, флаг REPLACEABLE).

        ``# FALLBACK: block_properties pending`` — флаг ``replaceable``
        приходит из block_properties.nbt.
        """
        return self.state_name(state) in REPLACEABLE_NAMES

    # -- canBeReplaced (level/place.rs:194) --

    def can_be_replaced(
        self,
        state: Union[BlockStateId, int, BlockState, str],
        ctx: Optional[PlacementContext] = None,
    ) -> bool:
        """``BlockState.canBeReplaced(BlockPlaceContext)`` (place.rs:194).

        Без контекста — только свойство ``replaceable``. С контекстом —
        ванильное правило «не заменять блок предметом того же блока».
        Специальные классы (Slab, SnowLayer, Multiface, ...) не портированы:
        они требуют ``Behaviours``/``data::ItemKind`` следующих сессий.
        """
        if ctx is None:
            return self.is_replaceable(state)
        if not self.is_replaceable(state):
            return False
        if not ctx.item:
            return True
        return ctx.item != self.state_name(state)

    # -- canSurvive (block_survival.rs:640) --

    def can_survive(
        self,
        world: PlacementWorld,
        state: Union[BlockStateId, int, BlockState, str],
        position: Tuple[int, int, int],
        ctx: Optional[PlacementContext] = None,
    ) -> bool:
        """``BlockState.canSurvive`` (block_survival.rs:640).

        Полный порт правил живёт в :mod:`quadrix.world.block_survival`
        (``BlockSurvivalRegistry``): Fire/Cactus/Path/Mushroom/Multiface/
        Support/... — по одной записи ``survival-rules.json`` на состояние.
        """
        del ctx  # контекст полному правилу не нужен
        from quadrix.world.block_survival import default_survival

        return default_survival().can_survive(world, state, position)

    # -- getStateForPlacement (level/place.rs) --

    def placement_state(
        self,
        item_stack: Union[ItemStack, str],
        ctx: Optional[PlacementContext] = None,
    ) -> Optional[BlockStateId]:
        """``Behaviours::placement_state`` (place.rs:1777).

        ``None`` — предмет не блок или блок неизвестен реестру. Для блоковых
        предметов id предмета совпадает с именем блока (ванильная конвенция),
        поэтому состояние берётся как default этого блока и уточняется по
        контексту: ``axis`` (логи/столбы), ``facing``/``half`` (ступени,
        печи), ``rotation`` (таблички), ``waterlogged``.
        """
        item = item_stack.item if isinstance(item_stack, ItemStack) else str(item_stack)
        if not item or item == "minecraft:air":
            return None
        default = self.registry.default_state(item)
        if default is None:
            return None
        if ctx is None:
            return default

        base = self.registry.state(default)
        if base is None:
            return default
        props = base.properties.properties
        updates: Dict[str, str] = {}

        if "axis" in props:
            updates["axis"] = _axis_name(ctx.face)
        elif "facing" in props:
            updates["facing"] = ctx.horizontal_direction().opposite().name.lower()
            if "half" in props:
                updates["half"] = "bottom" if ctx.half_from_click() else "top"
        if "rotation" in props:
            updates["rotation"] = str(rotation_segment(ctx.yaw))
        if "waterlogged" in props:
            updates["waterlogged"] = "false"

        if not updates:
            return default
        return self._resolve(base, updates)

    def _resolve(self, state: BlockState, updates: Dict[str, str]) -> Optional[BlockStateId]:
        """Слить свойства ``updates`` в ``state`` и вернуть id (иначе default)."""
        merged = dict(state.properties.properties)
        merged.update(updates)
        candidate = BlockState(name=state.name, properties=BlockProperties(merged))
        found = self.registry.id(candidate)
        if found is not None:
            return found
        return self.registry.default_state(state.name)

    # -- установка --

    def can_place(
        self,
        world: PlacementWorld,
        state: Union[BlockStateId, int, BlockState, str],
        position: Tuple[int, int, int],
        ctx: Optional[PlacementContext] = None,
    ) -> bool:
        """Можно ли поставить ``state`` в ``position``.

        Порядок как у ``BlockItem.place`` (place.rs:1744):
        1. цель должна быть заменяемой (иначе позиция занята);
        2. блок должен выжить (``can_survive`` — опора снизу);
        3. нельзя ставить воздух.
        Проверка перекрытия сущностями (``unobstructed_block``) сюда не входит:
        в клиенте сущностей рядом с точкой установки нет.
        """
        if self.is_air(state):
            return False
        target = world.get_block(position)
        if not self.can_be_replaced(target, ctx):
            return False
        if not self.can_survive(world, state, position, ctx):
            return False
        return True

    def place(
        self,
        world: PlacementWorld,
        position: Tuple[int, int, int],
        state: Union[BlockStateId, int, BlockState, str],
        flags: int = 11,
    ) -> bool:
        """Записать блок в мир (``Level.setBlock``; ванильные флаги — 11)."""
        state_id = self._as_state_id(state)
        if state_id is None:
            return False
        return bool(world.set_block(position, state_id, flags))

    def _as_state_id(self, state: Union[BlockStateId, int, BlockState, str]) -> Optional[BlockStateId]:
        if isinstance(state, BlockStateId):
            return state
        if isinstance(state, int):
            return BlockStateId(state)
        return self.registry.default_state(self.state_name(state))


def _axis_name(face: Direction) -> str:
    """``Direction.getAxis()`` для свойства ``axis`` (логи/столбы)."""
    if face in (Direction.UP, Direction.DOWN):
        return "y"
    if face in (Direction.EAST, Direction.WEST):
        return "x"
    return "z"


# ---------------------------------------------------------------------------
# Реестр и BlockPlacement по умолчанию (.local зафиксирован AGENTS.md)
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / ".local"
    / "horizon-client-motion"
    / "block-registry.nbt"
)

_DEFAULT_REGISTRY: Optional[BlockRegistry] = None
_DEFAULT_PLACEMENT: Optional[BlockPlacement] = None


def default_registry() -> BlockRegistry:
    """Ленивая загрузка ``block-registry.nbt`` из ``.local``."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        LOG.debug("[QuadRix] load block registry: %s", _DEFAULT_REGISTRY_PATH)
        _DEFAULT_REGISTRY = BlockRegistry.load(_DEFAULT_REGISTRY_PATH)
    return _DEFAULT_REGISTRY


def default_placement() -> BlockPlacement:
    """``BlockPlacement`` на реестре по умолчанию (и кэше столкновений)."""
    global _DEFAULT_PLACEMENT
    if _DEFAULT_PLACEMENT is None:
        registry = default_registry()
        _DEFAULT_PLACEMENT = BlockPlacement(
            registry, collision=default_collision_registry(registry)
        )
    return _DEFAULT_PLACEMENT


# ---------------------------------------------------------------------------
# Модульные функции (запрошенный клиентский API)
# ---------------------------------------------------------------------------

def _active_placement(
    registry: Optional[BlockRegistry],
    placement: Optional[BlockPlacement],
) -> BlockPlacement:
    """Выбрать ``BlockPlacement``: явный, по реестру или реестр ``.local``."""
    if placement is not None:
        return placement
    if registry is not None:
        return BlockPlacement(registry)
    return default_placement()


def is_air(
    state: Union[BlockStateId, int, BlockState, str],
    registry: Optional[BlockRegistry] = None,
    placement: Optional[BlockPlacement] = None,
) -> bool:
    """``is_air`` для состояния (см. ``BlockPlacement.is_air``)."""
    return _active_placement(registry, placement).is_air(state)


def is_solid(
    state: Union[BlockStateId, int, BlockState, str],
    registry: Optional[BlockRegistry] = None,
    placement: Optional[BlockPlacement] = None,
) -> bool:
    """``is_solid`` для состояния (см. ``BlockPlacement.is_solid``)."""
    return _active_placement(registry, placement).is_solid(state)


def is_replaceable(
    state: Union[BlockStateId, int, BlockState, str],
    registry: Optional[BlockRegistry] = None,
    placement: Optional[BlockPlacement] = None,
) -> bool:
    """``is_replaceable`` (трава/снег/вода/воздух — да; камень — нет)."""
    return _active_placement(registry, placement).is_replaceable(state)


def can_place_block(
    world: PlacementWorld,
    state: Union[BlockStateId, int, BlockState, str],
    position: Tuple[int, int, int],
    context: Optional[PlacementContext] = None,
    placement: Optional[BlockPlacement] = None,
) -> bool:
    """Можно ли поставить ``state`` в ``position`` мира ``world``.

    ``placement`` (реестр) можно передать явно; иначе берётся реестр ``.local``.
    """
    active = placement if placement is not None else default_placement()
    return active.can_place(world, state, (position[0], position[1], position[2]), context)


def get_placement_state(
    item_stack: Union[ItemStack, str],
    context: Optional[PlacementContext] = None,
    registry: Optional[BlockRegistry] = None,
    placement: Optional[BlockPlacement] = None,
) -> Optional[BlockStateId]:
    """Какое состояние поставить предметом (``getStateForPlacement``)."""
    if placement is None:
        active = BlockPlacement(registry) if registry is not None else default_placement()
    else:
        active = placement
    return active.placement_state(item_stack, context)
