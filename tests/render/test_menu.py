"""Тесты меню/настроек/языка QuadRix (GUI PART 2).

Проверяем реальные данные из ``.local``: список языков берётся из
``assets/pack.mcmeta`` + ``assets/minecraft/lang/*.json``, применение
``ru_ru`` меняет перевод, настройки round-trip'ятся через options.txt и
options.json, а экраны рисуются в батч PART 1 и навигируются стеком.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

from quadrix.core import lang
from quadrix.render.menu import (
    EDITION_TEXT,
    OPTION_CATEGORIES,
    VERSION_TEXT,
    Checkbox,
    GraphicsScreen,
    LanguageScreen,
    MainMenu,
    OptionsScreen,
    Screen,
    ScreenStack,
    ScrollableList,
    Settings,
    TextInput,
    available_languages,
    calculate_scale,
    gui_scaled_size,
    load_language,
)
from quadrix.render.ui import Batch, Font, Rect


@functools.lru_cache(maxsize=1)
def _font() -> Font:
    """Шрифт по умолчанию из ``.local`` (как в test_ui.py)."""
    return Font.load()


class _RecordingFont:
    """Шрифт-шпион: пишет тексты и позиции, квадов не даёт."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, float, float]] = []
        # Белый пиксель для сплошных заливок (Button/Slider FALLBACK).
        self.white = Rect(0.0, 0.0, 1.0, 1.0)

    def width(self, text: str) -> int:
        return len(text) * 6

    def render(self, text: str, x: float, y: float, color: int = 0xFFFFFFFF) -> list:
        self.texts.append((text, float(x), float(y)))
        return []


@pytest.fixture(autouse=True)
def _english() -> None:
    """Каждый тест начинается с ``en_us``: язык процесса — глобальный."""
    lang.set(load_language("en_us"))


# ---------------------------------------------------------------------------
# Screen: рендер в батч
# ---------------------------------------------------------------------------

def test_screen_render_adds_background_quad() -> None:
    screen = Screen(320.0, 200.0)
    batch = Batch()
    screen.render(batch)
    assert len(batch.quads) == 1
    q = batch.quads[0]
    assert (q.x, q.y, q.w, q.h) == (0.0, 0.0, 320.0, 200.0)


def test_main_menu_render_adds_quads_with_and_without_font() -> None:
    menu = MainMenu(854.0, 480.0)
    batch = Batch()
    menu.render(batch, None)
    # 5 текстовых кнопок (по фону) + 3 иконки (фон + иконка-фолбэк) = 11.
    assert len(batch.quads) == 11

    batch2 = Batch()
    menu.render(batch2, _font())
    assert len(batch2.quads) > 11  # добавлены глифы подписей


# ---------------------------------------------------------------------------
# MainMenu: кнопки и их геометрия (title.rs::Mode::Main)
# ---------------------------------------------------------------------------

def test_main_menu_eight_buttons() -> None:
    menu = MainMenu(854.0, 480.0)
    labels = [b.label_plain() for b in menu.buttons]
    assert labels[:5] == [
        "Singleplayer", "Multiplayer", "Minecraft Realms", "Options...", "Quit Game",
    ]
    assert len(menu.buttons) == 8
    # три кнопки-иконки: Friends / Language / Accessibility (title.rs L1824-1847).
    assert [b.icon for b in menu.buttons[5:]] == [
        "gui/sprites/friends/friends",
        "gui/sprites/icon/language",
        "gui/sprites/icon/accessibility",
    ]
    assert all(b.title_style for b in menu.buttons)


def test_main_menu_button_geometry_matches_rust() -> None:
    # title.rs::Title::buttons: cx = floor(w/2), y = floor(h/4) + 48.
    menu = MainMenu(854.0, 480.0)
    cx = 854 // 2
    y = 480 // 4 + 48
    single, multi, realms, options, quit_btn = menu.buttons[:5]
    assert (single.x, single.y, single.w) == (float(cx - 100), float(y), 200.0)
    assert (multi.x, multi.y) == (float(cx - 100), float(y + 24))
    assert (realms.x, realms.y) == (float(cx - 100), float(y + 48))
    # Options и Quit — по 98 в одной строке на y+96 (шаг 24 * 4).
    assert (options.x, options.y, options.w) == (float(cx - 100), float(y + 96), 98.0)
    assert (quit_btn.x, quit_btn.y) == (float(cx + 2), float(y + 96))
    # иконки: (cx-34 + i*24, y+72), 20x20.
    for i, button in enumerate(menu.buttons[5:]):
        assert (button.x, button.y, button.w, button.h) == (
            float(cx - 34 + i * 24), float(y + 72), 20.0, 20.0,
        )


def test_main_menu_click_options_pushes_options_screen() -> None:
    menu = MainMenu(854.0, 480.0)
    stack = ScreenStack(menu)
    menu.on_options = lambda: stack.push(OptionsScreen(stack=stack))

    opts = menu.buttons[3]  # Options...
    hit = opts.handle_click(opts.x + opts.w / 2.0, opts.y + opts.h / 2.0)
    assert hit is True
    assert stack.depth() == 2
    assert isinstance(stack.current, OptionsScreen)


def test_main_menu_callbacks_singleplayer_and_quit() -> None:
    calls: list[str] = []
    menu = MainMenu(854.0, 480.0)
    menu.on_singleplayer = lambda: calls.append("sp")
    menu.on_multiplayer = lambda: calls.append("mp")
    menu.on_quit = lambda: calls.append("quit")

    for button in menu.buttons:
        button.handle_click(button.x + 1.0, button.y + 1.0)
    assert calls == ["sp", "mp", "quit"]


# ---------------------------------------------------------------------------
# OptionsScreen: категории и FOV-слайдер
# ---------------------------------------------------------------------------

def test_options_screen_categories() -> None:
    keys = [key for key, _page in OPTION_CATEGORIES]
    assert "options.video" in keys  # Graphics
    assert "options.sounds" in keys  # Sound
    assert "options.controls" in keys  # Controls
    assert "options.language" in keys  # Language

    opts = OptionsScreen()
    assert len(opts.buttons) == len(OPTION_CATEGORIES)
    assert opts.fov_slider is not None
    assert opts.done_button is not None


def test_options_fov_slider_set_value_and_on_change() -> None:
    settings = Settings()
    opts = OptionsScreen(settings=settings)
    assert opts.fov_slider.value == 70.0

    opts.fov_slider.set_value(90.0)
    assert settings.fov == 90.0

    opts.fov_slider.set_value(1000.0)  # клампится к max диапазона
    assert opts.fov_slider.value == 110.0
    assert settings.fov == 110.0


def test_options_open_language_pushes_language_screen() -> None:
    opts = OptionsScreen()
    stack = ScreenStack(opts)
    opts.stack = stack
    screen = opts.open_page("language")
    assert isinstance(screen, LanguageScreen)
    assert isinstance(stack.current, LanguageScreen)


def test_options_category_click_opens_graphics() -> None:
    opts = OptionsScreen()
    stack = ScreenStack(opts)
    opts.stack = stack
    # кнопка "options.video" — третья категория (i=2).
    video = opts.buttons[2]
    assert video.handle_click(video.x + 1.0, video.y + 1.0) is True
    assert isinstance(stack.current, GraphicsScreen)


# ---------------------------------------------------------------------------
# LanguageScreen: список, выбор и применение
# ---------------------------------------------------------------------------

def test_language_screen_lists_real_languages() -> None:
    langs = available_languages()
    assert len(langs) >= 100  # в .local 143 языка
    codes = {info.code for info in langs}
    assert "en_us" in codes and "ru_ru" in codes

    screen = LanguageScreen()
    assert len(screen.languages) == len(langs)
    ru = next(info for info in screen.languages if info.code == "ru_ru")
    assert ru.label() == f"{ru.name} ({ru.region})"


def test_language_screen_click_and_apply_changes_text() -> None:
    screen = LanguageScreen()
    before = lang.get("menu.singleplayer")
    assert before == "Singleplayer"

    index = next(i for i, info in enumerate(screen.languages) if info.code == "ru_ru")
    row = screen.list
    row.scroll_to(index)  # показать строку (как AbstractSelectionList)
    my = row.row_y(index) + 1.0
    assert row.handle_click(row.x + 1.0, my) is True
    assert row.selected == index

    applied = screen.apply()
    assert applied.code == "ru_ru"
    assert lang.code() == "ru_ru"
    assert screen.settings.language == "ru_ru"
    # перевод реально поменялся (не английская строка)
    assert lang.get("menu.singleplayer") != "Singleplayer"


def test_language_screen_set_language_directly() -> None:
    screen = LanguageScreen()
    language = screen.set_language("de_de")
    assert language.code == "de_de"
    assert lang.code() == "de_de"
    assert screen.settings.language == "de_de"


# ---------------------------------------------------------------------------
# Settings: options.txt / options.json
# ---------------------------------------------------------------------------

def test_settings_load_save_txt_roundtrip(tmp_path: Path) -> None:
    settings = Settings(fov=90.0, render_distance=16, language="fr_fr",
                        master_volume=0.25, vsync=False)
    path = tmp_path / "options.txt"
    settings.save(path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "fov:90" in text and "lang:fr_fr" in text

    loaded = Settings.load(path)
    assert loaded.fov == 90.0
    assert loaded.render_distance == 16
    assert loaded.language == "fr_fr"
    assert loaded.master_volume == 0.25
    assert loaded.vsync is False


def test_settings_load_save_json_roundtrip(tmp_path: Path) -> None:
    settings = Settings(fov=100.0, render_distance=8, language="zh_cn")
    path = tmp_path / "options.json"
    settings.save(path)
    loaded = Settings.load(path)
    assert loaded.fov == 100.0
    assert loaded.render_distance == 8
    assert loaded.language == "zh_cn"


def test_settings_defaults_match_rust() -> None:
    settings = Settings()
    assert settings.fov == 70.0
    assert settings.render_distance == 12
    assert settings.master_volume == 1.0
    assert settings.language == "en_us"


# ---------------------------------------------------------------------------
# Navigation: стек экранов
# ---------------------------------------------------------------------------

def test_screen_stack_push_pop() -> None:
    root = Screen()
    stack = ScreenStack(root)
    assert stack.depth() == 1
    assert stack.current is root

    pushed = stack.push(Screen())
    assert stack.depth() == 2
    assert stack.current is pushed

    popped = stack.pop()
    assert popped is pushed
    assert stack.depth() == 1
    assert stack.current is root

    # корневой экран снять нельзя
    assert stack.pop() is None
    assert stack.depth() == 1


def test_screen_stack_resize_propagates() -> None:
    stack = ScreenStack(MainMenu(854.0, 480.0))
    stack.on_resize(1280.0, 720.0)
    assert stack.current.width == 1280.0
    assert stack.current.height == 720.0


# ---------------------------------------------------------------------------
# Checkbox / TextInput / ScrollableList
# ---------------------------------------------------------------------------

def test_checkbox_toggle_and_on_change() -> None:
    changes: list[bool] = []
    box = Checkbox(10.0, 20.0, "VSync", value=False, on_change=changes.append,
                   hit_width=80.0)

    assert box.handle_click(0.0, 0.0) is False  # вне
    assert box.handle_click(15.0, 25.0) is True  # внутри квадрата
    assert box.value is True
    assert changes == [True]

    # повторный клик снимает флажок
    box.handle_click(15.0, 25.0)
    assert box.value is False
    assert changes == [True, False]

    # выключенный флажок не переключается
    box.active = False
    assert box.toggle() is False
    assert box.value is False


def test_text_input_insert_and_backspace() -> None:
    seen: list[str] = []
    field = TextInput(0.0, 0.0, 100.0, on_change=seen.append)
    assert field.handle_char("a") is False  # нет фокуса

    assert field.handle_click(50.0, 9.0) is True
    assert field.focused is True
    assert field.handle_char("a") is True
    assert field.handle_char("b") is True
    assert field.handle_char("c") is True
    assert field.value == "abc"

    assert field.handle_key("backspace") is True
    assert field.value == "ab"
    assert seen == ["a", "ab", "abc", "ab"]

    # ограничение длины
    field.max_length = 3
    field.handle_char("c")
    assert field.value == "abc"
    assert field.handle_char("d") is False


def test_scrollable_list_scroll_and_click() -> None:
    items = list(range(100))
    chosen: list[tuple[int, int]] = []
    lst = ScrollableList(0.0, 0.0, 200.0, 90.0, items=items, item_height=18.0,
                         on_select=lambda i, item: chosen.append((i, item)))

    assert lst.visible_count() == 5
    assert lst.handle_click(10.0, 1.0) is True
    assert lst.selected == 0 and chosen == [(0, 0)]

    # клик по 3-й видимой строке
    assert lst.handle_click(10.0, 3.0 * 18.0 + 1.0) is True
    assert lst.selected == 3 and chosen[-1] == (3, 3)

    # прокрутка вниз и выбор видимой строки после неё
    assert lst.handle_scroll(5.0) is True
    assert lst.first_visible() == 5
    assert lst.handle_click(10.0, 1.0) is True
    assert lst.selected == 5 and chosen[-1] == (5, 5)

    # прокрутка ограничена диапазоном
    lst.handle_scroll(1000.0)
    assert lst.scroll == pytest.approx(lst.max_scroll())
    lst.handle_scroll(-1000.0)
    assert lst.scroll == 0.0


# ---------------------------------------------------------------------------
# GUI scale (window.rs::calculate_scale / gui_scaled_size) и Opt::GuiScale
# ---------------------------------------------------------------------------

def test_calculate_scale_matches_rust_cases() -> None:
    # Значения из horizon-client-input/src/window.rs (L758-761).
    assert calculate_scale((854, 480), 0, False) == 2
    assert calculate_scale((1920, 1080), 0, False) == 4
    assert calculate_scale((1920, 1080), 3, False) == 3
    assert calculate_scale((1920, 1080), 3, True) == 4
    # gui_scaled_size из того же теста Rust.
    assert gui_scaled_size((1921, 1081), 4) == (481, 271)


def test_graphics_gui_scale_row_cycles_auto_1_max_auto() -> None:
    settings = Settings(gui_scale=0)
    screen = GraphicsScreen(
        settings=settings, stack=None, width=427.0, height=240.0,
        framebuffer=(854, 480),
    )

    def row_point() -> tuple[float, float]:
        cols, lines, _content = screen.layout(settings)
        target = next(
            line for line in lines
            if line.setting is not None and line.setting.kind == "Opt"
            and line.setting.name == "GuiScale"
        )
        # Строка ниже видимой части (General длинная): прокрутить к ней.
        screen.scroll = max(0.0, target.y - 20.0)
        cols, lines, _content = screen.layout(settings)
        for line in lines:
            if (line.setting is not None and line.setting.kind == "Opt"
                    and line.setting.name == "GuiScale"):
                return (cols.list_x + 20.0, screen.row_y(cols, line) + 10.0)
        raise AssertionError("GUI Scale row missing")

    def value() -> str:
        from quadrix.render.graphics import item_label
        return item_label(settings, "Opt", "GuiScale")

    # Подпись: "GUI Scale: Auto" (options.generic_value).
    assert "Auto" in value()

    x, y = row_point()
    assert screen.handle_click(x, y) is True
    assert settings.gui_scale == 1
    assert value().endswith("1")

    x, y = row_point()
    screen.handle_click(x, y)
    assert settings.gui_scale == 2  # max для 854x480
    x, y = row_point()
    screen.handle_click(x, y)
    assert settings.gui_scale == 0  # Auto снова
    assert "Auto" in value()


def test_language_row_click_applies_immediately() -> None:
    settings = Settings(language="en_us")
    screen = LanguageScreen(settings=settings, width=427.0, height=240.0)
    # Вторая строка списка (первая — не обязательно не-en_us).
    target = next(i for i, info in enumerate(screen.list.items)
                  if info.code != "en_us")
    info = screen.list.items[target]
    y = screen.list.row_y(target) + 1.0
    assert screen.handle_click(screen.list.x + 1.0, y) is True

    assert settings.language == info.code
    assert lang.code() == info.code


def test_language_done_applies_and_pops() -> None:
    settings = Settings(language="en_us")
    stack = ScreenStack(MainMenu(427.0, 240.0))
    screen = LanguageScreen(settings=settings, stack=stack,
                            width=427.0, height=240.0)
    stack.push(screen)
    assert stack.current is screen

    target = next(i for i, info in enumerate(screen.list.items)
                  if info.code != "en_us")
    screen.list.selected = target
    screen.choice = screen.list.items[target].code
    assert screen.handle_click(
        screen.done_button.x + 1.0, screen.done_button.y + 1.0
    ) is True

    assert settings.language == screen.list.items[target].code
    assert stack.current is not screen


# ---------------------------------------------------------------------------
# Брендинг: версия в левом нижнем углу и «Python Edition» под логотипом
# ---------------------------------------------------------------------------

def test_main_menu_version_bottom_left() -> None:
    """title.rs L2578-2579: версия в (2, h - 10), как ``Horizon {v} (Rust)``."""
    menu = MainMenu(854.0, 480.0)
    font = _RecordingFont()
    menu.render(Batch(), font)

    assert VERSION_TEXT == "QuadRix 26.3 (Python)"
    hits = [(x, y) for text, x, y in font.texts if text == VERSION_TEXT]
    assert hits, "строка версии не нарисована"
    # draw_text кладёт тень в (+1, +1); сама строка — ровно в (2, h - 10).
    assert (2.0, 480.0 - 10.0) in hits


def test_main_menu_python_edition_under_logo() -> None:
    """Под логотипом — «Python Edition», а не ванильная «Java Edition»."""
    menu = MainMenu(854.0, 480.0)
    font = _RecordingFont()
    menu.render(Batch(), font)

    assert EDITION_TEXT == "Python Edition"
    assert any(text == "Python Edition" for text, _x, _y in font.texts)
    assert not any("Java" in text for text, _x, _y in font.texts)
    # title.rs L105-111: баннер на 30 + 44 - 7; текст 8px центрирован (+3).
    assert any(
        text == "Python Edition" and y == 30.0 + 44.0 - 7.0 + 3.0
        for text, _x, y in font.texts
    )


# ---------------------------------------------------------------------------
# Слайдер настроек: цепочка press → drag → release (не «прилипает»)
# ---------------------------------------------------------------------------

def test_options_fov_slider_drag_release_chain() -> None:
    settings = Settings()
    opts = OptionsScreen(settings=settings, width=854.0, height=480.0)
    slider = opts.fov_slider
    assert slider is not None

    # Нажатие на дорожку берёт ручку.
    assert opts.handle_click(slider.x + 10.0, slider.y + 10.0) is True
    assert slider.dragging is True

    # Движение с зажатой кнопкой тянет значение до max.
    opts.handle_move(slider.x + slider.w - 2.0, slider.y + 10.0)
    dragged = slider.value
    assert dragged > 70.0

    # Отпускание снимает ручку и запоминает значение.
    assert opts.handle_release(slider.x + slider.w - 2.0, slider.y + 10.0) is True
    assert slider.dragging is False

    # Дальнейшее движение мыши значение не меняет.
    opts.handle_move(slider.x + 2.0, slider.y + 10.0)
    assert slider.value == dragged
