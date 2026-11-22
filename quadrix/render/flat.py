"""CreateFlatWorldScreen и PresetFlatWorldScreen (WC4).

Порт ``horizon/crates/horizon-client/src/title/flat.rs``:
Superflat-список слоёв, выбор пресета, настройки, которые экран возвращает
Create New World, и их сериализация в ``level.dat``.

Порт сохраняет структуру Rust:
    * :class:`FlatLayer` / :class:`FlatSettings` — слои, биом, флаги
      (``from_tag``/``to_tag``/``to_share``/``parse``);
    * :class:`Page` (Layers/Presets), :class:`Preset`, :class:`State`;
    * :func:`load` — ``data/minecraft/tags/worldgen/flat_level_generator_preset/
      visible.json`` + сами пресеты + ``registries.json``/``worldgen/biomes.json``;
    * геометрия :func:`list_area` / :func:`buttons` / :func:`layer_row` /
      :func:`preset_row` / :func:`click` / :func:`focus_row` / :func:`wheel` /
      :func:`drag` / :func:`release` и :class:`Scroll` (``ui.rs::Scroll``);
    * :func:`draw` — отрисовка через GUI-атлас (WC10 добьёт мелочи).

FALLBACK (см. ``PORTING_STATE.yaml``):
    * ``FlatSettings::from_world`` требует ``save::world_gen_settings``
      (чтение ``level.dat``, PART сохранения мира) — возвращает ``None``;
    * иконки слоёв (``ItemRenderer`` — 3D-модели предметов) не портированы:
      :func:`layer_icon` ищет спрайт в атласе и иначе рисуется слот-заглушка;
    * ``widgets::Narratable``/``row_target`` (наррация и фокус контроллера)
      не портированы — функции списка работают без регистрации целей.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.render.create_world import Button as _CWButton
from quadrix.render.menu import (
    PACK_ROOT,
    Screen,
    ScreenStack,
    draw_menu_background,
    draw_text,
    solid,
)
from quadrix.render.ui import Batch, Button, Font, rgba
from quadrix.world.nbt import Tag, TagType

__all__ = [
    "Y_SIZE",
    "ROW_WIDTH",
    "HEADER",
    "LAYER_ROW",
    "PRESET_ROW",
    "FlatLayer",
    "FlatSettings",
    "Preset",
    "Page",
    "State",
    "Scroll",
    "namespaced",
    "preset_settings",
    "load",
    "list_area",
    "buttons",
    "layer_row",
    "preset_row",
    "click",
    "focus_row",
    "share_field",
    "wheel",
    "drag",
    "release",
    "selection_after_removal",
    "layer_item",
    "layer_icon",
    "item_name",
    "preset_name",
    "pretty",
    "draw",
    "button_ui",
    "draw_buttons",
    "FlatWorldScreen",
    # Общие виджеты списка (``ui.rs``/``title.rs``): ими пользуется и buffet.py.
    "centered",
    "list_background",
    "separators",
    "scrollbar",
    "edit_box",
    "ui_hovered",
]


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] flat: " + message)


# flat.rs L17-25: константы экрана (не менять).
#: ``DimensionType.Y_SIZE``: максимум блоков плоского генератора.
Y_SIZE = 4064
#: ``ObjectSelectionList.getRowWidth``.
ROW_WIDTH = 220.0
#: Заголовочная строка над слоями.
HEADER = 14.0
#: Строка слоя/пресета.
LAYER_ROW = 20.0
PRESET_ROW = 24.0


# ---------------------------------------------------------------------------
# FlatLayer / FlatSettings (flat.rs L27-225)
# ---------------------------------------------------------------------------

@dataclass
class FlatLayer:
    """Слой Superflat (``flat.rs::FlatLayer``)."""

    #: id блока, например ``minecraft:dirt``.
    block: str
    #: Высота слоя в блоках (0..=4064).
    height: int


def _default_layers() -> list[FlatLayer]:
    """``FlatSettings::default``: слои overworld из ``flat.json``."""
    return [
        FlatLayer("minecraft:bedrock", 1),
        FlatLayer("minecraft:dirt", 2),
        FlatLayer("minecraft:grass_block", 1),
    ]


@dataclass
class FlatSettings:
    """``FlatLevelGeneratorSettings`` (``flat.rs::FlatSettings``)."""

    biome: str = "minecraft:plains"
    features: bool = False
    lakes: bool = False
    layers: list[FlatLayer] = field(default_factory=_default_layers)
    structure_overrides: list[str] = field(
        default_factory=lambda: ["minecraft:strongholds", "minecraft:villages"]
    )

    @staticmethod
    def default() -> "FlatSettings":
        """``Default``: overworld-набор из ``world_preset/flat.json``."""
        return FlatSettings()

    @staticmethod
    def from_world(directory: Path) -> Optional["FlatSettings"]:
        """Настройки flat-генератора сохранённого мира (для Re-Create).

        FALLBACK: требует ``save::world_gen_settings`` (``level.dat``, PART
        сохранения мира), поэтому всегда ``None``. См. ``PORTING_STATE.yaml``.
        """
        return None

    @staticmethod
    def from_tag(tag: Tag) -> Optional["FlatSettings"]:
        """``flat.rs::from_tag``: слои/биом/флаги из NBT-компаунда."""
        layers_tag = _compound_get(tag, "layers")
        if layers_tag is None or layers_tag.tag_type != TagType.List:
            return None
        raw = layers_tag.list_val or []
        layers: list[FlatLayer] = []
        for layer in raw:
            block = _text(_compound_get(layer, "block"))
            number = _number(_compound_get(layer, "height"))
            if block is None or number is None:
                continue
            layers.append(
                FlatLayer(block, max(0, min(Y_SIZE, int(number))))
            )
        # ``layers: []`` — корректный void-мир; список, где все записи не
        # разобрались, — нет.
        if not layers and raw:
            return None

        def flag(key: str, default: bool) -> bool:
            value = _number(_compound_get(tag, key))
            return default if value is None else value != 0

        overrides_tag = _compound_get(tag, "structure_overrides")
        if overrides_tag is not None and overrides_tag.tag_type == TagType.String:
            structure_overrides = [_text(overrides_tag) or ""]
        elif overrides_tag is not None and overrides_tag.tag_type == TagType.List:
            structure_overrides = [
                text
                for text in (_text(v) for v in (overrides_tag.list_val or []))
                if text is not None
            ]
        else:
            structure_overrides = []
        return FlatSettings(
            biome=_text(_compound_get(tag, "biome")) or "minecraft:plains",
            features=flag("features", False),
            lakes=flag("lakes", False),
            layers=layers,
            structure_overrides=structure_overrides,
        )

    def to_tag(self) -> Tag:
        """``FlatLevelGeneratorSettings.CODEC`` как NBT-компаунд."""
        return Tag(TagType.Compound, compound_val={
            "biome": Tag(TagType.String, str_val=self.biome),
            "features": Tag(TagType.Byte, byte_val=int(self.features)),
            "lakes": Tag(TagType.Byte, byte_val=int(self.lakes)),
            "layers": Tag(TagType.List, list_val=[
                Tag(TagType.Compound, compound_val={
                    "block": Tag(TagType.String, str_val=layer.block),
                    "height": Tag(TagType.Int, int_val=layer.height),
                })
                for layer in self.layers
            ]),
            "structure_overrides": Tag(TagType.List, list_val=[
                Tag(TagType.String, str_val=identifier)
                for identifier in self.structure_overrides
            ]),
        })

    def to_share(self) -> str:
        """``CreateFlatWorldScreen.save``: текст, который показывает пресет."""
        layers = ",".join(
            layer.block if layer.height == 1
            else f"{layer.height}*{layer.block}"
            for layer in self.layers
        )
        return f"{layers};{self.biome}"

    @staticmethod
    def parse(
        text: str,
        blocks: set[str],
        biomes: set[str],
        base: "FlatSettings",
    ) -> Optional["FlatSettings"]:
        """``PresetFlatWorldScreen.fromString``: ``layers;biome``.

        Сохраняет декорации ``base``; ``None`` при некорректном списке (ваниль
        тогда берёт собственные настройки пресета).
        """
        if ";" in text:
            layer_text, biome_text = text.split(";", 1)
        else:
            layer_text, biome_text = text, ""
        layers: list[FlatLayer] = []
        total = 0
        for part in layer_text.split(","):
            part = part.strip()
            if not part:
                continue
            if "*" in part:
                height_text, block_text = part.split("*", 1)
                try:
                    height = int(height_text.strip())
                except ValueError:
                    return None
                block_part = block_text.strip()
            else:
                height = 1
                block_part = part
            block = namespaced(block_part)
            if blocks and block not in blocks:
                return None
            height = max(0, min(Y_SIZE - total, height))
            if height == 0:
                continue
            total += height
            layers.append(FlatLayer(block, height))
        if not layers:
            return None
        biome = namespaced(biome_text.strip())
        if biome in ("minecraft:", ""):
            biome = "minecraft:plains"
        if biomes and biome not in biomes:
            biome = "minecraft:plains"
        return FlatSettings(
            biome=biome,
            features=base.features,
            lakes=base.lakes,
            layers=layers,
            structure_overrides=list(base.structure_overrides),
        )


def namespaced(identifier: str) -> str:
    """``Identifier.parse``: голым именам — namespace ``minecraft``."""
    if not identifier or ":" in identifier:
        return identifier
    return f"minecraft:{identifier}"


# ---------------------------------------------------------------------------
# NBT helpers (``save::text`` / ``save::number`` / ``compound get``)
# ---------------------------------------------------------------------------

def _compound_get(tag: Optional[Tag], key: str) -> Optional[Tag]:
    if tag is None or tag.tag_type != TagType.Compound or tag.compound_val is None:
        return None
    return tag.compound_val.get(key)


def _text(tag: Optional[Tag]) -> Optional[str]:
    """``save::text`` — String-тег как Python str, иначе None."""
    if tag is None or tag.tag_type != TagType.String or tag.str_val is None:
        return None
    if isinstance(tag.str_val, str):
        return tag.str_val
    to_python = getattr(tag.str_val, "to_python_str", None)
    if callable(to_python):
        return to_python()
    return str(tag.str_val)


def _number(tag: Optional[Tag]) -> Optional[int]:
    """``save::number`` — целочисленный тег как i64, иначе None."""
    if tag is None:
        return None
    return {
        TagType.Byte: tag.byte_val,
        TagType.Short: tag.short_val,
        TagType.Int: tag.int_val,
        TagType.Long: tag.long_val,
    }.get(tag.tag_type)


# ---------------------------------------------------------------------------
# Preset / Page / State (flat.rs L227-333)
# ---------------------------------------------------------------------------

class Page(Enum):
    """``flat.rs::Page`` — открытая страница экрана."""

    LAYERS = "layers"
    PRESETS = "presets"


@dataclass
class Preset:
    """``flat.rs::Preset`` — пресет flat-мира."""

    id: str
    display: str
    settings: FlatSettings


@dataclass
class Scroll:
    """``ui.rs::Scroll`` (``AbstractScrollArea``): amount, wheel, held bar."""

    amount: float = 0.0
    #: Последняя y указателя, пока тянут скроллбар (``scrolling``).
    held: Optional[float] = None

    @staticmethod
    def _max(top: float, bottom: float, content: float) -> float:
        return max(0.0, content - (bottom - top))

    def clamp(self, top: float, bottom: float, content: float) -> None:
        self.amount = min(max(self.amount, 0.0), self._max(top, bottom, content))

    def wheel(
        self, delta: float, rate: float, top: float, bottom: float, content: float
    ) -> None:
        self.amount -= delta * rate
        self.clamp(top, bottom, content)

    def press(
        self,
        cursor: tuple[float, float],
        bar_x: float,
        top: float,
        bottom: float,
        content: float,
    ) -> bool:
        x, y = cursor
        over = bar_x <= x <= bar_x + 6.0 and top <= y < bottom
        self.held = y if (over and self._max(top, bottom, content) > 0.0) else None
        return self.held is not None

    def is_held(self) -> bool:
        return self.held is not None

    def drag(self, y: float, top: float, bottom: float, content: float) -> None:
        last = self.held
        if last is None:
            return
        maximum = self._max(top, bottom, content)
        if y < top:
            self.amount = 0.0
        elif y > bottom:
            self.amount = maximum
        else:
            height = bottom - top
            bar = min(max(math.trunc(height * height / content), 32.0), height - 8.0)
            self.amount += (y - last) * max(maximum / max(height - bar, 1e-9), 1.0)
        self.clamp(top, bottom, content)
        self.held = y

    def release(self) -> None:
        self.held = None


@dataclass
class State:
    """``flat.rs::State`` — состояние экрана слоёв/пресетов."""

    page: Page = Page.LAYERS
    settings: FlatSettings = field(default_factory=FlatSettings.default)
    share: str = ""
    share_focused: bool = False
    #: Выбранный слой в порядке списка сверху вниз.
    selected: Optional[int] = None
    scroll: Scroll = field(default_factory=Scroll)
    preset_selected: Optional[int] = None
    preset_pressed: Optional[int] = None
    preset_scroll: Scroll = field(default_factory=Scroll)
    presets: list[Preset] = field(default_factory=list)
    blocks: set[str] = field(default_factory=set)
    biomes: set[str] = field(default_factory=set)

    @classmethod
    def new(cls, root: Path, current: Optional[FlatSettings]) -> "State":
        """``State::new``: настройки (или default) + данные пресетов."""
        settings = current if current is not None else FlatSettings.default()
        presets, blocks, biomes = load(root)
        return cls(settings=settings, share=settings.to_share(), presets=presets,
                   blocks=blocks, biomes=biomes)

    def open_presets(self) -> None:
        self.page = Page.PRESETS
        self.preset_selected = None
        self.preset_pressed = None
        self.preset_scroll = Scroll()
        self.share = self.settings.to_share()
        self.share_focused = False

    def back_to_layers(self) -> None:
        self.page = Page.LAYERS
        self.share_focused = False

    def remove_selected(self) -> None:
        row = self.selected
        if row is None:
            return
        index = len(self.settings.layers) - 1 - row
        if 0 <= index < len(self.settings.layers):
            del self.settings.layers[index]
        self.selected = selection_after_removal(row, len(self.settings.layers))

    def apply_share(self) -> None:
        """``PresetFlatWorldScreen`` Select: разобрать share-текст в настройки."""
        if self.preset_pressed is not None and 0 <= self.preset_pressed < len(self.presets):
            base = self.presets[self.preset_pressed].settings
        else:
            base = self.settings
        parsed = FlatSettings.parse(self.share, self.blocks, self.biomes, base)
        self.settings = parsed if parsed is not None else FlatSettings.default()
        self.share = self.settings.to_share()
        self.page = Page.LAYERS
        self.share_focused = False
        self.selected = None

    def select_preset(self, index: int) -> None:
        if not (0 <= index < len(self.presets)):
            return
        self.preset_selected = index
        self.preset_pressed = index
        self.share = self.presets[index].settings.to_share()
        self.share_focused = False

    def selecting(self) -> Optional[int]:
        return self.preset_selected


# ---------------------------------------------------------------------------
# загрузка пресетов из .local (flat.rs L335-445)
# ---------------------------------------------------------------------------

def load(root: Path) -> tuple[list[Preset], set[str], set[str]]:
    """``flat.rs::load``: пресеты в порядке ``visible`` + id блоков/биомов."""
    presets: list[Preset] = []
    tag_path = root / "data/minecraft/tags/worldgen/flat_level_generator_preset/visible.json"
    tag_value = _read_json(tag_path)
    if isinstance(tag_value, dict):
        ids = tag_value.get("values")
        if isinstance(ids, list):
            for identifier in ids:
                if not isinstance(identifier, str) or ":" not in identifier:
                    continue
                namespace, path = identifier.split(":", 1)
                preset_path = root / (
                    f"data/{namespace}/worldgen/flat_level_generator_preset/{path}.json"
                )
                value = _read_json(preset_path)
                if not isinstance(value, dict):
                    continue
                settings = preset_settings(value)
                if settings is None:
                    continue
                display = value.get("display")
                presets.append(Preset(
                    id=identifier,
                    display=display if isinstance(display, str) else "minecraft:grass_block",
                    settings=settings,
                ))
    blocks = registry_ids(root, "minecraft:block")
    biomes = json_keys(root / "worldgen/biomes.json")
    return presets, blocks, biomes


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def preset_settings(value: Any) -> Optional[FlatSettings]:
    """``flat.rs::preset_settings``: ``settings`` пресета или None."""
    if not isinstance(value, dict):
        return None
    settings = value.get("settings")
    if not isinstance(settings, dict):
        return None
    layers_field = settings.get("layers")
    if not isinstance(layers_field, list):
        return None
    layers: list[FlatLayer] = []
    for layer in layers_field:
        if not isinstance(layer, dict):
            continue
        block = layer.get("block")
        height = layer.get("height")
        if isinstance(block, str) and isinstance(height, int):
            layers.append(FlatLayer(block, height))
    if not layers:
        return None
    overrides_field = settings.get("structure_overrides")
    if isinstance(overrides_field, str):
        structure_overrides = [overrides_field]
    elif isinstance(overrides_field, list):
        structure_overrides = [i for i in overrides_field if isinstance(i, str)]
    else:
        structure_overrides = []
    biome = settings.get("biome")
    return FlatSettings(
        biome=biome if isinstance(biome, str) else "minecraft:plains",
        features=bool(settings.get("features", False)),
        lakes=bool(settings.get("lakes", False)),
        layers=layers,
        structure_overrides=structure_overrides,
    )


def registry_ids(root: Path, registry: str) -> set[str]:
    """Id реестра из подготовленного ``registries.json``."""
    value = _read_json(root / "registries.json")
    if not isinstance(value, dict):
        return set()
    entry = value.get(registry)
    if not isinstance(entry, dict):
        return set()
    entries = entry.get("entries")
    if not isinstance(entries, dict):
        return set()
    return set(entries.keys())


def json_keys(path: Path) -> set[str]:
    value = _read_json(path)
    if not isinstance(value, dict):
        return set()
    return set(value.keys())


# ---------------------------------------------------------------------------
# геометрия (flat.rs L447-628)
# ---------------------------------------------------------------------------

def list_area(state: State, size: tuple[float, float]) -> tuple[float, float, float, float]:
    """``flat.rs::list_area``: ``(top, bottom, left, content_rows)``."""
    w, h = math.ceil(size[0]), math.ceil(size[1])
    if state.page == Page.LAYERS:
        top, bottom = 43.0, h - 60.0
    else:
        top, bottom = 80.0, h - 37.0
    left = math.floor((w - ROW_WIDTH) * 0.5)
    if state.page == Page.LAYERS:
        rows = HEADER + len(state.settings.layers) * LAYER_ROW + 4.0
    else:
        rows = len(state.presets) * PRESET_ROW + 4.0
    return top, bottom, left, rows


def _b(
    x: float, y: float, w: float, key: str, fallback: str, enabled: bool, id: int
) -> _CWButton:
    return _CWButton(
        x=x, y=y, w=w, label=lang.get_or(key, fallback),
        enabled=enabled, id=id,
    )


def buttons(w: float, h: float, state: State) -> list[_CWButton]:
    """``flat.rs::buttons``: кнопки открытой страницы."""
    if state.page == Page.LAYERS:
        x = math.trunc((w - 308.0) * 0.5)
        return [
            _b(x, h - 52.0, 150.0,
               "createWorld.customize.flat.removeLayer", "Remove Layer",
               state.selected is not None, 70),
            _b(x + 158.0, h - 52.0, 150.0,
               "createWorld.customize.presets", "Presets", True, 71),
            _b(x, h - 28.0, 150.0, "gui.done", "Done", True, 72).does("Done"),
            _b(x + 158.0, h - 28.0, 150.0,
               "gui.cancel", "Cancel", True, 73).does("Cancel"),
        ]
    return [
        _b(w / 2.0 - 155.0, h - 28.0, 150.0,
           "createWorld.customize.presets.select", "Select",
           state.selecting() is not None or len(state.share) > 1, 74),
        _b(w / 2.0 + 5.0, h - 28.0, 150.0,
           "gui.cancel", "Cancel", True, 75).does("Cancel"),
    ]


def layer_row(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> Optional[int]:
    """``flat.rs::layer_row``: строка под указателем (сверху вниз)."""
    top, bottom, _left, _ = list_area(state, size)
    if cursor[1] < top or cursor[1] >= bottom:
        return None
    y = cursor[1] - top - 2.0 + state.scroll.amount
    if y < HEADER:
        return None
    row = math.floor((y - HEADER) / LAYER_ROW)
    return row if row < len(state.settings.layers) else None


def preset_row(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> Optional[int]:
    """``flat.rs::preset_row``: строка пресета под указателем."""
    top, bottom, _left, _ = list_area(state, size)
    if cursor[1] < top or cursor[1] >= bottom:
        return None
    row = math.floor(
        (cursor[1] - top - 2.0 + state.preset_scroll.amount) / PRESET_ROW
    )
    return row if row < len(state.presets) else None


def click(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> None:
    """``flat.rs::click``: нажатие на список, share-поле или скроллбар."""
    top, bottom, left, content = list_area(state, size)
    bar = left + ROW_WIDTH + 6.0
    if state.page == Page.LAYERS:
        if state.scroll.press(cursor, bar, top, bottom, content):
            return
        state.selected = layer_row(state, cursor, size)
    else:
        field = share_field(size)
        state.share_focused = ui_hovered(cursor, field[0], field[1], field[2], field[3])
        if state.preset_scroll.press(cursor, bar, top, bottom, content):
            return
        row = preset_row(state, cursor, size)
        if row is not None:
            state.select_preset(row)


def focus_row(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> bool:
    """``flat.rs::focus_row``: фокус на строке (выбирает её), ``True`` если строка есть."""
    if state.page == Page.LAYERS:
        row = layer_row(state, cursor, size)
        if row is not None:
            state.selected = row
        return row is not None
    row = preset_row(state, cursor, size)
    if row is not None:
        state.preset_selected = row
        state.share_focused = False
    return row is not None


def share_field(size: tuple[float, float]) -> list[float]:
    """``flat.rs::share_field``: EditBox ``50,40,(w-100),20``."""
    return [50.0, 40.0, max(math.ceil(size[0]) - 100.0, 1.0), 20.0]


def wheel(
    state: State, delta: float, cursor: tuple[float, float], size: tuple[float, float]
) -> None:
    """``flat.rs::wheel``: колесо над списком."""
    top, bottom, _left, content = list_area(state, size)
    if cursor[1] < top or cursor[1] >= bottom:
        return
    if state.page == Page.LAYERS:
        state.scroll.wheel(delta, LAYER_ROW, top, bottom, content)
    else:
        state.preset_scroll.wheel(delta, PRESET_ROW, top, bottom, content)


def drag(state: State, cursor: tuple[float, float], size: tuple[float, float]) -> None:
    """``flat.rs::drag``: перетаскивание полосы прокрутки."""
    top, bottom, _left, content = list_area(state, size)
    if state.page == Page.LAYERS:
        state.scroll.drag(cursor[1], top, bottom, content)
    else:
        state.preset_scroll.drag(cursor[1], top, bottom, content)


def release(state: State) -> None:
    """``flat.rs::release``: отпустить обе полосы прокрутки."""
    state.scroll.release()
    state.preset_scroll.release()


def ui_hovered(cursor: tuple[float, float], x: float, y: float, w: float, h: float) -> bool:
    """``ui::hovered``: точка внутри прямоугольника."""
    return x <= cursor[0] < x + w and y <= cursor[1] < y + h


def selection_after_removal(row: int, remaining: int) -> Optional[int]:
    """``DetailsList.deleteLayer``: строка остаётся выбранной, иначе None."""
    if remaining > 0:
        return min(row, remaining - 1)
    return None


# ---------------------------------------------------------------------------
# имена/иконки слоёв (flat.rs L1006-1067)
# ---------------------------------------------------------------------------

def layer_item(identifier: str) -> str:
    """``FlatLayerInfo``: предмет блока; у жидкостей — ведро."""
    name = identifier[len("minecraft:"):] if identifier.startswith("minecraft:") else identifier
    if name == "water":
        return "minecraft:water_bucket"
    if name == "lava":
        return "minecraft:lava_bucket"
    return f"minecraft:{name}"


def layer_icon(atlas: Any, identifier: str) -> Optional[str]:
    """``flat.rs::layer_icon``: спрайт иконки слоя (или None).

    FALLBACK: спрайты блоков/предметов живут в block/item-атласе, которого у
    QuadRix пока нет; в GUI-атласе их не найти, поэтому обычно ``None`` и
    рисуется слот-заглушка.
    """
    name = identifier[len("minecraft:"):] if identifier.startswith("minecraft:") else identifier
    if name == "water":
        candidates = ["item/water_bucket"]
    elif name == "lava":
        candidates = ["item/lava_bucket"]
    else:
        candidates = [
            f"item/{name}", f"block/{name}",
            f"block/{name}_side", f"block/{name}_top",
        ]
    sprites = getattr(atlas, "sprites", None)
    if not sprites:
        return None
    for sprite in candidates:
        if sprite in sprites:
            return sprite
    return None


def item_name(identifier: str) -> str:
    """``flat.rs::item_name``: подпись слоя из ``lang``."""
    name = identifier[len("minecraft:"):] if identifier.startswith("minecraft:") else identifier
    if name == "water":
        return lang.get_or("item.minecraft.water_bucket", "Water Bucket")
    if name == "lava":
        return lang.get_or("item.minecraft.lava_bucket", "Lava Bucket")
    for key in (f"block.minecraft.{name}", f"item.minecraft.{name}"):
        if lang.has(key):
            return lang.get(key)
    return pretty(name)


def preset_name(identifier: str) -> str:
    """``flat.rs::preset_name``: подпись пресета из ``lang``."""
    key = "flat_world_preset." + identifier.replace(":", ".")
    name = identifier[len("minecraft:"):] if identifier.startswith("minecraft:") else identifier
    return lang.get_or(key, pretty(name))


def pretty(name: str) -> str:
    """``flat.rs::pretty``: ``grass_block`` → ``Grass Block``."""
    return " ".join(
        word[:1].upper() + word[1:]
        for word in name.split("_")
        if word
    )


# ---------------------------------------------------------------------------
# рендер (flat.rs L630-1005, упрощённо: без 3D-моделей предметов)
# ---------------------------------------------------------------------------

def draw(
    batch: Batch,
    font: Optional[Font],
    state: State,
    cursor: tuple[float, float],
    size: tuple[float, float],
    atlas: Any = None,
) -> None:
    """``flat.rs::draw``: фон и открытая страница."""
    if atlas is None:
        atlas = getattr(batch, "atlas", None)
    w, h = math.ceil(size[0]), math.ceil(size[1])
    draw_menu_background(batch, font, float(w), float(h))
    if state.page == Page.LAYERS:
        _draw_layers(batch, font, state, cursor, (w, h), atlas)
    else:
        _draw_presets(batch, font, state, cursor, (w, h), atlas)


def _draw_layers(
    batch: Batch,
    font: Optional[Font],
    state: State,
    cursor: tuple[float, float],
    size: tuple[float, float],
    atlas: Any,
) -> None:
    w, h = size
    centered(batch, font, lang.get_or(
        "createWorld.customize.flat.title", "Superflat Customization"
    ), 8.0, w)
    top, bottom, left, content = list_area(state, (w, h))
    list_background(batch, atlas, top, bottom, w)
    separators(batch, atlas, top, bottom, w)
    right = left + ROW_WIDTH
    draw_text(batch, font, lang.get_or(
        "createWorld.customize.flat.tile", "Layer Material"
    ), left + 2.0, top + 3.0, rgba(255, 255, 255, 255))
    height_label = lang.get_or("createWorld.customize.flat.height", "Height")
    draw_text(batch, font, height_label,
              right - _text_width(font, height_label) - 2.0, top + 3.0,
              rgba(255, 255, 255, 255))
    offset = math.trunc(state.scroll.amount)
    for row, layer in enumerate(reversed(state.settings.layers)):
        y = top + 2.0 + HEADER + row * LAYER_ROW - offset
        target = [left - 2.0, y - 1.0, ROW_WIDTH + 4.0, LAYER_ROW]
        hovered = ui_hovered(cursor, *target)
        if state.selected == row:
            solid(batch, font, *target, rgba(255, 255, 255, 70))
        elif hovered:
            solid(batch, font, *target, rgba(255, 255, 255, 25))
        _slot(batch, font, atlas, layer.block, left + 2.0, y + 1.0)
        draw_text(batch, font, item_name(layer.block),
                  left + 2.0 + 18.0 + 5.0, y + 5.0, rgba(255, 255, 255, 255))
        if row == 0:
            key, fallback = "createWorld.customize.flat.layer.top", "Top - %s"
        elif row + 1 == len(state.settings.layers):
            key, fallback = "createWorld.customize.flat.layer.bottom", "Bottom - %s"
        else:
            key, fallback = "createWorld.customize.flat.layer", "%s"
        label = _format_translation(lang.get_or(key, fallback), str(layer.height))
        draw_text(batch, font, label,
                  right - _text_width(font, label) - 2.0, y + 5.0,
                  rgba(255, 255, 255, 255))
    scrollbar(batch, atlas, left + ROW_WIDTH + 6.0, top, bottom, content,
               state.scroll.amount)


def _draw_presets(
    batch: Batch,
    font: Optional[Font],
    state: State,
    cursor: tuple[float, float],
    size: tuple[float, float],
    atlas: Any,
) -> None:
    w, h = size
    centered(batch, font, lang.get_or(
        "createWorld.customize.presets.title", "Select a Preset"
    ), 8.0, w)
    draw_text(batch, font, lang.get_or(
        "createWorld.customize.presets.share",
        "Want to share your preset with someone? Use the box below!",
    ), 51.0, 30.0, rgba(160, 160, 160, 255))
    field = share_field((w, h))
    edit_box(batch, font, field, state.share, state.share_focused)
    draw_text(batch, font, lang.get_or(
        "createWorld.customize.presets.list",
        "Alternatively, here are some we made earlier!",
    ), 51.0, 68.0, rgba(160, 160, 160, 255))
    top, bottom, left, content = list_area(state, (w, h))
    list_background(batch, atlas, top, bottom, w)
    separators(batch, atlas, top, bottom, w)
    offset = math.trunc(state.preset_scroll.amount)
    for row, preset in enumerate(state.presets):
        y = top + 2.0 + row * PRESET_ROW - offset
        target = [left - 2.0, y - 1.0, ROW_WIDTH + 4.0, PRESET_ROW]
        hovered = ui_hovered(cursor, *target)
        if state.preset_selected == row:
            solid(batch, font, *target, rgba(255, 255, 255, 70))
        elif hovered:
            solid(batch, font, *target, rgba(255, 255, 255, 25))
        _slot(batch, font, atlas, preset.display, left + 2.0, y + 2.0)
        draw_text(batch, font, preset_name(preset.id),
                  left + 2.0 + 18.0 + 5.0, y + 7.0, rgba(255, 255, 255, 255))
    scrollbar(batch, atlas, left + ROW_WIDTH + 6.0, top, bottom, content,
               state.preset_scroll.amount)


def centered(batch: Batch, font: Optional[Font], text: str, y: float, w: float) -> None:
    """``title.rs::centered``: строка по центру ширины ``w``."""
    width = _text_width(font, text)
    draw_text(batch, font, text, math.floor((w - width) / 2.0), y)


def _text_width(font: Optional[Font], text: str) -> float:
    return float(font.width(text)) if font is not None else 0.0


def _format_translation(line: str, value: str) -> str:
    """``format_translation`` для одной подстановки ``%s``."""
    if "%s" in line:
        return line.replace("%s", value)
    return line


def list_background(batch: Batch, atlas: Any, top: float, bottom: float, w: float) -> None:
    """``ui::list_background`` для строк списка."""
    if atlas is not None and atlas.tiled(
        batch, "gui/menulist_background", 0.0, top, w, bottom - top, 32.0
    ):
        return
    solid(batch, None, 0.0, top, w, bottom - top, rgba(0, 0, 0, 160))


def separators(batch: Batch, atlas: Any, top: float, bottom: float, w: float) -> None:
    """``ui::separators``: разделители над/под списком."""
    if atlas is None:
        return
    atlas.tiled(batch, "gui/header_separator", 0.0, top - 2.0, w, 2.0, 32.0)
    atlas.tiled(batch, "gui/footer_separator", 0.0, bottom, w, 2.0, 32.0)


def scrollbar(
    batch: Batch, atlas: Any, x: float, top: float, bottom: float,
    content: float, scroll: float,
) -> None:
    """``ui::scrollbar_sprites``: фон и бегунок полосы прокрутки."""
    height = bottom - top
    if content <= height:
        return
    bar = min(max(math.floor(height * height / content), 32.0), height - 8.0)
    y = top + math.floor((scroll / (content - height)) * (height - bar))
    if atlas is not None and atlas.nine_slice(
        batch, "gui/sprites/widget/scroller_background", x, top, 6.0, height
    ):
        atlas.nine_slice(batch, "gui/sprites/widget/scroller", x, y, 6.0, bar)
        return
    solid(batch, None, x, top, 6.0, height, rgba(0, 0, 0, 120))
    solid(batch, None, x, y, 6.0, bar, rgba(128, 128, 128, 255))


def edit_box(
    batch: Batch, font: Optional[Font], field: list[float], value: str, focused: bool
) -> None:
    """``EditBox`` share-текста (рамка + текст + каретка)."""
    x, y, w, h = field
    solid(batch, font, x, y, w, h, rgba(160, 160, 160, 255))
    solid(batch, font, x + 1.0, y + 1.0, w - 2.0, h - 2.0, rgba(0, 0, 0, 255))
    draw_text(batch, font, value, x + 4.0, y + 6.0, rgba(224, 224, 224, 255))
    if focused:
        caret = _text_width(font, value)
        solid(batch, font, x + 4.0 + caret, y + 3.0, 1.0, h - 6.0,
              rgba(224, 224, 224, 255))


def _slot(
    batch: Batch, font: Optional[Font], atlas: Any, identifier: str, x: float, y: float
) -> None:
    """``flat.rs::slot``: слот 18x18 под иконку слоя.

    FALLBACK: 3D-модели предметов (``ItemRenderer``) не портированы; рисуем
    спрайт ``container/slot`` и, если найдётся, плоскую иконку.
    """
    drawn = False
    if atlas is not None:
        drawn = atlas.blit(batch, "gui/sprites/container/slot", x, y, 18.0, 18.0)
    if not drawn:
        solid(batch, font, x, y, 18.0, 18.0, rgba(139, 139, 139, 255))
        solid(batch, font, x + 1.0, y + 1.0, 16.0, 16.0, rgba(55, 55, 55, 255))
    icon = layer_icon(atlas, identifier)
    if atlas is not None and icon is not None:
        atlas.blit(batch, icon, x + 1.0, y + 1.0, 16.0, 16.0)


def button_ui(button: _CWButton) -> Button:
    """Преобразовать кнопку WC4 в рисуемый :class:`ui.Button`."""
    return Button(
        x=button.x, y=button.y, w=button.w, h=20.0, label=button.label,
        active=button.enabled, hovered=False,
    )


def draw_buttons(
    batch: Batch, font: Optional[Font], w: float, h: float, state: State,
    cursor: tuple[float, float] = (-1.0, -1.0),
) -> None:
    """Нарисовать кнопки открытой страницы (``flat.rs::buttons`` → nine-slice)."""
    for button in buttons(w, h, state):
        ui = button_ui(button)
        ui.hovered = ui_hovered(cursor, button.x, button.y, button.w, 20.0)
        ui.render(batch, font)


# ---------------------------------------------------------------------------
# экран (title.rs::Mode::CreateFlat)
# ---------------------------------------------------------------------------

class FlatWorldScreen(Screen):
    """CreateFlatWorldScreen как :class:`Screen`.

    Обёртка вокруг :class:`State`: список слоёв, страница пресетов и кнопки.
    Порт ``title.rs::flat_click`` (id 70 Remove, 71 Presets, 72 Done,
    73 Cancel, 74 Select, 75 Cancel) и ``flat::wheel`` / ``flat::drag`` /
    ``flat::release`` / ``flat::click``.

    ``on_done`` получает итоговые ``FlatSettings`` (слой/биом), ``on_cancel``
    вызывается при Escape/Done без применения; без колбэков экран работает
    через переданный ``stack``.
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        *,
        root: Path | str = PACK_ROOT,
        settings: Optional[FlatSettings] = None,
        stack: Optional[ScreenStack] = None,
        on_done: Optional[Callable[[FlatSettings], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.stack = stack
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.root = Path(root)
        self.state = State.new(self.root, settings)
        self.cursor: tuple[float, float] = (-1.0, -1.0)
        self.buttons: list[Button] = []
        self.build()

    # -- сборка ----------------------------------------------------------

    def _size(self) -> tuple[float, float]:
        return (math.ceil(self.width), math.ceil(self.height))

    def build(self) -> None:
        w, h = self._size()
        self.buttons = [
            Button(
                x=b.x, y=b.y, w=b.w, h=20.0, label=b.label,
                active=b.enabled, on_click=self._dispatcher(b.id),
            )
            for b in buttons(w, h, self.state)
        ]

    def _dispatcher(self, bid: int) -> Callable[[], None]:
        return lambda: self._on_button(bid)

    def _on_button(self, bid: int) -> None:
        if bid == 70:
            self.state.remove_selected()
        elif bid == 71:
            self.state.open_presets()
        elif bid == 72:
            self.done()
            return
        elif bid == 73:
            self.cancel()
            return
        elif bid == 74:
            self.state.apply_share()
        elif bid == 75:
            self.state.back_to_layers()
        else:
            _log(f"неизвестная кнопка id={bid}")
            return
        self.build()

    # -- действия (title.rs::close_flat) --------------------------------

    def done(self) -> None:
        """Done (id 72): применить слои и вернуться в Create New World."""
        if self.on_done is not None:
            self.on_done(self.state.settings)
        elif self.stack is not None:
            self.stack.pop()

    def cancel(self) -> None:
        """Cancel/Escape: на странице пресетов — назад к слоям, иначе закрыть."""
        if self.state.page == Page.PRESETS:
            self.state.back_to_layers()
            self.build()
            return
        if self.on_cancel is not None:
            self.on_cancel()
            return
        if self.stack is not None:
            self.stack.pop()

    # -- ввод ------------------------------------------------------------

    def handle_click(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        click(self.state, (mx, my), self._size())
        self.build()
        return True

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key in ("escape", "key.keyboard.escape"):
            self.cancel()
            return True
        if self.state.page == Page.PRESETS and self.state.share_focused:
            if key in ("backspace", "key.keyboard.backspace"):
                self.state.share = self.state.share[:-1]
                return True
            if ch is not None and len(ch) == 1 and ch.isprintable():
                self.state.share += ch
                return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        self.cursor = (mx, my)
        handled = False
        for button in self.buttons:
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        return handled

    def handle_scroll(self, dy: float) -> bool:
        before = (self.state.scroll.amount, self.state.preset_scroll.amount)
        wheel(self.state, dy, self.cursor, self._size())
        return (self.state.scroll.amount, self.state.preset_scroll.amount) != before

    def handle_release(self, mx: float, my: float) -> bool:
        release(self.state)
        return True

    # -- рендер ----------------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw(batch, font, self.state, self.cursor, self._size())
        for button in self.buttons:
            button.render(batch, font)
