#!/usr/bin/env python3
"""[QuadRix] HUD hotbar: 9 слотов, выбор и отрисовка (Gameplay PART 2).

Порт раскладки ванильного ``Hud`` из
``horizon/crates/horizon-client-render/src/hud_layout.rs``
(``HotbarInputs``/``hotbar``):

    * фон ``hud/hotbar``        — ``center - 91, h - 22, 182, 22``;
    * выбор ``hud/hotbar_selection`` — ``center - 91 - 1 + selected * 20,
      h - 22 - 1, 24, 23``;
    * предмет слота ``n``       — ``center - 90 + n * 20 + 2, h - 16 - 3``,
      размер иконки 16×16.

Сами спрайты — ``.local/horizon-client/26.3/assets/minecraft/textures/gui/
sprites/hud/hotbar.png`` и ``hotbar_selection.png`` (в реальном клиенте они
пакуются в спрайтовый атлас; здесь — ``GuiAtlas``, ключи
``gui/sprites/hud/hotbar`` и ``hotbar_selection``).

Иконки предметов: в этом PART атлас предметов не собирается, поэтому вместо
иконки рисуется **FALLBACK** — цветной квадрат по имени предмета
(:func:`item_color`) и число стака (см. правило 9 AGENTS.md). Иконки
предметов — следующая сессия HUD.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from quadrix.items.items import ItemStack
from quadrix.render.ui import Quad, rgba
from quadrix.world.player_inventory import HOTBAR_SIZE

__all__ = [
    "HOTBAR_SLOTS",
    "HOTBAR_WIDTH",
    "HOTBAR_HEIGHT",
    "SLOT_STEP",
    "ITEM_SIZE",
    "item_color",
    "Hotbar",
]

#: ``Inventory.getSelectionSize`` — 9 слотов.
HOTBAR_SLOTS: int = HOTBAR_SIZE
#: ``hud/hotbar.png`` — 182×22 GUI-пикселя.
HOTBAR_WIDTH: int = 182
HOTBAR_HEIGHT: int = 22
#: Шаг между слотами по X (``n * 20``).
SLOT_STEP: int = 20
#: Размер иконки предмета (16×16 GUI-пикселей).
ITEM_SIZE: int = 16

#: Спрайты атласа (ключи ``GuiAtlas``).
HOTBAR_SPRITE: str = "gui/sprites/hud/hotbar"
SELECTION_SPRITE: str = "gui/sprites/hud/hotbar_selection"

#: FALLBACK-цвета фона и подсветки (нет атласа).
FALLBACK_BACKGROUND: int = rgba(24, 24, 24, 200)
FALLBACK_SELECTION: int = rgba(255, 255, 255, 160)
FALLBACK_ITEM_BORDER: int = rgba(0, 0, 0, 200)


def item_color(item_id: str) -> int:
    """FALLBACK: стабильный цвет по имени предмета (нет атласа иконок).

    Пока иконки предметов не собраны в атлас, слот рисуется квадратом этого
    цвета — видно, что слот занят, и одинаковые предметы одного цвета.
    """
    text = item_id or "minecraft:air"
    h = 0
    for ch in text:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    r = 64 + (h & 0x7F)
    g = 64 + ((h >> 8) & 0x7F)
    b = 64 + ((h >> 16) & 0x7F)
    return rgba(r, g, b, 255)


@dataclass
class Hotbar:
    """HUD-hotbar: держит инвентарь и выбранный слот (``hud_layout::hotbar``).

    ``inventory`` — объект с ``items`` (первые 9 — hotbar) и ``selected``;
    используется :class:`~quadrix.world.player_inventory.PlayerInventory`.
    """

    inventory: Any

    # -- выбор -----------------------------------------------------------

    @property
    def selected(self) -> int:
        return int(self.inventory.selected)

    def select(self, index: int) -> int:
        """Выбрать слот 0..8 (число на клавише минус 1)."""
        self.inventory.set_selected(int(index))
        return self.selected

    def select_key(self, key: str) -> bool:
        """Нажатие цифры ``"1".."9"`` → выбор слота. ``True``, если принято."""
        if len(key) == 1 and "1" <= key <= "9":
            self.select(int(key) - 1)
            return True
        return False

    def scroll(self, delta: int) -> int:
        """Колесо мыши: сдвиг выбора по кругу 0..8."""
        return self.inventory.scroll(int(delta))

    def slot_stack(self, index: int) -> Optional[ItemStack]:
        """Стек слота hotbar (0..8)."""
        if 0 <= index < HOTBAR_SLOTS:
            return self.inventory.items[index]
        return None

    # -- геометрия (hud_layout.rs:279-351) -------------------------------

    def background_rect(self, width: float, height: float) -> Tuple[float, float, float, float]:
        """Фон ``hud/hotbar``: ``(x, y, w, h)``."""
        return (
            float(width) / 2.0 - 91.0,
            float(height) - 22.0,
            float(HOTBAR_WIDTH),
            float(HOTBAR_HEIGHT),
        )

    def selection_rect(self, width: float, height: float) -> Tuple[float, float, float, float]:
        """Подсветка выбранного слота (24×23)."""
        return (
            float(width) / 2.0 - 91.0 - 1.0 + self.selected * SLOT_STEP,
            float(height) - 22.0 - 1.0,
            24.0,
            23.0,
        )

    def slot_rect(
        self, index: int, width: float, height: float
    ) -> Tuple[float, float, float, float]:
        """Прямоугольник иконки слота ``index`` (16×16)."""
        return (
            float(width) / 2.0 - 90.0 + index * SLOT_STEP + 2.0,
            float(height) - 16.0 - 3.0,
            float(ITEM_SIZE),
            float(ITEM_SIZE),
        )

    # -- отрисовка -------------------------------------------------------

    def render(
        self,
        batch: Any,
        font: Optional[Any] = None,
        width: float = 0.0,
        height: float = 0.0,
    ) -> None:
        """Нарисовать фон, подсветку, предметы и числа 1..9.

        ``width``/``height`` — логический размер экрана; если не заданы,
        берётся из атрибутов ``batch`` (тесты).
        """
        width, height = self._screen_size(batch, width, height)
        atlas = getattr(batch, "atlas", None)

        bx, by, bw, bh = self.background_rect(width, height)
        drawn = atlas is not None and atlas.blit(batch, HOTBAR_SPRITE, bx, by, bw, bh)
        if not drawn:
            self._solid(batch, font, bx, by, bw, bh, FALLBACK_BACKGROUND)

        sx, sy, sw, sh = self.selection_rect(width, height)
        if not (atlas is not None and atlas.blit(batch, SELECTION_SPRITE, sx, sy, sw, sh)):
            self._solid(batch, font, sx, sy, sw, sh, FALLBACK_SELECTION)

        for i in range(HOTBAR_SLOTS):
            self._render_slot(batch, font, i, width, height)

    def render_slots(
        self,
        batch: Any,
        font: Optional[Any] = None,
        width: float = 0.0,
        height: float = 0.0,
    ) -> None:
        """Только предметы и числа (без фона/подсветки) — для инвентаря."""
        width, height = self._screen_size(batch, width, height)
        for i in range(HOTBAR_SLOTS):
            self._render_slot(batch, font, i, width, height)

    def _screen_size(self, batch: Any, width: float, height: float) -> Tuple[float, float]:
        if width and height:
            return float(width), float(height)
        width = float(getattr(batch, "width", 0.0))
        height = float(getattr(batch, "height", 0.0))
        return width, height

    def _render_slot(
        self, batch: Any, font: Optional[Any], index: int, width: float, height: float
    ) -> None:
        x, y, w, h = self.slot_rect(index, width, height)
        stack = self.slot_stack(index)
        if stack is not None and not stack.is_empty():
            # FALLBACK: иконка предмета — цветной квадрат (атлас items — PART 5).
            self._solid(batch, font, x, y, w, h, item_color(stack.item))
            self._solid(batch, font, x, y, w, 1.0, FALLBACK_ITEM_BORDER)
            if stack.count > 1 and font is not None:
                from quadrix.render.menu import draw_text

                from quadrix.render.ui import WHITE

                label = str(stack.count)
                draw_text(batch, font, label, x + w - font.width(label), y + h - 8.0, WHITE)
        if font is not None:
            from quadrix.render.ui import rgba as _rgba

            number = str(index + 1)
            batch.add_quads(
                font.render(number, x + 1.0, y - 9.0, _rgba(255, 255, 255, 180))
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
        """Сплошной прямоугольник (белый пиксель шрифта либо полный UV)."""
        if font is not None:
            r = font.white
            batch.add_quad(Quad(x, y, w, h, r.u0, r.v0, r.u1, r.v1, color))
        else:
            batch.add_quad(Quad(x, y, w, h, 0.0, 0.0, 1.0, 1.0, color))
