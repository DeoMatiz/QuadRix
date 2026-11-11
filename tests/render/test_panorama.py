"""Тесты панорамы главного меню (порт Horizon ``gfx/panorama.rs``).

Проверяем реальные данные из ``.local``: шесть лиц ``panorama_*.png``
грузятся в порядке ``FACE_ORDER`` с перевёрнутыми по Y строками
(``CubeMapTexture``), проекция совпадает с Rust-тестом, поворот
накапливается как ``Rotation::update``, а GPU-часть рисует куб через
``gl_VertexID`` без вершинного буфера.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from quadrix.render.panorama import (
    FACE_ORDER,
    FALLBACK_COLOUR,
    PANORAMA_FOV,
    PACK_ROOT,
    TITLE_PITCH,
    Faces,
    Panorama,
    Rotation,
    projection,
)
from quadrix.render.ui import load_png_rgba

BACKGROUND = PACK_ROOT / "assets/minecraft/textures/gui/title/background"


# ---------------------------------------------------------------------------
# константы и поворот
# ---------------------------------------------------------------------------

def test_face_order_and_view_constants_match_rust() -> None:
    assert FACE_ORDER == (1, 3, 5, 4, 0, 2)  # CubeMapTexture.SUFFIXES
    assert TITLE_PITCH == 10.0               # game.rs: pitch: 10.0
    assert PANORAMA_FOV == 85.0              # CubeMap.render
    assert FALLBACK_COLOUR == (96, 110, 111, 255)


def test_rotation_update_matches_rust_test() -> None:
    # gfx/panorama.rs::tests::rotation_speed_changes_preserve_position.
    rotation = Rotation()
    assert rotation.update(5.0, 1.0) == pytest.approx(-10.0)
    assert rotation.update(10.0, 0.0) == pytest.approx(-10.0)
    assert rotation.update(12.0, 0.5) == pytest.approx(-12.0)
    assert rotation.update(13.0, 1.0) == pytest.approx(-14.0)


def test_projection_pitch_matches_rust_test() -> None:
    # gfx/panorama.rs::tests::vanilla_camera_centres_positive_z_face...
    straight = projection(1920, 1080, 0.0, 0.0) @ np.array([0.0, 0.0, 1.0, 1.0])
    assert abs(straight[0] / straight[3]) < 1e-6
    assert abs(straight[1] / straight[3]) < 1e-6
    assert straight[3] > 0.0

    pitched = projection(1920, 1080, 0.0, 10.0) @ np.array([0.0, 0.0, 1.0, 1.0])
    expected = math.tan(math.radians(10.0)) / math.tan(math.radians(42.5))
    assert (pitched[1] / pitched[3]) == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# Faces: реальные PNG + flipud
# ---------------------------------------------------------------------------

def test_faces_load_real_panorama() -> None:
    faces = Faces.load()
    assert faces.loaded is True
    assert faces.size == 1024
    assert faces.texels.shape == (6, 1024, 1024, 4)
    assert len(faces.bytes()) == 6 * 1024 * 1024 * 4


def test_faces_flip_rows_like_cubemap_texture() -> None:
    raw = load_png_rgba(BACKGROUND / "panorama_1.png")  # FACE_ORDER[0] == 1
    faces = Faces.load()
    assert np.array_equal(faces.texels[0], np.flipud(raw))


def test_faces_colour_fallback_is_one_texel() -> None:
    faces = Faces.colour(FALLBACK_COLOUR)
    assert faces.loaded is False
    assert faces.size == 1
    assert faces.texels.shape == (6, 1, 1, 4)
    assert len(faces.bytes()) == 24
    assert tuple(faces.texels[0, 0, 0]) == FALLBACK_COLOUR


def test_faces_load_missing_root_falls_back() -> None:
    faces = Faces.load("no/such/root")
    assert faces.loaded is False
    assert faces.size == 1


# ---------------------------------------------------------------------------
# Panorama: prepare / draw (фейковый бэкенд)
# ---------------------------------------------------------------------------

class _Uniform:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self._name = name

    def write(self, data: bytes) -> None:
        self._store[self._name] = data


class _Program:
    def __init__(self) -> None:
        self.uniforms: dict[str, bytes] = {}

    def __getitem__(self, name: str) -> _Uniform:
        return _Uniform(self.uniforms, name)

    def __setitem__(self, name: str, value) -> None:
        self.uniforms[name] = value

    def __contains__(self, name: str) -> bool:
        return True


class _PanoBackend:
    def __init__(self) -> None:
        self.pipelines = 0
        self.cubes = 0
        self.draws: list = []
        self.program = _Program()

    def create_pipeline(self, vert: str, frag: str) -> _Program:
        self.pipelines += 1
        return self.program

    def create_cube_texture(self, faces: Faces) -> object:
        self.cubes += 1
        self.faces = faces
        return object()

    def draw_panorama(self, cube, program, proj) -> None:
        self.draws.append((cube, program, proj))


def test_panorama_prepare_and_draw_uses_projection() -> None:
    pano = Panorama(Faces.colour(FALLBACK_COLOUR))
    backend = _PanoBackend()

    pano.prepare(backend)
    assert backend.pipelines == 1
    assert backend.cubes == 1

    assert pano.draw(backend, 800, 600, 90.0) is True
    assert len(backend.draws) == 1
    _cube, program, proj = backend.draws[0]
    assert program is backend.program
    assert proj.shape == (4, 4)
    assert np.allclose(proj, projection(800, 600, 90.0, TITLE_PITCH))


def test_panorama_draw_without_gpu_returns_false() -> None:
    pano = Panorama(Faces.colour(FALLBACK_COLOUR))
    assert pano.draw(_PanoBackend(), 320, 240, 0.0) is False


def test_panorama_release_drops_cube() -> None:
    pano = Panorama(Faces.colour(FALLBACK_COLOUR))
    backend = _PanoBackend()
    pano.prepare(backend)
    assert pano.cube is not None
    pano.release()
    assert pano.cube is None


# ---------------------------------------------------------------------------
# ModernglBackend: кубмап-текстура + отрисовка куба
# ---------------------------------------------------------------------------

class _RecordingVao:
    def __init__(self, events: list) -> None:
        self._events = events

    def render(self, mode, vertices: int) -> None:
        self._events.append(("render", mode, vertices))

    def release(self) -> None:
        self._events.append(("release",))


class _FakeCube:
    def __init__(self) -> None:
        self.filter = None
        self.used: list[int] = []

    def use(self, location: int) -> None:
        self.used.append(location)


class _FakeCtx:
    def __init__(self) -> None:
        self.events: list = []
        self.cube_args: tuple | None = None
        self.viewport = (0, 0, 0, 0)

    def texture_cube(self, size, components, data) -> _FakeCube:
        self.cube_args = (size, components, len(data))
        return _FakeCube()

    def enable(self, flag) -> None:
        self.events.append(("enable", flag))

    def disable(self, flag) -> None:
        self.events.append(("disable", flag))

    def vertex_array(self, program, attributes) -> _RecordingVao:
        return _RecordingVao(self.events)


def test_moderngl_create_cube_texture_and_draw_panorama() -> None:
    import moderngl

    from quadrix.render.backend_moderngl import ModernglBackend

    backend = ModernglBackend()
    ctx = _FakeCtx()
    backend.ctx = ctx

    faces = Faces.colour(FALLBACK_COLOUR)
    cube = backend.create_cube_texture(faces)

    assert ctx.cube_args == ((1, 1), 4, 24)
    assert cube.filter == (moderngl.LINEAR, moderngl.LINEAR)

    program = _Program()
    backend.draw_panorama(cube, program, np.eye(4, dtype=np.float32))

    assert ("disable", moderngl.CULL_FACE) in ctx.events
    assert ("disable", moderngl.DEPTH_TEST) in ctx.events
    assert ("disable", moderngl.BLEND) in ctx.events
    assert ("render", moderngl.TRIANGLES, 36) in ctx.events
    assert cube.used == [0]
    assert "projection" in program.uniforms


def test_moderngl_resize_updates_viewport() -> None:
    from quadrix.render.backend_moderngl import ModernglBackend

    backend = ModernglBackend()
    backend.ctx = _FakeCtx()

    backend.resize(640, 480)

    assert (backend.width, backend.height) == (640, 480)
    assert backend.ctx.viewport == (0, 0, 640, 480)
