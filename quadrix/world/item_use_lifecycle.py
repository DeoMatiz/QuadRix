#!/usr/bin/env python3
"""[QuadRix] Living item-use lifecycle ordering over stable item-stack handles.

Порт ``horizon/crates/horizon-world/src/item_use_lifecycle.rs`` (Minecraft 26.3).

Содержит:
  * struct UseState<Item> — состояние активного использования
  * trait UseLifecycleWorld — хуки мира для цикла использования
  * функции tick, update, complete, release, stop

Логи начинаются с ``[QuadRix]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, Optional

from quadrix.world.item_use import wrapping_sub_i32, INT32_MIN, INT32_MAX
from quadrix.world.item_use_start import start

Item = TypeVar("Item")
WorldType = TypeVar("WorldType")


# ---------------------------------------------------------------------------
# UseState — состояние использования предмета
# ---------------------------------------------------------------------------

@dataclass(frozen=False)
class UseState(Generic[Item]):
    """Структура состояния использования предмета.

    Портировано из ``horizon/crates/horizon-world/src/item_use_lifecycle.rs``.

    Поля:
        item: используемый предмет
        remaining: оставшиеся тики использования
        has_recent_kinetic_enemies: флаг recent kinetic enemies
    """

    item: Item
    remaining: int
    has_recent_kinetic_enemies: bool = False


# ---------------------------------------------------------------------------
# UseLifecycleWorld trait — зерно порта Rust-трайта
# ---------------------------------------------------------------------------

class UseLifecycleWorld(Protocol[WorldType]):
    """Зеркало Rust-трейта ``UseLifecycleWorld``.

    Реализуют наследники (или duck-typed объект), предоставляющий хуки мира.
    Всі методи приймают ``s: UseState[Item]`` для доступа к состоянию.
    """

    # --- empty_item ---

    def empty_item(self) -> Item:
        """Вернуть пустой предмет (воздух)."""
        ...

    # --- is_empty ---

    def is_empty(self, item: Item) -> bool:
        """Проверрить, является ли предмет пустым."""
        ...

    # --- same_item_type ---

    def same_item_type(self, a: Item, b: Item) -> bool:
        """Проверрить, одинаковые ли типы предметов."""
        ...

    # --- using_item ---

    def using_item(self, s: UseState[Item]) -> bool:
        """Длинется ли использование предмета сейчас."""
        ...

    # --- used_hand ---

    def used_hand(self, s: UseState[Item]) -> int:
        """Вернуть номер руки (0 = main, 1 = offhand)."""
        ...

    # --- hand_item ---

    def hand_item(self, s: UseState[Item], hand: int) -> Item:
        """Вернуть предмет в указанной руке."""
        ...

    # --- set_hand_item ---

    def set_hand_item(self, s: UseState[Item], hand: int, item: Item) -> None:
        """Установить предмет в руку."""
        ...

    # --- level ---

    def level(self, s: UseState[Item]) -> object:
        """Вернуть уровень мира."""
        ...

    # --- is_client ---

    def is_client(self, s: UseState[Item], level: object) -> bool:
        """Проверрить, является ли уровень клиентским."""
        ...

    # --- remaining_ticks ---

    def remaining_ticks(self, s: UseState[Item]) -> int:
        """Вернуть оставшиеся тики использования."""
        ...

    # --- item_tick ---

    def item_tick(self, s: UseState[Item], item: Item, level: object, remaining: int) -> None:
        """Тик предмета (эффекты, гравитация и т.д.)."""
        ...

    # --- use_on_release ---

    def use_on_release(self, s: UseState[Item], item: Item) -> bool:
        """Вызвать при релизе использования."""
        ...

    # --- release_item ---

    def release_item(self, s: UseState[Item], item: Item, level: object, remaining: int) -> None:
        """Релиз предмета."""
        ...

    # --- finish_item ---

    def finish_item(self, s: UseState[Item], item: Item, level: object) -> Item:
        """Завершить использование предмета и вернуть результат."""
        ...

    # --- set_using_flag ---

    def set_using_flag(self, s: UseState[Item], using: bool) -> None:
        """Установить флаг активного использования."""
        ...

    # --- finish_vibration ---

    def finish_vibration(self, s: UseState[Item], item: Item) -> None:
        """Запуск вибрации."""
        ...

    # --- update_using_item ---

    def update_using_item(self, s: UseState[Item], item: Item) -> None:
        """Обновить состояние использования."""
        ...

    # --- complete_using_item ---

    def complete_using_item(self, s: UseState[Item]) -> None:
        """Завершить использование предмета."""
        ...

    # --- release_using_item ---

    def release_using_item(self, s: UseState[Item]) -> None:
        """Релиз использования."""
        ...

    # --- stop_using_item ---

    def stop_using_item(self, s: UseState[Item]) -> None:
        """Остановить использование."""
        ...


# ---------------------------------------------------------------------------
# Функция tick — тик активного использования
# ---------------------------------------------------------------------------

def tick(w: UseLifecycleWorld, s: UseState[Item]) -> None:
    """``item_use_lifecycle.rs:tick`` — тик активного использования предмета.

    Выполняет один шаг цикла использования: проверяет, используется ли предмет,
    обновляет руку и вызывает item_tick. Если тики исчерпаны — вызывает update,
    которая в конце вызывает complete.

    Алгоритм:
      1. Если используется предмет (using_item), продолжаем тик:
         a. Получаем руку и-held предмет
         b. Если тип предмета тот же (same_item_type):
            - Получаем руку снова
            - Обновляем предмет в UseState через hand_item
            - Вызываем update_using_item
         c. Иначе (тип изменился):
            - Останавливаем использование через stop_using_item
      2. Иначе (не используется): ничего не делаем (no-op).
    """
    if w.using_item(s):
        hand = w.used_hand(s)
        held = w.hand_item(s, hand)
        if w.same_item_type(held, s.item):
            hand = w.used_hand(s)
            s.item = w.hand_item(s, hand)
            w.update_using_item(s, s.item)
        else:
            w.stop_using_item(s)


# ---------------------------------------------------------------------------
# Функция update — обновление состояния использования
# ---------------------------------------------------------------------------

def update(w: UseLifecycleWorld, s: UseState[Item], item: Item) -> None:
    """``item_use_lifecycle.rs:update`` — обновление состояния использования.

    Выполняет один тик использования:
      1. Получаем уровень мира и оставшиеся тики
      2. Вызываем item_tick (эффекты, гравитация)
      3. Уменьшаем remaining на 1 (wrapping_sub_i32 как в Rust)
      4. Если remaining стал 0:
         - Если не клиент и use_on_release не требует релиз — вызываем complete
    """
    level = w.level(s)
    remaining = w.remaining_ticks(s)
    w.item_tick(s, item, level, remaining)
    s.remaining = wrapping_sub_i32(s.remaining, 1)
    if s.remaining == 0:
        level = w.level(s)
        if not w.is_client(s, level) and not w.use_on_release(s, item):
            w.complete_using_item(s)


# ---------------------------------------------------------------------------
# Функция complete — завершение использования
# ---------------------------------------------------------------------------

def complete(w: UseLifecycleWorld, s: UseState[Item]) -> None:
    """``item_use_lifecycle.rs:complete`` — завершение использования предмета.

    Если мы на клиенте и предмет больше не используется — возвращаемся сразу.
    Иначе проверяем, изменился ли предмет в руке, и вызываем finish_item
    для применения эффектов (еда, стрелы и т.д.).
    """
    level = w.level(s)
    # Клиентский короткий путь: если предмет уже не используется — выходим
    if w.is_client(s, level) and not w.using_item(s):
        return
    hand = w.used_hand(s)
    original = s.item
    # Если предмет в руке изменился — релизим и выходим
    if original != w.hand_item(s, hand):
        w.release_using_item(s)
        return
    # Если предмет не пустой и всё ещё используется — завершаем
    if not w.is_empty(s.item) and w.using_item(s):
        item = s.item
        level = w.level(s)
        result = w.finish_item(s, item, level)
        # Если результат отличается от текущего предмета — обновляем руку
        if result != s.item:
            w.set_hand_item(s, hand, result)
        # Всегда останавливаем использование после finish_item
        w.stop_using_item(s)


# ---------------------------------------------------------------------------
# Функция release — отмена использования
# ---------------------------------------------------------------------------

def release(w: UseLifecycleWorld, s: UseState[Item]) -> None:
    """``item_use_lifecycle.rs:release`` — отмена использования предмета.

    Если предмет не пустой и его тип совпадает с held-item:
      - Меняем предмет на held
      - Вызываем release_item с текущими тиками
      - Если use_on_release вернул True — делаем тик (продолжаем использование)
    Всегда останавливаем использование в конце (stop_using_item).
    """
    hand = w.used_hand(s)
    held = w.hand_item(s, hand)
    if not w.is_empty(s.item) and w.same_item_type(held, s.item):
        s.item = held
        item = s.item
        level = w.level(s)
        remaining = w.remaining_ticks(s)
        w.release_item(s, item, level, remaining)
        if w.use_on_release(s, s.item):
            tick(w, s)
    w.stop_using_item(s)


# ---------------------------------------------------------------------------
# Функция stop — остановка использования
# ---------------------------------------------------------------------------

def stop(w: UseLifecycleWorld, s: UseState[Item]) -> None:
    """``item_use_lifecycle.rs:stop`` — остановка использования предмета.

    Сбрасывает состояние использования:
      1. Если не клиент — сбрасываем флаг использования и флаг kinetic enemies
      2. Если использование было активное — вызываем finish_vibration
      3. Устанавливаем пустой предмет
      4. Обнуляем remaining тики
    """
    level = w.level(s)
    if not w.is_client(s, level):
        using = w.using_item(s)
        s.has_recent_kinetic_enemies = False
        w.set_using_flag(s, False)
        if using:
            w.finish_vibration(s, s.item)
    s.item = w.empty_item()
    s.remaining = 0