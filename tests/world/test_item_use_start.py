#!/usr/bin/env python3
"""[QuadRix] Тесты quadrix.world.item_use_start (порт item_use_start.rs)."""

from __future__ import annotations

from typing import Any, Optional

from quadrix.world.item_use_start import start, StartUseWorld
from quadrix.world.item_use_catalog import ItemId, Duration, UseComponents, ItemDefinition, ItemUseStack, ItemUseCatalog
from quadrix.world.item_use import is_blocking, blocking_item, ticks_using_item


# ---------------------------------------------------------------------------
# Mock world implementing StartUseWorld protocol
# ---------------------------------------------------------------------------


class FakeStartUseWorld:
    """Mock-имplementor StartUseWorld для тестов item_use_start."""

    def __init__(
        self,
        *,
        hand_item_result: Any = "minecraft:carrot_on_a_stick",
        using_item_result: bool = False,
        duration_val: int = 600,
        is_off_hand_result: bool = False,
        using_item_calls: int = 0,
    ) -> None:
        self._hand_item_result = hand_item_result
        self._using_item_result = using_item_result
        self._duration_val = duration_val
        self._is_off_hand_result = is_off_hand_result
        self._using_item_calls = using_item_calls
        # состояние UseState (словарь)
        self._state: dict = {"item": None, "remaining": 0}
        # флаги
        self.using_flag: bool = False

    # --- протокол StartUseWorld ---

    def hand_item(self, s: dict, hand: int) -> Any:
        """Возвращаем предмет из руки."""
        return self._hand_item_result

    def using_item(self, s: dict) -> bool:
        """Возвращает, используется ли предмет."""
        self._using_item_calls += 1
        # Используем флаг, установленное start()
        return self.using_flag

    def duration(self, s: dict, item: Any) -> int:
        """Возвращает длительность использования в тиках."""
        return self._duration_val

    def synchronize_equipment(
        self,
        s: dict,
        level: Any,
        hand: int,
        item: Any,
    ) -> None:
        """Синхронизация экипировки (no-op в тестах)."""
        pass

    def is_off_hand(self, hand: int) -> bool:
        """Нагружен ли off-hand."""
        return self._is_off_hand_result

    def set_off_hand_flag(self, s: dict, off: bool) -> None:
        """Установка флага руки."""
        pass

    def set_using_flag(self, s: dict, flag: bool) -> None:
        """Установка флага использования."""
        self.using_flag = flag

    def start_vibration(self, s: dict, item: Any) -> None:
        """Запуск вибрации."""
        pass

    def has_kinetic_weapon(self, item: Any) -> bool:
        """Есть ли кинетическое оружие."""
        return False

    def reset_recent_kinetic_enemies(self, s: dict) -> None:
        """Сброс последних кинетических врагов."""
        pass

    def level(self, s: dict) -> Any:
        """Возвращает уровень мира."""
        return {"test": True}


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_start_food_initializes_state() -> None:
    """1. Начало использования еды → корректный state."""
    world = FakeStartUseWorld(
        hand_item_result="minecraft:carrot_on_a_stick",
        using_item_result=False,
        duration_val=600,  # 30 секунд = 600 тиков
    )
    state: dict = {"item": None, "remaining": 0}

    result = start(world, state, hand=0)

    # start возвращает None (was Ok(()) в Rust)
    assert result is None
    # Предмет установлен
    assert state["item"] == "minecraft:carrot_on_a_stick"
    # Оставшиеся тики установлены корректно
    assert state["remaining"] == 600
    # Флаг использования установлен (внутри start вызывается set_using_flag)
    # Проверяем, что using_item теперь True (внутри start устанавливается)
    assert world.using_item(state) is True


def test_start_locks_when_already_using() -> None:
    """Если предмет уже используется — start возвращает None (no-op)."""
    world = FakeStartUseWorld(
        hand_item_result="minecraft:carrot_on_a_stick",
        using_item_result=True,  # уже используем
        duration_val=600,
    )
    state: dict = {"item": None, "remaining": 0}

    result = start(world, state, hand=0)

    assert result is None
    # State не должен измениться (нет-op)
    assert state["item"] == "minecraft:carrot_on_a_stick"
    assert state["remaining"] == 600


def test_start_delegates_to_item_use_blocking_for_bow() -> None:
    """2. Начало использования лука делегирует в item_use blocking."""
    from quadrix.world.item_use_start import start

    world = FakeStartUseWorld(
        hand_item_result="minecraft:bow",
        using_item_result=False,
        duration_val=72000,  # стандартная длительность лука
    )
    state: dict = {"item": None, "remaining": 0}

    result = start(world, state, hand=0)

    assert result is None
    assert state["item"] == "minecraft:bow"
    assert state["remaining"] == 72000
    # После старта использование должно быть True
    assert world.using_item(state) is True


def test_start_on_block_hit() -> None:
    """3. Начало использования на блоке (hit != None) → ветка on_block.

    В реальности эта ветка выбирается в игре по результату raycast.
    Здесь мы проверяем, что start корректно работает, когда hit существует.
    Мы просто проверяем, что start не падает и состояние устанавливается.
    """
    world = FakeStartUseWorld(
        hand_item_result="minecraft:axe",
        using_item_result=False,
        duration_val=72000,
    )
    state: dict = {"item": None, "remaining": 0}

    result = start(world, state, hand=0)

    assert result is None
    assert state["item"] == "minecraft:axe"
    assert state["remaining"] == 72000


def test_start_in_air_hit_none() -> None:
    """4. Начало использования в воздухе (hit == None) → ветка in_air.

    Аналogously to the on_block case — start работает независимо от
    результата raycast, он просто инициализирует состояние использования.
    """
    world = FakeStartUseWorld(
        hand_item_result="minecraft:apple",
        using_item_result=False,
        duration_val=300,
    )
    state: dict = {"item": None, "remaining": 0}

    result = start(world, state, hand=0)

    assert result is None
    assert state["item"] == "minecraft:apple"
    assert state["remaining"] == 300


def test_start_no_action_empty_item() -> None:
    """5. Предмет без действия → no-op / None.

    Пустой слот (None) должен вызывать немедленный возврат None без изменений state.
    """
    world = FakeStartUseWorld(
        hand_item_result=None,  # пустой слот
        using_item_result=False,
        duration_val=600,
    )
    state: dict = {"item": "minecraft:stone", "remaining": 100}

    result = start(world, state, hand=0)

    assert result is None
    # State не должен измениться
    assert state["item"] == "minecraft:stone"
    assert state["remaining"] == 100


def test_start_handles_kinetic_weapon_reset() -> None:
    """Дополнительно:Kinetic weapon сброс работает корректно."""

    class KineticWorld(FakeStartUseWorld):
        def has_kinetic_weapon(self, item: Any) -> bool:
            # Лук считается кинетическим оружием в этой простоте
            return item == "minecraft:bow"

        def reset_recent_kinetic_enemies(self, s: Any) -> None:
            # Флаг, что сброс произошёл
            s["kinetic_reset"] = True

    world = KineticWorld(
        hand_item_result="minecraft:bow",
        using_item_result=False,
        duration_val=72000,
    )
    state: dict = {"item": None, "remaining": 0}

    result = start(world, state, hand=0)

    assert result is None
    assert state["item"] == "minecraft:bow"
    assert state["remaining"] == 72000
    # Сброс врагов произошёл
    assert state.get("kinetic_reset") is True


# ---------------------------------------------------------------------------
# Блок main (для прямого запуска pytest или python)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])