#!/usr/bin/env python3
"""Плоский мир и рендер terrain для GameScreen (Gameplay PART 1).

Полноценный мир (чанки, worldgen, освещение) — следующие PART'ы. Пока
используется ``FlatWorld`` — бесконечная в плане X/Z площадка из
``ground_top`` слоёв твёрдых блоков. Этого достаточно, чтобы WASD/мышь/
прыжок проверялись на реальной геометрии (см. AGENTS.md, правило 10:
FALLBACK — плоский мир).

Мешинг — ``quadrix.render.mesher`` (уже портирован). Один массив вершин,
один draw call; текстура — шахматка, чтобы движение было видно.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

import numpy as np

from quadrix.render.mesher import CHUNK_SIZE, mesh_chunk

__all__ = [
    "FlatWorld",
    "TerrainRenderer",
    "ChunkTerrainRenderer",
    "chunk_blocks",
    "checker_texture",
]

#: Сколько слоёв твёрдых блоков у плоского мира (верхний — трава).
GROUND_TOP = 4
#: Регион меша: от ``-MESH_HALF`` до ``+MESH_HALF`` по X и Z.
MESH_HALF = 24
#: Идентификатор твёрдого блока в меше (0 — воздух в mesher).
SOLID_STATE_ID = 1


class FlatWorld:
    """Бесконечный плоский мир (порт-заглушка до PART с чанками).

    ``block(x, y, z)`` отдаёт имя блока: трава на верхнем слое, земля
    ниже, камень под ними — как у плоского мира Minecraft.

    Поверх базы держится словарь ``_overrides``: он и есть мир для
    Gameplay PART 2 — ``set_block`` (разрушение/установка) пишет туда, а
    ``get_block``/``block`` читают. Rust-мир (``Level``/чанки) — следующий
    PART; интерфейс ``get_block``/``set_block`` уже тот, что ждут
    ``block_survival.break_block`` и ``block_placement`` (позиция-кортеж,
    состояние, флаги).
    """

    def __init__(self, ground_top: int = GROUND_TOP) -> None:
        self.ground_top = int(ground_top)
        #: (x, y, z) -> имя блока (всё, что не задано здесь, — база).
        self._overrides: dict[tuple[int, int, int], str] = {}

    def _base_block(self, y: int) -> str:
        """Блок плоской базы по высоте (x/z не важны)."""
        if y < 0:
            return "minecraft:stone"
        if y < self.ground_top - 1:
            return "minecraft:dirt"
        if y == self.ground_top - 1:
            return "minecraft:grass_block"
        return "minecraft:air"

    def block(self, x: int, y: int, z: int) -> str:
        """Имя блока в ``(x, y, z)`` (интерфейс ``world.block`` из motion)."""
        key = (int(x), int(y), int(z))
        name = self._overrides.get(key)
        if name is not None:
            return name
        return self._base_block(int(y))

    # -- интерфейс мира для block_survival / block_placement --------------

    def get_block(self, position: Sequence[int]) -> str:
        """Состояние блока в ``position`` (кортеж) — имя блока.

        Так же, как ``Level.getBlockState`` в Rust, только плоское имя:
        ``block_placement``/``block_survival`` резолвят его в id реестром.
        """
        return self.block(int(position[0]), int(position[1]), int(position[2]))

    def set_block(
        self, position: Sequence[int], state: Any, flags: int = 3
    ) -> bool:
        """Записать блок (``Level.setBlock``): имя или ``BlockStateId``.

        ``state`` — имя блока, ``BlockState`` или ``BlockStateId`` из
        реестра ``.local``. Неизвестный id трактуется как воздух. Флаги
        (11 — место, 3 — разрушение) на плоском мире не влияют; сохранены
        для совместимости с сигнатурой Rust.
        """
        name = self._state_name(state)
        self._overrides[(int(position[0]), int(position[1]), int(position[2]))] = name
        return True

    @staticmethod
    def _state_name(state: Any) -> str:
        """Привести состояние к имени блока (для словаря ``_overrides``)."""
        if isinstance(state, str):
            return state
        name = getattr(state, "name", None)
        if isinstance(name, str):
            return name
        state_id = getattr(state, "id", None)
        if isinstance(state_id, int):
            from quadrix.world.block_placement import default_registry
            from quadrix.world.registry import BlockStateId

            found = default_registry().state(BlockStateId(state_id))
            if found is not None:
                return found.name
        return "minecraft:air"


def _build_region(
    world: FlatWorld, half: int = MESH_HALF
) -> np.ndarray:
    """Массив блоков ``(2*half, ground_top, 2*half)`` для меша."""
    size = half * 2
    blocks = np.full(
        (size, world.ground_top, size), SOLID_STATE_ID, dtype=np.uint16
    )
    return blocks


@dataclass
class TerrainRenderer:
    """Меш плоского мира + отрисовка с MVP камеры."""

    world: FlatWorld
    vertices: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        if self.vertices is None:
            blocks = _build_region(self.world)
            verts, _ = mesh_chunk(blocks, None, cull_hidden=True, center=False)
            # Сдвигаем чанк так, чтобы центр региона был в начале координат.
            verts = np.asarray(verts, dtype=np.float32).copy()
            if verts.size:
                verts[:, 0] -= MESH_HALF
                verts[:, 2] -= MESH_HALF
            self.vertices = verts

    def draw(
        self,
        backend: Any,
        program: Any,
        texture: Any,
        camera: Any,
        width: float,
        height: float,
    ) -> None:
        """Один draw call terrain с ``mvp`` из камеры."""
        if self.vertices is None or self.vertices.size == 0:
            return
        mvp = camera.view_projection(width, height)
        backend.draw(
            self.vertices,
            program,
            texture,
            vertex_format="3f 3f 2f",
            attributes=("in_pos", "in_normal", "in_uv"),
            mvp=mvp,
            depth_test=True,
            cull_face=True,
            blend=False,
        )


def chunk_blocks(chunk: Any) -> np.ndarray:
    """Собрать блоки одной колонны в ``(16, height, 16)[x, y, z]`` uint16.

    ``ChunkSection.unpack()`` отдаёт плоский список с индексом
    ``(y << 8) | (z << 4) | x``; ``mesh_chunk`` ждёт ``blocks[x, y, z]``.
    Поэтому ``(16,16,16)[y,z,x]`` → ``transpose(2, 0, 1)`` → ``[x,y,z]``.
    """
    sections = getattr(chunk, "sections", None) or []
    parts: list[np.ndarray] = []
    for section in sections:
        flat = section.states.unpack()
        arr = np.asarray(flat, dtype=np.uint16).reshape(
            16, 16, 16
        )  # [y, z, x]
        arr = np.ascontiguousarray(arr.transpose(2, 0, 1))  # [x, y, z]
        parts.append(arr)
    if not parts:
        return np.zeros((16, 0, 16), dtype=np.uint16)
    return np.concatenate(parts, axis=1)


class ChunkTerrainRenderer:
    """Меш реальных чанков сервера (:class:`ClientWorld`) (Gameplay PART 3).

    Порт подмножества ``horizon-client-render/src/chunk.rs``/``mesher.rs``:
    на колонну — один ``mesh_chunk`` (координаты в мире: ``+cx*16``,
    ``+chunk.min_y``, ``+cz*16``). Меши пересобираются, когда меняется набор
    пришедших чанков (``world.chunks``), — этого достаточно для PART 3
    (полный стриминг/освещение — отдельные PART'ы).
    """

    def __init__(self, world: Any) -> None:
        self.world = world
        self.vertices: Optional[np.ndarray] = None
        self._keys: Optional[tuple] = None

    def refresh(self) -> bool:
        """Пересобрать меши, если набор чанков изменился. ``True`` — обновили."""
        chunks = getattr(self.world, "chunks", None)
        if not chunks:
            if self._keys is None:
                return False
            self.vertices = None
            self._keys = None
            return True
        keys = tuple(sorted(chunks.keys()))
        if keys == self._keys:
            return False
        self._keys = keys
        self._rebuild(chunks)
        return True

    def _rebuild(self, chunks: dict) -> None:
        """Собрать меши всех пришедших колонн в один буфер вершин."""
        parts: list[np.ndarray] = []
        for (cx, cz), chunk in chunks.items():
            blocks = chunk_blocks(chunk)
            if blocks.shape[1] == 0:
                continue
            verts, _ = mesh_chunk(
                blocks, None, cull_hidden=True, center=False
            )
            verts = np.asarray(verts, dtype=np.float32)
            if verts.size == 0:
                continue
            verts[:, 0] += float(cx) * 16.0
            verts[:, 1] += float(getattr(chunk, "min_y", 0))
            verts[:, 2] += float(cz) * 16.0
            parts.append(verts)
        self.vertices = np.concatenate(parts, axis=0) if parts else None

    def draw(
        self,
        backend: Any,
        program: Any,
        texture: Any,
        camera: Any,
        width: float,
        height: float,
    ) -> None:
        """Один draw call всех чанков с MVP камеры."""
        if self.vertices is None or self.vertices.size == 0:
            return
        mvp = camera.view_projection(width, height)
        backend.draw(
            self.vertices,
            program,
            texture,
            vertex_format="3f 3f 2f",
            attributes=("in_pos", "in_normal", "in_uv"),
            mvp=mvp,
            depth_test=True,
            cull_face=True,
            blend=False,
        )


def checker_texture(size: int = 16, square: int = 4) -> np.ndarray:
    """Шахматная RGBA-текстура (для terrain sampler ``texture0``)."""
    img = np.full((size, size, 4), 255, dtype=np.uint8)
    for y in range(size):
        for x in range(size):
            if ((x // square) + (y // square)) % 2 == 0:
                img[y, x, :3] = 150
            else:
                img[y, x, :3] = 90
    return img
