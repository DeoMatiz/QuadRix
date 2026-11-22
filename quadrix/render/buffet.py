#!/usr/bin/env python3
"""[QuadRix] CreateBuffetWorldScreen (WC5).

Порт ``horizon/crates/horizon-client/src/title/buffet.rs``: экран пресета
одного биома (``WorldPreset.SINGLE_BIOME_SURFACE``) — список биомов с
поиском и кнопки Done/Cancel, которые возвращают биом в Create New World
(``WorldCreationUiState.updateDimensions``).

Порт сохраняет структуру Rust:
    * :class:`Biome` / :class:`State` (``query``/``query_focused``/``biome``;
      ``rows``/``selected``/``name``/``select``);
    * :func:`load` — реестр биомов из ``worldgen/biomes.json``, отсортированный
      по ``(name.lower(), id)`` (``Registry.listElements`` с коллатором);
    * :func:`display_name` — ``Identifier.toLanguageKey("biome")``
      (``biome.<ns>.<path>``), иначе сам id;
    * геометрия :func:`list_area` / :func:`search_box` / :func:`row_at` /
      :func:`click` / :func:`focus_row` / :func:`wheel` / :func:`drag` /
      :func:`release` / :func:`buttons` и :func:`draw` (общие виджеты списка —
      из :mod:`quadrix.render.flat`, как ``crate::ui``/``super::flat``).

Обёртка :class:`BuffetWorldScreen` — для :class:`ScreenStack`; CreateWorld
Screen id 26 (Customize) открывает её для ``SINGLE_BIOME_SURFACE``.

FALLBACK (см. ``PORTING_STATE.yaml``):
    * наррация/``row_target`` (контроллер) не портированы;
    * каретка/выделение/clipboard (``title.caret``) не портированы — поле
      поиска редактируется простой вставкой/backspace.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.render.create_world import Button as _CWButton
from quadrix.render.flat import (
    Scroll,
    centered,
    edit_box,
    list_background,
    scrollbar,
    separators,
    ui_hovered,
)
from quadrix.render.menu import (
    PACK_ROOT,
    Screen,
    ScreenStack,
    draw_menu_background,
    draw_text,
    solid,
)
from quadrix.render.ui import Batch, Button, Font, rgba

__all__ = [
    "SEARCH",
    "HEADER",
    "FOOTER",
    "SEARCH_WIDTH",
    "SEARCH_HEIGHT",
    "SEARCH_TOP",
    "ROW_WIDTH",
    "ROW_HEIGHT",
    "Biome",
    "State",
    "load",
    "display_name",
    "list_area",
    "search_box",
    "row_at",
    "click",
    "focus_row",
    "wheel",
    "drag",
    "release",
    "buttons",
    "draw",
    "BuffetWorldScreen",
]


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] buffet: " + message)


# buffet.rs L15-28: константы экрана (не менять).
#: ``EditBox`` поиска: поле каретки/выделения/буфера (``FieldId``).
SEARCH = ("world.buffet-search", 0)
#: ``HeaderAndFooterLayout`` header: строка заголовка, 13 над ним, поле 15 под ним.
HEADER = 40.0
#: ``HeaderAndFooterLayout`` footer по умолчанию.
FOOTER = 33.0
#: Поле поиска (``new EditBox(font, 200, 15, ...)``).
SEARCH_WIDTH = 200.0
SEARCH_HEIGHT = 15.0
#: Верх поля: 13 + 9-пиксельная строка заголовка + 3.
SEARCH_TOP = 25.0
#: ``ObjectSelectionList``: строка 220 шириной и 20 высотой по умолчанию.
ROW_WIDTH = 220.0
ROW_HEIGHT = 20.0
#: ``EditBox`` поиска: максимум символов (``(SEARCH, query, 50)``).
QUERY_MAX = 50


# ---------------------------------------------------------------------------
# Biome / State (buffet.rs L30-95)
# ---------------------------------------------------------------------------

@dataclass
class Biome:
    """Один биом: id реестра и имя, которое показывает список."""

    id: str
    name: str


@dataclass
class State:
    """Состояние CreateBuffetWorldScreen (``buffet.rs::State``)."""

    #: Текст ``EditBox``: строки, чьё имя содержит его (без регистра).
    query: str = ""
    query_focused: bool = False
    #: Фиксированный биом: ``plains`` до иного выбора.
    biome: str = "minecraft:plains"
    scroll: Scroll = field(default_factory=Scroll)
    biomes: list[Biome] = field(default_factory=list)

    @classmethod
    def new(cls, root: Path, biome: str) -> "State":
        """Экран над ``biome`` с биомами подготовленного корня ресурсов."""
        return cls(query="", query_focused=False, biome=biome, scroll=Scroll(),
                   biomes=load(root))

    def rows(self) -> list[int]:
        """Индексы биомов, которые оставляет поиск, в порядке списка."""
        query = self.query.lower()
        return [
            index
            for index, biome in enumerate(self.biomes)
            if not query or query in biome.name.lower()
        ]

    def selected(self) -> Optional[int]:
        """Выбранная строка, пока поиск всё ещё показывает биом."""
        for position, index in enumerate(self.rows()):
            if self.biomes[index].id == self.biome:
                return position
        return None

    def name(self, row: int) -> Optional[str]:
        if 0 <= row < len(self.biomes):
            return self.biomes[row].name
        return None

    def select(self, row: int) -> None:
        if 0 <= row < len(self.biomes):
            self.biome = self.biomes[row].id


def load(root: Path) -> list[Biome]:
    """``buffet.rs::load``: биомы из ``worldgen/biomes.json``, сортированные."""
    try:
        value = json.loads((root / "worldgen/biomes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(value, dict):
        return []
    biomes = [Biome(id=identifier, name=display_name(identifier))
              for identifier in value.keys()]
    biomes.sort(key=lambda biome: (biome.name.lower(), biome.id))
    return biomes


def display_name(identifier: str) -> str:
    """``Identifier.toLanguageKey("biome")``: ``biome.<ns>.<path>`` иначе id."""
    if ":" in identifier:
        namespace, path = identifier.split(":", 1)
    else:
        namespace, path = "minecraft", identifier
    key = f"biome.{namespace}.{path.replace('/', '.')}"
    if lang.has(key):
        return lang.get(key)
    return identifier


# ---------------------------------------------------------------------------
# геометрия (buffet.rs L133-203)
# ---------------------------------------------------------------------------

def list_area(size: tuple[float, float], rows: int) -> tuple[float, float, float, float]:
    """``buffet.rs::list_area``: ``(top, bottom, left, content_rows)``."""
    w, h = math.ceil(size[0]), math.ceil(size[1])
    return (
        HEADER,
        h - FOOTER,
        math.floor((w - ROW_WIDTH) * 0.5),
        rows * ROW_HEIGHT + 4.0,
    )


def search_box(w: float) -> list[float]:
    """``buffet.rs::search_box``: EditBox 200x15 по центру."""
    return [
        math.floor((w - SEARCH_WIDTH) * 0.5),
        SEARCH_TOP,
        SEARCH_WIDTH,
        SEARCH_HEIGHT,
    ]


def row_at(
    state: State, cursor: tuple[float, float], size: tuple[float, float]
) -> Optional[int]:
    """``buffet.rs::row_at``: индекс биома под указателем (``getEntryAtPosition``)."""
    rows = state.rows()
    top, bottom, left, _content = list_area(size, len(rows))
    if (
        cursor[0] < left
        or cursor[0] >= left + ROW_WIDTH
        or cursor[1] < top
        or cursor[1] >= bottom
    ):
        return None
    row = int((cursor[1] - top + math.trunc(state.scroll.amount)) / ROW_HEIGHT)
    if 0 <= row < len(rows):
        return rows[row]
    return None


def click(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> None:
    """``buffet.rs::click``: поле поиска, список или скроллбар."""
    rows = state.rows()
    top, bottom, left, content = list_area(size, len(rows))
    field = search_box(math.ceil(size[0]))
    state.query_focused = ui_hovered(cursor, field[0], field[1], field[2], field[3])
    if state.scroll.press(cursor, left + ROW_WIDTH + 6.0, top, bottom, content):
        return
    row = row_at(state, cursor, size)
    if row is not None:
        state.select(row)


def focus_row(
    state: State, cursor: tuple[float, float], size: tuple[float, float]
) -> bool:
    """``buffet.rs::focus_row``: фокус на строке; ``True``, если строка есть."""
    row = row_at(state, cursor, size)
    if row is None:
        return False
    state.query_focused = False
    state.select(row)
    return True


def wheel(
    state: State, delta: float, cursor: tuple[float, float], size: tuple[float, float]
) -> None:
    """``buffet.rs::wheel``: колесо над списком."""
    rows = state.rows()
    top, bottom, _left, content = list_area(size, len(rows))
    if cursor[1] < top or cursor[1] >= bottom:
        return
    state.scroll.wheel(delta, ROW_HEIGHT, top, bottom, content)


def drag(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> None:
    """``buffet.rs::drag``: перетаскивание полосы прокрутки."""
    rows = state.rows()
    top, bottom, _left, content = list_area(size, len(rows))
    state.scroll.drag(cursor[1], top, bottom, content)


def release(state: State) -> None:
    """``buffet.rs::release``: отпустить полосу прокрутки."""
    state.scroll.release()


def buttons(w: float, h: float, state: State) -> list[_CWButton]:
    """``buffet.rs::buttons``: Done (id 80) и Cancel (id 81)."""
    x = math.trunc((math.ceil(w) - 308.0) * 0.5)
    y = math.ceil(h) - 27.0
    return [
        _CWButton(
            x=x, y=y, w=150.0,
            label=lang.get_or("gui.done", "Done"),
            enabled=state.selected() is not None, id=80,
        ).does("Done"),
        _CWButton(
            x=x + 158.0, y=y, w=150.0,
            label=lang.get_or("gui.cancel", "Cancel"),
            enabled=True, id=81,
        ).does("Cancel"),
    ]


# ---------------------------------------------------------------------------
# рендер (buffet.rs L225-339)
# ---------------------------------------------------------------------------

def draw(
    batch: Batch,
    font: Optional[Font],
    state: State,
    cursor: tuple[float, float],
    size: tuple[float, float],
    atlas: Any = None,
) -> None:
    """``buffet.rs::draw``: фон, заголовок, поле поиска и строки."""
    if atlas is None:
        atlas = getattr(batch, "atlas", None)
    w, h = math.ceil(size[0]), math.ceil(size[1])
    draw_menu_background(batch, font, float(w), float(h))
    centered(batch, font, lang.get_or(
        "createWorld.customize.buffet.title", "Single Biome Customization"
    ), 8.0, w)

    field = search_box(w)
    if state.query or state.query_focused:
        edit_box(batch, font, field, state.query, state.query_focused)
    else:
        edit_box(batch, font, field, "", False)
        draw_text_(batch, font, lang.get_or(
            "createWorld.customize.buffet.search", "Search..."
        ), field[0] + 4.0, field[1] + 4.0)

    rows = state.rows()
    top, bottom, left, content = list_area((w, h), len(rows))
    list_background(batch, atlas, top, bottom, w)
    separators(batch, atlas, top, bottom, w)
    offset = math.trunc(state.scroll.amount)
    selected = state.selected()
    hovered_biome = row_at(state, cursor, (w, h))
    hovered = (
        None
        if hovered_biome is None
        else (rows.index(hovered_biome) if hovered_biome in rows else None)
    )
    for at, index in enumerate(rows):
        y = top + 2.0 + at * ROW_HEIGHT - offset
        target = [left, y - 2.0, ROW_WIDTH, ROW_HEIGHT]
        if selected == at:
            solid(batch, font, *target, rgba(255, 255, 255, 70))
        elif hovered == at:
            solid(batch, font, *target, rgba(255, 255, 255, 25))
        name = state.name(index)
        if name is not None:
            draw_text_(batch, font, name, left + 5.0, y)
    scrollbar(batch, atlas, left + ROW_WIDTH + 6.0, top, bottom, content,
              state.scroll.amount)


def draw_text_(
    batch: Batch, font: Optional[Font], text: str, x: float, y: float
) -> None:
    """``batch.text`` белым (как ``u32::MAX`` в Rust)."""
    draw_text(batch, font, text, x, y, rgba(255, 255, 255, 255))


# ---------------------------------------------------------------------------
# экран (title.rs::Mode::CreateBuffet)
# ---------------------------------------------------------------------------

class BuffetWorldScreen(Screen):
    """CreateBuffetWorldScreen как :class:`Screen`.

    Список биомов с поиском и кнопки Done (80)/Cancel (81). ``on_done``
    получает выбранный биом; ``on_cancel`` вызывается при Escape/Cancel.
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        root: Path | str = PACK_ROOT,
        biome: str = "minecraft:plains",
        stack: Optional[ScreenStack] = None,
        on_done: Optional[Callable[[str], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.stack = stack
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.root = Path(root)
        self.state = State.new(self.root, biome)
        self.cursor: tuple[float, float] = (-1.0, -1.0)
        self.buttons: list[Button] = []
        self.build()

    # -- сборка ----------------------------------------------------------

    def _size(self) -> tuple[float, float]:
        return (math.ceil(self.width), math.ceil(self.height))

    def build(self) -> None:
        w, h = self._size()
        self.buttons = [
            Button(
                x=b.x, y=b.y, w=b.w, h=20.0, label=b.label,
                active=b.enabled, on_click=self._dispatcher(b.id),
            )
            for b in buttons(w, h, self.state)
        ]

    def _dispatcher(self, bid: int) -> Callable[[], None]:
        return lambda: self._on_button(bid)

    def _on_button(self, bid: int) -> None:
        if bid == 80:
            self.done()
            return
        if bid == 81:
            self.cancel()
            return
        _log(f"неизвестная кнопка id={bid}")

    # -- действия (title.rs::close_buffet) ------------------------------

    def done(self) -> None:
        """Done (id 80): вернуть выбранный биом в Create New World."""
        if self.state.selected() is None:
            return
        if self.on_done is not None:
            self.on_done(self.state.biome)
        elif self.stack is not None:
            self.stack.pop()

    def cancel(self) -> None:
        """Cancel/Escape: закрыть без применения."""
        if self.on_cancel is not None:
            self.on_cancel()
            return
        if self.stack is not None:
            self.stack.pop()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        click(self.state, (mx, my), self._size())
        self.build()
        return True

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key in ("escape", "key.keyboard.escape"):
            self.cancel()
            return True
        if self.state.query_focused:
            if key in ("backspace", "key.keyboard.backspace"):
                self.state.query = self.state.query[:-1]
                self.build()
                return True
            if ch is not None and len(ch) == 1 and ch.isprintable():
                if len(self.state.query) < QUERY_MAX:
                    self.state.query += ch
                    self.build()
                return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        handled = False
        for button in self.buttons:
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        return handled

    def handle_scroll(self, dy: float) -> bool:
        before = self.state.scroll.amount
        wheel(self.state, dy, self.cursor, self._size())
        return self.state.scroll.amount != before

    def handle_release(self, mx: float, my: float) -> bool:
        release(self.state)
        return True

    # -- рендер ----------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw(batch, font, self.state, self.cursor, self._size())
        for button in self.buttons:
            button.render(batch, font)
