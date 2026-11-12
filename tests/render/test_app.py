"""Тесты приложения QuadRix (GUI PART 3): App, связка меню → игра.

Проверяем интеграцию готовых частей: ``App`` открывается на ``MainMenu``,
переключает экраны, передаёт настройки рендеру (FOV/дальность/громкость),
применяет язык к ``quadrix.core.text`` и закрывает бэкенд. Бэкенд — mock
(без дисплея), поэтому тесты идут в CI. Отдельно проверяем флаги
``quadrix.py --gui`` / ``--no-gui``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import numpy as np

from quadrix.core import lang
from quadrix.core import text as core_text
from quadrix.render.app import App, GameScreen, RenderSettings
from quadrix.render.menu import (
    GraphicsScreen,
    LanguageScreen,
    MainMenu,
    OptionsScreen,
    ScreenStack,
    Settings,
    load_language,
)

#: Корень репозитория: tests/render/test_app.py -> ../..
ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# вход в quadrix.py (entry point, не пакет quadrix)
# ---------------------------------------------------------------------------

def _load_entry() -> ModuleType:
    """Загрузить quadrix.py по пути (не как пакет ``quadrix``)."""
    spec = importlib.util.spec_from_file_location("quadrix_entry_app", ROOT / "quadrix.py")
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("не удалось загрузить quadrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = _load_entry()


# ---------------------------------------------------------------------------
# mock-бэкенд (контракт backend.RenderBackend, без дисплея)
# ---------------------------------------------------------------------------

class FakeBackend:
    """Минимальный бэкенд: считает вызовы жизненного цикла и draw."""

    def __init__(self) -> None:
        self.created = 0
        self.presents = 0
        self.closed = 0
        self.draws: list[tuple[object, dict]] = []
        self.event_handler = None

    def set_event_handler(self, handler) -> None:
        self.event_handler = handler

    def create_context(self) -> object:
        self.created += 1
        return object()

    def draw(self, vbo, program=None, texture=None, **kwargs) -> None:
        self.draws.append((vbo, kwargs))

    def present(self) -> None:
        self.presents += 1

    def poll_events(self) -> None:
        pass

    def should_close(self) -> bool:
        return False

    def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def _english() -> None:
    """Язык процесса глобальный: каждый тест начинается с ``en_us``."""
    lang.set(load_language("en_us"))


def _button_center(button) -> tuple[float, float]:
    return button.x + button.w / 2.0, button.y + button.h / 2.0


# ---------------------------------------------------------------------------
# App: инициализация и стек экранов
# ---------------------------------------------------------------------------

def test_app_init_builds_main_menu() -> None:
    backend = FakeBackend()
    app = App.init(backend, Settings(fov=70.0, render_distance=12, master_volume=1.0))

    assert isinstance(app.screen_stack.current, MainMenu)
    assert app.screen_stack.depth() == 1
    assert app.backend is backend
    # снимок настроек для рендера совпадает с настройками
    assert app.render_settings.fov == 70.0
    assert app.render_settings.render_distance == 12
    assert app.render_settings.master_volume == 1.0


# ---------------------------------------------------------------------------
# App.loop: тик + рендер
# ---------------------------------------------------------------------------

class _CountingApp(App):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tick_calls = 0
        self.render_calls = 0

    def tick(self) -> None:
        self.tick_calls += 1
        super().tick()

    def render(self) -> int:
        self.render_calls += 1
        return super().render()


def test_app_loop_one_tick_calls_tick_and_render() -> None:
    backend = FakeBackend()
    app = _CountingApp.init(backend, Settings())

    frames = app.loop(max_ticks=1)

    assert app.tick_calls >= 1
    assert app.render_calls >= 1
    assert app.ticks == 1
    assert frames >= 1
    assert backend.presents >= 1
    assert backend.draws  # кадр дошёл до backend.draw


def test_app_render_flushes_to_backend() -> None:
    backend = FakeBackend()
    app = App.init(backend, Settings())

    vertices = app.render()
    assert vertices > 0
    assert len(backend.draws) == 1
    _vbo, kwargs = backend.draws[0]
    assert kwargs["count"] == vertices


# ---------------------------------------------------------------------------
# App.handle_event: click/key → ScreenStack
# ---------------------------------------------------------------------------

def test_app_handle_event_click_opens_options() -> None:
    app = App.init(FakeBackend(), Settings())
    menu = app.screen_stack.current
    assert isinstance(menu, MainMenu)

    options = menu.buttons[3]  # Options... (0=Single,1=Multi,2=Realms,3=Options)
    x, y = _button_center(options)
    # Экраны и кнопки живут в GUI-пикселях; мышь приходит в пикселях буфера.
    x *= app.width / app.gui_width
    y *= app.height / app.gui_height
    assert app.handle_event("click", x, y) is True

    assert app.screen_stack.depth() == 2
    assert isinstance(app.screen_stack.current, OptionsScreen)


def test_app_handle_event_key_escape_pops_game_screen() -> None:
    app = App.init(FakeBackend(), Settings())
    game = app.open_singleplayer()
    assert isinstance(game, GameScreen)
    assert app.screen_stack.current is game

    assert app.handle_event("key", "escape") is True
    assert app.screen_stack.current is not game
    assert isinstance(app.screen_stack.current, MainMenu)


def test_app_singleplayer_and_multiplayer_push_game_screen() -> None:
    app = App.init(FakeBackend(), Settings())
    single = app.open_singleplayer()
    assert isinstance(single, GameScreen) and single.kind == "singleplayer"

    app.screen_stack.pop()
    multi = app.open_multiplayer()
    # PART 3: Multiplayer ведёт на список серверов, а не сразу в игру.
    from quadrix.render.multiplayer_screen import MultiplayerScreen

    assert isinstance(multi, MultiplayerScreen)
    assert app.screen_stack.current is multi


# ---------------------------------------------------------------------------
# Settings → render: FOV и др.
# ---------------------------------------------------------------------------

def test_app_settings_fov_flows_to_render() -> None:
    app = App.init(FakeBackend(), Settings(fov=70.0))
    app.render()
    assert app.render_settings.fov == 70.0

    app.settings.fov = 90.0
    app.render()
    assert app.render_settings.fov == 90.0

    # и в игру тоже: снимок передаётся GameScreen'у
    game = app.open_singleplayer()
    app.settings.fov = 100.0
    app.render()
    assert game.render_settings.fov == 100.0


# ---------------------------------------------------------------------------
# Language → text
# ---------------------------------------------------------------------------

def test_app_set_language_updates_text_current_lang() -> None:
    app = App.init(FakeBackend(), Settings())
    app.set_language("ru_ru")

    assert app.settings.language == "ru_ru"
    assert lang.code() == "ru_ru"
    # мост lang.set → quadrix.core.text._CURRENT_LANG
    assert core_text._CURRENT_LANG is not None
    assert core_text._CURRENT_LANG.code == "ru_ru"


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

def test_app_shutdown_closes_backend() -> None:
    backend = FakeBackend()
    app = App.init(backend, Settings())

    app.shutdown()
    assert backend.closed == 1

    # повторное закрытие безопасно для App (backend решает идемпотентность сам)
    app.shutdown()
    assert backend.closed == 2


# ---------------------------------------------------------------------------
# quadrix.py: --gui / --no-gui и режимы
# ---------------------------------------------------------------------------

def test_cli_default_is_gui() -> None:
    # По умолчанию режим — GUI: ни headless, ни явный gui не выставлены.
    args = entry.parse_args([])
    assert args.gui is False
    assert args.no_gui is False
    assert args.headless is False


def test_cli_gui_flag_and_no_gui_exclusive() -> None:
    parser = entry.build_parser()
    assert parser.parse_args(["--gui"]).gui is True
    assert parser.parse_args(["--no-gui"]).no_gui is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--gui", "--no-gui"])


def test_cli_gui_and_daemon_prefers_headless() -> None:
    # --gui и --daemon вместе: окно и control-сервер несовместимы,
    # daemon выигрывает — режим становится headless (не аварийный код 2).
    args = entry.parse_args(["--gui", "--daemon"])
    assert args.headless is True
    assert args.gui is False


# ---------------------------------------------------------------------------
# App.setup: создание UI-пайплайна и текстуры (баг program=None на кадре)
# ---------------------------------------------------------------------------

class FakeUniform:
    """Заглушка uniform-а: запоминает записанные байты."""

    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self._name = name

    def write(self, data: bytes) -> None:
        self._store[self._name] = data


class FakeProgram:
    """Заглушка шейдерной программы: принимает ``program["uniform"]``."""

    def __init__(self) -> None:
        self.uniforms: dict[str, bytes] = {}

    def __getitem__(self, name: str) -> FakeUniform:
        return FakeUniform(self.uniforms, name)


class UiBackend(FakeBackend):
    """FakeBackend + создание UI-ресурсов, как настоящий moderngl-бэкенд."""

    def __init__(self) -> None:
        super().__init__()
        self.pipelines = 0
        self.textures = 0
        self.program = FakeProgram()
        self.image: object = None

    def create_pipeline(self, vert_src: str, frag_src: str) -> FakeProgram:
        self.pipelines += 1
        self.vert_src = vert_src
        self.frag_src = frag_src
        return self.program

    def create_texture(self, image: object) -> object:
        self.textures += 1
        self.image = image
        return object()

    def draw(self, vbo, program=None, texture=None, **kwargs) -> None:
        self.draw_program = program
        self.draw_texture = texture
        super().draw(vbo, program, texture, **kwargs)


class _StubFont:
    """Мини-шрифт: только ``atlas_image`` (нужен ``setup`` для текстуры)."""

    def __init__(self) -> None:
        self.atlas_image = np.zeros((4, 4, 4), dtype=np.uint8)


def test_app_setup_creates_ui_program_and_texture() -> None:
    """Причина падения: setup() оставлял program/texture = None."""
    backend = UiBackend()
    app = App.init(backend, Settings(), width=320, height=240, font=_StubFont())

    app.setup()

    assert app.program is not None
    assert app.texture is not None
    # UI-пайплайн + панорама; атлас шрифта + спрайтовый атлас GUI.
    assert backend.pipelines == 2
    assert backend.textures == 2


def test_app_setup_writes_ui_projection() -> None:
    """ui.vert ждёт uniform ``projection``; setup обязан его записать."""
    backend = UiBackend()
    app = App.init(backend, Settings(), width=320, height=240, font=_StubFont())

    app.setup()

    # Ортопроекция 4x4 float32 = 64 байта, записана в program["projection"].
    assert "projection" in backend.program.uniforms
    assert len(backend.program.uniforms["projection"]) == 64


def test_moderngl_draw_requires_program() -> None:
    """draw(program=None) → понятный RuntimeError, а не AttributeError."""
    from quadrix.render.backend_moderngl import ModernglBackend

    backend = ModernglBackend()
    backend.ctx = object()  # контекст «есть», чтобы дойти до проверки program
    data = np.zeros((3, 8), dtype=np.float32)

    with pytest.raises(RuntimeError, match="program not initialized"):
        backend.draw(data, None)


# ---------------------------------------------------------------------------
# Render: проекция, present, состояние 2D-отрисовки
# ---------------------------------------------------------------------------

def test_render_sets_projection_and_draws() -> None:
    """render() идёт через UI-программу и с записанной ортопроекцией."""
    backend = UiBackend()
    app = App.init(backend, Settings(), width=320, height=240)

    app.setup()
    assert "projection" in backend.program.uniforms

    vertices = app.render()

    assert vertices > 0
    # Квады группируются по текстуре (спрайты GUI + глифы атласа шрифта),
    # поэтому draw-вызовов несколько; все — через UI-программу.
    assert len(backend.draws) >= 1
    assert backend.draw_program is backend.program


def test_render_calls_present() -> None:
    """loop() обязан вызвать backend.present() (swap_buffers) на кадр."""
    backend = UiBackend()
    app = App.init(backend, Settings(), width=320, height=240)

    app.loop(max_frames=2)

    assert backend.presents >= 1


def test_batch_flush_requests_2d_state() -> None:
    """Batch.flush просит backend отключить отсечение и включить blend."""
    from quadrix.render.ui import Batch, Quad, rgba

    backend = FakeBackend()
    batch = Batch()
    batch.add_quad(Quad(0, 0, 10, 10, 0.0, 0.0, 1.0, 1.0, rgba(255, 0, 0, 255)))

    count = batch.flush(backend, program=object(), texture=object())

    assert count == 6
    _vbo, kwargs = backend.draws[0]
    assert kwargs["cull_face"] is False
    assert kwargs["depth_test"] is False
    assert kwargs["blend"] is True


class _RecordingVao:
    def __init__(self, events: list) -> None:
        self._events = events

    def render(self, mode, vertices: int) -> None:
        self._events.append(("render", mode, vertices))

    def release(self) -> None:
        self._events.append(("release",))


class _RecordingBuffer:
    size = 96

    def release(self) -> None:
        return None


class _RecordingCtx:
    """Мини-контекст moderngl: записывает enable/disable/clear."""

    def __init__(self) -> None:
        self.events: list = []
        self.blend_func = None

    def enable(self, flag) -> None:
        self.events.append(("enable", flag))

    def disable(self, flag) -> None:
        self.events.append(("disable", flag))

    def buffer(self, data) -> _RecordingBuffer:
        return _RecordingBuffer()

    def vertex_array(self, program, attributes) -> _RecordingVao:
        return _RecordingVao(self.events)

    def clear(self, *color) -> None:
        self.events.append(("clear", color))


def test_moderngl_draw_sets_2d_state() -> None:
    """2D-draw выключает CULL_FACE/DEPTH_TEST и включает BLEND."""
    import moderngl

    from quadrix.render.backend_moderngl import ModernglBackend

    backend = ModernglBackend()
    backend.ctx = _RecordingCtx()
    data = np.zeros((3, 8), dtype=np.float32)

    backend.draw(
        data, object(), None,
        count=3, cull_face=False, depth_test=False, blend=True,
    )

    events = backend.ctx.events
    assert ("disable", moderngl.CULL_FACE) in events
    assert ("disable", moderngl.DEPTH_TEST) in events
    assert ("enable", moderngl.BLEND) in events
    assert any(e[0] == "render" for e in events)


# ---------------------------------------------------------------------------
# Input: события backend → App.handle_event → ScreenStack
# ---------------------------------------------------------------------------

class _RecordingScreen:
    """Экран-шпион: фиксирует клики/клавиши/скролл/resize."""

    def __init__(self) -> None:
        self.width = 320.0
        self.height = 240.0
        self.clicks: list = []
        self.keys: list = []
        self.scrolls: list = []
        self.resizes: list = []
        self.releases: list = []

    def handle_click(self, mx: float, my: float) -> bool:
        self.clicks.append((mx, my))
        return True

    def handle_release(self, mx: float, my: float) -> bool:
        self.releases.append((mx, my))
        return True

    def handle_key(self, key: str, ch=None) -> bool:
        self.keys.append((key, ch))
        return True

    def handle_scroll(self, dy: float) -> bool:
        self.scrolls.append(dy)
        return True

    def on_resize(self, width: float, height: float) -> None:
        self.resizes.append((width, height))

    def render(self, batch, font=None) -> None:
        return None


def test_click_dispatches_to_screen_stack() -> None:
    """App.handle_event('click') → ScreenStack.handle_click (mock-экран)."""
    app = App.init(FakeBackend(), Settings())
    screen = _RecordingScreen()
    app.screen_stack = ScreenStack(screen)

    handled = app.handle_event("click", 12.0, 34.0)

    assert handled is True
    # 854x480 при auto-масштабе (2) → логическое поле 427x240.
    assert screen.clicks == [(6.0, 17.0)]


def test_backend_event_handler_dispatches() -> None:
    """setup() вешает App.handle_event на backend; событие доходит до экрана."""
    backend = UiBackend()
    app = App.init(backend, Settings(), width=320, height=240)
    screen = _RecordingScreen()
    app.screen_stack = ScreenStack(screen)

    app.setup()
    assert backend.event_handler is not None

    backend.event_handler("click", 5.0, 6.0)
    backend.event_handler("scroll", 1.0)

    assert screen.clicks == [(5.0, 6.0)]
    assert screen.scrolls == [1.0]


def test_handle_event_resize_updates_projection() -> None:
    """resize пересчитывает проекцию под новый размер кадрового буфера."""
    backend = UiBackend()
    app = App.init(backend, Settings(), width=320, height=240)

    app.setup()
    first = backend.program.uniforms["projection"]

    assert app.handle_event("resize", 1000.0, 800.0) is True

    assert app.width == 1000
    assert app.height == 800
    # auto-масштаб вырос до 3 → логическое поле 334x267 (проекция иная).
    assert (app.gui_width, app.gui_height) == (334, 267)
    assert backend.program.uniforms["projection"] != first

# ---------------------------------------------------------------------------
# GUI scale и язык через App (реальный путь клика: буфер → GUI-пиксели)
# ---------------------------------------------------------------------------

def test_app_gui_scale_click_changes_logical_size() -> None:
    app = App.init(FakeBackend(), Settings(gui_scale=0), width=854, height=480)
    assert (app.gui_width, app.gui_height) == (427, 240)

    options = app.open_options()
    options.open_page("graphics")
    graphics = app.screen_stack.current
    assert isinstance(graphics, GraphicsScreen)

    cols, lines, _content = graphics.layout(app.settings)
    row = next(
        line for line in lines
        if line.setting is not None and line.setting.kind == "Opt"
        and line.setting.name == "GuiScale"
    )
    # Строка ниже видимой части (General длинная): прокрутить к ней.
    graphics.scroll = max(0.0, row.y - 20.0)
    cols, lines, _content = graphics.layout(app.settings)
    row = next(
        line for line in lines
        if line.setting is not None and line.setting.kind == "Opt"
        and line.setting.name == "GuiScale"
    )
    x = cols.list_x + 20.0
    y = graphics.row_y(cols, row) + 10.0
    assert app.handle_event(
        "click",
        x * app.width / app.gui_width,
        y * app.height / app.gui_height,
    ) is True
    assert app.settings.gui_scale == 1

    app.render()
    assert (app.gui_width, app.gui_height) == (854, 480)
    # Экран пересобрался под новый логический размер.
    assert graphics.width == 854.0 and graphics.height == 480.0


def test_app_language_row_click_applies_without_leaving_screen() -> None:
    app = App.init(FakeBackend(), Settings(language="en_us"),
                   width=854, height=480)
    language = app.open_language()
    assert isinstance(language, LanguageScreen)

    row = next(i for i, info in enumerate(language.list.items)
               if info.code != "en_us")
    info = language.list.items[row]
    language.list.scroll_to(row)
    y = language.list.row_y(row) + 2.0
    assert app.handle_event(
        "click",
        (language.list.x + 10.0) * app.width / app.gui_width,
        y * app.height / app.gui_height,
    ) is True

    assert app.settings.language == info.code
    assert lang.code() == info.code
    # Выбор виден сразу, экран остаётся открытым до Done/back.
    assert app.screen_stack.current is language


# ---------------------------------------------------------------------------
# Input: отпускание ЛКМ (баг «слайдер прилипает к курсору»)
# ---------------------------------------------------------------------------

def test_release_dispatches_to_screen_stack() -> None:
    """App.handle_event('release') → ScreenStack.handle_release (mock-экран)."""
    app = App.init(FakeBackend(), Settings())
    screen = _RecordingScreen()
    app.screen_stack = ScreenStack(screen)

    assert app.handle_event("release", 12.0, 34.0) is True
    # 854x480 при auto-масштабе (2) → логическое поле 427x240.
    assert screen.releases == [(6.0, 17.0)]


class _FakeGlfw:
    """Мини-константы glfw для проверки mouse-button callback без дисплея."""

    MOUSE_BUTTON_LEFT = 0
    PRESS = 1
    RELEASE = 0


def test_backend_mouse_button_emits_click_and_release() -> None:
    """glfw PRESS → 'click', RELEASE → 'release' (порт MouseInput)."""
    from quadrix.render.backend_moderngl import ModernglBackend

    backend = ModernglBackend()
    backend._glfw = _FakeGlfw()
    events: list = []
    backend.set_event_handler(lambda kind, *args: events.append((kind, args)))
    backend._mouse_x, backend._mouse_y = 3.0, 4.0

    backend._on_mouse_button(None, _FakeGlfw.MOUSE_BUTTON_LEFT, _FakeGlfw.PRESS, 0)
    backend._on_mouse_button(None, _FakeGlfw.MOUSE_BUTTON_LEFT, _FakeGlfw.RELEASE, 0)
    # Кнопка не ЛКМ — событие не уходит.
    backend._on_mouse_button(None, 1, _FakeGlfw.PRESS, 0)

    assert [kind for kind, _ in events] == ["click", "release"]
    assert events[0][1] == (3.0, 4.0, 0)
    assert events[1][1] == (3.0, 4.0, 0)


# ---------------------------------------------------------------------------
# Брендинг: нигде «Horizon» в текстах/окне/логах (кроме ссылок на Rust)
# ---------------------------------------------------------------------------

def test_no_horizon_in_branding() -> None:
    import re

    from quadrix.render import app as app_mod
    from quadrix.render import menu as menu_mod

    # Заголовок окна, строка версии, подпись издания — QuadRix.
    assert "Horizon" not in app_mod.WINDOW_TITLE
    assert "Horizon" not in menu_mod.VERSION_TEXT
    assert "Horizon" not in menu_mod.EDITION_TEXT

    # Исходники: «Horizon» допустим только в комментариях-ссылках на Rust.
    files = [
        ROOT / "quadrix.py",
        ROOT / "quadrix/render/menu.py",
        ROOT / "quadrix/render/app.py",
        ROOT / "quadrix/render/ui.py",
        ROOT / "quadrix/render/graphics_ui.py",
        ROOT / "quadrix/render/graphics.py",
        ROOT / "quadrix/render/backend_moderngl.py",
    ]
    # Строка/скобка-литерал «Horizon» или лог «[Horizon]» — недопустимы.
    pattern = re.compile(r"[\"'\[]Horizon\b")
    offenders: list[str] = []
    for path in files:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if line.lstrip().startswith("#"):
                continue  # комментарий-ссылка на Rust (порт)
            if pattern.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], offenders
