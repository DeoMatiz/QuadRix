#!/usr/bin/env python3
"""[QuadRix] Тесты quadrix.world.item_use_lifecycle (порт item_use_lifecycle.rs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quadrix.world.item_use_lifecycle import (
    UseState,
    UseLifecycleWorld,
    tick,
    update,
    complete,
    release,
    stop,
)
from quadrix.world.item_use_start import start, StartUseWorld


# ---------------------------------------------------------------------------
# Mock Implementor UseLifecycleWorld для тестов
# ---------------------------------------------------------------------------

@dataclass
class FakeUseState:
    """Вспомогательная структура состояния для фейкового мира."""
    item: object = "minecraft:carrot_on_a_stick"
    remaining: int = 600
    has_recent_kinetic_enemies: bool = False


class FakeWorld(UseLifecycleWorld):
    """Mock-имplementor UseLifecycleWorld для тестов item_use_lifecycle."""

    def __init__(self, *, item_result: object = "minecraft:carrot_on_a_stick",
                 using_result: bool = True, remaining_val: int = 600,
                 is_client_result: bool = False) -> None:
        self._item_result = item_result
        self._using_result = using_result
        self._remaining_val = remaining_val
        self._is_client_result = is_client_result
        self._state: FakeUseState = FakeUseState(remaining=remaining_val)

    # --- UseLifecycleWorld methods ---

    def empty_item(self) -> object:
        return "minecraft:air"

    def is_empty(self, item: object) -> bool:
        return item == "minecraft:air" or item is None

    def same_item_type(self, a: object, b: object) -> bool:
        return type(a) is type(b) and a == b

    def using_item(self, s: UseState[object]) -> bool:
        return self._using_result

    def used_hand(self, s: UseState[object]) -> int:
        return 0

    def hand_item(self, s: UseState[object], hand: int) -> object:
        return self._item_result

    def set_hand_item(self, s: UseState[object], hand: int, item: object) -> None:
        s.item = item

    def level(self, s: UseState[object]) -> dict:
        return {"test": True}

    def is_client(self, s: UseState[object], level: object) -> bool:
        return self._is_client_result

    def remaining_ticks(self, s: UseState[object]) -> int:
        return s.remaining

    def item_tick(self, s: UseState[object], item: object, level: object, remaining: int) -> None:
        """Mock item_tick: ничего не делаем (тестовый случай)."""
        pass

    def use_on_release(self, s: UseState[object], item: object) -> bool:
        return False

    def release_item(self, s: UseState[object], item: object, level: object, remaining: int) -> None:
        """Mock release_item: ничего не делаем."""
        pass

    def finish_item(self, s: UseState[object], item: object, level: object) -> object:
        """Mock finish_item: возвращаем тот же предмет."""
        return item

    def set_using_flag(self, s: UseState[object], using: bool) -> None:
        pass

    def finish_vibration(self, s: UseState[object], item: object) -> None:
        pass

    def update_using_item(self, s: UseState[object], item: object) -> None:
        pass

    def complete_using_item(self, s: UseState[object]) -> None:
        """Mock complete_using_item: сбрасываем state."""
        s.item = "minecraft:air"
        s.remaining = 0
        s.has_recent_kinetic_enemies = False

    def release_using_item(self, s: UseState[object]) -> None:
        """Mock release_using_item: ничего не делаем."""
        pass

    def stop_using_item(self, s: UseState[object]) -> None:
        """Останавливает использование: сбрасываем state."""
        s.item = "minecraft:air"
        s.remaining = 0
        s.has_recent_kinetic_enemies = False


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

def test_update_remaining_decreases() -> None:
    """1. Обновление использования: remaining_ticks уменьшается.

    После вызова update remaining должен уменьшиться на 1 (wrapping_sub_i32).
    """
    world = FakeWorld(using_result=True, remaining_val=600)
    state = UseState(item="minecraft:carrot_on_a_stick", remaining=600)
    update(world, state, item="minecraft:carrot_on_a_stick")
    assert state.remaining == 599, (
        f"Expected remaining=599 after update, got {state.remaining}"
    )


def test_tick_to_zero_completion() -> None:
    """2. Тик до 0 → завершение (complete/stop).

    Когда remaining достигает 0, вызов complete должен сбросить state.
    """
    world = FakeWorld(using_result=True, remaining_val=1, is_client_result=False)
    state = UseState(item="minecraft:carrot_on_a_stick", remaining=1)
    complete(world, state)
    # После complete state должен быть сброшен
    assert state.remaining == 0, (
        f"Expected remaining=0 after complete, got {state.remaining}"
    )
    assert state.item == "minecraft:air", (
        f"Expected item=air after complete, got {state.item}"
    )


def test_complete_food_consumption() -> None:
    """3. Завершение еды → consume / эффект.

    В текущем портировании finish_item возвращает тот же предмет,
    а stop сбрасывает state. Это модель поведения для食品-items.
    """
    world = FakeWorld(using_result=True, remaining_val=600, is_client_result=False)
    state = UseState(item="minecraft:carrot_on_a_stick", remaining=600)
    # Сначала используем tick 600 раз, чтобы remaining стал 0
    for _ in range(600):
        tick(world, state)
    # Теперь remaining == 0, вызываем complete
    complete(world, state)
    # После complete state должен быть сброшен
    assert state.remaining == 0
    assert state.item == "minecraft:air"


def test_complete_bow_shooting_fallback() -> None:
    """4. Завершение лука → выстрел.

    В портированном коде finish_item возвращает тот же предмет (mock-режим).
    В реальной реализации здесь был бы выстрел стрелой.
    """
    world = FakeWorld(using_result=True, remaining_val=72000, is_client_result=False)
    state = UseState(item="minecraft:bow", remaining=72000)
    # Вызываем tick 72000 раз, чтобы remaining стал 0
    for _ in range(72000):
        tick(world, state)
    # remaining теперь 0, вызываем complete
    complete(world, state)
    # В mock-режиме state сбрасывается, но в реальности был бы выстрел
    assert state.remaining == 0


def test_release_cancels_usage() -> None:
    """5. Отмена использования (release) → state сброшен.

    Вызов release должен сбросить состояние использования (item = air, remaining = 0).
    """
    world = FakeWorld(using_result=True, remaining_val=600, is_client_result=False)
    state = UseState(item="minecraft:carrot_on_a_stick", remaining=600)
    release(world, state)
    # После release state должен быть сброшен
    assert state.remaining == 0, (
        f"Expected remaining=0 after release, got {state.remaining}"
    )
    assert state.item == "minecraft:air", (
        f"Expected item=air after release, got {state.item}"
    )


def test_no_active_item_noop() -> None:
    """6. Использование без active item → no-op / None.

    Если в UseState пустой предмет (air), tick и complete должны
    работать как no-op без ошибок.
    """
    world = FakeWorld(using_result=False, remaining_val=600, is_client_result=False)
    state = UseState(item="minecraft:air", remaining=600)
    # tick с пустым предметом — no-op
    tick(world, state)
    assert state.remaining == 600, (
        f"Expected remaining=600 after tick with air, got {state.remaining}"
    )
    # complete с пустым предметом — no-op (ранний возврат из-за is_client check)
    complete(world, state)
    assert state.remaining == 600


def test_stop_resets_state() -> None:
    """Дополнительно: stop сбрасывает состояние использования.

    Вызов stop должен обнулить remaining и поставить пустой предмет,
    независимо от того, клиент мы или сервер.
    """
    world = FakeWorld(using_result=True, remaining_val=600, is_client_result=True)
    state = UseState(item="minecraft:carrot_on_a_stick", remaining=600)
    stop(world, state)
    assert state.remaining == 0
    assert state.item == "minecraft:air"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])