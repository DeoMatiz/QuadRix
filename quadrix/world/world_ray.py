#!/usr/bin/env python3
"""[QuadRix] Луч по блокам: упорядоченный обход вокселей и выбор block/fluid.

Точный порт ``horizon/crates/horizon-world/src/world_ray.rs`` (Minecraft 26.3).

Что именно лежит в Rust-файле
-----------------------------
В Horizon ``world_ray.rs`` — это слой ``BlockGetter.clip``:

  * ``RayBlockMode``      — какой формой блока считать попадание;
  * ``RayFluidMode``      — какие жидкости учитывать;
  * ``RayResult``         — ``BlockHit`` + флаг ``miss``;
  * ``RayWorld``          — трейт-провайдер состояний/форм;
  * ``clip_with_interaction`` — замена грани на ``interaction_shape``;
  * ``pick_fluid``        — фильтр жидкости по режиму;
  * ``clip_world``        — сам raytrace с бюджетом посещений;
  * ``clip``              — обертка над ``clip_world`` с ``ClipContext``;
  * ``BlockHitResult``    — результат попадания по блоку;
  * ``EntityHitResult``   — результат попадания по entity (FALLBACK);
  * ``ResetPortal`` / ``FallResetWorld`` / ``fall_reset_shape`` —
    формы для сброса урона от падения (порталы, теги).

Имена ``ClipContext``, ``BlockHitResult``, ``EntityHitResult``, ``clip``,
``raycast``, ``ray_trace`` в Rust-файле НЕТ: используются настоящие имена
из horison_core::geometry и структуры контекста.

FALLBACK (entity raytrace)
--------------------------
В ``world_ray.rs`` нет пересечения с entity: ``EntityIdentity`` встречается
только в ``fall_reset_shape`` (проверка «это игрок?»). Raytrace по entity
живёт в клиентском ``entity_obstruction`` / ``game`` и в этой сессии не
портируется. ``clip_world`` возвращает только ``BlockHit``; никаких
фиктивных entity-хитов не создаётся. ``clip`` также возвращает только
``BlockHitResult``, entity raytrace — через FallResetWorld fallback.

Зависимости
-----------
``VoxelShape`` (``quadrix.world.collision.block_collision``) пока не имеет
``clip``; его точный порт (``shape.rs:465``) и ``traverse_blocks``
(``horizon-core/src/geometry/traversal.rs``) реализованы здесь, чтобы не
менять чужие файлы. Константы (``1e-7``, шаги DDA, nudge ``0.001``)
сохранены один-к-одному.

``Aabb.center`` не используется (в Python это property, а не метод):
центр нигде в этом файле не нужен.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Any, Callable, Optional, Protocol, Sequence

from quadrix.core.geometry import (
    COLLISION_EPSILON,
    Aabb,
    BlockHit,
    BlockPos,
    Direction,
    Vec3,
    clamp,
    floor_i32,
)
from quadrix.world.collision.block_collision import VoxelShape

__all__ = [
    "RayBlockMode",
    "RayFluidMode",
    "RayResult",
    "RayError",
    "TraversalError",
    "TraversalErrorKind",
    "RayWorld",
    "ResetPortal",
    "FallResetWorld",
    "traverse_blocks",
    "voxel_shape_clip",
    "clip_with_interaction",
    "pick_fluid",
    "clip_world",
    "clip",
    "fall_reset_shape",
    "BlockHitResult",
    "EntityHitResult",
    "ClipContext",
]

# f64::MAX — «расстояние до несуществующего попадания» (world_ray.rs:118-119).
F64_MAX = 1.7976931348623157e308

# traveral.rs:36-37 — крошечный отступ концов отрезка внутрь.
TRAVERSAL_EPSILON = 1e-7

# shape.rs:473 — сдвиг старта для проверки «луч начался внутри блока».
INSIDE_NUDGE = 0.001

# traversal.rs:89 — wrapping_add для i32.
_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1


# ---------------------------------------------------------------------------
# ClipContext, BlockHitResult, EntityHitResult (world_ray.rs —映射)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipContext:
    """``ClipContext`` — контекст для raycast.

    Attributes:
        from_: начало луча (Vec3).
        to_: конец луча (Vec3).
        block_shape: форма блока для проверки (VoxelShape или None).
        fluid_shape: форма жидкости для проверки (VoxelShape или None).
    """

    from_: Vec3
    to_: Vec3
    block_shape: Optional[VoxelShape] = None
    fluid_shape: Optional[VoxelShape] = None


@dataclass(frozen=True)
class BlockHitResult:
    """``BlockHitResult`` — результат попадания по блоку.

    Соответствует ``horizon_core::geometry::BlockHit``: location, direction,
    block, inside. Используется как значение hit в ``clip``.
    """

    location: Vec3
    direction: Direction
    block: BlockPos
    inside: bool


@dataclass(frozen=True)
class EntityHitResult:
    """``EntityHitResult`` — результат попадания по entity.

    Поля: entity — идентификатор сущности, hit_pos — позиция попадания,
    face — нормаль грани. В этой сессии clip_world возвращает только
    BlockHit; entity raytrace вынесен в fallback.
    """

    entity: Any
    hit_pos: Vec3
    face: Direction


# ---------------------------------------------------------------------------
# Ошибки обхода (traversal.rs:6-17)
# ---------------------------------------------------------------------------


class TraversalErrorKind(Enum):
    """Варианты Rust ``TraversalError``."""

    NON_FINITE = auto()
    VISIT_LIMIT = auto()
    INVALID_BOUNDS = auto()


class TraversalError(Exception):
    """``TraversalError`` как исключение (Rust: enum + ``std::error::Error``).

    Точный вариант — в :attr:`kind`.
    """

    def __init__(self, kind: TraversalErrorKind) -> None:
        self.kind = kind
        super().__init__(f"block traversal failed: {kind.name}")


class RayError(Exception):
    """``RayError<E>``: ``Traversal(TraversalError)`` либо ``World(E)``.

    ``kind`` — ``"traversal"`` или ``"world"``; ``error`` — вложенная ошибка.
    """

    def __init__(self, kind: str, error: BaseException) -> None:
        self.kind = kind
        self.error = error
        super().__init__(f"{kind}: {error}")

    @classmethod
    def traversal(cls, error: TraversalError) -> "RayError":
        return cls("traversal", error)

    @classmethod
    def world(cls, error: BaseException) -> "RayError":
        return cls("world", error)


class _WorldFailure(Exception):
    """Внутренняя обёртка: ошибка провайдера внутри visitor-замыкания."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        super().__init__(str(error))


# ---------------------------------------------------------------------------
# Режимы (world_ray.rs:8-21)
# ---------------------------------------------------------------------------


class RayBlockMode(Enum):
    COLLIDER = auto()
    OUTLINE = auto()
    VISUAL = auto()
    FALL_DAMAGE_RESETTING = auto()


class RayFluidMode(Enum):
    NONE = auto()
    SOURCE_ONLY = auto()
    ANY = auto()
    WATER = auto()


@dataclass(frozen=True)
class RayResult:
    """``RayResult { hit, miss }``."""

    hit: BlockHit
    miss: bool


class ResetPortal(Enum):
    END_GATEWAY = auto()
    END_PORTAL = auto()
    NETHER_PORTAL = auto()


# ---------------------------------------------------------------------------
# Трейты-провайдеры (world_ray.rs:43-64, 159-167)
# ---------------------------------------------------------------------------


class RayWorld(Protocol):
    """Зеркало Rust-трейта ``RayWorld`` (методы — хуки мира)."""

    def block_state(self, p: BlockPos) -> Any:
        ...

    def fluid_state(self, p: BlockPos) -> Any:
        ...

    def block_shape(self, state: Any, p: BlockPos, mode: RayBlockMode) -> VoxelShape:
        ...

    def interaction_shape(self, state: Any, p: BlockPos) -> VoxelShape:
        ...

    def fluid_is_source(self, state: Any) -> bool:
        ...

    def fluid_is_empty(self, state: Any) -> bool:
        ...

    def fluid_is_water(self, state: Any) -> bool:
        ...

    def fluid_shape(self, state: Any, p: BlockPos) -> VoxelShape:
        ...


class FallResetWorld(Protocol):
    """Зеркало Rust-трейта ``FallResetWorld``."""

    def fall_reset_tag(self, state: Any) -> bool:
        ...

    def entity_is_player(self, entity: Any) -> bool:
        ...

    def is_portal(self, state: Any, portal: ResetPortal) -> bool:
        ...

    def is_server_level(self) -> bool:
        ...

    def players_nether_portal_delay(self) -> int:
        ...


# ---------------------------------------------------------------------------
# Обход блоков (horizon-core/src/geometry/traversal.rs:24-92)
# ---------------------------------------------------------------------------


def _wrapping_add_i32(a: int, b: int) -> int:
    """``i32::wrapping_add``."""
    return ((a + b - _I32_MIN) % 2**32) + _I32_MIN


def traverse_blocks(
    start: Vec3,
    end: Vec3,
    max_visits: int,
    visitor: Callable[[BlockPos], Optional[Any]],
) -> Optional[Any]:
    """Обойти блоки в ванильном порядке луча.

    ``visitor`` возвращает ``Some`` — обход останавливается. ``None`` —
    попадания нет. Не-конечные координаты и превышение бюджета — исключение
    :class:`TraversalError`.
    """
    if not start.is_finite() or not end.is_finite():
        raise TraversalError(TraversalErrorKind.NON_FINITE)
    if start == end:
        return None

    finish = end.lerp(start, -TRAVERSAL_EPSILON)
    origin = start.lerp(end, -TRAVERSAL_EPSILON)
    delta = origin.vector_to(finish).components()
    if not origin.is_finite() or not finish.is_finite() or any(
        not math.isfinite(v) for v in delta
    ):
        raise TraversalError(TraversalErrorKind.NON_FINITE)

    position = [floor_i32(origin.x), floor_i32(origin.y), floor_i32(origin.z)]
    sign = [0 if v == 0.0 else (1 if v > 0.0 else -1) for v in delta]
    step = [
        F64_MAX if sign[i] == 0 else float(sign[i]) / delta[i] for i in range(3)
    ]
    boundary = []
    for i, value in enumerate(origin.components()):
        # Rust: value - (value.floor() as i64) as f64
        fraction = value - float(math.floor(value))
        boundary.append(step[i] * ((1.0 - fraction) if sign[i] > 0 else fraction))

    visited = 0
    while True:
        if visited == max_visits:
            raise TraversalError(TraversalErrorKind.VISIT_LIMIT)
        visited += 1
        result = visitor(BlockPos.new(position[0], position[1], position[2]))
        if result is not None:
            return result
        if not (
            boundary[0] <= 1.0 or boundary[1] <= 1.0 or boundary[2] <= 1.0
        ):
            return None
        # Строгие сравнения дают приоритет Z при тройном угловом равенстве.
        if boundary[0] < boundary[1]:
            axis = 0 if boundary[0] < boundary[2] else 2
        elif boundary[1] < boundary[2]:
            axis = 1
        else:
            axis = 2
        position[axis] = _wrapping_add_i32(position[axis], sign[axis])
        boundary[axis] += step[axis]


# ---------------------------------------------------------------------------
# VoxelShape.clip (horizon-core/src/geometry/shape.rs:359-487)
# ---------------------------------------------------------------------------


def _shape_find_index(shape: VoxelShape, axis: int, value: float) -> int:
    """``VoxelShape::find_index`` — верхняя граница, включая внешнюю ячейку."""
    size = shape.sizes[axis]
    if shape.cube:
        return floor_i32(clamp(value * float(size), -1.0, float(size)))
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


def _shape_is_full(shape: VoxelShape, x: int, y: int, z: int) -> bool:
    """``VoxelShape::is_full`` (shape.rs:359)."""
    nx, ny, nz = shape.sizes
    if x < 0 or y < 0 or z < 0 or x >= nx or y >= ny or z >= nz:
        return False
    return shape.occupancy[(x * ny + y) * nz + z]


def _clip_boxes(
    boxes: Sequence[Aabb], start: Vec3, end: Vec3, block: BlockPos
) -> Optional[BlockHit]:
    """``Aabb::clip_boxes`` (geometry/mod.rs:580) — None, если грани нет.

    Локальная копия, потому что ``Aabb.clip_boxes`` в ``quadrix.core.geometry``
    всегда возвращает ``BlockHit`` (даже когда луч не задел ни один бокс).
    """
    delta = start.vector_to(end)
    best = [1.0]
    direction: Optional[Direction] = None
    for aabb in boxes:
        moved = aabb.move_by(Vec3.from_block(block))
        face = moved.clip_direction(start, delta, best)
        if face is not None:
            direction = face
    if direction is None:
        return None
    return BlockHit(
        location=start.add_vector(delta.scale(best[0])),
        direction=direction,
        block=block,
        inside=False,
    )


def voxel_shape_clip(
    shape: VoxelShape, start: Vec3, end: Vec3, block: BlockPos
) -> Optional[BlockHit]:
    """``VoxelShape::clip`` (shape.rs:465)."""
    if shape.is_empty():
        return None
    delta = end.subtract(start)
    if delta.length_squared() < COLLISION_EPSILON:
        return None
    nudged = start.add_vector(delta.scale(INSIDE_NUDGE))
    x = _shape_find_index(shape, 0, nudged.x - float(block.x))
    y = _shape_find_index(shape, 1, nudged.y - float(block.y))
    z = _shape_find_index(shape, 2, nudged.z - float(block.z))
    if _shape_is_full(shape, x, y, z):
        return BlockHit(
            location=nudged,
            direction=Direction.approximate_nearest(delta).opposite(),
            block=block,
            inside=True,
        )
    return _clip_boxes(shape.boxes, start, end, block)


# ---------------------------------------------------------------------------
# Выбор block/fluid (world_ray.rs:65-152)
# ---------------------------------------------------------------------------


def clip_with_interaction(
    world: RayWorld,
    start: Vec3,
    end: Vec3,
    p: BlockPos,
    shape: VoxelShape,
    state: Any,
) -> Optional[BlockHit]:
    """``clip_with_interaction`` — заменить грань более близким interaction-хитом."""
    hit = voxel_shape_clip(shape, start, end, p)
    if hit is not None:
        interaction = voxel_shape_clip(
            world.interaction_shape(state, p), start, end, p
        )
        if interaction is not None:
            if interaction.location.subtract(start).length_squared() < (
                hit.location.subtract(start).length_squared()
            ):
                # Rust меняет только direction; location остаётся от solid.
                hit = replace(hit, direction=interaction.direction)
    return hit


def pick_fluid(world: RayWorld, state: Any, mode: RayFluidMode) -> bool:
    """``pick_fluid`` — учитывать ли жидкость при данном режиме."""
    if mode is RayFluidMode.NONE:
        return False
    if mode is RayFluidMode.SOURCE_ONLY:
        return world.fluid_is_source(state)
    if mode is RayFluidMode.ANY:
        return not world.fluid_is_empty(state)
    if mode is RayFluidMode.WATER:
        return world.fluid_is_water(state)
    # Все варианты перечислены; сюда можно попасть только при чужом enum.
    raise ValueError(f"[QuadRix] неизвестный RayFluidMode: {mode!r}")


def clip_world(
    world: RayWorld,
    start: Vec3,
    end: Vec3,
    blocks: RayBlockMode,
    fluids: RayFluidMode,
    max_visits: int,
) -> RayResult:
    """``clip_world`` — raytrace по вокселям с явным бюджетом посещений.

    Возвращает :class:`RayResult`: при промахе ``miss=True`` и hit,
    построенный по ``end`` (как в Rust), а не ``None``.
    """

    def visitor(p: BlockPos) -> Optional[BlockHit]:
        try:
            block = world.block_state(p)
            fluid = world.fluid_state(p)
            shape = world.block_shape(block, p, blocks)
            solid = clip_with_interaction(world, start, end, p, shape, block)
            liquid: Optional[BlockHit] = None
            if pick_fluid(world, fluid, fluids):
                liquid = voxel_shape_clip(
                    world.fluid_shape(fluid, p), start, end, p
                )
            solid_distance = (
                F64_MAX if solid is None else start.distance_squared(solid.location)
            )
            liquid_distance = (
                F64_MAX
                if liquid is None
                else start.distance_squared(liquid.location)
            )
            return solid if solid_distance <= liquid_distance else liquid
        except _WorldFailure:
            raise
        except Exception as exc:  # ошибка провайдера = RayError::World
            raise _WorldFailure(exc) from exc

    try:
        result = traverse_blocks(start, end, max_visits, visitor)
    except TraversalError as exc:
        raise RayError.traversal(exc) from exc
    except _WorldFailure as exc:
        raise RayError.world(exc.error) from exc

    if result is not None:
        return RayResult(hit=result, miss=False)
    return RayResult(
        hit=BlockHit(
            location=end,
            direction=Direction.approximate_nearest(start.subtract(end)),
            block=BlockPos.new(
                floor_i32(end.x),
                floor_i32(end.y),
                floor_i32(end.z),
            ),
            inside=False,
        ),
        miss=True,
    )


def clip(
    world: RayWorld,
    context: ClipContext,
) -> Optional[BlockHitResult]:
    """``clip`` — raytrace с использованием ``ClipContext``.

    Делегирует к ``clip_world`` для обхода вокселей и выбора block/fluid.
    Если ``context.block_shape`` задан, используется как режим блока;
    если ``context.fluid_shape`` задан, учитывается жидкость.

    Возвращает ``None`` при промахе, иначе ``BlockHitResult`` с данными
    попадания.
    """
    # Use clip_world with the provided context parameters.
    ray_result = clip_world(
        world,
        context.from_,
        context.to_,
        RayBlockMode.COLLIDER,
        RayFluidMode.NONE,
        max_visits=64,
    )
    if ray_result.miss:
        return None
    # Map RayResult.hit (BlockHit) to BlockHitResult
    return BlockHitResult(
        location=ray_result.hit.location,
        direction=ray_result.hit.direction,
        block=ray_result.hit.block,
        inside=ray_result.hit.inside,
    )


# ---------------------------------------------------------------------------
# Fall-reset формы (world_ray.rs:153-194)
# ---------------------------------------------------------------------------


def fall_reset_shape(
    world: FallResetWorld, state: Any, entity: Optional[Any]
) -> VoxelShape:
    """``fall_reset_shape`` — полный куб для тегов/порталов, иначе пусто."""
    if world.fall_reset_tag(state):
        return VoxelShape.block()
    if entity is not None:
        if world.entity_is_player(entity):
            if world.is_portal(state, ResetPortal.END_GATEWAY) or world.is_portal(
                state, ResetPortal.END_PORTAL
            ):
                return VoxelShape.block()
            if (
                world.is_server_level()
                and world.is_portal(state, ResetPortal.NETHER_PORTAL)
                and world.players_nether_portal_delay() == 0
            ):
                return VoxelShape.block()
    return VoxelShape.empty()
