"""Тесты ``quadrix/render/create_world.py`` (WC1: модель и геометрия).

Сверяем WorldOptions и геометрию Create World с ``title/create_world.rs``,
используя реальный ``en_us`` из ``.local`` для подписей.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

from quadrix.core import lang
from quadrix.core.lang import Language
from quadrix.render.create_world import (
    DIFFICULTIES,
    FOOTER,
    TAB_BAR,
    TABS,
    WorldOptions,
    buttons,
    field_at,
    field_rect,
    game_mode,
    grid,
    labelled,
    next_tab_index,
    numeric_key,
    on_off,
    round_toward,
    tab_at,
    tab_count,
    tabs,
    tr,
)
from quadrix.save.world_preset import WorldPreset

PACK_ROOT = Path(".local/horizon-client/26.3")


@functools.lru_cache(maxsize=1)
def _english() -> Language:
    return Language.load_from(PACK_ROOT, "en_us")


@pytest.fixture(autouse=True)
def _set_english() -> None:
    lang.set(_english())


def test_constants_match_rust() -> None:
    assert TAB_BAR == 24.0
    assert FOOTER == 33.0
    assert TABS == (
        "createWorld.tab.game.title",
        "createWorld.tab.world.title",
        "createWorld.tab.more.title",
    )
    assert DIFFICULTIES == ("peaceful", "easy", "normal", "hard")


def test_round_toward() -> None:
    assert round_toward(5.0, 2.0) == 6.0
    assert round_toward(4.0, 2.0) == 4.0
    assert round_toward(0.0, 2.0) == 0.0


def test_tabs_geometry() -> None:
    x0, tw = tabs(854.0)
    assert x0 == 242.0
    assert tw == 124.0


def test_tab_at_hit_and_miss() -> None:
    assert tab_at(854.0, (300.0, 10.0)) == 0
    assert tab_at(854.0, (500.0, 10.0)) == 2
    # Ниже бара — не вкладка.
    assert tab_at(854.0, (300.0, 30.0)) is None
    # Левее первой вкладки — не вкладка.
    assert tab_at(854.0, (100.0, 10.0)) is None
    assert tab_count() == 3


def test_numeric_key_and_next_tab() -> None:
    assert numeric_key("3") == 3
    assert numeric_key("0") == 0
    assert numeric_key("numpad7") == 7
    assert numeric_key("a") is None

    assert next_tab_index(0, "1", False) == 0
    assert next_tab_index(0, "0", False) == 9
    assert next_tab_index(2, "Tab", False) == 0
    assert next_tab_index(0, "Tab", True) == 2
    assert next_tab_index(0, "x", False) is None


def test_grid_and_fields() -> None:
    assert grid(854.0, 480.0, 0) == (322.0, 75.0)
    assert field_rect(854.0, 480.0, 0) == (0, [323.0, 88.0, 208.0, 20.0])
    assert field_rect(854.0, 480.0, 1) == (1, [272.0, 116.0, 308.0, 20.0])
    assert field_rect(854.0, 480.0, 2) is None
    assert field_at(854.0, 480.0, 0, (323.0, 88.0)) == 0
    assert field_at(854.0, 480.0, 0, (10.0, 10.0)) is None


def test_labels_use_real_language() -> None:
    assert tr("gui.cancel") == "Cancel"
    assert on_off(True) == "ON"
    assert on_off(False) == "OFF"
    assert labelled("options.difficulty", "Normal") == "Difficulty: Normal"
    assert game_mode(False, False) == "selectWorld.gameMode.survival"
    assert game_mode(False, True) == "selectWorld.gameMode.hardcore"
    assert game_mode(True, True) == "selectWorld.gameMode.creative"


def test_world_options_defaults() -> None:
    o = WorldOptions()
    assert o.tab == 0
    assert o.world_type is WorldPreset.NORMAL
    assert o.single_biome == "minecraft:plains"
    assert o.structures is True
    assert o.data_packs == ["vanilla"]
    assert o.difficulty() == 2
    assert o.allow_commands(False) is False
    assert o.allow_commands(True) is True
    assert o.bonus_chest_enabled() is False
    assert o.single_biome_of() is None


def test_hardcore_locks_difficulty_and_commands() -> None:
    o = WorldOptions(hardcore=True, bonus_chest=True)
    assert o.difficulty() == 3
    assert o.allow_commands(True) is False
    assert o.bonus_chest_enabled() is False


def test_cycle_game_mode() -> None:
    o = WorldOptions()
    creative = o.cycle(20, False, 1)
    assert (creative, o.hardcore) == (False, True)
    creative = o.cycle(20, creative, 1)
    assert (creative, o.hardcore) == (True, False)
    creative = o.cycle(20, creative, 1)
    assert (creative, o.hardcore) == (False, False)


def test_cycle_difficulty_and_commands() -> None:
    o = WorldOptions()
    o.cycle(23, False, 1)
    assert o.difficulty() == 3
    o.cycle(23, False, 1)
    assert o.difficulty() == 0
    o.cycle(23, False, -1)
    assert o.difficulty() == 3

    o2 = WorldOptions()
    assert o2.commands is None
    o2.cycle(24, False, 1)
    assert o2.commands is True
    o2.cycle(24, False, 1)
    assert o2.commands is False


def test_cycle_world_type_resets_single_biome() -> None:
    o = WorldOptions(single_biome="minecraft:desert")
    o.cycle(25, False, 1)
    assert o.world_type is WorldPreset.FLAT
    assert o.single_biome == "minecraft:plains"
    assert o.single_biome_of() is None  # flat — не single-biome
    o.world_type = WorldPreset.SINGLE_BIOME_SURFACE
    assert o.single_biome_of() == "minecraft:plains"


def test_cycle_switches() -> None:
    o = WorldOptions()
    o.cycle(27, False, 1)
    assert o.structures is False
    o.cycle(28, False, 1)
    assert o.bonus_chest is True


def test_buttons_game_tab() -> None:
    o = WorldOptions()
    bs = buttons(854.0, 480.0, False, o)
    assert [b.id for b in bs] == [20, 23, 24, 21, 22]
    assert bs[0].label == "Game Mode: Survival"
    assert bs[1].label == "Difficulty: Normal"
    # vanilla 26.3: deprecated.json переназначает key.new на key → "Allow Commands".
    assert bs[2].label == "Allow Commands: OFF"
    footer = bs[3]
    assert footer.x == 273.0 and footer.y == 453.0 and footer.label == "Create New World"
    assert bs[4].label == "Cancel" and bs[4].action == "Cancel"


def test_buttons_disable_difficulty_in_hardcore() -> None:
    o = WorldOptions(hardcore=True)
    bs = buttons(854.0, 480.0, False, o)
    assert bs[0].label == "Game Mode: Hardcore"
    assert bs[1].enabled is False  # сложность
    assert bs[2].enabled is False  # читы
    assert bs[1].label == "Difficulty: Hard"


def test_buttons_world_tab() -> None:
    o = WorldOptions(tab=1)
    bs = buttons(854.0, 480.0, False, o)
    assert [b.id for b in bs] == [25, 26, 27, 28, 21, 22]
    assert bs[1].enabled is False  # NORMAL без редактора
    o.world_type = WorldPreset.FLAT
    bs = buttons(854.0, 480.0, False, o)
    assert bs[1].enabled is True
    assert bs[2].label == "ON"  # structures
    assert bs[3].label == "OFF"  # bonus chest


def test_buttons_more_tab() -> None:
    o = WorldOptions(tab=2)
    bs = buttons(854.0, 480.0, False, o)
    assert [b.id for b in bs] == [29, 30, 31, 21, 22]
    assert bs[0].label == "Game Rules"
