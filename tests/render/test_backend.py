"""Тесты render-фундамента QuadRix: бэкенды, атлас, шейдеры.

Окно создаётся только в smoke-тесте; без дисплея он честно скипается.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from quadrix.render.backend import BackendType, RenderBackend, create_backend
from quadrix.render.backend_moderngl import ModernglBackend, load_shader
from quadrix.render.mesher import mesh_chunk
from quadrix.render.texture_atlas import STONE_TEXTURE_PATH, TextureAtlas


# ---------------------------------------------------------------------------
# бэкенды
# ---------------------------------------------------------------------------

def test_create_moderngl_backend_without_window() -> None:
    """Фабрика не открывает окно — только объект-конфигурацию."""
    backend = create_backend(BackendType.MODERNGL, 800, 600, "QuadRix test")

    assert isinstance(backend, ModernglBackend)
    assert isinstance(backend, RenderBackend)  # structural protocol
    assert (backend.width, backend.height, backend.title) == (800, 600, "QuadRix test")
    # контекст ещё не создан: тест работает в CI без дисплея
    assert backend.window is None
    assert backend.ctx is None


def test_create_wgpu_backend() -> None:
    """WGPU: либо RuntimeError (нет пакета), либо заготовка WgpuBackend."""
    if importlib.util.find_spec("wgpu") is None:
        with pytest.raises(RuntimeError, match="wgpu"):
            create_backend(BackendType.WGPU, 320, 240, "QuadRix")
        return

    from quadrix.render.backend_wgpu import WgpuBackend

    backend = create_backend(BackendType.WGPU, 320, 240, "QuadRix")
    assert isinstance(backend, WgpuBackend)
    assert backend.width == 320


def test_wgpu_backend_is_pending() -> None:
    """Заготовка wgpu не притворяется рабочим бэкендом."""
    if importlib.util.find_spec("wgpu") is None:
        pytest.skip("wgpu не установлен")

    from quadrix.render.backend_wgpu import WgpuBackend

    backend = WgpuBackend()
    for call in (
        backend.create_context,
        backend.present,
        backend.close,
        lambda: backend.create_pipeline("v", "f"),
        lambda: backend.draw(None, None, None),
    ):
        with pytest.raises(NotImplementedError, match="use moderngl"):
            call()


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="backend_type"):
        create_backend("opengl", 10, 10, "QuadRix")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# атлас
# ---------------------------------------------------------------------------

def _stone_state_id() -> int:
    from quadrix.world.registry import BlockRegistry

    registry = BlockRegistry.load(Path(".local/horizon-client-motion/block-registry.nbt"))
    stone = registry.default_state("minecraft:stone")
    assert stone is not None
    return stone.id


def test_texture_atlas_loads_real_stone_png() -> None:
    assert STONE_TEXTURE_PATH.exists()

    atlas = TextureAtlas.load_default()
    assert atlas.image.shape == (16, 16, 4)
    assert atlas.size == (16, 16)

    u, v, w, h = atlas.load(_stone_state_id())
    assert (u, v, w, h) == (0.0, 0.0, 1.0, 1.0)
    assert all(0.0 <= c <= 1.0 for c in (u, v, w, h))


def test_texture_atlas_load_many_matches_load() -> None:
    atlas = TextureAtlas.load_default()
    ids = np.asarray([1, 1, 1, 1], dtype=np.uint16)

    rects = atlas.load_many(ids)
    assert rects.shape == (4, 4)
    assert np.allclose(rects[0], np.asarray(atlas.load(1)))


# ---------------------------------------------------------------------------
# шейдеры
# ---------------------------------------------------------------------------

def test_terrain_shaders_are_glsl_330() -> None:
    vert = load_shader("terrain.vert")
    frag = load_shader("terrain.frag")

    assert vert.startswith("#version 330 core")
    assert frag.startswith("#version 330 core")
    assert "uniform mat4 mvp" in vert
    assert "out vec3 v_normal" in vert
    assert "out vec2 v_uv" in vert
    assert "uniform sampler2D texture0" in frag
    assert "uniform vec3 light_dir" in frag
    assert "uniform float ambient" in frag


# ---------------------------------------------------------------------------
# smoke: окно + draw + present (нужен дисплей)
# ---------------------------------------------------------------------------

def test_moderngl_draw_present_close_smoke() -> None:
    backend = create_backend(BackendType.MODERNGL, 64, 64, "QuadRix smoke")
    try:
        ctx = backend.create_context()
    except RuntimeError as err:
        pytest.skip(f"нет дисплея/OpenGL: {err}")

    try:
        program = backend.create_pipeline(
            load_shader("terrain.vert"), load_shader("terrain.frag")
        )
        atlas = TextureAtlas.load_default()
        texture = ctx.texture(atlas.size, 4, atlas.rgba_bytes)
        assert texture.size == atlas.size

        blocks = np.zeros((16, 16, 16), dtype=np.uint16)
        blocks[8, 8, 8] = 1
        vertices, indices = mesh_chunk(blocks, atlas)
        assert indices is None
        assert vertices.shape == (36, 8)

        mvp = np.identity(4, dtype=np.float32)
        backend.draw(vertices, program, texture, count=vertices.shape[0], mvp=mvp)

        # скриншот читается ДО present()
        pixels = backend.read_screen()
        assert pixels.ndim == 3
        assert pixels.shape[2] == 4
        assert pixels.any()  # хотя бы цвет очистки

        backend.present()
        assert backend.should_close() is False
    finally:
        backend.close()

    # повторное закрытие безопасно
    backend.close()
    with pytest.raises(RuntimeError):
        backend.present()
