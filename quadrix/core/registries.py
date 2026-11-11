# Порт horizon-client-core/src/registries.rs (Minecraft 26.3).
#
# `Registries` — это НЕ generic `Registry<T>` (тот живёт в
# horizon-world/src/registry.rs, уже портирован как quadrix.world.registry и
# читает block-registry.nbt). Здесь — состояние источников команд: какие id
# и tag-id существуют, чтобы валидировать и автодополнять аргументы команд
# (то, что держит registry access сервера). Поля — те же, что в Rust.
#
# Данные подгружаются из экспорта vanilla (`command-registries.json`,
# `.local/command-registries/registries.json`) через `fill_from_export`:
# встроенные реестры (эффекты, компоненты, block entities, участники тегов).
# Реестры, которые перегружают датапаки, остаются у игры (RELOADED).

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

__all__ = [
    "Registries",
    "RegistryIds",
    "CustomCompletionAction",
    "modify_custom_completions",
    "RELOADED",
    "EMPTY",
]


# ── один реестр: id элементов и id тегов ────────────────────────────────
@dataclass
class RegistryIds:
    """`RegistryIds`: id и tag-id одного реестра."""

    ids: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


# ── ClientboundCustomChatCompletionsPacket.Action ───────────────────────
class CustomCompletionAction(Enum):
    """`CustomCompletionAction`: Add, Remove, Set."""

    Add = 0
    Remove = 1
    Set = 2

    @classmethod
    def from_id(cls, id: int) -> "CustomCompletionAction":
        """`Action.BY_ID`: `ByIdMap.continuous` со стратегией `ZERO`, поэтому
        неизвестный id — это Add."""
        if id == 1:
            return cls.Remove
        if id == 2:
            return cls.Set
        return cls.Add


def modify_custom_completions(
    completions: Set[str],
    action: CustomCompletionAction,
    entries: List[str],
) -> None:
    """`ClientSuggestionProvider.modifyCustomCompletions`: сервер добавляет,
    удаляет или заменяет дополнительные чат-дополнения.

    `completions` — Python-множество (в Rust это BTreeSet), мутируется на
    месте; имя параметра отличается от Rust `set` только из-за встроенного
    `set` в Python.
    """
    if action is CustomCompletionAction.Add:
        completions.update(entries)
    elif action is CustomCompletionAction.Remove:
        for e in entries:
            completions.discard(e)
    elif action is CustomCompletionAction.Set:
        completions.clear()
        completions.update(entries)


# ── состояние источников команд ─────────────────────────────────────────
@dataclass
class Registries:
    """`Registries`: содержимое реестров и состояние источников команд.

    Компаунды `BTreeMap` в Rust → обычные `dict`, `BTreeSet` → `set`,
    `Vec` → `list`, `Option` → `Optional`. `Default` из Rust даёт пустые
    контейнеры/None через `default_factory`.
    """

    # Уровень прав источника команд.
    permission: int = 0
    items: List[str] = field(default_factory=list)
    item_tags: List[str] = field(default_factory=list)
    # Block id -> (property, allowed values).
    blocks: Dict[str, List[Tuple[str, List[str]]]] = field(default_factory=dict)
    block_tags: List[str] = field(default_factory=list)
    # Типы сущностей, которые может создать `summon`.
    summonable: List[str] = field(default_factory=list)
    # Все типы сущностей (селектор `type=`).
    entity_types: List[str] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)
    enchantments: List[str] = field(default_factory=list)
    structures: List[str] = field(default_factory=list)
    biomes: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    clocks: List[str] = field(default_factory=list)
    timelines: List[str] = field(default_factory=list)
    time_markers: List[str] = field(default_factory=list)
    advancements: List[str] = field(default_factory=list)
    # Game rule name -> integer-valued.
    game_rules: List[Tuple[str, bool]] = field(default_factory=list)
    players: List[str] = field(default_factory=list)
    ops: List[str] = field(default_factory=list)
    banned_players: List[str] = field(default_factory=list)
    banned_ips: List[str] = field(default_factory=list)
    whitelisted: List[str] = field(default_factory=list)
    # ClientSuggestionProvider.customCompletionSuggestions.
    custom_completions: Set[str] = field(default_factory=set)
    objectives: List[str] = field(default_factory=list)
    teams: List[str] = field(default_factory=list)
    tracked: List[str] = field(default_factory=list)
    # Загруженные датапак-функции (`ns:path`) и function tags.
    functions: List[str] = field(default_factory=list)
    # `/data ... storage` id.
    storages: List[str] = field(default_factory=list)
    bossbars: List[str] = field(default_factory=list)
    predicates: List[str] = field(default_factory=list)
    item_modifiers: List[str] = field(default_factory=list)
    schedules: List[str] = field(default_factory=list)
    stopwatches: List[str] = field(default_factory=list)
    recipes: List[str] = field(default_factory=list)
    sounds: List[str] = field(default_factory=list)
    damage_types: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    loot_tables: List[str] = field(default_factory=list)
    templates: List[str] = field(default_factory=list)
    random_sequences: List[str] = field(default_factory=list)
    datapacks_enabled: List[str] = field(default_factory=list)
    datapacks_disabled: List[str] = field(default_factory=list)
    function_tags: List[str] = field(default_factory=list)
    # Блок, на который смотрит источник (релевантные координаты).
    target_block: Optional[List[int]] = None
    # Entity.getStringUUID сущности под прицелом.
    selected_entities: List[str] = field(default_factory=list)
    # Точка попадания блока, каждая координата как `%.2f`.
    target_point: Optional[List[str]] = None
    # id элементов/тегов каждого реестра (`minecraft:item` -> ...).
    by_registry: Dict[str, RegistryIds] = field(default_factory=dict)
    # Блоки, у дефолтного состояния которых есть block entity.
    block_entities: Set[str] = field(default_factory=set)
    # Block tag -> блоки-участники.
    block_tag_members: Dict[str, List[str]] = field(default_factory=dict)
    # Типы data components с кодеком (не transient).
    persistent_components: List[str] = field(default_factory=list)
    # Рецепты, которые может выдать `/recipe` (не special).
    learnable_recipes: List[str] = field(default_factory=list)
    # Advancement id -> имена критериев.
    advancement_criteria: Dict[str, List[str]] = field(default_factory=dict)
    # World clock -> time markers, показываемые в командах.
    clock_time_markers: Dict[str, List[str]] = field(default_factory=dict)
    # Trigger-цели, которые может использовать источник (`/trigger`).
    trigger_objectives: List[str] = field(default_factory=list)
    # Objectives с критерием `trigger` -> holder -> заблокирован ли счёт.
    trigger_scores: Dict[str, Dict[str, bool]] = field(default_factory=dict)

    # ── чат-дополнения ──────────────────────────────────────────────────
    def custom_tab_suggestions(self) -> Set[str]:
        """`ClientSuggestionProvider.getCustomTabSuggestions`: имена онлайн-
        игроков вместе с дополнениями сервера, каждое один раз."""
        return set(self.players) | set(self.custom_completions)

    # ── заполнение из экспорта vanilla ──────────────────────────────────
    def fill_from_export(self, r: dict) -> None:
        """Заполнить то, что игра не построила сама, из экспортированных
        реестров vanilla. Реестры, перегружаемые датапаками, остаются у игры.
        """
        self._fill_vectors(r)
        if not self.summonable:
            self.summonable = sorted(set(_strings(r.get("summonable"))))
        if not self.entity_types:
            self.entity_types = sorted(set(_strings(r.get("entity_types"))))
        self._fill_by_registry(r)
        if not self.block_entities:
            self.block_entities = set(_strings(r.get("block_entities")))
        if not self.block_tag_members:
            for tag, members in _object(r.get("block_tag_members")):
                self.block_tag_members[tag] = _strings(members)
        if not self.clock_time_markers:
            for clock, markers in _object(r.get("clock_time_markers")):
                self.clock_time_markers[clock] = _strings(markers)
        if not self.advancement_criteria:
            for adv_id, criteria in _object(r.get("advancement_criteria")):
                self.advancement_criteria[adv_id] = _strings(criteria)

    @classmethod
    def from_export(cls, r: dict) -> "Registries":
        """Только то, что берёт `fill_from_export` из экспорта, чтобы хранить
        это вместо самого экспорта (треть его памяти)."""
        out = cls()
        out.fill_from_export(r)
        return out

    def fill_from_exported(self, e: "Registries") -> None:
        """`fill_from_export` из уже прочитанного экспорта: дозаполнить каждое
        оставшееся пустым поле, каждый не указанный реестр."""
        self._fill_exported_vectors(e)
        if not self.summonable:
            self.summonable = sorted(set(e.summonable))
        if not self.entity_types:
            self.entity_types = sorted(set(e.entity_types))
        for name, ids in e.by_registry.items():
            if name not in self.by_registry:
                self.by_registry[name] = RegistryIds(list(ids.ids), list(ids.tags))
        if not self.block_entities:
            self.block_entities = set(e.block_entities)
        if not self.block_tag_members:
            self.block_tag_members = {
                k: list(v) for k, v in e.block_tag_members.items()
            }
        if not self.clock_time_markers:
            self.clock_time_markers = {
                k: list(v) for k, v in e.clock_time_markers.items()
            }
        if not self.advancement_criteria:
            self.advancement_criteria = {
                k: list(v) for k, v in e.advancement_criteria.items()
            }

    def _fill_vectors(self, r: dict) -> None:
        for field_name, key in _VECTOR_FILLS:
            if not getattr(self, field_name):
                setattr(self, field_name, _strings(r.get(key)))

    def _fill_exported_vectors(self, e: "Registries") -> None:
        for field_name, _key in _VECTOR_FILLS:
            if not getattr(self, field_name):
                setattr(self, field_name, list(getattr(e, field_name)))

    def _fill_by_registry(self, r: dict) -> None:
        for name, entry in _object(r.get("by_registry")):
            if name in RELOADED or name in self.by_registry:
                continue
            if isinstance(entry, dict):
                ids = _strings(entry.get("ids"))
                tags = _strings(entry.get("tags"))
            else:
                ids, tags = [], []
            self.by_registry[name] = RegistryIds(ids, tags)

    # ── доступ к id/тегам реестра ───────────────────────────────────────
    def ids(self, registry: str) -> List[str]:
        """id элементов реестра (отсортированы)."""
        if registry in self.by_registry:
            return self.by_registry[registry].ids
        for name, field_name in _ID_FALLBACKS:
            if registry == name:
                return getattr(self, field_name)
        return EMPTY

    def tags(self, registry: str) -> List[str]:
        """tag-id реестра (отсортированы)."""
        if registry in self.by_registry:
            return self.by_registry[registry].tags
        if registry == "minecraft:item":
            return self.item_tags
        if registry == "minecraft:block":
            return self.block_tags
        return EMPTY


# Поля, которые `fill_from_export` берёт из плоских ключей экспорта.
_VECTOR_FILLS: List[Tuple[str, str]] = [
    ("effects", "effects"),
    ("enchantments", "enchantments"),
    ("attributes", "attributes"),
    ("damage_types", "damage_types"),
    ("templates", "templates"),
    ("persistent_components", "persistent_components"),
    ("learnable_recipes", "learnable_recipes"),
]

# Реестр -> поле `Registries` для фолбэка `ids()`.
_ID_FALLBACKS: List[Tuple[str, str]] = [
    ("minecraft:item", "items"),
    ("minecraft:entity_type", "entity_types"),
    ("minecraft:mob_effect", "effects"),
    ("minecraft:enchantment", "enchantments"),
    ("minecraft:worldgen/structure", "structures"),
    ("minecraft:worldgen/biome", "biomes"),
    ("minecraft:world_clock", "clocks"),
    ("minecraft:timeline", "timelines"),
    ("minecraft:attribute", "attributes"),
    ("minecraft:damage_type", "damage_types"),
    ("minecraft:sound_event", "sounds"),
    ("minecraft:predicate", "predicates"),
    ("minecraft:item_modifier", "item_modifiers"),
    ("minecraft:loot_table", "loot_tables"),
    ("minecraft:recipe", "recipes"),
    ("minecraft:advancement", "advancements"),
]

# Реестры, которые перегружают датапаки: их не берём из экспорта.
RELOADED: Tuple[str, ...] = (
    "minecraft:advancement",
    "minecraft:recipe",
    "minecraft:loot_table",
    "minecraft:predicate",
    "minecraft:item_modifier",
)

# Пустой список (Rust `const EMPTY: &[String] = &[]`).
EMPTY: List[str] = []


# ── помощники разбора serde_json::Value (как в Rust) ────────────────────
def _strings(v: object) -> List[str]:
    """`strings`: элементы массива, оставшиеся строками (иначе пусто)."""
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


def _object(v: object) -> List[Tuple[str, object]]:
    """Объект serde_json как список пар (иначе пусто)."""
    if isinstance(v, dict):
        return list(v.items())
    return []
