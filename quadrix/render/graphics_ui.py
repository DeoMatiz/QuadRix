"""Экран графики Horizon — порт ``graphics_ui.rs``.

Три Rust-файла в одном:

* ``graphics_style.rs`` — размеры, палитра ``BLOCKS_DARK`` и отрисовка
  контролов (панель, группа, well, кнопка, чекбокс, слайдер, циклер);
* ``settings_shell.rs`` — общая оболочка ``Columns``/``Lines`` экранов
  настроек: слева знак, поиск, список страниц, Done/Undo; справа плита со
  строками и полоса описания;
* ``graphics_ui.rs`` — сами страницы (General, Quality, Performance, Shaders,
  Advanced, HDR), поиск, фокус, прокрутка и Undo.

Данные строк (подписи, диапазоны, значения, описания) живут в
``quadrix/render/graphics.py``; здесь только раскладка, отрисовка и ввод.

FALLBACK: у ``ui.Batch`` нет scissor/clip, поэтому список не обрезается
геометрически — невидимые строки пропускаются, но частично видимая строка
может выйти за плиту на 1-2 пикселя. В Rust это делает ``batch.clip_since``.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Optional

from quadrix.core import lang
from quadrix.render import graphics as gfx
from quadrix.render.ui import Batch, Font, Quad, rgba

__all__ = [
    "Columns",
    "GraphicsScreen",
    "Line",
    "Lines",
    "layout_lines",
]


# ---------------------------------------------------------------------------
# размеры (graphics_style.rs)
# ---------------------------------------------------------------------------

CONTROL_W = 112.0
CONTROL_H = 16.0
SEARCH_H = 16.0
SCROLLER_W = 6.0
DOCK_H = 50.0
BUTTON_H = 20.0
INSET = 10.0
ROW = 20.0
GROUP_ROW = 14.0
PAGE_ROW = 16.0
GROUP_GAP = 10.0
PAGE_GAP = 6.0
TITLED = 300.0

# ---------------------------------------------------------------------------
# цвета (graphics_style.rs, BLOCKS_DARK)
# ---------------------------------------------------------------------------

GLASS = gfx.hexcolor(gfx._PAGE, 118)
EDGE = gfx.hexcolor(gfx._INK, 26)
GROUP = gfx.hexcolor(gfx._INK, 11)
HOVER = gfx.hexcolor(gfx._INK, 18)
OPEN = gfx.hexcolor(gfx._INK, 26)
HEAD_RULE = gfx.hexcolor(gfx._INK, 31)
ROW_RULE = gfx.hexcolor(gfx._INK, 15)
WELL = gfx.hexcolor(gfx._OUTLINE, 102)
BUTTON = gfx.hexcolor(gfx._INK, 20)
BUTTON_HOVER = gfx.hexcolor(gfx._INK, 41)
TRACK = gfx.hexcolor(gfx._INK, 64)
HANDLE = gfx.hexcolor(gfx._INK, 255)
FACE = gfx.hexcolor(gfx._FACE, 255)
FACE_HOVER = gfx.hexcolor(0x6A50E6, 255)
BOX_EDGE = gfx.hexcolor(gfx._INK_SOFT, 89)
OUTLINE = gfx.hexcolor(gfx._OUTLINE, 255)
ACCENT = gfx.hexcolor(gfx._ACCENT, 255)
WHITE = 0xFFFFFFFF
MUTED = gfx.hexcolor(gfx._MUTED, 255)
SOFT = gfx.hexcolor(gfx._INK_SOFT, 255)
GREY = gfx.hexcolor(0xAAAAAA, 255)
VEIL = gfx.hexcolor(gfx._PAGE, 77)

SHADOW = rgba(0, 0, 0, 160)
SEARCH_HINT = "Search options"
NO_MATCH = "No settings match."
MENU_BACKGROUND_SPRITE = "gui/menu_background"
MENU_BACKGROUND_TILE = 32.0

#: Описания трёх Extra-строк (extras.rs::Item::description).
EXTRA_DESCRIPTIONS = {
    "Fullbright": "Show blocks and entities at full light, even in dark areas.",
    "DynamicLights": (
        "Torches and other light sources held, dropped or on fire light the blocks around them."
    ),
    "HideBlockParticles": (
        "Hides the debris particles that burst from a broken block and crumble off the one you "
        "mine. Other particles stay."
    ),
}


def _tr(key: str, fallback: Optional[str] = None) -> str:
    return lang.get_or(key, fallback if fallback is not None else key)


# ---------------------------------------------------------------------------
# простые примитивы рисования (ui::fill / hudd batch)
# ---------------------------------------------------------------------------

def solid(
    batch: Batch, font: Optional[Font], x: float, y: float, w: float, h: float, color: int
) -> None:
    """Сплошной прямоугольник белым пикселем шрифта (как ``style::fill``)."""
    if w <= 0.0 or h <= 0.0:
        return
    if font is not None:
        r = font.white
        batch.add_quad(Quad(x, y, w, h, r.u0, r.v0, r.u1, r.v1, color))
    else:
        batch.add_quad(Quad(x, y, w, h, 0.0, 0.0, 1.0, 1.0, color))


def fill(batch: Batch, font: Optional[Font], rect: tuple[float, float, float, float],
         color: int) -> None:
    solid(batch, font, rect[0], rect[1], rect[2], rect[3], color)


def ring(batch: Batch, font: Optional[Font], rect: tuple[float, float, float, float],
         color: int) -> None:
    """1 px рамка внутри ``rect`` (``style::ring``)."""
    x, y, w, h = rect
    solid(batch, font, x, y, w, 1.0, color)
    solid(batch, font, x, y + h - 1.0, w, 1.0, color)
    solid(batch, font, x, y + 1.0, 1.0, h - 2.0, color)
    solid(batch, font, x + w - 1.0, y + 1.0, 1.0, h - 2.0, color)


def panel(batch: Batch, font: Optional[Font],
          rect: tuple[float, float, float, float]) -> None:
    fill(batch, font, rect, GLASS)
    ring(batch, font, rect, EDGE)


def text(
    batch: Batch,
    font: Optional[Font],
    value: str,
    x: float,
    y: float,
    color: int = WHITE,
    shadow: bool = True,
) -> float:
    """Строка с тенью; возвращает ширину (``HudBatch::text_styled``)."""
    if font is None or not value:
        return 0.0
    if shadow:
        batch.add_quads(font.render(value, x + 1.0, y + 1.0, SHADOW))
    batch.add_quads(font.render(value, x, y, color))
    return float(font.width(value))


def _width(font: Optional[Font], value: str) -> float:
    return float(font.width(value)) if font is not None else 0.0


def fit(font: Optional[Font], value: str, width: float) -> str:
    """Обрезать ``value`` до ``width`` с «...» (``style::fit``)."""
    if font is None or _width(font, value) <= width:
        return value
    out = ""
    for c in value:
        if _width(font, out + c + "...") > width:
            break
        out += c
    return out.rstrip() + "..."


def _wrap(font: Optional[Font], value: str, width: float, limit: int) -> list[str]:
    """Разбить текст на строки по словам (``font.split``)."""
    if font is None:
        return [value] if value else []
    lines: list[str] = []
    current = ""
    for word in value.split(" "):
        trial = word if not current else current + " " + word
        if _width(font, trial) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= limit:
                return lines[:limit]
    if current:
        lines.append(current)
    return lines[:limit]


def _centered(
    batch: Batch, font: Optional[Font], value: str,
    x: float, y: float, w: float, color: int,
) -> None:
    tw = _width(font, value)
    text(batch, font, value, x + math.floor((w - tw) / 2.0), y, color)


# ---------------------------------------------------------------------------
# Columns (settings_shell.rs)
# ---------------------------------------------------------------------------

@dataclass
class Columns:
    side_x: float
    side_y: float
    plate: tuple[float, float, float, float]
    dock: tuple[float, float, float, float]
    list_x: float
    list_w: float
    top: float
    bottom: float

    @classmethod
    def of(cls, w: float, h: float) -> "Columns":
        side_w = CONTROL_W
        gap = 16.0 if w >= 560.0 else 8.0
        pw = math.floor(min(w - 16.0 - side_w - gap, 432.0))
        side_x = math.floor((w - side_w - gap - pw) / 2.0)
        px = side_x + side_w + gap
        side_y = 24.0 if h >= TITLED else 8.0
        dock_y = h - 8.0 - DOCK_H
        dock = (px, dock_y, pw, DOCK_H)
        plate = (px, side_y, pw, dock_y - 4.0 - side_y)
        list_x = px + 8.0
        return cls(
            side_x=side_x,
            side_y=side_y,
            plate=plate,
            dock=dock,
            list_x=list_x,
            list_w=pw - 16.0 - SCROLLER_W - 2.0,
            top=side_y + 30.0,
            bottom=plate[1] + plate[3] - 6.0,
        )

    def search(self) -> tuple[float, float, float, float]:
        return (self.side_x, self.side_y + 26.0, CONTROL_W, SEARCH_H)

    def clear(self) -> tuple[float, float, float, float]:
        x, y, w, h = self.search()
        return (x + w - h, y, h, h)

    def scrolls(self) -> bool:
        return self.bottom - self.top >= 40.0

    def bar_x(self) -> float:
        return self.plate[0] + self.plate[2] - 8.0 - SCROLLER_W

    def page(self, i: int) -> tuple[float, float, float, float]:
        return (self.side_x, self.side_y + 56.0 + i * 18.0, CONTROL_W, 16.0)

    def button(self, i: int) -> tuple[float, float, float, float]:
        foot = self.dock[1] + self.dock[3] - BUTTON_H
        y = foot if i == 0 else foot - 4.0 - BUTTON_H
        return (self.side_x, y, CONTROL_W, BUTTON_H)

    def track(self) -> tuple[float, float]:
        x = self.list_x + self.list_w - INSET - CONTROL_W
        return (x, CONTROL_W)

    def slider_at(self, x: float) -> float:
        tx, tw = self.track()
        return min(1.0, max(0.0, (x - tx - 5.0) / (tw - 10.0)))

    def row(self, y: float) -> tuple[float, float, float, float]:
        return (self.list_x, y, self.list_w, ROW)


# ---------------------------------------------------------------------------
# Lines (settings_shell.rs::Line / Lines)
# ---------------------------------------------------------------------------

@dataclass
class Line:
    y: float
    page: str
    group: Optional[tuple[str, float]] = None
    setting: Optional[gfx.GraphicsSetting] = None

    def h(self) -> float:
        if self.setting is not None:
            return ROW
        if self.group is not None:
            return GROUP_ROW
        return PAGE_ROW


class Lines:
    """Раскладка строк списка сверху вниз."""

    def __init__(self) -> None:
        self.lines: list[Line] = []
        self.y = 0.0

    def page(self, page: str) -> None:
        if self.lines:
            self.y += PAGE_GAP
        self.lines.append(Line(self.y, page))
        self.y += PAGE_ROW

    def group(self, page: str, name: str, rows: list[gfx.GraphicsSetting]) -> None:
        self.lines.append(Line(self.y, page, (name, len(rows) * ROW)))
        self.y += GROUP_ROW
        for setting in rows:
            self.lines.append(Line(self.y, page, None, setting))
            self.y += ROW
        self.y += GROUP_GAP

    def finish(self) -> tuple[list[Line], float]:
        return self.lines, max(self.y - GROUP_GAP, 0.0)


# ---------------------------------------------------------------------------
# вспомогательные предикаты graphics_ui.rs
# ---------------------------------------------------------------------------

def _setting_text(s: Any, setting: gfx.GraphicsSetting) -> str:
    """Описание строки (``description`` / ``Item::description_text``)."""
    if setting.kind == "Extra":
        english = EXTRA_DESCRIPTIONS.get(setting.name, setting.name)
        key = "horizon.extras.%s.tooltip" % _extra_snake(setting.name)
        return _tr(key, english)
    return _tr(setting.text, setting.text)


def _extra_snake(name: str) -> str:
    out = []
    for i, c in enumerate(name):
        if c.isupper() and i:
            out.append("_")
        out.append(c.lower())
    return "".join(out)


def _description(s: Any, setting: gfx.GraphicsSetting) -> str:
    """``description(item, s, text)`` — особые тексты HDR и culling."""
    name = setting.name
    if setting.kind == "H":
        h = s.horizon
        if name == "HdrCalibrate":
            if h.hdr_peak == 0 and h.hdr_paper_white == 0 and not h.hdr:
                return _tr(
                    "Your display didn't say how bright it gets: calibrate to set it up.",
                    "Your display didn't say how bright it gets: calibrate to set it up.",
                )
        if name in ("HdrPeak", "HdrPaperWhite"):
            if h.hdr_peak == 0 or h.hdr_paper_white == 0:
                return _tr(
                    "Set up for your display. Leave on Auto unless it looks wrong.",
                    "Set up for your display. Leave on Auto unless it looks wrong.",
                )
        if name == "EntityCulling":
            return _tr({
                "off": "No entity occlusion culling.",
                "sync": "CPU occlusion test runs this frame.",
                "async": "Occlusion checks run on a worker thread.",
            }.get(h.entity_culling, ""))
        if name == "LeafCulling":
            return _tr({
                "off": "Every leaf face. Vanilla's fancy leaves.",
                "hidden": "Drops leaf faces behind two leaf layers: faster, same crowns.",
                "solid": "Leaves fully inside a canopy draw solid: fewer see-through layers.",
                "solid_aggressive":
                    "Leaves with one open side draw solid too: faster, chunkier edges.",
                "hollow": "Drops faces between leaves: faster, but gaps look through.",
            }.get(h.leaf_culling, ""))
        if name == "ParticleCulling":
            return _tr({
                "off": "Draws every particle.",
                "sync": "Skips offscreen, subpixel and terrain-hidden particles.",
                "async": (
                    "Skips offscreen, subpixel and terrain-hidden particles with less "
                    "render-thread work."
                ),
            }.get(h.particle_culling, ""))
    return _setting_text(s, setting)


def _shown(s: Any, setting: gfx.GraphicsSetting) -> bool:
    """Upscaling виден только при включённом TAA (``shown``)."""
    return not (setting.kind == "H" and setting.name == "Upscaling") or bool(s.horizon.taa)


def _parts(s: Any, setting: gfx.GraphicsSetting) -> tuple[str, Optional[str]]:
    label = gfx.item_label(s, setting.kind, setting.name)
    return gfx.name_and_value(label)


# ---------------------------------------------------------------------------
# отрисовка контролов (graphics_style.rs)
# ---------------------------------------------------------------------------

def draw_checkbox(batch: Batch, font: Optional[Font], right: float, y: float,
                  on: bool, live: bool) -> None:
    rect = (right - 12.0, y + 4.0, 12.0, 12.0)
    fill(batch, font, rect, WELL)
    if on:
        edge = ACCENT if live else MUTED
    else:
        edge = BOX_EDGE
    ring(batch, font, rect, edge)
    if on:
        _draw_tick(batch, font, rect[0] + 1.0, rect[1] + 2.0, edge)


_TICK = [
    "         #",
    "        ##",
    "       ## ",
    "#     ##  ",
    "##   ##   ",
    " ## ##    ",
    "  ###     ",
    "   #      ",
]


def _draw_tick(batch: Batch, font: Optional[Font], x: float, y: float, color: int) -> None:
    for j, row in enumerate(_TICK):
        for i, c in enumerate(row):
            if c == "#":
                px, py = x + i, y + j
                solid(batch, font, px + 1.0, py + 1.0, 1.0, 1.0, OUTLINE)
                solid(batch, font, px, py, 1.0, 1.0, color)


def _scrolling_label(
    batch: Batch, font: Optional[Font], value: str,
    left: float, right: float, y: float, color: int,
) -> None:
    """Подпись контрола: по центру, если влезает, иначе с левого края."""
    w = right - left
    tw = _width(font, value)
    x = left + max(0.0, math.floor((w - tw) / 2.0))
    text(batch, font, value, x, y, color)


def draw_button(
    batch: Batch, font: Optional[Font], rect: tuple[float, float, float, float],
    label: str, hover: bool, live: bool, primary: bool,
) -> None:
    x, y, w, h = rect
    if not live:
        face = WELL
    elif primary:
        face = FACE_HOVER if hover else FACE
    else:
        face = BUTTON_HOVER if hover else BUTTON
    fill(batch, font, rect, face)
    if hover and live:
        ring(batch, font, rect, WHITE)
    color = WHITE if live else MUTED
    ty = y + math.floor((h - 8.0) / 2.0)
    _scrolling_label(batch, font, label, x + 2.0, x + w - 2.0, ty, color)


def draw_slider(
    batch: Batch, font: Optional[Font], rect: tuple[float, float, float, float],
    value: str, position: float, hover: bool, live: bool,
) -> None:
    x, y, w, h = rect
    color = WHITE if live else MUTED
    _scrolling_label(batch, font, value, x + 2.0, x + w - 2.0, y + 1.0, color)
    line = y + h - 3.0
    at = x + round(min(1.0, max(0.0, position)) * (w - 4.0))
    fill(batch, font, (x, line, w, 2.0), TRACK)
    fill(batch, font, (x, line, at - x, 2.0), ACCENT if live else MUTED)
    fill(batch, font, (at, line - 3.0, 4.0, 8.0), HANDLE if live else MUTED)
    if hover and live:
        ring(batch, font, (at - 1.0, line - 4.0, 6.0, 10.0), ACCENT)


def draw_cycler(
    batch: Batch, font: Optional[Font], rect: tuple[float, float, float, float],
    value: str, hover: bool, live: bool,
) -> None:
    x, y, w, h = rect
    fill(batch, font, rect, WELL)
    if hover and live:
        ring(batch, font, rect, WHITE)
    ty = y + math.floor((h - 8.0) / 2.0)
    arrows = WHITE if (hover and live) else MUTED
    text(batch, font, "<", x + 3.0, ty, arrows)
    text(batch, font, ">", x + w - 8.0, ty, arrows)
    if not live:
        color = MUTED
    elif hover:
        color = WHITE
    else:
        color = SOFT
    _scrolling_label(batch, font, value, x + 9.0, x + w - 9.0, ty, color)


# ---------------------------------------------------------------------------
# фон и оболочка (settings_shell.rs)
# ---------------------------------------------------------------------------

def backdrop(batch: Batch, font: Optional[Font], w: float, h: float,
             in_world: bool) -> None:
    atlas = getattr(batch, "atlas", None)
    drew = False
    if atlas is not None:
        drew = bool(atlas.tiled(
            batch, MENU_BACKGROUND_SPRITE, 0.0, 0.0, w, h, MENU_BACKGROUND_TILE
        ))
    if not drew:
        # FALLBACK: спрайт menu_background отсутствует — тёмная заливка.
        solid(batch, font, 0.0, 0.0, w, h, rgba(0, 0, 0, 255))
    fill(batch, font, (0.0, 0.0, w, h), VEIL)


def draw_mark(batch: Batch, font: Optional[Font], cols: Columns, title: str) -> None:
    x, y = cols.side_x, cols.side_y
    fill(batch, font, (x, y + 2.0, 6.0, 6.0), ACCENT)
    text(batch, font, "Horizon", x + 10.0, y, WHITE)
    text(batch, font, title, x, y + 10.0, MUTED)


def draw_page_tab(
    batch: Batch, font: Optional[Font], rect: tuple[float, float, float, float],
    name: str, has: bool, opened: bool, focused: bool, cursor: tuple[float, float],
) -> None:
    px, py, pw, ph = rect
    hover = has and _hovered(cursor, rect)
    if opened:
        fill(batch, font, rect, OPEN)
        fill(batch, font, (px, py, 2.0, ph), ACCENT)
    if opened or hover:
        color = WHITE
    elif has:
        color = SOFT
    else:
        color = MUTED
    ty = py + math.floor((ph - 8.0) / 2.0)
    text(batch, font, fit(font, name, pw - 12.0), px + 8.0, ty, color)
    if focused:
        ring(batch, font, rect, WHITE)


def draw_search_field(
    batch: Batch, font: Optional[Font], cols: Columns, query: str, focused: bool,
    cursor: tuple[float, float],
) -> None:
    rect = cols.search()
    fill(batch, font, rect, WELL)
    x, y, _w, h = rect
    clear = cols.clear()
    field_w = clear[0] - (x + 5.0)
    ty = y + math.floor((h - 8.0) / 2.0)
    shown = query
    # Сдвигаем начало, чтобы каретка была видна внутри поля.
    while shown and _width(font, shown) > field_w:
        shown = shown[1:]
    text(batch, font, shown, x + 5.0, ty, WHITE)
    if not query and not focused:
        text(batch, font, _tr(SEARCH_HINT, SEARCH_HINT), x + 5.0, ty, MUTED)
    if query:
        hover = _hovered(cursor, clear)
        color = WHITE if hover else MUTED
        _centered(batch, font, "x", clear[0], ty, clear[2], color)
    if focused:
        ring(batch, font, (x, y, clear[0] - x, h), WHITE)


def draw_plate(batch: Batch, font: Optional[Font], cols: Columns, heading: str) -> None:
    px, py, pw, _ph = cols.plate
    panel(batch, font, cols.plate)
    text(batch, font, fit(font, heading, pw - 24.0), px + 12.0, py + 10.0, WHITE)
    fill(batch, font, (px + 8.0, py + 24.0, pw - 16.0, 1.0), HEAD_RULE)


def draw_scroller(batch: Batch, font: Optional[Font], cols: Columns,
                  content: float, scroll: float) -> None:
    if not cols.scrolls():
        return
    thumb = _scrollbar_thumb(cols.top, cols.bottom, content, scroll)
    if thumb is None:
        return
    y, bar = thumb
    x = cols.bar_x()
    height = cols.bottom - cols.top
    fill(batch, font, (x, cols.top, SCROLLER_W, height), ROW_RULE)
    fill(batch, font, (x, y, SCROLLER_W, bar), TRACK)


def _scrollbar_thumb(top: float, bottom: float, content: float,
                     scroll: float) -> Optional[tuple[float, float]]:
    height = bottom - top
    if content <= height:
        return None
    bar = math.floor(min(max(height * height / content, 32.0), height - 8.0))
    y = top + math.floor((scroll / (content - height)) * (height - bar))
    return (y, bar)


def _hovered(cursor: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    x, y = cursor
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


# ---------------------------------------------------------------------------
# GraphicsScreen
# ---------------------------------------------------------------------------

class GraphicsScreen:
    """Экран графики (порт ``GraphicsUi`` + ``Screen::Graphics``).

    Наследование от ``menu.Screen`` не используется намеренно: ``menu``
    импортирует этот модуль, и импорт базового класса дал бы цикл. Все
    методы, которых ждёт ``ScreenStack``, реализованы здесь.
    """

    def __init__(
        self,
        settings: Any = None,
        stack: Any = None,
        width: float = 854.0,
        height: float = 480.0,
        framebuffer: Optional[tuple[int, int]] = None,
        in_world: bool = False,
    ) -> None:
        if settings is None:
            from quadrix.render.menu import Settings

            settings = Settings()
        self.width = float(width)
        self.height = float(height)
        self.settings = settings
        self.stack = stack
        self.framebuffer = framebuffer or (int(width), int(height))
        self.in_world = in_world

        self.page = "General"
        self.picked: Optional[str] = None
        self.focus: Optional[tuple] = None
        self.dragging: Optional[gfx.GraphicsSetting] = None
        self.scroll = 0.0
        self.held: Optional[float] = None
        self.before: Any = None
        self.changed = False
        self.can_change_value = False
        self.binding: Optional[str] = None
        self.search = ""
        self.search_cursor = 0
        self.cursor: tuple[float, float] = (0.0, 0.0)

    # -- жизненный цикл --------------------------------------------------

    def on_resize(self, width: float, height: float) -> None:
        self.width = float(width)
        self.height = float(height)

    def _back(self) -> None:
        if self.stack is not None:
            self.stack.pop()

    def done(self) -> None:
        """Done / Escape: закрыть экран (Rust ``Action::Done``)."""
        self._back()

    # -- раскладка -------------------------------------------------------

    def query(self) -> str:
        return self.search.strip().lower()

    def lines(self, s: Any) -> tuple[list[Line], float]:
        query = self.query()
        lines = Lines()
        for page, groups in gfx.GRAPHICS_PAGES:
            if not query and page != self.page:
                continue
            kept: list[tuple[str, list[gfx.GraphicsSetting]]] = []
            for name, rows in groups:
                rows = [r for r in rows if _shown(s, r)]
                rows = [
                    r for r in rows
                    if not query
                    or self.focus == ("Item", r.kind, r.name)
                    or (self.dragging is not None
                        and self.dragging.kind == r.kind
                        and self.dragging.name == r.name)
                    or query in _parts(s, r)[0].lower()
                    or query in _setting_text(s, r).lower()
                ]
                if rows:
                    kept.append((name, rows))
            if not kept:
                continue
            if query:
                lines.page(page)
            for name, rows in kept:
                lines.group(page, name, rows)
        return lines.finish()

    def layout(self, s: Any) -> tuple[Columns, list[Line], float]:
        cols = Columns.of(self.width, self.height)
        lines, content = self.lines(s)
        self._clamp_scroll(cols, content)
        return cols, lines, content

    def _clamp_scroll(self, cols: Columns, content: float) -> None:
        height = cols.bottom - cols.top
        maximum = max(content - height, 0.0)
        self.scroll = min(max(self.scroll, 0.0), maximum)

    def row_y(self, cols: Columns, line: Line) -> float:
        return cols.top + line.y - self.scroll

    def has(self, page: str, lines: list[Line]) -> bool:
        return not self.query() or any(l.page == page for l in lines)

    def current(self, lines: list[Line]) -> Optional[str]:
        if not self.query():
            return self.page
        if self.picked is not None:
            return self.picked
        for line in lines:
            if line.y + line.h() > self.scroll:
                return line.page
        return None

    def pick(self, page: str, lines: list[Line], cols: Columns, content: float) -> None:
        self.page = page
        self.scroll = 0.0
        if not self.query():
            return
        for line in lines:
            if line.page == page:
                self.scroll = line.y
                self._clamp_scroll(cols, content)
                self.picked = page
                return

    def _searched(self) -> None:
        """Поиск изменился: список начинается сверху (``searched``)."""
        self.scroll = 0.0
        self.picked = None

    # -- Undo ------------------------------------------------------------

    def _keep(self, s: Any) -> None:
        if self.before is None:
            self.before = copy.deepcopy(s)

    def undo(self, s: Any) -> None:
        b = self.before
        if b is None:
            return
        for name in (
            "render_distance", "simulation_distance", "gamma", "gui_scale", "vsync",
            "max_fps", "inactivity_fps_limit", "menu_blur", "attack_indicator",
            "autosave_indicator", "clouds", "cloud_range", "weather_radius", "particles",
            "smooth_lighting", "biome_blend", "entity_distance", "entity_shadows",
            "vignette", "chunk_fade", "mipmap_levels", "cutout_leaves",
            "improved_transparency", "prioritize_chunk_updates", "graphics_preset",
        ):
            if hasattr(s, name) and hasattr(b, name):
                setattr(s, name, copy.deepcopy(getattr(b, name)))
        s.horizon = copy.deepcopy(b.horizon)
        s.extras = copy.deepcopy(b.extras)
        for key in ("exclusiveFullscreen", "textureFiltering", "maxAnisotropyBit",
                    "fullscreenResolution"):
            if key in b.file:
                s.file[key] = copy.deepcopy(b.file[key])
        self.changed = False

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        s = self.settings
        self.cursor = (mx, my)
        self._keep(s)
        cols, lines, content = self.layout(s)

        # Полоса прокрутки.
        if cols.scrolls() and _hovered((mx, my), (cols.bar_x(), cols.top,
                                                 SCROLLER_W, cols.bottom - cols.top)):
            self.picked = None
            self.held = my
            self._drag_scroll(my, cols, content)
            return True
        # Поиск.
        if _hovered((mx, my), cols.search()):
            if self.search and _hovered((mx, my), cols.clear()):
                self.search = ""
                self.search_cursor = 0
                self._searched()
                return True
            self.focus = ("Search",)
            self.search_cursor = len(self.search)
            return True
        if self.focus == ("Search",):
            self.focus = None
        # Done / Undo.
        if _hovered((mx, my), cols.button(0)):
            self.focus = ("Done",)
            self.done()
            return True
        if self.changed and _hovered((mx, my), cols.button(1)):
            self.focus = None
            self.undo(s)
            return True
        # Список страниц.
        for i, page in enumerate(gfx.GRAPHICS_PAGE_NAMES):
            if _hovered((mx, my), cols.page(i)) and self.has(page, lines):
                self.focus = ("Page", page)
                self.pick(page, lines, cols, content)
                return True
        # Строки.
        if my < cols.top or my >= cols.bottom:
            return False
        item = None
        for line in lines:
            if line.setting is None:
                continue
            ry = self.row_y(cols, line)
            if _hovered((mx, my), (cols.list_x, ry, cols.list_w, ROW)):
                item = line.setting
                break
        if item is None:
            return False
        if gfx.item_blocked(s, item.kind, item.name) is not None:
            return True
        self.focus = ("Item", item.kind, item.name)
        self._activate(s, item, mx, cols)
        return True

    def _activate(self, s: Any, item: gfx.GraphicsSetting, mx: float,
                  cols: Columns) -> None:
        name, kind = item.name, item.kind
        if kind == "H" and name == "HdrCalibrate":
            if s.horizon.hdr_peak == 0 and s.horizon.hdr_paper_white == 0:
                return
            s.horizon.hdr_peak = 0
            s.horizon.hdr_paper_white = 0
            self.changed = True
            return
        if kind == "H" and name in ("ShaderPacks", "HdrKey"):
            return
        position = gfx.item_slider(s, kind, name)
        if position is not None:
            self.can_change_value = True
            tx, _tw = cols.track()
            if mx >= tx:
                self.dragging = item
                gfx.item_set_slider(s, kind, name, cols.slider_at(mx))
                self.changed = True
            return
        self.can_change_value = False
        gfx.item_cycle(s, kind, name, False, self.framebuffer)
        self.changed = True

    def handle_move(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        cols, _lines, _content = self.layout(self.settings)
        if self.dragging is not None and self.held is None:
            # Слайдер тянется, пока кнопка зажата (App не шлёт release, поэтому
            # перетаскивание идёт по move внутри трека).
            if mx >= cols.track()[0]:
                gfx.item_set_slider(
                    self.settings, self.dragging.kind, self.dragging.name,
                    cols.slider_at(mx),
                )
                self.changed = True
        if self.held is not None:
            _c, _l, content = self.layout(self.settings)
            self._drag_scroll(my, cols, content)
            return True
        return (cols.top <= my < cols.bottom
                or _hovered((mx, my), cols.search())
                or any(_hovered((mx, my), cols.page(i)) for i in range(6))
                or _hovered((mx, my), cols.button(0))
                or _hovered((mx, my), cols.button(1)))

    def _drag_scroll(self, my: float, cols: Columns, content: float) -> None:
        height = cols.bottom - cols.top
        overflow = max(content - height, 0.0)
        if overflow <= 0.0:
            self.scroll = 0.0
            return
        # Позиция большого пальца переводится обратно в scroll.
        bar = math.floor(min(max(height * height / content, 32.0), height - 8.0))
        span = height - bar
        if span <= 0.0:
            self.scroll = 0.0
            return
        self.scroll = min(max((my - cols.top - bar / 2.0) / span * overflow, 0.0), overflow)

    def handle_scroll(self, dy: float) -> bool:
        s = self.settings
        cols, lines, content = self.layout(s)
        # Колесо над строкой-циклером меняет значение при включённой экстре.
        if dy != 0.0 and getattr(s.extras, "wheel_cycles_settings", False):
            item = self._hovered_item(cols, lines)
            if (item is not None and gfx.item_steps(s, item.kind, item.name)
                    and gfx.item_blocked(s, item.kind, item.name) is None):
                self._keep(s)
                gfx.item_cycle(s, item.kind, item.name, dy > 0.0, self.framebuffer)
                self.changed = True
                return True
        self.picked = None
        self.scroll -= dy * 18.0
        self._clamp_scroll(cols, content)
        return True

    def _hovered_item(self, cols: Columns, lines: list[Line]) -> Optional[gfx.GraphicsSetting]:
        mx, my = self.cursor
        if my < cols.top or my >= cols.bottom:
            return None
        for line in lines:
            if line.setting is None:
                continue
            if _hovered((mx, my), (cols.list_x, self.row_y(cols, line), cols.list_w, ROW)):
                return line.setting
        return None

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        s = self.settings
        if self.focus == ("Search",):
            if key == "escape":
                self.focus = None
                return True
            if key == "enter":
                self.focus = None
                return True
            if key == "backspace":
                if self.search_cursor > 0:
                    i = self.search_cursor
                    self.search = self.search[:i - 1] + self.search[i:]
                    self.search_cursor -= 1
                    self._searched()
                return True
            if key == "delete":
                i = self.search_cursor
                self.search = self.search[:i] + self.search[i + 1:]
                self._searched()
                return True
            if key == "left":
                self.search_cursor = max(0, self.search_cursor - 1)
                return True
            if key == "right":
                self.search_cursor = min(len(self.search), self.search_cursor + 1)
                return True
            if key == "home":
                self.search_cursor = 0
                return True
            if key == "end":
                self.search_cursor = len(self.search)
                return True
            if ch is not None and ch.isprintable():
                i = self.search_cursor
                self.search = self.search[:i] + ch + self.search[i:]
                self.search_cursor += 1
                self._searched()
                return True
            return False
        if key == "escape":
            self.done()
            return True
        if key == "tab":
            self._tab(False)
            return True
        if key == "shift+tab":
            self._tab(True)
            return True
        if key in ("up", "down"):
            self.held = None
            self.scroll += -18.0 if key == "up" else 18.0
            cols, _l, content = self.layout(s)
            self._clamp_scroll(cols, content)
            return True
        if key in ("left", "right") and self.focus is not None and self.focus[0] == "Item":
            tag, kind, name = self.focus
            item = gfx.GraphicsSetting(kind, name, gfx.Cost.NONE, "")
            if gfx.item_steps(s, kind, name) and gfx.item_blocked(s, item.kind, item.name) is None:
                self._keep(s)
                gfx.item_cycle(s, kind, name, key == "left", self.framebuffer)
                self.changed = True
                return True
            position = gfx.item_slider(s, kind, name)
            if position is not None and gfx.item_blocked(s, kind, name) is None:
                self._keep(s)
                cols, _l, _c = self.layout(s)
                steps = gfx.item_slider_steps(kind, name)
                gfx.item_set_slider(
                    s, kind, name, _slider_step(position, steps, cols.track()[1],
                                                key == "right")
                )
                self.changed = True
                return True
            return False
        if key == "enter" and self.focus is not None:
            if self.focus[0] == "Done":
                self.done()
                return True
            if self.focus[0] == "Item":
                tag, kind, name = self.focus
                cols, _l, _c = self.layout(s)
                item = gfx.GraphicsSetting(kind, name, gfx.Cost.NONE, "")
                if gfx.item_blocked(s, kind, name) is None:
                    gfx.item_cycle(s, kind, name, False, self.framebuffer)
                    self.changed = True
                return True
        return False

    def _tab(self, shift: bool) -> None:
        cols, lines, _content = self.layout(self.settings)
        controls: list[tuple] = [("Search",), ("Done",)]
        if self.changed:
            controls.append(("Undo",))
        for page in gfx.GRAPHICS_PAGE_NAMES:
            if self.has(page, lines):
                controls.append(("Page", page))
        for line in lines:
            if line.setting is not None:
                controls.append(("Item", line.setting.kind, line.setting.name))
        if not controls:
            return
        try:
            i = controls.index(self.focus)
        except ValueError:
            i = -1
        i = (i + (len(controls) - 1 if shift else 1)) % len(controls) if i >= 0 else (
            0 if not shift else len(controls) - 1
        )
        self.focus = controls[i]

    # -- отрисовка -------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        s = self.settings
        w, h = self.width, self.height
        cols, lines, content = self.layout(s)
        backdrop(batch, font, w, h, self.in_world)
        current = self.current(lines)
        # Слева: знак и список страниц.
        draw_mark(batch, font, cols, _tr("Graphics", "Graphics"))
        for i, page in enumerate(gfx.GRAPHICS_PAGE_NAMES):
            draw_page_tab(
                batch, font, cols.page(i), _tr(page, page), self.has(page, lines),
                current == page, self.focus == ("Page", page), self.cursor,
            )
        # Поиск.
        draw_search_field(
            batch, font, cols, self.search, self.focus == ("Search",), self.cursor
        )
        query = self.search.strip()
        if not query:
            heading = _tr(current or self.page, current or self.page)
        else:
            heading = _tr('Results for "%s"', 'Results for "%s"') % query
        draw_plate(batch, font, cols, heading)
        self._draw_list(batch, font, cols, lines)
        draw_scroller(batch, font, cols, content, self.scroll)
        self._draw_dock(batch, font, cols, lines, current)
        # Низ: Done (и Undo, если есть что отменять).
        foot = [(cols.button(0), _tr("Done", "Done"), ("Done",), True)]
        if self.changed:
            foot.append((cols.button(1), _tr("Undo", "Undo"), ("Undo",), False))
        for rect, label, target, primary in foot:
            hover = _hovered(self.cursor, rect)
            draw_button(batch, font, rect, label, hover or self.focus == target,
                        True, primary)

    def _described(self, cols: Columns, lines: list[Line]) -> Optional[gfx.GraphicsSetting]:
        over_list = cols.top <= self.cursor[1] < cols.bottom
        focused_item = None
        for line in lines:
            if line.setting is None:
                continue
            rect = cols.row(self.row_y(cols, line))
            hover = over_list and _hovered(self.cursor, rect)
            focused = self.focus == ("Item", line.setting.kind, line.setting.name)
            if hover or (self.dragging is not None
                         and self.dragging.kind == line.setting.kind
                         and self.dragging.name == line.setting.name):
                return line.setting
            if focused and focused_item is None:
                focused_item = line.setting
        return focused_item

    def _draw_list(self, batch: Batch, font: Optional[Font], cols: Columns,
                   lines: list[Line]) -> None:
        s = self.settings

        def shows(y: float, h: float) -> bool:
            return y + h > cols.top and y < cols.bottom

        # Панели групп.
        for line in lines:
            if line.group is None:
                continue
            y = self.row_y(cols, line)
            _name, panel = line.group
            if shows(y + GROUP_ROW, panel):
                fill(batch, font, (cols.list_x, y + GROUP_ROW, cols.list_w, panel), GROUP)
        # Строки и подписи.
        first = False
        for line in lines:
            y = self.row_y(cols, line)
            after_name = first
            first = line.group is not None
            if not shows(y, line.h()):
                continue
            if line.setting is None:
                if line.group is not None:
                    name, _panel = line.group
                    label = _tr(name, name) if name else _tr(line.page, line.page)
                    color, dy = MUTED, 3.0
                else:
                    label, color, dy = _tr(line.page, line.page), ACCENT, 4.0
                text(batch, font, label, cols.list_x + 2.0, y + dy, color)
                continue
            if not after_name:
                fill(batch, font, (cols.list_x + 8.0, y, cols.list_w - 16.0, 1.0), ROW_RULE)
            self._draw_row(batch, font, s, cols, line.setting, y)
        if not lines:
            text(batch, font, _tr(NO_MATCH, NO_MATCH), cols.list_x + 2.0,
                 cols.top + 4.0, MUTED)

    def _draw_row(self, batch: Batch, font: Optional[Font], s: Any, cols: Columns,
                  item: gfx.GraphicsSetting, y: float) -> None:
        rect = cols.row(y)
        tx, tw = cols.track()
        right = tx + tw
        control = (tx, y + (ROW - CONTROL_H) / 2.0, tw, CONTROL_H)
        hover = (cols.top <= self.cursor[1] < cols.bottom) and _hovered(self.cursor, rect)
        focused = self.focus == ("Item", item.kind, item.name)
        held = (self.dragging is not None and self.dragging.kind == item.kind
                and self.dragging.name == item.name)
        live = gfx.item_blocked(s, item.kind, item.name) is None
        active = live and (hover or focused or held)
        if active:
            fill(batch, font, (rect[0] + 2.0, y + 1.0, rect[2] - 4.0, ROW - 2.0), HOVER)
        color = WHITE if live else MUTED
        soft = SOFT if live else MUTED
        ty = y + math.floor((ROW - 8.0) / 2.0)
        lit = live and (hover or held)
        left = rect[0] + INSET
        name, value = _parts(s, item)
        switch = gfx.item_switch(s, item.kind, item.name)
        slider = gfx.item_slider(s, item.kind, item.name)
        if switch is None and slider is None and value is None:
            wide = (left, control[1], right - left, CONTROL_H)
            draw_button(batch, font, wide, name, lit, live, False)
        else:
            value = value or ""
            vw = _width(font, value)
            if switch is not None:
                start = right - CONTROL_H
            elif slider is not None and active:
                start = tx
            elif slider is not None:
                start = right - vw
            else:
                start = right - vw - 18.0
            if switch is not None:
                draw_checkbox(batch, font, right, y, bool(switch), live)
            elif slider is not None:
                if active:
                    draw_slider(batch, font, control, value, slider, lit, live)
                else:
                    text(batch, font, value, start, ty, soft)
            else:
                draw_cycler(batch, font, (start, y + 3.0, vw + 18.0, 14.0),
                            value, lit, live)
            text(batch, font, fit(font, name, start - 6.0 - left), left, ty, color)
        if focused:
            ring(batch, font, (rect[0] + 1.0, y, rect[2] - 2.0, ROW), WHITE)

    def _draw_dock(self, batch: Batch, font: Optional[Font], cols: Columns,
                   lines: list[Line], current: Optional[str]) -> None:
        s = self.settings
        x, y, w, _h = cols.dock
        panel(batch, font, cols.dock)
        left = x + 12.0
        setting = self._described(cols, lines)
        if setting is not None:
            name, _value = _parts(s, setting)
            cost = gfx.cost_label(setting.cost)
            line = fit(font, "%s - %s" % (name, cost), w - 32.0)
            fill(batch, font, (left, y + 10.0, 4.0, 4.0), gfx.cost_color(setting.cost))
            text(batch, font, line, left + 8.0, y + 8.0, WHITE)
            blocked = gfx.item_blocked(s, setting.kind, setting.name)
            note = blocked if blocked is not None else _description(s, setting)
            note_color = MUTED if blocked is not None else GREY
        else:
            if current is None:
                return
            text(batch, font, _tr(current, current), left, y + 8.0, WHITE)
            about = gfx.GRAPHICS_PAGE_ABOUT.get(current, "")
            note, note_color = _tr(about, about), GREY
        for i, line in enumerate(_wrap(font, note, w - 24.0, 2)):
            text(batch, font, line, x + 12.0, y + 20.0 + i * 10.0, note_color)


def _slider_step(pos: float, steps: Optional[int], width: float, forward: bool) -> float:
    """``settings_shell::slider_step``."""
    if steps is not None:
        current = round(pos * steps)
        nxt = current + 1 if forward else current - 1
        return min(1.0, max(0.0, nxt / steps))
    delta = 1.0 / max(width - 8.0, 1.0)
    return min(1.0, pos + delta) if forward else max(0.0, pos - delta)


#: Совместимость с прежним кодом: список колонок для текущего размера.
COLUMNS = Columns


def layout_lines(s: Any, page: str = "General") -> tuple[list[Line], float]:
    """Раскладка одной страницы без экрана (для тестов и отладки)."""
    screen = GraphicsScreen(settings=s, width=854.0, height=480.0)
    screen.page = page
    return screen.lines(s)