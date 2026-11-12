#!/usr/bin/env python3
"""[QuadRix] Игровой HUD: здоровье, еда, опыт, прицел (Gameplay PART 4).

Порт раскладки ванильного ``Hud`` из
``horizon/crates/horizon-client-render/src/hud_layout.rs`` — функций
``crosshair``, ``experience`` и ``HealthHud::layout``
(``Hud.extractCrosshair`` / ``ExperienceBar`` / ``Hud.extractPlayerHealth``).

Всё считается **без рисования** (как в Rust): методы ``*_layout``
возвращают список :class:`SpriteDraw` (спрайт + позиция), а
:meth:`HUD.render` превращает их в квады батча. Это позволяет тестам
проверять геометрию без дисплея.

Геометрия (Rust ``hud_layout.rs``):
    * прицел ``hud/crosshair`` — ``(w - 15) / 2, (h - 15) / 2``, 15×15;
    * опыт ``hud/experience_bar_background`` — ``w/2 - 91, h - 32 + 3``,
      182×5; заливка ``experience_bar_progress`` — ``progress * 183``;
      число уровня — по центру над баром (``y = h - 24 - 9 - 2``);
    * сердца — слева: ``x = w/2 - 91 + column * 8``,
      ``y = h - 39 - row * row_height``, 9×9;
    * еда — справа: ``x = w/2 + 91 - n * 8 - 9``, ``y = h - 39``, 9×9.

Спрайты — ``.local/horizon-client/26.3/assets/minecraft/textures/
gui/sprites/hud/**`` (26.3 хранит их как спрайты, а не ``icons.png`` /
``widgets.png``). Их грузит :mod:`quadrix.render.gui_atlas`.
FALLBACK: нет атласа — рисуем цветные квадраты (правило 9 AGENTS.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from quadrix.core.random import LegacyRandom
from quadrix.render.ui import Quad, rgba

__all__ = [
    "HEART_SIZE",
    "ICON_STEP",
    "HeartKind",
    "HealthInputs",
    "HealthHud",
    "HUD",
    "SpriteDraw",
    "crosshair_layout",
    "experience_layout",
]

#: Размер иконки сердца/еды (9×9 GUI-пикселей).
HEART_SIZE: int = 9
#: Шаг между иконками по X.
ICON_STEP: int = 8
#: Отступ от центра до левой/правой группы (``w/2 -/+ 91``).
MARGIN: int = 91
#: Базовая строка сердца/еды (``h - 39``).
Y_BASE_FROM_BOTTOM: int = 39

# -- ключи спрайтов атласа ------------------------------------------------
SPRITE_HEART_CONTAINER = "gui/sprites/hud/heart/container"
SPRITE_HEART_FULL = "gui/sprites/hud/heart/full"
SPRITE_HEART_HALF = "gui/sprites/hud/heart/half"
SPRITE_HEART_HARDCORE_FULL = "gui/sprites/hud/heart/hardcore_full"
SPRITE_HEART_HARDCORE_HALF = "gui/sprites/hud/heart/hardcore_half"
SPRITE_FOOD_EMPTY = "gui/sprites/hud/food_empty"
SPRITE_FOOD_FULL = "gui/sprites/hud/food_full"
SPRITE_FOOD_HALF = "gui/sprites/hud/food_half"
SPRITE_FOOD_EMPTY_HUNGER = "gui/sprites/hud/food_empty_hunger"
SPRITE_FOOD_FULL_HUNGER = "gui/sprites/hud/food_full_hunger"
SPRITE_FOOD_HALF_HUNGER = "gui/sprites/hud/food_half_hunger"
SPRITE_XP_BACKGROUND = "gui/sprites/hud/experience_bar_background"
SPRITE_XP_PROGRESS = "gui/sprites/hud/experience_bar_progress"
SPRITE_CROSSHAIR = "gui/sprites/hud/crosshair"

#: FALLBACK-цвета (нет атласа).
FALLBACK_HEART = rgba(220, 40, 40, 255)
FALLBACK_FOOD = rgba(170, 110, 40, 255)
FALLBACK_XP = rgba(80, 255, 32, 255)
FALLBACK_CROSSHAIR = rgba(220, 220, 220, 255)


def _floor(x: float) -> int:
    """``Mth.floor`` (Rust ``hud_layout::floor``)."""
    return math.floor(x)


def _ceil(x: float) -> int:
    """``Mth.ceil``."""
    return math.ceil(x)


@dataclass(frozen=True)
class SpriteDraw:
    """Один ``blitSprite`` из Rust ``GuiDraw::Sprite``.

    ``region`` не ``None`` — частичный спрайт (``hud.rs::sprite_region``):
    ``(logical_w, logical_h)`` — логический размер всего спрайта, из
    которого берётся верхний левый угол ``w × h``.
    """

    sprite: str
    x: float
    y: float
    w: float
    h: float
    region: Optional[tuple[float, float]] = None


class HeartKind(Enum):
    """``Hud.HeartType`` (Rust ``HeartKind``)."""

    Normal = "normal"
    Poisoned = "poisoned"
    Withered = "withered"
    Frozen = "frozen"


@dataclass
class HealthInputs:
    """``HealthInputs`` (Rust) — всё, что читает ``HealthHud::layout``."""

    tick: int = 0
    millis: int = 0
    health: float = 20.0
    max_health: float = 20.0
    absorption: float = 0.0
    armor: int = 0
    food: int = 20
    saturation: float = 0.0
    kind: HeartKind = HeartKind.Normal
    regeneration: bool = False
    hunger: bool = False
    hardcore: bool = False
    damage_cooldown: bool = False
    air: int = 300
    max_air: int = 300
    under_water: bool = False
    vehicle_hearts: int = 0


# ---------------------------------------------------------------------------
# прицел (Rust ``crosshair``)
# ---------------------------------------------------------------------------

def crosshair_layout(w: int, h: int) -> list[SpriteDraw]:
    """``Hud.extractCrosshair`` без индикатора атаки: один спрайт 15×15."""
    return [SpriteDraw(SPRITE_CROSSHAIR, (w - 15) // 2, (h - 15) // 2, 15.0, 15.0)]


# ---------------------------------------------------------------------------
# опыт (Rust ``experience``)
# ---------------------------------------------------------------------------

def experience_layout(
    w: int,
    h: int,
    progress: float,
    level: int,
    text_width: Optional[Any] = None,
    bar: bool = True,
) -> list[SpriteDraw]:
    """``ExperienceBar.extractBackground`` + ``ContextualBar``.

    ``text_width`` — функция измерения подписи шрифтом; используется,
    чтобы поставить число уровня по центру (при отсутствии — оценка по
    ширине символа 6 px, только для раскладки).
    """
    out: list[SpriteDraw] = []
    if bar:
        left = w // 2 - 91
        top = h - 32 + 3
        filled = int(progress * 183.0)
        out.append(
            SpriteDraw(SPRITE_XP_BACKGROUND, float(left), float(top), 182.0, 5.0)
        )
        if filled > 0:
            out.append(
                SpriteDraw(
                    SPRITE_XP_PROGRESS,
                    float(left),
                    float(top),
                    float(filled),
                    5.0,
                    region=(182.0, 5.0),
                )
            )
    if level > 0:
        label = str(level)
        width = int(text_width(label)) if text_width is not None else 6 * len(label)
        x = (w - width) / 2
        # Число уровня — отдельный текстовый draw в Rust; здесь запоминаем
        # позицию через служебный SpriteDraw нельзя, поэтому уровень рисует
        # ``HUD.render`` (см. ``level_text``). Оставляем позицию в HUD.
        out.append(
            SpriteDraw("__xp_level__", float(x), float(h - 24 - 9 - 2), 0.0, 0.0)
        )
    return out


def xp_level_position(w: int, h: int, level: int, text_width: Any = None) -> tuple[float, float]:
    """Позиция числа уровня (``y = h - 24 - 9 - 2``, по центру)."""
    label = str(level)
    width = int(text_width(label)) if text_width is not None else 6 * len(label)
    return (w - width) / 2.0, float(h - 24 - 9 - 2)


# ---------------------------------------------------------------------------
# сердца / броня / еда / воздух (Rust ``HealthHud::layout``)
# ---------------------------------------------------------------------------

_HEART_TABLES: dict[Optional[HeartKind], tuple[str, str, str, str]] = {
    None: (SPRITE_HEART_CONTAINER, SPRITE_HEART_CONTAINER, SPRITE_HEART_CONTAINER, SPRITE_HEART_CONTAINER),
    HeartKind.Normal: (SPRITE_HEART_FULL, SPRITE_HEART_FULL, SPRITE_HEART_HALF, SPRITE_HEART_HALF),
}


def _heart_name(
    kind: Optional[HeartKind], hardcore: bool, half: bool, blink: bool
) -> str:
    """``hud_layout::heart`` (сокращённая таблица: контейнер/full/half).

    FALLBACK: спрайты absorption/poisoned/withered/frozen (_blinking)
    зарегистрированы в ``.local``, но в этом PART используется обычная
    таблица; ``blink`` только меняет вид на ``_blinking``, если он есть.
    """
    if kind is None:
        return SPRITE_HEART_CONTAINER
    if hardcore:
        return SPRITE_HEART_HARDCORE_HALF if half else SPRITE_HEART_HARDCORE_FULL
    return SPRITE_HEART_HALF if half else SPRITE_HEART_FULL


class HealthHud:
    """Состояние между кадрами (``Hud.lastHealth``, ``displayHealth``, ...)."""

    def __init__(self) -> None:
        self.last_health: int = 0
        self.display_health: int = 0
        self.last_health_time: int = 0
        self.health_blink_time: int = 0

    def layout(self, i: HealthInputs, w: int, h: int) -> list[SpriteDraw]:
        """``Hud.extractPlayerHealth``: сердца, броня, еда, воздух."""
        out: list[SpriteDraw] = []
        tick = i.tick
        current = _ceil(i.health)
        blink = self.health_blink_time > tick and (
            (self.health_blink_time - tick) // 3
        ) % 2 == 1
        if current < self.last_health and i.damage_cooldown:
            self.last_health_time = i.millis
            self.health_blink_time = tick + 20
        elif current > self.last_health and i.damage_cooldown:
            self.last_health_time = i.millis
            self.health_blink_time = tick + 10
        if i.millis - self.last_health_time > 1000:
            self.display_health = current
            self.last_health_time = i.millis
        self.last_health = current
        old = self.display_health

        random = LegacyRandom(tick * 312871)

        def nxt(bound: int) -> int:
            return random.next_int_bound(bound)

        x_left = w // 2 - MARGIN
        x_right = w // 2 + MARGIN
        y_base = h - Y_BASE_FROM_BOTTOM
        max_health = max(i.max_health, float(max(old, current)))
        absorption = _ceil(i.absorption)
        rows = _ceil((max_health + absorption) / 2.0 / 10.0)
        row_height = max(10 - (rows - 2), 3)
        y_air = y_base - 10

        # Броня (Hud.extractArmor).
        if i.armor > 0:
            y = y_base - (rows - 1) * row_height - 10
            for n in range(10):
                x = x_left + n * ICON_STEP
                if n * 2 + 1 < i.armor:
                    out.append(SpriteDraw("gui/sprites/hud/armor_full", x, y, 9.0, 9.0))
                if n * 2 + 1 == i.armor:
                    out.append(SpriteDraw("gui/sprites/hud/armor_half", x, y, 9.0, 9.0))
                if n * 2 + 1 > i.armor:
                    out.append(SpriteDraw("gui/sprites/hud/armor_empty", x, y, 9.0, 9.0))

        containers = _ceil(max_health / 2.0)
        absorb_containers = _ceil(absorption / 2.0)
        offset_index = (tick % _ceil(max_health + 5.0)) if i.regeneration else -1
        for c in range(containers + absorb_containers - 1, -1, -1):
            row, column = c // 10, c % 10
            x = x_left + column * ICON_STEP
            y = y_base - row * row_height
            if current + absorption <= 4:
                y += nxt(2)
            if c < containers and c == offset_index:
                y -= 2
            out.append(
                SpriteDraw(_heart_name(None, i.hardcore, False, blink), x, y, 9.0, 9.0)
            )
            halves = c * 2
            if c >= containers:
                ah = halves - containers * 2
                if ah < absorption:
                    out.append(
                        SpriteDraw(
                            _heart_name(i.kind, i.hardcore, ah + 1 == absorption, False),
                            x, y, 9.0, 9.0,
                        )
                    )
            if blink and halves < old:
                out.append(
                    SpriteDraw(
                        _heart_name(i.kind, i.hardcore, halves + 1 == old, True),
                        x, y, 9.0, 9.0,
                    )
                )
            if halves < current:
                out.append(
                    SpriteDraw(
                        _heart_name(i.kind, i.hardcore, halves + 1 == current, False),
                        x, y, 9.0, 9.0,
                    )
                )

        # Еда (Hud.extractFood) — только если не верхом на животном.
        if i.vehicle_hearts == 0:
            if i.hunger:
                empty, half, full = (
                    SPRITE_FOOD_EMPTY_HUNGER, SPRITE_FOOD_HALF_HUNGER, SPRITE_FOOD_FULL_HUNGER,
                )
            else:
                empty, half, full = SPRITE_FOOD_EMPTY, SPRITE_FOOD_HALF, SPRITE_FOOD_FULL
            for n in range(10):
                y = y_base
                if i.saturation <= 0.0 and i.tick % (i.food * 3 + 1) == 0:
                    y += nxt(3) - 1
                x = x_right - n * ICON_STEP - 9
                out.append(SpriteDraw(empty, x, y, 9.0, 9.0))
                if n * 2 + 1 < i.food:
                    out.append(SpriteDraw(full, x, y, 9.0, 9.0))
                if n * 2 + 1 == i.food:
                    out.append(SpriteDraw(half, x, y, 9.0, 9.0))
            y_air -= 10

        # Пузыри воздуха (Hud.extractAirBubbles).
        max_air = max(i.max_air, 1)
        air = min(max(i.air, 0), max_air)
        if i.under_water or air < max_air:
            rows_air = _ceil(i.vehicle_hearts / 10.0)
            y = y_air - (rows_air - 1) * 10

            def bubble(offset: int) -> int:
                return _ceil(((air + offset) * 10) / max_air)

            full_b = bubble(-2)
            popping = bubble(0)
            # empty-счётчик (``bubble(delay)``) в Rust участвует только в
            # звуке всплытия пузыря — здесь он не нужен.
            for b in range(1, 11):
                x = x_right - (b - 1) * ICON_STEP - 9
                if b <= full_b:
                    out.append(SpriteDraw("gui/sprites/hud/air", x, y, 9.0, 9.0))
                elif full_b != popping and b == popping and i.under_water:
                    out.append(SpriteDraw("gui/sprites/hud/air_bursting", x, y, 9.0, 9.0))
        return out


# ---------------------------------------------------------------------------
# HUD — сборка и отрисовка
# ---------------------------------------------------------------------------

class HUD:
    """Игровой HUD: здоровья/еды/опыта/прицела (порт ``Hud``).

    Держит :class:`HealthHud` (состояние между кадрами) и собирает все
    элементы кадра одним вызовом :meth:`render`.
    """

    def __init__(self) -> None:
        self.health = HealthHud()

    # -- раскладка -------------------------------------------------------

    def layout(
        self,
        width: float,
        height: float,
        *,
        inputs: Optional[HealthInputs] = None,
        xp_progress: float = 0.0,
        xp_level: int = 0,
        crosshair: bool = True,
        text_width: Optional[Any] = None,
    ) -> list[SpriteDraw]:
        """Собрать все элементы HUD в список :class:`SpriteDraw`."""
        w, h = int(width), int(height)
        out: list[SpriteDraw] = []
        if crosshair:
            out.extend(crosshair_layout(w, h))
        out.extend(
            experience_layout(w, h, xp_progress, xp_level, text_width=text_width)
        )
        if inputs is not None:
            out.extend(self.health.layout(inputs, w, h))
        return out

    # -- отрисовка -------------------------------------------------------

    def render(
        self,
        batch: Any,
        font: Optional[Any] = None,
        width: float = 0.0,
        height: float = 0.0,
        **kwargs: Any,
    ) -> int:
        """Нарисовать HUD; вернуть число нарисованных спрайтов."""
        inputs = kwargs.get("inputs")
        xp_progress = float(kwargs.get("xp_progress", 0.0))
        xp_level = int(kwargs.get("xp_level", 0))
        crosshair = bool(kwargs.get("crosshair", True))
        text_width = kwargs.get("text_width")
        if text_width is None and font is not None:
            text_width = font.width
        draws = self.layout(
            width,
            height,
            inputs=inputs,
            xp_progress=xp_progress,
            xp_level=xp_level,
            crosshair=crosshair,
            text_width=text_width,
        )
        atlas = getattr(batch, "atlas", None)
        count = 0
        for draw in draws:
            if draw.sprite == "__xp_level__":
                continue
            if draw.region is not None:
                lw, lh = draw.region
                drawn = atlas is not None and atlas.region(
                    batch, draw.sprite, draw.x, draw.y, draw.w, draw.h, lw, lh
                )
            else:
                drawn = atlas is not None and atlas.blit(
                    batch, draw.sprite, draw.x, draw.y, draw.w, draw.h
                )
            if not drawn:
                self._fallback(batch, font, draw)
            count += 1
        # Число уровня опыта — текст поверх бара.
        if xp_level > 0 and font is not None:
            self._draw_level(batch, font, int(width), int(height), xp_level)
        return count

    def _draw_level(
        self, batch: Any, font: Any, w: int, h: int, level: int
    ) -> None:
        from quadrix.render.menu import draw_text

        x, y = xp_level_position(w, h, level, font.width)
        # Чёрная обводка, потом зелёная заливка (Rust: 0xFF80FF20).
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw_text(batch, font, str(level), x + dx, y + dy, rgba(0, 0, 0, 255))
        draw_text(batch, font, str(level), x, y, rgba(128, 255, 32, 255))

    def _fallback(
        self, batch: Any, font: Optional[Any], draw: SpriteDraw
    ) -> None:
        """FALLBACK: атласа нет — цветной квадрат на месте спрайта."""
        sprite = draw.sprite
        if "heart" in sprite:
            color = FALLBACK_HEART
        elif "food" in sprite:
            color = FALLBACK_FOOD
        elif "experience" in sprite:
            color = FALLBACK_XP
        elif "crosshair" in sprite:
            color = FALLBACK_CROSSHAIR
        else:
            color = rgba(180, 180, 180, 255)
        solid(batch, font, draw.x, draw.y, draw.w, draw.h, color)


def solid(
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
