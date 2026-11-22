"""Create World — экран создания одиночного мира (WC1: модель и геометрия).

Порт ``horizon/crates/horizon-client/src/title/create_world.rs`` (WC1:
``WorldOptions``, геометрия табов/сетки/полей, cycл-кнопки и футер). Это
первый PART экрана; отрисовка (WC2) и ввод (WC3) — отдельные PART.

Зависимости пресета мира: :mod:`quadrix.save.world_preset` (WC0).

Сверка констант с Rust (не менять):
    * ``TAB_BAR = 24.0``               — MenuTabBar.HEIGHT.
    * ``FOOTER = 33.0``                — HeaderAndFooterLayout.
    * ``TABS``                         — три заголовка вкладок.
    * ``DIFFICULTIES``                 — порядок cycle-кнопки сложности.
    * Сетки вкладок 210x117 / 310x117 / 210x76.
    * Футер: две кнопки по 150 шириной, 8 друг от друга, в 33 пикселях.

FALLBACK: ``flat_settings`` (``title/flat.rs::FlatSettings``) портирован в
PART WC4 (:mod:`quadrix.render.flat`); здесь тип ``Optional[Any]``, чтобы не
тянуть import. ``rules`` — :class:`GameRules`
(``quadrix.core.gamerules``, уже портирован). Наррация
(``widgets::Narratable``) — PART WC2. ``world_gen`` и ``of_world``
(``save::WorldGen`` / ``Level``) — PART сохранения мира.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from quadrix.core.gamerules import GameRules
from quadrix.core.text import Text
from quadrix.save.world_preset import WorldPreset

# ---------------------------------------------------------------------------
# константы (точно как в Rust; не менять)
# ---------------------------------------------------------------------------

# create_world.rs L11: MenuTabBar.HEIGHT — заголовок над областью вкладок.
TAB_BAR = 24.0
# create_world.rs L13: HeaderAndFooterLayout — высота футера.
FOOTER = 33.0
# create_world.rs L14: ключи трёх вкладок.
TABS: tuple[str, str, str] = (
    "createWorld.tab.game.title",
    "createWorld.tab.world.title",
    "createWorld.tab.more.title",
)
# create_world.rs L20: id сложностей в порядке cycle-кнопки.
DIFFICULTIES: tuple[str, str, str, str] = ("peaceful", "easy", "normal", "hard")


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] create_world: " + message)


# ---------------------------------------------------------------------------
# Button (title.rs::Button без иконки-действия: только то, что рисует WC2)
# ---------------------------------------------------------------------------

@dataclass
class Button:
    """Кнопка Create World (``title.rs::Button``).

    ``action`` — задача для контроллера (``widgets::Action``); здесь только
    поле (``None`` для обычных кнопок, ``"Cancel"`` для футера).
    """

    x: float
    y: float
    w: float
    label: str
    enabled: bool
    id: int
    icon: Optional[tuple[str, float]] = None
    trailing: Optional[tuple[str, float]] = None
    action: Optional[str] = None

    def does(self, action: str) -> "Button":
        self.action = action
        return self

    def contains(self, mx: float, my: float) -> bool:
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + 20.0

    def handle_click(self, mx: float, my: float) -> bool:
        """Порт ``Button.handleClick``: клик принят, если внутри и активна."""
        return self.enabled and self.contains(mx, my)


# ---------------------------------------------------------------------------
# геометрия (create_world.rs L244-335)
# ---------------------------------------------------------------------------

def round_toward(value: float, step: float) -> float:
    """``Mth.roundToward``: вверх до кратного ``step``."""
    return math.ceil(value / step) * step


def tabs(w: float) -> tuple[float, float]:
    """``MenuTabBar.arrangeElements``: x первой вкладки и ширина каждой."""
    width = min(w, 400.0) - 28.0
    return (
        round_toward(math.trunc((w - width) / 2.0), 2.0),
        round_toward(math.trunc(width / len(TABS)), 2.0),
    )


def tab_at(w: float, pos: tuple[float, float]) -> Optional[int]:
    """Вкладка под указателем (или ``None``)."""
    x, y = pos
    x0, width = tabs(w)
    if not (0.0 <= y < TAB_BAR and x >= x0):
        return None
    i = int((x - x0) / width)
    return i if i < len(TABS) else None


def tab_count() -> int:
    """``TabNavigationBar.tabs.size()``: число вкладок."""
    return len(TABS)


_DIGITS = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}
_NUMPAD = {f"numpad{d}": d for d in range(10)}


def numeric_key(key: str) -> Optional[int]:
    """``InputConstants.Key.getNumericKeyValue``: цифра клавиши, иначе None."""
    if key in _DIGITS:
        return _DIGITS[key]
    if key in _NUMPAD:
        return _NUMPAD[key]
    return None


def next_tab_index(tab: int, key: str, shift: bool) -> Optional[int]:
    """``TabNavigationBar.getNextTabIndex``: вкладка по Ctrl+цифра или Ctrl+Tab.

    Цифра — ``floorMod(key - 1, 10)`` (Ctrl+1 — первая, Ctrl+0 — десятая);
    Tab шагает на одну вкладку вперёд/назад (с ``shift``), по кругу. ``None``,
    если клавиша не цифра и не Tab.
    """
    digit = numeric_key(key)
    if digit is not None:
        return (digit - 1) % 10
    if key != "Tab":
        return None
    nxt = tab + (-1 if shift else 1)
    return nxt % len(TABS)


def grid(w: float, h: float, tab: int) -> tuple[float, float]:
    """``GridLayoutTab.doLayout``: сетка вкладки в области между баром и футером."""
    if tab == 0:
        gw, gh = 210.0, 117.0
    elif tab == 1:
        gw, gh = 310.0, 117.0
    else:
        gw, gh = 210.0, 76.0
    area = h - TAB_BAR - FOOTER
    return (
        math.trunc((w - gw) * 0.5),
        TAB_BAR + math.trunc((area - gh) * 0.166_666_67),
    )


def field_rect(w: float, h: float, tab: int) -> Optional[tuple[int, list[float]]]:
    """Текстовое поле вкладки: 0 — имя (Game), 1 — сид (World)."""
    gx, gy = grid(w, h, tab)
    if tab == 0:
        return (0, [gx + 1.0, gy + 13.0, 208.0, 20.0])
    if tab == 1:
        return (1, [gx, gy + 41.0, 308.0, 20.0])
    return None


def field_at(w: float, h: float, tab: int, pos: tuple[float, float]) -> Optional[int]:
    """Поле под указателем: 0 — имя, 1 — сид."""
    rect = field_rect(w, h, tab)
    if rect is None:
        return None
    fid, (fx, fy, fw, fh) = rect
    x, y = pos
    return fid if (fx <= x < fx + fw and fy <= y < fy + fh) else None


# ---------------------------------------------------------------------------
# подписи (create_world.rs L337-357)
# ---------------------------------------------------------------------------

def tr(key: str) -> str:
    """``Text::translate(key, &[]).plain()``."""
    return Text.translate(key, []).plain()


def labelled(key: str, value: str) -> str:
    """``CycleButton``: ``options.generic_value`` → "Label: Value"."""
    return Text.translate(
        "options.generic_value",
        [Text.translate(key, []), Text.literal(value)],
    ).plain()


def on_off(on: bool) -> str:
    """ON / OFF (``options.on`` / ``options.off``)."""
    return tr("options.on" if on else "options.off")


def game_mode(creative: bool, hardcore: bool) -> str:
    """Ключ режима игры: Creative, Hardcore или Survival."""
    if creative:
        return "selectWorld.gameMode.creative"
    if hardcore:
        return "selectWorld.gameMode.hardcore"
    return "selectWorld.gameMode.survival"


# ---------------------------------------------------------------------------
# WorldOptions (create_world.rs L22-231)
# ---------------------------------------------------------------------------

@dataclass
class WorldOptions:
    """``WorldCreationUiState`` за пределами имени и сида (create_world.rs)."""

    #: Открытая вкладка: Game, World или More.
    tab: int = 0
    #: Survival заперт на Hard, одна жизнь (``SelectedGameMode.HARDCORE``).
    hardcore: bool = False
    #: Индекс в :data:`DIFFICULTIES`.
    difficulty_level: int = 2
    #: Allow Cheats как переключено; ``None`` — следует режиму игры.
    commands: Optional[bool] = None
    #: Пресет мира, с которым мир создаётся.
    world_type: WorldPreset = WorldPreset.NORMAL
    #: Биом пресета одного биома; ``minecraft:plains`` до иного выбора.
    single_biome: str = "minecraft:plains"
    #: Слои/биом CreateFlatWorldScreen; None для не-flat пресетов.
    #: FALLBACK: FlatSettings — PART WC4.
    flat_settings: Optional[Any] = None
    structures: bool = True
    bonus_chest: bool = False
    #: ``getGameRules``: значения Game Rules, сохраняемые с миром.
    rules: GameRules = field(default_factory=GameRules)
    #: Выбор Data Packs, от низшего приоритета к высшему.
    data_packs: list[str] = field(default_factory=lambda: ["vanilla"])
    #: Папка пакетов нового мира (временная ``mcworld-`` у vanilla).
    pack_dir: Optional[Path] = None

    # --- create_world.rs::WorldOptions::difficulty ---
    def difficulty(self) -> int:
        """``getDifficulty``: Hardcore всегда Hard."""
        return 3 if self.hardcore else self.difficulty_level

    # --- create_world.rs::WorldOptions::commands ---
    def allow_commands(self, creative: bool) -> bool:
        """``isAllowCommands``: никогда в Hardcore, иначе Creative до переключения."""
        if self.hardcore:
            return False
        return self.commands if self.commands is not None else creative

    # --- create_world.rs::WorldOptions::bonus_chest ---
    def bonus_chest_enabled(self) -> bool:
        """``isBonusChest``: никогда в Hardcore."""
        return (not self.hardcore) and self.bonus_chest

    # --- create_world.rs::WorldOptions::single_biome ---
    def single_biome_of(self) -> Optional[str]:
        """Биом пресета одного биома; None для другого пресета."""
        if self.world_type == WorldPreset.SINGLE_BIOME_SURFACE:
            return self.single_biome
        return None

    # --- create_world.rs::WorldOptions::press / cycle ---
    def press(self, id: int, creative: bool) -> bool:
        """Нажатие на cycle-кнопке/переключателе (шаг 1)."""
        return self.cycle(id, creative, 1)

    def cycle(self, id: int, creative: bool, step: int) -> bool:
        """Шаг cycle-кнопки/переключателя (колесо или клавиатура).

        Возвращает обновлённый ``creative`` (в Rust ``&mut bool``).
        """
        if id == 20:
            # Survival, Hardcore, Creative.
            modes = [(False, False), (False, True), (True, False)]
            cur = (creative, self.hardcore)
            idx = modes.index(cur) if cur in modes else 0
            next_idx = (idx + step) % len(modes)
            creative, self.hardcore = modes[next_idx]
        elif id == 23:
            self.difficulty_level = (self.difficulty_level + step) % len(DIFFICULTIES)
        elif id == 24:
            self.commands = not self.allow_commands(creative)
        elif id == 25:
            self.world_type = self.world_type.next() if step >= 0 else self.world_type.prev()
            if self.world_type == WorldPreset.FLAT:
                # setWorldType запускает генератор от flat-пресета.
                self.flat_settings = _flat_default()
            # ...и его измерения заменяют предыдущие, так что выбранный
            # fixed biome начинается заново с биома пресета одного биома.
            self.single_biome = "minecraft:plains"
        elif id == 27:
            self.structures = not self.structures
        elif id == 28:
            self.bonus_chest = not self.bonus_chest
        return creative


def _flat_default() -> Any:
    """``FlatSettings::default()`` — overworld-набор (PART WC4)."""
    from quadrix.render.flat import FlatSettings

    return FlatSettings.default()


# ---------------------------------------------------------------------------
# кнопки (create_world.rs L360-474)
# ---------------------------------------------------------------------------

def _b(
    x: float,
    y: float,
    w: float,
    label: str,
    enabled: bool,
    id: int,
) -> Button:
    return Button(x=x, y=y, w=w, label=label, enabled=enabled, id=id)


def buttons(w: float, h: float, creative: bool, o: WorldOptions) -> list[Button]:
    """Кнопки открытой вкладки и футера (``create_world.rs::buttons``)."""
    gx, gy = grid(w, h, o.tab)
    if o.tab == 0:
        out = [
            _b(
                gx, gy + 41.0, 210.0,
                labelled("selectWorld.gameMode", tr(game_mode(creative, o.hardcore))),
                True, 20,
            ),
            _b(
                gx, gy + 69.0, 210.0,
                labelled("options.difficulty", tr(f"options.difficulty.{DIFFICULTIES[o.difficulty()]}")),
                not o.hardcore, 23,
            ),
            _b(
                gx, gy + 97.0, 210.0,
                labelled("selectWorld.allowCommands", on_off(o.allow_commands(creative))),
                not o.hardcore, 24,
            ),
        ]
    elif o.tab == 1:
        out = [
            _b(
                gx, gy, 150.0,
                labelled("selectWorld.mapType", tr(o.world_type.label)),
                True, 25,
            ),
            # PresetEditor.EDITORS: flat — CreateFlatWorldScreen, single-biome —
            # CreateBuffetWorldScreen; прочие пресеты без редактора.
            _b(
                gx + 160.0, gy, 150.0,
                tr("selectWorld.customizeType"),
                o.world_type in (WorldPreset.FLAT, WorldPreset.SINGLE_BIOME_SURFACE),
                26,
            ),
            # SwitchGrid: кнопки значения 44 шириной справа от сетки.
            _b(gx + 266.0, gy + 73.0, 44.0, on_off(o.structures), True, 27),
            _b(
                gx + 266.0, gy + 97.0, 44.0,
                on_off(o.bonus_chest_enabled()),
                not o.hardcore, 28,
            ),
        ]
    else:
        out = [
            _b(gx, gy + 28.0 * i, 210.0, tr(key), True, 29 + i)
            for i, key in enumerate((
                "selectWorld.gameRules",
                "selectWorld.experiments",
                "selectWorld.dataPacks",
            ))
        ]
    # Футер: две кнопки 150 шириной, 8 друг от друга, по центру 33 пикселей.
    x = math.trunc((w - 308.0) * 0.5)
    out.append(_b(x, h - 27.0, 150.0, _lang_get_or("selectWorld.create", "Create New World"), True, 21))
    cancel = _b(x + 158.0, h - 27.0, 150.0, _lang_get_or("gui.cancel", "Cancel"), True, 22)
    out.append(cancel.does("Cancel"))
    return out


def _lang_get_or(key: str, fallback: str) -> str:
    """``lang::get_or``: перевод keys, иначе fallback."""
    from quadrix.core import lang

    return lang.get_or(key, fallback)
