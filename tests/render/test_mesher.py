"""Тесты мешинга чанка (numpy, без окна)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from quadrix.render.mesher import (
    AIR_STATE_ID,
    CHUNK_SIZE,
    FACE_DEFS,
    VERTEX_FLOATS,
    VERTEX_FORMAT,
    chunk_from_heightmap,
    face_count,
    mesh_chunk,
)
from quadrix.render.texture_atlas import TextureAtlas

STONE_ID = 1  # block-registry.nbt: default_state("minecraft:stone") == 1


def _single_block(block_id: int = STONE_ID, pos: tuple[int, int, int] = (8, 8, 8)):
    blocks = np.zeros((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), dtype=np.uint16)
    blocks[pos] = block_id
    return blocks


def test_constants() -> None:
    assert CHUNK_SIZE == 16
    assert VERTEX_FLOATS == 8
    assert VERTEX_FORMAT == "3f 3f 2f"
    assert len(FACE_DEFS) == 6
    assert AIR_STATE_ID == 0


def test_empty_chunk_has_no_vertices() -> None:
    blocks = np.full((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), AIR_STATE_ID, dtype=np.uint16)

    vertices, indices = mesh_chunk(blocks)

    assert vertices.shape == (0, VERTEX_FLOATS)
    assert vertices.dtype == np.float32
    assert indices is None
    assert face_count(vertices) == 0


def test_single_block_emits_six_faces() -> None:
    vertices, indices = mesh_chunk(_single_block())

    # 6 граней * 2 треугольника * 3 вершины
    assert vertices.shape == (36, VERTEX_FLOATS)
    assert vertices.dtype == np.float32
    assert indices is None
    assert face_count(vertices) == 6

    # все 6 нормалей встречаются ровно по 6 вершин
    normals = vertices[:, 3:6]
    for normal, _ in FACE_DEFS:
        count = int(np.sum(np.all(normals == np.asarray(normal, dtype=np.float32), axis=1)))
        assert count == 6, f"normal {normal}: {count}"

    # UV в [0, 1]
    assert vertices[:, 6:8].min() >= 0.0
    assert vertices[:, 6:8].max() <= 1.0


def test_two_adjacent_blocks_cull_shared_face() -> None:
    blocks = _single_block(pos=(8, 8, 8))
    blocks[9, 8, 8] = STONE_ID  # сосед по +X

    vertices, _ = mesh_chunk(blocks)

    # 12 граней на двоих минус 2 скрытые = 10
    assert face_count(vertices) == 10
    assert vertices.shape == (60, VERTEX_FLOATS)

    # скрытой пары +X/-X быть не должно
    normals = vertices[:, 3:6]
    plus_x = int(np.sum(np.all(normals == np.array([1, 0, 0], np.float32), axis=1)))
    minus_x = int(np.sum(np.all(normals == np.array([-1, 0, 0], np.float32), axis=1)))
    assert plus_x == 6
    assert minus_x == 6


def test_two_diagonal_blocks_keep_all_faces() -> None:
    blocks = _single_block(pos=(8, 8, 8))
    blocks[9, 9, 9] = STONE_ID

    vertices, _ = mesh_chunk(blocks)

    assert face_count(vertices) == 12  # диагональ грани не прячет


def test_full_chunk_emits_only_outer_shell() -> None:
    blocks = np.full((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), STONE_ID, dtype=np.uint16)

    vertices, _ = mesh_chunk(blocks)

    # только внешняя оболочка: 6 * 16 * 16 = 1536 граней
    assert face_count(vertices) == 6 * CHUNK_SIZE * CHUNK_SIZE
    assert vertices.shape == (1536 * 6, VERTEX_FLOATS)

    # внутренних граней нет: каждая нормаль ровно 256 * 6 вершин
    normals = vertices[:, 3:6]
    for normal, _ in FACE_DEFS:
        count = int(np.sum(np.all(normals == np.asarray(normal, np.float32), axis=1)))
        assert count == 256 * 6


def test_uvs_come_from_atlas_rect() -> None:
    class HalfAtlas:
        """Крошечный фейковый атлас: тайл занимает верхнюю половину."""

        def load_many(self, ids: np.ndarray) -> np.ndarray:
            out = np.empty((np.asarray(ids).size, 4), dtype=np.float32)
            out[:] = (0.25, 0.5, 0.25, 0.5)
            return out

    vertices, _ = mesh_chunk(_single_block(), HalfAtlas())

    uvs = vertices[:, 6:8]
    assert np.isclose(uvs[:, 0].min(), 0.25)
    assert np.isclose(uvs[:, 0].max(), 0.50)
    assert np.isclose(uvs[:, 1].min(), 0.50)
    assert np.isclose(uvs[:, 1].max(), 1.00)


def test_real_atlas_uses_unit_uvs() -> None:
    atlas = TextureAtlas.load_default()
    vertices, _ = mesh_chunk(_single_block(), atlas)

    uvs = vertices[:, 6:8]
    assert np.isclose(uvs[:, 0].min(), 0.0)
    assert np.isclose(uvs[:, 0].max(), 1.0)
    assert np.isclose(uvs[:, 1].min(), 0.0)
    assert np.isclose(uvs[:, 1].max(), 1.0)


def test_centering_matches_prototype() -> None:
    blocks = np.full((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), STONE_ID, dtype=np.uint16)

    centered, _ = mesh_chunk(blocks)
    raw, _ = mesh_chunk(blocks, center=False)

    offset = CHUNK_SIZE / 2.0
    assert np.allclose(centered[:, :3] + offset, raw[:, :3])
    # оболочка чанка лежит в [-8, 8]
    assert np.isclose(centered[:, :3].min(), -offset)
    assert np.isclose(centered[:, :3].max(), offset)


def test_cull_hidden_false_emits_all_faces() -> None:
    blocks = _single_block(pos=(8, 8, 8))
    blocks[9, 8, 8] = STONE_ID

    vertices, _ = mesh_chunk(blocks, cull_hidden=False)

    assert face_count(vertices) == 12


def test_chunk_from_heightmap_builds_solid_columns() -> None:
    heights = np.zeros((CHUNK_SIZE, CHUNK_SIZE), dtype=np.int32)
    heights[0, 0] = CHUNK_SIZE  # полная колонна
    heights[1, 1] = 1

    blocks = chunk_from_heightmap(heights, STONE_ID)

    assert blocks.dtype == np.uint16
    assert int(np.count_nonzero(blocks)) == CHUNK_SIZE + 1
    assert blocks[0, CHUNK_SIZE - 1, 0] == STONE_ID
    assert blocks[0, 1, 0] == STONE_ID  # колонна сплошная
    assert blocks[2, 0, 2] == AIR_STATE_ID  # пустая колонна

    vertices, _ = mesh_chunk(blocks)
    assert face_count(vertices) > 0


def test_mesher_is_fast_enough() -> None:
    """Sanity: 100 полных чанков должны уложиться в 500 мс (2.1 мс/чанк в прототипе)."""
    blocks = np.full((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), STONE_ID, dtype=np.uint16)

    mesh_chunk(blocks)  # прогрев

    start = time.perf_counter()
    for _ in range(100):
        mesh_chunk(blocks)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < 500.0, f"мешинг слишком медленный: {elapsed_ms:.1f} мс / 100 чанков"


def test_mesh_chunk_rejects_bad_shape() -> None:
    with pytest.raises(ValueError, match="3D"):
        mesh_chunk(np.zeros((16, 16), dtype=np.uint16))
