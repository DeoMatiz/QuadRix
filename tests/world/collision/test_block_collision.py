#!/usr/bin/env python3
"""Тесты quadrix/world/collision/block_collision.py.

Порт поведения horizon-world/src/collision.rs и block_collision.rs.
Используются реальные .local/horizon-client-collision/*.nbt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.core.geometry import Vec3
from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    VoxelShape,
    block_collision_boxes,
    collision_shape,
    full_cube,
    load_cached_collision,
)
from quadrix.world.registry import BlockRegistry, load_registry


def _collision_dir(root: Path) -> Path:
    base = root / ".local" / "horizon-client-collision"
    if not base.exists():
        pytest.skip(f"нет данных столкновений: {base}")
    return base


ROOT = Path(__file__).resolve().parents[3]
COLLISION_DIR = _collision_dir(ROOT)


@pytest.fixture(scope="module")
def registry() -> BlockRegistry:
    return load_registry(COLLISION_DIR / "block-registry.nbt")


@pytest.fixture(scope="module")
def cached(registry: BlockRegistry) -> CachedCollisionRegistry:
    return load_cached_collision(
        registry, COLLISION_DIR / "cached-collision.nbt"
    )


def _boxes(shape: VoxelShape):
    return [
        (b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z)
        for b in shape.boxes_list()
    ]


# ---------------------------------------------------------------------------
# 1. Реальный cached-collision.nbt разбирается
# ---------------------------------------------------------------------------

def test_real_cached_collision_loads(cached: CachedCollisionRegistry) -> None:
    assert cached.shape_count() > 0
    assert cached.unique_grid_count() > 0
    assert cached.cached_state_count() > 0
    assert cached.has_canonical_identities() is True
    # 35723 состояния в block-registry.nbt этой версии.
    assert len(cached.state_shapes) == cached.registry.len()


# ---------------------------------------------------------------------------
# 2. stone -> полный куб, один бокс [0,0,0]..[1,1,1]
# ---------------------------------------------------------------------------

def test_stone_is_full_cube(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    stone = registry.default_state("minecraft:stone")
    assert stone is not None
    shape = collision_shape(registry, stone, cached)
    assert shape.is_empty() is False
    assert shape.is_block() is True
    boxes = block_collision_boxes(registry, stone, cached)
    assert len(boxes) == 1
    box = boxes[0]
    assert (box.min.x, box.min.y, box.min.z) == (0.0, 0.0, 0.0)
    assert (box.max.x, box.max.y, box.max.z) == (1.0, 1.0, 1.0)
    # full_cube() даёт ту же самую геометрию
    assert _boxes(full_cube()) == _boxes(shape)


# ---------------------------------------------------------------------------
# 3. stone_slab -> один бокс [0,0,0]..[1,0.5,1]
# ---------------------------------------------------------------------------

def test_stone_slab_bottom_half(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    slab = registry.default_state("minecraft:stone_slab")
    assert slab is not None
    shape = collision_shape(registry, slab, cached)
    assert shape.is_block() is False
    assert _boxes(shape) == [(0.0, 0.0, 0.0, 1.0, 0.5, 1.0)]
    # Разложение сетки не дробит плиту на лишние куски.
    assert len(shape.boxes_list()) == 1


# ---------------------------------------------------------------------------
# 4. air -> пустая форма, 0 боксов
# ---------------------------------------------------------------------------

def test_air_has_empty_shape(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    air = registry.default_state("minecraft:air")
    assert air is not None
    shape = collision_shape(registry, air, cached)
    assert shape.is_empty() is True
    assert shape.boxes_list() == []
    assert block_collision_boxes(registry, air, cached) == []
    # Кэш хранит каноническую пустую форму (collision.rs:183).
    assert cached.cached_shape(air) is not None


# ---------------------------------------------------------------------------
# 5. oak_stairs -> два бокса, не полный куб (жадное разложение)
# ---------------------------------------------------------------------------

def test_oak_stairs_has_multiple_boxes(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    stairs = registry.default_state("minecraft:oak_stairs")
    assert stairs is not None
    shape = collision_shape(registry, stairs, cached)
    assert shape.is_block() is False
    boxes = _boxes(shape)
    # Нижняя ступень 0..0.5 по Y целиком, верхняя — только 0..0.5 по Z.
    assert (0.0, 0.0, 0.0, 1.0, 0.5, 1.0) in boxes
    assert (0.0, 0.5, 0.0, 1.0, 1.0, 0.5) in boxes
    assert len(boxes) == 2


# ---------------------------------------------------------------------------
# 6. oak_fence -> узкий столб, выходящий за пределы блока по Y (large shape)
# ---------------------------------------------------------------------------

def test_oak_fence_post_shape(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    fence = registry.default_state("minecraft:oak_fence")
    assert fence is not None
    shape = collision_shape(registry, fence, cached)
    assert _boxes(shape) == [(0.375, 0.0, 0.375, 0.625, 1.5, 0.625)]
    # min/max — из discrete extrema, а не из координат куба.
    assert shape.min(1) == 0.0
    assert shape.max(1) == 1.5


# ---------------------------------------------------------------------------
# 7. torch -> пустая кэшированная форма (не «неизвестно»)
# ---------------------------------------------------------------------------

def test_torch_is_empty(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    torch = registry.default_state("minecraft:torch")
    assert torch is not None
    assert cached.cached_shape(torch) is not None
    assert collision_shape(registry, torch, cached).is_empty() is True


# ---------------------------------------------------------------------------
# 8. Некэшированные состояния: solid-заглушка (block_collision.rs:188)
# ---------------------------------------------------------------------------

def test_uncached_shulker_box_falls_back_to_full_cube(
    registry: BlockRegistry, cached: CachedCollisionRegistry
) -> None:
    shulker = registry.default_state("minecraft:shulker_box")
    assert shulker is not None
    # -1 в cached_shapes: форма зависит от block entity.
    assert cached.cached_shape(shulker) is None
    shape = collision_shape(registry, shulker, cached)
    assert shape.is_block() is True
    assert _boxes(shape) == [(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)]


# ---------------------------------------------------------------------------
# 9. VoxelShape: ручная сетка и защита от невалидных данных
# ---------------------------------------------------------------------------

def test_voxel_shape_manual_grid() -> None:
    # Тот же пример, что sparse_stair_decomposition в shape.rs:607.
    shape = VoxelShape.from_cube(
        (2, 2, 2), [True, True, False, False, True, True, True, True]
    )
    assert len(shape.boxes_list()) == 2
    with pytest.raises(ValueError):
        VoxelShape.from_grid(([0.0, 1.0], [0.0, 1.0], [0.0, 1.0]), [])
    with pytest.raises(ValueError):
        VoxelShape.from_cube((0, 1, 1), [])
