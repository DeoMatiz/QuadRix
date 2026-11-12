#!/usr/bin/env python3
"""[QuadRix] Мультиплеер: список серверов, Direct Connect, Add Server (PART 3).

Порт экранов многопользовательской игры Horizon:

    * ``horizon-client/src/multiplayer.rs`` — ``enum Screen`` со списком
      серверов (``List``), добавлением/правкой (``Edit``) и прямым
      подключением (``Direct``); кнопки футера списка (Join/Direct/Add/
      Edit/Delete/Refresh/Back, id 40..46) и экрана прямого подключения
      (Join id 52, Cancel id 53); ``Outcome::Connect { address, lan }`` —
      результат, который титульный экран превращает в ``Action::Connect``.
    * ``horizon-protocol/src/servers.rs`` — ``parse_address`` (``host``,
      ``host:port``, ``[v6]:port``; порт по умолчанию 25565) и
      ``ServerEntry``.

Поток: ``MainMenu`` → ``MultiplayerScreen`` → ``DirectConnectScreen`` →
ввод адреса → ``App.connect_server`` (реальное подключение, PART 3).

Хранение списка: Rust пишет ``servers.dat`` (NBT) рядом с ``saves/``.
QuadRix читает/пишет ``servers.json`` (FALLBACK: NBT-формат ``servers.dat``
не портирован в этой PART; интерфейс тот же — список ``ServerEntry``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.render.menu import (
    MAIN_MENU_BUTTON_HEIGHT,
    Screen,
    ScreenStack,
    ScrollableList,
    TextInput,
    draw_menu_background,
    draw_text,
)
from quadrix.render.ui import Batch, Button, Font

__all__ = [
    "ServerEntry",
    "ServersStore",
    "parse_address",
    "direct_address",
    "MultiplayerScreen",
    "DirectConnectScreen",
    "AddServerScreen",
]

#: Порт по умолчанию (servers.rs::parse_address).
DEFAULT_PORT: int = 25565

#: Максимальная длина адреса/имени (multiplayer.rs EditBox).
MAX_ADDRESS: int = 128
MAX_NAME: int = 64

#: Футер списка серверов (multiplayer.rs::Screen::buttons, List).
LIST_FOOTER_WIDTH = 308.0
LIST_ROW1_Y_OFFSET = 52.0
LIST_ROW2_Y_OFFSET = 28.0
LIST_ROW_HEIGHT = 18.0
LIST_ITEM_HEIGHT = 20.0

#: Прямое подключение (multiplayer.rs::Screen::buttons, Direct).
DIRECT_LABEL_Y = 100.0
DIRECT_BOX_Y = 116.0

#: Добавление сервера (multiplayer.rs::Screen::buttons, Edit).
EDIT_NAME_Y = 66.0
EDIT_ADDRESS_Y = 106.0


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] multiplayer: " + message)


def parse_address(text: str) -> Optional[tuple[str, int]]:
    """Разобрать адрес сервера (порт ``servers.rs::parse_address``).

    Поддерживает ``host``, ``host:port`` и ``[v6]:port``; порт по умолчанию
    ``25565``. Пустая строка, пустой host, ведущий ``+`` у порта и
    некорректный порт дают ``None``.
    """
    text = text.strip()
    if not text:
        return None
    if text.startswith("["):
        rest = text[1:]
        if "]" not in rest:
            return None
        host, _, tail = rest.rpartition("]")
        # HostAndPort требует двоеточие внутри скобок (это IPv6).
        if ":" not in host:
            return None
        port = _parse_bracket_tail(tail)
        if port is None:
            return None
        return host, port
    host, sep, port_text = text.rpartition(":")
    if sep and ":" not in host:
        if not host:
            return None
        parsed = _parse_port(port_text)
        if parsed is None:
            return None
        return host, parsed
    # Двоеточий несколько (голый IPv6) или нет вовсе — host без порта.
    return text, DEFAULT_PORT


def _parse_bracket_tail(tail: str) -> Optional[int]:
    """Хвост после ``]``: пусто → дефолт, ``:digits`` → порт, иначе ``None``."""
    if tail == "":
        return DEFAULT_PORT
    if not tail.startswith(":"):
        return None
    return _parse_port(tail[1:])


def _parse_port(text: str) -> Optional[int]:
    """Порт: пусто → 25565, ведущий ``+`` запрещён, диапазон 0..65535."""
    if text == "":
        return DEFAULT_PORT
    if text.startswith("+") or not text.isdigit():
        return None
    value = int(text)
    if value < 0 or value > 0xFFFF:
        return None
    return value


def direct_address(address: str) -> str:
    """Адрес из Direct Connect (порт ``multiplayer.rs::direct_address``).

    Полные приглашения друга (friend-invite) в PART 3 не портированы
    (secure_chat/friends pending), поэтому возвращается только ``trim``.
    # FALLBACK: friend-invite pending — friends не портированы.
    """
    return address.strip()


@dataclass
class ServerEntry:
    """Сохранённый сервер (порт ``servers::ServerEntry``)."""

    name: str
    address: str
    accept_textures: Optional[bool] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "address": self.address,
            "accept_textures": self.accept_textures,
        }

    @classmethod
    def from_json(cls, data: Any) -> Optional["ServerEntry"]:
        if not isinstance(data, dict):
            return None
        address = data.get("address")
        if not isinstance(address, str) or not address:
            return None
        name = data.get("name")
        if not isinstance(name, str) or not name:
            name = address
        packs = data.get("accept_textures")
        if not isinstance(packs, bool):
            packs = None
        return cls(name=name, address=address, accept_textures=packs)


class ServersStore:
    """Список серверов (порт ``servers::load``/``save``).

    FALLBACK: Rust хранит ``servers.dat`` (NBT); здесь — ``servers.json``.
    Формат — массив объектов ``{name, address, accept_textures}``.
    """

    def __init__(self, path: Path | str = Path("servers.json")) -> None:
        self.path = Path(path)
        self.entries: list[ServerEntry] = []
        self.load()

    def load(self) -> list[ServerEntry]:
        """Прочитать список; отсутствие/ошибка файла → пустой список."""
        self.entries = []
        try:
            if not self.path.exists():
                return self.entries
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log(f"servers.json не прочитан ({self.path}): {exc}")
            return self.entries
        if not isinstance(data, list):
            return self.entries
        for item in data:
            entry = ServerEntry.from_json(item)
            if entry is not None:
                self.entries.append(entry)
        return self.entries

    def save(self) -> None:
        """Записать список (по возможности; ошибки логируются)."""
        try:
            self.path.write_text(
                json.dumps([e.to_json() for e in self.entries], indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _log(f"servers.json не записан ({self.path}): {exc}")

    def add(self, entry: ServerEntry) -> None:
        """Добавить/обновить сервер по адресу (как ``servers::prepend``)."""
        self.entries = [e for e in self.entries if e.address != entry.address]
        self.entries.insert(0, entry)
        self.save()

    def remove(self, index: int) -> Optional[ServerEntry]:
        """Удалить запись по индексу (кнопка Delete)."""
        if index < 0 or index >= len(self.entries):
            return None
        entry = self.entries.pop(index)
        self.save()
        return entry

    def __len__(self) -> int:
        return len(self.entries)


# ---------------------------------------------------------------------------
# Список серверов (порт multiplayer.rs::Screen::List)
# ---------------------------------------------------------------------------

class MultiplayerScreen(Screen):
    """«Play Multiplayer»: список серверов + футер кнопок.

    Кнопки — как в Rust (id 40..46): Join Server (40, нужен выбор),
    Direct Connection (41), Add Server (42), Edit (43, нужен выбор),
    Delete (44, нужен выбор), Refresh (45), Back (46).
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        store: Optional[ServersStore] = None,
        stack: Optional[ScreenStack] = None,
        on_back: Optional[Callable[[], None]] = None,
        on_connect: Optional[Callable[[str], Any]] = None,
    ) -> None:
        super().__init__(width, height)
        self.store = store if store is not None else ServersStore()
        self.stack = stack
        self.on_back = on_back
        self.on_connect = on_connect
        self.list: Optional[ScrollableList] = None
        self.buttons: list[Button] = []
        self.build()

    # -- сборка ----------------------------------------------------------

    def build(self) -> None:
        """Собрать список и кнопки футера (multiplayer.rs::buttons, List)."""
        entries = self.store.entries
        list_height = self.height - 84.0
        self.list = ScrollableList(
            x=math.floor(self.width / 2.0) - 154.0,
            y=32.0,
            w=LIST_FOOTER_WIDTH,
            h=max(LIST_ITEM_HEIGHT, list_height),
            items=list(entries),
            item_height=LIST_ITEM_HEIGHT,
            selected=self._selected_index(),
            on_select=self._on_select,
            label_of=lambda e: f"{e.name}  ({e.address})",
        )
        self.buttons = self._footer_buttons()

    def _selected_index(self) -> Optional[int]:
        prev = getattr(self, "list", None)
        if prev is not None and prev.selected is not None:
            if 0 <= prev.selected < len(self.store.entries):
                return prev.selected
        return None

    def _footer_buttons(self) -> list[Button]:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        x = math.floor((w - LIST_FOOTER_WIDTH) / 2.0)
        y1 = h - LIST_ROW1_Y_OFFSET
        y2 = h - LIST_ROW2_Y_OFFSET
        saved = self._selected_index() is not None
        bh = MAIN_MENU_BUTTON_HEIGHT
        return [
            Button(x, y1, 100.0, bh,
                   lang.get_or("selectServer.select", "Join Server"),
                   on_click=self._join_selected, active=saved),
            Button(x + 104.0, y1, 100.0, bh,
                   lang.get_or("selectServer.direct", "Direct Connection"),
                   on_click=self._open_direct),
            Button(x + 208.0, y1, 100.0, bh,
                   lang.get_or("selectServer.add", "Add Server"),
                   on_click=self._open_add),
            Button(x, y2, 74.0, bh,
                   lang.get_or("selectServer.edit", "Edit"),
                   on_click=self._edit_selected, active=saved),
            Button(x + 78.0, y2, 74.0, bh,
                   lang.get_or("selectServer.delete", "Delete"),
                   on_click=self._delete_selected, active=saved),
            Button(x + 156.0, y2, 74.0, bh,
                   lang.get_or("selectServer.refresh", "Refresh"),
                   on_click=self._refresh),
            Button(x + 234.0, y2, 74.0, bh,
                   lang.get_or("gui.back", "Back"),
                   on_click=self._back),
        ]

    # -- действия --------------------------------------------------------

    def selected_entry(self) -> Optional[ServerEntry]:
        """Выбранная запись (или ``None``)."""
        idx = self._selected_index()
        if idx is None:
            return None
        return self.store.entries[idx]

    def _on_select(self, index: int, _item: Any) -> None:
        self.list.selected = index  # type: ignore[union-attr]
        self.buttons = self._footer_buttons()

    def _join_selected(self) -> Optional[ServerEntry]:
        entry = self.selected_entry()
        if entry is None:
            return None
        self._request_connect(entry.address)
        return entry

    def _request_connect(self, address: str) -> None:
        if self.on_connect is not None:
            self.on_connect(address)

    def _open_direct(self) -> "DirectConnectScreen":
        screen = DirectConnectScreen(
            self.width, self.height,
            stack=self.stack, on_connect=self.on_connect, on_back=self._back,
        )
        if self.stack is not None:
            self.stack.push(screen)
        return screen

    def _open_add(self) -> "AddServerScreen":
        screen = AddServerScreen(
            self.width, self.height,
            store=self.store, stack=self.stack, on_back=self._back,
        )
        if self.stack is not None:
            self.stack.push(screen)
        return screen

    def _edit_selected(self) -> Optional["AddServerScreen"]:
        entry = self.selected_entry()
        if entry is None:
            return None
        screen = AddServerScreen(
            self.width, self.height,
            store=self.store, stack=self.stack, on_back=self._back,
            index=self._selected_index(), entry=entry,
        )
        if self.stack is not None:
            self.stack.push(screen)
        return screen

    def _delete_selected(self) -> Optional[ServerEntry]:
        idx = self._selected_index()
        if idx is None:
            return None
        removed = self.store.remove(idx)
        self.build()
        return removed

    def _refresh(self) -> None:
        """Перечитать список с диска (кнопка Refresh)."""
        self.store.load()
        self.build()

    def _back(self) -> None:
        if self.on_back is not None:
            self.on_back()
            return
        if self.stack is not None:
            self.stack.pop()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
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
            self._join_selected()
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
        title = lang.get_or("multiplayer.title", "Play Multiplayer")
        if font is not None:
            tw = font.width(title)
            draw_text(batch, font, title,
                      math.floor((self.width - tw) / 2.0), 8.0)
        if self.list is not None:
            self.list.render(batch, font)
        for button in self.buttons:
            button.render(batch, font)


# ---------------------------------------------------------------------------
# Прямое подключение (порт multiplayer.rs::Screen::Direct)
# ---------------------------------------------------------------------------

class DirectConnectScreen(Screen):
    """«Direct Connection»: поле адреса + Join Server / Cancel (id 52/53)."""

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        stack: Optional[ScreenStack] = None,
        on_connect: Optional[Callable[[str], Any]] = None,
        on_back: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.stack = stack
        self.on_connect = on_connect
        self.on_back = on_back
        cx = math.floor(self.width / 2.0)
        self.input = TextInput(
            x=cx - 100.0, y=DIRECT_BOX_Y, w=200.0, h=20.0,
            value="", max_length=MAX_ADDRESS, focused=True,
        )
        self.buttons: list[Button] = []
        self.build()

    def build(self) -> None:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        cx = math.floor(w / 2.0)
        qy = math.floor(h / 4.0)
        valid = parse_address(self.value) is not None
        self.buttons = [
            Button(cx - 100.0, qy + 108.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
                   lang.get_or("selectServer.select", "Join Server"),
                   on_click=self.join, active=valid),
            Button(cx - 100.0, qy + 132.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
                   lang.get_or("gui.cancel", "Cancel"),
                   on_click=self._cancel),
        ]

    @property
    def value(self) -> str:
        return self.input.value

    def join(self) -> bool:
        """Подключиться к введённому адресу (порт ``Outcome::Connect``)."""
        if parse_address(self.value) is None:
            return False
        if self.on_connect is not None:
            self.on_connect(direct_address(self.value))
        return True

    def _cancel(self) -> None:
        if self.on_back is not None:
            self.on_back()
            return
        if self.stack is not None:
            self.stack.pop()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        if self.input.handle_click(mx, my):
            self.build()
            return True
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        return False

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if ch and len(ch) == 1 and ch.isprintable():
            if self.input.insert(ch):
                self.build()
            return True
        if key == "enter":
            return self.join()
        if key == "escape":
            self._cancel()
            return True
        if self.input.handle_key(key):
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

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw_menu_background(batch, font, self.width, self.height)
        title = lang.get_or("selectServer.direct", "Direct Connection")
        if font is not None:
            tw = font.width(title)
            draw_text(batch, font, title,
                      math.floor((self.width - tw) / 2.0), 20.0)
            label = lang.get_or("manageServer.enterIp", "Server Address")
            draw_text(batch, font, label, self.input.x + 1.0, DIRECT_LABEL_Y)
        self.input.render(batch, font)
        for button in self.buttons:
            button.render(batch, font)


# ---------------------------------------------------------------------------
# Добавление/правка сервера (порт multiplayer.rs::Screen::Edit)
# ---------------------------------------------------------------------------

class AddServerScreen(Screen):
    """«Add Server»/«Edit Server Info»: имя + адрес, Done (id 50), Cancel (51)."""

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        store: Optional[ServersStore] = None,
        stack: Optional[ScreenStack] = None,
        on_back: Optional[Callable[[], None]] = None,
        index: Optional[int] = None,
        entry: Optional[ServerEntry] = None,
    ) -> None:
        super().__init__(width, height)
        self.store = store if store is not None else ServersStore()
        self.stack = stack
        self.on_back = on_back
        self.index = index
        cx = math.floor(self.width / 2.0)
        name = entry.name if entry is not None else ""
        address = entry.address if entry is not None else ""
        self.name_input = TextInput(
            x=cx - 100.0, y=EDIT_NAME_Y, w=200.0, h=20.0,
            value=name, max_length=MAX_NAME, focused=True,
        )
        self.address_input = TextInput(
            x=cx - 100.0, y=EDIT_ADDRESS_Y, w=200.0, h=20.0,
            value=address, max_length=MAX_ADDRESS,
        )
        self.buttons: list[Button] = []
        self.build()

    def build(self) -> None:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        cx = math.floor(w / 2.0)
        qy = math.floor(h / 4.0)
        valid = parse_address(self.address) is not None
        self.buttons = [
            Button(cx - 100.0, qy + 114.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
                   lang.get_or("gui.done", "Done"),
                   on_click=self.done, active=valid),
            Button(cx - 100.0, qy + 138.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
                   lang.get_or("gui.cancel", "Cancel"),
                   on_click=self._cancel),
        ]

    @property
    def name(self) -> str:
        return self.name_input.value

    @property
    def address(self) -> str:
        return self.address_input.value

    def done(self) -> Optional[ServerEntry]:
        """Сохранить сервер (порт ``ServerEditScreen`` Done, id 50)."""
        if parse_address(self.address) is None:
            return None
        name = self.name.strip() or lang.get_or(
            "selectServer.defaultName", "Minecraft Server"
        )
        entry = ServerEntry(name=name, address=self.address.strip())
        if self.index is not None and 0 <= self.index < len(self.store.entries):
            self.store.entries[self.index] = entry
            self.store.save()
        else:
            self.store.add(entry)
        self._return()
        return entry

    def _cancel(self) -> None:
        self._return()

    def _return(self) -> None:
        if self.on_back is not None:
            self.on_back()
            return
        if self.stack is not None:
            self.stack.pop()

    # -- ввод ------------------------------------------------------------

    def _focused_input(self):
        if self.address_input.focused:
            return self.address_input
        return self.name_input

    def handle_click(self, mx: float, my: float) -> bool:
        if self.name_input.handle_click(mx, my):
            self.address_input.focused = False
            return True
        if self.address_input.handle_click(mx, my):
            self.name_input.focused = False
            return True
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        return False

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if ch and len(ch) == 1 and ch.isprintable():
            if self._focused_input().insert(ch):
                self.build()
            return True
        if key == "enter":
            return self.done() is not None
        if key == "escape":
            self._cancel()
            return True
        if self._focused_input().handle_key(key):
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

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw_menu_background(batch, font, self.width, self.height)
        title = lang.get_or("manageServer.add.title", "Add Server")
        if font is not None:
            tw = font.width(title)
            draw_text(batch, font, title,
                      math.floor((self.width - tw) / 2.0), 20.0)
            draw_text(batch, font,
                      lang.get_or("manageServer.enterName", "Server Name"),
                      self.name_input.x + 1.0, EDIT_NAME_Y - 12.0)
            draw_text(batch, font,
                      lang.get_or("manageServer.enterIp", "Server Address"),
                      self.address_input.x + 1.0, EDIT_ADDRESS_Y - 12.0)
        self.name_input.render(batch, font)
        self.address_input.render(batch, font)
        for button in self.buttons:
            button.render(batch, font)
