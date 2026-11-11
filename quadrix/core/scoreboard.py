# Порт horizon-client-core/src/scoreboard.rs (Minecraft 26.3).
#
# Табло (`Scoreboard`, `Objective`, `Score`, `PlayerTeam`, `ObjectiveCriteria`,
# `NumberFormat`) и его сохранённые данные
# (`data/minecraft/scoreboard.dat`, `ScoreboardSaveData.Packed`).
#
# Компаунд компонента (`Comp`) в Rust — это `serde_json::Value`, то есть
# обычные Python dict/list/str/bool/int/float/None. `Tag` используется только
# при сериализации (`pack`/`unpack`, `component_tag`).
#
# ВАЖНО (сверено с Rust):
#   * `objectives`/`scores`/`teams`/`display` — обычные `dict` (Python 3.7+
#     сохраняет порядок вставки, что повторяет итерационный порядок vanilla);
#   * полный набор методов табло (PART 1 модели + PART 2 операции) в одном
#     файле: `add_objective`/`remove_objective`/`set`/`get`/`reset_*`/
#     `add_team`/`remove_team`/`add_to_team`/`remove_from_team`/
#     `set_display_objective`/`pack`/`unpack`;
#   * `NumberFormat::to_tag`/`from_tag` — через `json_to_tag`/`tag_to_json`.
#
# FALLBACK: `uuid.rs` не портирован — локальная `uuid_from_text` нужна только
# для hover-события `show_entity` (`entity_uuids`).

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from quadrix.core.component import comp_text as _component_text
from quadrix.core.component import hex_color, shadow_color
from quadrix.core.text import COLORS, Style, Text, font_id as _text_font_id, named_color
from quadrix.world.nbt import Tag, TagType

__all__ = [
    "Comp",
    "literal",
    "comp_text",
    "bracketed",
    "json_to_tag",
    "tag_to_json",
    "string_of",
    "bool_of",
    "int_of",
    "NumberFormat",
    "style_from_json",
    "RenderType",
    "CRITERIA_DUMMY",
    "CRITERIA_TRIGGER",
    "CRITERIA_DEATH_COUNT",
    "CRITERIA_PLAYER_KILLS",
    "CRITERIA_TOTAL_KILLS",
    "CRITERIA_HEALTH",
    "CRITERIA_FOOD",
    "CRITERIA_AIR",
    "CRITERIA_ARMOR",
    "CRITERIA_XP",
    "CRITERIA_LEVEL",
    "CUSTOM_CRITERIA",
    "CUSTOM_STATS",
    "STAT_TYPES",
    "team_colors",
    "team_color_rgb",
    "InvalidIdentifier",
    "criteria_by_name",
    "criteria_exists",
    "criteria_read_only",
    "criteria_render_type",
    "stat_criteria",
    "SLOT_LIST",
    "SLOT_SIDEBAR",
    "SLOT_BELOW_NAME",
    "display_slots",
    "display_slot_valid",
    "Visibility",
    "CollisionRule",
    "Team",
    "teams_allied",
    "teams_allow_damage",
    "pushable_by",
    "invisible_to",
    "team_shows_name",
    "NameView",
    "name_shown",
    "death_message_reaches",
    "Objective",
    "Score",
    "ScoreEntry",
    "Scoreboard",
    "component_tag",
    "entity_uuids",
    "canonical_style",
    "canonical_component",
    "death_message_args",
]

# Текстовый компонент в его JSON-форме (то, что держит `ComponentSerialization`).
Comp = Any

I32_MIN = -2147483648
I32_MAX = 2147483647
I64_MIN = -(2 ** 63)
I64_MAX = 2 ** 63 - 1


def _wrap_i32(v: int) -> int:
    """`i32::wrapping_add` в границах i32."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _to_i32(v: int) -> int:
    """`u32 as i32`: беззнаковое 32-битное → знаковое."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def literal(s: str) -> Comp:
    """`literal`: строка-компонент."""
    return s


def comp_text(c: Comp) -> Text:
    """`comp_text`: JSON-компонент → текст."""
    return _component_text(c)


def bracketed(inner: Text) -> Text:
    """`ComponentUtils.wrapInSquareBrackets`."""
    return Text.translate("chat.square_brackets", [inner])


def hover_name(text: Text, name: str) -> Text:
    """Стиль с hover-текстом имени."""
    return text.with_style(Style(hover=Text.literal(name)))


# ── NBT <-> JSON ──────────────────────────────────────────────────────────
def _value_to_string(v: Any) -> str:
    """`Value::to_string` из serde_json (для не-стр/не-объект/не-массив)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return str(v)


def json_to_tag(v: Any) -> Tag:
    """JSON-значение → `Tag` (как `scoreboard::json_to_tag`)."""
    if v is None:
        return Tag(TagType.String, str_val="")
    if isinstance(v, bool):
        return Tag(TagType.Byte, byte_val=1 if v else 0)
    if isinstance(v, int):
        if I32_MIN <= v <= I32_MAX:
            return Tag(TagType.Int, int_val=v)
        if I64_MIN <= v <= I64_MAX:
            return Tag(TagType.Long, long_val=v)
        return Tag(TagType.Double, double_val=float(v))
    if isinstance(v, float):
        return Tag(TagType.Double, double_val=v)
    if isinstance(v, str):
        return Tag(TagType.String, str_val=v)
    if isinstance(v, list):
        return Tag(TagType.List, list_val=[json_to_tag(x) for x in v])
    if isinstance(v, dict):
        return Tag(
            TagType.Compound,
            compound_val={k: json_to_tag(x) for k, x in v.items()},
        )
    return Tag(TagType.String, str_val=str(v))


def tag_to_json(t: Any) -> Any:
    """`Tag` → JSON-значение (как `scoreboard::tag_to_json`)."""
    if not isinstance(t, Tag):
        return t
    tt = t.tag_type
    if tt == TagType.End:
        return None
    if tt == TagType.Byte:
        return (t.byte_val or 0) != 0
    if tt == TagType.Short:
        return int(t.short_val or 0)
    if tt == TagType.Int:
        return int(t.int_val or 0)
    if tt == TagType.Long:
        return int(t.long_val or 0)
    if tt == TagType.Float:
        return float(t.float_val or 0.0)
    if tt == TagType.Double:
        return float(t.double_val or 0.0)
    if tt == TagType.String:
        return t.str_val if t.str_val is not None else ""
    if tt == TagType.List:
        return [tag_to_json(x) for x in (t.list_val or [])]
    if tt == TagType.Compound:
        return {k: tag_to_json(x) for k, x in (t.compound_val or {}).items()}
    if tt == TagType.ByteArray:
        return [b if b < 128 else b - 256 for b in (t.bytes_val or b"")]
    if tt == TagType.IntArray:
        return list(t.intarray_val or [])
    if tt == TagType.LongArray:
        return list(t.longarray_val or [])
    return None


def string_of(t: Optional[Tag]) -> Optional[str]:
    """`string_of`: строковый `Tag`, иначе None."""
    if isinstance(t, Tag) and t.tag_type == TagType.String:
        return t.str_val if t.str_val is not None else ""
    return None


def bool_of(t: Optional[Tag], default: bool) -> bool:
    """`bool_of`: байтовый `Tag` (0/1), иначе `default`."""
    if isinstance(t, Tag) and t.tag_type == TagType.Byte:
        return (t.byte_val or 0) != 0
    return default


def int_of(t: Optional[Tag]) -> Optional[int]:
    """`int_of`: Int/Short/Byte → int, иначе None."""
    if not isinstance(t, Tag):
        return None
    if t.tag_type == TagType.Int:
        return int(t.int_val or 0)
    if t.tag_type == TagType.Short:
        return int(t.short_val or 0)
    if t.tag_type == TagType.Byte:
        return int(t.byte_val or 0)
    return None


def _get_tag(t: Any, key: str) -> Optional[Tag]:
    """`Tag::get` для компаунда."""
    if isinstance(t, Tag) and t.tag_type == TagType.Compound and t.compound_val is not None:
        return t.compound_val.get(key)
    return None


def _compound(pairs: List[Tuple[str, Tag]]) -> Tag:
    return Tag(TagType.Compound, compound_val={k: v for k, v in pairs})


# ── number formats ─────────────────────────────────────────────────────────
@dataclass
class NumberFormat:
    """`NumberFormat`: как показывается значение счёта (`blank`/`fixed`/`styled`)."""

    kind: str  # "blank" | "fixed" | "styled"
    value: Any = None

    @staticmethod
    def blank() -> "NumberFormat":
        return NumberFormat("blank")

    @staticmethod
    def fixed(comp: Comp) -> "NumberFormat":
        return NumberFormat("fixed", comp)

    @staticmethod
    def styled(style: Comp) -> "NumberFormat":
        return NumberFormat("styled", style)

    @staticmethod
    def sidebar_default() -> "NumberFormat":
        return NumberFormat.styled({"color": "red"})

    @staticmethod
    def player_list_default() -> "NumberFormat":
        return NumberFormat.styled({"color": "yellow"})

    def format(self, value: int) -> Text:
        """`NumberFormat.format`: счёт как текст."""
        if self.kind == "blank":
            return Text.empty()
        if self.kind == "fixed":
            return comp_text(self.value)
        return Text.literal(str(value)).with_style(style_from_json(self.value))

    def to_json(self) -> Comp:
        """`NumberFormatTypes.CODEC` — кодирование."""
        if self.kind == "blank":
            return {"type": "minecraft:blank"}
        if self.kind == "fixed":
            return {"type": "minecraft:fixed", "value": canonical_component(self.value)}
        v = canonical_style(self.value)
        if isinstance(v, dict):
            v["type"] = "minecraft:styled"
        return v

    @staticmethod
    def from_json(v: Any) -> Optional["NumberFormat"]:
        """`NumberFormatTypes.CODEC` — декодирование."""
        if not isinstance(v, dict):
            return None
        kind = v.get("type")
        if not isinstance(kind, str):
            return None
        kind = kind[len("minecraft:"):] if kind.startswith("minecraft:") else kind
        if kind == "blank":
            return NumberFormat.blank()
        if kind == "fixed":
            return NumberFormat.fixed(v.get("value")) if "value" in v else None
        if kind == "styled":
            s = {k: x for k, x in v.items() if k != "type"}
            return NumberFormat.styled(s)
        return None

    def to_tag(self) -> Tag:
        """`NumberFormat::to_tag`."""
        tag = json_to_tag(self.to_json())
        entity_uuids(tag)
        return tag

    @staticmethod
    def from_tag(t: Tag) -> Optional["NumberFormat"]:
        """`NumberFormat::from_tag`."""
        return NumberFormat.from_json(tag_to_json(t))


def style_from_json(v: Any) -> Style:
    """`Style` из его JSON-объектной формы."""
    s = Style()
    if not isinstance(v, dict):
        return s
    c = v.get("color")
    if isinstance(c, str):
        s.color = named_color(c)
        if s.color is None:
            s.color = hex_color(c)
    if "shadow_color" in v:
        s.shadow_color = shadow_color(v["shadow_color"])
    s.bold = v.get("bold") if isinstance(v.get("bold"), bool) else None
    s.italic = v.get("italic") if isinstance(v.get("italic"), bool) else None
    s.underlined = v.get("underlined") if isinstance(v.get("underlined"), bool) else None
    s.strikethrough = v.get("strikethrough") if isinstance(v.get("strikethrough"), bool) else None
    s.obfuscated = v.get("obfuscated") if isinstance(v.get("obfuscated"), bool) else None
    f = v.get("font")
    if isinstance(f, str):
        s.font = _text_font_id(f)
    return s


# ── criteria ───────────────────────────────────────────────────────────────
class RenderType(Enum):
    """`RenderType`: как рисуется счёт."""

    Integer = "integer"
    Hearts = "hearts"

    def id(self) -> str:
        return self.value

    @staticmethod
    def by_id(id: str) -> "RenderType":
        return RenderType.Hearts if id == "hearts" else RenderType.Integer


CRITERIA_DUMMY = "dummy"
CRITERIA_TRIGGER = "trigger"
CRITERIA_DEATH_COUNT = "deathCount"
CRITERIA_PLAYER_KILLS = "playerKillCount"
CRITERIA_TOTAL_KILLS = "totalKillCount"
CRITERIA_HEALTH = "health"
CRITERIA_FOOD = "food"
CRITERIA_AIR = "air"
CRITERIA_ARMOR = "armor"
CRITERIA_XP = "xp"
CRITERIA_LEVEL = "level"

# `ObjectiveCriteria.getCustomCriteriaNames` (без пер-цветовых).
CUSTOM_CRITERIA: List[str] = [
    CRITERIA_DUMMY,
    CRITERIA_TRIGGER,
    CRITERIA_DEATH_COUNT,
    CRITERIA_PLAYER_KILLS,
    CRITERIA_TOTAL_KILLS,
    CRITERIA_HEALTH,
    CRITERIA_FOOD,
    CRITERIA_AIR,
    CRITERIA_ARMOR,
    CRITERIA_XP,
    CRITERIA_LEVEL,
]

# `Stats` custom statistic ids.
CUSTOM_STATS: List[str] = [
    "leave_game",
    "play_time",
    "total_world_time",
    "time_since_death",
    "time_since_rest",
    "sneak_time",
    "walk_one_cm",
    "crouch_one_cm",
    "sprint_one_cm",
    "walk_on_water_one_cm",
    "fall_one_cm",
    "climb_one_cm",
    "fly_one_cm",
    "walk_under_water_one_cm",
    "minecart_one_cm",
    "boat_one_cm",
    "pig_one_cm",
    "happy_ghast_one_cm",
    "horse_one_cm",
    "aviate_one_cm",
    "swim_one_cm",
    "strider_one_cm",
    "nautilus_one_cm",
    "jump",
    "drop",
    "damage_dealt",
    "damage_dealt_absorbed",
    "damage_dealt_resisted",
    "damage_taken",
    "damage_blocked_by_shield",
    "damage_absorbed",
    "damage_resisted",
    "deaths",
    "mob_kills",
    "animals_bred",
    "player_kills",
    "fish_caught",
    "talked_to_villager",
    "traded_with_villager",
    "eat_cake_slice",
    "fill_cauldron",
    "use_cauldron",
    "clean_armor",
    "clean_banner",
    "clean_shulker_box",
    "interact_with_brewingstand",
    "interact_with_beacon",
    "inspect_dropper",
    "inspect_hopper",
    "inspect_dispenser",
    "play_noteblock",
    "tune_noteblock",
    "pot_flower",
    "trigger_trapped_chest",
    "open_enderchest",
    "enchant_item",
    "play_record",
    "interact_with_furnace",
    "interact_with_crafting_table",
    "open_chest",
    "sleep_in_bed",
    "sleep_in_straw_bed",
    "open_shulker_box",
    "open_barrel",
    "interact_with_blast_furnace",
    "interact_with_smoker",
    "interact_with_lectern",
    "interact_with_campfire",
    "interact_with_cartography_table",
    "interact_with_loom",
    "interact_with_stonecutter",
    "bell_ring",
    "raid_trigger",
    "raid_win",
    "interact_with_anvil",
    "interact_with_grindstone",
    "target_hit",
    "interact_with_smithing_table",
]

STAT_TYPES: List[str] = [
    "mined",
    "crafted",
    "used",
    "broken",
    "picked_up",
    "dropped",
    "killed",
    "killed_by",
    "custom",
]


def team_colors() -> List[str]:
    """16 цветов команды (`TeamColor`) в порядке `ChatFormatting`."""
    return [name for _code, name, _rgb in COLORS]


def team_color_rgb(name: str) -> Optional[int]:
    """RGB цвета команды по имени."""
    return named_color(name)


def _is_team_criteria(name: str) -> bool:
    colors = team_colors()
    for prefix in ("teamkill.", "killedByTeam."):
        if name.startswith(prefix):
            c = name[len(prefix):]
            if any(t == c for t in colors):
                return True
    return False


_NS_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-.")
_PATH_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-./")


def identifier_by_separator(id: str, sep: str) -> Optional[str]:
    """`Identifier.bySeparator`: None для символов, которые id не может
    содержать (vanilla бросает исключение)."""
    idx = id.find(sep)
    if idx == 0:
        ns, path = "minecraft", id[1:]
    elif idx > 0:
        ns, path = id[:idx], id[idx + 1:]
    else:
        ns, path = "minecraft", id
    ns_ok = all(c in _NS_CHARS for c in ns)
    path_ok = all(c in _PATH_CHARS for c in path)
    if ns_ok and path_ok:
        return ns + ":" + path
    return None


class InvalidIdentifier(Exception):
    """Идентификатор, который конструктор `Identifier` в vanilla отвергает."""


def criteria_by_name(name: str, reg: Any) -> Optional[str]:
    """`ObjectiveCriteria.byName`: каноничное имя критерия (статистики названы
    `minecraft.<type>:<namespace>.<path>`), None если такого нет; бросает
    `InvalidIdentifier` там, где vanilla бросает на плохом id."""
    if name in CUSTOM_CRITERIA or _is_team_criteria(name):
        return name
    colon = name.find(":")
    if colon < 0:
        return None
    ty = identifier_by_separator(name[:colon], ".")
    if ty is None:
        raise InvalidIdentifier(name)
    if ty.startswith("minecraft:"):
        ty = ty[len("minecraft:"):]
    else:
        return None
    if ty not in STAT_TYPES:
        return None
    key = identifier_by_separator(name[colon + 1:], ".")
    if key is None:
        raise InvalidIdentifier(name)
    if ty == "mined":
        known = (not reg.blocks) or (key in reg.blocks)
    elif ty in ("crafted", "used", "broken", "picked_up", "dropped"):
        known = (not reg.items) or (key in reg.items)
    elif ty in ("killed", "killed_by"):
        known = (not reg.entity_types) or (key in reg.entity_types)
    elif ty == "custom":
        k = key[len("minecraft:"):] if key.startswith("minecraft:") else None
        known = k is not None and k in CUSTOM_STATS
    else:
        known = False
    return stat_criteria(ty, key) if known else None


def criteria_exists(name: str, reg: Any) -> bool:
    """Находит ли `ObjectiveCriteria.byName` критерий."""
    try:
        return criteria_by_name(name, reg) is not None
    except InvalidIdentifier:
        return False


def criteria_read_only(name: str) -> bool:
    """`ObjectiveCriteria.isReadOnly`."""
    return name in (
        CRITERIA_HEALTH,
        CRITERIA_FOOD,
        CRITERIA_AIR,
        CRITERIA_ARMOR,
        CRITERIA_XP,
        CRITERIA_LEVEL,
    )


def criteria_render_type(name: str) -> RenderType:
    """`ObjectiveCriteria.getDefaultRenderType`."""
    return RenderType.Hearts if name == CRITERIA_HEALTH else RenderType.Integer


def stat_criteria(stat_type: str, key: str) -> str:
    """`Stat.buildName`: критерий, считающий статистику."""
    t = stat_type[len("minecraft:"):] if stat_type.startswith("minecraft:") else stat_type
    return "minecraft.{}:{}".format(t, key.replace(":", "."))


# ── display slots ────────────────────────────────────────────────────────
SLOT_LIST = "list"
SLOT_SIDEBAR = "sidebar"
SLOT_BELOW_NAME = "below_name"


def display_slots() -> List[str]:
    """Все имена `DisplaySlot` в порядке id."""
    v = [SLOT_LIST, SLOT_SIDEBAR, SLOT_BELOW_NAME]
    v.extend("sidebar.team." + c for c in team_colors())
    return v


def display_slot_valid(name: str) -> bool:
    """Есть ли такой `DisplaySlot`."""
    return name in display_slots()


# ── teams ──────────────────────────────────────────────────────────────────
class Visibility(Enum):
    """`Visibility`: видимость ников/смертей в команде."""

    Always = "always"
    Never = "never"
    HideForOtherTeams = "hideForOtherTeams"
    HideForOwnTeam = "hideForOwnTeam"

    def name(self) -> str:
        return self.value

    @staticmethod
    def by_name(n: str) -> Optional["Visibility"]:
        for v in Visibility:
            if v.value == n:
                return v
        return None

    def display_name(self) -> Text:
        return Text.translate("team.visibility." + self.value, [])


class CollisionRule(Enum):
    """`CollisionRule`: правила столкновений в команде."""

    Always = "always"
    Never = "never"
    PushOtherTeams = "pushOtherTeams"
    PushOwnTeam = "pushOwnTeam"

    def name(self) -> str:
        return self.value

    @staticmethod
    def by_name(n: str) -> Optional["CollisionRule"]:
        for v in CollisionRule:
            if v.value == n:
                return v
        return None

    def display_name(self) -> Text:
        return Text.translate("team.collision." + self.value, [])


@dataclass
class Team:
    """`PlayerTeam`: команда табло."""

    name: str
    display_name: Comp
    color: Optional[str] = None
    allow_friendly_fire: bool = True
    see_friendly_invisibles: bool = True
    prefix: Comp = ""
    suffix: Comp = ""
    nametag_visibility: Visibility = Visibility.Always
    death_message_visibility: Visibility = Visibility.Always
    collision_rule: CollisionRule = CollisionRule.Always
    # `Sets.newHashSet()`, в порядке вставки.
    players: List[str] = field(default_factory=list)

    @staticmethod
    def create(name: str) -> "Team":
        """`PlayerTeam::new`."""
        return Team(
            name=name,
            display_name=literal(name),
            color=None,
            allow_friendly_fire=True,
            see_friendly_invisibles=True,
            prefix=literal(""),
            suffix=literal(""),
            nametag_visibility=Visibility.Always,
            death_message_visibility=Visibility.Always,
            collision_rule=CollisionRule.Always,
            players=[],
        )

    def apply_color(self, t: Text) -> Text:
        if self.color is not None:
            rgb = team_color_rgb(self.color)
            if rgb is not None:
                return t.with_color(rgb)
        return t

    def formatted_display_name(self) -> Text:
        """`PlayerTeam.getFormattedDisplayName`."""
        inner = hover_name(comp_text(self.display_name), self.name)
        return self.apply_color(bracketed(inner))

    def formatted_name(self, member: Text) -> Text:
        """`PlayerTeam.getFormattedName`: префикс, имя и суффикс в цвете команды."""
        t = Text.empty()
        t.push(comp_text(self.prefix))
        t.push(member)
        t.push(comp_text(self.suffix))
        return self.apply_color(t)

    def formatted_name_comp(self, member: Comp) -> Comp:
        """`PlayerTeam.getFormattedName` как компонент."""
        c: Dict[str, Any] = {
            "text": "",
            "extra": [self.prefix, member, self.suffix],
        }
        if self.color is not None:
            c["color"] = self.color
        return c


# ── team rules in gameplay ──────────────────────────────────────────────────
def teams_allied(own: Optional[Team], other: Optional[Team]) -> bool:
    """`Team.isAlliedTo`: обе на одной команде."""
    return (
        own is not None
        and other is not None
        and own.name == other.name
    )


def teams_allow_damage(own: Optional[Team], other: Optional[Team]) -> bool:
    """`Entity.doTeamsAllowDamage`: союзники без friendly fire не бьют друг друга."""
    if own is None:
        return True
    return (not teams_allied(own, other)) or own.allow_friendly_fire


def pushable_by(own: Optional[Team], their: Optional[Team], their_pushable: bool) -> bool:
    """`EntitySelector.pushableBy`: толкает ли `their` `own`."""
    own_rule = own.collision_rule if own is not None else CollisionRule.Always
    if own_rule == CollisionRule.Never or not their_pushable:
        return False
    their_rule = their.collision_rule if their is not None else CollisionRule.Always
    if their_rule == CollisionRule.Never:
        return False
    same = teams_allied(own, their)
    if (own_rule == CollisionRule.PushOwnTeam or their_rule == CollisionRule.PushOwnTeam) and same:
        return False
    return (
        own_rule != CollisionRule.PushOtherTeams
        and their_rule != CollisionRule.PushOtherTeams
    ) or same


def invisible_to(
    own: Optional[Team],
    viewer: Optional[Team],
    viewer_spectator: bool,
    invisible: bool,
) -> bool:
    """`Entity.isInvisibleTo(player)`: невидим, если зритель не наблюдает и не
    делит команду, видящую невидимых союзников."""
    if viewer_spectator:
        return False
    if own is not None and teams_allied(own, viewer) and own.see_friendly_invisibles:
        return False
    return invisible


def team_shows_name(
    own: Optional[Team],
    viewer: Optional[Team],
    visible_to_viewer: bool,
) -> Optional[bool]:
    """`LivingEntityRenderer.shouldShowName` — решение команды, либо None."""
    t = own
    if t is None:
        return None
    if t.nametag_visibility == Visibility.Always:
        return visible_to_viewer
    if t.nametag_visibility == Visibility.Never:
        return False
    if t.nametag_visibility == Visibility.HideForOtherTeams:
        if viewer is None:
            return visible_to_viewer
        return teams_allied(own, viewer) and (t.see_friendly_invisibles or visible_to_viewer)
    # HideForOwnTeam
    if viewer is None:
        return visible_to_viewer
    return (not teams_allied(own, viewer)) and visible_to_viewer


@dataclass
class NameView:
    """Что `LivingEntityRenderer.shouldShowName` спрашивает о сущности."""

    discrete: bool = False
    distance_sqr: float = 0.0
    invisible_to_viewer: bool = False
    hud_hidden: bool = False
    is_camera: bool = False
    is_vehicle: bool = False


def name_shown(own: Optional[Team], viewer: Optional[Team], v: NameView) -> bool:
    """`LivingEntityRenderer.shouldShowName`."""
    if v.discrete and v.distance_sqr >= 1024.0:
        return False
    visible = not v.invisible_to_viewer
    shown = team_shows_name(own, viewer, visible)
    if shown is not None:
        return shown
    return (not v.hud_hidden) and (not v.is_camera) and visible and (not v.is_vehicle)


def death_message_reaches(board: "Scoreboard", dying: str, other: str) -> bool:
    """`ServerPlayer.die`: слышит ли `other` сообщение о смерти `dying`."""
    team = board.players_team(dying)
    if team is None:
        return True
    same_team = False
    ot = board.players_team(other)
    if ot is not None and ot.name == team.name:
        same_team = True
    if team.death_message_visibility == Visibility.Always:
        return True
    if team.death_message_visibility == Visibility.Never:
        return False
    if team.death_message_visibility == Visibility.HideForOtherTeams:
        return same_team and other != dying
    return not same_team


# ── objectives and scores ───────────────────────────────────────────────────
@dataclass
class Objective:
    """`Objective`: цель табло."""

    name: str
    criteria: str
    display_name: Comp
    render_type: RenderType
    display_auto_update: bool
    number_format: Optional[NumberFormat] = None

    def formatted_display_name(self) -> Text:
        """`Objective.getFormattedDisplayName`."""
        return bracketed(hover_name(comp_text(self.display_name), self.name))

    def display_text(self) -> Text:
        return comp_text(self.display_name)

    def format_or_default(self, default: NumberFormat) -> NumberFormat:
        return self.number_format if self.number_format is not None else default


@dataclass
class Score:
    """`Score`: счёт владельца по цели."""

    value: int = 0
    locked: bool = True
    display: Optional[Comp] = None
    number_format: Optional[NumberFormat] = None


@dataclass
class ScoreEntry:
    """Одна строка цели (`PlayerScoreEntry`)."""

    owner: str
    value: int
    display: Optional[Comp]
    number_format: Optional[NumberFormat]

    def is_hidden(self) -> bool:
        return self.owner.startswith("#")

    def owner_name(self) -> Text:
        if self.display is not None:
            return comp_text(self.display)
        return Text.literal(self.owner)

    def format_value(self, default: NumberFormat) -> Text:
        fmt = self.number_format if self.number_format is not None else default
        return fmt.format(self.value)


@dataclass
class Scoreboard:
    """`Scoreboard`: цели, счета, слоты и команды в порядке вставки."""

    # `objectivesByName` (`getObjectives()`), имя → цель.
    objectives: Dict[str, Objective] = field(default_factory=dict)
    # `objectivesByCriteria`: критерий → имена целей в порядке создания.
    by_criteria: Dict[str, List[str]] = field(default_factory=dict)
    # `playerScores`: владелец → (цель → счёт). Владелец остаётся учтённым,
    # даже когда его последняя цель удалена.
    scores: Dict[str, Dict[str, Score]] = field(default_factory=dict)
    # `displaySlots`: слот → имя цели.
    display: Dict[str, str] = field(default_factory=dict)
    # `teamsByName` (`getPlayerTeams()`), имя → команда.
    teams: Dict[str, Team] = field(default_factory=dict)
    # `teamsByPlayer`: владелец → имя команды.
    team_of: Dict[str, str] = field(default_factory=dict)

    # ── цели ──────────────────────────────────────────────────────────
    def objective(self, name: str) -> Optional[Objective]:
        return self.objectives.get(name)

    def objective_mut(self, name: str) -> Optional[Objective]:
        return self.objectives.get(name)

    def objectives_streamed(self) -> List[Objective]:
        """`getObjectives().stream()` (что использует сохранение)."""
        return list(self.objectives.values())

    def add_objective(
        self,
        name: str,
        criteria: str,
        display_name: Comp,
        render_type: RenderType = RenderType.Integer,
        display_auto_update: bool = False,
        number_format: Optional[NumberFormat] = None,
    ) -> bool:
        """`addObjective`: False, если цель уже есть."""
        if self.objective(name) is not None:
            return False
        self.objectives[name] = Objective(
            name=name,
            criteria=criteria,
            display_name=display_name,
            render_type=render_type,
            display_auto_update=display_auto_update,
            number_format=number_format,
        )
        self.by_criteria.setdefault(criteria, []).append(name)
        return True

    def remove_objective(self, name: str) -> None:
        """`removeObjective`: владельцы без счетов остаются учтёнными."""
        obj = self.objective(name)
        if obj is None:
            return
        criteria = obj.criteria
        del self.objectives[name]
        self.display = {s: o for s, o in self.display.items() if o != name}
        lst = self.by_criteria.get(criteria)
        if lst is not None:
            self.by_criteria[criteria] = [n for n in lst if n != name]
        for per in self.scores.values():
            per.pop(name, None)

    def display_objective(self, slot: str) -> Optional[Objective]:
        o = self.display.get(slot)
        return self.objective(o) if o is not None else None

    def set_display_objective(self, slot: str, objective: Optional[str]) -> None:
        """`setDisplayObjective`: None снимает слот."""
        if objective is not None:
            self.display[slot] = objective
        else:
            self.display.pop(slot, None)

    # ── счета ─────────────────────────────────────────────────────────
    def score(self, holder: str, objective: str) -> Optional[Score]:
        per = self.scores.get(holder)
        return per.get(objective) if per is not None else None

    def score_mut(self, holder: str, objective: str) -> Score:
        """`getOrCreatePlayerScore`: новый счёт — заблокирован и равен нулю."""
        per = self.scores.get(holder)
        if per is None:
            per = {}
            self.scores[holder] = per
        s = per.get(objective)
        if s is None:
            s = Score()
            per[objective] = s
        return s

    def get(self, holder: str, objective: str) -> int:
        return self.score_mut(holder, objective).value

    def set_with(
        self,
        holder: str,
        objective: str,
        value: int,
        display: Optional[Comp],
    ) -> None:
        """`ScoreAccess.set`; `display` — имя владельца, которое цель с
        автообновлением копирует в счёт."""
        o = self.objective(objective)
        auto = o is not None and o.display_auto_update
        s = self.score_mut(holder, objective)
        if auto and display is not None:
            cur = canonical_component(s.display) if s.display is not None else None
            if cur != canonical_component(display):
                s.display = copy.deepcopy(display)
        s.value = value

    def set(self, holder: str, objective: str, value: int) -> None:
        self.set_with(holder, objective, value, None)

    def add(self, holder: str, objective: str, amount: int) -> int:
        v = _wrap_i32(self.get(holder, objective) + amount)
        self.set(holder, objective, v)
        return v

    def for_all_objectives(
        self, criteria: str, holder: str, f: Callable[[int], int]
    ) -> None:
        """`forAllObjectives`: изменить счёт во всех целях с этим критерием."""
        self.for_all_objectives_with(criteria, holder, None, f)

    def for_all_objectives_with(
        self,
        criteria: str,
        holder: str,
        display: Optional[Comp],
        f: Callable[[int], int],
    ) -> None:
        names = list(self.by_criteria.get(criteria, []))
        for n in names:
            v = f(self.get(holder, n))
            self.set_with(holder, n, v, display)

    def has_objectives_for(self, criteria: str) -> bool:
        lst = self.by_criteria.get(criteria)
        return lst is not None and len(lst) > 0

    def reset_all(self, holder: str) -> None:
        """`resetAllPlayerScores`."""
        if holder in self.scores:
            del self.scores[holder]

    def reset_one(self, holder: str, objective: str) -> None:
        """`resetSinglePlayerScore`: владелец без счетов забывается."""
        per = self.scores.get(holder)
        if per is None:
            return
        per.pop(objective, None)
        if not per:
            self.reset_all(holder)

    def list_scores(self, objective: str) -> List[ScoreEntry]:
        """`listPlayerScores(objective)` в порядке `playerScores.forEach`."""
        out: List[ScoreEntry] = []
        for owner, per in self.scores.items():
            s = per.get(objective)
            if s is None:
                continue
            out.append(
                ScoreEntry(
                    owner=owner,
                    value=s.value,
                    display=s.display,
                    number_format=s.number_format,
                )
            )
        return out

    def holder_scores(self, holder: str) -> List[Tuple[Objective, int]]:
        """Счета владельца как (цель, значение) в порядке целей."""
        per = self.scores.get(holder)
        if per is None:
            return []
        out: List[Tuple[Objective, int]] = []
        for o in self.objectives.values():
            s = per.get(o.name)
            if s is not None:
                out.append((o, s.value))
        return out

    def tracked(self) -> List[str]:
        """`getTrackedPlayers` (`playerScores.keySet().stream()`)."""
        return list(self.scores.keys())

    def team_members(self) -> Iterator[str]:
        """Каждый владелец в команде (`teamsByPlayer.keySet()`)."""
        return iter(self.team_of.keys())

    # ── команды ───────────────────────────────────────────────────────
    def team(self, name: str) -> Optional[Team]:
        return self.teams.get(name)

    def team_mut(self, name: str) -> Optional[Team]:
        return self.teams.get(name)

    def add_team(self, name: str) -> Team:
        """`addPlayerTeam`: создаёт команду, если её нет."""
        if self.team(name) is None:
            self.teams[name] = Team.create(name)
        return self.teams[name]

    def teams_streamed(self) -> List[Team]:
        """`getPlayerTeams().stream()` (что использует сохранение)."""
        return list(self.teams.values())

    def remove_team(self, name: str) -> None:
        """`removePlayerTeam`: участники теряют команду."""
        team = self.teams.get(name)
        if team is None:
            return
        del self.teams[name]
        for p in team.players:
            self.team_of.pop(p, None)

    def players_team(self, player: str) -> Optional[Team]:
        return self.team(self.team_of[player]) if player in self.team_of else None

    def add_to_team(self, player: str, team: str) -> bool:
        """`addPlayerToTeam`: сначала покидает старую команду (даже ту же
        самую); False, если команды нет."""
        self.remove_from_team(player)
        self.team_of[player] = team
        t = self.team_mut(team)
        if t is None:
            return False
        if player in t.players:
            return False
        t.players.append(player)
        return True

    def remove_from_team(self, player: str) -> bool:
        team = self.team_of.pop(player, None)
        if team is None:
            return False
        t = self.team_mut(team)
        if t is not None and player in t.players:
            t.players.remove(player)
        return True

    def allied(self, a: str, b: str) -> bool:
        """`Team.isAlliedTo` для двух имён-владельцев."""
        x = self.team_of.get(a)
        y = self.team_of.get(b)
        if x is not None and y is not None:
            return x == y
        return False

    def entity_removed(self, holder: str) -> None:
        """`Scoreboard.entityRemoved` для мёртвой сущности не-игрока."""
        self.reset_all(holder)
        self.remove_from_team(holder)

    # ── saved data ────────────────────────────────────────────────────
    def pack(self) -> Tag:
        """`ScoreboardSaveData.Packed.CODEC` кодирование: поля, равные
        дефолту кодекa, опускаются."""
        objectives: List[Tag] = []
        for o in self.objectives_streamed():
            pairs: List[Tuple[str, Tag]] = [
                ("Name", Tag(TagType.String, str_val=o.name)),
                ("DisplayName", component_tag(o.display_name)),
            ]
            if o.criteria != CRITERIA_DUMMY:
                pairs.append(("CriteriaName", Tag(TagType.String, str_val=o.criteria)))
            if o.render_type != RenderType.Integer:
                pairs.append(("RenderType", Tag(TagType.String, str_val=o.render_type.id())))
            if o.display_auto_update:
                pairs.append(("display_auto_update", Tag(TagType.Byte, byte_val=1)))
            if o.number_format is not None:
                pairs.append(("format", o.number_format.to_tag()))
            objectives.append(_compound(pairs))

        scores: List[Tag] = []
        for owner, per in self.scores.items():
            for o in self.objectives_streamed():
                s = per.get(o.name)
                if s is None:
                    continue
                pairs = [
                    ("Name", Tag(TagType.String, str_val=owner)),
                    ("Objective", Tag(TagType.String, str_val=o.name)),
                ]
                if s.value != 0:
                    pairs.append(("Score", Tag(TagType.Int, int_val=s.value)))
                if s.locked:
                    pairs.append(("Locked", Tag(TagType.Byte, byte_val=1)))
                if s.display is not None:
                    pairs.append(("display", component_tag(s.display)))
                if s.number_format is not None:
                    pairs.append(("format", s.number_format.to_tag()))
                scores.append(_compound(pairs))

        slot_pairs: List[Tuple[str, Tag]] = []
        for slot in display_slots():
            o = self.display.get(slot)
            if o is None:
                continue
            if self.objective(o) is None:
                continue
            slot_pairs.append((slot, Tag(TagType.String, str_val=o)))

        teams: List[Tag] = []
        for t in self.teams_streamed():
            pairs = [
                ("Name", Tag(TagType.String, str_val=t.name)),
                ("DisplayName", component_tag(t.display_name)),
            ]
            if t.color is not None:
                pairs.append(("TeamColor", Tag(TagType.String, str_val=t.color)))
            if not t.allow_friendly_fire:
                pairs.append(("AllowFriendlyFire", Tag(TagType.Byte, byte_val=0)))
            if not t.see_friendly_invisibles:
                pairs.append(("SeeFriendlyInvisibles", Tag(TagType.Byte, byte_val=0)))
            empty = ""
            if canonical_component(t.prefix) != empty:
                pairs.append(("MemberNamePrefix", component_tag(t.prefix)))
            if canonical_component(t.suffix) != empty:
                pairs.append(("MemberNameSuffix", component_tag(t.suffix)))
            if t.nametag_visibility != Visibility.Always:
                pairs.append(
                    ("NameTagVisibility", Tag(TagType.String, str_val=t.nametag_visibility.name()))
                )
            if t.death_message_visibility != Visibility.Always:
                pairs.append(
                    (
                        "DeathMessageVisibility",
                        Tag(TagType.String, str_val=t.death_message_visibility.name()),
                    )
                )
            if t.collision_rule != CollisionRule.Always:
                pairs.append(
                    ("CollisionRule", Tag(TagType.String, str_val=t.collision_rule.name()))
                )
            if t.players:
                pairs.append(
                    (
                        "Players",
                        Tag(
                            TagType.List,
                            list_val=[Tag(TagType.String, str_val=p) for p in t.players],
                        ),
                    )
                )
            teams.append(_compound(pairs))

        entries: List[Tuple[str, Tag]] = []
        if objectives:
            entries.append(("Objectives", Tag(TagType.List, list_val=objectives)))
        if scores:
            entries.append(("PlayerScores", Tag(TagType.List, list_val=scores)))
        if slot_pairs:
            entries.append(("DisplaySlots", _compound(slot_pairs)))
        if teams:
            entries.append(("Teams", Tag(TagType.List, list_val=teams)))
        return _compound(entries)

    @staticmethod
    def unpack(data: Tag) -> "Scoreboard":
        """`ServerScoreboard.load` декодированных сохранённых данных."""
        sb = Scoreboard()

        def data_list(k: str) -> List[Tag]:
            t = _get_tag(data, k)
            if isinstance(t, Tag) and t.tag_type == TagType.List and t.list_val is not None:
                return list(t.list_val)
            return []

        for o in data_list("Objectives"):
            name = string_of(_get_tag(o, "Name"))
            if name is None:
                continue
            criteria = string_of(_get_tag(o, "CriteriaName"))
            if criteria is None:
                criteria = "dummy"
            dn_tag = _get_tag(o, "DisplayName")
            display_name = literal(name) if dn_tag is None else tag_to_json(dn_tag)
            fmt_tag = _get_tag(o, "format")
            sb.add_objective(
                name,
                criteria,
                display_name,
                RenderType.by_id(string_of(_get_tag(o, "RenderType")) or ""),
                bool_of(_get_tag(o, "display_auto_update"), False),
                NumberFormat.from_tag(fmt_tag) if fmt_tag is not None else None,
            )

        for s in data_list("PlayerScores"):
            owner = string_of(_get_tag(s, "Name"))
            obj = string_of(_get_tag(s, "Objective"))
            if owner is None or obj is None:
                continue
            if sb.objective(obj) is None:
                continue
            disp_tag = _get_tag(s, "display")
            fmt_tag = _get_tag(s, "format")
            sb.score_mut(owner, obj).value = int_of(_get_tag(s, "Score")) or 0
            sb.score_mut(owner, obj).locked = bool_of(_get_tag(s, "Locked"), False)
            sb.score_mut(owner, obj).display = tag_to_json(disp_tag) if disp_tag is not None else None
            sb.score_mut(owner, obj).number_format = (
                NumberFormat.from_tag(fmt_tag) if fmt_tag is not None else None
            )

        slots_tag = _get_tag(data, "DisplaySlots")
        if (
            isinstance(slots_tag, Tag)
            and slots_tag.tag_type == TagType.Compound
            and slots_tag.compound_val is not None
        ):
            for k, v in slots_tag.compound_val.items():
                if isinstance(v, Tag) and v.tag_type == TagType.String and display_slot_valid(k):
                    o = v.str_val if v.str_val is not None else ""
                    if sb.objective(o) is not None:
                        sb.display[k] = o

        for t in data_list("Teams"):
            name = string_of(_get_tag(t, "Name"))
            if name is None:
                continue
            team = sb.add_team(name)
            dn = _get_tag(t, "DisplayName")
            if dn is not None:
                team.display_name = tag_to_json(dn)
            color = string_of(_get_tag(t, "TeamColor"))
            team.color = color if color is not None and team_color_rgb(color) is not None else None
            team.allow_friendly_fire = bool_of(_get_tag(t, "AllowFriendlyFire"), True)
            team.see_friendly_invisibles = bool_of(_get_tag(t, "SeeFriendlyInvisibles"), True)
            pref = _get_tag(t, "MemberNamePrefix")
            team.prefix = literal("") if pref is None else tag_to_json(pref)
            suff = _get_tag(t, "MemberNameSuffix")
            team.suffix = literal("") if suff is None else tag_to_json(suff)
            v = string_of(_get_tag(t, "NameTagVisibility"))
            team.nametag_visibility = Visibility.by_name(v) if v is not None else Visibility.Always
            team.nametag_visibility = team.nametag_visibility or Visibility.Always
            v = string_of(_get_tag(t, "DeathMessageVisibility"))
            team.death_message_visibility = (
                Visibility.by_name(v) if v is not None else Visibility.Always
            )
            team.death_message_visibility = team.death_message_visibility or Visibility.Always
            v = string_of(_get_tag(t, "CollisionRule"))
            team.collision_rule = (
                CollisionRule.by_name(v) if v is not None else CollisionRule.Always
            )
            team.collision_rule = team.collision_rule or CollisionRule.Always
            players_tag = _get_tag(t, "Players")
            if (
                isinstance(players_tag, Tag)
                and players_tag.tag_type == TagType.List
                and players_tag.list_val is not None
            ):
                for p in players_tag.list_val:
                    if isinstance(p, Tag) and p.tag_type == TagType.String:
                        sb.add_to_team(p.str_val if p.str_val is not None else "", name)
        return sb

    # Алиасы в терминах задачи (Rust: `pack`/`unpack`).
    to_nbt = pack
    from_nbt = unpack


# ── ComponentSerialization / UUID ───────────────────────────────────────────
def uuid_from_text(s: str) -> Optional[List[int]]:
    """`UUIDUtil.CODEC`: каноническая строка → четыре int (big-endian).

    FALLBACK: `uuid.rs` не портирован — только эта функция.
    """
    hexchars: List[str] = []
    for ch in s:
        if ch == "-":
            continue
        if ch not in "0123456789abcdefABCDEF":
            return None
        hexchars.append(ch)
        if len(hexchars) > 32:
            return None
    if len(hexchars) != 32:
        return None
    h = "".join(hexchars)
    return [_to_i32(int(h[i * 8:i * 8 + 8], 16)) for i in range(4)]


def component_tag(c: Comp) -> Tag:
    """Компонент как его пишет `ComponentSerialization.CODEC` в NBT."""
    tag = json_to_tag(canonical_component(c))
    entity_uuids(tag)
    return tag


def entity_uuids(tag: Tag) -> None:
    """`HoverEvent.ShowEntity` пишет UUID через `UUIDUtil.CODEC`: int-массив."""
    if tag.tag_type == TagType.Compound:
        cv = tag.compound_val
        if cv is None:
            return
        action = cv.get("action")
        show_entity = (
            isinstance(action, Tag)
            and action.tag_type == TagType.String
            and (action.str_val or "") == "show_entity"
        )
        for k, v in list(cv.items()):
            if show_entity and k == "uuid":
                ints: Optional[List[int]] = None
                if isinstance(v, Tag) and v.tag_type == TagType.List and v.list_val is not None:
                    vals: List[int] = []
                    ok = True
                    for t in v.list_val:
                        if isinstance(t, Tag) and t.tag_type == TagType.Int:
                            vals.append(int(t.int_val or 0))
                        else:
                            ok = False
                            break
                    ints = vals if ok else None
                elif isinstance(v, Tag) and v.tag_type == TagType.String:
                    ints = uuid_from_text(v.str_val or "")
                if ints is not None and len(ints) == 4:
                    cv[k] = Tag(TagType.IntArray, intarray_val=ints)
            else:
                entity_uuids(v)
    elif tag.tag_type == TagType.List and tag.list_val is not None:
        for e in tag.list_val:
            entity_uuids(e)


# ── каноническая форма компонента/стиля ────────────────────────────────────
def canonical_style(style: Any) -> Any:
    """Стиль-объект как его перекодирует `Style.Serializer.MAP_CODEC`."""
    node, _ = _decompose(style)
    node.pop("text", None)
    return dict(node)


def canonical_component(c: Comp) -> Comp:
    """Компонент как vanilla декодирует и перекодирует (`ComponentSerialization`)."""
    node, extra = _decompose(c)
    return _finish(node, extra)


def _decompose(c: Comp) -> Tuple[Dict[str, Any], List[Comp]]:
    """Собственные поля компонента (содержимое и стиль) и его сиблинги."""
    if isinstance(c, list) and c:
        node, extra = _decompose(c[0])
        extra.extend(canonical_component(x) for x in c[1:])
        node.pop("extra", None)
        return node, extra
    if isinstance(c, dict):
        node: Dict[str, Any] = {}
        extra: List[Comp] = []
        for k, v in c.items():
            if k == "type":
                continue
            if k == "extra":
                if isinstance(v, list):
                    extra.extend(canonical_component(x) for x in v)
            elif k in ("bold", "italic", "underlined", "strikethrough", "obfuscated"):
                if isinstance(v, bool):
                    b = v
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    b = int(v) != 0
                else:
                    continue
                node[k] = b
            elif k == "color":
                if isinstance(v, str):
                    if v.startswith("#"):
                        rgb = hex_color(v)
                        node[k] = "#{:06X}".format(rgb) if rgb is not None else v
                    else:
                        node[k] = v
            elif k == "with":
                if isinstance(v, list):
                    node[k] = [
                        canonical_component(a) if isinstance(a, (dict, list)) else a
                        for a in v
                    ]
            elif k == "separator":
                node[k] = canonical_component(v)
            elif k == "hover_event":
                h = copy.deepcopy(v)
                if isinstance(h, dict) and "value" in h and h.get("action") == "show_text":
                    h["value"] = canonical_component(h["value"])
                node[k] = h
            else:
                node[k] = v
        return node, extra
    if isinstance(c, str):
        return {"text": c}, []
    return {"text": _value_to_string(c)}, []


def _finish(node: Dict[str, Any], extra: List[Comp]) -> Comp:
    if not extra and len(node) == 1 and isinstance(node.get("text"), str):
        return node["text"]
    if extra:
        node["extra"] = extra
    return dict(node)


# ── death message args ──────────────────────────────────────────────────────
def death_message_args(
    key: str,
    victim: Text,
    cause: Text,
    item: Optional[Text],
) -> Tuple[str, List[Text]]:
    """`DamageSource.getLocalizedDeathMessage`: причина с предметом и своим
    именем получает сообщение `<id>.item` с именем предмета третьим аргументом."""
    if item is not None:
        return key + ".item", [victim, cause, item]
    return key, [victim, cause]
