#!/usr/bin/env python3
"""[QuadRix] Тесты для ``quadrix.world.block_survival``.

Порт ``horizon/crates/horizon-world/src/block_survival.rs`` (``can_survive``)
и клиентский API разрушения блока (харднесс/сопротивление/дроп) по данным
``.local``: ``survival-rules.json``, ``widgets``-факты ``gameplay-facts.json``
и ``loot_table/blocks/*.json``.
"""

from __future__ import annotations

import pytest

from quadrix.items.items import ItemComponentMap, ItemStack
from quadrix.world import block_survival as bs


# ---------------------------------------------------------------------------
# FakeWorld: воздух по умолчанию (как FeatureWorld в тестах placement)
# ---------------------------------------------------------------------------

class FakeWorld:
    """Мир из словаря позиция → состояние; всё остальное — воздух."""

    def __init__(self, air, blocks=None):
        self.air = air
        self.blocks = dict(blocks or {})
        self.writes = []

    def get_block(self, position):
        return self.blocks.get(tuple(position), self.air)

    def set_block(self, position, state, flags=0):
        self.blocks[tuple(position)] = state
        self.writes.append((tuple(position), state, flags))
        return True


@pytest.fixture(scope="module")
def survival() -> bs.BlockSurvivalRegistry:
    return bs.default_survival()


@pytest.fixture(scope="module")
def registry(survival):
    return survival.registry


@pytest.fixture()
def air(registry):
    return registry.default_state("minecraft:air")


def _silk_touch_pickaxe() -> ItemStack:
    """Алмазная кирка с зачарованием ``silk_touch`` (компонент стека)."""
    stack = ItemStack.new("minecraft:diamond_pickaxe", 1)
    stack.extra = ItemComponentMap(
        {"minecraft:enchantments": {"minecraft:silk_touch": 1}}
    )
    return stack


# ---------------------------------------------------------------------------
# Харднесс / сопротивление (реальные данные .local)
# ---------------------------------------------------------------------------

def test_hardness_stone_greater_than_dirt():
    """Камень твёрже земли; сопротивления — как в ваниле (1.5/0.5, 6.0/0.5)."""
    assert bs.block_hardness("minecraft:stone") > bs.block_hardness("minecraft:dirt")
    assert bs.block_hardness("minecraft:stone") == 1.5
    assert bs.block_hardness("minecraft:dirt") == 0.5
    assert bs.block_hardness("minecraft:glass") == 0.3
    assert bs.block_resistance("minecraft:stone") == 6.0
    assert bs.block_resistance("minecraft:dirt") == 0.5


# ---------------------------------------------------------------------------
# Требование инструмента и добыча
# ---------------------------------------------------------------------------

def test_stone_requires_tool_and_cannot_harvest_by_hand():
    """Камень требует кирку: рукой не добыть, мечом тоже."""
    assert bs.requires_tool("minecraft:stone") is True
    assert bs.can_harvest("minecraft:stone", None) is False
    assert bs.can_harvest("minecraft:stone", ItemStack.new("minecraft:wooden_sword", 1)) is False
    assert bs.get_drops("minecraft:stone", None) == []


def test_stone_with_wooden_pickaxe_drops_cobblestone():
    """Деревянная кирка добывает камень → дроп ``cobblestone``."""
    pickaxe = ItemStack.new("minecraft:wooden_pickaxe", 1)

    assert bs.can_harvest("minecraft:stone", pickaxe) is True
    assert bs.is_harvestable("minecraft:stone", pickaxe) is True
    drops = bs.get_drops("minecraft:stone", pickaxe)
    assert [stack.item for stack in drops] == ["minecraft:cobblestone"]
    assert [stack.count for stack in drops] == [1]


def test_dirt_drops_without_tool():
    """Земля не требует инструмента: дропается рукой (1 шт.)."""
    assert bs.requires_tool("minecraft:dirt") is False
    assert bs.can_harvest("minecraft:dirt", None) is True

    drops = bs.get_drops("minecraft:dirt", None)
    assert len(drops) == 1
    assert drops[0].item == "minecraft:dirt"
    assert drops[0].count == 1


def test_glass_empty_without_silk_touch_and_drop_with_it():
    """Стекло: без ``silk_touch`` дропа нет, с ним — само стекло."""
    assert bs.get_drops("minecraft:glass", ItemStack.new("minecraft:diamond_pickaxe", 1)) == []

    drops = bs.get_drops("minecraft:glass", _silk_touch_pickaxe())
    assert [stack.item for stack in drops] == ["minecraft:glass"]


# ---------------------------------------------------------------------------
# can_survive: реальные правила из survival-rules.json
# ---------------------------------------------------------------------------

def test_torch_survives_only_on_solid(registry, air):
    """Факел (правило ``CenterBelow``) в воздухе падает, на камне стоит."""
    torch = registry.default_state("minecraft:torch")
    stone = registry.default_state("minecraft:stone")

    empty = FakeWorld(air)
    assert bs.can_survive(empty, torch, (0, 64, 0)) is False

    supported = FakeWorld(air, {(0, 63, 0): stone})
    assert bs.can_survive(supported, torch, (0, 64, 0)) is True
    # Тот же ответ через реестр (``BlockPlacement.can_survive`` делегирует сюда).
    assert bs.default_survival().can_survive(supported, torch, (0, 64, 0)) is True


def test_cactus_rejects_adjacent_cactus_and_solid(registry, air):
    """Кактус (правило ``Cactus``): соседний кактус/твёрдый блок запрещены."""
    cactus = registry.default_state("minecraft:cactus")
    stone = registry.default_state("minecraft:stone")
    dirt = registry.default_state("minecraft:dirt")

    beside_cactus = FakeWorld(air, {(0, 63, 0): cactus, (1, 64, 0): cactus})
    assert bs.can_survive(beside_cactus, cactus, (0, 64, 0)) is False

    beside_stone = FakeWorld(air, {(0, 63, 0): dirt, (1, 64, 0): stone})
    assert bs.can_survive(beside_stone, cactus, (0, 64, 0)) is False

    on_dirt = FakeWorld(air, {(0, 63, 0): dirt})
    assert bs.can_survive(on_dirt, cactus, (0, 64, 0)) is False

    on_cactus = FakeWorld(air, {(0, 63, 0): cactus})
    assert bs.can_survive(on_cactus, cactus, (0, 64, 0)) is True


# ---------------------------------------------------------------------------
# break_block
# ---------------------------------------------------------------------------

def test_break_block_returns_item_stack_and_clears_block(registry, air):
    """``break_block``: дроп киркой + в мире остаётся воздух (флаги 3)."""
    stone = registry.default_state("minecraft:stone")
    world = FakeWorld(air, {(4, 70, -2): stone})

    drops = bs.break_block(world, (4, 70, -2), ItemStack.new("minecraft:stone_pickaxe", 1))

    assert len(drops) == 1
    assert isinstance(drops[0], ItemStack)
    assert drops[0].item == "minecraft:cobblestone"
    assert world.get_block((4, 70, -2)) == air
    assert world.writes == [((4, 70, -2), air, 3)]


def test_survival_rules_cover_stone_and_torch(registry):
    """Состояния камня/факела разобраны: ``Always`` и ``CenterBelow``."""
    survival = bs.default_survival()
    stone = registry.default_state("minecraft:stone")
    torch = registry.default_state("minecraft:torch")

    assert survival.rules[stone.id].name == "Always"
    assert survival.rules[torch.id].name == "Support"
    assert survival.rules[torch.id].kind is bs.SupportType.CENTER
