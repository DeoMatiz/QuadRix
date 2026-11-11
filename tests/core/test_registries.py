# Тесты порта реестров (horizon-client-core/src/registries.rs) →
# quadrix/core/registries.py.
#
# ВАЖНО: настоящий `registries.rs` — это структура `Registries` (состояние
# источников команд для валидации/дополнения аргументов), а НЕ generic
# `Registry<T>` id↔name (тот — horizon-world/registry.rs, уже портирован как
# quadrix.world.registry). Здесь проверяем поля, заполнение из экспорта
# vanilla, доступ ids()/tags(), чат-дополнения и реальный
# `.local/command-registries/registries.json`.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quadrix.core.registries import (
    EMPTY,
    RELOADED,
    CustomCompletionAction,
    Registries,
    RegistryIds,
    modify_custom_completions,
)

REPO = Path(__file__).resolve().parents[2]
EXPORT = REPO / ".local" / "command-registries" / "registries.json"


# ── CustomCompletionAction ───────────────────────────────────────────────
def test_custom_completion_action_from_id() -> None:
    assert CustomCompletionAction.from_id(0) is CustomCompletionAction.Add
    assert CustomCompletionAction.from_id(1) is CustomCompletionAction.Remove
    assert CustomCompletionAction.from_id(2) is CustomCompletionAction.Set
    # Неизвестный id — Add (ByIdMap.continuous + OutOfBoundsStrategy.ZERO).
    assert CustomCompletionAction.from_id(7) is CustomCompletionAction.Add
    assert CustomCompletionAction.from_id(-1) is CustomCompletionAction.Add


def test_modify_custom_completions_add_remove_set() -> None:
    s: set = {"a"}
    modify_custom_completions(s, CustomCompletionAction.Add, ["b", "b", "c"])
    assert s == {"a", "b", "c"}
    modify_custom_completions(s, CustomCompletionAction.Remove, ["a", "zzz"])
    assert s == {"b", "c"}
    modify_custom_completions(s, CustomCompletionAction.Set, ["x", "y"])
    assert s == {"x", "y"}


# ── структуры по умолчанию ───────────────────────────────────────────────
def test_registry_ids_default_and_fields() -> None:
    r = RegistryIds()
    assert r.ids == [] and r.tags == []
    r2 = RegistryIds(["minecraft:stone"], ["minecraft:logs"])
    assert r2.ids == ["minecraft:stone"] and r2.tags == ["minecraft:logs"]


def test_registries_default_is_empty() -> None:
    reg = Registries()
    assert reg.permission == 0
    assert reg.items == [] and reg.item_tags == []
    assert reg.blocks == {} and reg.by_registry == {}
    assert reg.custom_completions == set()
    assert reg.block_entities == set()
    assert reg.block_tag_members == {}
    assert reg.clock_time_markers == {}
    assert reg.advancement_criteria == {}
    assert reg.target_block is None and reg.target_point is None


def test_custom_tab_suggestions_dedups() -> None:
    reg = Registries(players=["alice", "bob"])
    reg.custom_completions = {"bob", "carol"}
    assert reg.custom_tab_suggestions() == {"alice", "bob", "carol"}


# ── fill_from_export ─────────────────────────────────────────────────────
def _synthetic_export() -> dict:
    return {
        "effects": ["minecraft:speed", "minecraft:slowness"],
        "enchantments": ["minecraft:sharpness"],
        "attributes": ["minecraft:armor"],
        "damage_types": ["minecraft:arrow"],
        "templates": ["minecraft:foo"],
        "persistent_components": ["minecraft:custom_name"],
        "learnable_recipes": ["minecraft:stick"],
        "summonable": ["minecraft:zombie", "minecraft:zombie", "minecraft:cow"],
        "entity_types": ["minecraft:player", "minecraft:zombie"],
        "by_registry": {
            "minecraft:item": {
                "ids": ["minecraft:stone"],
                "tags": ["minecraft:logs"],
            },
            "minecraft:advancement": {"ids": ["x"], "tags": []},
        },
        "block_entities": ["minecraft:chest"],
        "block_tag_members": {"minecraft:logs": ["minecraft:oak_log"]},
        "clock_time_markers": {"minecraft:overworld": ["minecraft:day"]},
        "advancement_criteria": {"minecraft:story/root": ["has_item"]},
    }


def test_fill_from_export_synthetic() -> None:
    reg = Registries()
    reg.fill_from_export(_synthetic_export())
    assert reg.effects == ["minecraft:speed", "minecraft:slowness"]
    assert reg.enchantments == ["minecraft:sharpness"]
    assert reg.attributes == ["minecraft:armor"]
    assert reg.damage_types == ["minecraft:arrow"]
    assert reg.templates == ["minecraft:foo"]
    assert reg.persistent_components == ["minecraft:custom_name"]
    assert reg.learnable_recipes == ["minecraft:stick"]
    # summonable/entity_types сортируются и дедуплицируются.
    assert reg.summonable == ["minecraft:cow", "minecraft:zombie"]
    assert reg.entity_types == ["minecraft:player", "minecraft:zombie"]
    assert reg.block_entities == {"minecraft:chest"}
    assert reg.block_tag_members["minecraft:logs"] == ["minecraft:oak_log"]
    assert reg.clock_time_markers["minecraft:overworld"] == ["minecraft:day"]
    assert reg.advancement_criteria["minecraft:story/root"] == ["has_item"]
    # items не заполняется экспортом (остаётся пустым).
    assert reg.items == []


def test_fill_from_export_skips_reloaded_and_existing() -> None:
    reg = Registries()
    reg.by_registry["minecraft:block"] = RegistryIds(["minecraft:old"], [])
    reg.fill_from_export(_synthetic_export())
    # RELOADED не берём из экспорта.
    assert "minecraft:advancement" not in reg.by_registry
    assert not any(name in reg.by_registry for name in RELOADED)
    # Уже присутствующий реестр не перезаписывается.
    assert reg.by_registry["minecraft:block"].ids == ["minecraft:old"]
    assert reg.by_registry["minecraft:item"].ids == ["minecraft:stone"]


def test_fill_from_export_does_not_overwrite_non_empty() -> None:
    reg = Registries()
    reg.effects = ["minecraft:custom"]
    reg.summonable = ["minecraft:custom"]
    reg.fill_from_export(_synthetic_export())
    assert reg.effects == ["minecraft:custom"]
    assert reg.summonable == ["minecraft:custom"]
    # А пустые поля всё же заполнены.
    assert reg.enchantments == ["minecraft:sharpness"]


def test_from_export_returns_filled_registries() -> None:
    reg = Registries.from_export(_synthetic_export())
    assert isinstance(reg, Registries)
    assert reg.ids("minecraft:item") == ["minecraft:stone"]
    assert reg.tags("minecraft:item") == ["minecraft:logs"]


# ── fill_from_exported ────────────────────────────────────────────────────
def test_fill_from_exported_fills_only_empty() -> None:
    source = Registries.from_export(_synthetic_export())
    target = Registries(effects=["minecraft:keep"])
    target.fill_from_exported(source)
    assert target.effects == ["minecraft:keep"]  # не перезаписываем
    assert target.enchantments == ["minecraft:sharpness"]
    assert target.summonable == ["minecraft:cow", "minecraft:zombie"]
    assert target.by_registry["minecraft:item"].ids == ["minecraft:stone"]
    assert target.block_entities == {"minecraft:chest"}
    assert target.block_tag_members["minecraft:logs"] == ["minecraft:oak_log"]
    assert target.clock_time_markers["minecraft:overworld"] == ["minecraft:day"]
    assert target.advancement_criteria["minecraft:story/root"] == ["has_item"]


# ── ids() / tags() ────────────────────────────────────────────────────────
def test_ids_and_tags_fallbacks() -> None:
    reg = Registries()
    reg.items = ["minecraft:stone"]
    reg.item_tags = ["minecraft:logs"]
    reg.block_tags = ["minecraft:logs", "minecraft:planks"]
    assert reg.ids("minecraft:item") == ["minecraft:stone"]
    assert reg.tags("minecraft:item") == ["minecraft:logs"]
    assert reg.tags("minecraft:block") == ["minecraft:logs", "minecraft:planks"]
    assert reg.ids("minecraft:nonexistent") == []
    assert reg.ids("minecraft:nonexistent") is EMPTY
    assert reg.tags("minecraft:entity_type") is EMPTY
    # by_registry имеет приоритет над фолбэком.
    reg.by_registry["minecraft:item"] = RegistryIds(["minecraft:diamond"], ["t"])
    assert reg.ids("minecraft:item") == ["minecraft:diamond"]
    assert reg.tags("minecraft:item") == ["t"]


# ── реальные данные из .local ─────────────────────────────────────────────
def test_real_registries_export() -> None:
    if not EXPORT.is_file():
        pytest.skip("нет command-registries/registries.json в .local")
    data = json.loads(EXPORT.read_text(encoding="utf-8"))
    reg = Registries.from_export(data)

    assert "minecraft:absorption" in reg.effects
    assert len(reg.effects) == 40
    assert len(reg.enchantments) == 43
    assert len(reg.attributes) == 40
    assert len(reg.damage_types) == 51
    assert len(reg.persistent_components) == 119
    assert len(reg.learnable_recipes) == 1739
    assert len(reg.templates) == 1511
    assert len(reg.entity_types) == 161
    assert len(reg.summonable) == 159
    assert len(reg.block_entities) == 191

    # Участники block-тегов.
    assert len(reg.block_tag_members["minecraft:logs"]) == 48
    assert "minecraft:oak_log" in reg.block_tag_members["minecraft:logs"]

    # Реестры по имени: id элементов и tag-id.
    assert len(reg.ids("minecraft:item")) == 1658
    assert "minecraft:stone" in reg.ids("minecraft:item")
    assert "minecraft:logs" in reg.tags("minecraft:block")
    assert "minecraft:barrel" in reg.ids("minecraft:block_entity_type")
    assert len(reg.ids("minecraft:block")) == 1286

    # RELOADED-реестр не попал в by_registry.
    assert "minecraft:advancement" not in reg.by_registry
    assert len(reg.by_registry) >= 100

    # World clock -> маркеры времени.
    assert reg.clock_time_markers["minecraft:overworld"] == [
        "minecraft:day",
        "minecraft:midnight",
        "minecraft:night",
        "minecraft:noon",
    ]
    # Advancement id -> критерии.
    assert len(reg.advancement_criteria) == 1866

    # Экспорт заполняется идемпотентно (непустые поля не перезаписываются).
    snapshot = len(reg.effects)
    reg.fill_from_export(data)
    assert len(reg.effects) == snapshot
