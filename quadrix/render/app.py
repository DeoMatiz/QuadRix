"""Приложение QuadRix: связка меню → игра (GUI PART 3).

PART 3 — интеграция готовых частей: берёт экранную модель PART 2
(``quadrix/render/menu.py``), примитивы PART 1 (``quadrix/render/ui.py``)
и рендер-бэкенд (``quadrix/render/backend.py``) и собирает из них главный
цикл приложения ``App``: инициализация, тик 20 Гц + рендер в каждом кадре,
переключение экранов, применение настроек к рендеру и языка к тексту.

Порт Horizon (Rust → Python), читаем только точку входа и переключение
экранов:
    * ``horizon-client/src/entry.rs``       — ``main``: старт, разбор args,
      ``game::run_with()`` (наш ``App.loop``), завершение.
    * ``horizon-client/src/game/startup_menu.rs`` — ``StartupMenu``: титул
      (``Title``), ``OptionsUi``, ``handoff`` в игру; menю → игра.
    * ``horizon-client/src/game.rs``        — ``fn tick`` (20 Гц),
      ``fn render`` (кадр), ``enum Screen`` (``Playing``, ``Options``, ...);
      ``Gui.setScreen`` = наш ``ScreenStack``.

Что НЕ входит в PART 3 (следующие фазы): полный gameplay (WASD,
подключение к серверу, бинды), HUD, mobs, worldgen. ``GameScreen`` —
заглушка (см. ``# FALLBACK`` ниже), которая честно сообщает о своём статусе
в ``PORTING_STATE.yaml`` и просто держит переключение экранов.
"""

from __future__ import annotations

import json
import random as _random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from quadrix.core import lang
from quadrix.core.geometry import BlockPos, Vec3
from quadrix.core.lang import Language
from quadrix.input.input_state import InputState
from quadrix.input.keybinds import KeyBinds
from quadrix.input.mouse import LookOptions, MouseLook, Rotation as MouseRotation
from quadrix.items.items import ItemStack
from quadrix.motion.core import (
    MovementResources,
    PlayerMotion,
    jump_from_ground,
    tick as motion_tick,
    travel as motion_travel,
)
from quadrix.render.camera import Camera
from quadrix.render.game_world import (
    ChunkTerrainRenderer,
    FlatWorld,
    TerrainRenderer,
    checker_texture,
)
from quadrix.render.gui_atlas import GUI_TEXTURE, load_gui_atlas
from quadrix.render.hotbar import Hotbar
from quadrix.render.interaction import BlockHitResult, pick_block, reach_for
from quadrix.render.inventory_screen import InventoryScreen
from quadrix.render.menu import (
    FOV_DEFAULT,
    MASTER_VOLUME_DEFAULT,
    PACK_ROOT,
    RENDER_DISTANCE_DEFAULT,
    LanguageScreen,
    MainMenu,
    OptionsScreen,
    Screen,
    ScreenStack,
    Settings,
    calculate_scale,
    draw_text,
    effective_gui_scale,
    gui_scaled_size,
    load_language,
    solid,
)
from quadrix.render.panorama import Panorama, Rotation, load_panorama
from quadrix.render.remote import RemoteConnection
from quadrix.render.multiplayer_screen import (
    MultiplayerScreen,
    ServersStore,
    parse_address,
)
from quadrix.render.ui import Batch, Button, Font
from quadrix.world.block_placement import (
    PlacementContext,
    default_placement,
    get_placement_state,
    relative as relative_pos,
)
from quadrix.world.block_survival import break_block
from quadrix.world.player_inventory import PlayerInventory

__all__ = [
    "App",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "GameScreen",
    "Mining",
    "RenderSettings",
    "TICK_RATE",
    "TICK_SECONDS",
]

#: Один такт игры: 20 Гц (как ``game.rs::fn tick`` / ``Client.tick``).
TICK_RATE: int = 20
TICK_SECONDS: float = 1.0 / TICK_RATE

#: Размер окна по умолчанию (как GUI-размер в тестах PART 2).
DEFAULT_WIDTH: int = 854
DEFAULT_HEIGHT: int = 480

#: Заголовок окна (порт ``crash::version``/безымянного окна Rust).
WINDOW_TITLE: str = "QuadRix"


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] app: " + message)


@dataclass
class RenderSettings:
    """Снимок настроек, которые видит рендер/игра.

    Порт полей ``settings.rs::Settings``, которые читает кадр:
    ``fov`` (угол обзора), ``render_distance`` и ``master_volume``.
    ``App`` пересобирает снимок каждый кадр, поэтому меню и рендер всегда
    согласованы.
    """

    fov: float = FOV_DEFAULT
    render_distance: int = RENDER_DISTANCE_DEFAULT
    master_volume: float = MASTER_VOLUME_DEFAULT


#: Путь к ``gameplay-facts.json`` (hardness блоков; как в ``block_survival``).
_FACTS_PATH = (
    Path(".local") / "horizon-client" / "26.3" / "gameplay-facts.json"
)
#: Кэш списка фактов состояний (индексируется ``BlockStateId.id``).
_FACTS_STATES: Optional[list] = None


def block_hardness(name: str) -> float:
    """Твёрдость блока по имени из ``gameplay-facts.json`` (порт ``facts``).

    ``game.rs::destroy_progress`` берёт ``hardness`` состояния из фактов.
    Таблица состояний в ``.local`` (порядок = ``block-registry.nbt``), поэтому
    id состояния — индекс фактов. Неизвестный блок — 1.0 (безопасный дефолт).
    """
    global _FACTS_STATES
    if _FACTS_STATES is None:
        try:
            _FACTS_STATES = json.loads(_FACTS_PATH.read_text(encoding="utf-8"))["states"]
        except (OSError, ValueError, KeyError):
            _FACTS_STATES = []
    from quadrix.world.block_placement import default_registry

    sid = default_registry().default_state(name)
    if sid is None or sid.id < 0 or sid.id >= len(_FACTS_STATES):
        return 1.0
    return float(_FACTS_STATES[sid.id].get("hardness", 1.0))


@dataclass
class Mining:
    """Текущая цель добычи (порт ``game.rs::Mining``).

    ``progress`` накапливается за тики; ``>= 1.0`` — блок разрушен.
    """

    pos: tuple[int, int, int]
    progress: float = 0.0
    ticks: int = 0


class GameScreen(Screen):
    """Игровой экран (порт ``Screen::Playing``) — Gameplay PART 1.

    Держит состояние игрока (:class:`PlayerMotion`), мир, ввод и камеру.
    Каждый тик (20 Гц) собирает :class:`PlayerInput` из :class:`InputState`
    и прогоняет движение: ``jump_from_ground`` → ``travel`` → ``tick``
    (порт ``motion.rs::local_tick`` / ``controlled_simulation_tick``).
    Мышь вращает камеру через :class:`MouseLook` (порт ``mouse.rs``).

    Мир пока плоский (``# FALLBACK:`` см. ``quadrix/render/game_world.py``):
    настоящие чанки — следующий PART.
    """

    #: Стартовый набор Gameplay PART 2 (локальный демо-мир без сервера).
    #: В Rust creative-инвентарь открывается клавишей Creative; здесь хотбар
    #: предзаполнен блоками, чтобы клик сразу что-то ставил/ломал.
    DEFAULT_HOTBAR: tuple[str, ...] = (
        "minecraft:grass_block",
        "minecraft:dirt",
        "minecraft:stone",
        "minecraft:oak_planks",
        "minecraft:cobblestone",
        "minecraft:sand",
        "minecraft:glass",
        "minecraft:oak_log",
        "minecraft:torch",
    )
    #: ``destroy_delay`` (game.rs): тики между мгновенными разрушениями.
    DESTROY_DELAY: int = 5
    #: Дельта прогресса добычи за тик: ``1 / (hardness * N)``.
    #: FALLBACK: полная формула ``destroy_progress`` (скорость инструмента,
    #: enchant, on-ground) не портирована — здесь упрощённая зависимость от
    #: твёрдости блока, как в ванильном «руками».
    MINING_TICKS_PER_HARDNESS: float = 20.0

    def __init__(
        self,
        kind: str = "singleplayer",
        settings: Optional[Settings] = None,
        stack: Optional[ScreenStack] = None,
        width: float = DEFAULT_WIDTH,
        height: float = DEFAULT_HEIGHT,
        render_settings: Optional[RenderSettings] = None,
        world: Optional[FlatWorld] = None,
        player_motion: Optional[PlayerMotion] = None,
        input_state: Optional[InputState] = None,
        keybinds: Optional[KeyBinds] = None,
        on_close: Optional[Any] = None,
        creative: bool = False,
        on_pointer: Optional[Any] = None,
        inventory: Optional[PlayerInventory] = None,
        address: Optional[str] = None,
        client: Optional[Any] = None,
        remote: Optional[Any] = None,
        on_disconnect: Optional[Any] = None,
    ) -> None:
        super().__init__(width, height)
        self.kind = kind
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        self.render_settings = (
            render_settings if render_settings is not None else RenderSettings()
        )
        self.on_close = on_close
        #: ``true`` — режим creative (мгновенное разрушение, дальность 5.0).
        self.creative = bool(creative)
        #: Коллбэк захвата/отпускания курсора (``App._set_mouse_grabbed``).
        self.on_pointer = on_pointer

        # -- мультиплеер (Gameplay PART 3) --------------------------------
        #: Адрес сервера (``None`` — локальный singleplayer).
        self.address = address
        #: Подключённый :class:`Client` (или ``None``).
        self.client = client
        #: :class:`RemoteConnection` фонового чтения пакетов (или ``None``).
        self.remote = remote
        #: Коллбэк «отключились от сервера» (``App._remote_disconnected``).
        self.on_disconnect = on_disconnect
        self._disconnected = False
        #: Счётчик sequence для play-пакетов действий (Rust next_sequence).
        self._sequence = 0

        # -- инвентарь / hotbar (Gameplay PART 2) -------------------------
        self.inventory = inventory if inventory is not None else PlayerInventory()
        self.hotbar = Hotbar(self.inventory)
        self.inventory_screen: Optional[InventoryScreen] = None
        self.mining: Optional[Mining] = None
        self.destroy_delay: int = 0
        self._rng = _random.Random()
        self._populate_default_hotbar()

        # -- ввод ---------------------------------------------------------
        self.input_state = input_state if input_state is not None else InputState()
        self.keybinds = keybinds if keybinds is not None else KeyBinds()
        self.mouse_look = MouseLook(
            look=LookOptions(sensitivity=float(self.settings.sensitivity))
        )
        #: Поворот игрока (yaw/pitch) — :class:`quadrix.input.mouse.Rotation`.
        self.rotation = MouseRotation()
        self._time = 0.0

        # -- мир и игрок --------------------------------------------------
        if client is not None:
            # Реальный мир сервера: блоки из ClientWorld, движение — Client.motion.
            self.world = client.world
            client_motion = getattr(client, "motion", None)
            if client_motion is not None:
                self.player_motion = client_motion
                ground_top = None
            else:
                # Сервер ещё не прислал позицию — временная мотивация до неё.
                self.player_motion = PlayerMotion.new(
                    MovementResources(properties={}), Vec3(0.0, 64.0, 0.0)
                )
                ground_top = None
        else:
            self.world = world if world is not None else FlatWorld()
            ground_top = getattr(self.world, "ground_top", 4)
            if player_motion is not None:
                self.player_motion = player_motion
            else:
                # MovementResources не нужен для PlayerMotion.new (см. motion.rs);
                # travel() сам читает .nbt. Пустые ресурсы экономят загрузку.
                self.player_motion = PlayerMotion.new(
                    MovementResources(properties={}),
                    Vec3(0.5, float(ground_top), 0.5),
                )
        self.camera = Camera(
            position=(
                self.player_motion.position.x,
                self.player_motion.position.y + self.player_motion.eye_height(),
                self.player_motion.position.z,
            ),
            yaw=float(self.player_motion.yaw),
            pitch=0.0,
            fov=float(self.render_settings.fov),
        )
        if client is not None:
            # Меш реальных чанков сервера (пересобирается по мере прихода).
            self.terrain = ChunkTerrainRenderer(self.world)
            self.terrain.refresh()
        else:
            self.terrain = TerrainRenderer(self.world)

        self.back_button = Button(
            (float(width) / 2.0) - 100.0,
            float(height) - 27.0,
            200.0,
            20.0,
            lang.get_or("gui.back", "Back"),
            on_click=self._back,
        )

    # -- навигация -------------------------------------------------------

    def _back(self) -> None:
        # Мультиплеер: Escape закрывает соединение и возвращает в список серверов.
        if self.remote is not None or self.client is not None:
            self.disconnect()
            return
        if self.on_close is not None:
            self.on_close()
        if self.stack is not None:
            self.stack.pop()

    # -- горячий старт (Gameplay PART 2) --------------------------------

    def _populate_default_hotbar(self) -> None:
        """Заполнить hotbar стартовыми блоками (демо-мир без сервера)."""
        for i, name in enumerate(self.DEFAULT_HOTBAR):
            self.inventory.items[i] = ItemStack(name, 64)

    # -- raytrace клика (game.rs::aim / pick / reach) ---------------------

    def eye_position(self) -> Vec3:
        """Позиция глаз (``Camera`` уже включает ``eye_height``)."""
        x, y, z = self.camera.position
        return Vec3(float(x), float(y), float(z))

    def look_vector(self) -> Vec3:
        """Направление взгляда (``pick_view_vector``)."""
        f = self.camera.forward()
        return Vec3(float(f[0]), float(f[1]), float(f[2]))

    def reach(self) -> float:
        """Дальность клика по блоку (creative 5.0 / survival 4.5)."""
        return reach_for(self.creative)

    def pick(self) -> Optional[BlockHitResult]:
        """Первое попадание по блоку вдоль взгляда (``Game::pick``)."""
        return pick_block(
            self.world, self.eye_position(), self.look_vector(), self.reach()
        )

    # -- клик: разрушение / установка (game.rs::play_mouse/tick_mining) ---

    def handle_mouse_click(self, button: int = 0) -> bool:
        """Клик в мире: 0 — атака (добыча), 1 — использование (установка)."""
        if self.inventory_screen is not None:
            return True
        if button == 0:
            self._start_attack()
        elif button == 1:
            self._use()
        return True

    def _start_attack(self) -> Optional[BlockHitResult]:
        """ЛКМ: creative — мгновенно, survival — начать добычу (tick_mining).

        Мультиплеер: вместо локального мира — play-пакет (START/STOP
        destroy block), см. :meth:`_remote_attack`.
        """
        if self.client is not None:
            return self._remote_attack()
        hit = self.pick()
        if hit is None:
            self.mining = None
            return None
        pos = (hit.block.x, hit.block.y, hit.block.z)
        if self.creative:
            if self.destroy_delay > 0:
                # Между мгновенными разрушениями (game.rs: destroy_delay).
                return hit
            self._destroy(pos)
            self.destroy_delay = self.DESTROY_DELAY
            return hit
        self.mining = Mining(pos=pos)
        return hit

    def tick_mining(self) -> None:
        """Один тик добычи (``Game::tick_mining``)."""
        if self.destroy_delay > 0:
            self.destroy_delay -= 1
        mining = self.mining
        if mining is None:
            return
        hit = self.pick()
        if hit is None or (hit.block.x, hit.block.y, hit.block.z) != mining.pos:
            self.mining = None
            return
        hardness = block_hardness(self.world.get_block(mining.pos))
        step = 1.0 / max(1.0, hardness * self.MINING_TICKS_PER_HARDNESS)
        mining.progress += step
        mining.ticks += 1
        if mining.progress >= 1.0:
            self.mining = None
            self._destroy(mining.pos)
            self.destroy_delay = self.DESTROY_DELAY

    def _destroy(self, pos: tuple[int, int, int]) -> list[ItemStack]:
        """Разрушить блок: дроп в инвентарь (``Game::break_block``)."""
        stack = self.inventory.selected_item()
        drops = break_block(self.world, pos, stack, self._rng)
        for drop in drops:
            self.inventory.add_stack(drop)
        self.inventory.changed()
        return drops

    def _use(self) -> bool:
        """ПКМ: поставить блок предметом из выбранного слота.

        Порт ``use_hand``/``use_item_on``: позиция — сам кликнутый блок, если
        его можно заменить, иначе сосед по грани (``BlockPlaceContext``).
        Мультиплеер: play-пакет ``UseItemOn`` (см. :meth:`_remote_use`).
        """
        if self.client is not None:
            return self._remote_use()
        hit = self.pick()
        if hit is None:
            return False
        stack = self.inventory.selected_item()
        if stack is None or stack.is_empty():
            return False
        placement = default_placement()
        player_input = self.input_state.to_player_input(self.keybinds)
        yaw = float(self.camera.yaw)
        pitch = float(self.camera.pitch)
        clicked = hit.block
        cpos = (clicked.x, clicked.y, clicked.z)
        base_ctx = PlacementContext(
            pos=clicked,
            hit_pos=clicked,
            face=hit.direction,
            hit=hit.location,
            inside=hit.inside,
            yaw=yaw,
            pitch=pitch,
            sneaking=bool(player_input.sneak),
            item=stack.item,
        )
        target_state = self.world.get_block(cpos)
        if placement.can_be_replaced(target_state, base_ctx):
            pos = cpos
            replace_clicked = True
        else:
            pos = relative_pos(cpos, hit.direction)
            replace_clicked = False
        ctx = PlacementContext(
            pos=BlockPos(pos[0], pos[1], pos[2]),
            hit_pos=clicked,
            face=hit.direction,
            hit=hit.location,
            inside=hit.inside,
            yaw=yaw,
            pitch=pitch,
            sneaking=bool(player_input.sneak),
            item=stack.item,
            replace_clicked=replace_clicked,
        )
        state = get_placement_state(stack, ctx, placement=placement)
        if state is None:
            return False
        if not placement.can_place(self.world, state, pos, ctx):
            return False
        if not placement.place(self.world, pos, state, 11):
            return False
        self._consume_selected(stack)
        return True

    def _consume_selected(self, stack: ItemStack) -> None:
        """Уменьшить выбранный стак на 1 (очистить слот, если опустел)."""
        stack.count -= 1
        if stack.count <= 0:
            self.inventory.set_selected_item(None)
        self.inventory.changed()

    # -- инвентарь (E) ----------------------------------------------------

    def open_inventory(self) -> Optional[InventoryScreen]:
        """Открыть экран инвентаря (``Minecraft.setScreen``, отпустить курсор)."""
        if self.inventory_screen is not None:
            return self.inventory_screen
        screen = InventoryScreen(
            self.inventory,
            self.width,
            self.height,
            on_close=self._close_inventory,
        )
        self.inventory_screen = screen
        if self.stack is not None:
            self.stack.push(screen)
        if self.on_pointer is not None:
            self.on_pointer(False)
        return screen

    def _close_inventory(self) -> None:
        """Закрыть инвентарь (снять со стека, вернуть курсор в игру)."""
        screen = self.inventory_screen
        if screen is None:
            return
        self.inventory_screen = None
        stack = self.stack
        if stack is not None:
            inner = getattr(stack, "_stack", None)
            if inner and inner[-1] is screen:
                stack.pop()
        if self.on_pointer is not None:
            self.on_pointer(True)

    # -- навигация -------------------------------------------------------

    def title_key(self) -> str:
        """Ключ перевода заголовка (``menu.singleplayer`` / ``menu.multiplayer``)."""
        return "menu." + self.kind

    def title(self) -> str:
        return lang.get_or(self.title_key(), self.kind.title())

    # -- тик: ввод → PlayerInput → PlayerMotion ---------------------------

    def update(self, dt: float) -> None:
        """Один тик игры: ввод → движение (порт ``controlled_simulation_tick``)."""
        self._time += dt
        if self.remote is not None or self.client is not None:
            self._update_remote(dt)
            return
        player_input = self.input_state.to_player_input(self.keybinds)
        motion = self.player_motion
        if player_input.jump and motion.on_ground:
            jump_from_ground(motion, self.world, player_input)
        motion_travel(motion, player_input, self.world)
        motion_tick(motion, dt, self.world)
        self.tick_mining()
        self._sync_camera()

    def _sync_camera(self) -> None:
        """Позиция/углы камеры из PlayerMotion (порт ``Camera.alignWithEntity``)."""
        motion = self.player_motion
        self.camera.position = (
            motion.position.x,
            motion.position.y + motion.eye_height(),
            motion.position.z,
        )
        self.camera.yaw = float(motion.yaw)
        self.camera.pitch = float(self.rotation.x_rot)
        self.camera.fov = float(self.render_settings.fov)

    # -- мультиплеер: тик через Client.tick (Gameplay PART 3) --------------

    def _update_remote(self, dt: float) -> None:
        """Тик реального соединения: ввод → ``Client.tick`` → камера/меши.

        Движение выполняется **только** через ``Client.tick()``
        (AGENTS.md: иначе рассинхрон с сервером): GUI кладёт ввод в
        ``pending_input``, а ``Client.tick`` сам делает ``travel`` +
        ``tick`` + ``sync_client_to_server``.
        """
        client = self.client
        if client is None:
            return
        remote = self.remote
        # Фоновый поток упал (подключение/разрыв) — уходим со экрана.
        if remote is not None and remote.error is not None:
            self._remote_failed(remote.error)
            return
        motion = getattr(client, "motion", None)
        if motion is not None and self.player_motion is not motion:
            # Подключение завершилось в потоке — берём серверную мотивацию.
            self.player_motion = motion
        # Поворот из мыши (yaw/pitch), как в локальном пути.
        if motion is not None:
            motion.yaw = float(self.rotation.y_rot)
            try:
                motion.pitch = float(self.rotation.x_rot)
            except AttributeError:
                pass
            player_input = self.input_state.to_player_input(self.keybinds)
            client.pending_input = player_input
            client.pending_input_ticks = 1
            if player_input.jump and motion.on_ground:
                jump_from_ground(motion, self.world, player_input)
            try:
                client.tick()
            except BaseException as exc:  # noqa: BLE001 — разрыв соединения
                self._remote_failed(exc)
                return
        # Новые чанки пришли из потока — пересобрать меши.
        terrain = self.terrain
        refresh = getattr(terrain, "refresh", None)
        if callable(refresh):
            refresh()
        self._sync_camera()

    def _next_sequence(self) -> int:
        """Следующий sequence player-action (Rust ``next_sequence``)."""
        value = self._sequence
        self._sequence += 1
        return value

    def _send_packet(self, packet: Any) -> bool:
        """Отправить serverbound play-пакет через ``Client._send``."""
        client = self.client
        if client is None:
            return False
        try:
            from quadrix.protocol.packets import play

            body = play.Serverbound.encode(packet)
            client._send(body)
            return True
        except Exception as exc:  # noqa: BLE001 — отправка не критична
            _log(f"пакет не отправлен: {exc}")
            return False

    def _remote_attack(self) -> Optional[BlockHitResult]:
        """ЛКМ по серверу: START_DESTROY_BLOCK (0) + STOP (2) (creative)."""
        hit = self.pick()
        if hit is None:
            return None
        pos = (hit.block.x, hit.block.y, hit.block.z)
        direction = int(hit.direction.value)
        from quadrix.protocol.packets import play

        self._send_packet(
            play.PlayerAction(action=0, pos=pos, direction=direction,
                              sequence=self._next_sequence())
        )
        self._send_packet(
            play.PlayerAction(action=2, pos=pos, direction=direction,
                              sequence=self._next_sequence())
        )
        return hit

    def _remote_use(self) -> bool:
        """ПКМ по серверу: UseItemOn (face/cursor из попадания)."""
        hit = self.pick()
        if hit is None:
            return False
        cursor = (
            float(hit.location.x) - float(hit.block.x),
            float(hit.location.y) - float(hit.block.y),
            float(hit.location.z) - float(hit.block.z),
        )
        from quadrix.protocol.packets import play

        packet = play.UseItemOn(
            hand=0,
            pos=(hit.block.x, hit.block.y, hit.block.z),
            face=int(hit.direction.value),
            cursor=cursor,
            inside=bool(hit.inside),
            world_border=False,
            sequence=self._next_sequence(),
        )
        return self._send_packet(packet)

    def _remote_failed(self, exc: BaseException) -> None:
        """Соединение разорвано: закрыть и вернуться в список серверов."""
        _log(f"соединение с сервером потеряно: {exc}")
        self.disconnect()

    def disconnect(self) -> None:
        """Отключиться от сервера и вернуться в список (идемпотентно)."""
        if self._disconnected:
            return
        self._disconnected = True
        remote = self.remote
        if remote is not None:
            try:
                remote.stop()
            except Exception as exc:  # noqa: BLE001 — закрытие не критично
                _log(f"ошибка закрытия соединения: {exc}")
            self.remote = None
        elif self.client is not None:
            try:
                self.client.close()
            except Exception as exc:  # noqa: BLE001 — закрытие не критично
                _log(f"ошибка закрытия клиента: {exc}")
        self.client = None
        if self.on_disconnect is not None:
            self.on_disconnect()
        if self.stack is not None:
            self.stack.pop()

    # -- ввод -------------------------------------------------------------

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        """Клавиши игры: инвентарь (E), выбор hotbar (1..9), Escape.

        Пока открыт инвентарь, клавиши идут ему (``E``/``Escape`` закрывают).
        """
        if self.inventory_screen is not None:
            return bool(self.inventory_screen.handle_key(key, ch))
        if key == "escape":
            self._back()
            return True
        if self.hotbar.select_key(key):
            return True
        if key == "e":
            self.open_inventory()
            return True
        return False

    def handle_scroll(self, dy: float) -> bool:
        """Колесо мыши — выбор слота hotbar (``Inventory.swapPaint``).

        Ваниль: прокрутка вверх (``dy > 0``) — предыдущий слот.
        """
        if self.inventory_screen is not None:
            return False
        self.hotbar.scroll(-1 if dy > 0 else 1)
        return True

    def handle_key_down(self, key: str) -> bool:
        """Нажатие ванильной клавиши (``key.keyboard.w``) → InputState."""
        return self.input_state.press(key)

    def handle_key_up(self, key: str) -> bool:
        """Отпускание ванильной клавиши."""
        return self.input_state.release(key)

    def handle_mouse_move(self, dx: float, dy: float) -> bool:
        """Относительное движение мыши → yaw/pitch (порт ``MouseHandler``)."""
        self.input_state.add_mouse(dx, dy)
        self.mouse_look.add_motion(dx, dy)
        turn = self.mouse_look.handle_accumulated_movement(
            self._time, True, True
        )
        if turn is not None:
            self.rotation.turn(*turn)
            self.player_motion.yaw = self.rotation.y_rot
        self._sync_camera()
        return True

    # -- рендер -----------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        """HUD над terrain: прицел в центре + hotbar (``hud_layout::hotbar``)."""
        cx = self.width / 2.0
        cy = self.height / 2.0
        color = 0xFFFFFFFF
        solid(batch, font, cx - 5.0, cy - 0.5, 10.0, 1.0, color)
        solid(batch, font, cx - 0.5, cy - 5.0, 1.0, 10.0, color)
        self.hotbar.render(batch, font, self.width, self.height)

    def render_terrain(self, backend: Any, program: Any, texture: Any) -> None:
        """Нарисовать меш мира с MVP камеры (вызывает ``App.render``)."""
        self.terrain.draw(
            backend, program, texture, self.camera, self.width, self.height
        )

    def handle_click(self, mx: float, my: float) -> bool:
        return self.back_button.handle_click(mx, my)


class App:
    """Главный цикл QuadRix: экраны, тик и рендер.

    Порт ``entry.rs::main`` (старт и завершение) и ``game.rs`` (``fn tick``
    + ``fn render``).  ``backend`` — любой объект, реализующий контракт
    :class:`quadrix.render.backend.RenderBackend`; в PART 3 достаточно
    ``create_context``/``draw``/``present``/``close`` (тесты подставляют
    mock без дисплея).
    """

    def __init__(
        self,
        backend: Any = None,
        settings: Optional[Settings] = None,
        *,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        font: Optional[Font] = None,
        load_font: bool = False,
    ) -> None:
        self.backend = backend
        self.settings = settings if settings is not None else Settings()
        self.width = int(width)
        self.height = int(height)
        # GUI scale (``window.rs``): 0 = auto, иначе 1..max. Экраны и мышь
        # работают в логических (GUI) пикселях, кадр — в пикселях буфера.
        self.gui_scale = effective_gui_scale(
            self.settings, (self.width, self.height)
        )
        self.gui_width, self.gui_height = gui_scaled_size(
            (self.width, self.height), self.gui_scale
        )
        self.font: Optional[Font] = font
        if self.font is None and load_font:
            self.font = self._safe_font()

        self.batch = Batch()
        self.program: Any = None
        self.texture: Any = None
        #: Пайплайн terrain (создаётся лениво при входе в игру) + текстура.
        self.terrain_program: Any = None
        self.terrain_texture: Any = None
        #: Спрайтовый атлас GUI + GPU-текстура (кнопки/логотип/фон/иконки).
        self.atlas: Any = None
        self.gui_texture: Any = None
        #: Панорама главного меню (кубмап) + её поворот/таймер.
        self.panorama: Optional[Panorama] = None
        self.panorama_rotation = Rotation()
        self._started = time.monotonic()

        self.ticks = 0
        self.frames = 0
        self.running = False
        #: Курсор захвачен игрой (порт ``MouseHandler.grabMouse``).
        self._mouse_grabbed = False
        #: Текущий ``GameScreen`` (порт ``Game.screen == Screen::Playing``).
        self.game: Optional[GameScreen] = None
        #: Фабрика :class:`Client` для GUI (ставит ``quadrix.py::run_gui``).
        #: Сигнатура: ``factory(host, port) -> Client``. ``None`` — офлайн-демо.
        self.client_factory: Optional[Any] = None
        #: Список сохранённых серверов (multiplayer_screen.ServersStore).
        self.servers_store = ServersStore()
        #: Снимок настроек, которые получает рендер (см. ``RenderSettings``).
        self.render_settings = self._snapshot_settings()
        self.screen_stack = ScreenStack(self._build_main_menu())

    # ------------------------------------------------------------------
    # создание / стек экранов
    # ------------------------------------------------------------------

    @classmethod
    def init(
        cls,
        backend: Any = None,
        settings: Optional[Settings] = None,
        **kwargs: Any,
    ) -> "App":
        """Собрать приложение (порт ``entry.rs::main`` → ``game::run_with``).

        Стек открывается на ``MainMenu``; ``setup()`` отдельно открывает
        окно/контекст, поэтому ``init`` безопасен в тестах без дисплея.
        """
        app = cls(backend, settings, **kwargs)
        _log(f"App: экран {type(app.screen_stack.current).__name__}")
        return app

    def _build_main_menu(self) -> MainMenu:
        """Главное меню с обработчиками (порт ``Title`` / ``StartupMenu``)."""
        return MainMenu(
            float(self.gui_width),
            float(self.gui_height),
            on_quit=self.quit,
            on_singleplayer=self.open_singleplayer,
            on_multiplayer=self.open_multiplayer,
            on_options=self.open_options,
            on_realms=self._noop,
            on_friends=self._noop,
            on_language=self.open_language,
            on_accessibility=self._noop,
        )

    def _noop(self) -> None:
        """Заглушка действия (Friend/Realms/Accessibility — вне PART 3)."""
        _log("действие недоступно в PART 3")

    def _rebuild_screens(self) -> None:
        """Перестроить экраны (после смены языка переводы должны обновиться)."""
        stack = getattr(self.screen_stack, "_stack", [])
        for screen in list(stack):
            build = getattr(screen, "build", None)
            if callable(build):
                build()

    def _on_language_applied(self, code: str) -> None:
        """Язык применён экраном; обновить подписи экранов под ним.

        Текущий ``LanguageScreen`` не пересобираем: он сам обновил свои
        подписи, а пересборка сбросила бы прокрутку и позицию выбора.
        """
        self.settings.language = code
        stack = getattr(self.screen_stack, "_stack", [])
        for screen in list(stack):
            if screen is self.screen_stack.current:
                continue
            build = getattr(screen, "build", None)
            if callable(build):
                build()

    def _sync_gui_scale(self, *, force: bool = False) -> None:
        """Пересчитать GUI scale и размеры экранов (``Window.setGuiScale``)."""
        scale = effective_gui_scale(self.settings, (self.width, self.height))
        gui_width, gui_height = gui_scaled_size(
            (self.width, self.height), scale
        )
        if not force and (scale, gui_width, gui_height) == (
            self.gui_scale, self.gui_width, self.gui_height
        ):
            return
        self.gui_scale = scale
        self.gui_width, self.gui_height = gui_width, gui_height
        stack = getattr(self, "screen_stack", None)
        if stack is not None:
            stack.on_resize(float(gui_width), float(gui_height))
        self._set_ui_projection()
        _log(f"GUI scale: {scale} ({gui_width}x{gui_height})")

    def _screen_pos(self, mx: float, my: float) -> tuple[float, float]:
        """Пиксели кадрового буфера → логические (GUI) координаты.

        Порт ``window.rs::scaled_pos``: ``pos * gui_scaled / screen``.
        """
        width = float(self.width) or 1.0
        height = float(self.height) or 1.0
        return (
            mx * self.gui_width / width,
            my * self.gui_height / height,
        )

    # ------------------------------------------------------------------
    # навигация (порт ``Gui.setScreen`` / ``StartupMenu``)
    # ------------------------------------------------------------------

    def quit(self) -> None:
        """Выход: остановить цикл (пункт «Quit Game»)."""
        self.running = False
        _log("выход по запросу меню")

    def open_options(self) -> OptionsScreen:
        """MainMenu → OptionsScreen (кнопка Options...)."""
        screen = OptionsScreen(
            settings=self.settings,
            stack=self.screen_stack,
            width=self.screen_stack.current.width,
            height=self.screen_stack.current.height,
            framebuffer=(self.width, self.height),
        )
        self.screen_stack.push(screen)
        _log("экран: OptionsScreen")
        return screen

    def open_language(self) -> LanguageScreen:
        """MainMenu → LanguageScreen (кнопка-иконка Language)."""
        screen = LanguageScreen(
            settings=self.settings,
            stack=self.screen_stack,
            width=self.screen_stack.current.width,
            height=self.screen_stack.current.height,
            on_apply=self._on_language_applied,
        )
        self.screen_stack.push(screen)
        _log("экран: LanguageScreen")
        return screen

    def open_singleplayer(self) -> GameScreen:
        """MainMenu → Singleplayer → GameScreen (локальный плоский мир)."""
        return self._open_game("singleplayer")

    def open_multiplayer(self) -> MultiplayerScreen:
        """MainMenu → Multiplayer → список серверов (PART 3).

        Раньше кнопка сразу открывала ``GameScreen``; теперь она ведёт на
        ``MultiplayerScreen`` (Rust: ``Title`` → ``MultiplayerScreen``), а
        игра открывается после подключения (``connect_server``).
        """
        screen = MultiplayerScreen(
            width=self.screen_stack.current.width,
            height=self.screen_stack.current.height,
            store=self.servers_store,
            stack=self.screen_stack,
            on_back=self._multiplayer_back,
            on_connect=self.connect_server,
        )
        self.screen_stack.push(screen)
        _log("экран: MultiplayerScreen")
        return screen

    def _multiplayer_back(self) -> None:
        """Back из списка серверов → предыдущий экран."""
        self.screen_stack.pop()

    def _pop_connect_screens(self) -> None:
        """Закрыть Direct/Add поверх списка серверов перед входом в игру."""
        while (
            self.screen_stack.depth() > 1
            and not isinstance(self.screen_stack.current, MultiplayerScreen)
        ):
            self.screen_stack.pop()

    def connect_server(self, address: str) -> Optional[GameScreen]:
        """Подключиться к серверу и открыть реальный ``GameScreen`` (PART 3).

        Порт ``title.rs::Action::Connect`` → ``game.rs::connect_server``:
        создаётся :class:`Client`, соединение поднимается в фоне
        (:class:`RemoteConnection`), а окно сразу показывает игру.
        """
        parsed = parse_address(address)
        if parsed is None:
            _log(f"адрес не разобран: {address!r}")
            return None
        host, port = parsed
        self._ensure_terrain_resources()
        client: Optional[Any] = None
        factory = self.client_factory
        if factory is not None:
            try:
                client = factory(host, port)
            except Exception as exc:  # noqa: BLE001 — сервер недоступен
                _log(f"клиент не создан для {host}:{port}: {exc}")
                client = None
        remote: Optional[RemoteConnection] = None
        if client is not None:
            remote = RemoteConnection(client)
            remote.start()
        self._pop_connect_screens()
        screen = GameScreen(
            kind="multiplayer",
            settings=self.settings,
            stack=self.screen_stack,
            width=self.screen_stack.current.width,
            height=self.screen_stack.current.height,
            render_settings=self.render_settings,
            on_close=self._close_game,
            on_pointer=self._set_mouse_grabbed,
            address=address,
            client=client,
            remote=remote,
            on_disconnect=self._remote_disconnected,
        )
        self.screen_stack.push(screen)
        self.game = screen
        self._set_mouse_grabbed(True)
        _log(f"экран: GameScreen (connect {host}:{port})")
        return screen

    def _remote_disconnected(self) -> None:
        """GameScreen закрыл соединение (Escape/разрыв): отпустить курсор."""
        self.game = None
        self._set_mouse_grabbed(False)
        _log("отключено от сервера")

    def _open_game(self, kind: str) -> GameScreen:
        self._ensure_terrain_resources()
        screen = GameScreen(
            kind=kind,
            settings=self.settings,
            stack=self.screen_stack,
            width=self.screen_stack.current.width,
            height=self.screen_stack.current.height,
            render_settings=self.render_settings,
            on_close=self._close_game,
            on_pointer=self._set_mouse_grabbed,
        )
        self.screen_stack.push(screen)
        self.game = screen
        # Игра забирает курсор (порт ``MouseHandler.grabMouse``).
        self._set_mouse_grabbed(True)
        _log(f"экран: GameScreen ({kind})")
        return screen

    def _close_game(self) -> None:
        """GameScreen закрыт (Escape/Back): отпустить курсор."""
        self.game = None
        self._set_mouse_grabbed(False)

    def _set_mouse_grabbed(self, grabbed: bool) -> None:
        self._mouse_grabbed = bool(grabbed)
        backend = self.backend
        setter = getattr(backend, "set_mouse_grabbed", None)
        if callable(setter):
            setter(grabbed)

    def _ensure_terrain_resources(self) -> None:
        """Создать terrain-пайплайн и текстуру (лениво, при входе в игру).

        В ``setup`` их нет намеренно: menus тестов считают вызовы
        ``create_pipeline``/``create_texture`` (PART 3).
        """
        if self.backend is None:
            return
        create_pipeline = getattr(self.backend, "create_pipeline", None)
        create_texture = getattr(self.backend, "create_texture", None)
        if self.terrain_program is None and callable(create_pipeline):
            from quadrix.render.backend_moderngl import load_shader

            self.terrain_program = create_pipeline(
                load_shader("terrain.vert"), load_shader("terrain.frag")
            )
        if self.terrain_texture is None and callable(create_texture):
            self.terrain_texture = create_texture(checker_texture())


    # ------------------------------------------------------------------
    # настройки → рендер
    # ------------------------------------------------------------------

    def _snapshot_settings(self) -> RenderSettings:
        """Текущие настройки рендера (FOV, дальность, громкость)."""
        return RenderSettings(
            fov=float(self.settings.fov),
            render_distance=int(self.settings.render_distance),
            master_volume=float(self.settings.master_volume),
        )

    def _apply_settings(self) -> RenderSettings:
        """Settings → render: пересобрать снимок и передать игре."""
        self.render_settings = self._snapshot_settings()
        if self.game is not None:
            self.game.render_settings = self.render_settings
        return self.render_settings

    @property
    def fov(self) -> float:
        return float(self.settings.fov)

    @property
    def render_distance(self) -> int:
        return int(self.settings.render_distance)

    @property
    def master_volume(self) -> float:
        return float(self.settings.master_volume)

    # ------------------------------------------------------------------
    # язык → текст (порт ``lang::set`` из ``StartupMenu::set_root``)
    # ------------------------------------------------------------------

    def set_language(self, code: str, root: Path | str = PACK_ROOT) -> Language:
        """Загрузить и применить язык ``code`` (обновляет ``text._CURRENT_LANG``).

        ``lang.set`` — тот же мост, что и в Rust: все экраны читают
        перевод через ``lang``, а ``quadrix/core/text.py`` получает язык в
        ``_CURRENT_LANG``.
        """
        try:
            language = load_language(code, root)
        except Exception as exc:  # noqa: BLE001 - любой провал чтения ресурсов
            _log(f"язык {code!r} не загружен ({exc}); остаёмся на {lang.DEFAULT!r}")
            code = lang.DEFAULT
            language = load_language(code, root)
        lang.set(language)
        self.settings.language = code
        self._rebuild_screens()
        _log(f"язык: {code}")
        return language

    # ------------------------------------------------------------------
    # жизненный цикл (порт ``entry.rs`` / ``game.rs``)
    # ------------------------------------------------------------------

    def setup(self) -> "App":
        """Открыть окно/контекст, загрузить шрифт и применить язык.

        Вызывается из ``main`` перед ``loop``. В тестах без дисплея не
        вызывается — ``init`` уже даёт готовый стек экранов.
        """
        if self.backend is not None:
            create = getattr(self.backend, "create_context", None)
            if callable(create):
                create()
        if self.font is None:
            self.font = self._safe_font()
        self.set_language(self.settings.language)
        self._create_ui_resources()
        # Ввод: backend вызывает self.handle_event на click/key/scroll/resize.
        set_handler = getattr(self.backend, "set_event_handler", None)
        if callable(set_handler):
            set_handler(self.handle_event)
        _log(f"setup: backend={type(self.backend).__name__ if self.backend else None}")
        return self

    def _create_ui_resources(self) -> None:
        """Создать UI-пайплайн и текстуру атласа шрифта.

        ``render`` передаёт ``self.program``/``self.texture`` в
        ``Batch.flush``, а тот — в ``backend.draw``.  Без программы
        moderngl падает на первом кадре
        (``'NoneType' object has no attribute '_attribute_locations'``).
        Без backend (тесты без дисплея) GPU-ресурсы не нужны — выходим.
        """
        if self.backend is None:
            return

        create_pipeline = getattr(self.backend, "create_pipeline", None)
        if self.program is None and callable(create_pipeline):
            # Шейдеры ui.vert/ui.frag лежат в quadrix/render/shaders.
            from quadrix.render.backend_moderngl import load_shader

            self.program = create_pipeline(
                load_shader("ui.vert"), load_shader("ui.frag")
            )
            self._set_ui_projection()

        create_texture = getattr(self.backend, "create_texture", None)
        if (
            self.texture is None
            and self.font is not None
            and callable(create_texture)
        ):
            self.texture = create_texture(self.font.atlas_image)

        # Спрайтовый атлас ванильных виджетов (кнопки, логотип, фон, иконки).
        if self.atlas is None:
            self.atlas = load_gui_atlas()
        if (
            self.atlas is not None
            and self.gui_texture is None
            and callable(create_texture)
        ):
            self.gui_texture = create_texture(self.atlas.image)
        self.batch.atlas = self.atlas
        if self.gui_texture is not None:
            self.batch.textures[GUI_TEXTURE] = self.gui_texture

        # Панорама главного меню (кубмап + поворот).
        if self.panorama is None:
            self.panorama = Panorama(load_panorama())
        self.panorama.prepare(self.backend)

    def _set_ui_projection(self) -> None:
        """Записать ортопроекцию (GUI-пиксели → clip space) в ``ui.vert``.

        Без неё uniform ``projection`` остаётся нулевым, и все квады
        схлопываются в точку. Начало координат — верхний левый угол.
        """
        if self.program is None:
            return
        width = float(self.gui_width) or 1.0
        height = float(self.gui_height) or 1.0
        # x∈[0,w] -> [-1,1]; y∈[0,h] -> [1,-1] (экранная ось Y направлена вниз).
        projection = np.array(
            [
                [2.0 / width, 0.0, 0.0, -1.0],
                [0.0, -2.0 / height, 0.0, 1.0],
                [0.0, 0.0, -1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        # moderngl ждёт column-major, numpy даёт row-major → транспонируем.
        self.program["projection"].write(projection.T.tobytes())

    def _safe_font(self) -> Optional[Font]:
        """Загрузить шрифт из ``.local``; ``None`` при любой ошибке (рисуем без текста)."""
        try:
            return Font.load()
        except Exception as exc:  # noqa: BLE001 - шрифт не критичен для PART 3
            _log(f"шрифт не загружен: {exc}")
            return None

    def handle_events(self) -> None:
        """Опрос окна (порт ``window_event``/``about_to_wait`` glfw-части)."""
        backend = self.backend
        if backend is None:
            return
        poll = getattr(backend, "poll_events", None)
        if callable(poll):
            poll()
        should_close = getattr(backend, "should_close", None)
        if callable(should_close) and should_close():
            self.running = False

    def handle_event(self, kind: str, *args: Any) -> bool:
        """Одно событие UI: click/key/scroll/resize → ``ScreenStack``.

        ``True``, если экран событие принял (порт ``Game::window_event``).
        """
        if kind == "click":
            mx, my = self._screen_pos(float(args[0]), float(args[1]))
            button = int(args[2]) if len(args) > 2 else 0
            current = self.screen_stack.current
            # В захваченном курсоре клик — это действие в мире (атака/использование).
            if isinstance(current, GameScreen) and self._mouse_grabbed:
                return bool(current.handle_mouse_click(button))
            return bool(self.screen_stack.handle_click(mx, my))
        if kind == "key":
            key = args[0]
            ch = args[1] if len(args) > 1 else None
            return bool(self.screen_stack.handle_key(key, ch))
        if kind == "scroll":
            return bool(self.screen_stack.handle_scroll(float(args[0])))
        if kind == "move":
            # Курсор переместился — обновляем подсветку наведения (hover).
            mx, my = self._screen_pos(float(args[0]), float(args[1]))
            return bool(self.screen_stack.handle_move(mx, my))
        if kind == "mouse_move":
            # Относительное движение мыши (игра, захваченный курсор).
            return self._handle_mouse_move(float(args[0]), float(args[1]))
        if kind == "keydown":
            # Нажатие ванильной клавиши (InputState / GameScreen).
            return self._handle_key_state(args[0], pressed=True)
        if kind == "keyup":
            return self._handle_key_state(args[0], pressed=False)
        if kind == "release":
            # ЛКМ отпущена — завершаем перетаскивание (слайдер больше не липнет).
            mx, my = self._screen_pos(float(args[0]), float(args[1]))
            return bool(self.screen_stack.handle_release(mx, my))
        if kind == "resize":
            self.width = int(args[0]) or self.width
            self.height = int(args[1]) or self.height
            # GL viewport тоже привязан к размеру кадрового буфера.
            resize = getattr(self.backend, "resize", None)
            if callable(resize):
                resize(self.width, self.height)
            # GUI scale (auto) зависит от размера буфера — пересчитать.
            self._sync_gui_scale(force=True)
            return True
        return False

    def _handle_key_state(self, key: str, *, pressed: bool) -> bool:
        """keydown/keyup → InputState экрана игры (порт ``HeldKeys``)."""
        screen = self.screen_stack.current
        if not isinstance(screen, GameScreen):
            return False
        if pressed:
            return bool(screen.handle_key_down(key))
        return bool(screen.handle_key_up(key))

    def _handle_mouse_move(self, dx: float, dy: float) -> bool:
        """Относительное движение мыши → обзор камеры."""
        screen = self.screen_stack.current
        if not isinstance(screen, GameScreen):
            return False
        return bool(screen.handle_mouse_move(dx, dy))

    def tick(self) -> None:
        """Один игровой такт (20 Гц): счётчик + движение игрока."""
        self.ticks += 1
        if self.game is not None:
            self.game.render_settings = self.render_settings
            self.game.update(TICK_SECONDS)

    def render(self) -> int:
        """Кадр: очистка + панорама + экран → батч → ``backend.draw``.

        Один ``clear()`` на кадр (панорама и UI не затирают друг друга).
        Панорама кубмапа рисуется только под главным меню
        (``game.rs::shows_panorama``). Возвращает число вершин (0, если
        backend нет или нечего рисовать).
        """
        self._apply_settings()
        self._sync_gui_scale()
        self.batch.clear()
        backend = self.backend
        if backend is None:
            return 0

        # Очистка кадра ровно один раз: иначе каждый draw стирал бы панораму.
        clear = getattr(backend, "clear", None)
        if callable(clear):
            clear()

        # Панорама — фон главного меню (только MainMenu, как shows_panorama()).
        if self.panorama is not None and isinstance(
            self.screen_stack.current, MainMenu
        ):
            yaw = self.panorama_rotation.update(
                time.monotonic(), self._panorama_speed()
            )
            self.panorama.draw(backend, self.width, self.height, yaw)

        # Terrain — фон игрового экрана (рисуется до HUD-батча).
        current = self.screen_stack.current
        if (
            isinstance(current, GameScreen)
            and self.terrain_program is not None
        ):
            current.render_terrain(
                backend, self.terrain_program, self.terrain_texture
            )

        # Спрайтовый атлас нужен виджетам для nine-slice/логотипа.
        self.batch.atlas = self.atlas
        self.screen_stack.render(self.batch, self.font)
        return self.batch.flush(backend, self.program, self.texture)

    def _panorama_speed(self) -> float:
        """Скорость вращения панорамы (``options_file.rs``: 1.0 по умолчанию)."""
        try:
            return float(self.settings.file.get("panoramaScrollSpeed", 1.0))
        except (TypeError, ValueError):  # noqa: BLE001 - битое значение файла
            return 1.0

    def loop(self, max_ticks: int = 0, max_frames: int = 0) -> int:
        """Главный цикл: фиксированный тик 20 Гц, рендер в каждом кадре.

        ``max_ticks``/``max_frames`` ограничивают прогон (0 — без предела);
        так же ``--ticks`` останавливает headless-клиент. Возвращает число
        нарисованных кадров.
        """
        self.running = True
        frames = 0
        # Аккумулятор примирован одним тактом: первый кадр всегда тикает,
        # поэтому цикл прогрессирует и детерминирован в тестах.
        accumulator = TICK_SECONDS
        last = time.monotonic()
        while self.running:
            self.handle_events()
            if not self.running:
                break
            now = time.monotonic()
            accumulator += now - last
            last = now
            while accumulator >= TICK_SECONDS:
                self.tick()
                accumulator -= TICK_SECONDS
                if max_ticks and self.ticks >= max_ticks:
                    break
            self.render()
            present = getattr(self.backend, "present", None)
            if callable(present):
                present()
            frames += 1
            if max_ticks and self.ticks >= max_ticks:
                self.running = False
            if max_frames and frames >= max_frames:
                self.running = False
        self.frames += frames
        _log(f"loop: кадров={frames}, тиков={self.ticks}")
        return frames

    def shutdown(self) -> None:
        """Остановить цикл и освободить бэкенд (идемпотентно)."""
        self.running = False
        backend = self.backend
        if backend is not None:
            close = getattr(backend, "close", None)
            if callable(close):
                close()
        _log("shutdown")
