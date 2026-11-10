#!/usr/bin/env python3
"""Тесты порта ``horizon-world/src/heightmap.rs`` (Minecraft 26.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import pytest

from quadrix.world.heightmap import (
    HEIGHT,
    MIN_Y,
    Heightmap,
    HeightmapError,
    HeightmapType,
)


# ---- минимальные реализации трейтов Rust -----------------------------------


@dataclass(frozen=True)
class St:
    """``trait HeightmapState``: явные факты о блоке."""

    air: bool = False
    fluid: bool = False
    motion: bool = False
    no_leaves: bool = False

    def is_air(self) -> bool:
        return self.air

    def is_air_block(self) -> bool:
        return self.air

    def has_fluid(self) -> bool:
        return self.fluid

    def blocks_motion_in_heightmap(self) -> bool:
        return self.motion

    def blocks_motion_in_heightmap_no_leaves(self) -> bool:
        return self.no_leaves


AIR = St(air=True)
STONE = St(air=False, motion=True, no_leaves=True)
# Листва блокирует движение, но не для карты без листвы.
LEAVES = St(air=False, motion=True, no_leaves=False)
WATER = St(air=False, fluid=True, motion=False, no_leaves=False)


class StubChunk:
    """``trait HeightmapChunk``: словарь блоков и ванильная вертикаль."""

    def __init__(self, min_y: int = MIN_Y, height: int = HEIGHT) -> None:
        self._min_y = min_y
        self._height = height
        self._blocks: Dict[Tuple[int, int, int], St] = {}

    def min_y(self) -> int:
        return self._min_y

    def height(self) -> int:
        return self._height

    def highest_section_y(self) -> int:
        return self._min_y + (self._height // 16 - 1) * 16

    def set_block(self, x: int, y: int, z: int, state: St) -> None:
        self._blocks[(x, y, z)] = state

    def block_state(self, x: int, y: int, z: int) -> St:
        return self._blocks.get((x, y, z), AIR)


# ---- HeightmapType ----------------------------------------------------------


def test_heightmap_type_six_variants_names_and_flags():
    """``HeightmapType::ALL``: ровно 6 типов с проводными именами."""
    assert len(list(HeightmapType)) == 6
    assert [int(t) for t in HeightmapType] == [0, 1, 2, 3, 4, 5]
    assert HeightmapType.WorldSurfaceWg.name() == "WORLD_SURFACE_WG"
    assert HeightmapType.WorldSurface.name() == "WORLD_SURFACE"
    assert HeightmapType.OceanFloorWg.name() == "OCEAN_FLOOR_WG"
    assert HeightmapType.OceanFloor.name() == "OCEAN_FLOOR"
    assert HeightmapType.MotionBlocking.name() == "MOTION_BLOCKING"
    assert HeightmapType.MotionBlockingNoLeaves.name() == "MOTION_BLOCKING_NO_LEAVES"

    sending = {t for t in HeightmapType if t.send_to_client()}
    assert sending == {
        HeightmapType.WorldSurface,
        HeightmapType.MotionBlocking,
        HeightmapType.MotionBlockingNoLeaves,
    }
    assert not HeightmapType.WorldSurfaceWg.keep_after_worldgen()
    assert not HeightmapType.OceanFloorWg.keep_after_worldgen()
    assert HeightmapType.WorldSurface.keep_after_worldgen()


def test_heightmap_type_is_opaque_predicates():
    """``is_opaque``: разные правила у шести типов."""
    assert HeightmapType.WorldSurface.is_opaque(STONE)
    assert HeightmapType.WorldSurfaceWg.is_opaque(LEAVES)
    assert not HeightmapType.WorldSurface.is_opaque(AIR)

    # OCEAN_FLOOR / OCEAN_FLOOR_WG: только ``blocks_motion_in_heightmap``.
    assert HeightmapType.OceanFloor.is_opaque(STONE)
    assert not HeightmapType.OceanFloor.is_opaque(AIR)

    # MOTION_BLOCKING считает и жидкость, и листву.
    assert HeightmapType.MotionBlocking.is_opaque(LEAVES)
    assert HeightmapType.MotionBlocking.is_opaque(WATER)
    # MOTION_BLOCKING_NO_LEAVES игнорирует листву, но не жидкость.
    assert not HeightmapType.MotionBlockingNoLeaves.is_opaque(LEAVES)
    assert HeightmapType.MotionBlockingNoLeaves.is_opaque(WATER)


# ---- создание и границы -----------------------------------------------------


def test_heightmap_new_bits_and_bounds():
    """``new``: 384 блока -> 9 бит на 256 колонн; плохие границы — ошибка."""
    heightmap = Heightmap.new(HeightmapType.MotionBlocking, MIN_Y, HEIGHT)
    assert heightmap.bits() == 9
    assert len(heightmap.raw_data()) == 37
    assert heightmap.min_y == MIN_Y

    for min_y, height in ((MIN_Y, 15), (MIN_Y, 3840), (MIN_Y + 1, HEIGHT), (-2048, HEIGHT)):
        with pytest.raises(HeightmapError) as info:
            Heightmap.new(HeightmapType.WorldSurface, min_y, height)
        assert info.value.kind == HeightmapError.INVALID_BOUNDS


# ---- update -----------------------------------------------------------------


def test_heightmap_update_stone_world_surface_and_motion_blocking():
    """Камень на y=64 -> верхняя занятая y = 64 у SURFACE и MOTION_BLOCKING."""
    for kind in (HeightmapType.WorldSurface, HeightmapType.MotionBlocking):
        chunk = StubChunk()
        heightmap = Heightmap.new(kind, MIN_Y, HEIGHT)
        changed = heightmap.update(chunk, 3, 64, 5, STONE)
        assert changed is True
        assert heightmap.highest_taken(3, 5) == 64
        # first_available — на один выше верхнего блока (как в vanilla/Rust).
        assert heightmap.first_available(3, 5) == 65


def test_heightmap_update_leaves_excluded_for_no_leaves():
    """Листва y=64 + камень y=63: NO_LEAVES -> 63, MOTION_BLOCKING -> 64."""
    chunk = StubChunk()

    no_leaves = Heightmap.new(HeightmapType.MotionBlockingNoLeaves, MIN_Y, HEIGHT)
    # Пока один камень внизу, листва сверху не удерживается картой без листвы.
    nos = [
        (no_leaves, 64, LEAVES),
        (no_leaves, 63, STONE),
    ]
    for heightmap, y, state in nos:
        chunk.set_block(3, y, 5, state)
        heightmap.update(chunk, 3, y, 5, state)
    assert no_leaves.highest_taken(3, 5) == 63

    motion = Heightmap.new(HeightmapType.MotionBlocking, MIN_Y, HEIGHT)
    motion.update(chunk, 3, 64, 5, LEAVES)
    assert motion.highest_taken(3, 5) == 64

    # ``update`` для блока на 2+ ниже опоры выходит без изменений.
    assert no_leaves.below_update(chunk, 3, 10, 5) is True
    assert no_leaves.update(chunk, 3, 10, 5, STONE) is False


def test_heightmap_get_set_roundtrip():
    """``get``/``set``: прямая запись и чтение высоты колонны."""
    heightmap = Heightmap.new(HeightmapType.OceanFloor, MIN_Y, HEIGHT)
    assert heightmap.get(2, 3) == MIN_Y  # изначально 0 + min_y
    heightmap.set(2, 3, 100)
    assert heightmap.get(2, 3) == 100
    assert heightmap.highest_taken(2, 3) == 99
    assert heightmap.index(2, 3) == 2 + 3 * 16


# ---- prime / set_raw_data ---------------------------------------------------


def test_heightmap_prime_scans_top_down():
    """``prime``: сверху вниз по X/Z; ненайденная колонна хранит прежнее."""
    chunk = StubChunk()
    chunk.set_block(5, 70, 5, STONE)
    chunk.set_block(1, 12, 1, LEAVES)

    heightmaps = [
        Heightmap.new(HeightmapType.WorldSurface, MIN_Y, HEIGHT),
        Heightmap.new(HeightmapType.MotionBlockingNoLeaves, MIN_Y, HEIGHT),
    ]
    # Ненулевое начальное значение должно сохраниться, если колонна пуста.
    heightmaps[0].set(0, 0, 40)

    Heightmap.prime(chunk, heightmaps)

    assert heightmaps[0].highest_taken(5, 5) == 70
    assert heightmaps[1].highest_taken(5, 5) == 70
    assert heightmaps[0].first_available(0, 0) == 40  # не найдено -> прежнее
    # Листва не удерживается картой без листвы: колонна (1,1) остаётся пустой.
    assert heightmaps[1].first_available(1, 1) == MIN_Y
    assert heightmaps[0].highest_taken(1, 1) == 12


def test_heightmap_set_raw_data_preserves_bits():
    """``set_raw_data``: равная длина сохраняет все биты, включая padding."""
    chunk = StubChunk()
    source = Heightmap.new(HeightmapType.WorldSurface, MIN_Y, HEIGHT)
    source.set(7, 9, 123)

    target = Heightmap.new(HeightmapType.WorldSurface, MIN_Y, HEIGHT)
    target.set_raw_data(chunk, source.raw_data())
    assert target.raw_data() == source.raw_data()
    assert target.get(7, 9) == 123


def test_heightmap_check_chunk_mismatch():
    """``check_chunk``: вертикаль карты должна совпадать с чанком."""
    heightmap = Heightmap.new(HeightmapType.WorldSurface, MIN_Y, HEIGHT)
    other = StubChunk(min_y=-80, height=HEIGHT)
    with pytest.raises(HeightmapError) as info:
        heightmap.update(other, 0, 0, 0, STONE)
    assert info.value.kind == HeightmapError.MISMATCHED_CHUNK


def test_heightmap_is_single_class_with_chunk_module():
    """``chunk.py`` не дублирует Heightmap — импортирует его отсюда."""
    from quadrix.world.chunk import Heightmap as ChunkHeightmap
    from quadrix.world.chunk import HeightmapType as ChunkHeightmapType

    assert ChunkHeightmap is Heightmap
    assert ChunkHeightmapType is HeightmapType
