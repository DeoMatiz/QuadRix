# Тесты порта игровых правил (horizon-client-core/src/gamerules.rs) →
# quadrix/core/gamerules.py.
#
# Сверено с Rust: имена правил в 26.3 — snake_case (`keep_inventory`,
# `advance_time`, `random_tick_speed`), значения в NBT — Byte (0/1) для Bool
# и Int для Int (НЕ строки). Проверяем дефолты, set/set_string с проверкой
# типа и границ, by_name, to_nbt/from_nbt round-trip, feature minecart
# improvements и save/load файла мира.

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from quadrix.core.gamerules import (
    I32_MAX,
    MAX_MINECART_SPEED,
    MINECART_IMPROVEMENTS,
    RULES,
    GameRules,
    Value,
    available_rules,
    rule,
)
from quadrix.world.nbt import Tag, TagType
from quadrix.world.registry import DATA_VERSION


# ── дефолты ──────────────────────────────────────────────────────────────
def test_defaults_are_loaded() -> None:
    rules = GameRules()
    assert rules.bool("advance_time") is True
    assert rules.bool("keep_inventory") is False
    assert rules.get("keep_inventory") == Value.Bool(False)
    assert rules.int("random_tick_speed") == 3
    assert rules.bool("spawn_mobs") is True
    assert rules.bool("tnt_explosion_drop_decay") is False
    # Имена snake_case, camelCase отсутствует.
    assert rules.get("doDaylightCycle") is None
    assert rules.get("keepInventory") is None


def test_set_bool() -> None:
    rules = GameRules()
    assert rules.set("keep_inventory", Value.Bool(True)) is True
    assert rules.bool("keep_inventory") is True
    assert rules.get("keep_inventory") == Value.Bool(True)
    # Возврат к дефолту убирает запись из values.
    assert rules.set("keep_inventory", Value.Bool(False)) is True
    assert rules.values == {}


def test_set_int_bounds() -> None:
    rules = GameRules()
    assert rules.set("random_tick_speed", Value.Int(10)) is True
    assert rules.int("random_tick_speed") == 10
    # Ниже минимума (0) и выше максимума (8) — отказ.
    assert rules.set("random_tick_speed", Value.Int(-1)) is False
    assert rules.set("max_snow_accumulation_height", Value.Int(9)) is False
    assert rules.set("max_snow_accumulation_height", Value.Int(8)) is True


def test_type_mismatch_is_rejected() -> None:
    rules = GameRules()
    assert rules.set("random_tick_speed", Value.Bool(True)) is False
    assert rules.set("keep_inventory", Value.Int(1)) is False


def test_unknown_rule() -> None:
    rules = GameRules()
    assert rules.get("nonexistent") is None
    assert rules.set("nonexistent", Value.Bool(True)) is False
    assert rules.bool("nonexistent") is False
    assert rules.int("nonexistent") == 0
    assert rules.set_string("nonexistent", "true") is False


def test_namespaced_names() -> None:
    rules = GameRules()
    assert rule("minecraft:random_tick_speed").name == "random_tick_speed"
    assert rules.get("minecraft:keep_inventory") == Value.Bool(False)
    assert rules.set("minecraft:random_tick_speed", Value.Int(7)) is True
    assert rules.int("random_tick_speed") == 7
    # Другой namespace не срезается — правило не найдено.
    assert rule("other:keep_inventory") is None
    assert rules.set_string("other:keep_inventory", "false") is False


def test_set_string_validates() -> None:
    rules = GameRules()
    assert rules.set_string("minecraft:keep_inventory", "true") is True
    assert rules.bool("keep_inventory") is True
    assert rules.set_string("minecraft:keep_inventory", "1") is False
    assert rules.bool("keep_inventory") is True
    assert rules.set_string("minecraft:random_tick_speed", "7") is True
    assert rules.int("random_tick_speed") == 7
    assert rules.set_string("minecraft:random_tick_speed", "-1") is False
    assert rules.set_string("minecraft:random_tick_speed", "999999999999") is False
    assert rules.set_string("minecraft:unknown", "true") is False
    assert rules.int("random_tick_speed") == 7


def test_rule_and_available_rules() -> None:
    assert rule("advance_time") is not None
    assert rule("advance_time").category == "updates"
    assert rule("random_tick_speed").default == Value.Int(3)
    assert rule("random_tick_speed").min == 0
    assert rule("random_tick_speed").max == I32_MAX
    assert len(available_rules(False)) == 58
    assert len(available_rules(True)) == 59
    assert len(RULES) == 58


def test_by_name_booleans_as_int() -> None:
    rules = GameRules()
    rules.set("keep_inventory", Value.Bool(True))
    rules.set("random_tick_speed", Value.Int(5))
    named = rules.by_name()
    assert named["keep_inventory"] == 1
    assert named["advance_time"] == 1
    assert named["random_tick_speed"] == 5
    assert named["locator_bar"] == 1
    assert len(named) == 58


# ── NBT round-trip ────────────────────────────────────────────────────────
def test_to_nbt_shape_and_round_trip() -> None:
    rules = GameRules()
    assert rules.set("keep_inventory", Value.Bool(True)) is True
    assert rules.set("random_tick_speed", Value.Int(10)) is True
    root = rules.to_nbt()

    assert root.is_compound
    data = root.compound_val["data"]
    assert data.is_compound
    assert data.compound_val["minecraft:keep_inventory"] == Tag(
        TagType.Byte, byte_val=1
    )
    assert data.compound_val["minecraft:random_tick_speed"] == Tag(
        TagType.Int, int_val=10
    )
    assert root.compound_val["DataVersion"] == Tag(
        TagType.Int, int_val=DATA_VERSION
    )

    back = GameRules.from_nbt(root)
    assert back == rules
    assert back.bool("keep_inventory") is True
    assert back.int("random_tick_speed") == 10


def test_from_nbt_accepts_short_names() -> None:
    root = Tag(
        TagType.Compound,
        compound_val={
            "data": Tag(
                TagType.Compound,
                compound_val={
                    "keep_inventory": Tag(TagType.Byte, byte_val=1),
                    "random_tick_speed": Tag(TagType.Int, int_val=9),
                },
            ),
            "DataVersion": Tag(TagType.Int, int_val=DATA_VERSION),
        },
    )
    rules = GameRules.from_nbt(root)
    assert rules.bool("keep_inventory") is True
    assert rules.int("random_tick_speed") == 9


def test_from_nbt_ignores_wrong_types_and_missing_data() -> None:
    # Нет data — возвращаются дефолты.
    assert GameRules.from_nbt(Tag(TagType.Compound, compound_val={})) == GameRules()
    # keep_inventory как Int не принимается.
    root = Tag(
        TagType.Compound,
        compound_val={
            "data": Tag(
                TagType.Compound,
                compound_val={"minecraft:keep_inventory": Tag(TagType.Int, int_val=1)},
            )
        },
    )
    rules = GameRules.from_nbt(root)
    assert rules.bool("keep_inventory") is False


# ── feature: minecart improvements ───────────────────────────────────────
def test_minecart_improvements_feature() -> None:
    plain = GameRules()
    assert plain.get("max_minecart_speed") is None
    assert plain.set("max_minecart_speed", Value.Int(20)) is False

    improved = GameRules.with_features([MINECART_IMPROVEMENTS])
    assert improved.get("max_minecart_speed") == Value.Int(8)
    assert improved.set("max_minecart_speed", Value.Int(1000)) is True
    assert improved.int("max_minecart_speed") == 1000
    assert improved.set("max_minecart_speed", Value.Int(1001)) is False
    assert MAX_MINECART_SPEED.default == Value.Int(8)


def test_copy_with_features_keeps_values() -> None:
    rules = GameRules()
    rules.set("keep_inventory", Value.Bool(True))
    rules.set("random_tick_speed", Value.Int(4))
    improved = rules.copy_with_features([MINECART_IMPROVEMENTS])
    assert improved.bool("keep_inventory") is True
    assert improved.int("random_tick_speed") == 4
    assert improved.get("max_minecart_speed") == Value.Int(8)
    # Без функции minecart-правило отбрасывается.
    plain = rules.copy_with_features([])
    assert plain.get("max_minecart_speed") is None


# ── файл мира ────────────────────────────────────────────────────────────
def test_save_and_load_round_trip(tmp_path: Path) -> None:
    rules = GameRules()
    rules.set("keep_inventory", Value.Bool(True))
    rules.set("random_tick_speed", Value.Int(12))
    rules.save(tmp_path)

    path = tmp_path / "data" / "minecraft" / "game_rules.dat"
    assert path.is_file()
    # Файл действительно gzip-сжат.
    assert gzip.decompress(path.read_bytes()) != b""

    assert GameRules.load(tmp_path) == rules


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    rules = GameRules.load(tmp_path)
    assert rules == GameRules()
    assert rules.bool("advance_time") is True
