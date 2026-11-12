#!/usr/bin/env python3
"""[QuadRix] Инвентарь игрока: 36 слотов, выбор hotbar и снаряжение.

Порт ``horizon/crates/horizon-world/src/player_inventory.rs`` (Minecraft 26.3):
``EquipmentSlot``, ``InventoryError``, ``PlayerInventory``.

Где Rust хранит ссылки на стеки (``StackRef``/``ItemStacks``), Python хранит
сами :class:`~quadrix.items.items.ItemStack` (или ``None`` для пустого слота):
GIL и отсутствие алиасов-ссылок делают обёртку ненужной. Имена и порядок
индексов сохранены:

    * ``items[0..8]``   — hotbar (``selected`` указывает сюда);
    * ``items[9..35]``  — основной инвентарь (3×9);
    * ``get(36..40)``   — снаряжение: feet, legs, chest, head, offhand.

Что НЕ портировано (отдельные модули, см. AGENTS.md): подбор предметов
(``inventory_pickup.rs``), тик (``inventory_tick.rs``), использование
(``inventory_use.rs``), контейнеры (``simple_container.rs``), меню. Здесь —
только хранилище и выбор слота, чего достаточно для Gameplay PART 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from quadrix.items.items import ItemStack

__all__ = [
    "INVENTORY_SIZE",
    "HOTBAR_SIZE",
    "MAIN_SIZE",
    "EquipmentSlot",
    "InventoryError",
    "PlayerInventory",
]

#: ``PlayerInventory``: 36 слотов (hotbar + основной инвентарь).
INVENTORY_SIZE: int = 36
#: ``Inventory.getSelectionSize`` — длина hotbar.
HOTBAR_SIZE: int = 9
#: Основной инвентарь: 3 ряда по 9.
MAIN_SIZE: int = INVENTORY_SIZE - HOTBAR_SIZE


class EquipmentSlot(Enum):
    """``EquipmentSlot`` (player_inventory.rs:8).

    ``inventory_slot`` — номер слота в общем инвентаре (``get``/``set``).
    ``MainHand`` слота не имеет: он и есть выбранный слот hotbar.
    """

    MAIN_HAND = 0
    OFF_HAND = 1
    FEET = 2
    LEGS = 3
    CHEST = 4
    HEAD = 5
    BODY = 6
    SADDLE = 7

    def inventory_slot(self) -> Optional[int]:
        """``EquipmentSlot.inventory_slot`` (player_inventory.rs:29)."""
        return _EQUIPMENT_INVENTORY_SLOT.get(self)

    @staticmethod
    def from_inventory_slot(index: int) -> Optional["EquipmentSlot"]:
        """``EquipmentSlot.from_inventory_slot`` (player_inventory.rs:41)."""
        return _INVENTORY_SLOT_EQUIPMENT.get(int(index))


#: Rust: OffHand=40, Feet=36, Legs=37, Chest=38, Head=39, Body=41, Saddle=42.
_EQUIPMENT_INVENTORY_SLOT = {
    EquipmentSlot.OFF_HAND: 40,
    EquipmentSlot.FEET: 36,
    EquipmentSlot.LEGS: 37,
    EquipmentSlot.CHEST: 38,
    EquipmentSlot.HEAD: 39,
    EquipmentSlot.BODY: 41,
    EquipmentSlot.SADDLE: 42,
}
_INVENTORY_SLOT_EQUIPMENT = {
    slot: kind for kind, slot in _EQUIPMENT_INVENTORY_SLOT.items()
}

#: Сколько слотов снаряжения хранит модель (36..42 -> 0..6).
_EQUIPMENT_SLOTS: int = 7


class InventoryError(Exception):
    """``InventoryError`` (player_inventory.rs:100): ``Index`` / ``Selection``."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"inventory error: {kind}")


def _is_empty(stack: Optional[ItemStack]) -> bool:
    """Пустой слот: ``None`` или пустой стек (Rust ``StackRef.read().is_empty()``)."""
    return stack is None or stack.is_empty()


@dataclass
class PlayerInventory:
    """``PlayerInventory`` — хранилище и выбранный слот (player_inventory.rs:110).

    ``items`` — 36 слотов; ``equipment`` — снаряжение по индексу
    ``slot - 36``. ``selected`` — 0..8. ``times_changed`` — счётчик изменений
    (Rust ``changed``).
    """

    items: List[Optional[ItemStack]] = field(
        default_factory=lambda: [None] * INVENTORY_SIZE
    )
    equipment: List[Optional[ItemStack]] = field(
        default_factory=lambda: [None] * _EQUIPMENT_SLOTS
    )
    selected: int = 0
    times_changed: int = 0

    # -- выбор слота (player_inventory.rs:148-163) ------------------------

    def selected_index(self) -> int:
        """``PlayerInventory.selected``."""
        return int(self.selected)

    def set_selected(self, selected: int) -> None:
        """``set_selected``: вне 0..8 — ``InventoryError.Selection``."""
        if not (0 <= int(selected) < HOTBAR_SIZE):
            raise InventoryError("selection")
        self.selected = int(selected)

    def scroll(self, delta: int) -> int:
        """Колесо мыши: сдвиг выбора по кругу (``Inventory.swapPaint`` loop).

        Ваниль ``Inventory.setSelected`` (через ``scroll``) не выходит за
        0..8: выбор заворачивается по модулю 9.
        """
        self.selected = (self.selected + int(delta)) % HOTBAR_SIZE
        return self.selected

    def selected_item(self) -> Optional[ItemStack]:
        """``selected_item``: стек выбранного слота hotbar."""
        return self.items[self.selected]

    def set_selected_item(self, stack: Optional[ItemStack]) -> Optional[ItemStack]:
        """``set_selected_item``: заменить выбранный стек, вернуть старый."""
        old = self.items[self.selected]
        self.items[self.selected] = stack
        return old

    # -- доступ (player_inventory.rs:164-209) -----------------------------

    def get(self, index: int) -> Optional[ItemStack]:
        """``get``: слот 0..35 — items; 36..42 — снаряжение; иначе пусто."""
        index = int(index)
        if index < 0:
            raise InventoryError("index")
        if index < INVENTORY_SIZE:
            return self.items[index]
        kind = EquipmentSlot.from_inventory_slot(index)
        if kind is None:
            return None
        equipment_index = _EQUIPMENT_INVENTORY_SLOT[kind] - INVENTORY_SIZE
        if 0 <= equipment_index < len(self.equipment):
            return self.equipment[equipment_index]
        return None

    def set(self, index: int, stack: Optional[ItemStack]) -> None:
        """``set``: записать стек в слот (00..35 items, 36..42 снаряжение)."""
        index = int(index)
        if index < 0:
            raise InventoryError("index")
        if index < INVENTORY_SIZE:
            self.items[index] = stack
            return
        kind = EquipmentSlot.from_inventory_slot(index)
        if kind is None:
            return
        equipment_index = _EQUIPMENT_INVENTORY_SLOT[kind] - INVENTORY_SIZE
        if 0 <= equipment_index < len(self.equipment):
            self.equipment[equipment_index] = stack

    def remove_no_update(self, index: int) -> Optional[ItemStack]:
        """``remove_no_update``: вынуть стек из слота (обновление — у меню)."""
        stack = self.get(index)
        self.set(index, None)
        return stack

    # -- поиск свободного слота / обмен (player_inventory.rs:230-319) -----

    def free_slot(self) -> int:
        """``free_slot``: первый пустой слот items, иначе -1."""
        for i, stack in enumerate(self.items):
            if _is_empty(stack):
                return i
        return -1

    def pick_slot(self, index: int) -> None:
        """``pick_slot``: поменять выбранный слот с ``index`` (только items)."""
        self.selected = self._suitable_hotbar()
        index = int(index)
        if not (0 <= index < INVENTORY_SIZE):
            raise InventoryError("index")
        self.items[self.selected], self.items[index] = (
            self.items[index],
            self.items[self.selected],
        )

    def _suitable_hotbar(self) -> int:
        """``suitable_hotbar`` без правил: первый пустой слот, начиная с выбора."""
        for delta in range(HOTBAR_SIZE):
            i = (self.selected + delta) % HOTBAR_SIZE
            if _is_empty(self.items[i]):
                return i
        return self.selected

    def add_stack(self, stack: Optional[ItemStack]) -> bool:
        """Положить стек в первый свободный слот (упрощённый ``add_and_pick``).

        Возвращает ``False``, если свободного слота нет (предмет теряется —
        полноценный подбор — ``inventory_pickup.rs``, следующая сессия).
        """
        if _is_empty(stack):
            return False
        free = self.free_slot()
        if free < 0:
            return False
        self.items[free] = stack
        self.changed()
        return True

    # -- прочее -----------------------------------------------------------

    def clear(self) -> None:
        """``clear``: обнулить items и снаряжение."""
        self.items = [None] * INVENTORY_SIZE
        self.equipment = [None] * _EQUIPMENT_SLOTS

    def is_empty(self) -> bool:
        """``is_empty``: все слоты (0..42) пусты."""
        return all(_is_empty(self.get(i)) for i in range(43))

    def changed(self) -> None:
        """``changed``: инкремент ``times_changed`` (wrapping в Rust)."""
        self.times_changed = (self.times_changed + 1) & 0xFFFFFFFF
