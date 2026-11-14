#!/usr/bin/env python3
"""[QuadRix] Тесты травы (``grass_block``) 1:1 с Minecraft.

Проверяют исправление «чёрный куб с белой травой»:

    * UP — ``grass_block_top`` (серый) * биомный tint из ``grass.png``;
    * DOWN — ``dirt`` без tint;
    * N/S/E/W — ``grass_block_side`` + оверлей ``..._overlay`` (tint;
      включается только в оверлей);
    * v_color грани = биомный цвет (не белый и не 0);
    * offscreen-рендер куба травы — не чёрный, верх зелёный.

Эталон — Rust ``block_sprites.rs`` (top/side/bottom, TintSource::Grass),
``mesher.rs`` (``TerrainVertex::color``) и ``bake.rs`` (tintindex).
"""

from __future__ import annotations

import numpy as np
import pytest

from quadrix.render.mesher import FACE_DEFS, mesh_chunk
from quadrix.render.texture_atlas import (
    PLAINS_DOWNFALL,
    PLAINS_TEMPERATURE,
    grass_color,
    load_block_atlas,
)
from quadrix.world.block_placement import default_registry

#: Официальный plains-цвет травы (``grass.png`` при 0.8/0.4).
PLAINS_GRASS = (0x91, 0xBD, 0x59)


def _atlas():
    atlas = load_block_atlas()
    assert atlas is not None, "[QuadRix] block atlas не загружен"
    return atlas


def _grass_state() -> int:
    state = default_registry().default_state("minecraft:grass_block")
    assert state is not None
    return int(state.id)


def _face_vertices(vertices: np.ndarray, face_index: int) -> np.ndarray:
    """6 вершин грани ``face_index`` (по нормали из FACE_DEFS)."""
    normal = np.asarray(FACE_DEFS[face_index][0], dtype=np.float32)
    return vertices[np.all(vertices[:, 3:6] == normal, axis=1)]


def _face_center(rect: np.ndarray) -> np.ndarray:
    return np.array([rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0])


def _sprite_center(atlas, texture: str) -> np.ndarray:
    x, y, w, h = atlas._sprite_rects[texture]
    return np.array([(x + w / 2.0) / atlas.width, (y + h / 2.0) / atlas.height])


# ---------------------------------------------------------------------------
# биомный цвет из colormap
# ---------------------------------------------------------------------------

def test_grass_colormap_plains_green() -> None:
    """``grass_color`` (plains 0.8/0.4) — зелёный: G > R > B и ~#91BD59."""
    r, g, b = grass_color(PLAINS_TEMPERATURE, PLAINS_DOWNFALL)
    assert g > r > b, f"не зелёный: {(r, g, b)}"
    assert (r, g, b) == PLAINS_GRASS


def test_grass_colormap_in_range() -> None:
    """Цвет — канал 0..255 для любого климата (края не переполняются)."""
    for temp, down in ((0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (2.0, -1.0)):
        r, g, b = grass_color(temp, down)
        assert all(0 <= c <= 255 for c in (r, g, b))


# ---------------------------------------------------------------------------
# текстуры граней (top / side / bottom)
# ---------------------------------------------------------------------------

def test_grass_up_uses_top() -> None:
    """UP травы — ``grass_block_top``, а не бок."""
    atlas = _atlas()
    rects = atlas.face_rects(np.asarray([_grass_state()]))[0]
    assert np.allclose(
        _face_center(rects[4]),
        _sprite_center(atlas, "minecraft:block/grass_block_top"),
    )


def test_grass_side_uses_side() -> None:
    """N/S/E/W травы — ``grass_block_side``."""
    atlas = _atlas()
    rects = atlas.face_rects(np.asarray([_grass_state()]))[0]
    side = _sprite_center(atlas, "minecraft:block/grass_block_side")
    for fi in (0, 1, 2, 3):
        assert np.allclose(_face_center(rects[fi]), side)


def test_grass_down_uses_dirt() -> None:
    """DOWN травы — ``dirt``."""
    atlas = _atlas()
    rects = atlas.face_rects(np.asarray([_grass_state()]))[0]
    assert np.allclose(
        _face_center(rects[5]), _sprite_center(atlas, "minecraft:block/dirt")
    )


# ---------------------------------------------------------------------------
# v_color: tint грани
# ---------------------------------------------------------------------------

def test_grass_tint_applied() -> None:
    """UP травы: v_color = биомный tint (не белый и не 0). Спуск — белый."""
    atlas = _atlas()
    state = _grass_state()
    blocks = np.zeros((16, 16, 16), dtype=np.uint16)
    blocks[8, 8, 8] = state
    vertices, _ = mesh_chunk(blocks, atlas, center=False)

    up = _face_vertices(vertices, 4)[:, 8:12]
    expected = np.asarray(grass_color(), dtype=np.float32) / 255.0
    assert np.allclose(up[:, :3], expected[None, :], atol=1e-4)
    assert not np.allclose(up[:, :3], 1.0)  # не белый
    assert float(up[:, :3].sum()) > 0.0  # не 0 (чёрный множитель)

    down = _face_vertices(vertices, 5)[:, 8:12]
    assert np.allclose(down[:, :3], 1.0)  # низ (земля) без tint


def test_grass_tint_green() -> None:
    """Tint из colormap (plains): зелёная компонента > красной и синей."""
    r, g, b = grass_color()
    assert g > r and g > b


def test_grass_side_tint_white() -> None:
    """Бок травы не тонируется вершиной: оверлей запечён в тайл (FALLBACK)."""
    atlas = _atlas()
    tints = atlas.face_tints(np.asarray([_grass_state()]))[0]
    for fi in (0, 1, 2, 3):
        assert np.allclose(tints[fi, :3], 255)


# ---------------------------------------------------------------------------
# оверлей бока
# ---------------------------------------------------------------------------

def test_grass_side_overlay() -> None:
    """Оверлей есть и запечён в бок: верхняя кромка бока зелёная."""
    atlas = _atlas()
    assert atlas.has_texture("minecraft:block/grass_block_side_overlay")
    x, y, w, h = atlas._sprite_rects["minecraft:block/grass_block_side"]
    tile = atlas.image[y : y + h, x : x + w, :3].astype(np.int32)
    top_row = tile[0].mean(axis=0)
    bottom_row = tile[-1].mean(axis=0)
    # верхняя кромка — трава (G > R, G > B), низ — земля.
    assert top_row[1] > top_row[0] and top_row[1] > top_row[2], top_row
    assert bottom_row[0] >= bottom_row[1], bottom_row


# ---------------------------------------------------------------------------
# ориентация UV (не перевёрнута)
# ---------------------------------------------------------------------------

def test_uv_not_flipped() -> None:
    """Бок: верх блока берёт верх спрайта (v растёт вниз, как Rust)."""
    atlas = _atlas()
    state = _grass_state()
    blocks = np.zeros((16, 16, 16), dtype=np.uint16)
    blocks[8, 8, 8] = state
    vertices, _ = mesh_chunk(blocks, atlas, center=False)
    u0, v0, du, dv = atlas.face_rects(np.asarray([state]))[0][0]  # south
    face = _face_vertices(vertices, 0)
    top = face[np.isclose(face[:, 1] - 8.0, 1.0)]
    bottom = face[np.isclose(face[:, 1] - 8.0, 0.0)]
    assert (top[:, 7] - v0).max() / dv < 0.5  # верх → верх спрайта
    assert (bottom[:, 7] - v0).min() / dv > 0.5  # низ → низ спрайта


# ---------------------------------------------------------------------------
# offscreen-рендер: трава не чёрная
# ---------------------------------------------------------------------------

def test_grass_not_black() -> None:
    """Offscreen-рендер куба травы: не чёрный, верх зелёный, низ коричневый."""
    try:
        import moderngl
    except Exception as err:  # pragma: no cover - нет moderngl/GL
        pytest.skip(f"нет moderngl: {err}")
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as err:  # pragma: no cover - нет дисплея/GL
        pytest.skip(f"нет OpenGL-контекста: {err}")

    from quadrix.render.backend_moderngl import load_shader
    from quadrix.render.camera import Camera

    width, height = 160, 120
    atlas = _atlas()
    try:
        fbo = ctx.simple_framebuffer((width, height))
        fbo.use()
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.CULL_FACE)
        ctx.clear(0.1, 0.12, 0.16, 1.0)

        prog = ctx.program(
            vertex_shader=load_shader("terrain.vert"),
            fragment_shader=load_shader("terrain.frag"),
        )
        prog["light_dir"] = (0.2, 1.0, -0.3)
        prog["ambient"] = 0.35

        texture = ctx.texture(atlas.size, 4, atlas.image.tobytes())
        texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
        texture.use(location=0)
        prog["texture0"] = 0

        blocks = np.zeros((16, 16, 16), dtype=np.uint16)
        blocks[8, 8, 8] = _grass_state()
        vertices, _ = mesh_chunk(blocks, atlas, center=False)
        vbo = ctx.buffer(np.ascontiguousarray(vertices, np.float32).tobytes())
        vao = ctx.vertex_array(
            prog,
            [(vbo, "3f 3f 2f 4f", "in_pos", "in_normal", "in_uv", "in_color")],
        )

        camera = Camera(
            position=(11.5, 12.0, 11.5), yaw=135.0, pitch=30.0, fov=70.0
        )
        mvp = camera.view_projection(width, height)
        prog["mvp"].write(np.asarray(mvp, np.float32).T.tobytes())
        vao.render(moderngl.TRIANGLES, vertices=vertices.shape[0])

        data = fbo.read(components=4, alignment=1)
        pixels = np.frombuffer(data, np.uint8).reshape(height, width, 4)
        pixels = np.flipud(pixels)
        rgb = pixels[:, :, :3].astype(np.float32)
        background = np.array([0.1, 0.12, 0.16]) * 255.0
        mask = np.abs(rgb - background).sum(axis=2) > 12.0
        assert int(mask.sum()) > 0, "трава не нарисована"
        object_pixels = rgb[mask]
        # не чёрная: суммарная яркость объекта заметно выше нуля.
        assert float(object_pixels.mean()) > 20.0

        ys, xs = np.where(mask)
        y0, y1 = int(ys.min()), int(ys.max())
        top_cut = y0 + max(1, (y1 - y0) // 3)
        top = rgb[ys[ys <= top_cut], xs[ys <= top_cut]]
        top_mean = top.mean(axis=0)
        # верхняя треть — грань UP (трава): зелёная.
        assert top_mean[1] > top_mean[0] and top_mean[1] > top_mean[2], top_mean
        fbo.release()
    finally:
        ctx.release()
