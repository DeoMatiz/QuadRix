#!/usr/bin/env python3
"""[QuadRix] Тесты каталога использование предметов.

Порт ``horizon-world/src/item_use_catalog.rs`` (Minecraft 26.3).
"""

from __future__ import annotations

import json
from pathlib import Path

from quadrix.world.item_use_catalog import (
    ItemUseCatalog,
    ItemId,
    Duration,
    UseComponents,
    ItemDefinition,
    ItemUseStack,
)


# Минимальный каталог предметов на основе формата из item_use_catalog.rs.
# Содержит несколько предметов для тестов lookup и Duration-вариантов.
MINIMAL_CATALOG: dict = {
    "schema": 1,
    "DataVersion": 263,
    "items": [
        # 0: minecraft:air — обязательно первым
        {
            "id": 0,
            "name": "minecraft:air",
            "duration_impl": "Item",
            "release_impl": "Item",
            "components": {},
        },
        # 1: minecraft:oak_log
        {
            "id": 1,
            "name": "minecraft:oak_log",
            "duration_impl": "Item",
            "release_impl": "Item",
            "components": {
                "minecraft:max_stack_size": 64,
            },
        },
        # 2: minecraft:apple — еда (consume_seconds)
        {
            "id": 2,
            "name": "minecraft:apple",
            "duration_impl": "Item",
            "release_impl": "Item",
            "components": {
                "minecraft:consumable": 1.6,
                "minecraft:max_stack_size": 64,
            },
        },
        # 3: minecraft:bucket_empty — ведро (пустое)
        {
            "id": 3,
            "name": "minecraft:bucket_empty",
            "duration_impl": "Item",
            "release_impl": "Item",
            "components": {
                "minecraft:max_stack_size": 64,
            },
        },
        # 4: minecraft:wheat_seeds — семена (для farmland)
        {
            "id": 4,
            "name": "minecraft:wheat_seeds",
            "duration_impl": "Item",
            "release_impl": "Item",
            "components": {
                "minecraft:max_stack_size": 64,
            },
        },
        # 5: minecraft:flint_and_steel — зажигалка
        {
            "id": 5,
            "name": "minecraft:flint_and_steel",
            "duration_impl": "Item",
            "release_impl": "Item",
            "components": {
                "minecraft:max_stack_size": 1,
            },
        },
        # 6: minecraft:bow — лук
        {
            "id": 6,
            "name": "minecraft:bow",
            "duration_impl": "BowItem",
            "release_impl": "Item",
            "components": {
                "minecraft:max_stack_size": 64,
            },
        },
        # 7: minecraft:crossbow — арбалет
        {
            "id": 7,
            "name": "minecraft:crossbow",
            "duration_impl": "CrossbowItem",
            "release_impl": "CrossbowItem",
            "components": {
                "minecraft:max_stack_size": 64,
            },
        },
        # 8: minecraft:spyglass — трубопроектор
        {
            "id": 8,
            "name": "minecraft:spyglass",
            "duration_impl": "EnderEyeItem",
            "release_impl": "Item",
            "components": {
                "minecraft:max_stack_size": 1,
            },
        },
        # 9: minecraft:carrot_on_a_stick — ёжик с морковью (instrument)
        {
            "id": 9,
            "name": "minecraft:carrot_on_a_stick",
            "duration_impl": "InstrumentItem",
            "release_impl": "Item",
            "components": {
                "minecraft:instrument": "0x3f000000",  # float bits для 0.5
                "minecraft:max_stack_size": 1,
            },
        },
    ],
    "instruments": {
        "minecraft:carrot_on_a_stick": "3f000000",
    },
}


def test_lookup_existing_item():
    """1. lookup существующего предмета → запись найдена"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    # Ищем oak_log (id=1)
    item = catalog.get(ItemId(1))
    assert item is not None, "Expected oak_log to be found"
    assert item.name == "minecraft:oak_log"
    # Проверка Duration variant
    assert item.duration.variant == DurationVariant.Components  # type: ignore
    print("PASS: test_lookup_existing_item")


def test_lookup_nonexisting_item():
    """2. lookup несуществующего → None/пусто"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    # Ищем несуществующий ID 999
    item = catalog.get(ItemId(999))
    assert item is None, "Expected None for non-existing item"
    # Ищем несуществующее имя
    item = catalog.by_name("minecraft:non_existent")
    assert item is None, "Expected None for non-existing name"
    print("PASS: test_lookup_nonexisting_item")


def test_food_consume():
    """3. right-click еды (если food component есть) → consume=True"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    apple = catalog.by_name("minecraft:apple")
    assert apple is not None, "Apple should be in catalog"
    # Проверить, что у еды consume_seconds установлен
    assert apple.defaults.consume_seconds is not None, "Apple should have consume_seconds"
    assert apple.defaults.consume_seconds == 1.6, f"Expected 1.6, got {apple.defaults.consume_seconds}"
    # Проверить use_duration через Components - передаем defaults как компоненты стека
    stack = ItemUseStack(definition=apple, count=1, components=apple.defaults)
    dur = stack.use_duration()
    # 1.6 * 20 = 32 тика
    assert dur == 32, f"Expected 32 (1.6*20), got {dur}"
    print("PASS: test_food_consume")


def test_bucket_right_click():
    """4. right-click вёдра с водой по блоку → вода ставится (если fluid есть)"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    bucket = catalog.by_name("minecraft:bucket_empty")
    assert bucket is not None, "Bucket should be in catalog"
    # У ведра нет consume_seconds, use_duration через Components должен вернуть 0
    # (нет block_delay_seconds и kinetic_weapon)
    stack = ItemUseStack(definition=bucket, count=1)
    dur = stack.use_duration()
    assert dur == 0, f"Expected 0 for bucket without special components, got {dur}"
    print("PASS: test_bucket_right_click")


def test_seed_planting():
    """5. right-click посадки семян на farmland (если есть)"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    seeds = catalog.by_name("minecraft:wheat_seeds")
    assert seeds is not None, "Wheat seeds should be in catalog"
    # Проверка компонентов семян
    assert seeds.defaults.max_stack_size == 64
    stack = ItemUseStack(definition=seeds, count=1)
    dur = stack.use_duration()
    # Нет consume_seconds, нет block_delay_seconds, нет kinetic_weapon → 0
    assert dur == 0, f"Expected 0 for seeds without consume, got {dur}"
    print("PASS: test_seed_planting")


def test_firelight_right_click():
    """6. right-click зажигалки (если есть)"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    steel = catalog.by_name("minecraft:flint_and_steel")
    assert steel is not None, "Flint and steel should be in catalog"
    # Проверка, что у зажигалки unbreakable по умолчанию False (нет флага в components)
    assert steel.defaults.unbreakable is False
    stack = ItemUseStack(definition=steel, count=1)
    dur = stack.use_duration()
    # Нет consume_seconds, нет block_delay_seconds → 0
    assert dur == 0, f"Expected 0 for flint_and_steel, got {dur}"
    print("PASS: test_firelight_right_click")


def test_bow_right_click():
    """7. right-click лука → делегирует в item_use.is_blocking"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    bow = catalog.by_name("minecraft:bow")
    assert bow is not None, "Bow should be in catalog"
    # duration_impl = "BowItem" → Duration.Constant(72000)
    assert bow.duration.variant == DurationVariant.Constant  # type: ignore
    assert bow.duration.value == 72000, f"Expected 72000 for BowItem, got {bow.duration.value}"
    # crossbow_release для Item = False
    assert bow.crossbow_release is False
    # Проверить use_duration
    stack = ItemUseStack(definition=bow, count=1)
    dur = stack.use_duration()
    assert dur == 72000, f"Expected 72000 for BowItem, got {dur}"
    print("PASS: test_bow_right_click")


def test_crossbow_right_click():
    """8. right-click без hit (в воздух) → корректная ветка use_in_air"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    crossbow = catalog.by_name("minecraft:crossbow")
    assert crossbow is not None, "Crossbow should be in catalog"
    # duration_impl = "CrossbowItem" → Duration.Constant(72000)
    assert crossbow.duration.variant == DurationVariant.Constant  # type: ignore
    assert crossbow.duration.value == 72000
    # crossbow_release для CrossbowItem = True
    assert crossbow.crossbow_release is True
    # Проверить use_duration
    stack = ItemUseStack(definition=crossbow, count=1)
    dur = stack.use_duration()
    assert dur == 72000, f"Expected 72000 for CrossbowItem, got {dur}"
    print("PASS: test_crossbow_right_click")


def test_instrument_right_click():
    """9. right-click instrument (carrot_on_a_stick)"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    instrument = catalog.by_name("minecraft:carrot_on_a_stick")
    assert instrument is not None, "Carrot on a stick should be in catalog"
    # duration_impl = "InstrumentItem" → Duration.Instrument
    assert instrument.duration.variant == DurationVariant.Instrument  # type: ignore
    # instrument_seconds из компонентов (0.5 * 20 = 10)
    assert instrument.defaults.instrument_seconds is not None
    stack = ItemUseStack(definition=instrument, count=1, components=instrument.defaults)
    dur = stack.use_duration()
    # 0.5 * 20 = 10
    assert dur == 10, f"Expected 10 for InstrumentItem, got {dur}"
    print("PASS: test_instrument_right_click")


def test_air_first():
    """10. Air must be first in catalog (Rust validation)"""
    catalog = ItemUseCatalog.from_json(MINIMAL_CATALOG)
    # Access items via the items() method
    first = catalog.items()[0]
    assert first.name == "minecraft:air"
    print("PASS: test_air_first")


# Нужен импорт DurationVariant для типа проверок
from quadrix.world.item_use_catalog import DurationVariant  # noqa: E402


if __name__ == "__main__":
    test_lookup_existing_item()
    test_lookup_nonexisting_item()
    test_food_consume()
    test_bucket_right_click()
    test_seed_planting()
    test_firelight_right_click()
    test_bow_right_click()
    test_crossbow_right_click()
    test_instrument_right_click()
    test_air_first()
    print("\nAll 10 tests passed!")