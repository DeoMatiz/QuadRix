#!/usr/bin/env python3
"""[QuadRix] Предметы: реестр, свойства и стеки.

Порт horizon/crates/horizon-items/src/items.rs (Minecraft 26.3).

Что здесь:
  * ``fire_starter_sound`` / ``fire_starter_pitch`` — звук использования
    огнива/огненного заряда.
  * ``ToolRule`` и ``ItemInfo`` — свойства предмета (подмножество полей,
    которые Rust ``Items::load_with`` читает прямо из ``items.json``).
  * ``ItemComponentMap`` — компоненты стека помимо ``count``/``damage``
    (Rust: ``item_data::StackData``; полный разбор провода — следующая
    сессия по ``item_data.rs``).
  * ``ItemStack`` — стек (item/count/damage/extra).
  * ``Items`` — реестр и ``load_items``: читает ``items.json`` точно как
    ``horizon_world::item_defaults::read`` (``root.join("items.json")``),
    и ``command-registries.json`` для сетевого порядка id.

В Rust у предметов НЕТ enum ``ItemId``: id — это ``Arc<str>``, реестр —
``HashMap<Arc<str>, ItemInfo>``. Мы сохраняем те же имена и ту же строковую
идентификацию; ``Items.order`` — это и есть «таблица id».

Чего здесь НЕТ (следующие сессии, НЕ портировать сейчас):
  * ``item_data.rs`` — компоненты стека с провода, ``enchant.rs``,
    loot-таблицы, рецепты.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = [
    "ToolRule",
    "ItemInfo",
    "ItemComponentMap",
    "ItemStack",
    "Items",
    "ITEM_REGISTRY",
    "DEFAULT_RESOURCE_ROOT",
    "CRAFT_REMAINDERS",
    "MOD_CRAFT_REMAINDERS",
    "STACK_SIZE",
    "VANILLA_MAX_STACK_SIZE",
    "MAX_STACK_SIZE",
    "fire_starter_sound",
    "fire_starter_pitch",
    "load_items",
]


# ---------------------------------------------------------------------------
# Пути и константы (из Rust: item_defaults.rs, items.rs)
# ---------------------------------------------------------------------------

#: Корень подготовленных ресурсов (Rust зовёт его ``root``).
#: ``quadrix/items/items.py`` -> parents[2] == корень репозитория.
DEFAULT_RESOURCE_ROOT: Path = (
    Path(__file__).resolve().parents[2] / ".local" / "horizon-client" / "26.3"
)

#: ``Item.Properties.craftRemainder`` (items.rs:227): что остаётся в сетке
#: крафта. Это не компонент данных, поэтому его нет в отчёте компонентов.
CRAFT_REMAINDERS: Tuple[Tuple[str, str], ...] = (
    ("minecraft:water_bucket", "minecraft:bucket"),
    ("minecraft:lava_bucket", "minecraft:bucket"),
    ("minecraft:milk_bucket", "minecraft:bucket"),
    ("minecraft:dragon_breath", "minecraft:glass_bottle"),
    ("minecraft:honey_bottle", "minecraft:glass_bottle"),
)

#: В корне, собранном ``mod_content::build``: остатки крафта предметов модов.
MOD_CRAFT_REMAINDERS: str = "horizon-mod-craft-remainders.json"

#: Имя компонента размера стека (item_defaults.rs:58).
STACK_SIZE: str = "minecraft:max_stack_size"

#: Ванильный ``ExtraCodecs.intRange(1, 99)`` для значения датапака.
VANILLA_MAX_STACK_SIZE: int = 99

#: Предел, который может выставить нативный мод: ``count`` — это ``u32``,
#: но на проводе и в сейве он ``i32`` (item_defaults.rs:54).
MAX_STACK_SIZE: int = 2**31 - 1


# ---------------------------------------------------------------------------
# Звук огнива / огненного заряда (items.rs:18-35)
# ---------------------------------------------------------------------------

def fire_starter_sound(fire_charge: bool) -> str:
    """``SoundEvents.FIRECHARGE_USE`` или ``FLINTANDSTEEL_USE``."""
    if fire_charge:
        return "minecraft:item.firecharge.use"
    return "minecraft:item.flintandsteel.use"


def fire_starter_pitch(fire_charge: bool, random) -> float:
    """Высота звука по RNG уровня.

    ``FlintAndSteelItem.useOn``: ``nextFloat() * 0.4 + 0.8``;
    ``FireChargeItem.playSound``: ``(nextFloat() - nextFloat()) * 0.2 + 1.0``.
    ``random`` — источник со счётчиком ``next_float()`` (как ``RandomSource``).
    """
    if fire_charge:
        return (random.next_float() - random.next_float()) * 0.2 + 1.0
    return random.next_float() * 0.4 + 0.8


# ---------------------------------------------------------------------------
# Свойства предмета (items.rs:37-224)
# ---------------------------------------------------------------------------

@dataclass
class ToolRule:
    """Одно правило компонента ``minecraft:tool`` (items.rs:38)."""

    blocks: List[str] = field(default_factory=list)
    speed: Optional[float] = None
    correct: Optional[bool] = None


@dataclass
class ItemInfo:
    """Свойства предмета (items.rs:142 ``ItemInfo``).

    Имена полей сохранены как в Rust. Поля, которым нужны ещё не портированные
    подмодули (``consumable``, ``use_cooldown``, ``blocks_attacks``,
    ``modifiers`` и т.п.), опущены до своих сессий.
    """

    id: str
    fire_resistant: bool = False
    max_stack: int = 64
    max_damage: int = 0
    block: Optional[int] = None
    tool: List[ToolRule] = field(default_factory=list)
    tool_default_speed: float = 1.0
    tool_damage_per_block: Optional[int] = None
    can_destroy_blocks_in_creative: bool = True
    food: Optional[Tuple[int, float]] = None
    can_always_eat: bool = False
    model: str = ""
    attack_damage: float = 0.0
    attack_speed: float = 0.0
    glider: bool = False
    swappable: bool = True
    equip_dispensable: bool = True
    equip_damage_on_hurt: bool = True
    equip_slot: Optional[str] = None
    equip_asset: Optional[str] = None
    equip_sound: Optional[str] = None
    dye: Optional[str] = None
    cushion_color: Optional[str] = None
    block_transformer: Optional[str] = None
    bundle: bool = False
    components: List[str] = field(default_factory=list)
    use_remainder: Optional[str] = None
    crafting_remainder: Optional[str] = None
    remainder: Optional[str] = None
    villager_food: Optional[int] = None
    use_speed: float = 0.2
    can_sprint: bool = False
    interact_vibrations: bool = True
    weapon_damage: Optional[int] = None
    disable_blocking_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Компоненты стека (Rust: item_data::StackData, следующая сессия)
# ---------------------------------------------------------------------------

@dataclass
class ItemComponentMap:
    """Компоненты стека помимо ``count`` и ``damage``.

    Rust хранит их типизированно в ``item_data::StackData``; разбор
    компонентов с провода — задача ``item_data.rs`` (следующая сессия).
    Здесь это честная карта «id компонента -> значение», на которую
    ``ItemStack.extra`` ссылается как Rust на ``Option<Box<StackData>>``.
    """

    components: Dict[str, object] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """``StackData::is_empty``: ни одного компонента сверх default."""
        return not self.components

    def get(self, component_id: str) -> Optional[object]:
        """Значение компонента или ``None`` (нет — как ``StackData::other``)."""
        return self.components.get(component_id)

    def set(self, component_id: str, value: object) -> None:
        """Записать компонент."""
        self.components[component_id] = value

    def remove(self, component_id: str) -> None:
        """Убрать компонент (как ``StackData::set_other(id, None)``)."""
        self.components.pop(component_id, None)

    def __contains__(self, component_id: object) -> bool:
        return component_id in self.components

    def __len__(self) -> int:
        return len(self.components)


# ---------------------------------------------------------------------------
# ItemStack (items.rs:330-337, item_data.rs:272-447)
# ---------------------------------------------------------------------------

@dataclass
class ItemStack:
    """Стек предмета.

    Поля совпадают с Rust ``items::ItemStack``: ``item`` — id (``Arc<str>``),
    ``count`` (``u32``), ``damage`` (``u32``), ``extra`` — компоненты сверх
    count и damage (``Option<Box<StackData>>``; здесь ``ItemComponentMap``).
    """

    item: str
    count: int
    damage: int = 0
    extra: Optional[ItemComponentMap] = None

    # -- конструкторы --

    @classmethod
    def new(cls, item: str, count: int) -> "ItemStack":
        """``ItemStack::new`` (item_data.rs:273)."""
        return cls(item=item, count=count, damage=0, extra=None)

    @classmethod
    def empty(cls) -> "ItemStack":
        """``ItemStack.EMPTY``: воздух, нулевое количество."""
        return cls(item="minecraft:air", count=0, damage=0, extra=None)

    # -- helpers --

    def is_empty(self) -> bool:
        """``ItemStack.isEmpty``: воздуха или пустого количества достаточно."""
        return self.item == "minecraft:air" or self.count <= 0

    def item_id(self) -> str:
        """Id предмета (в Rust — поле ``item``)."""
        return self.item

    def same_item(self, other: "ItemStack") -> bool:
        """Сравнение предмета и компонент (не только типа).

        Ваниль ``ItemStack.isSameItem`` сравнивает лишь id; здесь по заданию
        учитываются и компоненты (``damage`` + ``extra``) — то же, что
        ``same_item_same_components`` и Rust ``isSameItemSameComponents``
        (item_data.rs:434). Количество, как и в Rust, не сравнивается.
        """
        return (
            self.item == other.item
            and self.damage == other.damage
            and self.data() == other.data()
        )

    def same_item_same_components(self, other: "ItemStack") -> bool:
        """``ItemStack.isSameItemSameComponents`` (item_data.rs:434)."""
        return self.item == other.item and self.damage == other.damage and self.data() == other.data()

    def data(self) -> Optional[ItemComponentMap]:
        """``ItemStack::data`` (item_data.rs:281)."""
        return self.extra

    def tidy(self) -> None:
        """``ItemStack::tidy``: выбросить пустую коробку компонентов."""
        if self.extra is not None and self.extra.is_empty():
            self.extra = None

    def transmute(self, item: str, count: int) -> "ItemStack":
        """``ItemStack::transmuteCopy``: другой предмет, все компоненты те же."""
        stack = ItemStack(item=item, count=count, damage=self.damage, extra=self.extra)
        stack.tidy()
        return stack

    def __len__(self) -> int:
        return self.count

    # -- прочность и стекаемость (component_durability.rs, item_use_catalog.rs,
    #    stations.rs; APPEND этой сессии) --

    def data_mut(self) -> ItemComponentMap:
        """``ItemStack::data_mut`` (item_data.rs:294): extra, создавая коробку."""
        if self.extra is None:
            self.extra = ItemComponentMap()
        return self.extra

    def max_damage(self) -> int:
        """``Info.max_damage`` предмета (0 — не ломается)."""
        info = ITEM_REGISTRY.get(self.item)
        return info.max_damage if info is not None else 0

    def is_damageable(self) -> bool:
        """``ItemStack.isDamageableItem`` (stations.rs:170).

        Есть прочность и нет ``minecraft:unbreakable``.
        """
        info = ITEM_REGISTRY.get(self.item)
        if info is None or info.max_damage <= 0:
            return False
        if self.extra is not None and "minecraft:unbreakable" in self.extra:
            return False
        return True

    def is_damaged(self) -> bool:
        """``DurabilityStack.is_damaged`` (item_durability.rs:40)."""
        return self.is_damageable() and self.damage > 0

    def is_broken(self) -> bool:
        """``DurabilityStack.is_broken`` (item_durability.rs:43)."""
        return self.is_damageable() and self.damage >= self.max_damage()

    def next_damage_will_break(self) -> bool:
        """``DurabilityStack.next_damage_will_break`` (item_durability.rs:46)."""
        return self.is_damageable() and self.damage >= self.max_damage() - 1

    def damage_per_hit(self) -> int:
        """Прочность, снимаемая за удар.

        ``ItemStack.postHurtEnemy``: ``weapon.item_damage_per_attack``;
        у оружия без него (и у не-оружия) — 1 (items.rs:928).
        """
        info = ITEM_REGISTRY.get(self.item)
        if info is not None and info.weapon_damage is not None:
            return info.weapon_damage
        return 1

    def next_damage(self) -> int:
        """Повреждение после следующего удара (``damage + damage_per_hit``).

        Ограничено ``max_damage``, как ``set_damage`` (item_durability.rs:34).
        Непрочный предмет не меняется.
        """
        if not self.is_damageable():
            return self.damage
        return min(self.damage + self.damage_per_hit(), self.max_damage())

    def is_stackable(self) -> bool:
        """``ItemUseStack.is_stackable`` (item_use_catalog.rs:83)."""
        info = ITEM_REGISTRY.get(self.item)
        max_stack = info.max_stack if info is not None else 1
        if max_stack <= 1:
            return False
        return not (self.is_damageable() and self.is_damaged())


# ---------------------------------------------------------------------------
# Разбор items.json (item_defaults.rs::read, items.rs::load_with)
# ---------------------------------------------------------------------------

def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _stack_size(value: object, maximum: int) -> Optional[int]:
    """``value`` как размер стека в ``1..=maximum``; ``None`` — не число.

    Порт ``item_defaults::stack_size``.
    """
    if not _is_number(value):
        return None
    return max(1, min(int(value), maximum))


def _read_default_components(root: Path) -> Dict[str, dict]:
    """``horizon_world::item_defaults::read``: items.json с ванильным clamp.

    Датапак — значение остаётся в ``1..=99`` (``ExtraCodecs.intRange``).
    """
    path = root / "items.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise FileNotFoundError(f"[QuadRix] items.json not found: {path}") from None
    items = json.loads(raw)
    for _item, components in items.items():
        if isinstance(components, dict) and STACK_SIZE in components:
            size = _stack_size(components[STACK_SIZE], VANILLA_MAX_STACK_SIZE)
            if size is not None:
                components[STACK_SIZE] = size
    return items


def _attribute_modifier(components: dict, kind: str) -> float:
    """Сумма ``amount`` модификаторов ``kind`` с ``operation == add_value``.

    Порт замыкания ``modifier`` из ``Items::load_with``.
    """
    total = 0.0
    modifiers = components.get("minecraft:attribute_modifiers")
    if isinstance(modifiers, list):
        for m in modifiers:
            if not isinstance(m, dict):
                continue
            if m.get("type") == kind and m.get("operation") == "add_value":
                amount = m.get("amount")
                if _is_number(amount):
                    total += float(amount)
    return total


def _allowed_text(value: object) -> Optional[str]:
    return value if isinstance(value, str) else None


def _item_info(name: str, c: dict) -> ItemInfo:
    """Один ``ItemInfo`` из JSON-компонентов предмета (``load_with``)."""

    tool = c.get("minecraft:tool")
    tool_rules: List[ToolRule] = []
    tool_default_speed = 1.0
    tool_damage_per_block: Optional[int] = None
    if isinstance(tool, dict):
        rules = tool.get("rules")
        if isinstance(rules, list):
            for r in rules:
                if not isinstance(r, dict):
                    continue
                blocks = r.get("blocks")
                if isinstance(blocks, str):
                    parsed_blocks = [blocks]
                elif isinstance(blocks, list):
                    parsed_blocks = [b for b in blocks if isinstance(b, str)]
                else:
                    parsed_blocks = []
                speed = r.get("speed")
                correct = r.get("correct_for_drops")
                tool_rules.append(
                    ToolRule(
                        blocks=parsed_blocks,
                        speed=float(speed) if _is_number(speed) else None,
                        correct=correct if isinstance(correct, bool) else None,
                    )
                )
        default_speed = tool.get("default_mining_speed")
        tool_default_speed = float(default_speed) if _is_number(default_speed) else 1.0
        per_block = tool.get("damage_per_block")
        tool_damage_per_block = int(per_block) if _is_number(per_block) else 1

    can_destroy = True
    if isinstance(tool, dict):
        flag = tool.get("can_destroy_blocks_in_creative")
        can_destroy = flag if isinstance(flag, bool) else True

    food: Optional[Tuple[int, float]] = None
    can_always_eat = False
    food_json = c.get("minecraft:food")
    if isinstance(food_json, dict):
        nutrition = food_json.get("nutrition")
        saturation = food_json.get("saturation")
        food = (
            int(nutrition) if _is_number(nutrition) else 0,
            float(saturation) if _is_number(saturation) else 0.0,
        )
        flag = food_json.get("can_always_eat")
        can_always_eat = flag if isinstance(flag, bool) else False

    damage_resistant = c.get("minecraft:damage_resistant")
    fire_resistant = (
        isinstance(damage_resistant, dict)
        and damage_resistant.get("types") == "#minecraft:is_fire"
    )

    equippable = c.get("minecraft:equippable")
    equip = equippable if isinstance(equippable, dict) else {}

    weapon = c.get("minecraft:weapon")
    weapon_damage: Optional[int] = None
    disable_blocking_seconds = 0.0
    if isinstance(weapon, dict):
        per_attack = weapon.get("item_damage_per_attack")
        weapon_damage = int(per_attack) if _is_number(per_attack) else 1
        disable = weapon.get("disable_blocking_for_seconds")
        disable_blocking_seconds = float(disable) if _is_number(disable) else 0.0

    use_effects = c.get("minecraft:use_effects")
    use = use_effects if isinstance(use_effects, dict) else {}
    speed_multiplier = use.get("speed_multiplier")
    use_speed = float(speed_multiplier) if _is_number(speed_multiplier) else 0.2
    can_sprint = use.get("can_sprint")
    can_sprint = can_sprint if isinstance(can_sprint, bool) else False
    interact_vibrations = use.get("interact_vibrations")
    interact_vibrations = interact_vibrations if isinstance(interact_vibrations, bool) else True

    use_remainder = None
    use_remainder_json = c.get("minecraft:use_remainder")
    if isinstance(use_remainder_json, dict):
        use_remainder = _allowed_text(use_remainder_json.get("id"))

    crafting_remainder: Optional[str] = None
    for item, rest in CRAFT_REMAINDERS:
        if item == name:
            crafting_remainder = rest
            break

    remainder = use_remainder
    if remainder is None:
        crafting_json = c.get("minecraft:crafting_remainder")
        if isinstance(crafting_json, dict):
            remainder = _allowed_text(crafting_json.get("id"))
        else:
            remainder = _allowed_text(crafting_json)
        if crafting_remainder is None:
            crafting_remainder = remainder

    villager_food_json = c.get("minecraft:villager_food")
    villager_food: Optional[int] = None
    if isinstance(villager_food_json, dict):
        nutrition = villager_food_json.get("nutrition")
        villager_food = int(nutrition) if _is_number(nutrition) else None

    max_stack_json = c.get(STACK_SIZE)
    max_stack = int(max_stack_json) if _is_number(max_stack_json) else 64
    max_damage_json = c.get("minecraft:max_damage")
    max_damage = int(max_damage_json) if _is_number(max_damage_json) else 0

    model = _allowed_text(c.get("minecraft:item_model")) or name

    glider = isinstance(c.get("minecraft:glider"), dict)
    swappable = equippable.get("swappable") if isinstance(equippable, dict) else None
    swappable = swappable if isinstance(swappable, bool) else True
    equip_dispensable = equip.get("dispensable")
    equip_dispensable = equip_dispensable if isinstance(equip_dispensable, bool) else True
    equip_damage_on_hurt = equip.get("damage_on_hurt")
    equip_damage_on_hurt = (
        equip_damage_on_hurt if isinstance(equip_damage_on_hurt, bool) else True
    )

    return ItemInfo(
        id=name,
        fire_resistant=fire_resistant,
        max_stack=max_stack,
        max_damage=max_damage,
        tool=tool_rules,
        tool_default_speed=tool_default_speed,
        tool_damage_per_block=tool_damage_per_block,
        can_destroy_blocks_in_creative=can_destroy,
        food=food,
        can_always_eat=can_always_eat,
        model=model,
        attack_damage=_attribute_modifier(c, "minecraft:attack_damage"),
        attack_speed=_attribute_modifier(c, "minecraft:attack_speed"),
        glider=glider,
        swappable=swappable,
        equip_dispensable=equip_dispensable,
        equip_damage_on_hurt=equip_damage_on_hurt,
        equip_slot=_allowed_text(equip.get("slot")),
        equip_asset=_allowed_text(equip.get("asset_id")),
        equip_sound=_allowed_text(equip.get("equip_sound")),
        dye=_allowed_text(c.get("minecraft:dye")),
        cushion_color=_allowed_text(c.get("minecraft:cushion/color")),
        block_transformer=_allowed_text(c.get("minecraft:block_transformer")),
        bundle="minecraft:bundle_contents" in c,
        components=list(c.keys()),
        use_remainder=use_remainder,
        crafting_remainder=crafting_remainder,
        remainder=remainder,
        villager_food=villager_food,
        use_speed=use_speed,
        can_sprint=can_sprint,
        interact_vibrations=interact_vibrations,
        weapon_damage=weapon_damage,
        disable_blocking_seconds=disable_blocking_seconds,
    )


# ---------------------------------------------------------------------------
# Реестр (items.rs:366 Items, 340 registry_order, 742 catalog)
# ---------------------------------------------------------------------------

def _registry_order(root: Path, order: List[str]) -> List[str]:
    """Порядок сетевых id из ``command-registries.json``.

    Порт ``registry_order`` (items.rs:340): элементы из ``order``, стоящие
    в файле, в порядке файла; сам ``order``, если файла нет.
    """
    path = root / "command-registries.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return list(order)
    listed = json.loads(raw).get("items")
    if not isinstance(listed, list) or not listed:
        return list(order)
    known = set(order)
    return [i for i in listed if isinstance(i, str) and i in known]


class Items:
    """Реестр предметов (items.rs:366 ``Items``).

    Поля сохранены как в Rust: ``items`` (id -> ``ItemInfo``), ``order``
    (порядок из items.json — в Rust это ``BTreeMap``, значит по имени) и
    ``registry_order`` (порядок сетевых id). Теги, loot и enchantments пока
    не портированы и здесь отсутствуют.
    """

    def __init__(
        self,
        items: Dict[str, ItemInfo],
        order: List[str],
        registry_order: List[str],
    ) -> None:
        self.items = items
        self.order = order
        self.registry_order = registry_order

    # -- контейнерные операции --

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, item_id: str) -> ItemInfo:
        return self.items[item_id]

    def __contains__(self, item_id: object) -> bool:
        return item_id in self.items

    def __iter__(self):
        return iter(self.items)

    # -- API --

    def get(self, item_id: str) -> Optional[ItemInfo]:
        """``Items::get`` (items.rs:994)."""
        return self.items.get(item_id)

    def is_empty(self) -> bool:
        return not self.items


def load_items(root: Optional[Path] = None) -> Items:
    """Загрузить реестр предметов из ``root`` (``Items::catalog``, items.rs:742).

    ``root`` по умолчанию — ``.local/horizon-client/26.3``. Читает
    ``items.json`` так же, как Rust ``horizon_world::item_defaults::read``.
    """
    if root is None:
        root = DEFAULT_RESOURCE_ROOT
    root = Path(root)
    raw = _read_default_components(root)
    items: Dict[str, ItemInfo] = {}
    for name, components in raw.items():
        if not isinstance(components, dict):
            components = {}
        items[name] = _item_info(name, components)
    # Rust хранит items в BTreeMap, поэтому order идёт по имени.
    order = sorted(items.keys())
    registry_order = _registry_order(root, order)
    return Items(items=items, order=order, registry_order=registry_order)


#: Реестр предметов по умолчанию: подготовленные ресурсы в ``.local``.
ITEM_REGISTRY: Items = load_items()
