#!/usr/bin/env python3
"""[QuadRix] Каталог использование предметов: таблица определений и прокси-запросы.

Порт ``horizon/crates/horizon-world/src/item_use_catalog.rs`` (Minecraft 26.3).

Содержит:
  * ``ItemId`` — идентификатор предмета (u32).
  * ``Duration`` — способы расчёта длительности использования.
  * ``UseComponents`` — компоненты basic-параметров (стек, ущерб, сроки).
  * ``ItemDefinition`` — определение предмета (имя, длительность, флаги).
  * ``ItemUseStack`` — стек предмета в руке (временное состояние).
  * ``ItemUseCatalog`` — загруженный каталог с поиском ``get`` / ``by_name``.

Логи начинаются с ``[QuadRix]``.
"""

from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

__all__ = [
    "ItemId",
    "Duration",
    "UseComponents",
    "ItemDefinition",
    "ItemUseStack",
    "ItemUseCatalog",
]


# ---------------------------------------------------------------------------
# ItemId — обертка u32
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ItemId:
    """``item_use_catalog.rs:ItemId(u32)`` — уникальный ID предмета."""

    raw: int

    def __int__(self) -> int:
        return self.raw


# ---------------------------------------------------------------------------
# DurationVariant — варианты длительности
# ---------------------------------------------------------------------------

class DurationVariant(Enum):
    """Варианты длительности: Components, Constant, Instrument."""

    Components = "components"
    Constant = "constant"
    Instrument = "instrument"


# ---------------------------------------------------------------------------
# Duration — источник длительности использования
# ---------------------------------------------------------------------------

@dataclass
class Duration:
    """``item_use_catalog.rs:Duration`` — источник длительности."""

    variant: DurationVariant
    value: int = 0  # для Constant — тики; для Instrument — биты; для Components — не используется


# ---------------------------------------------------------------------------
# UseComponents — базовые компоненты из catalog JSON
# ---------------------------------------------------------------------------

@dataclass
class UseComponents:
    """``item_use_catalog.rs:UseComponents`` — дефолтные компоненты предмета."""

    max_stack_size: Optional[int] = None
    max_damage: Optional[int] = None
    damage: Optional[int] = None
    unbreakable: bool = False
    consume_seconds: Optional[float] = None
    block_delay_seconds: Optional[float] = None
    kinetic_weapon: bool = False
    instrument_seconds: Optional[float] = None


# ---------------------------------------------------------------------------
# ItemDefinition — одно определение из каталога
# ---------------------------------------------------------------------------

@dataclass
class ItemDefinition:
    """``item_use_catalog.rs:ItemDefinition`` — запись одного предмета."""

    id: ItemId
    name: str
    duration: Duration
    crossbow_release: bool
    defaults: UseComponents = field(default_factory=UseComponents)


# ---------------------------------------------------------------------------
# ItemUseStack — стек предмета в руке (временное состояние)
# ---------------------------------------------------------------------------

@dataclass
class ItemUseStack:
    """``item_use_catalog.rs:ItemUseStack<'a>`` — стек предмета во время использования."""

    definition: ItemDefinition
    count: int = 1
    components: UseComponents = field(default_factory=UseComponents)

    def is_empty(self) -> bool:
        return self.count <= 0 or self.definition.name == "minecraft:air"

    def max_stack_size(self) -> int:
        if self.is_empty():
            return 1
        return self.components.max_stack_size or 1

    def durability(self) -> dict:
        return {
            "count": self.count,
            "air": self.definition.name == "minecraft:air",
            "max_damage": self.components.max_damage,
            "damage": self.components.damage,
            "unbreakable": self.components.unbreakable,
        }

    def is_stackable(self) -> bool:
        d = self.durability()
        md = d["max_damage"]
        dmg = d["damage"]
        return self.max_stack_size() > 1 and not (
            md is not None and dmg is not None and dmg >= md
        )

    def use_duration(self) -> int:
        if self.is_empty():
            return 0
        match self.definition.duration.variant:
            case DurationVariant.Constant:
                return self.definition.duration.value
            case DurationVariant.Instrument:
                iv = self.components.instrument_seconds
                return int((iv or 0) * 20.0) if iv is not None else 0
            case DurationVariant.Components:
                cv = self.components.consume_seconds
                if cv is not None:
                    return int(cv * 20.0)
                if self.components.block_delay_seconds is not None or self.components.kinetic_weapon:
                    return 72000
                return 0

    def use_on_release(self) -> bool:
        if self.is_empty():
            return False
        return self.definition.crossbow_release


# ---------------------------------------------------------------------------
# Error class for catalog loading
# ---------------------------------------------------------------------------

class CatalogError(Exception):
    """Ошибка при загрузке каталога предметов (аналог ``std::io::Error``)."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.message = msg


# ---------------------------------------------------------------------------
# ItemUseCatalog — загруженный реестр предметов
# ---------------------------------------------------------------------------

class ItemUseCatalog:
    """``item_use_catalog.rs:ItemUseCatalog`` — каталог определений предметов.

    Загружается из JSON-формата каталога Minecraft 26.3 (ключ ``items``).
    Обеспечивает поиск по индексу (ID) и по имени.

    Attributes:
        _items: список ``ItemDefinition``, проиндексированный номером ID.
        names: словарь ``имя -> raw ID`` для обратного поиска (аналог BTreeMap).
    """

    def __init__(self, items: list, names: dict[str, int]) -> None:
        self._items = items
        self.names = names  # str -> int (raw ItemId)

    @classmethod
    def from_json(cls, value: dict) -> "ItemUseCatalog":
        """``ItemUseCatalog::from_json`` — создать каталог из JSON-объекта.

        Ожидаемый формат (упрощённый, без валидации полной схемы):
            {
                "schema": 1,
                "DataVersion": 263,
                "items": [
                    {
                        "id": 0,
                        "name": "minecraft:air",
                        "duration_impl": "Item",
                        "release_impl": "Item",
                        "components": {
                            "minecraft:max_stack_size": 64,
                            ...
                        }
                    },
                    ...
                ],
                "instruments": { ... }
            }
        """
        rows = value.get("items", [])
        if not isinstance(rows, list):
            raise CatalogError("missing item catalog entries")

        instruments = value.get("instruments", {})

        items: list = []
        names: dict[str, int] = {}

        for index, row in enumerate(rows):
            raw = index  # u32::try_from(index)
            # Проверка contiguous ID
            if row.get("id") != raw:
                raise CatalogError("non-contiguous item catalog ID")

            name: str = row.get("name", "")
            # Canonical identifier check (упрощено)

            item_id = ItemId(raw)
            if name in names:
                raise CatalogError("duplicate item identifier")
            names[name] = raw

            # duration_impl
            duration_impl: str = row.get("duration_impl", "Item")
            match duration_impl:
                case "Item":
                    dur_variant = DurationVariant.Components
                    dur_value = 0
                case "BowItem" | "CrossbowItem" | "TridentItem":
                    dur_variant = DurationVariant.Constant
                    dur_value = 72000
                case "BundleItem" | "BrushItem":
                    dur_variant = DurationVariant.Constant
                    dur_value = 200
                case "SpyglassItem":
                    dur_variant = DurationVariant.Constant
                    dur_value = 1200
                case "EnderEyeItem":
                    dur_variant = DurationVariant.Constant
                    dur_value = 0
                case "InstrumentItem":
                    dur_variant = DurationVariant.Instrument
                    dur_value = 0
                case _:
                    raise CatalogError(f"unsupported item duration implementation: {duration_impl}")

            # release_impl
            release_impl: str = row.get("release_impl", "Item")
            match release_impl:
                case "Item":
                    crossbow_release = False
                case "CrossbowItem":
                    crossbow_release = True
                case _:
                    raise CatalogError(f"unsupported release implementation: {release_impl}")

            # components
            comp_obj = row.get("components")
            if comp_obj is None or not isinstance(comp_obj, dict):
                raise CatalogError("missing item component defaults")

            # optional_int helpers
            def opt_int(val):
                if val is None:
                    return None
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return None

            # number helper for f32
            def num(key: str, default: float = 0.0) -> Optional[float]:
                v = comp_obj.get(key)
                if v is None:
                    return default
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return default

            # Parse instrument bits if present
            instrument_seconds: Optional[float] = None
            instr = comp_obj.get("minecraft:instrument")
            if instr is not None:
                try:
                    # Handle "0x" prefix for hex string
                    if isinstance(instr, str) and instr.startswith("0x"):
                        bits = int(instr, 16)
                    elif isinstance(instr, str):
                        bits = int(instr)
                    elif isinstance(instr, int):
                        bits = instr
                    else:
                        bits = 0
                    # Convert 32-bit unsigned int to float (IEEE 754)
                    instrument_seconds = struct.unpack(
                        "f", struct.pack("I", bits & 0xFFFFFFFF)
                    )[0]
                except (ValueError, TypeError, struct.error):
                    instrument_seconds = None

            defaults = UseComponents(
                max_stack_size=opt_int(comp_obj.get("minecraft:max_stack_size")),
                max_damage=opt_int(comp_obj.get("minecraft:max_damage")),
                damage=opt_int(comp_obj.get("minecraft:damage")),
                unbreakable=comp_obj.get("minecraft:unbreakable") is not None,
                consume_seconds=num("minecraft:consumable", 1.6),
                block_delay_seconds=num("minecraft:blocks_attacks", 0.0),
                kinetic_weapon=comp_obj.get("minecraft:kinetic_weapon") is not None,
                instrument_seconds=instrument_seconds,
            )

            items.append(ItemDefinition(
                id=item_id,
                name=name,
                duration=Duration(variant=dur_variant, value=dur_value),
                crossbow_release=crossbow_release,
                defaults=defaults,
            ))

        # Air must be first
        if not items or items[0].name != "minecraft:air":
            raise CatalogError("item registry must start with air")

        return cls(items, names)

    def get(self, id: ItemId) -> Optional[ItemDefinition]:
        """``ItemUseCatalog::get`` — получить определение по ID."""
        idx = id.raw
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def by_name(self, name: str) -> Optional[ItemDefinition]:
        """``ItemUseCatalog::by_name`` — получить определение по имени."""
        raw = self.names.get(name)
        if raw is None:
            return None
        return self.get(ItemId(raw))

    def items(self) -> list:
        """``ItemUseCatalog::items`` — получить все определения."""
        return self._items

    def count(self) -> int:
        """Количество записей в каталоге."""
        return len(self._items)


# ----------------------------------------------------------------------------
# Пример использования (для тестов)
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    # Минимальный тест загрузки из JSON
    sample = {
        "schema": 1,
        "DataVersion": 263,
        "items": [
            {
                "id": 0,
                "name": "minecraft:air",
                "duration_impl": "Item",
                "release_impl": "Item",
                "components": {}
            }
        ],
        "instruments": {}
    }
    catalog = ItemUseCatalog.from_json(sample)
    print(f"Catalog loaded: {catalog.count()} items")
    air = catalog.by_name("minecraft:air")
    print(f"Air item: {air}")