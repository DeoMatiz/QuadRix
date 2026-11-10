#!/usr/bin/env python3
"""[QuadRix] Тесты проводной формы ItemStack в play.py (_Slot / _Template).

Источник: horizon-protocol/src/item.rs (Stack, Slot, DelimitedSlot,
Template). После закрытия item_data.rs ``_Slot``/``_Template`` в play.py —
это псевдонимы ``item_data.Slot``/``item_data.Template``, а ``ItemStack`` —
псевдоним ``item_data.Stack``. Непустые патчи компонент читаются и
пишутся реально (``read_component``/``write_component``), а не дают
ProtocolError, как раньше.

Это чистые тесты провода: .local нужен только для реестра компонент
(``component_id``) и сетевого id предмета.
"""

from __future__ import annotations

import pytest

from quadrix.items.item_data import (
    ComponentInt,
    ComponentText,
    DelimitedSlot,
    Slot,
    Stack,
    Template,
    component_id,
)
from quadrix.items.items import ITEM_REGISTRY
from quadrix.protocol.buf import ProtocolError, Reader, Writer
from quadrix.protocol.packets.play import (
    ItemStack,
    _DelimitedSlot,
    _Slot,
    _Template,
)
from quadrix.world.nbt import Tag, TagType

DAMAGE = component_id("minecraft:damage")
CUSTOM_NAME = component_id("minecraft:custom_name")
REPAIR_COST = component_id("minecraft:repair_cost")


def protocol_item(name: str) -> int:
    """Сетевой id предмета = индекс в сетевом порядке реестра."""
    return ITEM_REGISTRY.registry_order.index(name)


def _string(value: str) -> Tag:
    return Tag(TagType.String, str_val=value)


def _round_trip(codec, stack):
    w = Writer()
    codec.write(stack, w)
    return codec.read(Reader(bytes(w.data)))


# ---------------------------------------------------------------------------
# Псевдонимы (обратная совместимость)
# ---------------------------------------------------------------------------

def test_play_slot_and_template_are_item_data_aliases():
    """play._Slot/_Template/ItemStack — те же объекты, что в item_data."""
    assert _Slot is Slot
    assert _Template is Template
    assert _DelimitedSlot is DelimitedSlot
    assert ItemStack is Stack


# ---------------------------------------------------------------------------
# _Slot (ItemStack.OPTIONAL_STREAM_CODEC)
# ---------------------------------------------------------------------------

def test_empty_item_stack_round_trip_is_not_broken():
    """Пустой стек (count=0) — varint 0, обратно None; не сломан."""
    w = Writer()
    _Slot.write(ItemStack(item=protocol_item("minecraft:stone"), count=0), w)
    assert bytes(w.data) == b"\x00"
    assert _Slot.read(Reader(bytes(w.data))) is None
    # None тоже кодируется нулём.
    w2 = Writer()
    _Slot.write(None, w2)
    assert bytes(w2.data) == b"\x00"


def test_stone_count_round_trip_without_components():
    """Обычный стек: count=32, item=stone, без компонент."""
    stone = protocol_item("minecraft:stone")
    stack = ItemStack(item=stone, count=32)
    back = _round_trip(_Slot, stack)

    assert back is not None
    assert back.item == stone
    assert back.count == 32
    assert back.added == []
    assert back.removed == []
    assert back.damage() == 0


def test_damage_component_round_trip():
    """damage=50 переживает _Slot: компонента damage реально на проводе."""
    sword = protocol_item("minecraft:diamond_sword")
    stack = ItemStack(item=sword, count=1, added=[(DAMAGE, ComponentInt(50))])
    back = _round_trip(_Slot, stack)

    assert back is not None
    assert back.item == sword
    assert back.count == 1
    assert back.added == [(DAMAGE, ComponentInt(50))]
    assert back.damage() == 50
    assert back.component(DAMAGE) == ComponentInt(50)
    assert back.removed == []


def test_custom_name_component_round_trip():
    """custom_name — NBT-компонента; tag переживает провод."""
    name = _string("test")
    stack = ItemStack(
        item=protocol_item("minecraft:stone"),
        count=1,
        added=[(CUSTOM_NAME, ComponentText(name))],
    )
    back = _round_trip(_Slot, stack)

    assert back is not None
    assert back.component(CUSTOM_NAME) == ComponentText(name)


def test_removed_components_round_trip():
    """Removed-виды идут varint-id и читаются обратно."""
    stack = ItemStack(
        item=protocol_item("minecraft:stone"),
        count=1,
        removed=[DAMAGE, REPAIR_COST],
    )
    back = _round_trip(_Slot, stack)

    assert back is not None
    assert back.added == []
    assert back.removed == [DAMAGE, REPAIR_COST]


def test_slot_nonempty_encoded_bytes_match_rust_shape():
    """bytes: count, item, positive, negative, kind, value."""
    stack = ItemStack(item=5, count=2, added=[(DAMAGE, ComponentInt(50))])
    w = Writer()
    _Slot.write(stack, w)
    assert bytes(w.data) == bytes([2, 5, 1, 0, DAMAGE, 50])


# ---------------------------------------------------------------------------
# _Template (ItemStackTemplate.STREAM_CODEC): item идёт перед count
# ---------------------------------------------------------------------------

def test_template_item_first_round_trip_with_damage():
    item = protocol_item("minecraft:stone")
    stack = ItemStack(item=item, count=1, added=[(DAMAGE, ComponentInt(50))])
    w = Writer()
    _Template.write(stack, w)
    # item первым: байт 0 — item, байт 1 — count.
    assert bytes(w.data)[:2] == bytes([item, 1])
    back = _Template.read(Reader(bytes(w.data)))
    assert back.item == item
    assert back.count == 1
    assert back.damage() == 50


# ---------------------------------------------------------------------------
# _DelimitedSlot (ItemStack.OPTIONAL_UNTRUSTED_STREAM_CODEC)
# ---------------------------------------------------------------------------

def test_delimited_slot_round_trip_with_components():
    """DelimitedSlot: то же, но значение компоненты за длиной."""
    item = protocol_item("minecraft:diamond_sword")
    stack = ItemStack(item=item, count=1, added=[(DAMAGE, ComponentInt(50))])
    back = _round_trip(_DelimitedSlot, stack)
    assert back is not None
    assert back.damage() == 50

    # Без компонент delimited и обычный Slot побайтово совпадают.
    plain = ItemStack(item=item, count=1)
    dw = Writer()
    _DelimitedSlot.write(plain, dw)
    sw = Writer()
    _Slot.write(plain, sw)
    assert bytes(dw.data) == bytes(sw.data)


def test_delimited_slot_length_prefixed_component_value():
    """В delimited-виде перед значением компоненты стоит varint-длина."""
    stack = ItemStack(item=5, count=1, added=[(DAMAGE, ComponentInt(50))])
    dw = Writer()
    _DelimitedSlot.write(stack, dw)
    sw = Writer()
    _Slot.write(stack, sw)
    # count, item, positive, negative, kind, затем длина значения (1), 50.
    assert bytes(dw.data) == bytes([1, 5, 1, 0, DAMAGE, 1, 50])
    assert bytes(sw.data) == bytes([1, 5, 1, 0, DAMAGE, 50])


# ---------------------------------------------------------------------------
# Усечённый ввод → ProtocolError (тело не дочитано)
# ---------------------------------------------------------------------------

def test_truncated_component_value_raises_protocol_error():
    """Объявлена компонента damage, но значение оборвано."""
    raw = bytes([1, 5, 1, 0, DAMAGE])  # count, item, +1, removed 0, kind
    with pytest.raises(ProtocolError):
        _Slot.read(Reader(raw))
