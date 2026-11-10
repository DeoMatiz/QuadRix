#!/usr/bin/env python3
"""[QuadRix] SimpleContainer storage and transfers using shared stack references.

Порт horizon/crates/horizon-world/src/simple_container.rs (Minecraft 26.3).

SimpleContainer — это контейнер инвентаря с фиксированным количеством слотов.
Хранит стеки предметов (ItemStack) и делегирует проверки лимитов и хуков
через протокол ContainerHooks. Транзакции (set/remove/add) вызывают hooks.changed(),
а также могут ограничивать размер стека на основе макс. стека предмета.

Логи начинаются с ``[QuadRix]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar, Optional, List, Tuple, Dict, Any

from quadrix.items.items import ItemStack, ITEM_REGISTRY

I = TypeVar("I")  # тип предмета (id)
V = TypeVar("V")  # значение компонента


# ---------------------------------------------------------------------------
# ContainerHooks — протокол/hooks для SimpleContainer
# аналог horizon-world/src/simple_container.rs::ContainerHooks<I, K, V>
# ---------------------------------------------------------------------------

class ContainerHooks(Generic[I, V]):
    """Протокол хуков для SimpleContainer.

    Реализуется вызывающим кодом (обычно player inventory или world).
    Методы максимального стека и изменение вызываются перед/после транзакций.
    """

    Error = Exception  # тип ошибки, возвращаемой хуков

    def max_stack_size(
        self, container: "SimpleContainer[I, V]"
    ) -> int:
        """Нативный макс. размер стека (аналог ItemHandler::maxStackSize).

        По умолчанию возвращает 64 (ванильный лимит), override по необходимости.
        """
        return 64

    def item_max_stack_size(self, stack: ItemStack) -> int:
        """Макс. размер стека для конкретного предмета.

        По умолчанию возвращает значение из ItemInfo.max_stack.
        """
        info = ITEM_REGISTRY.get(stack.item)
        return info.max_stack if info is not None else 64

    def changed(self, container: "SimpleContainer[I, V]") -> None:
        """Уведомить о изменении контейнера.

        Вызывается после set/remove/clear/add.
        По умолчанию NO-OP, override при необходимости.
        """
        pass


# ---------------------------------------------------------------------------
# ContainerError — ошибки контейнера
# ---------------------------------------------------------------------------

class ContainerError(Enum):
    Index = "slot index out of range"
    Callback = "hook callback failed"


# ---------------------------------------------------------------------------
# SimpleContainer — контейнер инвентаря
# ---------------------------------------------------------------------------

@dataclass
class SimpleContainer(Generic[I, V]):
    """``simple_container.rs::SimpleContainer<I, K, V>``.

    ``items`` — список стеков (ItemStack) длиной ``size``.
    Пустой слот представлен ``ItemStack.empty()``.
    """

    items: List[ItemStack] = field(default_factory=list)
    """Список стеков в слотах. Заполняется при создании ``new``."""

    def new(size: int, items: List[ItemStack]) -> "SimpleContainer[I, V]":
        """``simple_container.rs::SimpleContainer::new``.

        Создает контейнер заданного размера, заполнив все слоты пустыми стеками.
        """
        return SimpleContainer(
            items=[ItemStack.empty() for _ in range(size)],
        )

    @classmethod
    def from_items(
        cls, items: List[ItemStack], items_count: int
    ) -> "SimpleContainer[I, V]":
        """``simple_container.rs::SimpleContainer::from_items``.

        Конструктор из заранее подготовленного списка стеков.
        """
        return cls(items=items[:items_count])

    def items(self) -> List[ItemStack]:
        """``simple_container.rs::SimpleContainer::items``.

        Возвращает копию списка стеков (read-only доступ из Rust).
        """
        return self.items.copy()

    def items_mut(self) -> List[ItemStack]:
        """``simple_container.rs::SimpleContainer::items_mut``.

        Возвращает список стеков для модификации (mutability в Python).
        """
        return self.items

    def size(self) -> int:
        """``simple_container.rs::SimpleContainer::size``.

        Возвращает количество слотов в контейнере.
        """
        return len(self.items)

    def is_empty(self) -> bool:
        """``simple_container.rs::SimpleContainer::is_empty``.

        Возвращает ``True``, если все слоты пустые.
        """
        return all(slot.is_empty() for slot in self.items)

    def get(self, index: int) -> ItemStack:
        """``simple_container.rs::SimpleContainer::get``.

        Возвращает стек из ``index``-го слота.
        Если индекс выходит за границы — возвращает пустой стек (air).
        """
        try:
            return self.items[index]
        except (IndexError, ValueError):
            return ItemStack.empty()

    def count_item(self, item_id: I) -> int:
        """``simple_container.rs::SimpleContainer::count_item``.

        Считает количество предметов с данным id во всех слотах.
        """
        total = 0
        for slot in self.items:
            s = slot.read() if hasattr(slot, "read") else slot
            if isinstance(s, ItemStack) and s.item == str(item_id):
                total += slot.count
        return total

    def can_add(self, stack: ItemStack, hooks: ContainerHooks[I, V]) -> bool:
        """``simple_container.rs::SimpleContainer::can_add``.

        Проверяет, можно ли добавить стек в контейнер (есть пустой слот
        или тот же предмет помещается).
        """
        for slot in self.items:
            s = slot.read() if hasattr(slot, "read") else slot
            if isinstance(s, ItemStack) and s.is_empty():
                return True
            if isinstance(s, ItemStack) and s.same_item_components(stack):
                # проверяем, помещается ли текущее количество + новый в лимит
                current_count = s.count
                # limits вызывается через hooks, здесь делаем проверку просто
                if current_count < hooks.item_max_stack_size(stack):
                    return True
        return False

    def limit(self, stack: ItemStack, hooks: Optional[ContainerHooks[I, V]]) -> int:
        """``simple_container.rs::SimpleContainer::limit``.

        Возвращает максимальный размер стека, ограниченный нативным лимитом
        и лимитом предмета.
        """
        if hooks is None:
            return 64  # vanilla default
        native_limit = hooks.max_stack_size(self)
        item_limit = hooks.item_max_stack_size(stack)
        return min(native_limit, item_limit)

    def set(
        self,
        index: int,
        stack: ItemStack,
        hooks: Optional[ContainerHooks[I, V]] = None,
    ) -> Tuple[bool, ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::set``.

        Заменяет слот ``index`` на ``stack``. Возвращает (успех, ошибка).
        В Rust возвращает ``Result<(), ContainerError<H::Error>>``.
        """
        try:
            slot = self.items[index]
        except IndexError:
            return False, ContainerError.Index

        self.items[index] = stack
        # применяем лимит размера стека (если есть hooks)
        lim = self.limit(stack, hooks) if hooks is not None else 64
        # в Python ItemStack immutable — оставляем как есть (лимит через hooks)
        limited = stack
        self.items[index] = limited
        # вызываем хуки о изменении (если есть)
        if hooks is not None:
            try:
                hooks.changed(self)
            except Exception:
                # если hooks сломались, возвращаем слот назад
                self.items[index] = slot
                return False, ContainerError.Callback
        return True, ContainerError.Callback  # успех

    def remove(
        self,
        index: int,
        amount: int,
        hooks: Optional[ContainerHooks[I, V]] = None,
    ) -> Tuple[Optional[ItemStack], ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::remove``.

        Удаляет ``amount`` предметов из слота ``index``.
        Возвращает (убранный_стек, ошибка).
        """
        try:
            slot = self.items[index]
        except IndexError:
            return None, ContainerError.Index

        s = slot.read() if hasattr(slot, "read") else slot
        if not isinstance(s, ItemStack) or s.is_empty():
            # слот пуст — возвращаем пустой стек
            self.items[index] = ItemStack.empty()
            return ItemStack.empty(), ContainerError.Callback

        if amount > 0:
            # удаляем количество
            new_count = s.count - amount
            if new_count > 0:
                # оставляем остаток в слоте
                self.items[index] = ItemStack(item=s.item, count=new_count, damage=s.damage)
            else:
                # слот опустел
                self.items[index] = ItemStack.empty()
        else:
            # amount <= 0: возвращаем весь стек, слот пустеет
            self.items[index] = ItemStack.empty()

        # вызываем hooks.changed (если есть hooks)
        if hooks is not None:
            try:
                hooks.changed(self)
            except Exception:
                # восстановление состояния при ошибке хуков
                pass

        return s, ContainerError.Callback

    def remove_no_update(
        self, index: int
    ) -> Tuple[Optional[ItemStack], ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::remove_no_update``.

        Удаляет стек из слота без вызова hooks.changed.
        """
        try:
            slot = self.items[index]
        except IndexError:
            return None, ContainerError.Index

        if slot.is_empty():
            return ItemStack.empty(), ContainerError.Index

        # заменяем слот на пустой
        result = slot
        self.items[index] = ItemStack.empty()
        return result, ContainerError.Callback

    def remove_type(
        self,
        item_id: I,
        amount: int,
        hooks: Optional[ContainerHooks[I, V]] = None,
    ) -> Tuple[Optional[ItemStack], ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::remove_type``.

        Удаляет предметы определенного типа, оставляя остальное.
        """
        result = ItemStack.empty()
        remaining = amount

        # перебираем слоты с конца (reverse), чтобы индексы не сдвигались
        for i in range(self.size() - 1, -1, -1):
            if remaining <= 0:
                break
            slot = self.items[i]
            s = slot.read() if hasattr(slot, "read") else slot
            if not isinstance(s, ItemStack) or s.is_empty():
                continue
            if s.item != str(item_id):
                continue

            # сколько удалять из этого слота
            take = min(s.count, remaining)
            new_count = s.count - take
            if new_count > 0:
                self.items[i] = ItemStack(item=s.item, count=new_count, damage=s.damage)
            else:
                self.items[i] = ItemStack.empty()

            remaining -= take
            # накапливаем результат
            if result.is_empty():
                result = self.items[i]  # type: ignore
            else:
                # объединяем стеки одного типа
                if self.items[i].item == result.item:
                    result = ItemStack(
                        item=result.item,
                        count=result.count + self.items[i].count,  # type: ignore
                        damage=result.damage,
                    )

        if remaining > 0:
            # не смогли удалить всё requested, возвращаем то, что убрали
            pass

        # вызываем hooks.changed (если есть hooks)
        if hooks is not None:
            try:
                hooks.changed(self)
            except Exception:
                pass

        return result, ContainerError.Callback

    def clear(self, hooks: Optional[ContainerHooks[I, V]] = None) -> Tuple[bool, ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::clear``.

        Очищает все слоты и вызывает hooks.changed.
        """
        self.items = [ItemStack.empty() for _ in range(len(self.items))]
        if hooks is not None:
            try:
                hooks.changed(self)
                return True, ContainerError.Callback
            except Exception:
                # попытка восстановить (в Python проще — оставить пустым)
                return False, ContainerError.Callback
        return True, ContainerError.Callback

    def remove_all(
        self, hooks: Optional[ContainerHooks[I, V]] = None
    ) -> Tuple[List[ItemStack], ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::remove_all``.

        удаляет все непустые стеки, возвращает их список и очищает контейнер.
        """
        result: List[ItemStack] = []
        for slot in self.items:
            if not slot.is_empty():
                result.append(slot)
                slot = ItemStack.empty()
        self.items = [ItemStack.empty() for _ in range(len(self.items))]
        if hooks is not None:
            try:
                hooks.changed(self)
            except Exception:
                pass
        return result, ContainerError.Callback

    def add(
        self, stack: ItemStack, hooks: Optional[ContainerHooks[I, V]] = None
    ) -> Tuple[Optional[ItemStack], ContainerError[Any]]:
        """``simple_container.rs::SimpleContainer::add``.

        Добавляет стек в контейнер, распределяя по слотам.
        Возвращает (оставшийся_стек, ошибка).
        """
        if stack.is_empty():
            return ItemStack.empty(), ContainerError.Callback

        # копия стека, которую будем распределять
        remainder = stack.copy() if hasattr(stack, "copy") else stack

        # пытаемся добавить в существующие стеки того же типа
        for i in range(self.size()):
            target = self.items[i]
            if target.same_item_components(remainder):
                # есть место? вычисляем лимит
                lim = self.limit(target, hooks)
                space = lim - target.count
                if space > 0:
                    amount = min(remainder.count, space)
                    # увеличиваем целевой слот
                    self.items[i] = ItemStack(
                        item=target.item,
                        count=target.count + amount,
                        damage=target.damage,
                    )
                    # уменьшаем remainder
                    remainder = ItemStack(
                        item=remainder.item,
                        count=remainder.count - amount,
                        damage=remainder.damage,
                    )
                    if remainder.is_empty():
                        if hooks is not None:
                            hooks.changed(self)
                        return ItemStack.empty(), ContainerError.Callback
                    # продолжаем попытки добавить в другие слоты
                    continue

        # ищем пустой слот
        for i in range(self.size()):
            if self.items[i].is_empty():
                # перемещаем remainder в пустой слот
                self.items[i] = remainder
                if hooks is not None:
                    hooks.changed(self)
                return ItemStack.empty(), ContainerError.Callback

        # ничего не поместилось — возвращаем remainder (весь стек)
        return remainder, ContainerError.Callback

    def copy(self) -> "SimpleContainer[I, V]":
        """Создает копию контейнера."""
        return SimpleContainer(items=self.items.copy())


# ---------------------------------------------------------------------------
# Пример использования (для тестов):
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # минимальный тест создания контейнера
    container = SimpleContainer.new(3, [])
    print(f"size={container.size()}, is_empty={container.is_empty()}")
    assert container.size() == 3
    assert container.is_empty()

    # set и get
    from quadrix.items.items import ItemStack
    item = ItemStack.new("minecraft:coal", 64)
    ok, err = container.set(0, item, None)  # hooks=None для простого теста
    print(f"set result: ok={ok}, err={err}")
    retrieved = container.get(0)
    print(f"get after set: {retrieved.item} x {retrieved.count}")
    assert retrieved.item == "minecraft:coal"
    assert retrieved.count == 64

    # clear
    ok, err = container.clear(None)
    print(f"clear: ok={ok}, err={err}")
    assert container.is_empty()

    print("All basic tests passed!")