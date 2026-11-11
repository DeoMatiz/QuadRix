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

from quadrix.core import lang
from quadrix.core import text as core_text
from quadrix.render.app import App, GameScreen, RenderSettings
from quadrix.render.menu import (
    MainMenu,
    OptionsScreen,
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

    options = menu.buttons[2]  # Options...
    x, y = _button_center(options)
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
    assert isinstance(multi, GameScreen) and multi.kind == "multiplayer"


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

def test_cli_default_is_headless() -> None:
    args = entry.build_parser().parse_args([])
    assert args.gui is False
    assert args.no_gui is False


def test_cli_gui_flag_and_no_gui_exclusive() -> None:
    parser = entry.build_parser()
    assert parser.parse_args(["--gui"]).gui is True
    assert parser.parse_args(["--no-gui"]).no_gui is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--gui", "--no-gui"])


def test_cli_gui_and_daemon_incompatible() -> None:
    # --gui и --daemon вместе → код 2, окно даже не открывается
    assert entry.main(["--gui", "--daemon"]) == 2
