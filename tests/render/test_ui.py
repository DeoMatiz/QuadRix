"""Тесты UI-примитивов QuadRix (GUI PART 1).

Проверяем реальные данные из ``.local``: шрифт грузится из настоящего
``ascii.png`` + ``font/default.json``, метрики совпадают с ванильными,
батч делает ровно один draw call, кнопка и слайдер работают.
"""

from __future__ import annotations

import functools
from pathlib import Path

import numpy as np
import pytest

from quadrix.core.text import Text
from quadrix.render.backend_moderngl import load_shader
from quadrix.render.ui import (
    ASCII_PNG,
    Batch,
    Button,
    Font,
    Glyph,
    Layout,
    Quad,
    Rect,
    Slider,
    WHITE,
    load_png_rgba,
    rgba,
    rgba_channels,
)


@functools.lru_cache(maxsize=1)
def _font() -> Font:
    """Шрифт по умолчанию из ``.local`` (загружаем один раз на модуль)."""
    return Font.load()


# ---------------------------------------------------------------------------
# цвет / геометрия
# ---------------------------------------------------------------------------

def test_rgba_packs_like_horizon() -> None:
    # hud.rs::rgba: a<<24 | b<<16 | g<<8 | r
    assert rgba(0x11, 0x22, 0x33, 0x44) == 0x44332211
    assert rgba_channels(0x44332211) == (0x11, 0x22, 0x33, 0x44)
    assert WHITE == 0xFFFFFFFF


def test_quad_fields_and_positions() -> None:
    q = Quad(x=1.0, y=2.0, w=3.0, h=4.0, u0=0.0, v0=0.1, u1=0.5, v1=0.6, color=WHITE)
    assert (q.x, q.y, q.w, q.h) == (1.0, 2.0, 3.0, 4.0)
    assert (q.u0, q.v0, q.u1, q.v1) == (0.0, 0.1, 0.5, 0.6)
    assert q.color == WHITE
    assert q.positions() == [(1.0, 2.0), (4.0, 2.0), (4.0, 6.0), (1.0, 6.0)]
    assert q.uvs() == [(0.0, 0.1), (0.5, 0.1), (0.5, 0.6), (0.0, 0.6)]


def test_layout_contains_and_center() -> None:
    layout = Layout(10.0, 20.0, 100.0, 40.0)
    assert layout.contains(10.0, 20.0)
    assert not layout.contains(110.0, 20.0)  # правая граница исключена
    assert layout.centered(20.0, 8.0) == (50.0, 36.0)


# ---------------------------------------------------------------------------
# шрифт
# ---------------------------------------------------------------------------

def test_font_width_matches_vanilla_metrics() -> None:
    font = _font()
    # 'a' — обрезанная ширина 5 → advance = floor(0.5+5)+1 = 6
    assert font.width("a") == 6
    # пробел — из include/space.json (advance 4), а не из ascii.png
    assert font.width(" ") == 4
    # линейность для одинаковых символов
    assert font.width("aaaaa") == 5 * font.width("a")
    assert font.width("hello") == 24
    assert font.width("") == 0


def test_font_render_returns_quads() -> None:
    font = _font()
    quads = font.render("a", 0.0, 0.0, WHITE)
    assert isinstance(quads, list) and len(quads) == 1
    q = quads[0]
    assert isinstance(q, Quad)
    assert q.color == WHITE
    # ванильная геометрия ячейки ascii 8x8, top = 7 - ascent(7) = 0
    assert (q.x, q.y, q.w, q.h) == (0.0, 0.0, 8.0, 8.0)
    assert 0.0 <= q.u0 < q.u1 <= 1.0
    assert 0.0 <= q.v0 < q.v1 <= 1.0


def test_font_render_advances_and_empty() -> None:
    font = _font()
    assert font.render("", 0.0, 0.0, WHITE) == []
    # пробел не даёт квада, но сдвигает п... проверяем сдвиг второго глифа
    quads = font.render("a a", 0.0, 0.0, WHITE)
    assert len(quads) == 2
    assert quads[1].x == font.width("a ")  # 6 + 4 = 10


def test_font_atlas_from_real_ascii_png() -> None:
    assert ASCII_PNG.exists()
    ascii_rgba = load_png_rgba(ASCII_PNG)
    assert ascii_rgba.shape == (128, 128, 4)
    assert ascii_rgba[..., 3].any()  # в реальном PNG есть непрозрачные пиксели

    font = _font()
    aw, ah = font.atlas_size
    assert font.atlas_image.shape == (ah, aw, 4)
    assert font.white.u0 < font.white.u1 and font.white.v0 < font.white.v1


# ---------------------------------------------------------------------------
# батч
# ---------------------------------------------------------------------------

class _MockBackend:
    """Считает draw-вызовы; ничего на GPU не делает."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def draw(self, vbo, program=None, texture=None, **kwargs) -> None:
        self.calls.append((vbo, program, texture, kwargs))


def test_batch_add_quad_flush_one_draw_call() -> None:
    batch = Batch()
    assert batch.flush(_MockBackend()) == 0  # пусто — draw не зовём

    backend = _MockBackend()
    batch.add_quads(_font().render("ab", 0.0, 0.0, WHITE))
    assert len(batch.quads) == 2

    count = batch.flush(backend)
    assert count == 2 * 6  # два треугольника на квад
    assert len(backend.calls) == 1  # ровно один draw call
    vbo, _program, _texture, kwargs = backend.calls[0]
    assert vbo.shape == (12, 8)  # pos(2)+uv(2)+color(4)
    assert kwargs["count"] == 12
    assert kwargs["attributes"] == ("in_pos", "in_uv", "in_color")
    # батч очищен после flush
    assert batch.quads == []


def test_batch_vertices_format() -> None:
    batch = Batch()
    batch.add_quad(Quad(0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, WHITE))
    data = batch.vertices()
    assert data.dtype == np.float32
    assert data.shape == (6, 8)
    assert np.allclose(data[0], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])


# ---------------------------------------------------------------------------
# кнопка
# ---------------------------------------------------------------------------

def test_button_render_adds_background_and_text() -> None:
    font = _font()
    batch = Batch()
    button = Button(10.0, 20.0, 100.0, 20.0, Text.literal("Done"))
    button.render(batch, font)
    n_quads = len(batch.quads)
    # 1 фон + (тень + текст) глифов "Done"
    assert n_quads > 1
    assert batch.quads[0].x == 10.0 and batch.quads[0].y == 20.0
    assert batch.quads[0].w == 100.0 and batch.quads[0].h == 20.0


def test_button_on_click_triggered() -> None:
    hits: list[int] = []
    button = Button(0.0, 0.0, 50.0, 20.0, "OK", on_click=lambda: hits.append(1))

    assert button.handle_click(100.0, 100.0) is False  # вне кнопки
    assert hits == []

    assert button.handle_click(25.0, 10.0) is True
    assert hits == [1]

    # неактивная кнопка клик не принимает
    button.active = False
    assert button.click() is False
    assert hits == [1]

    # прямая проверка __contains__
    assert button.contains(25.0, 10.0)


# ---------------------------------------------------------------------------
# слайдер
# ---------------------------------------------------------------------------

def test_slider_value_min_max_and_on_change() -> None:
    changes: list[float] = []
    slider = Slider(0.0, 0.0, 100.0, 20.0, value=0.0, min=0.0, max=10.0,
                    on_change=changes.append)

    slider.set_value(5.0)
    assert slider.value == 5.0
    assert changes == [5.0]
    assert slider.fraction() == pytest.approx(0.5)

    slider.set_value(100.0)  # клампится к max
    assert slider.value == 10.0
    assert changes[-1] == 10.0

    slider.set_value(-5.0)  # клампится к min
    assert slider.value == 0.0
    assert changes[-1] == 0.0

    prev = len(changes)
    slider.set_value(0.0)  # без изменения — on_change не зовётся
    assert len(changes) == prev


def test_slider_click_and_render() -> None:
    slider = Slider(0.0, 0.0, 100.0, 20.0, value=0.0, min=0.0, max=1.0)
    # клик в правый край дорожки → около max
    assert slider.click(100.0) is True
    assert slider.value == pytest.approx(1.0)

    font = _font()
    batch = Batch()
    slider.render(batch, font)
    assert len(batch.quads) >= 2  # дорожка + ручка


def test_slider_release_stops_dragging() -> None:
    """Нажатие берёт ручку, отпускание — снимает (порт options_ui::release)."""
    slider = Slider(0.0, 0.0, 100.0, 20.0, value=0.0, min=0.0, max=1.0)
    assert slider.dragging is False

    # options_ui.rs L4251-4257: press → dragging = Some(opt), value from mouse.
    assert slider.handle_click(50.0, 10.0) is True
    assert slider.dragging is True
    assert slider.focused is True
    assert slider.value == pytest.approx((50.0 - 4.0) / 92.0)

    # options_ui.rs::release: self.dragging.take().
    assert slider.handle_release() is True
    assert slider.dragging is False
    # повторное отпускание — уже не в drag
    assert slider.handle_release() is False
    # клик вне дорожки ручку не берёт
    assert slider.handle_click(500.0, 10.0) is False
    assert slider.dragging is False


def test_slider_drag_then_release() -> None:
    """После release движение мыши больше не меняет значение (без «прилипания»)."""
    slider = Slider(0.0, 0.0, 100.0, 20.0, value=0.0, min=0.0, max=1.0)
    slider.handle_click(10.0, 10.0)
    assert slider.dragging is True
    before = slider.value

    # drag тянет ручку, пока кнопка зажата (drag-ветка options_ui.rs L4093-4120).
    assert slider.handle_drag(90.0) is True
    assert slider.value == pytest.approx((90.0 - 4.0) / 92.0)
    assert slider.value != before

    # отпускание замораживает значение
    assert slider.handle_release() is True
    assert slider.dragging is False
    frozen = slider.value
    assert slider.handle_drag(5.0) is False
    assert slider.value == frozen


# ---------------------------------------------------------------------------
# шейдеры
# ---------------------------------------------------------------------------

def test_ui_shaders_glsl_330() -> None:
    vert = load_shader("ui.vert")
    frag = load_shader("ui.frag")
    assert vert.startswith("#version 330 core")
    assert frag.startswith("#version 330 core")
    assert "uniform mat4 projection" in vert
    assert "in vec2 in_pos" in vert
    assert "in vec2 in_uv" in vert
    assert "in vec4 in_color" in vert
    assert "uniform sampler2D texture0" in frag
    assert "texture(texture0, v_uv)" in frag


def test_ui_shaders_compile() -> None:
    try:
        import moderngl

        ctx = moderngl.create_standalone_context()
    except Exception as err:  # pragma: no cover - нет дисплея/GL
        pytest.skip(f"нет OpenGL-контекста: {err}")

    try:
        program = ctx.program(
            vertex_shader=load_shader("ui.vert"),
            fragment_shader=load_shader("ui.frag"),
        )
        assert "projection" in program
        assert "texture0" in program
        assert "in_pos" in program
    finally:
        ctx.release()
