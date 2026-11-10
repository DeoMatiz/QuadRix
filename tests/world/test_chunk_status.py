#!/usr/bin/env python3
"""Тесты порта ``horizon-world/src/chunk_status.rs`` (Minecraft 26.3)."""

from __future__ import annotations

import pytest

from quadrix.world.chunk_status import ChunkStatus
from quadrix.world.heightmap import HeightmapType
from quadrix.world.nbt import Tag, TagType


def test_chunk_status_all_ten_in_order():
    """``ChunkStatus::ALL``: 10 статусов, индекс = значение."""
    assert len(list(ChunkStatus)) == 10
    assert ChunkStatus.ALL[0] is ChunkStatus.Empty
    assert ChunkStatus.ALL[-1] is ChunkStatus.Full
    assert [status.index() for status in ChunkStatus.ALL] == list(range(10))
    assert ChunkStatus.Terrain.index() == 4
    assert ChunkStatus.MAX_STRUCTURE_DISTANCE == 8


def test_chunk_status_roundtrip_nbt():
    """``to_nbt``/``from_nbt``: строка реестрового имени."""
    status = ChunkStatus.InitializeLight
    tag = status.to_nbt()
    assert tag.is_string
    assert tag.str_val == "minecraft:initialize_light"
    assert ChunkStatus.from_nbt(tag) is status

    with pytest.raises(ValueError):
        ChunkStatus.from_nbt(Tag(TagType.Int, int_val=7))


def test_chunk_status_parse_namespaces_and_fallback():
    """``parse`` принимает minecraft:/пустое пространство; ``by_name`` — fallback."""
    assert ChunkStatus.parse("minecraft:full") is ChunkStatus.Full
    assert ChunkStatus.parse("full") is ChunkStatus.Full
    assert ChunkStatus.parse(":spawn") is ChunkStatus.Spawn

    with pytest.raises(ValueError):
        ChunkStatus.parse("tutorial:full")  # чужое пространство имён
    with pytest.raises(ValueError):
        ChunkStatus.parse("minecraft:does_not_exist")

    assert ChunkStatus.by_name("minecraft:biomes") is ChunkStatus.Biomes
    assert ChunkStatus.by_name("garbage") is ChunkStatus.Empty  # fallback


def test_chunk_status_parent_and_level_chunk():
    """``parent`` сдвигает назад, ``Empty`` — сам себе родитель."""
    assert ChunkStatus.Empty.parent() is ChunkStatus.Empty
    assert ChunkStatus.Full.parent() is ChunkStatus.Spawn
    assert ChunkStatus.Terrain.parent() is ChunkStatus.Biomes
    assert ChunkStatus.Full.is_level_chunk()
    assert not ChunkStatus.Spawn.is_level_chunk()


def test_chunk_status_heightmaps_by_progress():
    """``heightmaps``: до Terrain — WG, с Terrain — финальный набор."""
    assert ChunkStatus.Empty.heightmaps() == [
        HeightmapType.WorldSurfaceWg,
        HeightmapType.OceanFloorWg,
    ]
    assert ChunkStatus.Biomes.heightmaps() == [
        HeightmapType.WorldSurfaceWg,
        HeightmapType.OceanFloorWg,
    ]
    final = ChunkStatus.Terrain.heightmaps()
    assert final == [
        HeightmapType.WorldSurface,
        HeightmapType.OceanFloor,
        HeightmapType.MotionBlocking,
        HeightmapType.MotionBlockingNoLeaves,
    ]
    assert ChunkStatus.Full.heightmaps() == final
