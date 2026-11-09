#!/usr/bin/env python3
"""[QuadRix] Компоненты стека предмета: NBT-модель и провод.

Порт horizon/crates/horizon-items/src/item_data.rs (Minecraft 26.3) и его
проводной половины из horizon/crates/horizon-protocol/src/item.rs (+ item/skip.rs).

Здесь две связанные, но разные вещи:

  * **NBT-модель** (``StackData``, ``decode_components``, ``encode_components``,
    ``components_tag``) — как Rust хранит компоненты, прочитанные из сейва
    (``minecraft:components`` compound). Значения полей названы точно как в
    item_data.rs.
  * **Провод** (``ComponentMap``/``ComponentPatch``, ``Component``-варианты,
    ``Stack``, ``Slot``/``DelimitedSlot``/``Template``, ``read_stack``/
    ``write_stack``) — формат vanilla 1.20.5+: ``count``, id предмета,
    число added компонент, число removed, затем каждая добавленная компонента
    (varint id + payload) и varint-id удалённых. Значения и порядок — как в
    item.rs; непонятые компоненты читаются в ``ComponentRaw`` через skip.rs.

Реестр компонент (id <-> имя) читается из ``registries.json``
(``minecraft:data_component_type``), не хардкодится.

Не портируется: enchant.rs, рецепты, торговля, модификационные custom-компоненты.

Любой вывод начинается с ``[QuadRix]``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from quadrix.items.items import (
    DEFAULT_RESOURCE_ROOT,
    ItemComponentMap,
    ItemStack,
)
from quadrix.protocol.buf import (
    ProtocolError,
    Reader,
    Writer,
    pack_block_pos,
    unpack_block_pos,
)
from quadrix.world.nbt import Tag, TagType

__all__ = [
    # реестр компонент
    "COMPONENT_IDS",
    "COMPONENT_NAMES",
    "ItemComponent",
    "component_id",
    "component_name",
    "load_component_registry",
    # NBT-модель (item_data.rs)
    "Wire",
    "BundleSelected",
    "WrittenBook",
    "FireworkShape",
    "FireworkExplosion",
    "BannerLayer",
    "StackData",
    "MODELLED",
    "OMINOUS_LAYERS",
    "component_bool",
    "destroyed_container",
    "decode_components",
    "encode_components",
    "components_tag",
    # провод (item.rs)
    "Component",
    "ComponentInt",
    "ComponentUnit",
    "ComponentBool",
    "ComponentText",
    "ComponentNbt",
    "ComponentIdent",
    "ComponentLore",
    "ComponentEnchantments",
    "ComponentAttackRange",
    "ComponentPotion",
    "ComponentProfile",
    "ComponentCustomModelData",
    "ComponentTooltipDisplay",
    "ComponentWritableBook",
    "ComponentWrittenBook",
    "ComponentStacks",
    "ComponentFireworks",
    "ComponentFireworkExplosion",
    "ComponentLodestoneTracker",
    "ComponentTrim",
    "ComponentStewEffects",
    "ComponentInstrument",
    "ComponentBannerPatterns",
    "ComponentPaintingVariant",
    "ComponentRaw",
    "WireProfile",
    "WireSkinPatch",
    "WireWrittenBook",
    "WireFireworkExplosion",
    "ComponentMap",
    "ComponentPatch",
    "WirePatch",
    "Stack",
    "read_stack",
    "write_stack",
    "Slot",
    "DelimitedSlot",
    "Template",
]


# ---------------------------------------------------------------------------
# Реестр компонент (minecraft:data_component_type, registries.json)
# ---------------------------------------------------------------------------

def load_component_registry(root: Optional[Path] = None) -> Dict[str, int]:
    """Прочитать реестр ``data_component_type`` из ``registries.json``.

    Возвращает ``{имя_компоненты: protocol_id}``. Файла нет — исключение,
    как ``items.json`` в items.py (никаких заглушек).
    """
    if root is None:
        root = DEFAULT_RESOURCE_ROOT
    path = Path(root) / "registries.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"[QuadRix] registries.json not found: {path}"
        ) from None
    doc = json.loads(raw)
    registry = doc.get("minecraft:data_component_type")
    if not isinstance(registry, dict):
        raise ValueError("[QuadRix] registries.json has no data_component_type")
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("[QuadRix] data_component_type has no entries")
    out: Dict[str, int] = {}
    for name, value in entries.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        protocol_id = value.get("protocol_id")
        if isinstance(protocol_id, int):
            out[name] = protocol_id
    return out


COMPONENT_IDS: Dict[str, int] = load_component_registry()
COMPONENT_NAMES: Dict[int, str] = {v: k for k, v in COMPONENT_IDS.items()}


def component_id(name: str) -> Optional[int]:
    """protocol_id компоненты по имени (или ``None``)."""
    return COMPONENT_IDS.get(name)


def component_name(kind: int) -> Optional[str]:
    """Имя компоненты по protocol_id (или ``None``)."""
    return COMPONENT_NAMES.get(kind)


def _enum_member(name: str) -> str:
    """Имя элемента enum из id компоненты (``minecraft:max_stack_size`` ->
    ``MAX_STACK_SIZE``)."""
    short = name.split(":", 1)[1] if ":" in name else name
    chars: List[str] = []
    for ch in short:
        chars.append(ch.upper() if ch.isalnum() else "_")
    text = "".join(chars)
    while "__" in text:
        text = text.replace("__", "_")
    text = text.strip("_")
    if not text or text[0].isdigit():
        text = "C_" + text
    return text


def _build_item_component_enum() -> type:
    members: Dict[str, str] = {}
    for name in sorted(COMPONENT_IDS):
        member = _enum_member(name)
        candidate = member
        suffix = 2
        while candidate in members:
            candidate = f"{member}_{suffix}"
            suffix += 1
        members[candidate] = name
    return Enum("ItemComponent", members, type=str)


#: Все компоненты 26.3: имя элемента -> полный id (``str``-enum).
ItemComponent = _build_item_component_enum()


# ---------------------------------------------------------------------------
# NBT-модель из item_data.rs
# ---------------------------------------------------------------------------

def _t_string(s: str) -> Tag:
    return Tag(TagType.String, str_val=s)


def _t_int(v: int) -> Tag:
    return Tag(TagType.Int, int_val=int(v))


def _t_byte(v: int) -> Tag:
    return Tag(TagType.Byte, byte_val=int(v))


def _t_compound(pairs) -> Tag:
    return Tag(TagType.Compound, compound_val=dict(pairs))


def _t_list(items) -> Tag:
    return Tag(TagType.List, list_val=list(items))


def _get(tag: Optional[Tag], key: str) -> Optional[Tag]:
    if tag is None or tag.compound_val is None:
        return None
    return tag.compound_val.get(key)


def _as_number(tag: Optional[Tag]) -> Optional[float]:
    """``datafix::dynamic::as_number``: числовой тег в float."""
    if tag is None:
        return None
    tt = tag.tag_type
    if tt == TagType.Byte:
        return float(tag.byte_val or 0)
    if tt == TagType.Short:
        return float(tag.short_val or 0)
    if tt == TagType.Int:
        return float(tag.int_val or 0)
    if tt == TagType.Long:
        return float(tag.long_val or 0)
    if tt == TagType.Float:
        return float(tag.float_val or 0.0)
    if tt == TagType.Double:
        return float(tag.double_val or 0.0)
    return None


def _as_int(tag: Optional[Tag], default: int) -> int:
    """``datafix::dynamic::as_int``: усечение к нулю."""
    n = _as_number(tag)
    if n is None:
        return default
    return int(n)


def _t_int_value(tag: Optional[Tag]) -> Optional[int]:
    n = _as_number(tag)
    return None if n is None else int(n)


def _namespaced(name: str) -> str:
    """``datafix::dynamic::namespaced``: без ``:`` -> ``minecraft:``."""
    return name if ":" in name else "minecraft:" + name


def _plain_text(tag: Optional[Tag]) -> Optional[str]:
    """Плоский текст компоненты (``component::name_text(...).plain()``).

    Достаточно для строк, ``{text:..}``, вложенных ``extra`` и списков.
    """
    if tag is None:
        return None
    if tag.tag_type == TagType.String:
        return tag.str_val or ""
    if tag.tag_type == TagType.List:
        parts = [_plain_text(item) for item in (tag.list_val or [])]
        text = "".join(p for p in parts if p is not None)
        return text
    if tag.tag_type == TagType.Compound:
        out: List[str] = []
        root = tag.compound_val.get("text")
        if root is not None:
            text = _plain_text(root)
            if text is not None:
                out.append(text)
        extra = tag.compound_val.get("extra")
        if extra is not None and extra.tag_type == TagType.List:
            for item in extra.list_val or []:
                text = _plain_text(item)
                if text is not None:
                    out.append(text)
        return "".join(out)
    return None


def _read_text(tag: Optional[Tag]) -> Optional[str]:
    if tag is None:
        return None
    if tag.tag_type == TagType.String:
        return tag.str_val or ""
    if tag.tag_type in (TagType.Compound, TagType.List):
        return _plain_text(tag)
    return None


def _filterable_text(tag: Optional[Tag]) -> Optional[str]:
    raw = _get(tag, "raw")
    if raw is not None:
        return _read_text(raw)
    return _read_text(tag)


def _collapsed_text(tag: Tag) -> Tag:
    """``Component.tryCollapseToString``: plain text без стиля -> строка."""
    if tag.tag_type == TagType.Compound and tag.compound_val is not None:
        text = tag.compound_val.get("text")
        if text is not None and text.tag_type == TagType.String:
            ok = True
            for key, value in tag.compound_val.items():
                if key == "text":
                    continue
                if key == "type" and value.tag_type == TagType.String \
                        and (value.str_val or "") == "text":
                    continue
                if key == "extra" and value.tag_type == TagType.List \
                        and not (value.list_val or []):
                    continue
                ok = False
                break
            if ok:
                return _t_string(text.str_val or "")
    return tag


def _plain_component(tag: Tag) -> Tag:
    """``ComponentSerialization`` short form: ``{text:..}`` без стиля -> строка."""
    if tag.tag_type == TagType.Compound and tag.compound_val is not None:
        keys = tag.compound_val
        text = keys.get("text")
        if text is not None and text.tag_type == TagType.String:
            ok = True
            for key, value in keys.items():
                if key == "text":
                    continue
                if key == "type" and value.tag_type == TagType.String \
                        and (value.str_val or "") == "text":
                    continue
                ok = False
                break
            if ok:
                return text
    return tag


def component_bool(value: Optional[Tag]) -> Optional[bool]:
    """``NbtOps.getBooleanValue`` для boolean-компонент."""
    if value is None:
        return None
    tt = value.tag_type
    if tt == TagType.Byte:
        return (value.byte_val or 0) != 0
    if tt == TagType.Short:
        return (value.short_val or 0) != 0
    if tt == TagType.Int:
        return (value.int_val or 0) != 0
    if tt == TagType.Long:
        return (value.long_val or 0) != 0
    if tt == TagType.Float:
        return float(value.float_val or 0.0) != 0.0
    if tt == TagType.Double:
        return float(value.double_val or 0.0) != 0.0
    return None


# -- типы, на которые ссылается item_data.rs --------------------------------

class FireworkShape(Enum):
    """``FireworkExplosion.Shape`` (firework.rs:6)."""

    SMALL_BALL = "small_ball"
    LARGE_BALL = "large_ball"
    STAR = "star"
    CREEPER = "creeper"
    BURST = "burst"

    @classmethod
    def from_name(cls, name: str) -> "FireworkShape":
        for member in cls:
            if member.value == name:
                return member
        return cls.SMALL_BALL

    def name_(self) -> str:
        return self.value


@dataclass
class FireworkExplosion:
    """``FireworkExplosion`` (firework.rs:54)."""

    shape: FireworkShape = FireworkShape.SMALL_BALL
    colors: List[int] = field(default_factory=list)
    fade: List[int] = field(default_factory=list)
    trail: bool = False
    twinkle: bool = False


@dataclass
class BannerLayer:
    """``BannerPatternLayers.Layer`` (banner_layer.rs:7)."""

    pattern: str
    color: str

    @classmethod
    def new(cls, pattern: str, color: str) -> "BannerLayer":
        return cls(pattern=pattern, color=color)


def layers_to_nbt(layers: List[BannerLayer]) -> Tag:
    return _t_list(
        _t_compound([
            ("pattern", _t_string(layer.pattern)),
            ("color", _t_string(layer.color)),
        ])
        for layer in layers
    )


def layers_from_nbt(tag: Optional[Tag]) -> List[BannerLayer]:
    if tag is None or tag.tag_type != TagType.List:
        return []
    out: List[BannerLayer] = []
    for entry in tag.list_val or []:
        pattern = _read_text(_get(entry, "pattern"))
        color = _read_text(_get(entry, "color"))
        if pattern is None or color is None:
            continue
        out.append(BannerLayer.new(_namespaced(pattern), color))
    return out


@dataclass
class WrittenBook:
    """``WrittenBookContent`` с текстовыми страницами (item_data.rs:225)."""

    title: str = ""
    author: str = ""
    generation: int = 0
    pages: List[str] = field(default_factory=list)
    page_tags: List[Tag] = field(default_factory=list)


@dataclass
class BundleSelected:
    """``BundleContents.selectedItem``: runtime, не сохраняется (item_data.rs:94)."""

    value: int = -1

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BundleSelected)

    def __hash__(self) -> int:
        return 0


@dataclass
class Wire:
    """Патч сервера, отправленный для стека (item_data.rs:76).

    Сравнение всегда истинно: как ``BundleContents.selectedItem`` патч не
    участвует в сравнении стеков.
    """

    decoded: Optional[ItemStack] = None
    patch: Optional[bytes] = None

    @classmethod
    def new(cls, decoded: ItemStack, patch: bytes) -> "Wire":
        return cls(decoded=decoded, patch=patch)

    def patch_bytes(self) -> Optional[bytes]:
        return self.patch

    def is_empty(self) -> bool:
        return self.decoded is None and self.patch is None

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0


#: Компоненты, которые ``components_tag`` пишет из смоделированных полей.
MODELLED: Tuple[str, ...] = (
    "minecraft:banner_patterns",
    "minecraft:base_color",
    "minecraft:bundle_contents",
    "minecraft:charged_projectiles",
    "minecraft:container",
    "minecraft:custom_name",
    "minecraft:damage",
    "minecraft:dyed_color",
    "minecraft:enchantments",
    "minecraft:firework_explosion",
    "minecraft:fireworks",
    "minecraft:map_id",
    "minecraft:map_post_processing",
    "minecraft:ominous_bottle_amplifier",
    "minecraft:pot_decorations",
    "minecraft:potion_contents",
    "minecraft:repair_cost",
    "minecraft:stored_enchantments",
    "minecraft:suspicious_stew_effects",
    "minecraft:trim",
    "minecraft:writable_book_content",
    "minecraft:written_book_content",
)

#: ``Raid.getBannerComponentPatch`` (item_data.rs:203).
OMINOUS_LAYERS: Tuple[Tuple[str, str], ...] = (
    ("rhombus", "cyan"),
    ("stripe_bottom", "light_gray"),
    ("stripe_center", "gray"),
    ("border", "light_gray"),
    ("stripe_middle", "black"),
    ("half_horizontal", "light_gray"),
    ("circle", "light_gray"),
    ("border", "black"),
)


def ominous_tooltip_display() -> Tag:
    return _t_compound([
        ("hidden_components", _t_list([_t_string("minecraft:banner_patterns")])),
    ])


@dataclass
class StackData:
    """``item_data::StackData`` — компоненты сверх ``count``/``damage``.

    Имена полей сохранены как в Rust. ``Arc<str>`` -> ``str``, ``Vec<T>`` ->
    ``list``, ``Option<T>`` -> ``Optional``.
    """

    enchantments: List[Tuple[str, int]] = field(default_factory=list)
    stored_enchantments: List[Tuple[str, int]] = field(default_factory=list)
    repair_cost: int = 0
    custom_name: Optional[Tag] = None
    potion: Optional[str] = None
    potion_extra: List[Tuple[str, Tag]] = field(default_factory=list)
    trim: Optional[Tuple[str, str]] = None
    container: List[Tuple[int, ItemStack]] = field(default_factory=list)
    charged: List[ItemStack] = field(default_factory=list)
    fireworks: Optional[Tuple[int, List[FireworkExplosion]]] = None
    map_id: Optional[int] = None
    writable_pages: List[str] = field(default_factory=list)
    written: Optional[WrittenBook] = None
    banner_patterns: List[BannerLayer] = field(default_factory=list)
    base_color: Optional[str] = None
    ominous_banner: bool = False
    ominous_amplifier: Optional[int] = None
    dyed_color: Optional[int] = None
    firework_explosion: Optional[FireworkExplosion] = None
    pot_decorations: Optional[List[Optional[ItemStack]]] = None
    bundle_contents: List[ItemStack] = field(default_factory=list)
    bundle_selected: BundleSelected = field(default_factory=BundleSelected)
    stew_effects: List[Tuple[str, int]] = field(default_factory=list)
    map_post_processing: Optional[int] = None
    other: List[Tuple[str, Tag]] = field(default_factory=list)
    wire: Wire = field(default_factory=Wire)

    # -- методы StackData (item_data.rs:130) --

    def custom_name_plain(self) -> Optional[str]:
        return _read_text(self.custom_name)

    def get_other(self, component_id_: str) -> Optional[Tag]:
        """``StackData::other``: значение сохранённого компонента.

        В Rust метод и поле называются одинаково (``other``); в Python поле
        ``other`` занимает имя, поэтому метод назван ``get_other``.
        """
        if component_id_ == "minecraft:custom_name":
            return self.custom_name
        for key, value in self.other:
            if key == component_id_:
                return value
        return None

    def set_other(self, component_id_: str, value: Optional[Tag]) -> None:
        self.other = [(k, v) for (k, v) in self.other if k != component_id_]
        if component_id_ == "minecraft:custom_name":
            if value is not None and _read_text(value) is not None:
                self.custom_name = _collapsed_text(value)
            else:
                self.custom_name = None
            return
        if value is not None:
            self.other.append((component_id_, value))
            self.other.sort(key=lambda kv: kv[0])

    def is_empty(self) -> bool:
        return self.wire.is_empty() and self == StackData()


def destroyed_container(stack: ItemStack) -> List[ItemStack]:
    """``BlockItem.onDestroyed`` (item_data.rs:243)."""
    data = stack.extra
    if not isinstance(data, StackData) or not data.container:
        return []
    held = list(data.container)
    data.container = []
    if data.is_empty():
        stack.extra = None
    held.sort(key=lambda kv: kv[0])
    return [s for _, s in held]


# -- чтение уровней зачарований (item_data.rs:490) ---------------------------

def read_levels(tag: Optional[Tag]) -> List[Tuple[str, int]]:
    if tag is None or tag.tag_type != TagType.Compound or tag.compound_val is None:
        return []
    mapping = tag.compound_val
    inner = mapping.get("levels")
    if inner is not None and inner.tag_type == TagType.Compound \
            and inner.compound_val is not None:
        mapping = inner.compound_val
    out: List[Tuple[str, int]] = []
    for key, value in mapping.items():
        level = _t_int_value(value)
        if level is None or not (1 <= level <= 255):
            continue
        out.append((_namespaced(key), level))
    return out


def levels_tag(levels: List[Tuple[str, int]]) -> Tag:
    return _t_compound((name, _t_int(level)) for name, level in levels)


def upgrade(levels: List[Tuple[str, int]], enchant_id: str, level: int) -> None:
    """``ItemEnchantments.Mutable.upgrade`` (item_data.rs:449)."""
    if level == 0:
        return
    for i, (name, current) in enumerate(levels):
        if name == enchant_id:
            levels[i] = (name, max(current, level))
            return
    levels.append((enchant_id, level))


def set_level(levels: List[Tuple[str, int]], enchant_id: str, level: int) -> None:
    """``ItemEnchantments.Mutable.set`` (item_data.rs:459)."""
    if level == 0:
        levels[:] = [(n, l) for (n, l) in levels if n != enchant_id]
        return
    for i, (name, _) in enumerate(levels):
        if name == enchant_id:
            levels[i] = (name, level)
            return
    levels.append((enchant_id, level))


# -- шаблон стека и ёлочные компоненты (item_data.rs:569-709) ----------------

def explosion_tag(e: FireworkExplosion) -> Tag:
    colors = lambda c: _t_list(_t_int(x) for x in c)
    fields: List[Tuple[str, Tag]] = [("shape", _t_string(e.shape.name_()))]
    if e.colors:
        fields.append(("colors", colors(e.colors)))
    if e.fade:
        fields.append(("fade_colors", colors(e.fade)))
    if e.trail:
        fields.append(("has_trail", _t_byte(1)))
    if e.twinkle:
        fields.append(("has_twinkle", _t_byte(1)))
    return _t_compound(fields)


def explosion_from(tag: Tag) -> FireworkExplosion:
    def ints(t: Optional[Tag]) -> List[int]:
        if t is None:
            return []
        if t.tag_type == TagType.IntArray:
            return list(t.intarray_val or [])
        if t.tag_type == TagType.List:
            return [v for v in (_t_int_value(x) for x in (t.list_val or [])) if v is not None]
        return []

    shape_name = _read_text(_get(tag, "shape"))
    if shape_name is None:
        shape_name = "small_ball"
    if shape_name.startswith("minecraft:"):
        shape_name = shape_name[len("minecraft:"):]
    trail = _t_int_value(_get(tag, "has_trail")) or 0
    twinkle = _t_int_value(_get(tag, "has_twinkle")) or 0
    return FireworkExplosion(
        shape=FireworkShape.from_name(shape_name),
        colors=ints(_get(tag, "colors")),
        fade=ints(_get(tag, "fade_colors")),
        trail=trail != 0,
        twinkle=twinkle != 0,
    )


def template_tag(stack: ItemStack) -> Tag:
    entries: List[Tuple[str, Tag]] = [("id", _t_string(stack.item))]
    if stack.count != 1:
        entries.append(("count", _t_int(stack.count)))
    components = encode_components(stack)
    if components is not None:
        entries.append(("components", components))
    return _t_compound(entries)


def all_bricks(sides: List[Optional[ItemStack]]) -> bool:
    for side in sides:
        if side is None:
            return False
        if not (side.item == "minecraft:brick" and side.count == 1 and side.extra is None):
            return False
    return True


def template_from(tag: Optional[Tag]) -> Optional[ItemStack]:
    if tag is None:
        return None
    if tag.tag_type == TagType.String:
        return ItemStack(str(tag.str_val or ""), 1)
    item_id = _read_text(_get(tag, "id"))
    if item_id is None:
        return None
    damage, extra = decode_components(_get(tag, "components"))
    count = _t_int_value(_get(tag, "count"))
    count = 1 if count is None else max(1, count)
    return ItemStack(item_id, count, damage=damage, extra=extra)


def canonical_other_component(component_id_: str, tag: Tag) -> Tag:
    """``MapDecorations.Entry.CODEC``: тип без ``:`` -> ``minecraft:`` (item_data.rs:720)."""
    if component_id_ != "minecraft:map_decorations":
        return tag
    if tag.tag_type != TagType.Compound or tag.compound_val is None:
        return tag
    for entry in tag.compound_val.values():
        if entry is None or entry.tag_type != TagType.Compound or entry.compound_val is None:
            continue
        kind = entry.compound_val.get("type")
        if kind is not None and kind.tag_type == TagType.String:
            text = kind.str_val or ""
            if text and ":" not in text:
                kind.str_val = _namespaced(text)
    return tag


def components_tag(damage: int, data: Optional[StackData]) -> Optional[Tag]:
    """``components_tag`` из damage и полей StackData (item_data.rs:775)."""
    entries: List[Tuple[str, Tag]] = []
    if damage > 0:
        entries.append(("minecraft:damage", _t_int(damage)))
    if isinstance(data, StackData):
        if data.enchantments:
            entries.append(("minecraft:enchantments", levels_tag(data.enchantments)))
        if data.stored_enchantments:
            entries.append(("minecraft:stored_enchantments", levels_tag(data.stored_enchantments)))
        if data.repair_cost > 0:
            entries.append(("minecraft:repair_cost", _t_int(data.repair_cost)))
        if data.custom_name is not None:
            entries.append(("minecraft:custom_name", data.custom_name))
        if data.potion is not None or data.potion_extra:
            potion: List[Tuple[str, Tag]] = []
            if data.potion is not None:
                potion.append(("potion", _t_string(data.potion)))
            potion.extend(data.potion_extra)
            entries.append(("minecraft:potion_contents", _t_compound(potion)))
        if data.trim is not None:
            material, pattern = data.trim
            entries.append((
                "minecraft:trim",
                _t_compound([
                    ("material", _t_string(material)),
                    ("pattern", _t_string(pattern)),
                ]),
            ))
        if data.map_id is not None:
            entries.append(("minecraft:map_id", _t_int(data.map_id)))
        if data.banner_patterns:
            entries.append(("minecraft:banner_patterns", layers_to_nbt(data.banner_patterns)))
        if data.base_color is not None:
            entries.append(("minecraft:base_color", _t_string(data.base_color)))
        if data.writable_pages:
            pages = [_t_compound([("raw", _t_string(p))]) for p in data.writable_pages]
            entries.append((
                "minecraft:writable_book_content",
                _t_compound([("pages", _t_list(pages))]),
            ))
        if data.written is not None:
            w = data.written
            if len(w.page_tags) == len(w.pages):
                pages = [_t_compound([("raw", t)]) for t in w.page_tags]
            else:
                pages = [_t_compound([("raw", _t_string(p))]) for p in w.pages]
            fields: List[Tuple[str, Tag]] = [
                ("title", _t_compound([("raw", _t_string(w.title))])),
                ("author", _t_string(w.author)),
            ]
            if w.pages:
                fields.append(("pages", _t_list(pages)))
            if w.generation != 0:
                fields.append(("generation", _t_int(w.generation)))
            entries.append(("minecraft:written_book_content", _t_compound(fields)))
        if data.fireworks is not None:
            flight, explosions = data.fireworks
            fields = []
            if flight != 0:
                fields.append(("flight_duration", _t_byte(flight)))
            if explosions:
                fields.append(("explosions", _t_list(explosion_tag(e) for e in explosions)))
            entries.append(("minecraft:fireworks", _t_compound(fields)))
        if data.firework_explosion is not None:
            entries.append((
                "minecraft:firework_explosion",
                explosion_tag(data.firework_explosion),
            ))
        if data.dyed_color is not None:
            entries.append(("minecraft:dyed_color", _t_int(data.dyed_color)))
        if data.pot_decorations is not None:
            sherds: List[Tuple[str, Tag]] = []
            for name, side in zip(("back", "left", "right", "front"), data.pot_decorations):
                if side is not None:
                    sherds.append((name, template_tag(side)))
            entries.append(("minecraft:pot_decorations", _t_compound(sherds)))
        if data.bundle_contents:
            entries.append((
                "minecraft:bundle_contents",
                _t_list(template_tag(s) for s in data.bundle_contents),
            ))
        if data.stew_effects:
            stew = []
            for effect_id, duration in data.stew_effects:
                e: List[Tuple[str, Tag]] = [("id", _t_string(effect_id))]
                if duration != 160:
                    e.append(("duration", _t_int(duration)))
                stew.append(_t_compound(e))
            entries.append(("minecraft:suspicious_stew_effects", _t_list(stew)))
        if data.charged:
            entries.append((
                "minecraft:charged_projectiles",
                _t_list(template_tag(s) for s in data.charged),
            ))
        if data.ominous_banner:
            def layer(pattern: str, color: str) -> Tag:
                return _t_compound([
                    ("pattern", _t_string(f"minecraft:{pattern}")),
                    ("color", _t_string(color)),
                ])
            entries.append((
                "minecraft:banner_patterns",
                _t_list(layer(p, c) for (p, c) in OMINOUS_LAYERS),
            ))
            if data.get_other("minecraft:tooltip_display") is None:
                entries.append(("minecraft:tooltip_display", ominous_tooltip_display()))
            entries.append((
                "minecraft:item_name",
                _t_compound([("translate", _t_string("block.minecraft.ominous_banner"))]),
            ))
            entries.append(("minecraft:rarity", _t_string("uncommon")))
        if data.ominous_amplifier is not None:
            entries.append((
                "minecraft:ominous_bottle_amplifier",
                _t_int(data.ominous_amplifier),
            ))
        if data.container:
            slots = [
                _t_compound([("slot", _t_int(slot)), ("item", template_tag(stack))])
                for slot, stack in data.container
            ]
            entries.append(("minecraft:container", _t_list(slots)))
    out: Dict[str, Tag] = {}
    for key, value in entries:
        out.setdefault(key, value)
    if isinstance(data, StackData):
        for key, value in data.other:
            out.setdefault(key, canonical_other_component(key, value))
    if not out:
        return None
    return _t_compound(out)


def _strip_none(entries) -> Dict[str, Tag]:
    out: Dict[str, Tag] = {}
    for key, value in entries:
        if value is not None:
            out[key] = value
    return out


def decode_components(components: Optional[Tag]) -> Tuple[int, Optional[StackData]]:
    """``decode_components`` (item_data.rs:984): damage и StackData из compound."""
    if components is None:
        return 0, None
    damage = max(0, _as_int(_get(components, "minecraft:damage"), 0))

    potion_tag = _get(components, "minecraft:potion_contents")
    potion: Optional[str] = None
    if potion_tag is not None and potion_tag.tag_type == TagType.String:
        potion = potion_tag.str_val or ""
    elif potion_tag is not None:
        potion = _read_text(_get(potion_tag, "potion"))
    potion_extra: List[Tuple[str, Tag]] = []
    if potion_tag is not None and potion_tag.tag_type == TagType.Compound \
            and potion_tag.compound_val is not None:
        for key, value in potion_tag.compound_val.items():
            if key != "potion":
                potion_extra.append((key, value))

    custom_name_tag = _get(components, "minecraft:custom_name")
    custom_name = None
    if custom_name_tag is not None and _read_text(custom_name_tag) is not None:
        custom_name = _collapsed_text(custom_name_tag)

    writable_pages: List[str] = []
    writable = _get(components, "minecraft:writable_book_content")
    if writable is not None:
        pages = _get(writable, "pages")
        if pages is not None and pages.tag_type == TagType.List:
            for p in pages.list_val or []:
                text = _filterable_text(p)
                if text is not None:
                    writable_pages.append(text)

    written: Optional[WrittenBook] = None
    written_tag = _get(components, "minecraft:written_book_content")
    if written_tag is not None:
        pages_tag = _get(written_tag, "pages")
        page_texts: List[str] = []
        page_tags: List[Tag] = []
        if pages_tag is not None and pages_tag.tag_type == TagType.List:
            for p in pages_tag.list_val or []:
                text = _filterable_text(p)
                if text is not None:
                    page_texts.append(text)
                raw = _get(p, "raw")
                page_tags.append(_plain_component(raw if raw is not None else p))
        generation = max(0, min(3, _t_int_value(_get(written_tag, "generation")) or 0))
        written = WrittenBook(
            title=_filterable_text(_get(written_tag, "title")) or "",
            author=_read_text(_get(written_tag, "author")) or "",
            generation=generation,
            pages=page_texts,
            page_tags=page_tags,
        )

    fireworks: Optional[Tuple[int, List[FireworkExplosion]]] = None
    fireworks_tag = _get(components, "minecraft:fireworks")
    if fireworks_tag is not None:
        flight = max(0, min(255, _t_int_value(_get(fireworks_tag, "flight_duration")) or 0))
        explosions: List[FireworkExplosion] = []
        expl_tag = _get(fireworks_tag, "explosions")
        if expl_tag is not None and expl_tag.tag_type == TagType.List:
            explosions = [explosion_from(e) for e in expl_tag.list_val or []]
        if not (flight == 1 and not explosions):
            fireworks = (flight, explosions)

    pot_decorations: Optional[List[Optional[ItemStack]]] = None
    pot_tag = _get(components, "minecraft:pot_decorations")
    if pot_tag is not None:
        sides = [
            template_from(_get(pot_tag, name))
            for name in ("back", "left", "right", "front")
        ]
        if not all_bricks(sides):
            pot_decorations = sides

    stew_effects: List[Tuple[str, int]] = []
    stew_tag = _get(components, "minecraft:suspicious_stew_effects")
    if stew_tag is not None and stew_tag.tag_type == TagType.List:
        for e in stew_tag.list_val or []:
            eid = _read_text(_get(e, "id"))
            if eid is None:
                continue
            duration = _t_int_value(_get(e, "duration"))
            stew_effects.append((eid, 160 if duration is None else duration))

    map_post: Optional[int] = None
    mpp = _get(components, "minecraft:map_post_processing")
    if mpp is not None and mpp.tag_type == TagType.String:
        map_post = 0 if (mpp.str_val or "") == "lock" else 1
    elif mpp is not None:
        v = _t_int_value(mpp)
        if v is not None:
            map_post = max(0, min(1, v))

    charged: List[ItemStack] = []
    charged_tag = _get(components, "minecraft:charged_projectiles")
    if charged_tag is not None and charged_tag.tag_type == TagType.List:
        for e in charged_tag.list_val or []:
            stack = item_from_nbt(e)
            if stack is not None:
                charged.append(stack)

    container: List[Tuple[int, ItemStack]] = []
    container_tag = _get(components, "minecraft:container")
    if container_tag is not None and container_tag.tag_type == TagType.List:
        for e in container_tag.list_val or []:
            slot = _t_int_value(_get(e, "slot"))
            stack = template_from(_get(e, "item"))
            if slot is None or stack is None:
                continue
            container.append((max(0, min(255, slot)), stack))

    item_name_translate = _read_text(_get(_get(components, "minecraft:item_name"), "translate"))
    banner_list = _get(components, "minecraft:banner_patterns")
    ominous_banner = (
        item_name_translate == "block.minecraft.ominous_banner"
        and banner_list is not None
        and banner_list.tag_type == TagType.List
        and len(banner_list.list_val or []) == len(OMINOUS_LAYERS)
    )

    trim: Optional[Tuple[str, str]] = None
    trim_tag = _get(components, "minecraft:trim")
    if trim_tag is not None:
        material = _read_text(_get(trim_tag, "material"))
        pattern = _read_text(_get(trim_tag, "pattern"))
        if material is not None and pattern is not None:
            trim = (material, pattern)

    def amp() -> Optional[int]:
        v = _t_int_value(_get(components, "minecraft:ominous_bottle_amplifier"))
        return None if v is None else max(0, min(4, v))

    bundle_contents: List[ItemStack] = []
    bundle_tag = _get(components, "minecraft:bundle_contents")
    if bundle_tag is not None and bundle_tag.tag_type == TagType.List:
        for e in bundle_tag.list_val or []:
            stack = item_from_nbt(e)
            if stack is not None:
                bundle_contents.append(stack)

    firework_explosion = None
    firework_tag = _get(components, "minecraft:firework_explosion")
    if firework_tag is not None:
        firework_explosion = explosion_from(firework_tag)

    data = StackData(
        enchantments=read_levels(_get(components, "minecraft:enchantments")),
        stored_enchantments=read_levels(_get(components, "minecraft:stored_enchantments")),
        repair_cost=max(0, _t_int_value(_get(components, "minecraft:repair_cost")) or 0),
        custom_name=custom_name,
        potion=potion,
        potion_extra=potion_extra,
        trim=trim,
        container=container,
        charged=charged,
        fireworks=fireworks,
        map_id=_t_int_value(_get(components, "minecraft:map_id")),
        writable_pages=writable_pages,
        written=written,
        banner_patterns=layers_from_nbt(_get(components, "minecraft:banner_patterns")),
        base_color=_read_text(_get(components, "minecraft:base_color")),
        ominous_banner=ominous_banner,
        ominous_amplifier=amp(),
        dyed_color=_t_int_value(_get(components, "minecraft:dyed_color")),
        firework_explosion=firework_explosion,
        pot_decorations=pot_decorations,
        bundle_contents=bundle_contents,
        stew_effects=stew_effects,
        map_post_processing=map_post,
    )

    if components.tag_type == TagType.Compound and components.compound_val is not None:
        for key, value in components.compound_val.items():
            ominous_part = data.ominous_banner and (
                key in ("minecraft:item_name", "minecraft:rarity")
                or (key == "minecraft:tooltip_display" and value == ominous_tooltip_display())
            )
            if key not in MODELLED and not ominous_part:
                data.other.append((key, canonical_other_component(key, value)))
        data.other.sort(key=lambda kv: kv[0])

    if data.is_empty():
        return damage, None
    return damage, data


def item_from_nbt(tag: Optional[Tag]) -> Optional[ItemStack]:
    """``item_nbt::item_from_nbt`` в объёме ``{id,count,components}``."""
    if tag is None:
        return None
    if tag.tag_type == TagType.String:
        return ItemStack(str(tag.str_val or ""), 1)
    item_id = _read_text(_get(tag, "id"))
    if item_id is None:
        return None
    damage, extra = decode_components(_get(tag, "components"))
    count = _t_int_value(_get(tag, "count"))
    count = 1 if count is None else count
    return ItemStack(item_id, count, damage=damage, extra=extra)


def encode_components(stack: ItemStack) -> Optional[Tag]:
    """``encode_components`` (item_data.rs:741)."""
    data = stack.extra if isinstance(stack.extra, StackData) else None
    components = components_tag(stack.damage, data)
    if components is None:
        return None
    mapping = components.compound_val or {}
    # LodestoneTracker.CODEC: tracked=true по умолчанию не сохраняется.
    tracker = mapping.get("minecraft:lodestone_tracker")
    if tracker is not None and tracker.compound_val is not None:
        if tracker.compound_val.get("tracked") == _t_byte(1):
            del tracker.compound_val["tracked"]
    if stack.item == "minecraft:filled_map":
        entries = mapping.get("minecraft:map_decorations")
        if entries is not None and entries.tag_type == TagType.Compound \
                and not (entries.compound_val or {}):
            del mapping["minecraft:map_decorations"]
            if not mapping:
                return None
    if stack.item in ("minecraft:beehive", "minecraft:bee_nest"):
        block_state = mapping.get("minecraft:block_state")
        if block_state is not None and block_state.tag_type == TagType.Compound \
                and block_state.compound_val is not None \
                and len(block_state.compound_val) == 1:
            level = block_state.compound_val.get("honey_level")
            if level is not None and level.tag_type == TagType.String \
                    and (level.str_val or "") == "0":
                del mapping["minecraft:block_state"]
                if not mapping:
                    return None
    return components


# ---------------------------------------------------------------------------
# Провод (horizon-protocol/src/item.rs, item/skip.rs)
# ---------------------------------------------------------------------------

MAX_NESTING: int = 64
_NESTING: List[int] = [0]


class _Nested:
    """Один уровень ``MAX_NESTING`` на время жизни (item.rs:33)."""

    def __enter__(self) -> "_Nested":
        if _NESTING[0] >= MAX_NESTING:
            raise ProtocolError("[QuadRix] item data nested too deeply")
        _NESTING[0] += 1
        return self

    def __exit__(self, *exc: object) -> None:
        _NESTING[0] -= 1


# -- варианты Component (item.rs:132) ----------------------------------------

class Component:
    """Базовый класс значения компоненты (Rust ``enum Component``)."""


@dataclass(frozen=True)
class ComponentInt(Component):
    value: int


@dataclass(frozen=True)
class ComponentUnit(Component):
    pass


@dataclass(frozen=True)
class ComponentBool(Component):
    value: bool


@dataclass(frozen=True)
class ComponentText(Component):
    tag: Tag


@dataclass(frozen=True)
class ComponentNbt(Component):
    tag: Tag


@dataclass(frozen=True)
class ComponentIdent(Component):
    value: str


@dataclass(frozen=True)
class ComponentLore(Component):
    lines: List[Tag]


@dataclass(frozen=True)
class ComponentEnchantments(Component):
    levels: List[Tuple[int, int]]


@dataclass(frozen=True)
class ComponentAttackRange(Component):
    values: List[float]


@dataclass(frozen=True)
class ComponentPotion(Component):
    potion: Optional[int]
    color: Optional[int]
    rest: bytes


@dataclass(frozen=True)
class WireSkinPatch:
    body: Optional[str] = None
    cape: Optional[str] = None
    elytra: Optional[str] = None
    slim: Optional[bool] = None


@dataclass(frozen=True)
class WireProfile:
    name: Optional[str]
    id: Optional[int]
    properties: List[Tuple[str, str, Optional[str]]]
    skin: WireSkinPatch


@dataclass(frozen=True)
class ComponentProfile(Component):
    profile: WireProfile


@dataclass(frozen=True)
class ComponentCustomModelData(Component):
    floats: List[float]
    flags: List[bool]
    strings: List[str]
    colors: List[int]


@dataclass(frozen=True)
class ComponentTooltipDisplay(Component):
    hide: bool
    hidden: List[int]


@dataclass(frozen=True)
class ComponentWritableBook(Component):
    pages: List[str]
    filtered: List[Optional[str]]


@dataclass(frozen=True)
class WireWrittenBook:
    title: str = ""
    title_filtered: Optional[str] = None
    author: str = ""
    generation: int = 0
    pages: List[Tag] = field(default_factory=list)
    pages_filtered: List[Optional[Tag]] = field(default_factory=list)
    resolved: bool = False


@dataclass(frozen=True)
class ComponentWrittenBook(Component):
    book: WireWrittenBook


@dataclass(frozen=True)
class ComponentStacks(Component):
    stacks: List["Stack"]


@dataclass(frozen=True)
class WireFireworkExplosion:
    shape: int
    colors: List[int]
    fade: List[int]
    trail: bool
    twinkle: bool


@dataclass(frozen=True)
class ComponentFireworks(Component):
    flight: int
    explosions: List[WireFireworkExplosion]


@dataclass(frozen=True)
class ComponentFireworkExplosion(Component):
    explosion: WireFireworkExplosion


@dataclass(frozen=True)
class ComponentLodestoneTracker(Component):
    target: Optional[Tuple[str, Tuple[int, int, int]]]
    tracked: bool


@dataclass(frozen=True)
class ComponentTrim(Component):
    material: int
    pattern: int


@dataclass(frozen=True)
class ComponentStewEffects(Component):
    effects: List[Tuple[int, int]]


@dataclass(frozen=True)
class ComponentInstrument(Component):
    value: int


@dataclass(frozen=True)
class ComponentBannerPatterns(Component):
    layers: List[Tuple[int, int]]


@dataclass(frozen=True)
class ComponentPaintingVariant(Component):
    value: int


@dataclass(frozen=True)
class ComponentRaw(Component):
    data: bytes


# -- чтение типизированных компонент (item.rs:306) ---------------------------

def _read_filterable(r: Reader, read_value):
    raw = read_value(r)
    filtered = read_value(r) if r.bool() else None
    return raw, filtered


def _filtered_variants(pages: List[Tuple[object, Optional[object]]]):
    any_filtered = any(f is not None for _, f in pages)
    raw = [v for v, _ in pages]
    filtered = [f for _, f in pages]
    return raw, (filtered if any_filtered else [])


def _read_firework_explosion(r: Reader) -> WireFireworkExplosion:
    def ints(rr: Reader) -> List[int]:
        n = rr.count(1024)
        return [rr.i32() for _ in range(n)]

    return WireFireworkExplosion(
        shape=r.varint(),
        colors=ints(r),
        fade=ints(r),
        trail=r.bool(),
        twinkle=r.bool(),
    )


def _write_firework_explosion(e: WireFireworkExplosion, w: Writer) -> None:
    w.varint(e.shape)
    w.varint(len(e.colors))
    for c in e.colors:
        w.i32(c)
    w.varint(len(e.fade))
    for c in e.fade:
        w.i32(c)
    w.bool(e.trail)
    w.bool(e.twinkle)


def _read_skin_patch(r: Reader) -> WireSkinPatch:
    def texture(rr: Reader) -> Optional[str]:
        return rr.string(32767) if rr.bool() else None

    body = texture(r)
    cape = texture(r)
    elytra = texture(r)
    slim = r.bool() if r.bool() else None
    return WireSkinPatch(body=body, cape=cape, elytra=elytra, slim=slim)


def _write_skin_patch(skin: WireSkinPatch, w: Writer) -> None:
    for texture in (skin.body, skin.cape, skin.elytra):
        w.bool(texture is not None)
        if texture is not None:
            w.string(texture)
    w.bool(skin.slim is not None)
    if skin.slim is not None:
        w.bool(skin.slim)


def _read_profile(r: Reader) -> WireProfile:
    def properties(rr: Reader):
        n = rr.count(1024)
        out = []
        for _ in range(n):
            name = rr.string(32767)
            value = rr.string(32767)
            signature = rr.string(32767) if rr.bool() else None
            out.append((name, value, signature))
        return out

    if r.u8() == 0:
        name = r.string(64) if r.bool() else None
        ident = r.uuid() if r.bool() else None
    else:
        ident = r.uuid()
        name = r.string(64)
    return WireProfile(
        name=name,
        id=ident,
        properties=properties(r),
        skin=_read_skin_patch(r),
    )


def _write_profile(p: WireProfile, w: Writer) -> None:
    w.u8(0)
    w.bool(p.name is not None)
    if p.name is not None:
        w.string(p.name)
    w.bool(p.id is not None)
    if p.id is not None:
        w.uuid(p.id)
    w.varint(len(p.properties))
    for name, value, signature in p.properties:
        w.string(name)
        w.string(value)
        w.bool(signature is not None)
        if signature is not None:
            w.string(signature)
    _write_skin_patch(p.skin, w)


def _read_component_written_book(r: Reader) -> WireWrittenBook:
    title, title_filtered = _read_filterable(r, lambda rr: rr.string(32))
    author = r.string(32767)
    generation = r.varint()
    n = r.count(r.remaining())
    pages = [_read_filterable(r, lambda rr: rr.nbt()) for _ in range(n)]
    page_tags, pages_filtered = _filtered_variants(pages)
    return WireWrittenBook(
        title=title,
        title_filtered=title_filtered,
        author=author,
        generation=generation,
        pages=page_tags,
        pages_filtered=pages_filtered,
        resolved=r.bool(),
    )


def _write_component_written_book(b: WireWrittenBook, w: Writer) -> None:
    w.string(b.title)
    if b.title_filtered is not None:
        w.bool(True)
        w.string(b.title_filtered)
    else:
        w.bool(False)
    w.string(b.author)
    w.varint(b.generation)
    w.varint(len(b.pages))
    for i, page in enumerate(b.pages):
        w.nbt(page)
        filtered = b.pages_filtered[i] if i < len(b.pages_filtered) else None
        if filtered is not None:
            w.bool(True)
            w.nbt(filtered)
        else:
            w.bool(False)
    w.bool(b.resolved)


def read_component(kind: int, r: Reader) -> Component:
    """``Component::read`` (item.rs:307) в приколотом к 26.3 виде."""
    name = COMPONENT_NAMES.get(kind)

    if name in {
        "minecraft:max_stack_size", "minecraft:max_damage", "minecraft:damage",
        "minecraft:rarity", "minecraft:repair_cost", "minecraft:map_id",
        "minecraft:map_post_processing", "minecraft:ominous_bottle_amplifier",
        "minecraft:base_color",
    }:
        return ComponentInt(r.varint())
    if name == "minecraft:writable_book_content":
        n = r.count(100)
        pages = [_read_filterable(r, lambda rr: rr.string(1024)) for _ in range(n)]
        raw, filtered = _filtered_variants(pages)
        return ComponentWritableBook(pages=raw, filtered=filtered)
    if name == "minecraft:written_book_content":
        return ComponentWrittenBook(_read_component_written_book(r))
    if name in ("minecraft:charged_projectiles", "minecraft:bundle_contents"):
        n = r.count(1024)
        return ComponentStacks(stacks=[Template.read(r) for _ in range(n)])
    if name == "minecraft:dyed_color":
        return ComponentInt(r.i32())
    if name in ("minecraft:unbreakable", "minecraft:creative_slot_lock"):
        return ComponentUnit()
    if name == "minecraft:enchantment_glint_override":
        return ComponentBool(r.bool())
    if name in ("minecraft:custom_name", "minecraft:item_name"):
        return ComponentText(r.nbt())
    if name == "minecraft:custom_data":
        return ComponentNbt(r.nbt())
    if name == "minecraft:item_model":
        return ComponentIdent(r.string(32767))
    if name == "minecraft:lore":
        n = r.count(256)
        return ComponentLore(lines=[r.nbt() for _ in range(n)])
    if name == "minecraft:suspicious_stew_effects":
        n = r.count(r.remaining())
        return ComponentStewEffects(effects=[(r.varint(), r.varint()) for _ in range(n)])
    if name in ("minecraft:enchantments", "minecraft:stored_enchantments"):
        n = r.count(r.remaining())
        return ComponentEnchantments(levels=[(r.varint(), r.varint()) for _ in range(n)])
    if name == "minecraft:potion_contents":
        potion = r.varint() if r.bool() else None
        color = r.i32() if r.bool() else None
        start = r.position()
        _skip_potion_effects_and_name(r)
        tail = r.since(start)
        rest = b"" if tail == b"\x00\x00" else bytes(tail)
        return ComponentPotion(potion=potion, color=color, rest=rest)
    if name == "minecraft:attack_range":
        return ComponentAttackRange(values=[r.f32() for _ in range(6)])
    if name == "minecraft:profile":
        return ComponentProfile(_read_profile(r))
    if name == "minecraft:custom_model_data":
        n = r.count(r.remaining())
        floats = [r.f32() for _ in range(n)]
        n = r.count(r.remaining())
        flags = [r.bool() for _ in range(n)]
        n = r.count(r.remaining())
        strings = [r.string(32767) for _ in range(n)]
        n = r.count(r.remaining())
        colors = [r.i32() for _ in range(n)]
        return ComponentCustomModelData(
            floats=floats, flags=flags, strings=strings, colors=colors
        )
    if name == "minecraft:tooltip_display":
        hide = r.bool()
        n = r.count(r.remaining())
        hidden = [r.varint() for _ in range(n)]
        return ComponentTooltipDisplay(hide=hide, hidden=hidden)
    if name == "minecraft:fireworks":
        flight = r.varint()
        n = r.count(256)
        return ComponentFireworks(
            flight=flight,
            explosions=[_read_firework_explosion(r) for _ in range(n)],
        )
    if name == "minecraft:firework_explosion":
        return ComponentFireworkExplosion(_read_firework_explosion(r))
    if name == "minecraft:lodestone_tracker":
        if r.bool():
            dimension = r.string(32767)
            target = (dimension, unpack_block_pos(r.i64()))
        else:
            target = None
        return ComponentLodestoneTracker(target=target, tracked=r.bool())
    if name == "minecraft:trim":
        start = r.position()
        _skip_component(kind, r)
        raw = bytes(r.since(start))
        ids = Reader(raw)
        try:
            material = ids.varint()
            pattern = ids.varint()
        except ProtocolError:
            return ComponentRaw(data=raw)
        if material >= 1 and pattern >= 1 and ids.remaining() == 0:
            return ComponentTrim(material=material - 1, pattern=pattern - 1)
        return ComponentRaw(data=raw)
    if name == "minecraft:instrument":
        start = r.position()
        _skip_component(kind, r)
        raw = bytes(r.since(start))
        ids = Reader(raw)
        try:
            value = ids.varint()
        except ProtocolError:
            return ComponentRaw(data=raw)
        if value >= 1 and ids.remaining() == 0:
            return ComponentInstrument(value - 1)
        return ComponentRaw(data=raw)
    if name == "minecraft:painting_variant":
        start = r.position()
        _skip_component(kind, r)
        raw = bytes(r.since(start))
        ids = Reader(raw)
        try:
            value = ids.varint()
        except ProtocolError:
            return ComponentRaw(data=raw)
        if value >= 1 and ids.remaining() == 0:
            return ComponentPaintingVariant(value - 1)
        return ComponentRaw(data=raw)
    if name == "minecraft:banner_patterns":
        start = r.position()
        _skip_component(kind, r)
        raw = bytes(r.since(start))
        layers = _banner_layers(raw)
        if layers is not None:
            return ComponentBannerPatterns(layers=layers)
        return ComponentRaw(data=raw)

    start = r.position()
    _skip_component(kind, r)
    return ComponentRaw(data=bytes(r.since(start)))


def _banner_layers(raw: bytes) -> Optional[List[Tuple[int, int]]]:
    ids = Reader(raw)
    try:
        n = ids.count(ids.remaining())
        layers: List[Tuple[int, int]] = []
        for _ in range(n):
            pattern = ids.varint()
            color = ids.varint()
            if pattern < 1:
                return None
            layers.append((pattern - 1, color))
    except ProtocolError:
        return None
    return layers if ids.remaining() == 0 else None


def write_component(kind: int, comp: Component, w: Writer) -> None:
    """``Component::write`` (item.rs:563)."""
    if isinstance(comp, ComponentRaw):
        w.bytes(comp.data)
        return
    if isinstance(comp, ComponentBannerPatterns):
        w.varint(len(comp.layers))
        for pattern, color in comp.layers:
            w.varint(pattern + 1)
            w.varint(color)
        return
    if isinstance(comp, ComponentTrim):
        w.varint(comp.material + 1)
        w.varint(comp.pattern + 1)
        return
    if isinstance(comp, ComponentInstrument):
        w.varint(comp.value + 1)
        return
    if isinstance(comp, ComponentPaintingVariant):
        w.varint(comp.value + 1)
        return
    if isinstance(comp, ComponentInt):
        if kind == component_id("minecraft:dyed_color"):
            w.i32(comp.value)
        else:
            w.varint(comp.value)
        return
    if isinstance(comp, ComponentUnit):
        return
    if isinstance(comp, ComponentBool):
        w.bool(comp.value)
        return
    if isinstance(comp, (ComponentText, ComponentNbt)):
        w.nbt(comp.tag)
        return
    if isinstance(comp, ComponentIdent):
        w.string(comp.value)
        return
    if isinstance(comp, ComponentLore):
        w.varint(len(comp.lines))
        for line in comp.lines:
            w.nbt(line)
        return
    if isinstance(comp, (ComponentEnchantments, ComponentStewEffects)):
        items = comp.levels if isinstance(comp, ComponentEnchantments) else comp.effects
        w.varint(len(items))
        for e, level in items:
            w.varint(e)
            w.varint(level)
        return
    if isinstance(comp, ComponentAttackRange):
        for v in comp.values:
            w.f32(v)
        return
    if isinstance(comp, ComponentPotion):
        w.bool(comp.potion is not None)
        if comp.potion is not None:
            w.varint(comp.potion)
        w.bool(comp.color is not None)
        if comp.color is not None:
            w.i32(comp.color)
        if not comp.rest:
            w.varint(0)
            w.bool(False)
        else:
            w.bytes(comp.rest)
        return
    if isinstance(comp, ComponentProfile):
        _write_profile(comp.profile, w)
        return
    if isinstance(comp, ComponentCustomModelData):
        w.varint(len(comp.floats))
        for f in comp.floats:
            w.f32(f)
        w.varint(len(comp.flags))
        for f in comp.flags:
            w.bool(f)
        w.varint(len(comp.strings))
        for s in comp.strings:
            w.string(s)
        w.varint(len(comp.colors))
        for c in comp.colors:
            w.i32(c)
        return
    if isinstance(comp, ComponentTooltipDisplay):
        w.bool(comp.hide)
        w.varint(len(comp.hidden))
        for h in comp.hidden:
            w.varint(h)
        return
    if isinstance(comp, ComponentStacks):
        w.varint(len(comp.stacks))
        for s in comp.stacks:
            Template.write(s, w)
        return
    if isinstance(comp, ComponentFireworks):
        w.varint(comp.flight)
        w.varint(len(comp.explosions))
        for e in comp.explosions:
            _write_firework_explosion(e, w)
        return
    if isinstance(comp, ComponentFireworkExplosion):
        _write_firework_explosion(comp.explosion, w)
        return
    if isinstance(comp, ComponentLodestoneTracker):
        w.bool(comp.target is not None)
        if comp.target is not None:
            dimension, pos = comp.target
            w.string(dimension)
            w.i64(pack_block_pos(pos))
        w.bool(comp.tracked)
        return
    if isinstance(comp, ComponentWritableBook):
        w.varint(len(comp.pages))
        for i, page in enumerate(comp.pages):
            w.string(page)
            filtered = comp.filtered[i] if i < len(comp.filtered) else None
            if filtered is not None:
                w.bool(True)
                w.string(filtered)
            else:
                w.bool(False)
        return
    if isinstance(comp, ComponentWrittenBook):
        _write_component_written_book(comp.book, w)
        return
    raise ProtocolError(f"[QuadRix] cannot write component {kind}")


# -- чтение мимо непонятых компонент (item/skip.rs) --------------------------

def _skip_string(r: Reader) -> None:
    r.string(32767)


def _skip_ident(r: Reader) -> None:
    r.string(32767)


def _skip_i32(r: Reader) -> None:
    r.i32()


def _skip_f32(r: Reader) -> None:
    r.f32()


def _skip_bool(r: Reader) -> None:
    r.bool()


def _skip_nbt(r: Reader) -> None:
    r.nbt()


def _skip_optional(r: Reader, value) -> None:
    if r.bool():
        value(r)


def _skip_list(r: Reader, element) -> None:
    n = r.count(r.remaining())
    for _ in range(n):
        element(r)


def _skip_holder(r: Reader, direct) -> None:
    if r.varint() == 0:
        direct(r)


def _skip_holder_set(r: Reader) -> None:
    first = r.varint()
    if first == 0:
        _skip_ident(r)
        return
    n = first - 1
    if n > r.remaining():
        raise ProtocolError("[QuadRix] holder set past the end")
    for _ in range(n):
        r.varint()


def _skip_sound(r: Reader) -> None:
    def direct(rr: Reader) -> None:
        _skip_ident(rr)
        _skip_optional(rr, _skip_f32)

    _skip_holder(r, direct)


def _skip_resolvable(r: Reader, constant) -> None:
    if r.bool():
        constant(r)
    else:
        _skip_ident(r)


def _skip_trim_material(r: Reader) -> None:
    def direct(rr: Reader) -> None:
        _skip_ident(rr)
        r.nbt()

    _skip_holder(r, direct)


def _skip_trim_pattern(r: Reader) -> None:
    _skip_ident(r)
    r.nbt()
    r.bool()


def _skip_instrument_direct(r: Reader) -> None:
    _skip_sound(r)
    r.f32()
    r.f32()
    r.varint()
    r.nbt()


def _skip_jukebox(r: Reader) -> None:
    _skip_sound(r)
    r.nbt()
    r.f32()
    r.varint()


def _skip_global_pos(r: Reader) -> None:
    _skip_ident(r)
    r.i64()


def _skip_firework_explosion(r: Reader) -> None:
    r.varint()
    _skip_list(r, _skip_i32)
    _skip_list(r, _skip_i32)
    r.bool()
    r.bool()


def _skip_banner_layer(r: Reader) -> None:
    def direct(rr: Reader) -> None:
        _skip_ident(rr)
        _skip_string(rr)

    _skip_holder(r, direct)
    r.varint()


def _skip_template(r: Reader) -> None:
    Template.read(r)


def _skip_string_pair(r: Reader) -> None:
    _skip_string(r)
    _skip_string(r)


def _skip_bee(r: Reader) -> None:
    r.varint()
    r.nbt()
    r.varint()
    r.varint()


def _skip_painting(r: Reader) -> None:
    r.varint()
    r.varint()
    _skip_ident(r)
    _skip_optional(r, _skip_nbt)
    _skip_optional(r, _skip_nbt)


def _skip_four_nbt(r: Reader) -> None:
    for _ in range(4):
        r.nbt()


def _skip_attribute_modifier(r: Reader) -> None:
    r.varint()
    _skip_ident(r)
    r.f64()
    r.varint()
    r.varint()
    display = r.varint()
    if display in (0, 1):
        return
    if display == 2:
        r.nbt()
        return
    raise ProtocolError(f"[QuadRix] unknown attribute modifier display {display}")


def _skip_tool(r: Reader) -> None:
    def rule(rr: Reader) -> None:
        _skip_holder_set(rr)
        _skip_optional(rr, _skip_f32)
        _skip_optional(rr, _skip_bool)

    _skip_list(r, rule)
    r.f32()
    r.varint()
    r.bool()


def _skip_equippable(r: Reader) -> None:
    r.varint()
    _skip_sound(r)
    _skip_optional(r, _skip_ident)
    _skip_optional(r, _skip_ident)
    _skip_optional(r, _skip_holder_set)
    for _ in range(5):
        r.bool()
    _skip_sound(r)


def _skip_blocks_attacks(r: Reader) -> None:
    r.f32()
    r.f32()

    def reduction(rr: Reader) -> None:
        rr.f32()
        _skip_optional(rr, _skip_holder_set)
        rr.f32()
        rr.f32()

    _skip_list(r, reduction)
    for _ in range(3):
        r.f32()
    _skip_optional(r, _skip_holder_set)
    _skip_optional(r, _skip_sound)
    _skip_optional(r, _skip_sound)


def _skip_kinetic_weapon(r: Reader) -> None:
    r.varint()
    r.varint()

    def condition(rr: Reader) -> None:
        rr.varint()
        rr.f32()
        rr.f32()

    for _ in range(3):
        _skip_optional(r, condition)
    r.f32()
    r.f32()
    _skip_optional(r, _skip_sound)
    _skip_optional(r, _skip_sound)


def _skip_mob_effect(r: Reader) -> None:
    r.varint()
    _skip_effect_details(r)


def _skip_effect_details(r: Reader) -> None:
    with _Nested():
        r.varint()
        r.varint()
        r.bool()
        r.bool()
        r.bool()
        _skip_optional(r, _skip_effect_details)


def _skip_consume_effect(r: Reader) -> None:
    kind = r.varint()
    if kind == 0:
        _skip_list(r, _skip_mob_effect)
        r.f32()
    elif kind == 1:
        _skip_holder_set(r)
    elif kind == 2:
        return
    elif kind == 3:
        r.f32()
        r.bool()
    elif kind == 4:
        _skip_sound(r)
    else:
        raise ProtocolError(f"[QuadRix] unknown consume effect type {kind}")


def _skip_block_predicate(r: Reader) -> None:
    _skip_optional(r, _skip_holder_set)

    def property_matcher(rr: Reader) -> None:
        _skip_string(rr)
        if rr.bool():
            _skip_string(rr)
        else:
            _skip_optional(rr, _skip_string)
            _skip_optional(rr, _skip_string)

    _skip_optional(r, lambda rr: _skip_list(rr, property_matcher))
    _skip_optional(r, _skip_nbt)

    def typed_component(rr: Reader) -> None:
        kind = rr.varint()
        read_component(kind, rr)

    _skip_list(r, typed_component)

    def predicate(rr: Reader) -> None:
        rr.bool()
        rr.varint()
        rr.nbt()

    _skip_list(r, predicate)


def _skip_potion_effects_and_name(r: Reader) -> None:
    _skip_list(r, _skip_mob_effect)
    _skip_optional(r, _skip_string)


def _skip_component(kind: int, r: Reader) -> None:
    """``skip::component`` (item/skip.rs:17)."""
    if kind in (34, 120):
        return
    if kind in (22, 49, 59, 68, 81, 82):
        r.nbt()
        return
    if kind in (8, 31, 42, 43, 44, 46, 65, 75) or 88 <= kind <= 108 \
            or 110 <= kind <= 117 or kind == 121:
        r.varint()
        return
    if kind in (7, 54):
        r.f32()
        return
    if kind in (35, 73):
        _skip_ident(r)
        return
    if kind == 5:
        r.bool()
        r.bool()
        r.f32()
        return
    if kind in (14, 15):
        _skip_list(r, _skip_block_predicate)
        return
    if kind == 16:
        _skip_list(r, _skip_attribute_modifier)
        return
    if kind == 23:
        r.varint()
        r.f32()
        r.bool()
        return
    if kind == 24:
        r.f32()
        r.varint()
        _skip_sound(r)
        r.bool()
        _skip_list(r, _skip_consume_effect)
        return
    if kind in (25, 80):
        _skip_template(r)
        return
    if kind == 26:
        r.f32()
        _skip_optional(r, _skip_ident)
        return
    if kind in (27, 33, 67):
        _skip_holder_set(r)
        return
    if kind == 28:
        _skip_tool(r)
        return
    if kind == 29:
        r.varint()
        r.f32()
        return
    if kind == 32:
        _skip_equippable(r)
        return
    if kind == 36:
        _skip_list(r, _skip_consume_effect)
        return
    if kind == 37:
        _skip_blocks_attacks(r)
        return
    if kind == 38:
        r.bool()
        r.bool()
        _skip_optional(r, _skip_sound)
        _skip_optional(r, _skip_sound)
        return
    if kind == 39:
        _skip_kinetic_weapon(r)
        return
    if kind in (40, 41):
        r.varint()
        r.varint()
        return
    if kind == 52:
        _skip_list(r, _skip_template)
        return
    if kind == 55:
        _skip_list(r, lambda rr: (rr.varint(), rr.varint()))
        return
    if kind == 58:
        _skip_trim_material(r)
        _skip_holder(r, _skip_trim_pattern)
        return
    if kind in (60, 62):
        r.varint()
        r.nbt()
        return
    if kind == 61:
        r.nbt()
        return
    if kind == 63:
        _skip_holder(r, _skip_instrument_direct)
        return
    if kind == 64:
        _skip_trim_material(r)
        return
    if kind == 66:
        _skip_holder(r, _skip_jukebox)
        return
    if kind == 69:
        _skip_optional(r, _skip_global_pos)
        r.bool()
        return
    if kind == 70:
        _skip_firework_explosion(r)
        return
    if kind == 71:
        r.varint()
        _skip_list(r, _skip_firework_explosion)
        return
    if kind == 74:
        _skip_list(r, _skip_banner_layer)
        return
    if kind == 76:
        for _ in range(4):
            _skip_optional(r, _skip_template)
        return
    if kind == 77:
        _skip_list(r, lambda rr: _skip_optional(rr, _skip_template))
        return
    if kind == 78:
        _skip_list(r, _skip_string_pair)
        return
    if kind == 79:
        _skip_list(r, _skip_bee)
        return
    if kind == 83:
        _skip_sound(r)
        return
    if kind == 84:
        _skip_resolvable(r, _skip_i32)
        return
    if kind in (85, 86):
        _skip_resolvable(r, _skip_i32)
        _skip_resolvable(r, _skip_f32)
        return
    if kind == 87:
        _skip_holder_set(r)
        r.f32()
        return
    if kind == 109:
        _skip_holder(r, _skip_painting)
        return
    if kind in (118, 119):
        for _ in range(4):
            r.nbt()
        def four(rr: Reader) -> None:
            for _ in range(4):
                rr.nbt()

        _skip_optional(r, four)
        r.varint()
        r.bool()
        return
    raise ProtocolError(f"[QuadRix] unsupported item component {kind}")


# -- Stack / Slot / DelimitedSlot / Template (item.rs:946-1130) --------------

@dataclass
class Stack:
    """Ненулевой стек (item.rs:948). ``wire`` не участвует в сравнении."""

    item: int
    count: int
    added: List[Tuple[int, Component]] = field(default_factory=list)
    removed: List[int] = field(default_factory=list)
    wire: Optional[bytes] = field(default=None, compare=False)

    @classmethod
    def new(cls, item: int, count: int) -> "Stack":
        return cls(item=item, count=count)

    def component(self, kind: int) -> Optional[Component]:
        for k, comp in self.added:
            if k == kind:
                return comp
        return None

    def damage(self) -> int:
        comp = self.component(component_id("minecraft:damage") or 3)
        if isinstance(comp, ComponentInt):
            return comp.value
        return 0


def _read_added(raw: int, r: Reader) -> Tuple[int, Component, bytes]:
    with _Nested():
        start = r.position()
        comp = read_component(raw, r)
        return raw, comp, bytes(r.since(start))


def _read_removed(r: Reader, negative: int) -> List[int]:
    return [r.varint() for _ in range(negative)]


def _read_patch(r: Reader, delimited: bool):
    positive = r.count(65536)
    negative = r.count(65536)
    added: List[Tuple[int, Component]] = []
    for _ in range(positive):
        raw = r.varint()
        if delimited:
            length = r.count(r.remaining())
            sub = Reader(r.bytes(length))
            kind, comp, _ = _read_added(raw, sub)
        else:
            kind, comp, _ = _read_added(raw, r)
        added.append((kind, comp))
    removed = _read_removed(r, negative)
    return added, removed


def _write_patch(added, removed, w: Writer, delimited: bool) -> None:
    w.varint(len(added))
    w.varint(len(removed))
    for kind, comp in added:
        w.varint(kind)
        if delimited:
            value = Writer()
            write_component(kind, comp, value)
            w.byte_array(bytes(value.data))
        else:
            write_component(kind, comp, w)
    for kind in removed:
        w.varint(kind)


def read_stack(r: Reader, delimited: bool = False) -> Optional[Stack]:
    """``read_stack`` (item.rs:1013)."""
    count = r.varint()
    if count <= 0:
        return None
    item = r.varint()
    added, removed = _read_patch(r, delimited)
    wire: Optional[bytes] = None
    if added or removed:
        patch = Writer()
        _write_patch(added, removed, patch, True)
        wire = bytes(patch.data)
    return Stack(item=item, count=count, added=added, removed=removed, wire=wire)


def write_stack(stack: Optional[Stack], w: Writer, delimited: bool = False) -> None:
    if stack is None or stack.count <= 0:
        w.varint(0)
        return
    w.varint(stack.count)
    w.varint(stack.item)
    if delimited and stack.wire is not None:
        w.bytes(stack.wire)
        return
    _write_patch(stack.added, stack.removed, w, delimited)


class Slot:
    """``ItemStack.OPTIONAL_STREAM_CODEC`` (item.rs:978)."""

    @classmethod
    def read(cls, r: Reader) -> Optional[Stack]:
        return read_stack(r, False)

    @classmethod
    def write(cls, v: Optional[Stack], w: Writer) -> None:
        write_stack(v, w, False)


class DelimitedSlot:
    """``ItemStack.OPTIONAL_UNTRUSTED_STREAM_CODEC`` (item.rs:1067)."""

    @classmethod
    def read(cls, r: Reader) -> Optional[Stack]:
        return read_stack(r, True)

    @classmethod
    def write(cls, v: Optional[Stack], w: Writer) -> None:
        write_stack(v, w, True)


class Template:
    """``ItemStackTemplate.STREAM_CODEC`` (item.rs:1102)."""

    @classmethod
    def read(cls, r: Reader) -> Stack:
        item = r.varint()
        count = r.varint()
        positive = r.count(65536)
        negative = r.count(65536)
        added: List[Tuple[int, Component]] = []
        for _ in range(positive):
            raw = r.varint()
            kind, comp, _ = _read_added(raw, r)
            added.append((kind, comp))
        removed = _read_removed(r, negative)
        return Stack(item=item, count=count, added=added, removed=removed)

    @classmethod
    def write(cls, s: Stack, w: Writer) -> None:
        w.varint(s.item)
        w.varint(s.count)
        _write_patch(s.added, s.removed, w, False)


def stack_from_hover(event: Tag) -> Optional[ItemStack]:
    """``stack_from_hover`` (item_data.rs:640): ``{id,count?,components?}``."""
    return template_from(event)


# ---------------------------------------------------------------------------
# ComponentMap / ComponentPatch
# ---------------------------------------------------------------------------

@dataclass
class ComponentMap:
    """Набор added/removed компонент (патч провода).

    ``added`` — пары ``(protocol_id, Component)``, ``removed`` — protocol_id.
    Пустой набор (нет added, нет removed) кодируется как ``varint(0) varint(0)``.
    """

    added: List[Tuple[int, Component]] = field(default_factory=list)
    removed: List[int] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.added and not self.removed

    def get(self, kind: int) -> Optional[Component]:
        for k, comp in self.added:
            if k == kind:
                return comp
        return None

    def component_names(self) -> List[str]:
        return [COMPONENT_NAMES.get(k, str(k)) for k, _ in self.added]

    def to_dict(self) -> Dict[str, Component]:
        return {
            COMPONENT_NAMES.get(k, f"minecraft:component_{k}"): comp
            for k, comp in self.added
        }

    def encode(self, delimited: bool = False) -> bytes:
        w = Writer()
        _write_patch(self.added, self.removed, w, delimited)
        return bytes(w.data)

    @classmethod
    def decode(cls, data: bytes, delimited: bool = False) -> "ComponentMap":
        r = Reader(data)
        added, removed = _read_patch(r, delimited)
        return cls(added=added, removed=removed)

    def apply(self, stack: ItemStack) -> ItemStack:
        """Применить патч к ``ItemStack`` из items.py.

        ``minecraft:damage`` идёт в ``stack.damage``; остальные added — в
        ``stack.extra`` (``ItemComponentMap``) по имени компоненты; removed
        убирает их. Как ``ItemStack.applyComponents`` в vanilla.
        """
        damage_id = component_id("minecraft:damage")
        for kind, comp in self.added:
            if kind == damage_id and isinstance(comp, ComponentInt):
                stack.damage = comp.value
                continue
            name = COMPONENT_NAMES.get(kind, f"minecraft:component_{kind}")
            if stack.extra is None or not isinstance(stack.extra, ItemComponentMap):
                stack.extra = ItemComponentMap()
            stack.extra.set(name, comp)
        for kind in self.removed:
            if kind == damage_id:
                stack.damage = 0
                continue
            name = COMPONENT_NAMES.get(kind, f"minecraft:component_{kind}")
            if isinstance(stack.extra, ItemComponentMap):
                stack.extra.remove(name)
        if stack.extra is not None and isinstance(stack.extra, ItemComponentMap) \
                and stack.extra.is_empty():
            stack.extra = None
        return stack


#: Синоним ``ComponentMap`` — патч провода.
ComponentPatch = ComponentMap


class WirePatch:
    """Патч в делимом виде (item.rs:729)."""

    def __init__(self, data: Optional[bytes] = None) -> None:
        self.data = data

    @staticmethod
    def adds(patch: bytes, kind: int) -> bool:
        r = Reader(patch)
        positive = r.count(65536)
        r.count(65536)
        for _ in range(positive):
            k = r.varint()
            length = r.count(r.remaining())
            r.bytes(length)
            if k == kind:
                return True
        return False

    @staticmethod
    def decode(patch: bytes):
        added, removed = _read_patch(Reader(patch), True)
        return added, removed
