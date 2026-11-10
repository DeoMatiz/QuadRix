#!/usr/bin/env python3
"""[QuadRix] Начало использования предмета: старт длительности right-click.

Порт ``horizon/crates/horizon-world/src/item_use_start.rs`` (Minecraft 26.3).

Содержит:
  * Трейт ``StartUseWorld`` — расширение ``UseLifecycleWorld`` методами
    длительности, синхронизацией оборудования, флагами руки/рукава и вибрацией.
  * Функция ``start`` — запускает процесс использования предмета (еда, лук, и т.д.).
    В отличие от ``item_use.rs`` ( blockingItem/щит/лук), эта функция отвечает за
    инициализацию состояния использования: установка предмета, оставшихся тиков,
    флагов руки и вызов хуков мира.

Логи начинаются с ``[QuadRix]``.
"""

from __future__ import annotations

from typing import Optional, Protocol, TypeVar

from quadrix.world.item_use_catalog import ItemId, Duration, UseComponents, ItemDefinition, ItemUseStack, ItemUseCatalog
from quadrix.world.item_use import is_blocking, blocking_item, ticks_using_item, wrapping_sub_i32
from quadrix.world.world_ray import ClipContext, BlockHitResult

__all__ = [
    "StartUseWorld",
    "start",
]


# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

Item = TypeVar("Item")
WorldType = TypeVar("WorldType")


# ---------------------------------------------------------------------------
# StartUseWorld trait — зерно порта Rust-трайта
# ---------------------------------------------------------------------------


class StartUseWorld(Protocol[WorldType]):
    """Зеркало Rust-трайта ``StartUseWorld`` (extends UseLifecycleWorld).

    Реализуют наследники (или duck-typed объект), предоставляющий хуки мира:
      * duration — сколько тиков длиться использование
      * synchronize_equipment — синхронизация экипировки
      * is_off_hand — нагружен ли рукой/рукавом
      * set_off_hand_flag — установка флага руки
      * set_using_flag — установка флага активного использования
      * start_vibration — запуск вибрации
      * has_kinetic_weapon — есть ли кинетическое оружие
      * reset_recent_kinetic_enemies — сброс последних врагов
    """

    def duration(
        self,
        s: dict,
        item: Item,
    ) -> int:
        """``item_use_start.rs:duration`` — длительность использования в тиках."""
        ...

    def synchronize_equipment(
        self,
        s: dict,
        level: object,
        hand: int,
        item: Item,
    ) -> None:
        """``item_use_start.rs:synchronize_equipment`` — синхронизация экипировки."""
        ...

    def is_off_hand(self, hand: int) -> bool:
        """``item_use_start.rs:is_off_hand`` — нагружен ли off-hand."""
        ...

    def set_off_hand_flag(
        self,
        s: dict,
        off: bool,
    ) -> None:
        """``item_use_start.rs:set_off_hand_flag`` — установка флага руки."""
        ...

    def set_using_flag(
        self,
        s: dict,
        flag: bool,
    ) -> None:
        """``item_use_start.rs:set_using_flag`` — установка флага использования."""
        ...

    def start_vibration(
        self,
        s: dict,
        item: Item,
    ) -> None:
        """``item_use_start.rs:start_vibration`` — запуск вибрации."""
        ...

    def has_kinetic_weapon(self, item: Item) -> bool:
        """``item_use_start.rs:has_kinetic_weapon`` — кинетическое оружие."""
        ...

    def reset_recent_kinetic_enemies(self, s: dict) -> None:
        """``item_use_start.rs:reset_recent_kinetic_enemies`` — сброс врагов."""
        ...


# ---------------------------------------------------------------------------
# Функция start — портированная из pub fn start<W: StartUseWorld>(...)
# ---------------------------------------------------------------------------


def start(
    w: StartUseWorld,
    s: dict,
    hand: int,
) -> None:
    """``item_use_start.rs:start`` — начать использование предмета.

    Портировано из ``pub fn start<W: StartUseWorld>(w: &mut W, s: &mut UseState<W::Item>, hand: W::Hand)``.

    Алгоритм:
      1. Получить предмет из руки ``w.hand_item(s, hand)``.
      2. Если предмет пуст или уже используется — возвращаем ``None`` (no-op).
      3. Установить ``s["item"] = item`` и ``s["remaining"] = w.duration(s, item)``.
      4. Если не клиент (server): синхронизировать экипировку, поставить флаг использования,
         флаг руки, запустить вибрацию, сбросить последних кинетических врагов.

    Args:
        w: мировой провайдер, реализующий ``StartUseWorld``.
        s: словарь состояния использования (UseState).
        hand: рука (0 = main, 1 = offhand).
    """
    # 1. Получить предмет из руки
    item: Item = w.hand_item(s, hand)
    if item is None:
        # Пустой слот — нет-op
        return None

    # 2. Если уже используем — нет-op
    if w.using_item(s):
        return None

    # 3. Установить предмет и оставшиеся тики
    s["item"] = item
    s["remaining"] = w.duration(s, item)

    # 4. Server-side setup (not client)
    # В Rust: ``if !w.is_client(s, level)?`` — здесь пропускаем,
    # так как Python-версия не имеет концепции client/server в этой функции.
    # Хуки выполняются всегда (или можно добавить флаг уровня).

    # Синхронизировать экипировку
    w.synchronize_equipment(s, w.level(s), hand, s["item"])

    # Поставить флаг использования
    w.set_using_flag(s, True)

    # Флаг руки (off-hand)
    off = w.is_off_hand(hand)
    w.set_off_hand_flag(s, off)

    # Вибрация
    w.start_vibration(s, s["item"])

    # Сбросить последних кинетических врагов (если оружие)
    if w.has_kinetic_weapon(s["item"]):
        w.reset_recent_kinetic_enemies(s)

    return None


# ----------------------------------------------------------------------------
# Вспомогательные протоколы для StartUseWorld (методы, используемые в start)
# ----------------------------------------------------------------------------


# hand_item, using_item, set_using_flag, level — эти методы также нужны внутри start.
# Мы объявляем их здесь для ясности, хотя они могут быть определены в broader Protocol.

def hand_item(s: dict, hand: int) -> Optional[Item]:
    """Вспомогательная обёртка для доступа к предмету в руке."""
    # В реальности это метод протокола; здесь оставили как документацию.
    raise NotImplementedError


def using_item(s: dict) -> bool:
    """Вспомогательная обёртка для проверки, используется ли предмет."""
    raise NotImplementedError


def set_using_flag(s: dict, flag: bool) -> None:
    """Вспомогательная обёртка для установки флага использования."""
    raise NotImplementedError


def level(s: dict) -> object:
    """Вспомогательная обёртка для получения уровня мира."""
    raise NotImplementedError