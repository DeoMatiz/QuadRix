#!/usr/bin/env python3
"""Точный sweep Aabb по формам столкновений блоков (VoxelShape).

Порт логики сущностного столкновения из:

  * ``horizon/crates/horizon-world/src/entity_collision.rs`` — отбор форм;
  * ``horizon/crates/horizon-world/src/world_movement.rs`` — порядок обхода
    мира и границы запроса;
  * ``horizon-core/src/geometry/movement.rs`` — порядок осей Y, X/Z и
    ``resolve_shape_movement``;
  * ``horizon-core/src/geometry/shape.rs`` — ``VoxelShape::collide`` /
    ``collide_all``;
  * ``horizon-world/src/block_collision_scan.rs`` — обход ячеек мира.

Здесь нет entity-vs-entity (это отдельный слой) и нет projectile collision
(``arrows.rs``). Формы блоков берутся только через
:func:`quadrix.world.collision.block_collision.block_collision_boxes`, поэтому
плита, ступени, забор и прочие неполные кубы обрезают движение по своей
настоящей VoxelShape, а не как полный куб.

Мир должен предоставить:

  * ``registry`` — :class:`quadrix.world.registry.BlockRegistry`;
  * ``block_state(x, y, z) -> BlockStateId | int | None`` **или**
    ``block(x, y, z) -> str`` (имя блока, как в ``motion/core.py``).

Необязательный ``cached_collision`` (CachedCollisionRegistry) на мире
позволяет не разбирать ``cached-collision.nbt`` повторно.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from quadrix.core.geometry import (
    Aabb,
    Axis,
    BlockPos,
    Vec3,
)
from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    block_collision_boxes,
)
from quadrix.world.registry import BlockRegistry, BlockStateId

__all__ = [
    "COLLISION_EPSILON",
    "DEGENERATE_SIZE",
    "SCAN_PADDING",
    "DEFAULT_CANDIDATE_BUDGET",
    "entity_collision_bounds",
    "collect_collision_boxes",
    "resolve_shape_movement",
    "collide_aabb",
    "sweep",
    "clip_movement",
]

# entity_collision.rs:54 — зазор запроса форм (inflate на 1e-7).
COLLISION_EPSILON: float = 1.0e-7

# entity_collision.rs:51 — средний размер, ниже которого форма пустая.
DEGENERATE_SIZE: float = 1.0e-7

# block_collision_scan.rs:115-118 — содержащая ячейка плюс один слой запаса.
SCAN_PADDING: int = 1

# world_movement.rs / motion.rs — бюджет ячеек одного запроса.
DEFAULT_CANDIDATE_BUDGET: int = 1_000_000


# ---------------------------------------------------------------------------
# Доступ к миру
# ---------------------------------------------------------------------------

def _world_registry(world: object) -> BlockRegistry:
    """Вернуть BlockRegistry мира.

    В Rust реестр приходит отдельным параметром ``CachedCollisionRegistry``;
    в Python-мире он лежит на самом мире.
    """
    for attribute in ("registry", "block_registry"):
        registry = getattr(world, attribute, None)
        if isinstance(registry, BlockRegistry):
            return registry
    raise ValueError(
        "entity_collision: у мира нет BlockRegistry (registry/block_registry)"
    )


def _world_cached_collision(
    world: object, registry: BlockRegistry
) -> Optional[CachedCollisionRegistry]:
    """Кэш форм, если мир его уже загрузил."""
    for attribute in ("cached_collision", "collision_registry"):
        cached = getattr(world, attribute, None)
        if isinstance(cached, CachedCollisionRegistry):
            return cached
    return None


def _as_state_id(value: object) -> Optional[BlockStateId]:
    """Привести ответ мира к BlockStateId; None — воздуха нет."""
    if value is None:
        return None
    if isinstance(value, BlockStateId):
        return value
    if isinstance(value, bool):
        # bool — это int, но состоянием блока он быть не может.
        return None
    if isinstance(value, int):
        return BlockStateId(value)
    return None


def _block_state_at(
    world: object, registry: BlockRegistry, x: int, y: int, z: int
) -> Optional[BlockStateId]:
    """Состояние блока в позиции.

    Сначала ``block_state`` (настоящий id), затем ``block`` (имя, как в
    ``motion/core.py::move_entity``).
    """
    getter = getattr(world, "block_state", None)
    if callable(getter):
        state = _as_state_id(getter(x, y, z))
        if state is not None:
            return state

    getter = getattr(world, "block", None)
    if callable(getter):
        value = getter(x, y, z)
        state = _as_state_id(value)
        if state is not None:
            return state
        if isinstance(value, str):
            # default_state — блок без свойств, как BlockState в ваниле.
            return registry.default_state(value)
        if value is None:
            return None
        raise ValueError(
            f"entity_collision: неподдерживаемый блок {value!r} "
            f"в ({x}, {y}, {z})"
        )

    raise ValueError(
        "entity_collision: мир не умеет block_state(x,y,z) или block(x,y,z)"
    )


# ---------------------------------------------------------------------------
# Геометрические помощники
# ---------------------------------------------------------------------------

def _expand_towards(bounds: Aabb, amount: Vec3) -> Aabb:
    """Aabb::expand_towards (geometry/mod.rs) без правки общего geometry.py.

    В текущем ``Aabb.change_extent`` ``components()`` возвращает tuple, поэтому
    расширение делаем локально: отрицательная компонента двигает min, положи-
    тельная — max.
    """
    minimum = list(bounds.min.components())
    maximum = list(bounds.max.components())
    for i, value in enumerate(amount.components()):
        if value < 0.0:
            minimum[i] += value
        elif value > 0.0:
            maximum[i] += value
    return Aabb.new(
        Vec3(minimum[0], minimum[1], minimum[2]),
        Vec3(maximum[0], maximum[1], maximum[2]),
    )


# ---------------------------------------------------------------------------
# Обход ячеек мира
# ---------------------------------------------------------------------------

def _cell_range(bounds: Aabb) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Диапазон блоков, которые может задеть *bounds* (block_collision_scan.rs:109)."""
    minimum = bounds.min
    maximum = bounds.max
    if not (
        math.isfinite(minimum.x)
        and math.isfinite(minimum.y)
        and math.isfinite(minimum.z)
        and math.isfinite(maximum.x)
        and math.isfinite(maximum.y)
        and math.isfinite(maximum.z)
    ):
        raise ValueError("collision scan bounds must be finite")

    # BlockPos::containing(x) = floor(x), плюс слой запаса с каждой стороны.
    start = BlockPos(
        math.floor(minimum.x - COLLISION_EPSILON) - SCAN_PADDING,
        math.floor(minimum.y - COLLISION_EPSILON) - SCAN_PADDING,
        math.floor(minimum.z - COLLISION_EPSILON) - SCAN_PADDING,
    )
    end = BlockPos(
        math.floor(maximum.x + COLLISION_EPSILON) + SCAN_PADDING,
        math.floor(maximum.y + COLLISION_EPSILON) + SCAN_PADDING,
        math.floor(maximum.z + COLLISION_EPSILON) + SCAN_PADDING,
    )
    return (
        (start.x, start.y, start.z),
        (end.x, end.y, end.z),
    )


def collect_collision_boxes(
    world: object,
    bounds: Aabb,
    cached: Optional[CachedCollisionRegistry] = None,
) -> List[Aabb]:
    """Собрать мировые Aabb всех форм, пересекающих *bounds*.

    Это ``BlockCollisionScan`` без контекстов жидкостей: для каждого состояния
    вызывается :func:`block_collision_boxes`, боксы сдвигаются на координаты
    блока и фильтруются по пересечению с запросом.
    """
    registry = _world_registry(world)
    if cached is None:
        cached = _world_cached_collision(world, registry)

    (min_x, min_y, min_z), (max_x, max_y, max_z) = _cell_range(bounds)
    widths = (max_x - min_x + 1, max_y - min_y + 1, max_z - min_z + 1)
    if any(width <= 0 for width in widths):
        raise ValueError("collision scan exceeds the cursor domain")
    cells = widths[0] * widths[1] * widths[2]
    if cells > DEFAULT_CANDIDATE_BUDGET:
        raise ValueError("collision scan candidate budget exhausted")

    boxes: List[Aabb] = []
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                state = _block_state_at(world, registry, x, y, z)
                if state is None:
                    continue
                local_boxes = block_collision_boxes(registry, state, cached)
                if not local_boxes:
                    continue
                offset = Vec3(float(x), float(y), float(z))
                for box in local_boxes:
                    moved = box.move_by(offset)
                    # Форма, не пересекающая запрос, ничего не обрезает.
                    if moved.intersects(bounds):
                        boxes.append(moved)
    return boxes


# ---------------------------------------------------------------------------
# Разрешение движения по осям (geometry/movement.rs:100-126)
# ---------------------------------------------------------------------------

def _overlaps_other_axes(aabb: Aabb, box: Aabb, other: int) -> bool:
    """Пересечение по *other* с зазором COLLISION_EPSILON (shape.rs:407-412)."""
    a_min = aabb.min.components()[other] + COLLISION_EPSILON
    a_max = aabb.max.components()[other] - COLLISION_EPSILON
    b_min = box.min.components()[other]
    b_max = box.max.components()[other]
    return a_min < b_max and a_max > b_min


def _collide_axis(
    axis: int, aabb: Aabb, boxes: Sequence[Aabb], amount: float
) -> float:
    """``VoxelShape::collide_all`` для одной оси (shape.rs:451-464).

    *axis* — индекс 0/1/2. Возвращает допустимое смещение: при движении в
    плюс — расстояние до ближайшей грани, при движении в минус — до обратной.
    """
    if abs(amount) < COLLISION_EPSILON:
        return 0.0

    p = (axis + 1) % 3
    q = (axis + 2) % 3
    for box in boxes:
        if abs(amount) < COLLISION_EPSILON:
            return 0.0
        if not _overlaps_other_axes(aabb, box, p):
            continue
        if not _overlaps_other_axes(aabb, box, q):
            continue

        a_min = aabb.min.components()[axis]
        a_max = aabb.max.components()[axis]
        b_min = box.min.components()[axis]
        b_max = box.max.components()[axis]

        if amount > 0.0:
            # shape.rs:428 — расстояние от текущей дальней грани до слоя.
            distance = b_min - a_max
            if distance >= -COLLISION_EPSILON:
                amount = min(amount, distance)
        elif amount < 0.0:
            # shape.rs:440 — расстояние от текущей ближней грани до слоя.
            distance = b_max - a_min
            if distance <= COLLISION_EPSILON:
                amount = max(amount, distance)
    return amount


def resolve_shape_movement(
    movement: Vec3, bounds: Aabb, boxes: Sequence[Aabb]
) -> Vec3:
    """Разрешить движение по уже собранным формам.

    Точный порядок ``Entity.collide``: сначала Y, затем ось с большей
    горизонтальной составляющей (``Axis::step_order``), каждая следующая ось
    считается от уже сдвинутого Aabb.
    """
    if not boxes:
        return movement

    result = [0.0, 0.0, 0.0]
    for axis in Axis.step_order(movement):
        amount = movement.component(axis)
        if amount == 0.0:
            continue
        moved = bounds.move_by(Vec3(result[0], result[1], result[2]))
        result[axis.value] = _collide_axis(
            axis.value, moved, boxes, amount
        )
    return Vec3(result[0], result[1], result[2])


# ---------------------------------------------------------------------------
# Публичное API
# ---------------------------------------------------------------------------

def entity_collision_bounds(
    movement: Vec3, bounds: Aabb, max_step: float
) -> Aabb:
    """Границы одного запроса ``Entity.collide`` (movement.rs:20-23)."""
    return _expand_towards(
        _expand_towards(bounds, movement),
        Vec3(0.0, float(max_step), 0.0),
    )


def collide_aabb(world: object, bounds: Aabb, velocity: Vec3) -> Vec3:
    """Сдвинуть *bounds* на *velocity* с учётом VoxelShape блоков.

    Возвращает скорректированное смещение (не новую позицию): компонента,
    упёршаяся в форму, обрезается до её грани; свободные компоненты остаются
    как были. Именно это значение ожидает ``Entity.move`` в ``motion/core.py``.
    """
    if velocity.length_squared() == 0.0:
        # Как Rust: нулевое движение не собирает формы и сохраняет -0.0.
        return velocity

    query = _expand_towards(bounds, velocity)
    boxes = collect_collision_boxes(world, query)
    return resolve_shape_movement(velocity, bounds, boxes)


def sweep(world: object, bounds: Aabb, movement: Vec3) -> Vec3:
    """Синоним :func:`collide_aabb` с именем из постановки задачи."""
    return collide_aabb(world, bounds, movement)


# clip_movement — публичный alias, как в API задачи.
clip_movement = sweep
