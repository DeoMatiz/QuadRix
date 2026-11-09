#!/usr/bin/env python3
"""[QuadRix] Тесты порта item_data.rs и проводной половины item.rs.

Проверяются:
  * реестр компонент из ``.local/horizon-client/26.3/registries.json``;
  * NBT-модель компонент (``decode_components``/``encode_components``);
  * провод (``Slot``/``DelimitedSlot``/``ComponentMap``/``ComponentPatch``);
  * helpers прочности и стекаемости в ``quadrix.items.items``.
"""

from pathlib import Path

from quadrix.items.item_data import (
    COMPONENT_IDS,
    ComponentInt,
    ComponentMap,
    ComponentNbt,
    ComponentPatch,
    ComponentText,
    DelimitedSlot,
    ItemComponent,
    Slot,
    Stack,
    component_id,
    load_component_registry,
    decode_components,
    encode_components,
)
from quadrix.items.items import ItemStack
from quadrix.protocol.buf import Reader, Writer
from quadrix.world.nbt import Tag, TagType

LOCAL_ROOT = Path("H:/Test/QuadRix/.local/horizon-client/26.3")

DAMAGE = component_id("minecraft:damage")


def _tag_string(value: str) -> Tag:
    return Tag(TagType.String, str_val=value)


def _tag_int(value: int) -> Tag:
    return Tag(TagType.Int, int_val=value)


def _tag_compound(mapping: dict) -> Tag:
    return Tag(TagType.Compound, compound_val=dict(mapping))


# ---------------------------------------------------------------------------
# Реестр компонент из .local
# ---------------------------------------------------------------------------

def test_component_registry_loads_from_local():
    """protocol_id компонент читаются из registries.json, а не хардкодятся."""
    assert LOCAL_ROOT.joinpath("registries.json").exists()
    registry = load_component_registry(LOCAL_ROOT)
    assert len(registry) > 100
    # Значения pinned-версии 26.3 (data_component_type).
    assert registry["minecraft:damage"] == 3
    assert registry["minecraft:max_stack_size"] == 1
    assert registry["minecraft:custom_name"] == 6
    assert registry["minecraft:custom_data"] == 0
    assert registry["minecraft:bundle_contents"] == 52


def test_item_component_enum_covers_every_registry_entry():
    """У каждой компоненты реестра есть элемент enum."""
    members = {m.value for m in ItemComponent}
    assert members == set(COMPONENT_IDS)
    assert ItemComponent.DAMAGE.value == "minecraft:damage"
    assert ItemComponent.MAX_STACK_SIZE.value == "minecraft:max_stack_size"
    assert ItemComponent.CUSTOM_DATA.value == "minecraft:custom_data"
    assert ItemComponent.LORE.value == "minecraft:lore"
    assert ItemComponent.FOOD.value == "minecraft:food"


# ---------------------------------------------------------------------------
# Компоненты и стеки
# ---------------------------------------------------------------------------

def test_component_map_empty_round_trip():
    """Пустой патч (нет added, нет removed) кодируется и читается обратно."""
    empty = ComponentMap()
    assert empty.is_empty() is True
    encoded = empty.encode()
    assert encoded == b"\x00\x00"
    back = ComponentMap.decode(encoded)
    assert back.is_empty() is True
    assert back.added == []
    assert back.removed == []


def test_same_item_ignores_count_but_tracks_components():
    """same_item сравнивает компоненты, но не количество."""
    a = ItemStack("minecraft:stone", 32)
    b = ItemStack("minecraft:stone", 32)
    c = ItemStack("minecraft:dirt", 32)
    assert a.same_item(b) is True
    assert a.same_item(c) is False
    damaged = ItemStack("minecraft:stone", 32, damage=5)
    assert a.same_item(damaged) is False


def test_diamond_sword_next_damage_and_damage_per_hit():
    """Алмазный меч: прочность за удар и следующее повреждение."""
    sword = ItemStack("minecraft:diamond_sword", 1, damage=50)
    assert sword.max_damage() == 1561
    # weapon.item_damage_per_attack отсутствует -> 1.
    assert sword.damage_per_hit() == 1
    assert sword.next_damage() == 51
    assert sword.next_damage_will_break() is False
    # У кирки weapon.item_damage_per_attack = 2.
    pickaxe = ItemStack("minecraft:diamond_pickaxe", 1)
    assert pickaxe.damage_per_hit() == 2
    broken = ItemStack("minecraft:diamond_sword", 1, damage=1560)
    assert broken.next_damage_will_break() is True


def test_is_damageable():
    """damageable — есть max_damage и нет unbreakable."""
    assert ItemStack("minecraft:diamond_sword", 1).is_damageable() is True
    assert ItemStack("minecraft:stone", 1).is_damageable() is False
    unbreakable = ItemStack("minecraft:diamond_sword", 1, damage=3)
    # unbreakable через реальный компонент.
    from quadrix.items.items import ItemComponentMap

    unbreakable.extra = ItemComponentMap(components={"minecraft:unbreakable": {}})
    assert unbreakable.is_damageable() is False


def test_is_stackable():
    """Стекается то, что кладётся по >1 и не повреждено/непрочно."""
    assert ItemStack("minecraft:stone", 1).is_stackable() is True
    assert ItemStack("minecraft:diamond_sword", 1).is_stackable() is False
    damaged_tool = ItemStack("minecraft:diamond_pickaxe", 1, damage=1)
    assert damaged_tool.is_stackable() is False
    # Пластилина: стекаемый предмет, но повреждённый уже не стекается.
    damaged_stack = ItemStack("minecraft:stone", 1, damage=1)
    assert damaged_stack.is_stackable() is True


# ---------------------------------------------------------------------------
# ComponentPatch::apply
# ---------------------------------------------------------------------------

def test_component_patch_apply_empty_changes_nothing():
    """Пустой патч не меняет стек."""
    stack = ItemStack("minecraft:stone", 4)
    before = (stack.item, stack.count, stack.damage, stack.extra)
    out = ComponentPatch().apply(stack)
    assert out is stack
    assert (stack.item, stack.count, stack.damage, stack.extra) == before


def test_component_patch_apply_sets_damage_and_extra():
    """added применяются к damage/extra, removed убирают компоненты."""
    stack = ItemStack("minecraft:diamond_sword", 1)
    patch = ComponentPatch(
        added=[
            (DAMAGE, ComponentInt(7)),
            (component_id("minecraft:custom_data"), ComponentNbt(
                _tag_compound({"keep": _tag_int(1)})
            )),
        ],
    )
    patch.apply(stack)
    assert stack.damage == 7
    assert stack.extra is not None
    assert "minecraft:custom_data" in stack.extra
    # removed: damage обнуляется, компонент удаляется.
    removal = ComponentPatch(removed=[DAMAGE, component_id("minecraft:custom_data")])
    removal.apply(stack)
    assert stack.damage == 0
    assert stack.extra is None


# ---------------------------------------------------------------------------
# Провод компонент
# ---------------------------------------------------------------------------

def test_damage_component_wire_round_trip():
    """damage=50 переживает Slot и DelimitedSlot."""
    sword = Stack(
        item=900,
        count=1,
        added=[(DAMAGE, ComponentInt(50))],
    )
    for codec in (Slot, DelimitedSlot):
        writer = Writer()
        codec.write(sword, writer)
        back = codec.read(Reader(bytes(writer.data)))
        assert back is not None
        assert back.item == 900
        assert back.count == 1
        assert back.added == [(DAMAGE, ComponentInt(50))]
        assert back.damage() == 50
        assert back.removed == []


def test_custom_name_nbt_component_wire_round_trip():
    """custom_name — NBT-компонента; tag переживает провод."""
    name = _tag_compound({"text": _tag_string("Excalibur")})
    stack = Stack(
        item=901,
        count=1,
        added=[(component_id("minecraft:custom_name"), ComponentText(name))],
    )
    writer = Writer()
    Slot.write(stack, writer)
    back = Slot.read(Reader(bytes(writer.data)))
    assert back is not None
    assert back.added == [(component_id("minecraft:custom_name"), ComponentText(name))]


def test_removed_components_wire_round_trip():
    """Удалённые компоненты идут varint-id и читаются обратно."""
    stack = Stack(item=902, count=1, removed=[DAMAGE, component_id("minecraft:repair_cost")])
    writer = Writer()
    Slot.write(stack, writer)
    back = Slot.read(Reader(bytes(writer.data)))
    assert back is not None
    assert back.added == []
    assert back.removed == [DAMAGE, component_id("minecraft:repair_cost")]


# ---------------------------------------------------------------------------
# NBT-модель (item_data.rs)
# ---------------------------------------------------------------------------

def test_nbt_components_round_trip():
    """decode_components/encode_components сохраняют damage, чары и имя."""
    components = _tag_compound({
        "minecraft:damage": _tag_int(12),
        "minecraft:enchantments": _tag_compound({
            "knockback": _tag_int(2),
            "minecraft:sharpness": _tag_int(1),
        }),
        "minecraft:repair_cost": _tag_int(3),
        "minecraft:custom_name": _tag_compound({"text": _tag_string("Blade")}),
        "minecraft:custom_data": _tag_compound({"keep": _tag_int(7)}),
    })
    damage, data = decode_components(components)
    assert damage == 12
    assert data is not None
    assert data.repair_cost == 3
    assert data.custom_name_plain() == "Blade"
    assert ("minecraft:sharpness", 1) in data.enchantments
    assert ("minecraft:knockback", 2) in data.enchantments
    # custom_data не смоделирован -> остаётся в other.
    assert data.get_other("minecraft:custom_data") is not None

    stack = ItemStack("minecraft:diamond_sword", 1, damage=damage, extra=data)
    encoded = encode_components(stack)
    assert encoded is not None
    damage2, data2 = decode_components(encoded)
    assert damage2 == 12
    assert data2 is not None
    assert data2.custom_name_plain() == "Blade"
    assert data2.enchantments == data.enchantments
    assert data2.repair_cost == 3
