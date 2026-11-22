#!/usr/bin/env python3
"""[QuadRix] Тесты CreateFlatWorldScreen (WC4).

Порт ``horizon/crates/horizon-client/src/title/flat.rs``:
``FlatLayer``/``FlatSettings`` (сериализация и ``parse``), загрузка пресетов
из реального ``.local``, геометрия списка/кнопок, ввод (клик/фокус/скролл),
имена и рендер.

FALLBACK'и (``from_world``, 3D-иконки предметов, наррация) описаны в
``quadrix/render/flat.py`` и ``PORTING_STATE.yaml``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from quadrix.core import lang
from quadrix.render.flat import (
    HEADER,
    LAYER_ROW,
    PRESET_ROW,
    ROW_WIDTH,
    Y_SIZE,
    FlatLayer,
    FlatSettings,
    Page,
    Preset,
    Scroll,
    State,
    click,
    draw,
    focus_row,
    item_name,
    layer_item,
    list_area,
    load,
    namespaced,
    preset_name,
    pretty,
    selection_after_removal,
    share_field,
    wheel,
)
from quadrix.render.menu import load_language
from quadrix.render.ui import Batch, Font
from quadrix.world.nbt import Tag, TagType

ROOT = Path(".local/horizon-client/26.3")
PRESET_IDS = [
    "minecraft:classic_flat",
    "minecraft:tunnelers_dream",
    "minecraft:water_world",
    "minecraft:overworld",
    "minecraft:snowy_kingdom",
    "minecraft:bottomless_pit",
    "minecraft:desert",
    "minecraft:redstone_ready",
    "minecraft:the_void",
]


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


def _layer(block: str, height: int) -> Tag:
    return Tag(TagType.Compound, compound_val={
        "block": Tag(TagType.String, str_val=block),
        "height": Tag(TagType.Int, int_val=height),
    })


def _layers(*layers: Tag) -> Tag:
    return Tag(TagType.Compound, compound_val={
        "layers": Tag(TagType.List, list_val=list(layers)),
    })


# ---------------------------------------------------------------------------
# FlatSettings: namespaced / to_share / NBT round-trip
# ---------------------------------------------------------------------------

def test_namespaced_adds_default_namespace() -> None:
    assert namespaced("dirt") == "minecraft:dirt"
    assert namespaced("minecraft:dirt") == "minecraft:dirt"
    assert namespaced("") == ""


def test_default_settings_to_share() -> None:
    assert FlatSettings.default().to_share() == (
        "minecraft:bedrock,2*minecraft:dirt,minecraft:grass_block;minecraft:plains"
    )


def test_to_tag_from_tag_round_trip() -> None:
    settings = FlatSettings(
        biome="minecraft:desert", features=True, lakes=True,
        layers=[FlatLayer("minecraft:sand", 3), FlatLayer("minecraft:bedrock", 1)],
        structure_overrides=["minecraft:villages"],
    )
    restored = FlatSettings.from_tag(settings.to_tag())
    assert restored == settings
    # features/lakes — byte 0/1 (FlatLevelGeneratorSettings.CODEC).
    tag = settings.to_tag()
    assert tag.compound_val["features"].byte_val == 1
    assert tag.compound_val["lakes"].byte_val == 1


def test_from_tag_void_world_is_valid() -> None:
    """``layers: []`` — корректный void-мир (не ошибка разбора)."""
    out = FlatSettings.from_tag(_layers())
    assert out is not None
    assert out.layers == []


def test_from_tag_missing_layers_is_none() -> None:
    assert FlatSettings.from_tag(Tag(TagType.Compound, compound_val={})) is None
    broken = Tag(TagType.Compound, compound_val={
        "layers": Tag(TagType.List, list_val=[Tag(TagType.Compound, compound_val={})]),
    })
    assert FlatSettings.from_tag(broken) is None


def test_from_tag_clamps_height() -> None:
    out = FlatSettings.from_tag(_layers(
        _layer("minecraft:dirt", 999_999),
        _layer("minecraft:stone", -5),
    ))
    assert out is not None
    assert out.layers[0].height == Y_SIZE
    assert out.layers[1].height == 0


def test_from_tag_structure_overrides_string_and_list() -> None:
    tag = _layers(_layer("minecraft:dirt", 1))
    tag.compound_val["structure_overrides"] = Tag(
        TagType.String, str_val="minecraft:villages"
    )
    assert FlatSettings.from_tag(tag).structure_overrides == ["minecraft:villages"]

    tag2 = _layers(_layer("minecraft:dirt", 1))
    tag2.compound_val["structure_overrides"] = Tag(TagType.List, list_val=[
        Tag(TagType.String, str_val="minecraft:strongholds"),
        Tag(TagType.String, str_val="minecraft:villages"),
    ])
    assert FlatSettings.from_tag(tag2).structure_overrides == [
        "minecraft:strongholds", "minecraft:villages",
    ]


def test_from_world_not_ported() -> None:
    """FALLBACK: чтение ``level.dat`` (PART сохранения мира) — None."""
    assert FlatSettings.from_world(Path("missing")) is None


# ---------------------------------------------------------------------------
# FlatSettings.parse (PresetFlatWorldScreen.fromString)
# ---------------------------------------------------------------------------

BLOCKS = {"minecraft:bedrock", "minecraft:dirt", "minecraft:stone"}
BIOMES = {"minecraft:plains", "minecraft:desert"}


def _base() -> FlatSettings:
    return FlatSettings(
        features=True, lakes=True,
        structure_overrides=["minecraft:strongholds"],
    )


def test_parse_layers_and_decorations() -> None:
    out = FlatSettings.parse(
        "minecraft:bedrock,2*minecraft:dirt;minecraft:desert",
        BLOCKS, BIOMES, _base(),
    )
    assert out is not None
    assert [(layer.block, layer.height) for layer in out.layers] == [
        ("minecraft:bedrock", 1), ("minecraft:dirt", 2),
    ]
    assert out.biome == "minecraft:desert"
    # Декорации берутся из base.
    assert out.features is True and out.lakes is True
    assert out.structure_overrides == ["minecraft:strongholds"]


def test_parse_bare_names_get_namespace() -> None:
    out = FlatSettings.parse("dirt;desert", {"minecraft:dirt"}, BIOMES, _base())
    assert out is not None
    assert out.layers[0].block == "minecraft:dirt"
    assert out.biome == "minecraft:desert"


def test_parse_rejects_unknown_block_and_empty() -> None:
    assert FlatSettings.parse("minecraft:gold_block;minecraft:plains",
                              BLOCKS, BIOMES, _base()) is None
    assert FlatSettings.parse(";minecraft:plains", BLOCKS, BIOMES, _base()) is None
    assert FlatSettings.parse("x*minecraft:dirt;minecraft:plains",
                              BLOCKS, BIOMES, _base()) is None


def test_parse_unknown_biome_falls_back_to_plains() -> None:
    out = FlatSettings.parse("minecraft:dirt;minecraft:the_end",
                             BLOCKS, BIOMES, _base())
    assert out is not None and out.biome == "minecraft:plains"


def test_parse_clamps_and_skips_zero_height() -> None:
    out = FlatSettings.parse("0*minecraft:dirt,99999*minecraft:stone;minecraft:plains",
                             BLOCKS, BIOMES, _base())
    assert out is not None
    assert [(layer.block, layer.height) for layer in out.layers] == [
        ("minecraft:stone", Y_SIZE),
    ]


# ---------------------------------------------------------------------------
# load: реальные данные .local
# ---------------------------------------------------------------------------

def test_load_reads_presets_in_visible_order() -> None:
    presets, blocks, biomes = load(ROOT)
    assert [preset.id for preset in presets] == PRESET_IDS
    assert len(blocks) > 1000
    assert "minecraft:grass_block" in blocks
    assert "minecraft:plains" in biomes and "minecraft:the_void" in biomes


def test_load_classic_flat_settings() -> None:
    presets, _blocks, _biomes = load(ROOT)
    classic = next(p for p in presets if p.id == "minecraft:classic_flat")
    assert classic.display == "minecraft:grass_block"
    assert classic.settings.biome == "minecraft:plains"
    assert [(l.block, l.height) for l in classic.settings.layers] == [
        ("minecraft:bedrock", 1), ("minecraft:dirt", 2), ("minecraft:grass_block", 1),
    ]
    assert classic.settings.structure_overrides == ["minecraft:villages"]


def test_load_the_void_settings() -> None:
    presets, _blocks, _biomes = load(ROOT)
    void = next(p for p in presets if p.id == "minecraft:the_void")
    assert void.settings.biome == "minecraft:the_void"
    assert void.settings.features is True
    assert [(l.block, l.height) for l in void.settings.layers] == [("minecraft:air", 1)]
    assert void.settings.structure_overrides == []


def test_load_missing_root_is_empty() -> None:
    presets, blocks, biomes = load(Path("missing-root"))
    assert presets == [] and blocks == set() and biomes == set()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_state_new_uses_current_settings() -> None:
    current = FlatSettings.default()
    state = State.new(ROOT, current)
    assert state.settings is current
    assert state.share == current.to_share()
    assert len(state.presets) == 9


def test_state_open_presets_and_back() -> None:
    state = State.new(ROOT, None)
    state.open_presets()
    assert state.page == Page.PRESETS
    assert state.share == state.settings.to_share()
    state.back_to_layers()
    assert state.page == Page.LAYERS


def test_select_preset_puts_settings_in_share() -> None:
    state = State.new(ROOT, None)
    state.open_presets()
    state.select_preset(0)
    assert state.selecting() == 0
    assert state.preset_pressed == 0
    assert state.share == state.presets[0].settings.to_share()


def test_apply_share_overrides_layers_keeps_decorations() -> None:
    state = State.new(ROOT, None)
    state.open_presets()
    state.select_preset(0)  # classic_flat
    state.share = "minecraft:bedrock,5*minecraft:dirt;minecraft:plains"
    state.apply_share()
    assert state.page == Page.LAYERS
    assert [(l.block, l.height) for l in state.settings.layers] == [
        ("minecraft:bedrock", 1), ("minecraft:dirt", 5),
    ]
    # Декорации выбранного пресета сохраняются.
    assert state.settings.structure_overrides == ["minecraft:villages"]


def test_apply_share_malformed_falls_back_to_default() -> None:
    state = State.new(ROOT, None)
    state.open_presets()
    state.share = "minecraft:not_a_block;minecraft:plains"
    state.apply_share()
    assert state.settings.to_share() == FlatSettings.default().to_share()


def test_remove_selected_keeps_row_in_place() -> None:
    state = State.new(ROOT, None)
    # default: [bedrock, dirt, grass]; top row — grass_block.
    state.selected = 0
    state.remove_selected()
    assert [l.block for l in state.settings.layers] == [
        "minecraft:bedrock", "minecraft:dirt",
    ]
    assert state.selected == 0


def test_selection_after_removal() -> None:
    assert selection_after_removal(0, 3) == 0
    assert selection_after_removal(2, 3) == 2
    assert selection_after_removal(3, 3) == 2
    assert selection_after_removal(0, 0) is None


# ---------------------------------------------------------------------------
# геометрия
# ---------------------------------------------------------------------------

def test_list_area_layers_and_presets() -> None:
    state = State.new(ROOT, None)
    top, bottom, left, rows = list_area(state, (854.0, 480.0))
    assert top == 43.0 and bottom == 420.0
    assert left == math.floor((854 - ROW_WIDTH) * 0.5)
    assert rows == HEADER + 3 * LAYER_ROW + 4.0

    state.open_presets()
    top, bottom, left, rows = list_area(state, (854.0, 480.0))
    assert top == 80.0 and bottom == 443.0
    assert rows == 9 * PRESET_ROW + 4.0


def test_buttons_layers(english) -> None:
    from quadrix.render.flat import buttons

    state = State.new(ROOT, None)
    state.selected = None
    out = buttons(854.0, 480.0, state)
    assert [b.id for b in out] == [70, 71, 72, 73]
    assert out[0].label == "Remove Layer" and out[0].enabled is False
    assert out[1].label == "Presets"
    assert out[2].action == "Done" and out[3].action == "Cancel"

    state.selected = 1
    assert buttons(854.0, 480.0, state)[0].enabled is True


def test_buttons_presets(english) -> None:
    from quadrix.render.flat import buttons

    state = State.new(ROOT, None)
    state.open_presets()
    out = buttons(854.0, 480.0, state)
    assert [b.id for b in out] == [74, 75]
    assert out[0].label == "Use Preset"
    # Select активна: share длиннее одного символа.
    assert out[0].enabled is True
    state.share = ";"
    assert buttons(854.0, 480.0, state)[0].enabled is False


def test_layer_row_and_preset_row() -> None:
    state = State.new(ROOT, None)
    size = (854.0, 480.0)
    top, _bottom, _left, _rows = list_area(state, size)
    # Заголовок — не строка.
    from quadrix.render.flat import layer_row
    assert layer_row(state, (320.0, top + 2.0 + HEADER - 1.0), size) is None
    assert layer_row(state, (320.0, top + 2.0 + HEADER + 1.0), size) == 0
    assert layer_row(state, (320.0, top + 2.0 + HEADER + LAYER_ROW + 1.0), size) == 1

    state.open_presets()
    size = (854.0, 480.0)
    top, _bottom, _left, _rows = list_area(state, size)
    from quadrix.render.flat import preset_row
    assert preset_row(state, (320.0, top + 2.0 + 1.0), size) == 0


def test_click_selects_layer() -> None:
    state = State.new(ROOT, None)
    size = (854.0, 480.0)
    top, _bottom, _left, _rows = list_area(state, size)
    click(state, (320.0, top + 2.0 + HEADER + LAYER_ROW + 1.0), size)
    assert state.selected == 1


def test_focus_row_keeps_share_but_click_sets_it() -> None:
    """Порт Rust-теста: выбор пресета фокусом не трогает share-текст."""
    state = State.new(Path("missing"), None)
    state.settings.layers.clear()
    state.presets.append(Preset(
        id="minecraft:test", display="Test", settings=FlatSettings.default(),
    ))
    state.page = Page.PRESETS
    state.share = "typed"
    size = (480.0, 262.0)
    top, _bottom, left, _rows = list_area(state, size)
    row = (left + 1.0, top + 3.0)
    assert focus_row(state, row, size) is True
    assert state.selecting() == 0
    assert state.share == "typed"
    click(state, row, size)
    assert state.share == state.presets[0].settings.to_share()


def test_share_field() -> None:
    assert share_field((300.0, 200.0)) == [50.0, 40.0, 200.0, 20.0]
    assert share_field((10.0, 10.0))[2] == 1.0


def test_wheel_scrolls_layers() -> None:
    state = State.new(ROOT, None)
    state.settings.layers = [FlatLayer("minecraft:dirt", 1) for _ in range(100)]
    size = (854.0, 480.0)
    wheel(state, -1.0, (320.0, 100.0), size)
    assert state.scroll.amount == LAYER_ROW
    # Вне области списка колесо не прокручивает.
    before = state.scroll.amount
    wheel(state, -1.0, (320.0, 10.0), size)
    assert state.scroll.amount == before


def test_scroll_press_drag_release() -> None:
    scroll = Scroll()
    # Полоса — колонка 6px, начинающаяся в bar_x.
    assert scroll.press((2.0, 5.0), 0.0, 0.0, 20.0, 100.0) is True
    assert scroll.is_held() is True
    scroll.drag(15.0, 0.0, 20.0, 100.0)
    assert scroll.amount > 0.0
    scroll.release()
    assert scroll.is_held() is False
    # Без content скроллбар не берётся.
    assert Scroll().press((2.0, 5.0), 0.0, 0.0, 20.0, 10.0) is False


# ---------------------------------------------------------------------------
# имена / иконки
# ---------------------------------------------------------------------------

def test_layer_item() -> None:
    assert layer_item("minecraft:grass_block") == "minecraft:grass_block"
    assert layer_item("dirt") == "minecraft:dirt"
    assert layer_item("minecraft:water") == "minecraft:water_bucket"
    assert layer_item("minecraft:lava") == "minecraft:lava_bucket"


def test_item_preset_and_pretty_names(english) -> None:
    assert item_name("minecraft:grass_block") == "Grass Block"
    assert item_name("minecraft:water") == "Water Bucket"
    assert preset_name("minecraft:classic_flat") == "Classic Flat"
    assert preset_name("minecraft:the_void") == "The Void"
    assert pretty("grass_block") == "Grass Block"
    assert pretty("") == ""


def test_layer_icon_without_atlas_is_none() -> None:
    from quadrix.render.flat import layer_icon
    assert layer_icon(None, "minecraft:grass_block") is None


# ---------------------------------------------------------------------------
# рендер
# ---------------------------------------------------------------------------

def test_draw_layers_and_presets_add_quads(font: Font) -> None:
    state = State.new(ROOT, None)
    batch = Batch()
    draw(batch, font, state, (320.0, 100.0), (854.0, 480.0))
    assert batch.quads

    state.open_presets()
    batch.clear()
    draw(batch, font, state, (320.0, 100.0), (854.0, 480.0))
    assert batch.quads


def test_draw_buttons_adds_quads(font: Font) -> None:
    from quadrix.render.flat import draw_buttons
    state = State.new(ROOT, None)
    batch = Batch()
    draw_buttons(batch, font, 854.0, 480.0, state)
    assert batch.quads


# ---------------------------------------------------------------------------
# FlatWorldScreen (обёртка вокруг State)
# ---------------------------------------------------------------------------

def _screen(**kwargs) -> "FlatWorldScreen":
    from quadrix.render.flat import FlatWorldScreen

    return FlatWorldScreen(**kwargs)


def test_flat_screen_starts_on_layers() -> None:
    screen = _screen()
    assert screen.state.page is Page.LAYERS
    assert [b.label for b in screen.buttons] == [
        "Remove Layer", "Presets", "Done", "Cancel",
    ]
    assert screen.buttons[0].active is False


def test_flat_screen_presets_then_cancel_returns_to_layers() -> None:
    screen = _screen()
    screen._on_button(71)
    assert screen.state.page is Page.PRESETS
    assert [b.label for b in screen.buttons] == ["Use Preset", "Cancel"]
    screen._on_button(75)
    assert screen.state.page is Page.LAYERS
    assert [b.label for b in screen.buttons][1] == "Presets"


def test_flat_screen_remove_enables_when_selected() -> None:
    screen = _screen()
    screen.state.selected = 0
    screen.build()
    assert screen.buttons[0].active is True  # Remove Layer


def test_flat_screen_done_applies_settings() -> None:
    captured: list[FlatSettings] = []
    screen = _screen(on_done=lambda s: captured.append(s))
    screen.state.selected = 0  # верхний слой — grass_block
    screen._on_button(70)
    screen._on_button(72)
    assert len(captured) == 1
    assert [layer.block for layer in captured[0].layers] == [
        "minecraft:bedrock", "minecraft:dirt",
    ]


def test_flat_screen_cancel_on_layers_calls_callback() -> None:
    called: list[int] = []
    screen = _screen(on_cancel=lambda: called.append(1))
    assert screen.handle_key("escape") is True
    assert called == [1]


def test_flat_screen_escape_on_presets_returns_to_layers() -> None:
    called: list[int] = []
    screen = _screen(on_cancel=lambda: called.append(1))
    screen._on_button(71)
    assert screen.handle_key("escape") is True
    assert screen.state.page is Page.LAYERS
    assert called == []  # пресеты не закрывают экран


def test_flat_screen_select_preset_then_use_preset() -> None:
    screen = _screen()
    screen._on_button(71)
    preset = screen.state.presets[1]  # tunnelers_dream
    screen.state.select_preset(1)
    screen._on_button(74)  # Use Preset
    assert screen.state.page is Page.LAYERS
    assert [(l.block, l.height) for l in screen.state.settings.layers] == [
        (l.block, l.height) for l in preset.settings.layers
    ]


def test_flat_screen_share_editing() -> None:
    screen = _screen()
    screen._on_button(71)
    screen.state.share = "minecraft:dirt"
    screen.state.share_focused = True
    assert screen.handle_key("key.keyboard.backspace") is True
    assert screen.state.share == "minecraft:dir"
    assert screen.handle_key("x", ch="t") is True
    assert screen.state.share == "minecraft:dirt"


def test_flat_screen_resize_rebuilds_buttons() -> None:
    screen = _screen()
    old_x = screen.buttons[0].x
    screen.on_resize(500.0, 300.0)
    assert screen.buttons and screen.buttons[0].x != old_x


def test_flat_screen_scroll_and_release() -> None:
    screen = _screen()
    screen.state.settings.layers = [
        FlatLayer("minecraft:dirt", 1) for _ in range(100)
    ]
    screen.handle_move(320.0, 100.0)
    before = screen.state.scroll.amount
    assert screen.handle_scroll(-1.0) is True
    assert screen.state.scroll.amount > before
    assert screen.handle_release(0.0, 0.0) is True
    assert screen.state.scroll.is_held() is False


def test_flat_screen_render_adds_quads(font: Font) -> None:
    screen = _screen()
    batch = Batch()
    screen.render(batch, font)
    assert batch.quads
    screen._on_button(71)
    batch.clear()
    screen.render(batch, font)
    assert batch.quads
