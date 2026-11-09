#!/usr/bin/env python3
"""[QuadRix] Тесты порта items.rs — реестр предметов и стеки.

Данные берутся из реального ``.local/horizon-client/26.3/items.json``
(подготовленные ресурсы), поэтому здесь же проверяется и загрузчик.
"""

from pathlib import Path

from quadrix.items.items import (
    ITEM_REGISTRY,
    ItemComponentMap,
    ItemStack,
    Items,
    MAX_STACK_SIZE,
    STACK_SIZE,
    VANILLA_MAX_STACK_SIZE,
    fire_starter_sound,
    load_items,
)

LOCAL_ROOT = Path("H:/Test/QuadRix/.local/horizon-client/26.3")


# ---------------------------------------------------------------------------
# Загрузка реестра из .local
# ---------------------------------------------------------------------------

def test_registry_loads_from_local():
    """Реестр читается из настоящего items.json, предметов > 1000."""
    assert LOCAL_ROOT.joinpath("items.json").exists(), "нужен .local items.json"
    registry = load_items(LOCAL_ROOT)
    assert len(registry) > 1000
    # items.json экспортирует 1658 предметов на 26.3.
    assert len(registry.items) == len(registry.order)


def test_module_registry_is_loaded():
    """Модульный ITEM_REGISTRY загружен из .local по умолчанию."""
    assert isinstance(ITEM_REGISTRY, Items)
    assert len(ITEM_REGISTRY) > 1000


def test_registry_order_only_known_items():
    """registry_order не пуст и все его id есть в реестре."""
    registry = load_items(LOCAL_ROOT)
    assert len(registry.registry_order) > 1000
    assert all(item_id in registry for item_id in registry.registry_order)
    # Сетевой порядок начинается с воздуха, как в command-registries.json.
    assert registry.registry_order[0] == "minecraft:air"


# ---------------------------------------------------------------------------
# Известные предметы
# ---------------------------------------------------------------------------

def test_stone_stack_size():
    """minecraft:stone кладётся по 64."""
    stone = ITEM_REGISTRY.get("minecraft:stone")
    assert stone is not None
    assert stone.max_stack == 64
    assert stone.max_damage == 0


def test_diamond_sword_stack_size_and_damage():
    """minecraft:diamond_sword — по одному и с прочностью."""
    sword = ITEM_REGISTRY.get("minecraft:diamond_sword")
    assert sword is not None
    assert sword.max_stack == 1
    assert sword.max_damage > 0
    # Ваниль 26.3: прочность алмазного меча.
    assert sword.max_damage == 1561


def test_apple_is_food():
    """minecraft:apple — еда (nutrition 4, saturation 2.4)."""
    apple = ITEM_REGISTRY.get("minecraft:apple")
    assert apple is not None
    assert apple.food == (4, 2.4)


def test_every_item_has_id_and_model():
    """У каждого предмета id равен ключу, а модель по умолчанию — сам id."""
    for item_id, info in ITEM_REGISTRY.items.items():
        assert info.id == item_id
        assert info.model


# ---------------------------------------------------------------------------
# ItemStack
# ---------------------------------------------------------------------------

def test_empty_stack_is_empty():
    """ItemStack.empty() пуст."""
    stack = ItemStack.empty()
    assert stack.is_empty() is True
    assert stack.count == 0
    assert stack.item_id() == "minecraft:air"


def test_new_stack_is_not_empty():
    """Стек из 32 камней не пуст и помнит количество."""
    stack = ItemStack("minecraft:stone", 32)
    assert stack.is_empty() is False
    assert stack.count == 32
    assert stack.item_id() == "minecraft:stone"
    assert len(stack) == 32


def test_same_item_ignores_count():
    """Одинаковые предметы сравниваются независимо от количества."""
    a = ItemStack("minecraft:stone", 32)
    b = ItemStack("minecraft:stone", 32)
    c = ItemStack("minecraft:dirt", 32)
    assert a.same_item(b) is True
    assert a.same_item(c) is False


def test_same_item_same_components_tracks_extra():
    """same_item_same_components учитывает component map."""
    a = ItemStack("minecraft:stone", 1)
    b = ItemStack("minecraft:stone", 1)
    assert a.same_item_same_components(b) is True
    b.extra = ItemComponentMap(components={"minecraft:custom_data": {"x": 1}})
    assert a.same_item_same_components(b) is False


def test_component_map_is_empty_and_tidy():
    """Пустая коробка компонентов выбрасывается tidy()."""
    data = ItemComponentMap()
    assert data.is_empty() is True
    data.set("minecraft:enchantments", {"minecraft:sharpness": 5})
    assert data.is_empty() is False
    assert data.get("minecraft:enchantments") == {"minecraft:sharpness": 5}
    stack = ItemStack("minecraft:stone", 1, extra=data)
    stack.tidy()
    assert stack.extra is data
    data.remove("minecraft:enchantments")
    stack.tidy()
    assert stack.extra is None


def test_transmute_keeps_components():
    """transmuteCopy меняет предмет, сохраняя компоненты."""
    stack = ItemStack("minecraft:stone", 5, damage=3)
    stack.extra = ItemComponentMap(components={"minecraft:custom_data": {"k": "v"}})
    out = stack.transmute("minecraft:dirt", 1)
    assert out.item == "minecraft:dirt"
    assert out.count == 1
    assert out.damage == 3
    assert out.extra is stack.extra


# ---------------------------------------------------------------------------
# Константы и звук
# ---------------------------------------------------------------------------

def test_stack_size_constants():
    """Константы размера стека из item_defaults.rs."""
    assert STACK_SIZE == "minecraft:max_stack_size"
    assert VANILLA_MAX_STACK_SIZE == 99
    assert MAX_STACK_SIZE == 2**31 - 1


def test_fire_starter_sound():
    """Звук огненного заряда и огнива."""
    assert fire_starter_sound(True) == "minecraft:item.firecharge.use"
    assert fire_starter_sound(False) == "minecraft:item.flintandsteel.use"
