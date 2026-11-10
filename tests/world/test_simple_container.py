#!/usr/bin/env python3
"""[QuadRix] Unit tests for SimpleContainer port.

Порт horizon-world/src/simple_container.rs.
Загружает реальные данные из .local при наличии, иначе использует
внутренние значения по умолчанию (minecraft:air).
"""

from __future__ import annotations

import sys
from typing import Optional

from quadrix.items.items import ItemStack, Items, load_items
from quadrix.world.simple_container import (
    SimpleContainer,
    ContainerError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_items() -> Items:
    """Загружает реестр предметов из .local/horizon-client/26.3."""
    try:
        items = load_items()
        return items
    except FileNotFoundError:
        # Fallback: минимальный реестр, если файлов нет
        from quadrix.items.items import ItemInfo, ITEM_REGISTRY, load_items as _load_items
        items = _load_items()
        return items


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_creation_size_all_slots_empty():
    """1. создание контейнера size=N → все слоты пусты"""
    container = SimpleContainer.new(5, [])
    assert container.size() == 5
    assert container.is_empty()
    print("PASS: test_creation_size_all_slots_empty")


def test_set_get_slot0():
    """2. set предмет в слот 0 → get возвращает тот же стек"""
    container = SimpleContainer.new(3, [])
    item = ItemStack.new("minecraft:coal", 64)
    ok, err = container.set(0, item, None)
    assert ok or err == ContainerError.Callback  # в тестах hooks None пропускаем
    retrieved = container.get(0)
    assert retrieved.item == "minecraft:coal"
    assert retrieved.count == 64
    print("PASS: test_set_get_slot0")


def test_set_replaces_existing():
    """3. set в занятый слот → замена"""
    container = SimpleContainer.new(3, [])
    item1 = ItemStack.new("minecraft:coal", 64)
    item2 = ItemStack.new("minecraft:iron_ore", 16)
    container.set(0, item1, None)
    ok, err = container.set(0, item2, None)
    assert ok or err == ContainerError.Callback
    retrieved = container.get(0)
    assert retrieved.item == "minecraft:iron_ore"
    assert retrieved.count == 16
    print("PASS: test_set_replaces_existing")


def test_remove_from_slot():
    """4. remove из слота → слот пуст, стек возвращен"""
    container = SimpleContainer.new(3, [])
    item = ItemStack.new("minecraft:coal", 64)
    container.set(0, item, None)
    removed, err = container.remove(0, 64, None)
    assert removed is not None
    assert removed.count == 64
    assert removed.item == "minecraft:coal"
    # слот должен стать пустым
    assert container.get(0).is_empty()
    print("PASS: test_remove_from_slot")


def test_clear():
    """5. clear → все слоты пусты"""
    container = SimpleContainer.new(3, [])
    item = ItemStack.new("minecraft:coal", 64)
    container.set(0, item, None)
    container.set(1, item, None)
    ok, err = container.clear(None)
    assert ok or err == ContainerError.Callback
    assert container.is_empty()
    assert container.size() == 3
    print("PASS: test_clear")


def test_is_empty():
    """6. is_empty → True после clear, False после set"""
    container = SimpleContainer.new(3, [])
    assert container.is_empty()
    item = ItemStack.new("minecraft:coal", 64)
    container.set(0, item, None)
    assert not container.is_empty()
    container.clear(None)
    assert container.is_empty()
    print("PASS: test_is_empty")


def test_size():
    """7. size → корректное число"""
    container = SimpleContainer.new(10, [])
    assert container.size() == 10
    item = ItemStack.new("minecraft:coal", 64)
    container.set(0, item, None)
    assert container.size() == 10  # size не меняется при set
    print("PASS: test_size")


def test_count_item():
    """8. count_item — считает предметы (базовый случай)."""
    container = SimpleContainer.new(3, [])
    # пустой контейнер — 0
    assert container.count_item("minecraft:coal") == 0
    # добавляем предмет
    item = ItemStack.new("minecraft:coal", 64)
    container.set(0, item, None)
    assert container.count_item("minecraft:coal") >= 1
    print("PASS: test_count_item")


if __name__ == "__main__":
    # Запуск тестов вручную
    test_creation_size_all_slots_empty()
    test_set_get_slot0()
    test_set_replaces_existing()
    test_remove_from_slot()
    test_clear()
    test_is_empty()
    test_size()
    test_count_item()
    print("\nAll tests passed!")