"""Мешинг чанка QuadRix (CPU, numpy).

Источник геометрии — ``proto_moderngl.py`` (``chunk_vertices``), но чище:
без запечённой текстуры, UV берутся из атласа, отсечение скрытых граней
через padding-массив (никаких проверок границ).

Формат вершины (stride 12 float32) — общий с terrain.vert:
    in_pos(3) | in_normal(3) | in_uv(2) | in_color(4)

``in_color`` — биомный tint грани (v_color, 0..1), как в Rust
(``TerrainVertex::color`` = tint * shade * AO). Для травы UP-грань берёт
цвет из ``grass.png`` colormap; остальные грани белые.

Один чанк = один draw call. Индексы не нужны: прототип отдаёт triangle
soup, поэтому ``mesh_chunk`` возвращает ``(vertices, None)``.

# FALLBACK: полноценный атмосферный свет / AO / greedy meshing — Фаза 5.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

# Размер чанка по каждой оси (ванильный Minecraft).
CHUNK_SIZE = 16

# ID воздуха. 0 — ванильный air, подтверждено block-registry.nbt
# (default_state("minecraft:air") == 0).
AIR_STATE_ID = 0

# Сколько float на вершину: pos(3) + normal(3) + uv(2) + color(4).
VERTEX_FLOATS = 12
# Формат для moderngl.vertex_array.
VERTEX_FORMAT = "3f 3f 2f 4f"
ATTRIBUTES = ("in_pos", "in_normal", "in_uv", "in_color")

# Таблица граней: (нормаль, 4 угла CCW при взгляде снаружи).
# Координаты углов — смещения от (x, y, z) блока в [0, 1].
FACE_DEFS: tuple[tuple[tuple[int, int, int], tuple[tuple[int, int, int], ...]], ...] = (
    ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
    ((0, 0, -1), ((1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0))),
    ((1, 0, 0), ((1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1))),
    ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    ((0, 1, 0), ((0, 1, 1), (1, 1, 1), (1, 1, 0), (0, 1, 0))),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
)

# Квад -> два треугольника: (0,1,2) и (0,2,3).
TRIANGLE_ORDER = (0, 1, 2, 0, 2, 3)

# Локальные UV на одну грань (6 вершин), порядок углов = TRIANGLE_ORDER
# (0, 1, 2, 0, 2, 3). V-компонента перевёрнута относительно наивной
# раскладки, чтобы она совпала с Rust ``mesher::standard_uv``: спрайт
# растёт сверху вниз (v = 1 - y на боках, v = z сверху, v = 1 - z снизу),
# а углы FACE_DEFS упорядочены так, что верх блока идёт последним.
# Без этого трава сбоку/снизу перевёрнута (трава у земли вместо верха).
QUAD_UV = np.asarray(
    ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    dtype=np.float32,
)


def mesh_chunk(
    blocks: np.ndarray,
    texture_atlas: Optional[object] = None,
    *,
    cull_hidden: bool = True,
    center: bool = True,
) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """Построить вершины чанка.

    Параметры
    ---------
    blocks:
        ``(16, 16, 16)`` uint16 — block state ids. Всё, что не
        ``AIR_STATE_ID``, считается твёрдым.
    texture_atlas:
        Объект с ``load_many(ids) -> (m, 4)`` (см. ``TextureAtlas``).
        ``None`` — UV всего тайла (0..1).
    cull_hidden:
        Отсекать грани, закрытые соседним твёрдым блоком.
    center:
        Сдвинуть чанк в начало координат (как в прототипе), иначе
        координаты начинаются с (0, 0, 0).

    Возвращает
    ----------
    ``(vertices, None)``: массив ``(N, 8)`` float32; ``None`` вместо
    индексов — геометрия уже разбита на треугольники (один draw call).
    """
    blocks = np.asarray(blocks)
    if blocks.ndim != 3:
        raise ValueError(
            f"[QuadRix] mesh_chunk: ожидается 3D-массив блоков, получено {blocks.shape}"
        )
    nx, ny, nz = blocks.shape

    solid = blocks != AIR_STATE_ID
    if not solid.any():
        return np.zeros((0, VERTEX_FLOATS), dtype=np.float32), None

    # padding-объём: соседи на границе чанка — воздух, без проверок границ
    pad = np.zeros((nx + 2, ny + 2, nz + 2), dtype=bool)
    pad[1:-1, 1:-1, 1:-1] = solid

    parts: list[np.ndarray] = []
    # Атлас с per-face UV (BlockAtlas) отдаёт прямоугольник для каждой грани;
    # старый интерфейс load_many даёт один прямоугольник на все грани.
    use_faces = hasattr(texture_atlas, "face_rects")
    for fi, (normal, corners) in enumerate(FACE_DEFS):
        dx, dy, dz = normal
        neighbor = pad[1 + dx : 1 + dx + nx, 1 + dy : 1 + dy + ny, 1 + dz : 1 + dz + nz]
        mask = solid & ~neighbor if cull_hidden else solid
        xs, ys, zs = np.nonzero(mask)
        m = xs.size
        if m == 0:
            continue

        base = np.stack((xs, ys, zs), axis=1).astype(np.float32)  # (m, 3)
        # два треугольника на блок: (m, 6, 3) -> (m*6, 3)
        tri = np.stack(
            [base + np.asarray(corners[i], dtype=np.float32) for i in TRIANGLE_ORDER],
            axis=1,
        ).reshape(-1, 3)

        verts_per_face = tri.shape[0]
        normals = np.tile(np.asarray(normal, dtype=np.float32), (verts_per_face, 1))

        if texture_atlas is None:
            uvs = np.tile(QUAD_UV, (m, 1))
            face_colors = np.ones((m, 4), dtype=np.float32)
        else:
            ids = blocks[xs, ys, zs]
            if use_faces:
                rects = np.asarray(
                    texture_atlas.face_rects(ids)[:, fi, :], dtype=np.float32
                )
            else:
                rects = np.asarray(texture_atlas.load_many(ids), dtype=np.float32)
            u0 = rects[:, 0:1]
            v0 = rects[:, 1:2]
            du = rects[:, 2:3]
            dv = rects[:, 3:4]
            # локальные UV -> прямоугольник тайла, на каждую из 6 вершин
            local = QUAD_UV[None, :, :]  # (1, 6, 2)
            uvs = np.empty((m, 6, 2), dtype=np.float32)
            uvs[:, :, 0] = u0 + local[:, :, 0] * du
            uvs[:, :, 1] = v0 + local[:, :, 1] * dv
            uvs = uvs.reshape(-1, 2)
            # v_color грани: биомный tint (только UP травы), иначе белый.
            if hasattr(texture_atlas, "face_tints"):
                face_colors = (
                    np.asarray(texture_atlas.face_tints(ids)[:, fi, :], dtype=np.float32)
                    / 255.0
                )
            else:
                face_colors = np.ones((m, 4), dtype=np.float32)

        # цвет на каждую из 6 вершин грани (порядок = TRIANGLE_ORDER)
        colors = np.repeat(face_colors, 6, axis=0)
        parts.append(np.concatenate((tri, normals, uvs, colors), axis=1))

    if not parts:
        return np.zeros((0, VERTEX_FLOATS), dtype=np.float32), None

    out = np.concatenate(parts, axis=0).astype(np.float32)
    if center:
        # центрируем чанк в начале координат (как прототип)
        out[:, 0] -= nx / 2.0
        out[:, 1] -= ny / 2.0
        out[:, 2] -= nz / 2.0
    return out, None


def face_count(vertices: np.ndarray) -> int:
    """Сколько квадов в буфере (6 вершин на грань) — удобно в тестах."""
    return int(np.asarray(vertices).shape[0]) // 6


def chunk_from_heightmap(heights: np.ndarray, solid_id: int) -> np.ndarray:
    """Собрать чанк из карты высот ``(16, 16)``: блоки при ``y < height``.

    Индексация: ``heights[x, z]`` -> ``blocks[x, y, z]``.
    Вспомогательная функция для тестов и отладки сцены.
    """
    heights = np.asarray(heights, dtype=np.int32)
    if heights.shape != (CHUNK_SIZE, CHUNK_SIZE):
        raise ValueError(
            f"[QuadRix] chunk_from_heightmap: карта высот должна быть "
            f"{CHUNK_SIZE}x{CHUNK_SIZE}, получено {heights.shape}"
        )
    blocks = np.zeros((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), dtype=np.uint16)
    ys = np.arange(CHUNK_SIZE, dtype=np.int32)[None, :, None]  # (1, 16, 1)
    filled = ys < heights[:, None, :]  # (16, 16, 16)
    blocks[filled] = np.uint16(solid_id)
    return blocks
