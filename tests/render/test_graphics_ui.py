"""Тесты экрана графики (порт graphics_ui.rs / settings_shell.rs / graphics_style.rs)."""

from __future__ import annotations

import math

import pytest

from quadrix.core import lang
from quadrix.render import graphics as gfx
from quadrix.render import graphics_ui as gui
from quadrix.render.menu import Settings, load_language
from quadrix.render.ui import Batch


@pytest.fixture(autouse=True)
def _english() -> None:
    """Английский язык: поиск и подписи сравниваются с текстами Rust."""
    lang.set(load_language("en_us"))


def _screen(page: str = "General", settings: Settings | None = None,
            stack=None, width: float = 854.0, height: float = 480.0) -> gui.GraphicsScreen:
    screen = gui.GraphicsScreen(
        settings=settings if settings is not None else Settings(),
        stack=stack, width=width, height=height, framebuffer=(854, 480),
    )
    screen.page = page
    return screen


def _point(screen: gui.GraphicsScreen, kind: str, name: str) -> tuple[float, float]:
    """Центр строки, прокрутив список так, чтобы она была видна."""
    cols, lines, content = screen.layout(screen.settings)
    line = next(
        l for l in lines
        if l.setting is not None and l.setting.kind == kind and l.setting.name == name
    )
    height = cols.bottom - cols.top
    screen.scroll = max(0.0, min(line.y - 20.0, max(content - height, 0.0)))
    cols, lines, _content = screen.layout(screen.settings)
    line = next(
        l for l in lines
        if l.setting is not None and l.setting.kind == kind and l.setting.name == name
    )
    return cols.list_x + 20.0, screen.row_y(cols, line) + 10.0


# ---------------------------------------------------------------------------
# данные и значения по умолчанию
# ---------------------------------------------------------------------------

def test_six_pages_and_default_hidden_upscaling() -> None:
    assert gui.gfx.GRAPHICS_PAGE_NAMES == [
        "General", "Quality", "Performance", "Shaders", "Advanced", "HDR",
    ]
    settings = Settings()
    general, _content = _screen("General", settings).lines(settings)
    names = [l.setting.name for l in general if l.setting is not None]
    assert "RenderDistance" in names and "GuiScale" in names

    quality, _ = _screen("Quality", settings).lines(settings)
    assert "Upscaling" not in [l.setting.name for l in quality if l.setting is not None]
    settings.horizon.taa = True
    quality, _ = _screen("Quality", settings).lines(settings)
    assert "Upscaling" in [l.setting.name for l in quality if l.setting is not None]


def test_vanilla_graphics_defaults_match_settings_rs() -> None:
    s = Settings()
    assert (s.cloud_range, s.particles, s.mipmap_levels) == (128, 0, 4)
    assert (s.biome_blend, s.weather_radius, s.attack_indicator) == (2, 10, 1)
    assert math.isclose(s.chunk_fade, 0.75)
    assert s.inactivity_fps_limit == "afk"
    assert s.prioritize_chunk_updates == 0
    assert s.graphics_preset == "fancy"
    assert s.video_modes == [] and s.video_mode_index() == -1

    # options.txt round-trip сохраняет ванильные графические ключи.
    text = "fov:70\ncloudRange:64\nchunkSectionFadeInTime:1.5\n" \
           "inactivityFpsLimit:minimized\nprioritizeChunkUpdates:2\n"
    parsed = Settings.parse(text)
    assert parsed.cloud_range == 64
    assert math.isclose(parsed.chunk_fade, 1.5)
    assert parsed.inactivity_fps_limit == "minimized"
    assert parsed.prioritize_chunk_updates == 2
    assert parsed.to_file()["cloudRange"] == 64


# ---------------------------------------------------------------------------
# клики: слайдер, чекбокс, циклер
# ---------------------------------------------------------------------------

def test_slider_click_sets_value_and_marks_preset_custom() -> None:
    s = Settings(render_distance=12)
    screen = _screen("General", s)
    cols, _l, _c = screen.layout(s)
    tx, tw = cols.track()
    # Трек: value = round(2 + f * (32-2)); берём f = 0.5 → 17.
    x = tx + 5.0 + 0.5 * (tw - 10.0)
    y = _point(screen, "Opt", "RenderDistance")[1]
    assert screen.handle_click(x, y) is True
    assert s.render_distance == 17
    assert s.graphics_preset == "custom"
    assert screen.changed is True


def test_switch_row_toggles_and_undo_restores() -> None:
    s = Settings(smooth_lighting=True)
    screen = _screen("Quality", s)
    x, y = _point(screen, "Opt", "SmoothLighting")
    assert screen.handle_click(x, y) is True
    assert s.smooth_lighting is False
    assert screen.changed is True

    cols, _l, _c = screen.layout(s)
    undo = cols.button(1)
    assert screen.handle_click(undo[0] + 2.0, undo[1] + 2.0) is True
    assert s.smooth_lighting is True
    assert screen.changed is False


def test_cycler_rows_step_forward() -> None:
    s = Settings(clouds="true")
    screen = _screen("Quality", s)
    x, y = _point(screen, "Opt", "Clouds")
    screen.handle_click(x, y)
    # Порядок Horizon [false, fast, true]: «true» -> «false».
    assert s.clouds == "false"
    x, y = _point(screen, "Opt", "Clouds")
    screen.handle_click(x, y)
    assert s.clouds == "fast"


def test_blocked_hdr_row_does_nothing() -> None:
    s = Settings()
    screen = _screen("HDR", s)
    assert gfx.item_blocked(s, "H", "Hdr") is not None
    x, y = _point(screen, "H", "Hdr")
    assert screen.handle_click(x, y) is True
    assert s.horizon.hdr is False
    assert screen.changed is False


# ---------------------------------------------------------------------------
# поиск, список и полоса описания
# ---------------------------------------------------------------------------

def test_search_spans_pages_and_shows_page_lines() -> None:
    s = Settings()
    screen = _screen("General", s)
    screen.search = "worker threads"
    lines, _content = screen.lines(s)
    pages = {line.page for line in lines}
    assert pages == {"Performance"}
    assert any(line.setting is not None and line.setting.name == "Workers" for line in lines)
    # Пока идёт поиск, у страницы есть строка-заголовок (group None, setting None).
    assert any(line.group is None and line.setting is None for line in lines)

    screen.search = "zzz-nothing"
    lines, _content = screen.lines(s)
    assert lines == []


def test_dock_describes_hovered_row_with_cost() -> None:
    s = Settings()
    screen = _screen("General", s)
    x, y = _point(screen, "Opt", "RenderDistance")
    cols, lines, _c = screen.layout(s)
    screen.cursor = (x, y)
    described = screen._described(cols, lines)
    assert described is not None and described.name == "RenderDistance"
    assert gfx.cost_label(described.cost) in {
        "No cost", "Low cost", "Medium cost", "High cost", "Saves time",
    }
    assert gui._description(s, described)


def test_click_on_page_tab_switches_page() -> None:
    s = Settings()
    screen = _screen("General", s)
    cols = gui.Columns.of(screen.width, screen.height)
    rect = cols.page(2)  # Performance
    assert screen.handle_click(rect[0] + 4.0, rect[1] + 4.0) is True
    assert screen.page == "Performance"
    _lines, _c = screen.lines(s)
    assert any(line.page == "Performance" for line in _lines)


# ---------------------------------------------------------------------------
# Done / Escape / прокрутка
# ---------------------------------------------------------------------------

class _Stack:
    def __init__(self) -> None:
        self.pops = 0

    def pop(self):
        self.pops += 1


def test_done_button_and_escape_close_screen() -> None:
    stack = _Stack()
    screen = _screen("General", stack=stack)
    cols = gui.Columns.of(screen.width, screen.height)
    done = cols.button(0)
    assert screen.handle_click(done[0] + 2.0, done[1] + 2.0) is True
    assert stack.pops == 1

    assert screen.handle_key("escape") is True
    assert stack.pops == 2


def test_search_field_takes_typing_and_clear_button() -> None:
    s = Settings()
    screen = _screen("General", s)
    cols = gui.Columns.of(screen.width, screen.height)
    search = cols.search()
    screen.handle_click(search[0] + 4.0, search[1] + 4.0)
    screen.scroll = 50.0
    assert screen.handle_key("key", "w") is True
    assert screen.handle_key("key", "o") is True
    assert screen.search == "wo"
    # Ввод поиска возвращает список к началу (graphics_ui.rs::searched).
    assert screen.scroll == 0.0

    clear = cols.clear()
    screen.handle_click(clear[0] + 2.0, clear[1] + 2.0)
    assert screen.search == ""


def test_percent_labels_show_one_percent_sign() -> None:
    s = Settings(entity_distance=1.0)
    assert gfx.item_label(s, "Opt", "EntityDistance").endswith("100%")
    assert gfx.item_label(s, "H", "ResolutionScale").endswith("100%")


def test_scroll_is_clamped_to_content() -> None:
    s = Settings()
    screen = _screen("General", s)
    cols, _lines, content = screen.layout(s)
    assert content > cols.bottom - cols.top
    screen.handle_scroll(-1000.0)
    assert screen.scroll <= content - (cols.bottom - cols.top)
    screen.handle_scroll(1000.0)
    assert screen.scroll == 0.0


def test_render_draws_without_font_and_with_font() -> None:
    s = Settings()
    screen = _screen("Performance", s)
    batch = Batch()
    screen.render(batch)
    assert batch.quads, "экран должен рисовать панели даже без шрифта"