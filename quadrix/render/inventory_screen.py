#!/usr/bin/env python3
"""[QuadRix] Экран инвентаря игрока (Gameplay PART 2).

Простой (PART 2) экран инвентаря: сетка основного инвентаря 3×9, hotbar 1×9,
4 слота брони, offhand и (только отрисовка) крафт 2×2 с результатом.
Drag&drop — упрощённый: клик берёт стак в «руку», клик по другому слоту
кладет/меняет (полноценный перенос с разделением — PART 5).

Геометрия — ванильный ``InventoryScreen`` 176×166
(``horizon-client/src/container_screen.rs`` / ``screen.rs``):
слоты идут с шагом 18, main начинается на ``y=84``, hotbar — ``y=142``,
броня — левая колонка ``x=8``. Фон — ``gui/container/inventory.png``; если
атлас пуст, рисуется сплошная заливка (FALLBACK).

Ключ ``E``/``Escape`` закрывает экран (``Minecraft.setScreen(null)``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from quadrix.items.items import ItemStack
from quadrix.render.hotbar import item_color
from quadrix.render.menu import Screen, draw_text
from quadrix.render.ui import BLACK, WHITE, Quad, rgba

__all__ = ["InventoryScreen", "InventorySlot"]

#: Ванильный GUI игрока: 176×166.
GUI_WIDTH: int = 176
GUI_HEIGHT: int = 166
#: Шаг сетки слотов.
SLOT_STEP: int = 18
#: Размер иконки предмета.
ITEM_SIZE: int = 16

#: Спрайты атласа.
INVENTORY_SPRITE: str = "gui/container/inventory"
SLOT_SPRITE: str = "gui/sprites/container/slot"

#: FALLBACK-цвета.
FALLBACK_PANEL: int = rgba(198, 198, 198, 255)
FALLBACK_SLOT: int = rgba(139, 139, 139, 255)
FALLBACK_ITEM_BORDER: int = rgba(0, 0, 0, 200)


@dataclass(frozen=True)
class InventorySlot:
    """Слот экрана инвентаря: позиция и индекс в ``PlayerInventory``."""

    x: float
    y: float
    index: int
    kind: str


class InventoryScreen(Screen):
    """Экран инвентаря игрока (порт ``InventoryScreen``).

    ``inventory`` — :class:`~quadrix.world.player_inventory.PlayerInventory`.
    ``on_close`` вызывается при ``E``/``Escape`` (закрыть экран, вернуть
    курсор — см. ``GameScreen._close_inventory``).
    """

    def __init__(
        self,
        inventory: Any,
        width: float = 854.0,
        height: float = 480.0,
        on_close: Optional[Any] = None,
    ) -> None:
        super().__init__(width, height)
        self.inventory = inventory
        self.on_close = on_close
        #: Стак «в руке» при перетаскивании.
        self.carried: Optional[ItemStack] = None
        #: Последняя позиция курсора (для отрисовки carried).
        self.mouse: Tuple[float, float] = (0.0, 0.0)

    # -- геометрия -------------------------------------------------------

    def origin(self) -> Tuple[float, float]:
        """Левый верхний угол панели (центр экрана)."""
        return (
            (self.width - GUI_WIDTH) / 2.0,
            (self.height - GUI_HEIGHT) / 2.0,
        )

    def slots(self) -> List[InventorySlot]:
        """Все кликабельные слоты: броня, offhand, main (3×9), hotbar (9)."""
        ox, oy = self.origin()
        out: List[InventorySlot] = []
        # Броня: feet, legs, chest, head (инвентарь 36..39).
        for i in range(4):
            out.append(
                InventorySlot(ox + 8.0, oy + 8.0 + i * SLOT_STEP, 36 + i, "armor")
            )
        # Offhand (инвентарь 40).
        out.append(InventorySlot(ox + 77.0, oy + 62.0, 40, "offhand"))
        # Основной инвентарь: 3 ряда по 9 (инвентарь 9..35).
        for row in range(3):
            for col in range(9):
                out.append(
                    InventorySlot(
                        ox + 8.0 + col * SLOT_STEP,
                        oy + 84.0 + row * SLOT_STEP,
                        9 + row * 9 + col,
                        "main",
                    )
                )
        # Hotbar: 9 слотов (инвентарь 0..8).
        for col in range(9):
            out.append(
                InventorySlot(
                    ox + 8.0 + col * SLOT_STEP,
                    oy + 142.0,
                    col,
                    "hotbar",
                )
            )
        return out

    def decorative_slots(self) -> List[Tuple[float, float]]:
        """Слоты крафта 2×2 и результата (только отрисовка — PART 5)."""
        ox, oy = self.origin()
        return [
            (ox + 98.0, oy + 18.0),
            (ox + 116.0, oy + 18.0),
            (ox + 98.0, oy + 36.0),
            (ox + 116.0, oy + 36.0),
            (ox + 154.0, oy + 28.0),
        ]

    def slot_at(self, mx: float, my: float) -> Optional[int]:
        """Индекс инвентаря под курсором, иначе ``None``."""
        for slot in self.slots():
            if slot.x <= mx < slot.x + SLOT_STEP and slot.y <= my < slot.y + SLOT_STEP:
                return slot.index
        return None

    # -- ввод (упрощённый click pickup/place) ----------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        """Клик: взять стак / положить / поменять (Rust ``clicked``, упрощённо)."""
        self.mouse = (float(mx), float(my))
        index = self.slot_at(mx, my)
        if index is None:
            return False
        self.click_slot(index)
        return True

    def click_slot(self, index: int) -> None:
        """Один клик по слоту ``index`` (0..42) с учётом ``carried``.

        * рука пуста, слот не пуст → берём стак;
        * рука полна, слот пуст → кладём;
        * оба полны → меняем;
        * оба пусты → ничего.
        """
        stack = self.inventory.get(index)
        if self.carried is None or self.carried.is_empty():
            if stack is not None and not stack.is_empty():
                self.carried = self.inventory.remove_no_update(index)
                self.inventory.changed()
            return
        if stack is None or stack.is_empty():
            self.inventory.set(index, self.carried)
            self.carried = None
        else:
            self.inventory.set(index, self.carried)
            self.carried = stack
        self.inventory.changed()

    def handle_move(self, mx: float, my: float) -> bool:
        self.mouse = (float(mx), float(my))
        return True

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        """``E``/``Escape`` закрывают инвентарь."""
        if key in ("e", "escape"):
            self.close()
            return True
        return False

    def close(self) -> None:
        """Закрыть экран (вызвать ``on_close``)."""
        if self.on_close is not None:
            self.on_close()

    # -- отрисовка -------------------------------------------------------

    def render(self, batch: Any, font: Optional[Any] = None) -> None:
        """Панель, слоты, предметы и стак в руке."""
        ox, oy = self.origin()
        atlas = getattr(batch, "atlas", None)
        drawn = atlas is not None and atlas.blit(
            batch, INVENTORY_SPRITE, ox, oy, float(GUI_WIDTH), float(GUI_HEIGHT)
        )
        if not drawn:
            self._solid(batch, font, ox, oy, float(GUI_WIDTH), float(GUI_HEIGHT), FALLBACK_PANEL)
        for slot in self.slots():
            self._render_slot(batch, font, slot.x, slot.y, slot.index)
        for dx, dy in self.decorative_slots():
            self._solid(batch, font, dx, dy, float(SLOT_STEP), float(SLOT_STEP), FALLBACK_SLOT)
        # Стак в руке следует за курсором.
        if self.carried is not None and not self.carried.is_empty():
            mx, my = self.mouse
            self._solid(
                batch, font, mx - ITEM_SIZE / 2.0, my - ITEM_SIZE / 2.0,
                float(ITEM_SIZE), float(ITEM_SIZE), item_color(self.carried.item),
            )
        if font is not None:
            draw_text(batch, font, "Inventory", ox + 8.0, oy + 6.0, BLACK)

    def _render_slot(
        self, batch: Any, font: Optional[Any], x: float, y: float, index: int
    ) -> None:
        atlas = getattr(batch, "atlas", None)
        if not (atlas is not None and atlas.blit(batch, SLOT_SPRITE, x, y, float(SLOT_STEP), float(SLOT_STEP))):
            self._solid(batch, font, x, y, float(SLOT_STEP), float(SLOT_STEP), FALLBACK_SLOT)
        stack = self.inventory.get(index)
        if stack is None or stack.is_empty():
            return
        ix, iy = x + 1.0, y + 1.0
        # FALLBACK: иконка предмета — цветной квадрат (атлас items — PART 5).
        self._solid(batch, font, ix, iy, float(ITEM_SIZE), float(ITEM_SIZE), item_color(stack.item))
        self._solid(batch, font, ix, iy, float(ITEM_SIZE), 1.0, FALLBACK_ITEM_BORDER)
        if stack.count > 1 and font is not None:
            label = str(stack.count)
            draw_text(
                batch, font, label,
                ix + ITEM_SIZE - font.width(label), iy + ITEM_SIZE - 8.0, WHITE,
            )

    @staticmethod
    def _solid(
        batch: Any,
        font: Optional[Any],
        x: float,
        y: float,
        w: float,
        h: float,
        color: int,
    ) -> None:
        if font is not None:
            r = font.white
            batch.add_quad(Quad(x, y, w, h, r.u0, r.v0, r.u1, r.v1, color))
        else:
            batch.add_quad(Quad(x, y, w, h, 0.0, 0.0, 1.0, 1.0, color))
