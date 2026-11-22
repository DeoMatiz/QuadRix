#!/usr/bin/env python3
"""[QuadRix] Create World: Experiments + ConfirmExperimentalFeatures (WC6).

Порт двух Rust-файлов (Golden Rule 1 — один PART = оба, они связаны):

    * ``horizon-client/src/title/experiments.rs`` — ``ExperimentsScreen``:
      feature-паки, что поставляет jar (``data/minecraft/datapacks``), каждый
      со switch под красным предупреждением, что их нельзя выключить после
      создания мира. Раскладка как у vanilla: ``HeaderAndFooterLayout``
      (header/footer 33), предупреждение ``MultiLineTextWidget`` шириной 310,
      ``SwitchGrid`` 299 с информацией под каждым switch.
    * ``horizon-client/src/title/confirm_experiments.rs`` —
      ``ConfirmExperimentsScreen``: предупреждение, что выбранные паки просят
      экспериментальные фичи, и вторым экраном (``DetailsScreen``) их флаги.
      Vanilla центрирует сетку (колонки 10, ряды 20): заголовок, сообщение на
      310, кнопка Details 100, затем Proceed и Back.

Порт сохраняет структуру и константы Rust:
    * ``RESEARCH``-хелпер :func:`feature_packs` — PART ``datapack.rs``
      (``ServerPacksSource`` сканирует ``resources/data/minecraft/datapacks``:
      папка с ``pack.mcmeta``, id = имя папки, ``pack.mcmeta.features.enabled``);
    * :func:`repository_flags` (``ExperimentsScreen.init``) и
      :func:`confirm_entries` (``ConfirmExperimentalFeaturesScreen::new``);
    * геометрия/рендер и обёртки :class:`ExperimentsScreen` /
      :class:`ConfirmExperimentsScreen` над :class:`~quadrix.render.menu.Screen`.

Ввод/вывод (как в title.rs):
    * CreateWorld id 30 (Experiments) открывает :class:`ExperimentsScreen`;
      Done пишет выбранные паки в ``options.data_packs`` (прочие сохраняют
      порядок, включённые feature-паки дописываются в обратном порядке экрана);
      Cancel их отбрасывает.
    * :class:`ConfirmExperimentsScreen` открывается через
      ``CreateWorldScreen.offer_data_packs`` (порт ``title.rs::offer_data_packs``),
      как только среди выбранных есть feature-пак: Details — флаги, Proceed —
      применить ``pending``, Back/Escape — назад (в Details — из деталей).

FALLBACK (см. ``PORTING_STATE.yaml``):
    * ``datapack.rs`` портирован частично — только ``feature_packs``/
      ``pack.mcmeta`` (поиск world-паков ``file/``, zip и функции команд —
      другие PART);
    * bold-стиль заголовка в DetailsScreen не портирован (шрифт QuadRix без
      ``Text``-стилей в bitmap-рендере);
    * экран Data Packs (id 31), который вызывает ``offer_data_packs``,
      — следующий PART; здесь он объявлен и покрыт тестами.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.render.flat import ui_hovered
from quadrix.render.menu import (
    PACK_ROOT,
    Screen,
    ScreenStack,
    draw_menu_background,
    draw_text,
)
from quadrix.render.ui import Batch, Button, Font, rgba

__all__ = [
    # experiments.rs
    "HEADER",
    "FOOTER",
    "GRID",
    "BUTTON",
    "INFO",
    "WARNING",
    "MAX_INFO_ROWS",
    "ROW_SPACING",
    "FLAG_HEIGHT",
    "Flag",
    "Outcome",
    "feature_packs",
    "repository_flags",
    "content_top",
    "grid_left",
    "footer",
    "warning_lines",
    "grid_top",
    "switch_rect",
    "experiments_click",
    "ExperimentsScreen",
    # confirm_experiments.rs
    "COLUMN_SPACING",
    "BUTTON_CONFIRM",
    "DETAILS",
    "WARNING_CONFIRM",
    "ROW",
    "ConfirmClick",
    "Entry",
    "confirm_entries",
    "message_lines",
    "block_top",
    "details_rect",
    "footer_pair",
    "footer_single",
    "confirm_click",
    "ConfirmExperimentsScreen",
]


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] experiments: " + message)


# ---------------------------------------------------------------------------
# datapack.rs::feature_packs (PART — только feature-паки)
# ---------------------------------------------------------------------------

@dataclass
class _DataPack:
    """Пак на диске (``datapack.rs::DataPack``) — только чтение mcmeta."""

    id: str
    path: Path

    def read(self, rel: str) -> Optional[bytes]:
        try:
            return (self.path / rel).read_bytes()
        except OSError:
            return None

    def _mcmeta(self) -> Any:
        raw = self.read("pack.mcmeta")
        if raw is None:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def features(self) -> list[str]:
        """``DataPack::features``: ``features.enabled`` из ``pack.mcmeta``."""
        value = self._mcmeta()
        if not isinstance(value, dict):
            return []
        arr = value.get("features", {})
        if not isinstance(arr, dict):
            return []
        enabled = arr.get("enabled")
        if not isinstance(enabled, list):
            return []
        return [f for f in enabled if isinstance(f, str)]


def feature_packs(resources: Path | str) -> list[_DataPack]:
    """``datapack.rs::feature_packs``: папки с ``pack.mcmeta``, id = имя.

    Идёт по ``<resources>/data/minecraft/datapacks``; пропускает пак без
    ``pack.mcmeta``; сортирует по id.
    """
    base = Path(resources) / "data" / "minecraft" / "datapacks"
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    packs: list[_DataPack] = []
    for entry in entries:
        if (entry / "pack.mcmeta").exists():
            packs.append(_DataPack(id=entry.name, path=entry))
    packs.sort(key=lambda pack: pack.id)
    return packs


# ---------------------------------------------------------------------------
# experiments.rs L16-31: константы (не менять)
# ---------------------------------------------------------------------------

#: ``HeaderAndFooterLayout`` header/footer.
HEADER = 33.0
FOOTER = 33.0
#: ``SwitchGrid.builder(299)``, ``DEFAULT_SWITCH_BUTTON_WIDTH`` и максимум
#: информации (``width - paddingLeft - buttonWidth``).
GRID = 299.0
BUTTON = 44.0
INFO = 266.0 - 11.0
#: ``ExperimentsScreen.MAIN_CONTENT_WIDTH``: максимум предупреждения.
WARNING = 310.0
#: ``withInfoUnderneath(2, true)``.
MAX_INFO_ROWS = 2
#: ``withRowSpacing(4)``.
ROW_SPACING = 4.0
#: Один switch и его две строки информации, с ``rowSpacing``.
FLAG_HEIGHT = 20.0 + ROW_SPACING + (9.0 * MAX_INFO_ROWS)

#: named_color("red") / named_color("gray") (text.rs).
RED = 0xFF5555
GRAY = 0xAAAAAA
WHITE = rgba(255, 255, 255, 255)


class Outcome(Enum):
    """``experiments.rs::Outcome``."""

    DONE = "done"
    CANCEL = "cancel"


@dataclass
class Flag:
    """Один feature-пак: ``SwitchGrid.addSwitch(...).withInfo(description)``."""

    id: str
    title: str
    description: str
    enabled: bool = False


def repository_flags(resources: Path | str, enabled: list[str]) -> list[Flag]:
    """``experiments.rs::repository_flags``: все feature-паки, включённые в ``enabled``."""
    flags: list[Flag] = []
    for pack in feature_packs(resources):
        ident = pack.id
        name_key = f"dataPack.{ident}.name"
        title = lang.get(name_key) if lang.has(name_key) else ident
        flags.append(
            Flag(
                id=ident,
                title=title,
                description=lang.translate(f"dataPack.{ident}.description"),
                enabled=ident in enabled,
            )
        )
    return flags


# ---------------------------------------------------------------------------
# experiments.rs L70-198: геометрия
# ---------------------------------------------------------------------------

def content_top() -> float:
    """``HeaderAndFooterLayout.arrangeElements``: содержимое на header + 30."""
    return HEADER + 30.0


def grid_left(w: float) -> float:
    """``ExperimentsScreen.grid_left``."""
    return math.trunc((w - GRID) / 2.0)


def footer(w: float, h: float) -> list[tuple[float, float]]:
    """``header_and_footer``: две кнопки 150 врозь в footer 33."""
    x = math.trunc((w - 308.0) / 2.0)
    y = h - FOOTER + 6.0
    return [(x, y), (x + 158.0, y)]


def _warning_text() -> str:
    return lang.translate("selectWorld.experiments.info")


def warning_lines(font: Font) -> list[str]:
    """``MultiLineTextWidget.setMaxWidth(310)``: строки предупреждения."""
    return [line for line, _ in font.split_lines(_warning_text(), WARNING)]


def grid_top(font: Font) -> float:
    """``SwitchGrid`` начинается под предупреждением и его паддингом 15."""
    return content_top() + 9.0 * len(warning_lines(font)) + 15.0


def switch_rect(font: Font, w: float, i: int) -> tuple[float, float]:
    """i-й switch (``alignHorizontallyRight`` в колонке 44)."""
    top = grid_top(font) + i * FLAG_HEIGHT
    return (grid_left(w) + GRID - BUTTON, top)


def experiments_click(
    flags: list[Flag], font: Font, cursor: tuple[float, float], size: tuple[float, float]
) -> Optional[tuple[str, Any]]:
    """``ExperimentsScreen::click``: ``("switch", i)`` | ``("outcome", Outcome)`` | None."""
    w, h = size
    for i in range(len(flags)):
        bx, by = switch_rect(font, w, i)
        if ui_hovered(cursor, bx, by, BUTTON, 20.0):
            return ("switch", i)
    (dx, dy), (cx, cy) = footer(w, h)
    if ui_hovered(cursor, dx, dy, 150.0, 20.0):
        return ("outcome", Outcome.DONE)
    if ui_hovered(cursor, cx, cy, 150.0, 20.0):
        return ("outcome", Outcome.CANCEL)
    return None


# ---------------------------------------------------------------------------
# экран экспериментов (title.rs::CreateWorldScreen.openExperimentsScreen)
# ---------------------------------------------------------------------------

class ExperimentsScreen(Screen):
    """CreateWorldScreen's Experiments screen как :class:`Screen`.

    ``on_done`` получает итоговый список :class:`Flag` (для слияния в
    ``options.data_packs``); ``on_cancel`` — при Cancel/Escape.
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        resources: Path | str = PACK_ROOT,
        enabled: Optional[list[str]] = None,
        flags: Optional[list[Flag]] = None,
        stack: Optional[ScreenStack] = None,
        on_done: Optional[Callable[[list[Flag]], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        in_world: bool = False,
    ) -> None:
        super().__init__(width, height)
        self.stack = stack
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.in_world = bool(in_world)
        self.flags = (
            list(flags)
            if flags is not None
            else repository_flags(Path(resources), list(enabled or []))
        )
        self.cursor: tuple[float, float] = (-1.0, -1.0)
        self.font: Optional[Font] = None

    # -- шрифт для геометрии (высота предупреждения зависит от переноса) ---

    def _font(self) -> Font:
        if self.font is None:
            self.font = Font.load()
        return self.font

    # -- действия --------------------------------------------------------

    def selected_ids(self) -> list[str]:
        """Включённые feature-паки (в порядке экрана)."""
        return [flag.id for flag in self.flags if flag.enabled]

    def done(self) -> None:
        """Done: отдать switches в selection (``ExperimentsScreen.onDone``)."""
        if self.stack is not None:
            self.stack.pop()
        if self.on_done is not None:
            self.on_done(self.flags)

    def cancel(self) -> None:
        """Cancel/Escape: switches отбрасываются."""
        if self.stack is not None:
            self.stack.pop()
        if self.on_cancel is not None:
            self.on_cancel()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        hit = experiments_click(
            self.flags, self._font(), self.cursor,
            (math.ceil(self.width), math.ceil(self.height)),
        )
        if hit is None:
            return False
        kind, value = hit
        if kind == "switch":
            self.flags[value].enabled = not self.flags[value].enabled
        elif value is Outcome.DONE:
            self.done()
        else:
            self.cancel()
        return True

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key in ("escape", "key.keyboard.escape"):
            self.cancel()
            return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        return True

    def handle_scroll(self, dy: float) -> bool:
        return False

    # -- рендер ----------------------------------------------------------

    def draw(
        self,
        batch: Batch,
        font: Optional[Font],
        cursor: tuple[float, float],
        atlas: Any = None,
    ) -> None:
        """``ExperimentsScreen::draw``."""
        if font is None:
            return
        self.font = font
        if atlas is None:
            atlas = getattr(batch, "atlas", None)
        w, h = math.ceil(self.width), math.ceil(self.height)
        draw_menu_background(batch, font, float(w), float(h))
        title = lang.translate("selectWorld.experiments")
        tw = font.width(title)
        draw_text(batch, font, title, math.trunc((w - tw) / 2.0), 15.0, WHITE)

        y = content_top()
        for line in warning_lines(font):
            draw_text(batch, font, line, math.trunc((w - WARNING) / 2.0), y, RED)
            y += 9.0

        left = grid_left(w)
        for i, flag in enumerate(self.flags):
            bx, by = switch_rect(font, w, i)
            draw_text(batch, font, flag.title, float(left), by + 5.0, WHITE)
            value = lang.translate("options.on" if flag.enabled else "options.off")
            Button(
                x=bx, y=by, w=BUTTON, h=20.0, label=value, active=True,
                hovered=ui_hovered(cursor, bx, by, BUTTON, 20.0),
            ).render(batch, font)
            info_y = by + 20.0
            for line, _ in font.split_lines(flag.description, INFO):
                draw_text(batch, font, line, float(left), info_y, GRAY)
                info_y += 9.0

        fx, fy = footer(w, h)[0]
        cx, cy = footer(w, h)[1]
        for key, x, y in (("gui.done", fx, fy), ("gui.cancel", cx, cy)):
            Button(
                x=x, y=y, w=150.0, h=20.0, label=lang.translate(key), active=True,
                hovered=ui_hovered(cursor, x, y, 150.0, 20.0),
            ).render(batch, font)

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        self.draw(batch, font, self.cursor)


# ---------------------------------------------------------------------------
# confirm_experiments.rs L15-24: константы (не менять)
# ---------------------------------------------------------------------------

COLUMN_SPACING = 10.0
#: Ширина футер-кнопок (``Button.defaults``; в confirm_experiments.rs это
#: ``BUTTON`` 150 — здесь имя с суффиксом, чтобы не путать с switch 44).
BUTTON_CONFIRM = 150.0
DETAILS = 100.0
WARNING_CONFIRM = 310.0
#: Один ряд кнопок плюс межрядный интервал сетки 20, дважды.
ROW = 40.0

#: Сообщение по умолчанию (``selectWorld.experimental.message``).
MESSAGE_FALLBACK = (
    "Be careful!\nThis configuration requires features that are still under "
    "development. Your world might crash, break, or not work with future "
    "updates."
)


class ConfirmClick(Enum):
    """``confirm_experiments.rs::Click``."""

    DETAILS = "details"
    PROCEED = "proceed"
    BACK = "back"


@dataclass
class Entry:
    """Один включённый feature-пак, как его показывает ``DetailsScreen``."""

    title: str
    flags: str


def confirm_entries(resources: Path | str, selected: list[str]) -> list[Entry]:
    """``ConfirmExperimentsScreen::new``: выбранные паки с их флагами."""
    entries: list[Entry] = []
    for pack in feature_packs(resources):
        if pack.id not in selected:
            continue
        feats = pack.features()
        if not feats:
            continue
        name_key = f"dataPack.{pack.id}.name"
        title = lang.get(name_key) if lang.has(name_key) else pack.id
        flags = ", ".join(f.removeprefix("minecraft:") for f in feats)
        entries.append(Entry(title=title, flags=flags))
    return entries


def message_lines(font: Font) -> list[str]:
    """``message_lines``: сообщение на 310, переносы ``\\n`` сохранены."""
    text = lang.get_or("selectWorld.experimental.message", MESSAGE_FALLBACK)
    out: list[str] = []
    for line in text.split("\n"):
        out.extend(l for l, _ in font.split_lines(line, WARNING_CONFIRM))
    return out


def block_top(message: int, h: float) -> float:
    """``block_top``: весь блок центрируется вертикально."""
    rows = 9.0 + message * 9.0 + ROW + ROW
    return max((h - rows) / 2.0, 0.0)


def details_rect(message: int, w: float, h: float) -> tuple[float, float]:
    """``details_rect``: кнопка Details (по центру, под сообщением)."""
    return (math.trunc((w - DETAILS) / 2.0), block_top(message, h) + 9.0 + ROW)


def footer_pair(w: float, h: float) -> list[tuple[float, float]]:
    """``footer_pair``: две кнопки 150 врозь (``COLUMN_SPACING``), по центру."""
    x = math.trunc((w - (BUTTON_CONFIRM * 2.0 + COLUMN_SPACING)) / 2.0)
    y = h - 45.0
    return [(x, y), (x + BUTTON_CONFIRM + COLUMN_SPACING, y)]


def footer_single(w: float, h: float) -> list[tuple[float, float]]:
    """``footer_single``: одна центрированная кнопка (``DetailsScreen`` Back)."""
    return [(math.trunc((w - BUTTON_CONFIRM) / 2.0), h - 45.0)]


def confirm_click(
    entries: list[Entry],
    details: bool,
    font: Font,
    cursor: tuple[float, float],
    size: tuple[float, float],
) -> Optional[ConfirmClick]:
    """``ConfirmExperimentsScreen::click``."""
    w, h = size
    if details:
        (bx, by) = footer_single(w, h)[0]
        return ConfirmClick.BACK if ui_hovered(cursor, bx, by, BUTTON_CONFIRM, 20.0) else None
    message = len(message_lines(font))
    dx, dy = details_rect(message, w, h)
    if ui_hovered(cursor, dx, dy, DETAILS, 20.0):
        return ConfirmClick.DETAILS
    px, py = footer_pair(w, h)[0]
    bx, by = footer_pair(w, h)[1]
    if ui_hovered(cursor, px, py, BUTTON_CONFIRM, 20.0):
        return ConfirmClick.PROCEED
    if ui_hovered(cursor, bx, by, BUTTON_CONFIRM, 20.0):
        return ConfirmClick.BACK
    return None


# ---------------------------------------------------------------------------
# экран подтверждения (title.rs::offer_data_packs)
# ---------------------------------------------------------------------------

class ConfirmExperimentsScreen(Screen):
    """ConfirmExperimentalFeaturesScreen как :class:`Screen`.

    ``on_proceed`` получает ``pending`` (применить выбор), ``on_back`` —
    ``onAbort`` (вернуться к Data Packs); без колбэков экран работает через
    ``stack``.
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        resources: Path | str = PACK_ROOT,
        selected: Optional[list[str]] = None,
        entries: Optional[list[Entry]] = None,
        stack: Optional[ScreenStack] = None,
        on_proceed: Optional[Callable[[list[str]], None]] = None,
        on_back: Optional[Callable[[], None]] = None,
        in_world: bool = False,
    ) -> None:
        super().__init__(width, height)
        self.stack = stack
        self.on_proceed = on_proceed
        self.on_back = on_back
        self.in_world = bool(in_world)
        self.entries = (
            list(entries)
            if entries is not None
            else confirm_entries(Path(resources), list(selected or []))
        )
        self.pending: list[str] = list(selected or [])
        self.details = False
        self.cursor: tuple[float, float] = (-1.0, -1.0)
        self.font: Optional[Font] = None

    def _font(self) -> Font:
        if self.font is None:
            self.font = Font.load()
        return self.font

    # -- действия --------------------------------------------------------

    def proceed(self) -> None:
        """Proceed: применить ``pending``."""
        if self.stack is not None:
            self.stack.pop()
        if self.on_proceed is not None:
            self.on_proceed(self.pending)

    def back(self) -> None:
        """Back: из Details — назад к предупреждению, иначе — отказ."""
        if self.details:
            self.details = False
            return
        if self.stack is not None:
            self.stack.pop()
        if self.on_back is not None:
            self.on_back()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        hit = confirm_click(
            self.entries, self.details, self._font(), self.cursor,
            (math.ceil(self.width), math.ceil(self.height)),
        )
        if hit is None:
            return False
        if hit is ConfirmClick.DETAILS:
            self.details = True
        elif hit is ConfirmClick.PROCEED:
            self.proceed()
        else:
            self.back()
        return True

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key in ("escape", "key.keyboard.escape"):
            self.back()
            return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        return True

    def handle_scroll(self, dy: float) -> bool:
        return False

    # -- рендер ----------------------------------------------------------

    def draw(
        self,
        batch: Batch,
        font: Optional[Font],
        cursor: tuple[float, float],
        atlas: Any = None,
    ) -> None:
        """``ConfirmExperimentsScreen::draw``."""
        if font is None:
            return
        self.font = font
        if atlas is None:
            atlas = getattr(batch, "atlas", None)
        w, h = math.ceil(self.width), math.ceil(self.height)
        draw_menu_background(batch, font, float(w), float(h))

        if self.details:
            title = lang.translate("selectWorld.experimental.details.title")
            tw = font.width(title)
            draw_text(batch, font, title, math.trunc((w - tw) / 2.0), 15.0, WHITE)
            y = 63.0 + 30.0
            for entry in self.entries:
                x = math.trunc(w / 2.0 - 155.0)
                draw_text(batch, font, entry.title, float(x), y, WHITE)
                y += 12.0
                line = lang.translate("selectWorld.experimental.details.entry") + entry.flags
                for sub, _ in font.split_lines(line, WARNING_CONFIRM):
                    draw_text(batch, font, sub, float(x), y, GRAY)
                    y += 9.0
                y += 10.0
            (bx, by) = footer_single(w, h)[0]
            Button(
                x=bx, y=by, w=BUTTON_CONFIRM, h=20.0,
                label=lang.translate("gui.back"), active=True,
                hovered=ui_hovered(cursor, bx, by, BUTTON_CONFIRM, 20.0),
            ).render(batch, font)
            return

        message = message_lines(font)
        top = block_top(len(message), h)
        title = lang.translate("selectWorld.experimental.title")
        tw = font.width(title)
        draw_text(batch, font, title, math.trunc((w - tw) / 2.0), top, WHITE)
        dx, dy = details_rect(len(message), w, h)
        y = top + 9.0
        for line in message:
            draw_text(batch, font, line, math.trunc((w - WARNING_CONFIRM) / 2.0), y, WHITE)
            y += 9.0
        Button(
            x=dx, y=dy, w=DETAILS, h=20.0,
            label=lang.translate("selectWorld.experimental.details"), active=True,
            hovered=ui_hovered(cursor, dx, dy, DETAILS, 20.0),
        ).render(batch, font)
        px, py = footer_pair(w, h)[0]
        bx, by = footer_pair(w, h)[1]
        for key, x, yy in (("gui.proceed", px, py), ("gui.back", bx, by)):
            Button(
                x=x, y=yy, w=BUTTON_CONFIRM, h=20.0, label=lang.translate(key),
                active=True, hovered=ui_hovered(cursor, x, yy, BUTTON_CONFIRM, 20.0),
            ).render(batch, font)

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        self.draw(batch, font, self.cursor)
