#!/usr/bin/env python3
"""[QuadRix] Блокирующее использование предмета (щит/лук): тики и допуск.

Точный порт ``horizon/crates/horizon-world/src/item_use.rs``.

ВАЖНО про содержимое Rust-файла
--------------------------------
В Horizon ``item_use.rs`` — это НЕ right-click dispatch (еда, вёдра, кровати,
семена, зажигалка, ножницы). Это слой, который отвечает на вопросы:

  * использует ли живой игрок предмет прямо сейчас (``using_item``);
  * какой предмет блокирует (``blocking_item``);
  * сколько тиков уже длится использование (``ticks_using_item``,
    ``ticks_using_item_partial``).

Right-click-логика живёт в других rust-файлах:
``item_use_catalog.rs`` (компоненты consumable/block/bucket), ``inventory_use.rs``,
``item_use_start.rs``, ``item_use_lifecycle.rs``, ``item_after_use.rs``,
``food.rs``/``consumable.rs``. Они портируются отдельными сессиями. Здесь
сохранены ровно те имена и формулы, что есть в Rust; никаких ``UseContext`` /
``UseResult`` в этом файле Rust нет.

Соответствие Rust → Python
--------------------------
  * ``trait ItemUseWorld`` → :class:`ItemUseWorld` (базовый класс с двумя
    готовыми ``query_*``-методами; хуки реализует наследник либо duck-typed
    объект);
  * ``blocking_item``, ``is_blocking``, ``ticks_using_item``,
    ``ticks_using_item_partial`` → одноимённые функции;
  * ``i32::wrapping_sub`` → :func:`wrapping_sub_i32` (переполнение как в Rust).

Ошибки: в Rust методы возвращают ``Result``, Python-хуки выбрасывают исключение.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, TypeVar

__all__ = [
    "INT32_MAX",
    "INT32_MIN",
    "ItemUseWorld",
    "blocking_item",
    "is_blocking",
    "ticks_using_item",
    "ticks_using_item_partial",
    "wrapping_sub_i32",
]

# Границы i32 — нужны для точного поведения Rust ``wrapping_sub``.
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
_INT32_RANGE = 2**32

Item = TypeVar("Item")
ItemType = TypeVar("ItemType")


class ItemUseWorld(Protocol[Item, ItemType]):
    """Зеркало Rust-трейта ``ItemUseWorld``.

    Наследник (или любой duck-typed объект) реализует хуки; ``query_*``
    повторяют default-методы трейта и делегируют свободным функциям модуля.
    """

    def using_item(self) -> bool:
        """``fn using_item`` — длится ли использование предмета сейчас."""
        ...

    def use_item(self) -> Item:
        """``fn use_item`` — предмет, который используется."""
        ...

    def blocking_delay(self, item: Item) -> Optional[int]:
        """``fn blocking_delay`` — задержка блокировки из компонента или None."""
        ...

    def item_type(self, item: Item) -> ItemType:
        """``fn item_type`` — тип предмета (для ``use_duration``)."""
        ...

    def use_duration(self, item_type: ItemType, item: Item) -> int:
        """``fn use_duration`` — полная длительность использования, в тиках."""
        ...

    def remaining_ticks(self) -> int:
        """``fn remaining_ticks`` — оставшиеся тики использования."""
        ...

    def remaining_ticks_virtual(self) -> int:
        """``fn remaining_ticks_virtual`` — виртуальные оставшиеся тики."""
        ...

    def query_blocking_item(self) -> Optional[Item]:
        """Default-метод Rust: ``blocking_item(self)``."""
        return blocking_item(self)

    def query_ticks_using_item(self) -> int:
        """Default-метод Rust: ``ticks_using_item(self)``."""
        return ticks_using_item(self)


def wrapping_sub_i32(a: int, b: int) -> int:
    """Точный аналог ``i32::wrapping_sub`` (переполнение по модулю 2**32)."""
    return ((a - b - INT32_MIN) % _INT32_RANGE) + INT32_MIN


def blocking_item(w: ItemUseWorld[Item, ItemType]) -> Optional[Item]:
    """Вернуть блокирующий предмет, если задержка уже выдержана.

    Порт ``pub fn blocking_item``:

    ``elapsed = duration.wrapping_sub(w.remaining_ticks())``;
    предмет блокирует, только если ``elapsed >= delay``.
    """
    if not w.using_item():
        return None

    # Rust: let Some(delay) = w.blocking_delay(w.use_item()) else { return None }
    delay = w.blocking_delay(w.use_item())
    if delay is None:
        return None

    item_type = w.item_type(w.use_item())
    item = w.use_item()
    duration = w.use_duration(item_type, item)
    elapsed = wrapping_sub_i32(duration, w.remaining_ticks())
    # Rust: (elapsed >= delay).then(|| w.use_item())
    return w.use_item() if elapsed >= delay else None


def is_blocking(w: ItemUseWorld[Item, ItemType]) -> bool:
    """``pub fn is_blocking`` — есть ли блокирующий предмет."""
    return blocking_item(w) is not None


def ticks_using_item(w: ItemUseWorld[Item, ItemType]) -> int:
    """``pub fn ticks_using_item`` — сколько тиков предмет уже используется."""
    if not w.using_item():
        return 0

    item = w.use_item()
    item_type = w.item_type(item)
    duration = w.use_duration(item_type, item)
    return wrapping_sub_i32(duration, w.remaining_ticks_virtual())


def ticks_using_item_partial(
    w: ItemUseWorld[Item, ItemType], partial: float
) -> float:
    """``pub fn ticks_using_item_partial`` — тики использования + ``partial``."""
    if not w.using_item():
        return 0.0
    # Rust: query_ticks_using_item()? as f32 + partial
    return float(ticks_using_item(w)) + float(partial)
