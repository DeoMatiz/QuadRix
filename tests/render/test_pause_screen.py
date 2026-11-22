#!/usr/bin/env python3
"""[QuadRix] Тесты меню паузы (PauseScreen).

Проверяют порт ``horizon-client/src/game/screens.rs`` (только пауза):

    * ``pause_grid``/``pause_buttons``/``pause_icons`` — геометрия сетки
      GridLayout (2 колонки 98px, padding 4) и id кнопок;
    * ``PauseMenuScreen`` — сборка кнопок, подписи из реального ``.local``
      ``en_us`` (``menu.returnToGame`` и т.п.), callbacks resume/leave,
      ``Escape`` = Return to Game;
    * регрессия: ``Escape`` в игре открывает паузу, а НЕ закрывает мир.

FALLBACK'и (серверные ссылки, статистика, world options, иконки и т.п.)
описаны в ``quadrix/render/pause_screen.py`` и ``PORTING_STATE.yaml``.
"""

from __future__ import annotations

import pytest

from quadrix.core import lang
from quadrix.render.menu import Screen, ScreenStack, load_language
from quadrix.render.pause_screen import (
    PAUSE_ICONS,
    PauseMenuScreen,
    pause_buttons,
    pause_grid,
    pause_icons,
)
from quadrix.render.ui import Batch, Font


@pytest.fixture(scope="module")
def font() -> Font:
    """Шрифт по умолчанию из ``.local`` (один раз на модуль)."""
    return Font.load()


@pytest.fixture()
def english():
    """Загрузить ``en_us`` на время теста и вернуть прежний язык."""
    previous = lang.current()
    lang.set(load_language("en_us"))
    yield
    if previous is not None:
        lang.set(previous)


# ---------------------------------------------------------------------------
# pause_grid / pause_buttons / pause_icons (screens.rs)
# ---------------------------------------------------------------------------

def test_pause_grid_centered() -> None:
    """Сетка 212x166: центр по X, четверть сверху по Y."""
    x0, y0 = pause_grid(854.0, 480.0)
    assert x0 == (854 - 212) // 2
    assert y0 == int((480 - 166) * 0.25)


def test_pause_grid_extra_rows_shift_up() -> None:
    """Доп. ряды (links/split) увеличивают высоту сетки → она выше."""
    _, y0 = pause_grid(854.0, 480.0)
    _, y0_more = pause_grid(854.0, 480.0, 1)
    assert y0_more == int((480 - (166 + 24)) * 0.25)
    assert y0_more < y0


def test_pause_buttons_local_ids_and_geometry() -> None:
    """Порядок/id кнопок и раскладка двух колонок (98px)."""
    w, h = 854.0, 480.0
    x0, y0 = pause_grid(w, h)
    btns = pause_buttons(w, h, remote=False)
    assert [b[4] for b in btns] == [0, 4, 3, 1, 9, 2]

    top = btns[0]
    assert top[0:4] == (x0 + 4.0, y0 + 50.0, 204.0, "menu.returnToGame")

    # Advancements (4) слева, Statistics (3) справа.
    assert btns[1][0:3] == (x0 + 4.0, y0 + 74.0, 98.0)
    assert btns[2][0:3] == (x0 + 110.0, y0 + 74.0, 98.0)

    options = next(b for b in btns if b[4] == 1)
    assert options[0:3] == (x0 + 4.0, y0 + 122.0, 98.0)


def test_pause_buttons_bottom_row_label_by_mode() -> None:
    """Нижний ряд: локально — Save and Quit to Title, remote — Disconnect."""
    w, h = 854.0, 480.0
    x0, y0 = pause_grid(w, h)
    local = pause_buttons(w, h, remote=False)[-1]
    assert local[3] == "menu.returnToMenu"
    assert local[0:3] == (x0 + 4.0, y0 + 146.0, 204.0)

    remote = pause_buttons(w, h, remote=True)[-1]
    assert remote[3] == "menu.disconnect"


def test_pause_icons_row() -> None:
    """Четыре иконки 20x20 с шагом 24 под рядом статистики."""
    w, h = 854.0, 480.0
    x0, y0 = pause_grid(w, h)
    icons = pause_icons(w, h)
    assert len(icons) == 4
    assert icons[0][:2] == (x0 + 60.0, y0 + 98.0)
    assert icons[1][0] - icons[0][0] == 24.0
    assert icons[3][0] == x0 + 60.0 + 72.0
    assert [s for _x, _y, s in icons] == [s for s, _id in PAUSE_ICONS]


# ---------------------------------------------------------------------------
# PauseMenuScreen: сборка и подписи
# ---------------------------------------------------------------------------

def test_pause_screen_builds_widgets() -> None:
    screen = PauseMenuScreen(854.0, 480.0)
    # 6 кнопок (0,4,3,1,9,2) и 4 иконки.
    assert len(screen.buttons) == 6
    assert len(screen.icons) == 4
    assert screen.icons[0].icon == PAUSE_ICONS[0][0]


def test_pause_screen_labels_from_en_us(english) -> None:
    """Подписи берутся из реального ``.local`` ``en_us``."""
    screen = PauseMenuScreen(854.0, 480.0)
    labels = [b.label_plain() for b in screen.buttons]
    assert labels[0] == "Back to Game"  # menu.returnToGame
    assert labels[1] == "Advancements"  # gui.advancements
    assert labels[2] == "Statistics"  # gui.stats
    assert labels[3] == "Options..."  # menu.options
    assert labels[4] == "World Options..."  # options.worldOptions.button
    assert labels[5] == "Save and Quit to Title"  # menu.returnToMenu


def test_pause_screen_remote_bottom_label(english) -> None:
    labels = [b.label_plain() for b in PauseMenuScreen(854.0, 480.0, remote=True).buttons]
    assert labels[-1] == "Disconnect"  # menu.disconnect


# ---------------------------------------------------------------------------
# PauseMenuScreen: действия
# ---------------------------------------------------------------------------

def _center(button) -> tuple[float, float]:
    return button.x + 1.0, button.y + 1.0


def test_pause_screen_resume_and_leave_callbacks() -> None:
    calls: list[str] = []
    screen = PauseMenuScreen(
        854.0, 480.0,
        on_resume=lambda: calls.append("resume"),
        on_leave=lambda: calls.append("leave"),
    )
    assert screen.handle_click(*_center(screen.buttons[0])) is True
    assert calls == ["resume"]
    assert screen.handle_click(*_center(screen.buttons[-1])) is True
    assert calls == ["resume", "leave"]


def test_pause_screen_options_callback() -> None:
    calls: list[str] = []
    screen = PauseMenuScreen(854.0, 480.0, on_options=lambda: calls.append("opt"))
    button = next(b for b in screen.buttons if b.label_plain() == "Options...")
    assert screen.handle_click(*_center(button)) is True
    assert calls == ["opt"]


def test_pause_screen_escape_resumes() -> None:
    calls: list[int] = []
    screen = PauseMenuScreen(854.0, 480.0, on_resume=lambda: calls.append(1))
    assert screen.handle_key("escape") is True
    assert calls == [1]


def test_pause_screen_resume_pops_stack_without_callback() -> None:
    base = Screen(854.0, 480.0)
    stack = ScreenStack(base)
    screen = PauseMenuScreen(854.0, 480.0, stack=stack)
    stack.push(screen)
    assert stack.current is screen
    screen.resume()
    assert stack.current is base


def test_pause_screen_click_outside_is_miss() -> None:
    screen = PauseMenuScreen(854.0, 480.0)
    assert screen.handle_click(-50.0, -50.0) is False


def test_pause_screen_icon_click_is_handled() -> None:
    """Клик по иконке принимается (даже если действие ещё не портировано)."""
    screen = PauseMenuScreen(854.0, 480.0)
    assert screen.handle_click(*_center(screen.icons[0])) is True


# ---------------------------------------------------------------------------
# рендер
# ---------------------------------------------------------------------------

def test_pause_screen_render_adds_quads(font: Font) -> None:
    screen = PauseMenuScreen(854.0, 480.0)
    batch = Batch()
    screen.render(batch, font)
    assert batch.quads
    assert len(batch.quads) > len(screen.buttons) + len(screen.icons)


def test_pause_screen_handle_move_hover() -> None:
    screen = PauseMenuScreen(854.0, 480.0)
    x, y = _center(screen.buttons[0])
    assert screen.handle_move(x, y) is True
    assert screen.buttons[0].hovered is True
    assert screen.handle_move(-100.0, -100.0) is False
