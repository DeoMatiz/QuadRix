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
from typing import Any, Optional

import numpy as np

from quadrix.render.mesher import CHUNK_SIZE, mesh_chunk

__all__ = ["FlatWorld", "TerrainRenderer", "checker_texture"]

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
    """

    def __init__(self, ground_top: int = GROUND_TOP) -> None:
        self.ground_top = int(ground_top)

    def block(self, x: int, y: int, z: int) -> str:
        """Имя блока в ``(x, y, z)`` (интерфейс ``world.block`` из motion)."""
        if y < 0:
            return "minecraft:stone"
        if y < self.ground_top - 1:
            return "minecraft:dirt"
        if y == self.ground_top - 1:
            return "minecraft:grass_block"
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
