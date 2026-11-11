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

from quadrix.core import lang
from quadrix.core.lang import Language
from quadrix.render.menu import (
    FOV_DEFAULT,
    MASTER_VOLUME_DEFAULT,
    PACK_ROOT,
    RENDER_DISTANCE_DEFAULT,
    MainMenu,
    OptionsScreen,
    Screen,
    ScreenStack,
    Settings,
    draw_text,
    load_language,
    solid,
)
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
        self.font: Optional[Font] = font
        if self.font is None and load_font:
            self.font = self._safe_font()

        self.batch = Batch()
        self.program: Any = None
        self.texture: Any = None

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
            float(self.width),
            float(self.height),
            on_quit=self.quit,
            on_singleplayer=self.open_singleplayer,
            on_multiplayer=self.open_multiplayer,
            on_options=self.open_options,
        )

    def _rebuild_screens(self) -> None:
        """Перестроить экраны (после смены языка переводы должны обновиться)."""
        stack = getattr(self.screen_stack, "_stack", [])
        for screen in list(stack):
            build = getattr(screen, "build", None)
            if callable(build):
                build()

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
        )
        self.screen_stack.push(screen)
        _log("экран: OptionsScreen")
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
        _log(f"setup: backend={type(self.backend).__name__ if self.backend else None}")
        return self

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
            return bool(self.screen_stack.handle_click(float(args[0]), float(args[1])))
        if kind == "key":
            key = args[0]
            ch = args[1] if len(args) > 1 else None
            return bool(self.screen_stack.handle_key(key, ch))
        if kind == "scroll":
            return bool(self.screen_stack.handle_scroll(float(args[0])))
        if kind == "resize":
            self.screen_stack.on_resize(float(args[0]), float(args[1]))
            return True
        return False

    def tick(self) -> None:
        """Один игровой такт (20 Гц): счётчик + настройки игры."""
        self.ticks += 1
        if self.game is not None:
            self.game.render_settings = self.render_settings

    def render(self) -> int:
        """Кадр: экран → батч → один ``backend.draw``.

        Возвращает число вершин (0, если backend нет или нечего рисовать).
        """
        self._apply_settings()
        self.batch.clear()
        self.screen_stack.render(self.batch, self.font)
        if self.backend is None:
            self.batch.clear()
            return 0
        return self.batch.flush(self.backend, self.program, self.texture)

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
