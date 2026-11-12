#!/usr/bin/env python3
"""[QuadRix] Тесты Gameplay PART 4: HUD (сердца, еда, опыт, прицел).

Проверяем геометрию ``quadrix/render/hud.py`` (порт ``hud_layout.rs``):
счётчики полных/половинных иконок, позицию прицела, опыт и число уровня.
Раскладка считается без рисования — на выходе список ``SpriteDraw``, тесты
работают без дисплея.
"""

from __future__ import annotations

from quadrix.render.hud import (
    HUD,
    SPRITE_CROSSHAIR,
    SPRITE_FOOD_FULL,
    SPRITE_HEART_CONTAINER,
    SPRITE_HEART_FULL,
    SPRITE_XP_BACKGROUND,
    SPRITE_XP_PROGRESS,
    HealthInputs,
    crosshair_layout,
    experience_layout,
    xp_level_position,
)
from quadrix.render.ui import Batch

WIDTH = 854
HEIGHT = 480


def _count(draws, sprite: str) -> int:
    return sum(1 for d in draws if d.sprite == sprite)


# ---------------------------------------------------------------------------
# Сердца (Hud.extractPlayerHealth)
# ---------------------------------------------------------------------------

def test_health_full_hearts() -> None:
    """Health=20 → 10 контейнеров и 10 полных сердец (10×2 половин)."""
    hud = HUD()
    draws = hud.health.layout(HealthInputs(health=20.0, max_health=20.0), 0, 0)
    assert _count(draws, SPRITE_HEART_CONTAINER) == 10
    assert _count(draws, SPRITE_HEART_FULL) == 10


def test_health_five_hearts() -> None:
    """Health=10 → 10 контейнеров, 5 полных сердец (остальные пусты)."""
    hud = HUD()
    draws = hud.health.layout(HealthInputs(health=10.0, max_health=20.0), 0, 0)
    assert _count(draws, SPRITE_HEART_CONTAINER) == 10
    assert _count(draws, SPRITE_HEART_FULL) == 5


def test_health_heart_positions() -> None:
    """Первое (левое) сердце — ``w/2 - 91``, ``h - 39`` (hud_layout.rs).

    Сердца рисуются справа налево, поэтому левое — с минимальным ``x``.
    """
    hud = HUD()
    draws = hud.health.layout(HealthInputs(health=20.0), WIDTH, HEIGHT)
    hearts = [d for d in draws if d.sprite == SPRITE_HEART_CONTAINER]
    assert min(d.x for d in hearts) == WIDTH // 2 - 91
    assert min(d.y for d in hearts) == HEIGHT - 39
    assert (hearts[0].w, hearts[0].h) == (9.0, 9.0)


# ---------------------------------------------------------------------------
# Еда (Hud.extractFood)
# ---------------------------------------------------------------------------

def test_food_full() -> None:
    """Food=20 → 10 полных иконок еды."""
    hud = HUD()
    draws = hud.health.layout(HealthInputs(food=20), 0, 0)
    assert _count(draws, SPRITE_FOOD_FULL) == 10


def test_food_half() -> None:
    """Food=10 → 5 полных иконок еды (половина шкалы)."""
    hud = HUD()
    draws = hud.health.layout(HealthInputs(food=10), 0, 0)
    assert _count(draws, SPRITE_FOOD_FULL) == 5


def test_food_position_right() -> None:
    """Первая иконка еды у правого края: ``w/2 + 91 - 9``.

    ``tick=1`` — без дрожания (``saturation == 0`` даёт сдвиг только на
    ``tick % (food*3+1) == 0``).
    """
    hud = HUD()
    draws = hud.health.layout(HealthInputs(food=20, tick=1), WIDTH, HEIGHT)
    full = next(d for d in draws if d.sprite == SPRITE_FOOD_FULL)
    assert full.x == WIDTH // 2 + 91 - 9
    assert full.y == HEIGHT - 39


# ---------------------------------------------------------------------------
# Прицел (Hud.extractCrosshair)
# ---------------------------------------------------------------------------

def test_crosshair_center() -> None:
    """Прицел 15×15 по центру: ``(w - 15) // 2``, ``(h - 15) // 2``."""
    draws = crosshair_layout(WIDTH, HEIGHT)
    assert len(draws) == 1
    sprite = draws[0]
    assert sprite.sprite == SPRITE_CROSSHAIR
    assert sprite.x == (WIDTH - 15) // 2
    assert sprite.y == (HEIGHT - 15) // 2
    assert (sprite.w, sprite.h) == (15.0, 15.0)


# ---------------------------------------------------------------------------
# Опыт (ExperienceBar.extractBackground)
# ---------------------------------------------------------------------------

def test_experience_bar() -> None:
    """Фон опыта ``w/2 - 91, h - 32 + 3`` 182×5; заливка = progress*183."""
    draws = experience_layout(WIDTH, HEIGHT, progress=0.5, level=3)
    bg = next(d for d in draws if d.sprite == SPRITE_XP_BACKGROUND)
    assert bg.x == WIDTH // 2 - 91
    assert bg.y == HEIGHT - 32 + 3
    assert (bg.w, bg.h) == (182.0, 5.0)

    progress = next(d for d in draws if d.sprite == SPRITE_XP_PROGRESS)
    assert progress.w == int(0.5 * 183.0)
    # Частичный спрайт: регион берётся из логического размера 182×5.
    assert progress.region == (182.0, 5.0)


def test_experience_zero_progress_no_fill() -> None:
    """Progress=0 → фон есть, заливки нет."""
    draws = experience_layout(WIDTH, HEIGHT, progress=0.0, level=0)
    assert _count(draws, SPRITE_XP_BACKGROUND) == 1
    assert _count(draws, SPRITE_XP_PROGRESS) == 0


def test_xp_level_position() -> None:
    """Число уровня по центру, ``y = h - 24 - 9 - 2`` (hud_layout.rs)."""
    x, y = xp_level_position(WIDTH, HEIGHT, 3)
    # Без метрики шрифта ширина оценивается как 6 px на символ.
    assert x == (WIDTH - 6) / 2
    assert y == HEIGHT - 24 - 9 - 2


# ---------------------------------------------------------------------------
# HUD.render (FALLBACK-квады без атласа)
# ---------------------------------------------------------------------------

def test_hud_render_fallback() -> None:
    """Без атласа HUD рисует цветные квадраты и возвращает их число."""
    hud = HUD()
    batch = Batch()
    count = hud.render(
        batch,
        None,
        WIDTH,
        HEIGHT,
        inputs=HealthInputs(health=20.0, food=20.0),
        xp_progress=1.0,
        xp_level=0,
    )
    # Прицел + фон опыта + заливка + сердца/еда — заведомо больше 20 квадов.
    assert count > 20
