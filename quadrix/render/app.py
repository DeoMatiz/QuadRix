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

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from quadrix.core import lang
from quadrix.core.lang import Language
from quadrix.render.gui_atlas import GUI_TEXTURE, load_gui_atlas
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
from quadrix.render.ui import Batch, Button, Font

__all__ = [
    "App",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "GameScreen",
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


class GameScreen(Screen):
    """Заглушка игрового экрана (порт ``Screen::Playing``).

    ``# FALLBACK: полный gameplay (WASD, подключение, бинды) pending —``
    следующая фаза.  Здесь только каркас: экран рисует фон и заголовок,
    Escape/Back возвращают в меню, а рендер-настройки (FOV и т.п.)
    применяются к ``render_settings``.
    """

    def __init__(
        self,
        kind: str = "singleplayer",
        settings: Optional[Settings] = None,
        stack: Optional[ScreenStack] = None,
        width: float = DEFAULT_WIDTH,
        height: float = DEFAULT_HEIGHT,
        render_settings: Optional[RenderSettings] = None,
    ) -> None:
        super().__init__(width, height)
        self.kind = kind
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        self.render_settings = (
            render_settings if render_settings is not None else RenderSettings()
        )
        self.back_button = Button(
            (float(width) / 2.0) - 100.0,
            float(height) - 27.0,
            200.0,
            20.0,
            lang.get_or("gui.back", "Back"),
            on_click=self._back,
        )

    def _back(self) -> None:
        if self.stack is not None:
            self.stack.pop()

    def title_key(self) -> str:
        """Ключ перевода заголовка (``menu.singleplayer`` / ``menu.multiplayer``)."""
        return "menu." + self.kind

    def title(self) -> str:
        return lang.get_or(self.title_key(), self.kind.title())

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, 0.0, 0.0, self.width, self.height, 0x000000FF)
        if font is not None:
            text = self.title()
            tw = font.width(text)
            draw_text(batch, font, text, (self.width - tw) / 2.0, self.height / 2.0)
        self.back_button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        return self.back_button.handle_click(mx, my)

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key == "escape":
            self._back()
            return True
        return False


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
        #: Текущий ``GameScreen`` (порт ``Game.screen == Screen::Playing``).
        self.game: Optional[GameScreen] = None
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
        """MainMenu → Singleplayer → GameScreen (заглушка)."""
        return self._open_game("singleplayer")

    def open_multiplayer(self) -> GameScreen:
        """MainMenu → Multiplayer → GameScreen (заглушка)."""
        return self._open_game("multiplayer")

    def _open_game(self, kind: str) -> GameScreen:
        screen = GameScreen(
            kind=kind,
            settings=self.settings,
            stack=self.screen_stack,
            width=self.screen_stack.current.width,
            height=self.screen_stack.current.height,
            render_settings=self.render_settings,
        )
        self.screen_stack.push(screen)
        self.game = screen
        _log(f"экран: GameScreen ({kind})")
        return screen

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

    def tick(self) -> None:
        """Один игровой такт (20 Гц): счётчик + настройки игры."""
        self.ticks += 1
        if self.game is not None:
            self.game.render_settings = self.render_settings

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
