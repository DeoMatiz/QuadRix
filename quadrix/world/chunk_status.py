#!/usr/bin/env python3
"""Идентичности и порядок статусов генерации чанка.

Порт ``horizon/crates/horizon-world/src/chunk_status.rs`` (Minecraft 26.3).

Статус описывает прогресс; его присвоение не запускает задачу генерации и
не реализует освещение.
"""

from __future__ import annotations

from enum import IntEnum
from typing import List

from quadrix.world.heightmap import HeightmapType
from quadrix.world.nbt import Tag, TagType

__all__ = ["ChunkStatus"]


def _invalid(reason: str) -> ValueError:
    """``compression::invalid`` — ошибка формата с префиксом QuadRix."""
    return ValueError(f"[QuadRix] {reason}")


# ``ChunkStatus::FINAL_HEIGHTMAPS`` (chunk_status.rs:23), объявляется после
# класса: внутри тела Enum список стал бы лишним членом.
_FINAL_HEIGHTMAP_TYPES: List[HeightmapType] = [
    HeightmapType.WorldSurface,
    HeightmapType.OceanFloor,
    HeightmapType.MotionBlocking,
    HeightmapType.MotionBlockingNoLeaves,
]

_WG_HEIGHTMAP_TYPES: List[HeightmapType] = [
    HeightmapType.WorldSurfaceWg,
    HeightmapType.OceanFloorWg,
]


class ChunkStatus(IntEnum):
    """``enum ChunkStatus``: статус по ``repr(u8)``, порядок = индекс."""

    Empty = 0
    StructureStarts = 1
    StructureReferences = 2
    Biomes = 3
    Terrain = 4
    Features = 5
    InitializeLight = 6
    Light = 7
    Spawn = 8
    Full = 9

    def index(self) -> int:
        """``index``: ``self as usize``."""
        return int(self)

    def parent(self) -> "ChunkStatus":
        """``parent``: предыдущий статус; у ``Empty`` — он же."""
        return _CHUNK_STATUS_ALL[max(0, self.index() - 1)]

    def name(self) -> str:
        """``name``: реестровое имя ``minecraft:<path>``."""
        return _CHUNK_STATUS_NAMES[self]

    def is_level_chunk(self) -> bool:
        """``is_level_chunk``: только ``Full`` грузится как LevelChunk."""
        return self is ChunkStatus.Full

    def heightmaps(self) -> List[HeightmapType]:
        """``heightmaps``: ``Terrain`` и позже — финальный набор."""
        if self >= ChunkStatus.Terrain:
            return list(_FINAL_HEIGHTMAP_TYPES)
        return list(_WG_HEIGHTMAP_TYPES)

    @classmethod
    def parse(cls, name: str) -> "ChunkStatus":
        """``parse``: реестровый codec, неизвестные id — ошибка."""
        if ":" in name:
            namespace, _, path = name.partition(":")
            if namespace not in ("", "minecraft"):
                raise _invalid("unknown chunk status namespace")
        else:
            path = name
        for status in _CHUNK_STATUS_ALL:
            if status.name().startswith("minecraft:") and status.name()[len("minecraft:"):] == path:
                return status
        raise _invalid("unknown chunk status")

    @classmethod
    def by_name(cls, name: str) -> "ChunkStatus":
        """``by_name``: прямой native-обход с fallback на ``Empty``."""
        try:
            return cls.parse(name)
        except ValueError:
            return cls.Empty

    @classmethod
    def from_nbt(cls, tag: Tag) -> "ChunkStatus":
        """``from_nbt``: тег должен быть строкой известного статуса."""
        if not tag.is_string:
            raise _invalid("chunk status is not a string")
        return cls.parse(tag.str_val or "")

    def to_nbt(self) -> Tag:
        """``to_nbt``: строковый тег с именем статуса."""
        return Tag(TagType.String, str_val=self.name())


_CHUNK_STATUS_NAMES = {
    ChunkStatus.Empty: "minecraft:empty",
    ChunkStatus.StructureStarts: "minecraft:structure_starts",
    ChunkStatus.StructureReferences: "minecraft:structure_references",
    ChunkStatus.Biomes: "minecraft:biomes",
    ChunkStatus.Terrain: "minecraft:terrain",
    ChunkStatus.Features: "minecraft:features",
    ChunkStatus.InitializeLight: "minecraft:initialize_light",
    ChunkStatus.Light: "minecraft:light",
    ChunkStatus.Spawn: "minecraft:spawn",
    ChunkStatus.Full: "minecraft:full",
}

# ``ChunkStatus::ALL`` (chunk_status.rs:29).
_CHUNK_STATUS_ALL: List[ChunkStatus] = [
    ChunkStatus.Empty,
    ChunkStatus.StructureStarts,
    ChunkStatus.StructureReferences,
    ChunkStatus.Biomes,
    ChunkStatus.Terrain,
    ChunkStatus.Features,
    ChunkStatus.InitializeLight,
    ChunkStatus.Light,
    ChunkStatus.Spawn,
    ChunkStatus.Full,
]

ChunkStatus.ALL = _CHUNK_STATUS_ALL  # type: ignore[attr-defined]
ChunkStatus.MAX_STRUCTURE_DISTANCE = 8  # type: ignore[attr-defined]
ChunkStatus.FINAL_HEIGHTMAPS = _FINAL_HEIGHTMAP_TYPES  # type: ignore[attr-defined]
