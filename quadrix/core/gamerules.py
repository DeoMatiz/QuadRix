# Порт horizon-client-core/src/gamerules.rs (Minecraft 26.3).
#
# `GameRules` — зарегистрированные игровые правила (категория, тип, дефолт и
# границы), карта текущих значений и сохранение в world-файл
# `data/minecraft/game_rules.dat` (gzip + named NBT).
#
# ВАЖНО (сверено с Rust):
#   * имена правил в 26.3 — snake_case (`keep_inventory`, `advance_time`,
#     `random_tick_speed`), НЕ camelCase (`keepInventory`, `doDaylightCycle`);
#   * в NBT значения — Byte (0/1) для Bool и Int для Int, НЕ строки
#     "true"/"false" (вопреки расхожему представлению о vanilla);
#   * `to_nbt` в Rust возвращает NamedTag; здесь (в nbt.py нет NamedTag)
#     возвращается корневой `Tag`-компаунд `{data: {...}, DataVersion}`,
#     а `from_nbt` принимает либо `Tag`, либо dict (мост к read_nbt).

from __future__ import annotations

import gzip
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from quadrix.world.nbt import Tag, TagType, read_nbt
from quadrix.world.registry import DATA_VERSION

__all__ = [
    "Value",
    "Rule",
    "RULES",
    "MAX_MINECART_SPEED",
    "MINECART_IMPROVEMENTS",
    "available_rules",
    "rule",
    "GameRules",
    "I32_MAX",
]

# `i32::MAX` — верхняя граница правил в Rust.
I32_MAX = 2147483647


# ── значение правила ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Value:
    """`Value`: `Bool(bool) | Int(i32)`.

    Конструкторы `Value.Bool(...)` / `Value.Int(...)` повторяют
    `Value::Bool`/`Value::Int` из Rust.
    """

    kind: str  # "bool" | "int"
    value: Union[bool, int]

    @staticmethod
    def Bool(b: bool) -> "Value":
        return Value("bool", bool(b))

    @staticmethod
    def Int(i: int) -> "Value":
        return Value("int", int(i))

    @property
    def is_bool(self) -> bool:
        return self.kind == "bool"

    @property
    def is_int(self) -> bool:
        return self.kind == "int"

    def __str__(self) -> str:
        """`impl Display for Value`."""
        return str(self.value)


# ── метаданные правила ──────────────────────────────────────────────────
@dataclass(frozen=True)
class Rule:
    """`Rule`: имя, категория, дефолт и границы."""

    name: str
    category: str
    default: Value
    min: int
    max: int


def _b(name: str, category: str, default: bool) -> Rule:
    """Rust `const fn b(...)`."""
    return Rule(name, category, Value.Bool(default), 0, 0)


def _i(name: str, category: str, default: int, min_: int, max_: int) -> Rule:
    """Rust `const fn i(...)`."""
    return Rule(name, category, Value.Int(default), min_, max_)


# Все правила без экспериментальных функций, в порядке регистрации.
RULES: List[Rule] = [
    _b("advance_time", "updates", True),
    _b("advance_weather", "updates", True),
    _b("allow_entering_nether_using_portals", "misc", True),
    _b("block_drops", "drops", True),
    _b("block_explosion_drop_decay", "drops", True),
    _b("command_blocks_work", "misc", True),
    _b("command_block_output", "chat", True),
    _b("drowning_damage", "player", True),
    _b("elytra_movement_check", "player", True),
    _b("ender_pearls_vanish_on_death", "player", True),
    _b("entity_drops", "drops", True),
    _b("fall_damage", "player", True),
    _b("fire_damage", "player", True),
    _i("fire_spread_radius_around_player", "updates", 128, -1, I32_MAX),
    _b("forgive_dead_players", "mobs", True),
    _b("freeze_damage", "player", True),
    _b("global_sound_events", "misc", True),
    _b("immediate_respawn", "player", False),
    _b("keep_inventory", "player", False),
    _b("lava_source_conversion", "updates", False),
    _b("limited_crafting", "player", False),
    _b("locator_bar", "player", True),
    _b("log_admin_commands", "chat", True),
    _i("max_block_modifications", "misc", 32768, 1, I32_MAX),
    _i("max_command_forks", "misc", 65536, 0, I32_MAX),
    _i("max_command_sequence_length", "misc", 65536, 0, I32_MAX),
    _i("max_entity_cramming", "mobs", 24, 0, I32_MAX),
    _i("max_snow_accumulation_height", "updates", 1, 0, 8),
    _b("mob_drops", "drops", True),
    _b("mob_explosion_drop_decay", "drops", True),
    _b("mob_griefing", "mobs", True),
    _b("natural_health_regeneration", "player", True),
    _b("player_movement_check", "player", True),
    _i("players_nether_portal_creative_delay", "player", 0, 0, I32_MAX),
    _i("players_nether_portal_default_delay", "player", 80, 0, I32_MAX),
    _i("players_sleeping_percentage", "player", 100, 0, I32_MAX),
    _b("projectiles_can_break_blocks", "drops", True),
    _b("pvp", "player", True),
    _b("raids", "mobs", True),
    _i("random_tick_speed", "updates", 3, 0, I32_MAX),
    _b("reduced_debug_info", "misc", False),
    _i("respawn_radius", "player", 10, 0, I32_MAX),
    _b("send_command_feedback", "chat", True),
    _b("show_advancement_messages", "chat", True),
    _b("show_death_messages", "chat", True),
    _b("spawner_blocks_work", "misc", True),
    _b("spawn_mobs", "spawning", True),
    _b("spawn_monsters", "spawning", True),
    _b("spawn_patrols", "spawning", True),
    _b("spawn_phantoms", "spawning", True),
    _b("spawn_wandering_traders", "spawning", True),
    _b("spawn_wardens", "spawning", True),
    _b("spectators_generate_chunks", "player", True),
    _b("spread_vines", "updates", True),
    _b("tnt_explodes", "misc", True),
    _b("tnt_explosion_drop_decay", "drops", False),
    _b("universal_anger", "mobs", False),
    _b("water_source_conversion", "updates", True),
]

# GameRules.MAX_MINECART_SPEED (26.3), доступно с minecart improvements.
MAX_MINECART_SPEED: Rule = _i("max_minecart_speed", "misc", 8, 1, 1000)
MINECART_IMPROVEMENTS: str = "minecraft:minecart_improvements"


def available_rules(minecart_improvements: bool) -> List[Rule]:
    """Все доступные правила; при minecart improvements добавляется
    `max_minecart_speed`."""
    if minecart_improvements:
        return list(RULES) + [MAX_MINECART_SPEED]
    return list(RULES)


def rule(name: str) -> Optional[Rule]:
    """Найти правило по имени (префикс `minecraft:` срезается)."""
    if name.startswith("minecraft:"):
        name = name[len("minecraft:"):]
    for r in available_rules(True):
        if r.name == name:
            return r
    return None


_INT_RE = re.compile(r"[+-]?[0-9]+\Z")


def _parse_bool(text: str) -> Optional[bool]:
    """`bool::from_str`: только `true`/`false`."""
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _parse_i32(text: str) -> Optional[int]:
    """`i32::from_str`: знак + цифры, без пробелов, в пределах i32."""
    if not _INT_RE.match(text):
        return None
    value = int(text)
    if -2147483648 <= value <= I32_MAX:
        return value
    return None


def _compound_of(root: object) -> Dict[str, Tag]:
    """Достать компаунд: `Tag`-компаунд или готовый dict (мост к read_nbt)."""
    if isinstance(root, Tag):
        return root.compound_val or {}
    if isinstance(root, dict):
        return root
    return {}


# ── карта текущих значений ──────────────────────────────────────────────
@dataclass
class GameRules:
    """`GameRules`: текущие значения (дефолты, если не заданы)."""

    values: Dict[str, Value] = field(default_factory=dict)
    minecart_improvements: bool = False

    # ── функции ─────────────────────────────────────────────────────────
    @classmethod
    def with_features(cls, features: List[str]) -> "GameRules":
        """`with_features`: включить minecart improvements, если функция есть."""
        return cls(
            values={},
            minecart_improvements=any(f == MINECART_IMPROVEMENTS for f in features),
        )

    def copy_with_features(self, features: List[str]) -> "GameRules":
        """`GameRules.copy(enabledFeatures)`: сохранить доступные значения,
        добавить дефолты новых правил и отбросить отсутствующие."""
        rules = GameRules.with_features(features)
        for name, value in self.values.items():
            rules.set(name, value)
        return rules

    def available_rules(self) -> List[Rule]:
        return available_rules(self.minecart_improvements)

    def get(self, name: str) -> Optional[Value]:
        """Значение правила или None, если правило неизвестно/недоступно."""
        r = rule(name)
        if r is None:
            return None
        if r.name == MAX_MINECART_SPEED.name and not self.minecart_improvements:
            return None
        return self.values.get(r.name, r.default)

    def bool(self, name: str) -> bool:
        v = self.get(name)
        return v is not None and v.is_bool and bool(v.value)

    def set_string(self, name: str, text: str) -> bool:
        """Разобрать сетевое значение правила, сохранив проверку типа и
        диапазона."""
        current = self.get(name)
        if current is None:
            return False
        if current.is_bool:
            parsed = _parse_bool(text)
            if parsed is None:
                return False
            value = Value.Bool(parsed)
        else:
            parsed = _parse_i32(text)
            if parsed is None:
                return False
            value = Value.Int(parsed)
        return self.set(name, value)

    def int(self, name: str) -> int:
        v = self.get(name)
        if v is not None and v.is_int:
            return int(v.value)
        return 0

    def set(self, name: str, value: Value) -> bool:
        """Установить правило; False, если имя или тип значения неверны."""
        r = rule(name)
        if r is None or self.get(r.name) is None:
            return False
        if r.default.is_bool and value.is_bool:
            ok = True
        elif r.default.is_int and value.is_int:
            ok = r.min <= int(value.value) <= r.max
        else:
            ok = False
        if ok and value == r.default:
            self.values.pop(r.name, None)
        elif ok:
            self.values[r.name] = value
        return ok

    def by_name(self) -> Dict[str, int]:
        """Значение каждого правила по имени без namespace (bool как 0/1),
        как их держит `save::Level`."""
        out: Dict[str, int] = {}
        for r in self.available_rules():
            v = self.values.get(r.name, r.default)
            out[r.name] = int(v.value) if v.is_int else (1 if v.value else 0)
        return out

    # ── NBT ─────────────────────────────────────────────────────────────
    def to_nbt(self) -> Tag:
        """Кодек GameRuleMap: `{data: {"minecraft:<rule>": value}, DataVersion}`.

        В Rust возвращается NamedTag; здесь — корневой `Tag`-компаунд.
        """
        data: Dict[str, Tag] = {}
        for r in self.available_rules():
            v = self.values.get(r.name, r.default)
            if v.is_bool:
                data["minecraft:" + r.name] = Tag(
                    TagType.Byte, byte_val=1 if v.value else 0
                )
            else:
                data["minecraft:" + r.name] = Tag(
                    TagType.Int, int_val=int(v.value)
                )
        return Tag(
            TagType.Compound,
            compound_val={
                "data": Tag(TagType.Compound, compound_val=data),
                "DataVersion": Tag(TagType.Int, int_val=DATA_VERSION),
            },
        )

    @classmethod
    def from_nbt(cls, root: object) -> "GameRules":
        return cls.from_nbt_with_features(root, [])

    @classmethod
    def from_nbt_with_features(cls, root: object, features: List[str]) -> "GameRules":
        rules = GameRules.with_features(features)
        root_map = _compound_of(root)
        data = _compound_of(root_map.get("data"))
        for r in rules.available_rules():
            key = "minecraft:" + r.name
            value = data.get(key)
            if value is None:
                value = data.get(r.name)
            if r.default.is_bool:
                if value is not None and value.tag_type == TagType.Byte:
                    rules.set(r.name, Value.Bool((value.byte_val or 0) != 0))
            else:
                if value is not None and value.tag_type == TagType.Int:
                    rules.set(r.name, Value.Int(value.int_val or 0))
        return rules

    # ── файл мира ───────────────────────────────────────────────────────
    @classmethod
    def load(cls, world: Path) -> "GameRules":
        return cls.load_with_features(world, [])

    @classmethod
    def load_with_features(cls, world: Path, features: List[str]) -> "GameRules":
        """Прочитать `data/minecraft/game_rules.dat`; при любой ошибке —
        значения по умолчанию с заданными функциями."""
        path = Path(world) / "data" / "minecraft" / "game_rules.dat"
        try:
            raw = gzip.decompress(path.read_bytes())
            root = read_nbt(raw)
        except OSError:
            return cls.with_features(features)
        except Exception:  # noqa: BLE001 — как Rust `Err(_) => with_features`
            return cls.with_features(features)
        return cls.from_nbt_with_features(root, features)

    def save(self, world: Path) -> None:
        """Записать `data/minecraft/game_rules.dat` (gzip + named NBT)."""
        directory = Path(world) / "data" / "minecraft"
        directory.mkdir(parents=True, exist_ok=True)
        payload = self.to_nbt().compound_val or {}
        data = _encode_nbt_root(payload)
        (directory / "game_rules.dat").write_bytes(gzip.compress(data))


# ── локальный NBT-энкодер ───────────────────────────────────────────────
# FALLBACK: nbt.write_named — вложенный Compound кодируется неверно (пишет
# лишний type-byte + count-префикс перед полями), из-за чего read_nbt не
# может прочитать собственные bytes. Правка nbt.py запрещена, поэтому
# запись делаем сами. Чтение — через штатный read_nbt (его reader корректен:
# поля Compound = [type, name, payload]... до 0x00). Формат ровно как
# `write_named` из nbt.py, только без ошибочного префикса.
def _encode_payload(tag: Tag) -> bytes:
    """Payload тега без type-byte и имени (Byte/Int/Compound)."""
    if tag.is_byte:
        return struct.pack(">b", int(tag.byte_val or 0))
    if tag.is_int:
        return struct.pack(">i", int(tag.int_val or 0))
    if tag.is_compound:
        out = bytearray()
        for name, value in sorted((tag.compound_val or {}).items()):
            out += _encode_entry(name, value)
        out += b"\x00"
        return bytes(out)
    raise ValueError(f"[QuadRix] cannot encode NBT tag type {tag.tag_type}")


def _encode_entry(name: str, tag: Tag) -> bytes:
    """Запись одного поля: [type][u16 len][имя][payload]."""
    name_bytes = name.encode("utf-8")
    return (
        struct.pack(">BH", int(tag.tag_type), len(name_bytes))
        + name_bytes
        + _encode_payload(tag)
    )


def _encode_nbt_root(compound: Dict[str, Tag]) -> bytes:
    """Файловый корень NBT: [0x0a][пустое имя][поля][0x00]."""
    out = bytearray(struct.pack(">BH", TagType.Compound, 0))
    for name, value in sorted(compound.items()):
        out += _encode_entry(name, value)
    out += b"\x00"
    return bytes(out)
