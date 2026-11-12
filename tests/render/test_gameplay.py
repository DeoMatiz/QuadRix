#!/usr/bin/env python3
"""[QuadRix] Тесты Gameplay PART 2: клик → raytrace → разрушение/установка.

Проверяем связку, собранную в ``GameScreen`` (``quadrix/render/app.py``):

    * ``pick`` — raytrace по взгляду (``world_ray.clip`` + ``block_collision``);
    * ``handle_mouse_click(0)`` — ЛКМ: разрушение (creative — мгновенно,
      survival — ``tick_mining``);
    * ``handle_mouse_click(1)`` — ПКМ: установка блока предметом слота;
    * дальность 4.5/5.0 (survival/creative);
    * hotbar 1..9 и колесо, инвентарь ``E`` (открыть/закрыть/клик).

Мир — плоская заглушка ``FlatWorld(ground_top=1)`` (трава в ``y=0``); целевые
блоки для клика ставятся прямо в мир через ``FlatWorld.set_block``.
"""

from __future__ import annotations

from quadrix.core.geometry import BlockPos
from quadrix.items.items import ItemStack
from quadrix.render.app import TICK_SECONDS, GameScreen
from quadrix.render.game_world import FlatWorld


def _game(**kwargs) -> GameScreen:
    """GameScreen на маленьком плоском мире (без дисплея)."""
    kwargs.setdefault("world", FlatWorld(ground_top=1))
    kwargs.setdefault("width", 64.0)
    kwargs.setdefault("height", 48.0)
    return GameScreen(**kwargs)


def _look_forward(game: GameScreen) -> None:
    """Смотреть по +Z (yaw 0, pitch 0) на уровне глаз."""
    game.camera.yaw = 0.0
    game.camera.pitch = 0.0


# ---------------------------------------------------------------------------
# ЛКМ: разрушение
# ---------------------------------------------------------------------------

def test_left_click_breaks() -> None:
    """Survival: ЛКМ начинает добычу, блок исчезает за несколько тиков."""
    game = _game()
    game.world.set_block((0, 2, 3), "minecraft:dirt")
    _look_forward(game)

    hit = game.pick()
    assert hit is not None and hit.block == BlockPos(0, 2, 3)

    assert game.handle_mouse_click(0) is True
    # Сразу блок цел — survival добывает по тикам.
    assert game.world.get_block((0, 2, 3)) == "minecraft:dirt"
    assert game.mining is not None

    for _ in range(200):
        if game.world.get_block((0, 2, 3)) == "minecraft:air":
            break
        game.update(TICK_SECONDS)
    assert game.world.get_block((0, 2, 3)) == "minecraft:air"
    assert game.mining is None


def test_creative_instant_break() -> None:
    """Creative: ЛКМ ломает блок мгновенно, без тиков."""
    game = _game(creative=True)
    game.world.set_block((0, 2, 3), "minecraft:stone")
    _look_forward(game)

    assert game.handle_mouse_click(0) is True
    assert game.world.get_block((0, 2, 3)) == "minecraft:air"
    assert game.mining is None


# ---------------------------------------------------------------------------
# ПКМ: установка
# ---------------------------------------------------------------------------

def test_right_click_places() -> None:
    """ПКМ ставит блок выбранного слота на грань кликнутого блока."""
    game = _game()
    game.inventory.items[0] = ItemStack("minecraft:stone", 1)
    game.inventory.set_selected(0)
    # Взгляд вниз: луч идёт через (0,2,0)/(0,1,0) в траву (0,0,0).
    game.camera.yaw = 0.0
    game.camera.pitch = 90.0
    hit = game.pick()
    assert hit is not None and hit.block == BlockPos(0, 0, 0)

    assert game.handle_mouse_click(1) is True
    # Блок лёг на верхнюю грань: (0,1,0).
    assert game.world.get_block((0, 1, 0)) == "minecraft:stone"
    # Стак израсходован и слот очищен.
    assert game.inventory.items[0] is None


def test_click_no_hit() -> None:
    """Промах: горизонтальный луч на высоте глаз блока не задевает."""
    game = _game()
    _look_forward(game)

    assert game.pick() is None
    assert game.handle_mouse_click(0) is True
    assert game.mining is None
    assert game.handle_mouse_click(1) is True


# ---------------------------------------------------------------------------
# Дальность
# ---------------------------------------------------------------------------

def test_reach_survival() -> None:
    """Блок в 4.8 блока: survival (4.5) — мимо, creative (5.0) — попадание."""
    game = _game()
    game.world.set_block((0, 2, 5), "minecraft:stone")
    # Глаза чуть позади: расстояние по Z до грани блока ровно 4.8.
    game.camera.position = (0.5, 2.62, 0.2)
    _look_forward(game)

    assert game.reach() == 4.5
    assert game.pick() is None

    game.creative = True
    assert game.reach() == 5.0
    hit = game.pick()
    assert hit is not None
    assert hit.block == BlockPos(0, 2, 5)


# ---------------------------------------------------------------------------
# Hotbar
# ---------------------------------------------------------------------------

def test_hotbar_select() -> None:
    """Цифры 1..9 выбирают слот hotbar (номер минус 1)."""
    game = _game()
    assert game.handle_key("1") is True
    assert game.hotbar.selected == 0
    assert game.handle_key("9") is True
    assert game.hotbar.selected == 8
    assert game.handle_key("3") is True
    assert game.hotbar.selected == 2
    # Не цифра — не наше событие.
    assert game.handle_key("z") is False


def test_hotbar_scroll() -> None:
    """Колесо мыши двигает выбор по кругу (вниз — следующий, вверх — прошлый)."""
    game = _game()
    game.hotbar.select(0)

    assert game.handle_scroll(-1.0) is True
    assert game.hotbar.selected == 1
    assert game.handle_scroll(1.0) is True
    assert game.hotbar.selected == 0
    # Из нуля вверх заворачивается на последний слот.
    assert game.handle_scroll(1.0) is True
    assert game.hotbar.selected == 8


# ---------------------------------------------------------------------------
# Инвентарь (E)
# ---------------------------------------------------------------------------

def test_inventory_open() -> None:
    """E открывает экран инвентаря и кладёт его на стек экранов."""
    from quadrix.render.menu import ScreenStack

    game = _game()
    game.stack = ScreenStack(game)
    assert game.inventory_screen is None

    assert game.handle_key("e") is True
    assert game.inventory_screen is not None
    assert game.stack.current is game.inventory_screen


def test_inventory_close() -> None:
    """Escape (и повторный E) закрывают инвентарь и снимают его со стека."""
    from quadrix.render.menu import ScreenStack

    game = _game()
    game.stack = ScreenStack(game)
    game.handle_key("e")
    assert game.inventory_screen is not None
    assert game.stack.current is game.inventory_screen

    assert game.handle_key("escape") is True
    assert game.inventory_screen is None
    assert game.stack.current is game

    game.handle_key("e")
    assert game.inventory_screen is not None
    assert game.handle_key("e") is True
    assert game.inventory_screen is None
    assert game.stack.current is game


def test_inventory_click() -> None:
    """Клик: взять стак из слота и положить его в другой слот."""
    game = _game()
    for i in range(9):
        game.inventory.items[i] = None
    game.inventory.items[0] = ItemStack("minecraft:stone", 5)
    game.handle_key("e")
    screen = game.inventory_screen
    assert screen is not None

    slot0 = next(s for s in screen.slots() if s.index == 0)
    assert screen.handle_click(slot0.x + 1.0, slot0.y + 1.0) is True
    assert screen.carried is not None
    assert screen.carried.item == "minecraft:stone"
    assert game.inventory.get(0) is None

    slot9 = next(s for s in screen.slots() if s.index == 9)
    assert screen.handle_click(slot9.x + 1.0, slot9.y + 1.0) is True
    placed = game.inventory.get(9)
    assert placed is not None and placed.item == "minecraft:stone"
    assert screen.carried is None
