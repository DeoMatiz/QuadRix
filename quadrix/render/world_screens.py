#!/usr/bin/env python3
"""[QuadRix] Одиночный мир: Select World и Create World (WC2/WC3/WC8).

Порт экранов одиночной игры Horizon:

    * ``horizon-client/src/title.rs`` — ``Mode::Select`` (SelectWorldScreen):
      список миров (``LIST_TOP``/``LIST_BOTTOM``/``ROW_HEIGHT``/``ROW_WIDTH``),
      поиск, футер кнопок (Play id 10, Create id 11, Edit id 13, Delete 14,
      Re-Create 15, Back 12) и обработка кликов/клавиш.
    * ``horizon-client/src/title/create_world.rs`` — CreateWorldScreen:
      таб-бар (``create_world.TABS``), поля имени/сида, cycle-кнопки и футер
      (Create id 21, Cancel id 22). Модель/геометрия — :mod:`quadrix.render.create_world`.

Визуальная составляющая: фон меню (плитка ``gui/menu_background``), nine-slice
кнопки и заголовки — те же, что у MultiplayerScreen/OptionsScreen, чтобы экраны
читались как один UI.

FALLBACK (см. ``PORTING_STATE.yaml``):
    * таб-бар: спрайты ``gui/sprites/tab/*`` в атлас не добавлены — вкладки
      рисуются текстом с подсветкой выбранной;
    * список миров хранится в ``saves/worlds.json`` (Rust — ``level.dat``/NBT);
    * Create open: Play открывает локальный плоский мир (нет интегрированного
      сервера), см. ``App._play_world``;
    * Re-Create/Edit/Game Rules/Experiments/Data Packs/Customize(single-biome)
      — заглушки (``_not_ported``), PART'ы WC5/WC6/WC7/WC9. Customize для
      flat-пресета открывает :class:`quadrix.render.flat.FlatWorldScreen` (WC4).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.render import create_world as cw
from quadrix.render.menu import (
    BACKGROUND,
    LABEL_COLOR,
    Screen,
    ScreenStack,
    ScrollableList,
    TextInput,
    draw_menu_background,
    draw_text,
    solid,
)
from quadrix.render.ui import Batch, Button, Font, rgba

__all__ = [
    "WorldEntry",
    "WorldsStore",
    "SelectWorldScreen",
    "CreateWorldScreen",
    "list_top",
    "list_bottom",
    "list_row_height",
    "list_row_width",
]

# title.rs L32-36: SelectWorldScreen HeaderAndFooterLayout + строки списка.
LIST_TOP = 49.0
LIST_BOTTOM = 60.0
ROW_HEIGHT = 36.0
ROW_WIDTH = 270.0

# Информационная строка списка — серый (как ванильный ``WorldListEntry``).
INFO_COLOR = rgba(0x80, 0x80, 0x80, 255)


def list_top() -> float:
    """``title.rs::LIST_TOP``."""
    return LIST_TOP


def list_bottom() -> float:
    """``title.rs::LIST_BOTTOM``."""
    return LIST_BOTTOM


def list_row_height() -> float:
    """``title.rs::ROW_HEIGHT``."""
    return ROW_HEIGHT


def list_row_width() -> float:
    """``title.rs::ROW_WIDTH``."""
    return ROW_WIDTH


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] world: " + message)


def _tr(key: str, fallback: str) -> str:
    """``lang::get_or`` для подписей экрана."""
    return lang.get_or(key, fallback)


# ---------------------------------------------------------------------------
# запись мира и хранилище
# ---------------------------------------------------------------------------

@dataclass
class WorldEntry:
    """Строка мира (порт ``title.rs::WorldEntry``, урезанная до QuadRix)."""

    folder: str
    name: str
    version: str = "26.3"
    game_mode: str = "survival"
    hardcore: bool = False
    cheats: bool = False
    last_played: int = 0

    def can_play(self) -> bool:
        """``WorldEntry::can_play``: мир доступен для игры."""
        return bool(self.folder)

    def can_edit(self) -> bool:
        """``WorldEntry::can_edit``: мир редактируем."""
        return bool(self.folder)

    def mode_label(self) -> str:
        """Подпись режима игры (``selectWorld.gameMode.*``)."""
        key = (
            "selectWorld.gameMode.hardcore"
            if self.hardcore
            else f"selectWorld.gameMode.{self.game_mode}"
        )
        return _tr(key, self.game_mode.title())

    def info_line(self, folder_label: str, version_label: str) -> str:
        """Информационная строка списка (режим, читы, папка, версия)."""
        parts = [self.mode_label()]
        if self.cheats:
            parts.append(_tr("selectWorld.commands", "Commands"))
        parts.append(f"{folder_label}: {self.folder}")
        parts.append(f"{version_label} {self.version}")
        return ", ".join(parts)

    def to_json(self) -> dict[str, Any]:
        return {
            "folder": self.folder,
            "name": self.name,
            "version": self.version,
            "game_mode": self.game_mode,
            "hardcore": self.hardcore,
            "cheats": self.cheats,
            "last_played": self.last_played,
        }

    @classmethod
    def from_json(cls, data: Any) -> Optional["WorldEntry"]:
        if not isinstance(data, dict):
            return None
        folder = data.get("folder")
        name = data.get("name")
        if not isinstance(folder, str) or not folder:
            return None
        if not isinstance(name, str) or not name:
            return None
        return cls(
            folder=folder,
            name=name,
            version=str(data.get("version", "26.3")),
            game_mode=str(data.get("game_mode", "survival")),
            hardcore=bool(data.get("hardcore", False)),
            cheats=bool(data.get("cheats", False)),
            last_played=int(data.get("last_played", 0) or 0),
        )


class WorldsStore:
    """Список одиночных миров (``saves/worlds.json``).

    FALLBACK: Rust читает ``level.dat`` каждой папки ``saves/`` (NBT PART);
    здесь реестр миров — простой JSON, интерфейс тот же (``entries``).
    """

    def __init__(self, path: Path | str = Path("saves/worlds.json")) -> None:
        self.path = Path(path)
        self.entries: list[WorldEntry] = []
        self.load()

    def load(self) -> list[WorldEntry]:
        self.entries = []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.entries
        if not isinstance(raw, list):
            return self.entries
        for item in raw:
            entry = WorldEntry.from_json(item)
            if entry is not None:
                self.entries.append(entry)
        return self.entries

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([e.to_json() for e in self.entries], indent=2),
                encoding="utf-8",
            )
        except OSError as exc:  # noqa: BLE001 - диск недоступен, не критично
            _log(f"не сохранён список миров: {exc}")

    def add(self, entry: WorldEntry) -> None:
        self.entries.append(entry)
        self.save()

    def remove(self, index: int) -> Optional[WorldEntry]:
        if not 0 <= index < len(self.entries):
            return None
        removed = self.entries.pop(index)
        self.save()
        return removed

    def unique_folder(self, name: str) -> str:
        """Свободная папка для нового мира (``WorldStorage.getWorldFolder``)."""
        base = "".join(c for c in name if c.isalnum() or c in " _-").strip()
        base = base or "world"
        candidate = base
        taken = {e.folder for e in self.entries}
        n = 2
        while candidate in taken:
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def __len__(self) -> int:
        return len(self.entries)


# ---------------------------------------------------------------------------
# Select World (title.rs::Mode::Select)
# ---------------------------------------------------------------------------

class SelectWorldScreen(Screen):
    """«Select World»: список миров + поиск + футер (id 10..15)."""

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        store: Optional[WorldsStore] = None,
        stack: Optional[ScreenStack] = None,
        on_play: Optional[Callable[[WorldEntry], Any]] = None,
        on_create: Optional[Callable[[], Any]] = None,
        on_back: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.store = store if store is not None else WorldsStore()
        self.stack = stack
        self.on_play = on_play
        self.on_create = on_create
        self.on_back = on_back
        self.query = ""
        self.search: Optional[TextInput] = None
        self.list: Optional[ScrollableList] = None
        self.buttons: list[Button] = []
        self.build()

    # -- сборка ----------------------------------------------------------

    def build(self) -> None:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        list_x = math.floor((w - ROW_WIDTH) / 2.0)
        list_h = max(ROW_HEIGHT, h - LIST_TOP - LIST_BOTTOM)
        self.search = TextInput(
            x=list_x, y=22.0, w=ROW_WIDTH, h=18.0,
            value=self.query, max_length=64, focused=True,
        )
        self.list = ScrollableList(
            x=list_x,
            y=LIST_TOP,
            w=ROW_WIDTH,
            h=list_h,
            items=list(self._filtered()),
            item_height=ROW_HEIGHT,
            selected=self._selected_index(),
            on_select=self._on_select,
        )
        self.buttons = self._footer_buttons()

    def _filtered(self) -> list[WorldEntry]:
        q = self.query.strip().lower()
        if not q:
            return list(self.store.entries)
        return [e for e in self.store.entries if q in e.name.lower()]

    def _selected_index(self) -> Optional[int]:
        prev = getattr(self, "list", None)
        if prev is not None and prev.selected is not None:
            if 0 <= prev.selected < len(self._filtered()):
                return prev.selected
        return None

    def _folder_label(self) -> str:
        return _tr("selectWorld.world", "World")

    def _version_label(self) -> str:
        return _tr("selectWorld.version", "Version:")

    def _footer_buttons(self) -> list[Button]:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        cx = math.floor(w / 2.0)
        bh = 20.0
        has = self._selected_index() is not None
        return [
            Button(cx - 154.0, float(h) - 52.0, 150.0, bh,
                   _tr("selectWorld.select", "Play Selected World"),
                   on_click=self._play_selected, active=has),
            Button(cx + 4.0, float(h) - 52.0, 150.0, bh,
                   _tr("selectWorld.create", "Create New World"),
                   on_click=self._open_create),
            Button(cx - 154.0, float(h) - 28.0, 71.0, bh,
                   _tr("selectWorld.edit", "Edit"),
                   on_click=self._edit_selected, active=has),
            Button(cx - 75.0, float(h) - 28.0, 71.0, bh,
                   _tr("selectWorld.delete", "Delete"),
                   on_click=self._delete_selected, active=has),
            Button(cx + 4.0, float(h) - 28.0, 71.0, bh,
                   _tr("selectWorld.recreate", "Re-Create"),
                   on_click=self._recreate_selected, active=has),
            Button(cx + 83.0, float(h) - 28.0, 71.0, bh,
                   _tr("gui.back", "Back"), on_click=self._back),
        ]

    # -- действия --------------------------------------------------------

    def selected_entry(self) -> Optional[WorldEntry]:
        idx = self._selected_index()
        if idx is None:
            return None
        items = self._filtered()
        if 0 <= idx < len(items):
            return items[idx]
        return None

    def _on_select(self, index: int, _item: Any) -> None:
        if self.list is not None:
            self.list.selected = index
        self.buttons = self._footer_buttons()

    def _play_selected(self) -> Optional[WorldEntry]:
        entry = self.selected_entry()
        if entry is None or not entry.can_play():
            return None
        if self.on_play is not None:
            self.on_play(entry)
        return entry

    def _open_create(self) -> None:
        if self.on_create is not None:
            self.on_create()

    def _edit_selected(self) -> None:
        # FALLBACK: WorldEditScreen — PART WC9.
        self._not_ported("edit", 13)

    def _delete_selected(self) -> Optional[WorldEntry]:
        idx = self._selected_index()
        if idx is None:
            return None
        items = self._filtered()
        if not (0 <= idx < len(items)):
            return None
        target = items[idx]
        real = next(
            (i for i, e in enumerate(self.store.entries) if e is target), None
        )
        if real is None:
            return None
        removed = self.store.remove(real)
        self.build()
        return removed

    def _recreate_selected(self) -> None:
        # FALLBACK: Re-Create (WorldOptions из level.dat) — PART WC9.
        self._not_ported("recreate", 15)

    def _not_ported(self, what: str, bid: int) -> None:
        _log(f"кнопка id={bid} ({what}) ещё не портирована")

    def _back(self) -> None:
        if self.on_back is not None:
            self.on_back()
            return
        if self.stack is not None:
            self.stack.pop()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        if self.search is not None and self.search.handle_click(mx, my):
            return True
        if self.list is not None and self.list.handle_click(mx, my):
            return True
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        return False

    def handle_scroll(self, dy: float) -> bool:
        if self.list is None:
            return False
        return self.list.handle_scroll(dy)

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key == "escape":
            self._back()
            return True
        if key == "enter":
            self._play_selected()
            return True
        if self.search is not None and self.search.focused:
            if ch and len(ch) == 1 and ch.isprintable():
                if self.search.insert(ch):
                    self.query = self.search.value
                    self.build()
                return True
            if self.search.handle_key(key):
                self.query = self.search.value
                self.build()
                return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        handled = False
        for button in self.buttons:
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        return handled

    # -- рендер ----------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw_menu_background(batch, font, self.width, self.height)
        title = _tr("selectWorld.title", "Select World")
        if font is not None:
            draw_text(
                batch, font, title,
                math.floor((self.width - font.width(title)) / 2.0), 8.0,
            )
        # Поле поиска + подсказка.
        if self.search is not None:
            self.search.render(batch, font)
            if font is not None and not self.search.value:
                draw_text(
                    batch, font, _tr("selectWorld.search", "Search..."),
                    self.search.x + 4.0, self.search.y + 5.0, INFO_COLOR,
                )
        self._render_rows(batch, font)
        for button in self.buttons:
            button.render(batch, font)

    def _render_rows(self, batch: Batch, font: Optional[Font]) -> None:
        """Строки списка: иконка-заглушка, имя и информационная строка.

        FALLBACK: иконка мира (``icon.png``) не читается — квадрат-заглушка.
        """
        lst = self.list
        if lst is None:
            return
        folder_label = self._folder_label()
        version_label = self._version_label()
        for index, item in lst.visible_items():
            ry = lst.row_y(index)
            if ry + lst.item_height < lst.y or ry > lst.y + lst.h:
                continue
            if index == lst.selected:
                solid(batch, font, lst.x, ry, lst.w, lst.item_height, LABEL_COLOR)
                solid(batch, font, lst.x + 1.0, ry + 1.0, lst.w - 2.0,
                      lst.item_height - 2.0, BACKGROUND)
            # иконка 32x32 слева.
            entry_color = rgba(0x30, 0x30, 0x30, 255)
            solid(batch, font, lst.x + 2.0, ry + 2.0, 32.0, 32.0, entry_color)
            if font is None:
                continue
            draw_text(batch, font, item.name, lst.x + 38.0, ry + 3.0)
            draw_text(
                batch, font, item.info_line(folder_label, version_label),
                lst.x + 38.0, ry + 15.0, INFO_COLOR,
            )


# ---------------------------------------------------------------------------
# Create World (title.rs::Mode::Create + create_world.rs)
# ---------------------------------------------------------------------------

class CreateWorldScreen(Screen):
    """«Create New World»: таб-бар, поля имени/сида и cycle-кнопки."""

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        stack: Optional[ScreenStack] = None,
        on_create: Optional[Callable[[str, str, bool, cw.WorldOptions], Any]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        name: str = "New World",
        seed: str = "",
        creative: bool = False,
        options: Optional[cw.WorldOptions] = None,
    ) -> None:
        super().__init__(width, height)
        self.stack = stack
        self.on_create = on_create
        self.on_cancel = on_cancel
        self.name_input: Optional[TextInput] = None
        self.seed_input: Optional[TextInput] = None
        self.buttons: list[Button] = []
        self.creative = bool(creative)
        self.options = options if options is not None else cw.WorldOptions()
        self._name = name
        self._seed = seed
        self.build()

    # -- сборка ----------------------------------------------------------

    def build(self) -> None:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        # Создаём поле только активной вкладки (name — Game, seed — World):
        # у Rust виджеты вкладки существуют лишь пока вкладка открыта, поэтому
        # снятые с экрана поля не должны перехватывать клики.
        self.name_input = None
        self.seed_input = None
        if self.options.tab == 0:
            self.name_input = self._make_input(w, h, 0, self._name, 64)
            if self.name_input is not None:
                self._name = self.name_input.value
        elif self.options.tab == 1:
            self.seed_input = self._make_input(w, h, 1, self._seed, 32)
            if self.seed_input is not None:
                self._seed = self.seed_input.value
        self.buttons = self._ui_buttons(w, h)

    def _persist_fields(self) -> None:
        """Сохранить содержимое живых полей перед сменой вкладки/пересборкой."""
        if self.name_input is not None:
            self._name = self.name_input.value
        if self.seed_input is not None:
            self._seed = self.seed_input.value

    def _make_input(
        self, w: int, h: int, tab: int, value: str, max_len: int
    ) -> Optional[TextInput]:
        rect = cw.field_rect(float(w), float(h), tab)
        if rect is None:
            return None
        _fid, (fx, fy, fw, fh) = rect
        return TextInput(
            x=float(fx), y=float(fy), w=float(fw), h=float(fh),
            value=value, max_length=max_len, focused=False,
        )

    def _ui_buttons(self, w: int, h: int) -> list[Button]:
        out: list[Button] = []
        for b in cw.buttons(float(w), float(h), self.creative, self.options):
            out.append(Button(
                x=b.x, y=b.y, w=b.w, h=20.0, label=b.label,
                active=b.enabled, on_click=self._dispatcher(b.id),
            ))
        return out

    def _dispatcher(self, bid: int) -> Callable[[], None]:
        return lambda: self._on_button(bid)

    def _on_button(self, bid: int) -> None:
        if bid == 21:
            self.create()
        elif bid == 22:
            self.cancel()
        elif bid == 26:
            if self.options.world_type == cw.WorldPreset.SINGLE_BIOME_SURFACE:
                # FALLBACK: CreateBuffetWorldScreen — PART WC5.
                self._not_ported("customize", 26)
            else:
                self.open_flat()
        elif bid in (20, 23, 24, 25, 27, 28):
            self.creative = self.options.cycle(bid, self.creative, 1)
            self._persist_fields()
            self.build()
        elif bid in (29, 30, 31):
            # FALLBACK: Game Rules / Experiments / Data Packs — PART WC7.
            self._not_ported("more", bid)
        else:
            _log(f"неизвестная кнопка id={bid}")

    def _not_ported(self, what: str, bid: int) -> None:
        _log(f"кнопка id={bid} ({what}) ещё не портирована")

    # -- Customize → CreateFlatWorldScreen (WC4) -------------------------

    def open_flat(self) -> None:
        """Customize (id 26) для flat-пресета: открыть редактор слоёв."""
        from quadrix.render import flat as _flat

        if self.stack is None:
            self._not_ported("customize", 26)
            return
        self._persist_fields()
        screen = _flat.FlatWorldScreen(
            width=self.width,
            height=self.height,
            stack=self.stack,
            settings=self.options.flat_settings,
            on_done=self._apply_flat,
        )
        self.stack.push(screen)

    def _apply_flat(self, settings: Any) -> None:
        """Done в редакторе: сохранить слои и вернуться в Create New World."""
        self.options.world_type = cw.WorldPreset.FLAT
        self.options.flat_settings = settings
        if self.stack is not None:
            self.stack.pop()

    # -- действия --------------------------------------------------------

    def value_name(self) -> str:
        return self.name_input.value if self.name_input is not None else self._name

    def value_seed(self) -> str:
        return self.seed_input.value if self.seed_input is not None else self._seed

    def create(self) -> bool:
        """Создать мир (порт действия ``Create``): имя не пустое."""
        name = self.value_name().strip()
        if not name:
            return False
        if self.on_create is not None:
            self.on_create(
                name, self.value_seed(), self.creative, self.options
            )
        return True

    def cancel(self) -> None:
        if self.on_cancel is not None:
            self.on_cancel()
            return
        if self.stack is not None:
            self.stack.pop()

    def _focused_input(self) -> Optional[TextInput]:
        for i in (self.name_input, self.seed_input):
            if i is not None and i.focused:
                return i
        return None

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        tab = cw.tab_at(float(math.ceil(self.width)), (mx, my))
        if tab is not None:
            self._set_tab(tab)
            return True
        # Поля активной вкладки: клик фокусирует.
        for field in (self.name_input, self.seed_input):
            if field is not None and field.contains(mx, my):
                field.handle_click(mx, my)
                other = self.seed_input if field is self.name_input else self.name_input
                if other is not None:
                    other.focused = False
                return True
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        # Клик мимо — снять фокус.
        for field in (self.name_input, self.seed_input):
            if field is not None:
                field.focused = False
        return False

    def _set_tab(self, tab: int) -> None:
        if tab == self.options.tab:
            return
        self._persist_fields()
        self.options.tab = tab
        for field in (self.name_input, self.seed_input):
            if field is not None:
                field.focused = False
        self.build()

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key == "escape":
            self.cancel()
            return True
        if key == "tab":
            self._set_tab((self.options.tab + 1) % cw.tab_count())
            return True
        if key == "enter":
            if self.create():
                return True
            return False
        field = self._focused_input()
        if field is not None:
            if ch and len(ch) == 1 and ch.isprintable():
                return bool(field.insert(ch))
            if field.handle_key(key):
                return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        handled = False
        for button in self.buttons:
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        return handled

    # -- рендер ----------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw_menu_background(batch, font, self.width, self.height)
        tab = self.options.tab
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        self._render_field_labels(batch, font, tab, w, h)
        # Активное поле ввода.
        active = self.name_input if tab == 0 else self.seed_input if tab == 1 else None
        if active is not None:
            active.render(batch, font)
        self._render_tabs(batch, font, w)
        for button in self.buttons:
            button.render(batch, font)

    def _render_field_labels(
        self, batch: Batch, font: Optional[Font], tab: int, w: int, h: int
    ) -> None:
        if font is None:
            return
        if tab == 0:
            rect = cw.field_rect(float(w), float(h), 0)
            if rect is not None:
                _fid, (fx, fy, _fw, _fh) = rect
                draw_text(batch, font, _tr("selectWorld.enterName", "World Name"),
                          float(fx), float(fy) - 10.0)
        elif tab == 1:
            rect = cw.field_rect(float(w), float(h), 1)
            if rect is not None:
                _fid, (fx, fy, _fw, _fh) = rect
                draw_text(batch, font, _tr("selectWorld.enterSeed", "Seed for the world generator"),
                          float(fx), float(fy) - 10.0)
            # SwitchGrid: подписи слева от кнопок ON/OFF (x = gx+266).
            gx, gy = cw.grid(float(w), float(h), 1)
            draw_text(batch, font, _tr("selectWorld.mapFeatures", "Generate Structures"),
                      float(gx), float(gy) + 73.0 + 6.0)
            draw_text(batch, font, _tr("selectWorld.bonusItems", "Bonus Chest"),
                      float(gx), float(gy) + 97.0 + 6.0)

    def _render_tabs(self, batch: Batch, font: Optional[Font], w: int) -> None:
        """Таб-бар: подсветка выбранной вкладки + подпись (FALLBACK без спрайтов)."""
        x0, width = cw.tabs(float(w))
        h = cw.TAB_BAR
        for i, key in enumerate(cw.TABS):
            x = x0 + i * width
            selected = i == self.options.tab
            color = LABEL_COLOR if not selected else rgba(0xFF, 0xFF, 0xFF, 255)
            if selected:
                solid(batch, font, x, 0.0, width, h, rgba(0x59, 0x59, 0x59, 255))
                solid(batch, font, x, h - 2.0, width, 2.0,
                      rgba(0xFF, 0xFF, 0xFF, 255))
            label = _tr(key, key.rsplit(".", 2)[-2].title())
            if font is not None:
                tw = font.width(label)
                draw_text(batch, font, label,
                          x + (width - tw) / 2.0, math.floor((h - 8.0) / 2.0),
                          color)
