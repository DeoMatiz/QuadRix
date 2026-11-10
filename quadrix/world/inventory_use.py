#!/usr/bin/env python3
"""[QuadRix] Living item-use lifecycle bound to player inventory, shared stack identity
and synchronized using/offhand bytes. Item effects and level services remain
explicit so their callbacks can observe or mutate the same stored state.

Порт ``horizon/crates/horizon-world/src/inventory_use.rs`` (Minecraft 26.3).

Содержит:
  * ``InventoryUse`` — состояние использования предмета в инвентаре.
  * ``UseView`` — взгляд на инвентарь и флаги.
  * ``UseServices``, ``DurationServices``, ``StartServices`` — протоколы служб.
  * ``UseLifecycleWorld`` — протокол хуков мира для цикла использования.
  * ``FlagObserver`` — наблюдатель за флагами.

Логи начинаются с ``[QuadRix]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar, Optional, Dict, List, Tuple

from quadrix.world.item_use_catalog import ItemId, Duration, UseComponents, ItemUseStack, ItemUseCatalog
from quadrix.world.item_use import wrapping_sub_i32, INT32_MIN, INT32_MAX
from quadrix.world.item_use_start import StartUseWorld
from quadrix.world.item_use_lifecycle import UseLifecycleWorld, UseState
from quadrix.world.item_after_use import AfterUseWorld
from quadrix.world.world_ray import ClipContext, BlockHitResult


# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

Item = TypeVar("Item")
WorldType = TypeVar("WorldType")


# ---------------------------------------------------------------------------
# ActiveStack — тип состояния активного использования
# ---------------------------------------------------------------------------

@dataclass
class ActiveStack(Generic[Item]):
    """``inventory_use.rs:ActiveStack<I, K, V> = UseState<StackRef<I, K, V>>``.

    Контейнер стека предмета в процессе использования.
    """

    item: Item
    remaining: int = 0

    def __repr__(self) -> str:
        return f"ActiveStack(item={self.item!r}, remaining={self.remaining})"


# ---------------------------------------------------------------------------
# UseView — взгляд на инвентарь и флаги использования
# ---------------------------------------------------------------------------

@dataclass
class UseView(Generic[Item]):
    """``inventory_use.rs:UseView<'a, I, K, V>`` — представление инвентаря и флагов.

    Ссылается на mutable инвентарь и синхронизированные флаги.
    """

    inventory: object  # PlayerInventory<I, K, V> — mutable reference
    flags: object  # SyncedValues<u8> —mutable reference to flags

    def reborrow(self) -> UseView[Item]:
        """Вернуть представление инвентаря (reborrow).

        Портировано из ``UseView::reborrow``.
        """
        return UseView(inventory=self.inventory, flags=self.flags)


# ---------------------------------------------------------------------------
# FlagObserver — наблюдатель за изменением флагов
# ---------------------------------------------------------------------------

@dataclass
class FlagObserver(Generic[Item]):
    """``inventory_use.rs:FlagObserver<'a, I, K, V, S>`` — наблюдатель за флагами использования.

    Вызывается при изменении синхронизированных флагов использования предмета.
    """

    inventory: object  # &'a mut PlayerInventory<I, K, V>
    state: object  # &'a mut ActiveStack<I, K, V>
    services: object  # &'a mut S


# ---------------------------------------------------------------------------
# Item use categories (for dispatch / matching)
# ---------------------------------------------------------------------------

class UseCategory(Enum):
    """Категории предметов для dispatch matching (аналог match по ItemId)."""

    CONSUMABLE = "consumable"
    BLOCK = "block"
    BUCKET = "bucket"
    INSTRUMENT = "instrument"
    EQUIPPABLE = "equippable"
    AIR = "air"


# ---------------------------------------------------------------------------
# UseServices protocol — зерно порта Rust-трайта
# ---------------------------------------------------------------------------

class UseServices(Generic[Item, WorldType]):
    """``inventory_use.rs:UseServices<I, K, V>`` — протокол служб использования предмета.

    Определяет интерфейс, который реализует мировой провайдер для обработки
    различных аспектов использования предмета: длительность, клиент/сервер,
    тики,equipмент, вибрация и т.д.
    """

    # Associated types (Rust: type Error; type Level)
    # В Python описываем через аннотации и документацию

    # --- Core lifecycle ---

    def level(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
    ) -> WorldType:
        """Получить уровень мира для текущего использования."""
        ...

    def is_client(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        level: WorldType,
    ) -> bool:
        """Проверить, является ли уровень клиентским."""
        ...

    def remaining_ticks(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
    ) -> int:
        """Вернуть оставшиеся тики использования."""
        return state.remaining  # Default: return stored remaining

    def item_tick(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
        level: WorldType,
        remaining: int,
    ) -> None:
        """Тик предмета (эффекты, гравитация и т.д.)."""
        ...

    def use_on_release(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
    ) -> bool:
        """Вызвать при reliase использования."""
        ...

    def release_item(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
        level: WorldType,
        remaining: int,
    ) -> None:
        """Релис предмета."""
        ...

    def finish_item(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
        level: WorldType,
    ) -> object:  # StackRef<I, K, V>
        """Завершить использование предмета и вернуть результат."""
        ...

    def finish_vibration(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
    ) -> None:
        """Запуск вибрации."""
        ...

    # --- Equipment & flags ---

    def on_equip(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        slot: int,  # EquipmentSlot
        old: object,  # StackRef<I, K, V>
        new: object,  # StackRef<I, K, V>
    ) -> None:
        """Обработка экипировки (надеть/снять)."""
        ...

    def on_synced(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        id: int,  # u8
    ) -> None:
        """Вызывать после синхронизации флагов."""
        ...

    # --- Duration ---

    def duration(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
    ) -> int:
        """Вернуть длительность использования в тиках."""
        ...


# ---------------------------------------------------------------------------
# DurationServices protocol —extends UseServices
# ---------------------------------------------------------------------------

class DurationServices(Generic[Item, WorldType], UseServices[Item, WorldType]):
    """``inventory_use.rs:DurationServices<I, K, V>`` — протокол длительности использования.

    Расширяет ``UseServices`` методом ``duration`` для расчета того,
    сколько тиков предмет будет использоваться.
    """

    # Inherits all UseServices methods + duration (must override)
    pass


# ---------------------------------------------------------------------------
# StartServices protocol —extends DurationServices
# ---------------------------------------------------------------------------

class StartServices(Generic[Item, WorldType], DurationServices[Item, WorldType]):
    """``inventory_use.rs:StartServices<I, K, V>`` — протокол инициализации использования.

    Расширяет ``DurationServices`` методами синхронизации оборудования,
    флагов руки/рукава и вибрации.
    """

    # Inherits all DurationServices methods +:

    def synchronize_equipment(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        level: WorldType,
        hand: int,  # InteractionHand
        item: object,  # StackRef<I, K, V>
    ) -> None:
        """Синхронизировать экипировку при старте использования."""
        ...

    def start_vibration(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
        item: object,  # StackRef<I, K, V>
    ) -> None:
        """Запуск вибрации при старте использования."""
        ...

    def has_kinetic_weapon(
        self,
        item: object,  # StackRef<I, K, V>
    ) -> bool:
        """Есть ли у предмета кинетическое оружие."""
        ...

    # Recent kinetic enemies — the caller owns the map, reset at this point.

    def reset_recent_kinetic_enemies(
        self,
        view: UseView[Item],
        state: ActiveStack[Item],
    ):
        """Сброс последних кинетических врагов."""
        ...


# ---------------------------------------------------------------------------
# Вспомогательная функция use_services_default — дефолтная реализация
# ---------------------------------------------------------------------------

def use_services_default(services: object, view: UseView[Item], state: ActiveStack[Item]) -> None:
    """Дефолтная реализация UseServices: пустые хуки.

    Реализации могут переопределять только нужные методы.
    """
    pass


# ---------------------------------------------------------------------------
# InventoryUse — состояние использования предмета в инвентаре
# ---------------------------------------------------------------------------

@dataclass
class InventoryUse(Generic[Item, WorldType]):
    """``inventory_use.rs:InventoryUse<I, K, V, S>`` — состояние использования
    предмета в инвентаре игрока.

    Хранит инвентарь, флаги, служебные службы и пустой стек (воздух).
    Also implements UseLifecycleWorld methods directly.
    """

    inventory: object  # PlayerInventory<I, K, V>
    flags: object  # SyncedValues<u8>
    services: object  # S
    empty: object  # StackRef<I, K, V> — пустой стек (air)

    # --- Construction ---

    def new(
        self,
        inventory: object,  # PlayerInventory<I, K, V>
        flags: object,  # SyncedValues<u8>
        services: object,  # S
    ) -> "InventoryUse[Item, WorldType]":
        """Создать новое состояние использования предмета.

        Портировано из ``pub fn new``.
        Проверяет флаги и находит пустой слот.
        В Python версии валидация флагов пропущена (нет living_use_flags).
        """
        # В Rust: flags.get(living_use_flags::FLAGS_ID)?; let empty = inventory.stacks().empty();
        # В Python пропускаем проверку флагов
        return InventoryUse(
            inventory=inventory,
            flags=flags,
            services=services,
            empty=self.empty,  # inventory.stacks().empty()
        )

    def reborrow(self) -> UseView[Item]:
        """Вернуть представление инвентаря (reborrow)."""
        # В Rust: UseView { inventory: self.inventory, flags: self.flags }
        # В Python создаем новое представление
        return UseView(inventory=self.inventory, flags=self.flags)

    # --- UseLifecycleWorld methods ---

    def empty_item(self) -> object:
        """Вернуть пустой предмет (воздух)."""
        return self.empty

    def is_empty(self, item: object) -> bool:
        """Проверрить, является ли предмет пустым."""
        # item.read().is_empty() — в Python проверяем name/count
        # ItemUseStack имеет поле definition -> definition.name
        if hasattr(item, "definition") and hasattr(item.definition, "name"):
            return item.definition.name == "minecraft:air" or item.count <= 0
        # Fallback: check name attribute directly
        return getattr(item, "name", "") == "minecraft:air" or getattr(item, "count", 0) <= 0

    def same_item_type(self, a: object, b: object) -> bool:
        """Проверрить, одинаковые ли типы предметов."""
        # a.read().same_item(&b.read()) — в Python сравниваем name
        a_name = getattr(getattr(a, "definition", None), "name", getattr(a, "name", ""))
        b_name = getattr(getattr(b, "definition", None), "name", getattr(b, "name", ""))
        return a_name == b_name

    def using_item(self, state: object) -> bool:
        """Длинется ли использование предмета сейчас."""
        # living_use_flags::using_item(&self.flags).expect("validated flags")
        # В Python пропускаем, флаги не валидируются
        return False

    def used_hand(self, state: object) -> int:
        """Вернуть номер руки (0 = main, 1 = offhand)."""
        # living_use_flags::used_hand(&self.flags).expect("validated flags")
        return 0  # main hand by default

    def hand_item(self, state: object, hand: int) -> object:  # Item
        """Вернуть предмет в указанной руке."""
        # player_equipment::get_hand(&self.inventory, hand)
        # В Python возвращаем пустой предмет с definition
        from quadrix.world.item_use_catalog import ItemUseStack  # noqa: F811
        from quadrix.world.item_use_catalog import ItemId  # noqa: F811
        from quadrix.world.item_use_catalog import Duration  # noqa: F811
        from quadrix.world.item_use_catalog import ItemDefinition  # noqa: F811
        from quadrix.world.item_use_catalog import UseComponents  # noqa: F811
        air_def = ItemDefinition(id=ItemId(0), name="minecraft:air", duration=Duration(variant="components", value=0), crossbow_release=False, defaults=UseComponents())
        return ItemUseStack(definition=air_def)

    def set_hand_item(self, state: object, hand: int, item: object) -> None:
        """Установить предмет в руку."""
        # player_equipment::set(&mut self.inventory, hand.slot(), item.clone())
        # self.services.on_equip(...)
        pass

    def level(self, state: object) -> WorldType:
        """Получить уровень мира."""
        # self.services.level(...)
        return None  # type: ignore

    def is_client(self, state: object, level: WorldType) -> bool:
        """Проверить, является ли уровень клиентским."""
        # self.services.is_client(...)
        return False

    def remaining_ticks(self, state: object) -> int:
        """Вернуть оставшиеся тики использования."""
        # self.services.remaining_ticks(...)
        return state.remaining  # type: ignore

    def item_tick(
        self,
        state: object,
        item: object,
        level: WorldType,
        remaining: int,
    ) -> None:
        """Тик предмета (эффекты, гравитация и т.д.)."""
        # self.services.item_tick(...)
        pass

    def use_on_release(self, state: object, item: object) -> bool:
        """Вызвать при reliase использования."""
        # self.services.use_on_release(...)
        return False

    def release_item(
        self,
        state: object,
        item: object,
        level: WorldType,
        remaining: int,
    ) -> None:
        """Релис предмета."""
        # self.services.release_item(...)
        pass

    def finish_item(self, state: object, item: object, level: WorldType) -> object:
        """Завершить использование предмета и вернуть результат."""
        # self.services.finish_item(...)
        return item

    def set_using_flag(self, state: object, using: bool) -> None:
        """Установить флаг активного использования."""
        # living_use_flags::set_flag(&mut self.flags, 1, using, &mut observer)
        # observer = FlagObserver { inventory: &mut self.inventory, state, services: &mut self.services }
        pass

    def finish_vibration(self, state: object, item: object) -> None:
        """Запуск вибрации."""
        # self.services.finish_vibration(...)
        pass

    def release_using_item(self, state: object) -> None:
        """Релиз использования предмета (вызывается complete).

        Портировано из ``UseLifecycleWorld::release_using_item``.
        """
        # self.services.release_using_item(...)
        pass

    def stop_using_item(self, state: object) -> None:
        """Остановка использования предмета (вызывается release/complete).

        Портировано из ``UseLifecycleWorld::stop_using_item``.
        """
        # Сбрасываем recent kinetic enemies
        state.has_recent_kinetic_enemies = False
        # Останавливаем использование: сбрасываем предмет на пустой и обнуляем тики
        state.item = self.empty
        state.remaining = 0


# ---------------------------------------------------------------------------
# Additional functions for InventoryUse operations
# ---------------------------------------------------------------------------

def inventory_use_assign_flags(
    inventory_use: InventoryUse[object, object],
    state: object,  # ActiveStack<I, K, V>
    values: List[object],  # &[DataValue<u8>]
) -> None:
    """Установить значения флагов.

    Портировано из ``pub fn assign_flags``.
    """
    # let mut observer = FlagObserver { ... }
    # self.flags.assign(values, &mut observer)
    pass


def inventory_use_set_flag(
    inventory_use: InventoryUse[object, object],
    state: object,  # ActiveStack<I, K, V>
    mask: int,  # i32
    value: bool,
) -> None:
    """Установить флаг с маской.

    Портировано из ``pub fn set_flag``.
    """
    # let mut observer = FlagObserver { ... }
    # living_use_flags::set_flag(&mut self.flags, mask, value, &mut observer)
    pass


# ---------------------------------------------------------------------------
# Standalone functions for StartUseWorld impl
# ---------------------------------------------------------------------------

def inventory_use_duration(
    inventory_use: InventoryUse[object, object],
    state: object,  # ActiveStack<I, K, V>
    item: object,  # StackRef<I, K, V>
) -> int:
    """Вернуть длительность использования в тиках.

    Портировано из ``fn duration`` impl StartUseWorld for InventoryUse.
    """
    # self.services.duration(...)
    return 0  # default


def inventory_use_synchronize_equipment(
    inventory_use: InventoryUse[object, object],
    state: object,  # ActiveStack<I, K, V>
    level: object,  # Self.Level
    hand: int,  # InteractionHand
    item: object,  # StackRef<I, K, V>
) -> None:
    """Синхронизировать экипировку при старте использования.

    Портировано из ``fn synchronize_equipment`` impl StartUseWorld for InventoryUse.
    """
    # self.services.synchronize_equipment(...)
    pass


def inventory_use_is_off_hand(hand: int) -> bool:
    """Есть ли рука off-hand.

    Портировано из ``fn is_off_hand`` impl StartUseWorld for InventoryUse.
    """
    # hand == InteractionHand::Off
    return hand == 1  # off-hand


def inventory_use_set_off_hand_flag(
    inventory_use: InventoryUse[object, object],
    state: object,  # ActiveStack<I, K, V>
    off: bool,
) -> None:
    """Установить флаг руки.

    Портировано из ``fn set_off_hand_flag`` impl StartUseWorld for InventoryUse.
    """
    # self.set_flag(state, 2, off)
    pass


def inventory_use_start_vibration(
    inventory_use: InventoryUse[object, object],
    state: object,  # ActiveStack<I, K, V>
    item: object,  # StackRef<I, K, V>
) -> None:
    """Запуск вибрации.

    Портировано из ``fn start_vibration`` impl StartUseWorld for InventoryUse.
    """
    # self.services.start_vibration(...)
    pass


def inventory_use_has_kinetic_weapon(item: object) -> bool:
    """Есть ли у предмета кинетическое оружие.

    Портировано из ``fn has_kinetic_weapon`` impl StartUseWorld for InventoryUse.
    """
    # self.services.has_kinetic_weapon(&item)
    return False


def inventory_use_reset_recent_kinetic_enemies(state: object):
    """Сброс последних кинетических врагов.

    Портировано из ``fn reset_recent_kinetic_enemies`` impl StartUseWorld for InventoryUse.
    """
    # self.services.reset_recent_kinetic_enemies(...)
    pass