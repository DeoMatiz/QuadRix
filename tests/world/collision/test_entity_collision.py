#!/usr/bin/env python3
"""Тесты quadrix/world/collision/entity_collision.py.

Проверяется настоящий sweep по VoxelShape из
.local/horizon-client-collision/cached-collision.nbt:
  * пол из stone останавливает падение;
  * пустой мир не трогает движение;
  * стена обрезает X;
  * плита (0.5) останавливает раньше полного куба;
  * диагональ скользит по свободной оси.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.core.geometry import Aabb, Vec3
from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    load_cached_collision,
)
from quadrix.world.collision.entity_collision import (
    clip_movement,
    collide_aabb,
    sweep,
)
from quadrix.world.registry import BlockRegistry, load_registry


ROOT = Path(__file__).resolve().parents[3]
COLLISION_DIR = ROOT / ".local" / "horizon-client-collision"

if not COLLISION_DIR.exists():  # pragma: no cover - зависит от .local
    pytest.skip(f"нет данных столкновений: {COLLISION_DIR}", allow_module_level=True)


@pytest.fixture(scope="module")
def registry() -> BlockRegistry:
    return load_registry(COLLISION_DIR / "block-registry.nbt")


@pytest.fixture(scope="module")
def cached(registry: BlockRegistry) -> CachedCollisionRegistry:
    return load_cached_collision(
        registry, COLLISION_DIR / "cached-collision.nbt"
    )


class FakeWorld:
    """Мир с блоком по имени и настоящими формами из .local.

    ``floor_y`` задаёт сплошной пол из stone на этой высоте и ниже; ``blocks``
    перекрывает отдельные позиции (например, плитой).
    """

    def __init__(
        self,
        registry: BlockRegistry,
        cached: CachedCollisionRegistry,
        blocks: dict[tuple[int, int, int], str] | None = None,
        floor_y: int | None = None,
    ) -> None:
        self.registry = registry
        self.cached_collision = cached
        self._blocks = blocks or {}
        self._floor_y = floor_y

    def block(self, x: int, y: int, z: int) -> str:
        name = self._blocks.get((x, y, z))
        if name is not None:
            return name
        if self._floor_y is not None and y <= self._floor_y:
            return "minecraft:stone"
        return "minecraft:air"


def _body(min_x: float, min_y: float, min_z: float) -> Aabb:
    """Тело игрока 0.6 x 1.8 x 0.6 с ногами в (min_x, min_y, min_z)."""
    return Aabb.new(
        Vec3(min_x, min_y, min_z),
        Vec3(min_x + 0.6, min_y + 1.8, min_z + 0.6),
    )


# ---------------------------------------------------------------------------
# 1. Пол из stone: падение упирается ровно в верхнюю грань y=64
# ---------------------------------------------------------------------------

def test_floor_stops_downward_movement(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    world = FakeWorld(registry, cached, floor_y=63)
    bounds = _body(0.2, 64.0, 0.2)

    resolved = collide_aabb(world, bounds, Vec3(0.0, -1.0, 0.0))

    # Ноги уже на y=64, плита пола 63..64: двигаться вниз нельзя.
    assert resolved.x == 0.0
    assert resolved.z == 0.0
    assert resolved.y == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 2. Пустой мир: движение не меняется
# ---------------------------------------------------------------------------

def test_empty_world_keeps_movement(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    world = FakeWorld(registry, cached)
    bounds = _body(0.2, 64.0, 0.2)

    resolved = collide_aabb(world, bounds, Vec3(0.0, -1.0, 0.0))

    assert resolved == Vec3(0.0, -1.0, 0.0)


# ---------------------------------------------------------------------------
# 3. Стена x>=1: X обрезается до нуля, а Z остаётся свободный
# ---------------------------------------------------------------------------

def test_wall_stops_horizontal_movement(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    world = FakeWorld(
        registry,
        cached,
        blocks={(1, 64, 0): "minecraft:stone", (1, 65, 0): "minecraft:stone"},
    )
    bounds = _body(0.4, 64.0, 0.2)  # max.x == 1.0, вплотную к стене

    resolved = collide_aabb(world, bounds, Vec3(1.0, 0.0, 0.0))

    assert resolved.x == pytest.approx(0.0, abs=1e-9)
    assert resolved.y == 0.0
    assert resolved.z == 0.0


# ---------------------------------------------------------------------------
# 4. Плита: 0.5, а не 1.0 — используется VoxelShape, а не полный куб
# ---------------------------------------------------------------------------

def test_slab_stops_at_half_block(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    world = FakeWorld(
        registry, cached, blocks={(0, 63, 0): "minecraft:stone_slab"}
    )
    bounds = _body(0.2, 64.0, 0.2)

    resolved = collide_aabb(world, bounds, Vec3(0.0, -1.0, 0.0))

    # Верх плиты 63.5: падение -1.0 обрезается до -0.5.
    assert resolved.y == pytest.approx(-0.5, abs=1e-9)
    assert resolved.y != pytest.approx(-1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 5. Диагональ: X упёрся в стену, Z свободно скользит
# ---------------------------------------------------------------------------

def test_diagonal_movement_slides_along_free_axis(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    world = FakeWorld(registry, cached, blocks={(1, 64, 0): "minecraft:stone"})
    bounds = _body(0.4, 64.0, 0.2)

    resolved = collide_aabb(world, bounds, Vec3(1.0, 0.0, 1.0))

    assert resolved.x == pytest.approx(0.0, abs=1e-9)
    assert resolved.y == 0.0
    assert resolved.z == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 6. Публичные имена sweep / clip_movement — тот же sweep
# ---------------------------------------------------------------------------

def test_sweep_and_clip_movement_are_aliases(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    world = FakeWorld(registry, cached, floor_y=63)
    bounds = _body(0.2, 64.0, 0.2)
    movement = Vec3(0.0, -0.25, 0.0)

    expected = collide_aabb(world, bounds, movement)
    assert sweep(world, bounds, movement) == expected
    assert clip_movement(world, bounds, movement) == expected
