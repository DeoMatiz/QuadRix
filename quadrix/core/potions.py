# Порт horizon-client-core/src/potions.rs → quadrix/core/potions.py.
#
# Это НЕ компонент `PotionContents` и не таблица рецептов варки, а две
# вандаловые таблицы кода (ported as tables):
#   * `MobEffects`  — цвет и категория каждого эффекта (`EFFECTS`);
#   * `Potions`     — id, суффикс имени и эффекты каждого зелья (`POTIONS`);
# плюс цвет смеси эффектов (`PotionContents.getColor`). Рецептов варки
# (`PotionBrewing`) в этом файле нет — их тут не портируем.
#
# `mod_effects`/`register_mod_effects` повторяют `OnceLock`: список эффектов
# модов задаётся один раз за процесс, повторный вызов возвращает False.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "Category",
    "EffectDef",
    "PotionDef",
    "EFFECTS",
    "POTIONS",
    "BASE_POTION_COLOR",
    "effect",
    "all_effects",
    "mod_effects",
    "register_mod_effects",
    "is_mod_effect",
    "description_id",
    "sprite",
    "push_sprite",
    "namespaced",
    "potion",
    "potion_color",
    "effects_color",
]


class Category(Enum):
    """`Category` (potions.rs:7): польза / вред / нейтрально."""

    Beneficial = "beneficial"
    Harmful = "harmful"
    Neutral = "neutral"


# Локальные псевдонимы, как в Rust `use Category::{Beneficial as B, ...}`.
B = Category.Beneficial
H = Category.Harmful
N = Category.Neutral


@dataclass(frozen=True)
class EffectDef:
    """`EffectDef` (potions.rs:15): id, цвет, категория, мгновенный ли."""

    id: str
    color: int
    category: Category
    instant: bool = False


@dataclass(frozen=True)
class PotionDef:
    """`PotionDef` (potions.rs:183): id, суффикс имени и эффекты.

    Эффекты — кортежи `(effect_id, duration, amplifier)` (тики).
    """

    id: str
    name: str
    effects: Tuple[Tuple[str, int, int], ...]


def _fx(id: str, color: int, category: Category) -> EffectDef:
    """`fx` (potions.rs:21): обычный (не мгновенный) эффект."""
    return EffectDef(id=id, color=color, category=category, instant=False)


def _p(id: str, name: str, effects: Sequence[Tuple[str, int, int]]) -> PotionDef:
    """`p` (potions.rs:188): зелье."""
    return PotionDef(id=id, name=name, effects=tuple(effects))


# `MobEffects` в порядке регистрации (potions.rs:31..87).
EFFECTS: Tuple[EffectDef, ...] = (
    _fx("speed", 3402751, B),
    _fx("slowness", 9154528, H),
    _fx("haste", 14270531, B),
    _fx("mining_fatigue", 4866583, H),
    _fx("strength", 16762624, B),
    EffectDef(id="instant_health", color=16262179, category=B, instant=True),
    EffectDef(id="instant_damage", color=11101546, category=H, instant=True),
    _fx("jump_boost", 16646020, B),
    _fx("nausea", 5578058, H),
    _fx("regeneration", 13458603, B),
    _fx("resistance", 9520880, B),
    _fx("fire_resistance", 16750848, B),
    _fx("water_breathing", 10017472, B),
    _fx("invisibility", 16185078, B),
    _fx("blindness", 2039587, H),
    _fx("night_vision", 12779366, B),
    _fx("hunger", 5797459, H),
    _fx("weakness", 4738376, H),
    _fx("poison", 8889187, H),
    _fx("wither", 7561558, H),
    _fx("health_boost", 16284963, B),
    _fx("absorption", 2445989, B),
    EffectDef(id="saturation", color=16262179, category=B, instant=True),
    _fx("glowing", 9740385, N),
    _fx("levitation", 13565951, H),
    _fx("luck", 5882118, B),
    _fx("unluck", 12624973, H),
    _fx("slow_falling", 15978425, B),
    _fx("conduit_power", 1950417, B),
    _fx("dolphins_grace", 8954814, B),
    _fx("bad_omen", 745784, N),
    _fx("hero_of_the_village", 4521796, B),
    _fx("darkness", 2696993, H),
    _fx("trial_omen", 1484454, N),
    _fx("raid_omen", 14565464, N),
    _fx("wind_charged", 12438015, H),
    _fx("weaving", 7891290, H),
    _fx("oozing", 10092451, H),
    _fx("infested", 9214860, H),
    _fx("breath_of_the_nautilus", 65518, B),
)

# Эффекты модов, регистрируемые после вандаловых. `OnceLock` — задаётся один раз.
_MOD_EFFECTS: Optional[List[EffectDef]] = None


def register_mod_effects(
    effects: Iterable[Tuple[str, int, Category]],
) -> bool:
    """`register_mod_effects` (potions.rs:93): зарегистрировать эффекты модов.

    Список задаётся один раз за процесс: при повторном вызове вернёт False,
    а эффекты останутся от первого вызова до перезапуска игры.
    """
    global _MOD_EFFECTS
    if _MOD_EFFECTS is not None:
        return False
    defs: List[EffectDef] = []
    for id, color, category in effects:
        if ":" not in id:
            raise AssertionError(f"{id} has no namespace")
        defs.append(_fx(id, color, category))
    _MOD_EFFECTS = defs
    return True


def mod_effects() -> List[EffectDef]:
    """`mod_effects` (potions.rs:107): эффекты модов в порядке регистрации."""
    return _MOD_EFFECTS if _MOD_EFFECTS is not None else []


def all_effects() -> List[EffectDef]:
    """`all_effects` (potions.rs:111): вандаловы, затем эффекты модов."""
    return list(EFFECTS) + mod_effects()


def effect(id: str) -> Optional[EffectDef]:
    """`effect` (potions.rs:114): вандалов эффект по id (с/без minecraft:)."""
    short = id[len("minecraft:"):] if id.startswith("minecraft:") else id
    for e in EFFECTS:
        if e.id == short:
            return e
    # Холодный путь: эффект мода.
    for e in mod_effects():
        if e.id == id:
            return e
    return None


def is_mod_effect(id: str) -> bool:
    """`is_mod_effect` (potions.rs:124): `<ns>:<path>`, не вандалов."""
    return not id.startswith("minecraft:") and ":" in id


def description_id(id: str) -> str:
    """`description_id` (potions.rs:135): `effect.<ns>.<path>` (`/` → `.`)."""
    ns, sep, path = id.partition(":")
    if not sep:
        ns, path = "minecraft", id
    return f"effect.{ns}.{path.replace('/', '.')}"


def push_sprite(out: List[str], id: str) -> None:
    """`push_sprite` (potions.rs:148): дописать `mob_effect/<path>` в `out`."""
    ns, sep, path = id.partition(":")
    if not sep:
        path = id
    elif ns == "minecraft":
        pass
    else:
        out.append(f"{ns}:")
    out.append("mob_effect/")
    out.append(path)


def sprite(id: str) -> str:
    """`sprite` (potions.rs:142): спрайт эффекта в атласе GUI."""
    out: List[str] = []
    push_sprite(out, id)
    return "".join(out)


def namespaced(id: str) -> str:
    """`namespaced` (potions.rs:162): `<ns>:<path>` для хранилища эффектов.

    Для вандалова id (с/без `minecraft:`) добавляется префикс `minecraft:`;
    id мода уже содержит namespace и возвращается как есть.
    """
    key = id[len("minecraft:"):] if id.startswith("minecraft:") else id
    for e in EFFECTS:
        if e.id == key:
            return f"minecraft:{e.id}"
    return id


# `Potions` в порядке регистрации (potions.rs:196..291).
POTIONS: Tuple[PotionDef, ...] = (
    _p("water", "water", ()),
    _p("mundane", "mundane", ()),
    _p("thick", "thick", ()),
    _p("awkward", "awkward", ()),
    _p("night_vision", "night_vision", (("night_vision", 3600, 0),)),
    _p("long_night_vision", "night_vision", (("night_vision", 9600, 0),)),
    _p("invisibility", "invisibility", (("invisibility", 3600, 0),)),
    _p("long_invisibility", "invisibility", (("invisibility", 9600, 0),)),
    _p("leaping", "leaping", (("jump_boost", 3600, 0),)),
    _p("long_leaping", "leaping", (("jump_boost", 9600, 0),)),
    _p("strong_leaping", "leaping", (("jump_boost", 1800, 1),)),
    _p("fire_resistance", "fire_resistance", (("fire_resistance", 3600, 0),)),
    _p("long_fire_resistance", "fire_resistance",
       (("fire_resistance", 9600, 0),)),
    _p("swiftness", "swiftness", (("speed", 3600, 0),)),
    _p("long_swiftness", "swiftness", (("speed", 9600, 0),)),
    _p("strong_swiftness", "swiftness", (("speed", 1800, 1),)),
    _p("slowness", "slowness", (("slowness", 1800, 0),)),
    _p("long_slowness", "slowness", (("slowness", 4800, 0),)),
    _p("strong_slowness", "slowness", (("slowness", 400, 3),)),
    _p("turtle_master", "turtle_master",
       (("slowness", 400, 3), ("resistance", 400, 2))),
    _p("long_turtle_master", "turtle_master",
       (("slowness", 800, 3), ("resistance", 800, 2))),
    _p("strong_turtle_master", "turtle_master",
       (("slowness", 400, 5), ("resistance", 400, 3))),
    _p("water_breathing", "water_breathing", (("water_breathing", 3600, 0),)),
    _p("long_water_breathing", "water_breathing",
       (("water_breathing", 9600, 0),)),
    _p("healing", "healing", (("instant_health", 1, 0),)),
    _p("strong_healing", "healing", (("instant_health", 1, 1),)),
    _p("harming", "harming", (("instant_damage", 1, 0),)),
    _p("strong_harming", "harming", (("instant_damage", 1, 1),)),
    _p("poison", "poison", (("poison", 900, 0),)),
    _p("long_poison", "poison", (("poison", 1800, 0),)),
    _p("strong_poison", "poison", (("poison", 432, 1),)),
    _p("regeneration", "regeneration", (("regeneration", 900, 0),)),
    _p("long_regeneration", "regeneration", (("regeneration", 1800, 0),)),
    _p("strong_regeneration", "regeneration", (("regeneration", 450, 1),)),
    _p("strength", "strength", (("strength", 3600, 0),)),
    _p("long_strength", "strength", (("strength", 9600, 0),)),
    _p("strong_strength", "strength", (("strength", 1800, 1),)),
    _p("weakness", "weakness", (("weakness", 1800, 0),)),
    _p("long_weakness", "weakness", (("weakness", 4800, 0),)),
    _p("luck", "luck", (("luck", 6000, 0),)),
    _p("slow_falling", "slow_falling", (("slow_falling", 1800, 0),)),
    _p("long_slow_falling", "slow_falling", (("slow_falling", 4800, 0),)),
    _p("wind_charged", "wind_charged", (("wind_charged", 3600, 0),)),
    _p("weaving", "weaving", (("weaving", 3600, 0),)),
    _p("oozing", "oozing", (("oozing", 3600, 0),)),
    _p("infested", "infested", (("infested", 3600, 0),)),
)


def potion(id: str) -> Optional[PotionDef]:
    """`potion` (potions.rs:292): зелье по id (с/без `minecraft:`)."""
    short = id[len("minecraft:"):] if id.startswith("minecraft:") else id
    for p in POTIONS:
        if p.id == short:
            return p
    return None


# `PotionContents.BASE_POTION_COLOR` (ARGB -13083194) как RGB (potions.rs:297).
BASE_POTION_COLOR: int = 0x385DC6


def potion_color(id: Optional[str]) -> int:
    """`potion_color` (potions.rs:299): цвет зелья по id (смесь эффектов).

    Для неизвестного/отсутствующего id — базовый цвет зелья.
    """
    def_ = potion(id) if id is not None else None
    if def_ is None:
        return BASE_POTION_COLOR
    return effects_color((eid, amp) for eid, _dur, amp in def_.effects)


def effects_color(effects: Iterable[Tuple[str, int]]) -> int:
    """`effects_color` (potions.rs:307): смесь цветов видимых эффектов.

    Каждый цвет взвешен `amplifier + 1`, каналы усреднены целочисленным
    делением; пустой/неизвестный набор — базовый цвет зелья.
    """
    r = g = b = 0
    total = 0
    for eid, amp in effects:
        e = effect(eid)
        if e is None:
            continue
        w = amp + 1
        r += w * (e.color >> 16 & 255)
        g += w * (e.color >> 8 & 255)
        b += w * (e.color & 255)
        total += w
    if total == 0:
        return BASE_POTION_COLOR
    return ((r // total) << 16) | ((g // total) << 8) | (b // total)
