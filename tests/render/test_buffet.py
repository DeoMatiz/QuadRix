#!/usr/bin/env python3
"""[QuadRix] Тесты CreateBuffetWorldScreen (WC5).

Порт ``horizon/crates/horizon-client/src/title/buffet.rs``: ``Biome``/
``State`` (поиск, выбор биома), загрузка реестра биомов из реального
``.local`` (``worldgen/biomes.json``), геометрия списка/поля поиска, ввод
(клик/фокус/скролл) и рендер, плюс обёртка :class:`BuffetWorldScreen`.

FALLBACK'и (наррация/``row_target``, каретка/буфер поля поиска) описаны в
``quadrix/render/buffet.py`` и ``PORTING_STATE.yaml``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from quadrix.core import lang
from quadrix.render.buffet import (
    FOOTER,
    HEADER,
    ROW_HEIGHT,
    ROW_WIDTH,
    SEARCH_HEIGHT,
    SEARCH_TOP,
    SEARCH_WIDTH,
    Biome,
    BuffetWorldScreen,
    State,
    buttons,
    click,
    display_name,
    focus_row,
    list_area,
    load,
    row_at,
    search_box,
    wheel,
)
from quadrix.render.menu import load_language
from quadrix.render.ui import Batch, Font

ROOT = Path(".local/horizon-client/26.3")


@pytest.fixture(scope="module")
def font() -> Font:
    return Font.load()


@pytest.fixture()
def english():
    previous = lang.current()
    lang.set(load_language("en_us"))
    yield
    if previous is not None:
        lang.set(previous)


# ---------------------------------------------------------------------------
# load / display_name
# ---------------------------------------------------------------------------

def test_load_real_biomes_sorted(english) -> None:
    biomes = load(ROOT)
    assert len(biomes) == 67
    # отсортировано по (name.lower(), id)
    assert biomes == sorted(biomes, key=lambda b: (b.name.lower(), b.id))
    plains = next(b for b in biomes if b.id == "minecraft:plains")
    assert plains.name == "Plains"
    assert next(b for b in biomes if b.id == "minecraft:the_void").name == "The Void"


def test_load_missing_root_is_empty() -> None:
    assert load(Path("missing-root")) == []


def test_display_name_translates_and_falls_back(english) -> None:
    assert display_name("minecraft:plains") == "Plains"
    assert display_name("minecraft:snowy_plains") == "Snowy Plains"
    # id без имени в языке показывается как есть.
    assert display_name("minecraft:not_a_biome") == "minecraft:not_a_biome"
    # имя без namespace.
    assert display_name("plains") == "Plains"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_state_new_has_all_rows(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    assert state.biome == "minecraft:plains"
    assert state.query == "" and state.query_focused is False
    assert len(state.rows()) == len(state.biomes)
    assert state.rows() == list(range(len(state.biomes)))


def test_rows_filter_is_case_insensitive(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    state.query = "SNOW"
    names = [state.name(index) for index in state.rows()]
    assert names and all("snow" in (n or "").lower() for n in names)


def test_selected_tracks_biome_and_query(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    position = state.selected()
    assert position is not None
    assert state.biomes[state.rows()[position]].id == "minecraft:plains"
    # поиск, скрывающий plains, снимает выбор.
    state.query = "snow"
    assert state.selected() is None


def test_select_sets_biome(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    index = next(i for i, b in enumerate(state.biomes) if b.id == "minecraft:desert")
    state.select(index)
    assert state.biome == "minecraft:desert"
    assert state.selected() is not None
    # вне диапазона — без изменений.
    state.select(9999)
    assert state.biome == "minecraft:desert"


# ---------------------------------------------------------------------------
# геометрия
# ---------------------------------------------------------------------------

def test_list_area_and_search_box() -> None:
    top, bottom, left, content = list_area((854.0, 480.0), 10)
    assert top == HEADER and bottom == 480.0 - FOOTER
    assert left == math.floor((854 - ROW_WIDTH) * 0.5)
    assert content == 10 * ROW_HEIGHT + 4.0
    assert search_box(854.0) == [
        math.floor((854 - SEARCH_WIDTH) * 0.5), SEARCH_TOP, SEARCH_WIDTH, SEARCH_HEIGHT,
    ]


def test_row_at_and_click_select(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    size = (854.0, 480.0)
    top, _bottom, left, _content = list_area(size, len(state.rows()))
    cursor = (left + 5.0, top + 2.0 + 3.0)
    biome = row_at(state, cursor, size)
    assert biome is not None
    click(state, cursor, size)
    assert state.biome == state.biomes[biome].id
    # клик вне списка — без выбора.
    state.biome = "minecraft:plains"
    click(state, (left - 50.0, top + 3.0), size)
    assert state.biome == "minecraft:plains"


def test_click_focuses_search_box(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    field = search_box(854.0)
    click(state, (field[0] + 5.0, field[1] + 5.0), (854.0, 480.0))
    assert state.query_focused is True


def test_focus_row_clears_search_focus(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    state.query_focused = True
    size = (854.0, 480.0)
    top, _bottom, left, _content = list_area(size, len(state.rows()))
    assert focus_row(state, (left + 5.0, top + 3.0), size) is True
    assert state.query_focused is False


def test_buttons_done_needs_biome(english) -> None:
    state = State.new(ROOT, "minecraft:plains")
    out = buttons(854.0, 480.0, state)
    assert [b.id for b in out] == [80, 81]
    assert out[0].label == "Done" and out[1].label == "Cancel"
    assert out[0].enabled is True and out[1].enabled is True
    state.query = "zzz_nothing"
    assert state.selected() is None
    assert buttons(854.0, 480.0, state)[0].enabled is False


def test_wheel_scrolls_when_content_overflows(english) -> None:
    state = State.new(ROOT, "minecraft:plains")  # 67 строк — больше области
    size = (854.0, 480.0)
    wheel(state, -1.0, (400.0, HEADER + 10.0), size)
    assert state.scroll.amount == ROW_HEIGHT
    before = state.scroll.amount
    wheel(state, -1.0, (400.0, 5.0), size)  # вне списка
    assert state.scroll.amount == before


# ---------------------------------------------------------------------------
# рендер
# ---------------------------------------------------------------------------

def test_draw_adds_quads(english, font: Font) -> None:
    from quadrix.render.buffet import draw

    state = State.new(ROOT, "minecraft:plains")
    batch = Batch()
    draw(batch, font, state, (400.0, 100.0), (854.0, 480.0))
    assert batch.quads


# ---------------------------------------------------------------------------
# BuffetWorldScreen (обёртка)
# ---------------------------------------------------------------------------

def test_buffet_screen_done_applies_biome(english) -> None:
    captured: list[str] = []
    screen = BuffetWorldScreen(on_done=lambda b: captured.append(b))
    index = next(i for i, b in enumerate(screen.state.biomes) if b.id == "minecraft:desert")
    screen.state.select(index)
    screen._on_button(80)
    assert captured == ["minecraft:desert"]


def test_buffet_screen_done_ignored_without_selection(english) -> None:
    captured: list[str] = []
    screen = BuffetWorldScreen(on_done=lambda b: captured.append(b))
    screen.state.query = "zzz_nothing"
    screen._on_button(80)
    assert captured == []


def test_buffet_screen_cancel_and_escape(english) -> None:
    called: list[int] = []
    screen = BuffetWorldScreen(on_cancel=lambda: called.append(1))
    screen._on_button(81)
    assert called == [1]
    assert screen.handle_key("escape") is True
    assert called == [1, 1]


def test_buffet_screen_search_typing_and_backspace(english) -> None:
    screen = BuffetWorldScreen()
    screen.state.query_focused = True
    assert screen.handle_key("s", ch="s") is True
    assert screen.handle_key("n", ch="n") is True
    assert screen.state.query == "sn"
    assert screen.handle_key("backspace") is True
    assert screen.state.query == "s"
    # максимум 50 символов.
    screen.state.query = "x" * 50
    assert screen.handle_key("y", ch="y") is True
    assert len(screen.state.query) == 50


def test_buffet_screen_click_selects_and_scroll(english) -> None:
    screen = BuffetWorldScreen()
    size = (854.0, 480.0)
    top, _bottom, left, _content = list_area(size, len(screen.state.rows()))
    screen.handle_move(left + 5.0, top + 3.0)
    before = screen.state.scroll.amount
    assert screen.handle_scroll(-1.0) is True
    assert screen.state.scroll.amount != before
    assert screen.handle_release(0.0, 0.0) is True
    assert screen.state.scroll.is_held() is False


def test_buffet_screen_resize_and_render(english, font: Font) -> None:
    screen = BuffetWorldScreen()
    old_x = screen.buttons[0].x
    screen.on_resize(500.0, 320.0)
    assert screen.buttons and screen.buttons[0].x != old_x
    batch = Batch()
    screen.render(batch, font)
    assert batch.quads
