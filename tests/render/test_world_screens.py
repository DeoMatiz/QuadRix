#!/usr/bin/env python3
"""[QuadRix] Тесты экранов одиночного мира (Select World / Create World).

Проверяют порт ``horizon-client/src/title.rs`` (``Mode::Select``/
``Mode::Create``) и ``title/create_world.rs``:

    * ``WorldsStore`` — реестр миров (``saves/worlds.json``): save/load,
      add/remove, ``unique_folder``;
    * ``SelectWorldScreen`` — геометрия списка, выбор, поиск, удаление,
      кнопки футера (id 10..15);
    * ``CreateWorldScreen`` — таб-бар, поля имени/сида, cycle-кнопки,
      Create/Cancel;
    * подписи берутся из реального ``.local`` ``en_us`` (``selectWorld.*``).

FALLBACK'и экранов (JSON вместо ``level.dat``, таб-бар текстом, заглушки
Edit/Re-Create и т.п.) описаны в ``quadrix/render/world_screens.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quadrix.core import lang
from quadrix.render import create_world as cw
from quadrix.render.menu import load_language
from quadrix.render.ui import Batch, Font
from quadrix.render.world_screens import (
    LIST_BOTTOM,
    LIST_TOP,
    ROW_HEIGHT,
    ROW_WIDTH,
    CreateWorldScreen,
    SelectWorldScreen,
    WorldEntry,
    WorldsStore,
)


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
# WorldEntry / WorldsStore
# ---------------------------------------------------------------------------

def test_world_entry_round_trip() -> None:
    entry = WorldEntry(folder="alpha", name="Alpha", game_mode="creative", cheats=True)
    restored = WorldEntry.from_json(entry.to_json())
    assert restored is not None
    assert restored.folder == "alpha"
    assert restored.name == "Alpha"
    assert restored.game_mode == "creative"
    assert restored.cheats is True


def test_world_entry_rejects_invalid_json() -> None:
    assert WorldEntry.from_json(None) is None
    assert WorldEntry.from_json({"folder": "", "name": "x"}) is None
    assert WorldEntry.from_json({"folder": "x"}) is None


def test_worlds_store_add_save_load(tmp_path: Path) -> None:
    path = tmp_path / "saves" / "worlds.json"
    store = WorldsStore(path)
    assert len(store) == 0
    store.add(WorldEntry(folder="one", name="One"))
    store.add(WorldEntry(folder="two", name="Two"))
    assert path.is_file()

    reloaded = WorldsStore(path)
    assert [e.name for e in reloaded.entries] == ["One", "Two"]


def test_worlds_store_load_missing_file_is_empty(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "nope" / "worlds.json")
    assert store.entries == []


def test_worlds_store_load_ignores_garbage(tmp_path: Path) -> None:
    path = tmp_path / "worlds.json"
    path.write_text("not json", encoding="utf-8")
    assert WorldsStore(path).entries == []
    path.write_text(json.dumps([{"bad": 1}, {"folder": "ok", "name": "Ok"}]), encoding="utf-8")
    store = WorldsStore(path)
    assert len(store) == 1
    assert store.entries[0].folder == "ok"


def test_worlds_store_remove(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="A"))
    store.add(WorldEntry(folder="b", name="B"))
    removed = store.remove(0)
    assert removed is not None and removed.folder == "a"
    assert [e.folder for e in store.entries] == ["b"]
    assert store.remove(5) is None


def test_worlds_store_unique_folder(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    assert store.unique_folder("New World") == "New World"
    store.add(WorldEntry(folder="New World", name="New World"))
    assert store.unique_folder("New World") == "New World-2"
    store.add(WorldEntry(folder="New World-2", name="x"))
    assert store.unique_folder("New World") == "New World-3"


def test_worlds_store_unique_folder_empty_name(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    assert store.unique_folder("   ") == "world"


# ---------------------------------------------------------------------------
# SelectWorldScreen
# ---------------------------------------------------------------------------

def test_select_world_layout_constants_match_rust() -> None:
    # title.rs L32-36.
    assert LIST_TOP == 49.0
    assert LIST_BOTTOM == 60.0
    assert ROW_HEIGHT == 36.0
    assert ROW_WIDTH == 270.0


def test_select_world_lists_store_entries(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    store.add(WorldEntry(folder="b", name="Beta"))
    screen = SelectWorldScreen(854.0, 480.0, store=store)
    assert screen.list is not None
    assert len(screen.list.items) == 2
    assert screen.list.items[0].name == "Alpha"


def test_select_world_play_requires_selection(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    played: list[WorldEntry] = []
    screen = SelectWorldScreen(
        854.0, 480.0, store=store, on_play=played.append
    )
    # Ничего не выбрано — Play ничего не делает.
    assert screen._play_selected() is None
    assert played == []

    # Выбор строки + клик по Play (id 10).
    screen.list.selected = 0
    screen.buttons = screen._footer_buttons()
    play = next(b for b in screen.buttons if b.label == "Play Selected World")
    assert play.active is True
    screen._play_selected()
    assert [e.folder for e in played] == ["a"]


def test_select_world_row_click_selects(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    store.add(WorldEntry(folder="b", name="Beta"))
    screen = SelectWorldScreen(854.0, 480.0, store=store)
    assert screen.list is not None
    hit = screen.list.handle_click(screen.list.x + 5.0, screen.list.y + 5.0)
    assert hit is True
    assert screen.list.selected == 0
    assert screen.selected_entry() is not None
    assert screen.selected_entry().folder == "a"


def test_select_world_search_filters(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    store.add(WorldEntry(folder="b", name="Beta"))
    screen = SelectWorldScreen(854.0, 480.0, store=store)
    screen.query = "bet"
    screen.build()
    assert screen.list is not None
    assert [e.name for e in screen.list.items] == ["Beta"]


def test_select_world_delete_selected(tmp_path: Path) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    store.add(WorldEntry(folder="b", name="Beta"))
    screen = SelectWorldScreen(854.0, 480.0, store=store)
    screen.list.selected = 0
    removed = screen._delete_selected()
    assert removed is not None and removed.folder == "a"
    assert [e.folder for e in store.entries] == ["b"]
    # после удаления список пересобран
    assert len(screen.list.items) == 1


def test_select_world_back_callback(tmp_path: Path) -> None:
    called: list[int] = []
    screen = SelectWorldScreen(
        854.0, 480.0,
        store=WorldsStore(tmp_path / "worlds.json"),
        on_back=lambda: called.append(1),
    )
    assert screen.handle_key("escape") is True
    assert called == [1]


def test_select_world_footer_labels_from_local(tmp_path: Path, english) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    screen = SelectWorldScreen(854.0, 480.0, store=store)
    labels = {b.label for b in screen.buttons}
    assert "Play Selected World" in labels
    assert "Create New World" in labels
    assert "Re-Create" in labels


def test_select_world_create_button_callback(tmp_path: Path) -> None:
    called: list[int] = []
    screen = SelectWorldScreen(
        854.0, 480.0,
        store=WorldsStore(tmp_path / "worlds.json"),
        on_create=lambda: called.append(1),
    )
    create = next(b for b in screen.buttons if b.label == "Create New World")
    assert create.handle_click(create.x + 1.0, create.y + 1.0) is True
    assert called == [1]


# ---------------------------------------------------------------------------
# CreateWorldScreen
# ---------------------------------------------------------------------------

def test_create_world_default_name_and_mode() -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    assert screen.value_name() == "New World"
    assert screen.creative is False
    assert screen.options.hardcore is False


def test_create_world_tab_click_switches() -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    x0, width = cw.tabs(854.0)
    # Вкладка World (индекс 1).
    assert screen.handle_click(x0 + width + 5.0, 5.0) is True
    assert screen.options.tab == 1
    assert screen.seed_input is not None and screen.name_input is None


def test_create_world_tab_key_cycles() -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    assert screen.handle_key("tab") is True
    assert screen.options.tab == 1
    assert screen.handle_key("tab") is True
    assert screen.options.tab == 2


def test_create_world_name_persists_across_tab_switch() -> None:
    screen = CreateWorldScreen(854.0, 480.0, name="My World")
    # печатаем в поле имени (курсор — в конец, как после клика)
    screen.name_input.focused = True
    screen.name_input.cursor = len(screen.name_input.value)
    assert screen.handle_key("", "!") is True
    assert screen.value_name() == "My World!"
    # уходим на сид и обратно
    screen._set_tab(1)
    screen._set_tab(0)
    assert screen.value_name() == "My World!"


def test_create_world_cycle_game_mode() -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    gx, gy = cw.grid(854.0, 480.0, 0)
    # Кнопка режима игры (id 20): Survival → Hardcore → Creative.
    assert screen.handle_click(gx + 105.0, gy + 51.0) is True
    assert screen.options.hardcore is True
    assert screen.creative is False
    assert screen.handle_click(gx + 105.0, gy + 51.0) is True
    assert screen.creative is True
    assert screen.options.hardcore is False


def test_create_world_cycle_world_type_and_structures() -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    screen._set_tab(1)
    gx, gy = cw.grid(854.0, 480.0, 1)
    before = screen.options.world_type
    assert screen.handle_click(gx + 75.0, gy + 10.0) is True  # кнопка типа мира (id 25)
    assert screen.options.world_type != before
    # переключатель структур (id 27): gx+266, gy+73, 44 шириной
    before_structures = screen.options.structures
    assert screen.handle_click(gx + 266.0 + 5.0, gy + 73.0 + 5.0) is True
    assert screen.options.structures is (not before_structures)


def test_create_world_create_returns_values() -> None:
    captured: list = []
    screen = CreateWorldScreen(
        854.0, 480.0, name="Seedling", seed="42",
        on_create=lambda n, s, c, o: captured.append((n, s, c, o)),
    )
    assert screen.create() is True
    assert captured[0][0] == "Seedling"
    assert captured[0][1] == "42"
    assert captured[0][2] is False
    assert isinstance(captured[0][3], cw.WorldOptions)


def test_create_world_empty_name_rejected() -> None:
    captured: list = []
    screen = CreateWorldScreen(
        854.0, 480.0, name="   ",
        on_create=lambda *a: captured.append(a),
    )
    assert screen.create() is False
    assert captured == []


def test_create_world_create_button_click() -> None:
    captured: list = []
    screen = CreateWorldScreen(
        854.0, 480.0, name="World",
        on_create=lambda n, s, c, o: captured.append(n),
    )
    create = next(b for b in screen.buttons if b.label == "Create New World")
    assert create.handle_click(create.x + 1.0, create.y + 1.0) is True
    assert captured == ["World"]


def test_create_world_cancel_callback() -> None:
    called: list[int] = []
    screen = CreateWorldScreen(
        854.0, 480.0, on_cancel=lambda: called.append(1)
    )
    assert screen.handle_key("escape") is True
    assert called == [1]


def test_create_world_buttons_match_create_world_module() -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    ids = {b.label for b in screen.buttons}
    # Футер (id 21/22) присутствует.
    expected = cw.buttons(854.0, 480.0, False, screen.options)
    assert len(screen.buttons) == len(expected)
    assert "Create New World" in ids
    assert "Cancel" in ids


def test_create_world_labels_from_local(english) -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    labels = {b.label for b in screen.buttons}
    # ``selectWorld.gameMode`` превращается в "Game Mode: Survival".
    assert any(lbl.startswith("Game Mode:") for lbl in labels)
    assert "Allow Commands: OFF" in labels


# ---------------------------------------------------------------------------
# рендер
# ---------------------------------------------------------------------------

def test_select_world_renders(tmp_path: Path, font: Font) -> None:
    store = WorldsStore(tmp_path / "worlds.json")
    store.add(WorldEntry(folder="a", name="Alpha"))
    store.add(WorldEntry(folder="b", name="Beta"))
    screen = SelectWorldScreen(854.0, 480.0, store=store)
    batch = Batch()
    screen.render(batch, font)
    assert batch.quads  # что-то нарисовано


def test_create_world_renders_each_tab(font: Font) -> None:
    screen = CreateWorldScreen(854.0, 480.0)
    for tab in range(cw.tab_count()):
        screen._set_tab(tab)
        batch = Batch()
        screen.render(batch, font)
        assert batch.quads


# ---------------------------------------------------------------------------
# Customize → CreateFlatWorldScreen (WC4)
# ---------------------------------------------------------------------------

def test_create_world_customize_opens_flat_screen() -> None:
    from quadrix.render.flat import FlatWorldScreen
    from quadrix.render.menu import ScreenStack

    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=1))
    stack = ScreenStack(screen)
    screen.stack = stack
    screen.options.world_type = cw.WorldPreset.FLAT
    screen._on_button(26)
    assert isinstance(stack.current, FlatWorldScreen)
    assert stack.depth() == 2

    # Done возвращает в Create World и сохраняет слои.
    flat = stack.current
    flat.state.selected = 0  # верхний слой — grass_block
    flat._on_button(70)
    flat._on_button(72)
    assert stack.depth() == 1
    assert stack.current is screen
    assert screen.options.world_type is cw.WorldPreset.FLAT
    assert [layer.block for layer in screen.options.flat_settings.layers] == [
        "minecraft:bedrock", "minecraft:dirt",
    ]


def test_create_world_customize_cancel_keeps_settings() -> None:
    from quadrix.render.flat import FlatWorldScreen
    from quadrix.render.menu import ScreenStack

    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=1))
    stack = ScreenStack(screen)
    screen.stack = stack
    screen.options.world_type = cw.WorldPreset.FLAT
    screen.options.flat_settings = None
    screen._on_button(26)
    flat = stack.current
    assert isinstance(flat, FlatWorldScreen)
    flat.state.selected = 0
    flat._on_button(70)
    flat.handle_key("escape")  # Cancel — не применяет
    assert stack.depth() == 1
    assert screen.options.flat_settings is None


def test_create_world_customize_without_stack_is_safe(capsys) -> None:
    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=1))
    screen.options.world_type = cw.WorldPreset.FLAT
    screen._on_button(26)  # не должно падать без stack
    assert "[QuadRix]" in capsys.readouterr().out


def test_create_world_customize_single_biome_opens_buffet() -> None:
    from quadrix.render.buffet import BuffetWorldScreen
    from quadrix.render.menu import ScreenStack

    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=1))
    stack = ScreenStack(screen)
    screen.stack = stack
    screen.options.world_type = cw.WorldPreset.SINGLE_BIOME_SURFACE
    screen.options.single_biome = "minecraft:plains"
    screen._on_button(26)
    assert isinstance(stack.current, BuffetWorldScreen)
    buffet = stack.current
    index = next(
        i for i, b in enumerate(buffet.state.biomes) if b.id == "minecraft:desert"
    )
    buffet.state.select(index)
    buffet._on_button(80)  # Done
    assert stack.depth() == 1
    assert screen.options.world_type is cw.WorldPreset.SINGLE_BIOME_SURFACE
    assert screen.options.single_biome == "minecraft:desert"


def test_create_world_customize_single_biome_without_stack_is_safe(capsys) -> None:
    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=1))
    screen.options.world_type = cw.WorldPreset.SINGLE_BIOME_SURFACE
    screen._on_button(26)  # без stack — лог, не падение
    assert "[QuadRix]" in capsys.readouterr().out
