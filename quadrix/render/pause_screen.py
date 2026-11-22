#!/usr/bin/env python3
"""[QuadRix] Меню паузы в игре (PauseScreen).

Порт ``horizon-client/src/game/screens.rs`` (только пауза; DeathScreen —
следующий PART):

    * ``pause_grid``    — GridLayout из двух колонок 98px (padding 4),
      выровнен в ``(0.5, 0.25)``.
    * ``pause_buttons`` — кнопки с их id: Return to Game (0), Advancements (4),
      Statistics (3), Options (1), World Options (9), и нижняя
      Disconnect (мультиплеер) / Save and Quit to Title (локально) id 2.
    * ``pause_icons``   — ряд иконок (bug/feedback/friends/reporting).
    * ``execute_pause_action`` — диспетчер действий по id.

Раньше ``Escape`` в игре сразу закрывал соединение и мир — это неверно:
ваниль открывает PauseScreen, и только кнопка нижнего ряда покидает мир.
``GameScreen.handle_key('escape')`` теперь вызывает ``open_pause_menu()``.

FALLBACK (см. ``PORTING_STATE.yaml``):
    * серверные ссылки (id 11), additions-диалоги (14), split-settings (30),
      Advancements (4), Statistics (3), World Options (9) и иконки
      bug/feedback/friends/reporting — не портированы (внешние экраны/ссылки);
      кнопки присутствуют, но логируют «не портировано».
    * фон меню рисуется ванильным спрайтом ``gui/menu_background``; блюр
      ``extractBackground`` (``game.rs::menu_blur``) не портирован — мир
      остаётся видимым за меню 1:1 как в паузе без постобработки.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.render.menu import (
    Screen,
    ScreenStack,
    draw_menu_background,
    draw_text,
)
from quadrix.render.ui import Batch, Button, Font

__all__ = [
    "PauseMenuScreen",
    "pause_grid",
    "pause_buttons",
    "pause_icons",
    "PAUSE_ICONS",
    "PAUSE_GRID_WIDTH",
    "PAUSE_GRID_HEIGHT",
    "PAUSE_GRID_PADDING",
]


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] pause: " + message)


def _tr(key: str, fallback: str) -> str:
    """``lang::get_or`` для подписей экрана."""
    return lang.get_or(key, fallback)


# game/screens.rs L53-56: сетка паузы.
PAUSE_GRID_WIDTH = 212.0
PAUSE_GRID_HEIGHT = 166.0
PAUSE_GRID_PADDING = 4.0
PAUSE_GRID_ROW = 24.0


def pause_grid(w: float, h: float, extra_rows: int = 0) -> tuple[float, float]:
    """``screens.rs::pause_grid``: origin сетки (2 колонки 98px)."""
    grid_w = PAUSE_GRID_WIDTH
    grid_h = PAUSE_GRID_HEIGHT + PAUSE_GRID_ROW * extra_rows
    return (
        math.floor((w - grid_w) * 0.5),
        math.floor((h - grid_h) * 0.25),
    )


def pause_buttons(
    w: float,
    h: float,
    remote: bool,
    links: bool = False,
    additions: bool = False,
    split: bool = False,
) -> list[tuple[float, float, float, str, int, bool]]:
    """``screens.rs::pause_buttons``: (x, y, ширина, ключ подписи, id, активна).

    ``links``/``additions``/``split`` оставлены для точной геометрии, но в
    QuadRix не используются (FALLBACK); подписи берутся из ``lang``.
    """
    row3 = links or additions
    x0, y0 = pause_grid(w, h, int(row3) + int(split))
    down = PAUSE_GRID_ROW * (int(row3) + int(split))
    v: list[tuple[float, float, float, str, int, bool]] = [
        (x0 + 4.0, y0 + 50.0, 204.0, "menu.returnToGame", 0, True),
        (x0 + 4.0, y0 + 74.0, 98.0, "gui.advancements", 4, True),
        (x0 + 110.0, y0 + 74.0, 98.0, "gui.stats", 3, True),
    ]
    if additions:
        v.append((x0 + 4.0, y0 + 122.0, 204.0, "", 14, True))
    elif links:
        v.append((x0 + 4.0, y0 + 122.0, 204.0, "menu.server_links", 11, True))
    if split:
        y = y0 + 122.0 + (PAUSE_GRID_ROW if row3 else 0.0)
        v.append((x0 + 4.0, y, 204.0, "horizon.pages.split_settings", 30, True))
    v.extend([
        (x0 + 4.0, y0 + 122.0 + down, 98.0, "menu.options", 1, True),
        (
            x0 + 110.0,
            y0 + 122.0 + down,
            98.0,
            "options.worldOptions.button",
            9,
            True,
        ),
        (
            x0 + 4.0,
            y0 + 146.0 + down,
            204.0,
            "menu.disconnect" if remote else "menu.returnToMenu",
            2,
            True,
        ),
    ])
    return v


#: Иконки паузы (``screens.rs::pause_icons``): спрайты и их id.
PAUSE_ICONS: tuple[tuple[str, int], ...] = (
    ("gui/sprites/pause_menu/bug", 12),
    ("gui/sprites/pause_menu/social_interactions", 13),
    ("gui/sprites/friends/friends", 10),
    ("gui/sprites/pause_menu/player_reporting", 15),
)


def pause_icons(
    w: float,
    h: float,
    links: bool = False,
    additions: bool = False,
    split: bool = False,
) -> list[tuple[float, float, str]]:
    """``screens.rs::pause_icons``: 4 иконки 20x20 под кнопками статистики."""
    x0, y0 = pause_grid(w, h, int(links or additions) + int(split))
    bx, by = x0 + 60.0, y0 + 98.0
    return [
        (bx, by, PAUSE_ICONS[0][0]),
        (bx + 24.0, by, PAUSE_ICONS[1][0]),
        (bx + 48.0, by, PAUSE_ICONS[2][0]),
        (bx + 72.0, by, PAUSE_ICONS[3][0]),
    ]


class PauseMenuScreen(Screen):
    """Экран паузы: Return to Game + Options/Stats/... + Save and Quit.

    Не закрывает мир при открытии; нижняя кнопка (id 2) покидает мир/сервер
    через ``on_leave``; Return to Game (id 0) и ``Escape`` — ``on_resume``.
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        remote: bool = False,
        stack: Optional[ScreenStack] = None,
        on_resume: Optional[Callable[[], None]] = None,
        on_options: Optional[Callable[[], None]] = None,
        on_advancements: Optional[Callable[[], None]] = None,
        on_stats: Optional[Callable[[], None]] = None,
        on_world_options: Optional[Callable[[], None]] = None,
        on_leave: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.remote = bool(remote)
        self.stack = stack
        self.on_resume = on_resume
        self.on_options = on_options
        self.on_advancements = on_advancements
        self.on_stats = on_stats
        self.on_world_options = on_world_options
        self.on_leave = on_leave
        self.buttons: list[Button] = []
        self.icons: list[Button] = []
        self.build()

    # -- сборка ----------------------------------------------------------

    def build(self) -> None:
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        self.buttons = [
            Button(
                x=x, y=y, w=bw, h=20.0, label=self._label(key, bid),
                on_click=self._dispatcher(bid), active=active,
            )
            for x, y, bw, key, bid, active in pause_buttons(
                float(w), float(h), self.remote
            )
        ]
        self.icons = [
            Button(
                x=x, y=y, w=20.0, h=20.0, label="", icon=sprite,
                on_click=self._dispatcher(icon_id), active=True,
            )
            for (x, y, sprite), (_sprite, icon_id) in zip(
                pause_icons(float(w), float(h)), PAUSE_ICONS
            )
        ]

    def _label(self, key: str, bid: int) -> str:
        if bid == 2:
            fallback = "Disconnect" if self.remote else "Save and Quit to Title"
            return _tr(key, fallback)
        fallbacks = {
            0: "Back to Game",
            1: "Options...",
            3: "Statistics",
            4: "Advancements",
            9: "World Options...",
        }
        return _tr(key, fallbacks.get(bid, key))

    def _dispatcher(self, bid: int) -> Callable[[], None]:
        return lambda: self._activate(bid)

    # -- действия (screens.rs::execute_pause_action) ---------------------

    def _activate(self, hit: int) -> None:
        if hit == 0:
            self.resume()
        elif hit == 1:
            self._call(self.on_options, "options", hit)
        elif hit == 2:
            self.leave()
        elif hit == 3:
            self._call(self.on_stats, "stats", hit)
        elif hit == 4:
            self._call(self.on_advancements, "advancements", hit)
        elif hit == 9:
            self._call(self.on_world_options, "world_options", hit)
        elif hit in (10, 11, 12, 13, 14, 15, 30):
            self._not_ported(hit)
        else:
            _log(f"неизвестная кнопка id={hit}")

    @staticmethod
    def _call(callback: Optional[Callable[[], None]], what: str, bid: int) -> None:
        if callback is not None:
            callback()
        else:
            _log(f"кнопка id={bid} ({what}) ещё не портирована")

    def _not_ported(self, bid: int) -> None:
        _log(f"кнопка id={bid} ещё не портирована")

    def resume(self) -> None:
        """Return to Game (id 0): закрыть паузу, вернуть управление."""
        if self.on_resume is not None:
            self.on_resume()
        elif self.stack is not None:
            self.stack.pop()

    def leave(self) -> None:
        """Save and Quit to Title / Disconnect (id 2)."""
        if self.on_leave is not None:
            self.on_leave()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        for button in (*self.buttons, *self.icons):
            if button.handle_click(mx, my):
                return True
        return False

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        # PauseScreen: Escape = Return to Game.
        if key in ("escape", "key.keyboard.escape"):
            self.resume()
            return True
        if key == "enter":
            # Активировать кнопку под фокусом — фокуса нет, вернуть в игру.
            self.resume()
            return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        handled = False
        for button in (*self.buttons, *self.icons):
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        return handled

    # -- рендер ----------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        # ui::menu_background(batch, atlas, 0, 0, w, h, true).
        draw_menu_background(batch, font, self.width, self.height)
        if font is not None:
            title = _tr("menu.game", "Game Menu")
            draw_text(
                batch, font, title,
                math.floor((self.width - font.width(title)) / 2.0), 40.0,
            )
        for button in (*self.buttons, *self.icons):
            button.render(batch, font)
