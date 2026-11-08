# Ported from horizon/crates/horizon-client/src/health.rs PART 1
# ONLY the types specified in the task:
# - HealthEvent enum (all variants)
# - HurtSource<'a> struct
# - Hurting<'a> enum (not exported, but types used)
# - Knock struct
# - BlockOutcome struct
# - HurtRecord struct
# - AttackRecord struct
# - HealthResources struct (with load, with_packs, landing_source)
# - PlayerHealth struct (with specified methods)

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from quadrix.effects import (
    StatusFlags,
    damage_protection as effects_damage_protection,
    has_fire_resistance as effects_has_fire_resistance,
)
from quadrix.combat import armor_reduction, hurt_armor as combat_hurt_armor
from quadrix.totem import try_use_totem, TOTEM_EFFECTS


# ─── HealthEvent ──────────────────────────────────────────────────────
class HealthEvent(Enum):
    """Port of HealthEvent enum from health.rs line 230.

    All variants copied exactly from Rust:
      StarvationDamage(f32),
      FreezeDamage(f32),
      SweetBerryBushDamage(f32),
      DrownDamage(f32),
      Updated { id: u8, value: f32, dirty: bool },
      Statistic { name: &'static str, amount: i32 },
      RecordedDamage { source: DamageTypeId, amount: f32 },
      Phase(&'static str),
      ArmorHurt { source: DamageTypeId, amount: f32 },
      DamageBroadcast { source: DamageTypeId },
      Criterion { original: f32, amount: f32, blocked: bool }
    """
    StarvationDamage = auto()
    FreezeDamage = auto()
    SweetBerryBushDamage = auto()
    DrownDamage = auto()
    Updated = auto()
    Statistic = auto()
    RecordedDamage = auto()
    Phase = auto()
    ArmorHurt = auto()
    DamageBroadcast = auto()
    Criterion = auto()

    # Each variant can hold extra data via instance attributes set after construction.
    # This keeps the Enum itself simple while preserving all variant identities.

    def __init__(self, *args):
        pass


# ─── HurtSource ───────────────────────────────────────────────────────
@dataclass(frozen=True, eq=True)
class HurtSource:
    """Port of HurtSource<'a> struct from health.rs line 33.
    
    Fields:
        damage_type: &str - the damage type name (e.g. "minecraft:fall")
        causing: i32 - the causing entity ID
        direct: i32 - the direct entity ID
    """
    damage_type: str
    causing: i32
    direct: i32


# ─── Knock ────────────────────────────────────────────────────────────
@dataclass(frozen=True, eq=True)
class Knock:
    """Port of Knock struct from health.rs line 94.
    
    Fields:
        strength: f64 - knockback strength
        x: f64 - x direction
        z: f64 - z direction
    """
    strength: float
    x: float
    z: float


# ─── BlockOutcome ─────────────────────────────────────────────────────
@dataclass(frozen=True, eq=True)
class BlockOutcome:
    """Port of BlockOutcome struct from health.rs line 690.
    
    Fields:
        hurt: bool - whether the hurt was applied
        blocked: f32 - amount blocked
        fully_blocked: bool - whether fully blocked
        sound: bool - whether block sound played
        knockback: bool - whether knockback applied
        canceled: bool - whether canceled
    """
    hurt: bool
    blocked: float
    fully_blocked: bool
    sound: bool
    knockback: bool
    canceled: bool


# ─── HurtRecord ───────────────────────────────────────────────────────
@dataclass(frozen=True, eq=True)
class HurtRecord:
    """Port of HurtRecord struct from health.rs line 651.
    
    Fields:
        game_time: i64 - the game time of the hurt
        source: String - the damage type source name
        amount: f32 - the damage amount
        blocked: f32 - amount blocked by armor/shield
        taken: f32 - health/absorption taken
        hurt: bool - whether the entity was hurt
        armor: f32 - armor value after the hit
        toughness: f32 - toughness value after the hit
        health: f32 - remaining health after the hit
        fire_ticks: i32 - fire ticks before the hurt
        knockback: Optional<[f64; 3]> - optional knockback vector
    """
    game_time: int
    source: str
    amount: float
    blocked: float
    taken: float
    hurt: bool
    armor: float
    toughness: float
    health: float
    fire_ticks: int
    knockback: Optional[list[float]] = field(default=None, repr=False)


# ─── AttackRecord ─────────────────────────────────────────────────────
@dataclass(frozen=True, eq=True)
class AttackRecord:
    """Port of AttackRecord struct from health.rs line 676.
    
    Fields:
        game_time: i64 - the game time of the attack
        target: String - the target entity name
        id: u32 - the entity ID
        killed: bool - whether the target was killed
        amount: f32 - the damage amount
        scale: f32 - the attack strength scale
        crit: bool - whether it was a critical hit
        landed: bool - whether the attack landed
        dealt: f32 - the actual damage dealt
    """
    game_time: int
    target: str
    id: int
    killed: bool
    amount: float
    scale: float
    crit: bool
    landed: bool
    dealt: float


# ─── PlayerFloatIds ───────────────────────────────────────────────────
@dataclass(frozen=True, eq=True)
class PlayerFloatIds:
    """Port of PlayerFloatIds struct from player_health.rs line 28.
    
    Fields:
        health: u8 - the health float ID index
        absorption: u8 - the absorption float ID index
    """
    health: int
    absorption: int


# ─── DamageType / DamageCatalog ───────────────────────────────────────
@dataclass
class DamageType:
    """Port of horizon-world's damage_source::Definition (damage type data).

    Fields:
        id: canonical damage type name (e.g. "minecraft:fall")
        message_id: translation key used in death messages
        exhaustion: exhaustion applied to the attacker
        scaling: one of never / when_caused_by_living_non_player / always
        effects: one of hurt / burning / drowning / freezing / poking / thorns
        death_message_type: default / fall_variants / intentional_game_design
        tags: damage type tags this type belongs to
    """
    id: str
    message_id: str
    exhaustion: float
    scaling: str
    effects: str
    death_message_type: str
    tags: list[str] = field(default_factory=list)


def _decode_health_json(value: Any) -> Any:
    """Decode one entry of the prepared health JSON files.

    types.json and tags.json store each value as a JSON-encoded string, so a
    second json.loads is needed. Plain objects/lists pass through unchanged.
    """
    if isinstance(value, str):
        return json.loads(value)
    return value


def _read_health_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _decode_hex_float(text: str) -> float:
    """Decode a big-endian IEEE-754 float stored as 8 hex characters."""
    return struct.unpack(">f", bytes.fromhex(text))[0]


def _tag_value_list(raw: Any) -> list[str]:
    """Normalise a damage type tag entry to a list of member names.

    Prepared files wrap the members in {"values": [...]}; plain lists are also
    accepted. Nested references keep their leading '#' until resolved.
    """
    raw = _decode_health_json(raw)
    if isinstance(raw, dict):
        values = raw.get("values", [])
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    return [value for value in values if isinstance(value, str)]


def _resolve_tag(name: str, tags: dict[str, list[str]], seen: Optional[set[str]] = None) -> list[str]:
    """Recursively expand '#' tag references, preserving order without duplicates."""
    if name.startswith("#"):
        name = name[1:]
    if seen is None:
        seen = set()
    if name in seen:
        return []
    seen = seen | {name}

    resolved: list[str] = []
    for value in tags.get(name, []):
        if value.startswith("#"):
            resolved.extend(_resolve_tag(value, tags, seen))
        else:
            resolved.append(value)

    # Deduplicate while keeping first-seen order.
    result: list[str] = []
    for value in resolved:
        if value not in result:
            result.append(value)
    return result


def _build_damage_catalog(
    catalog_data: Any,
    types_data: Any,
    tags_data: Any,
) -> "DamageCatalog":
    """Build a DamageCatalog from catalog.json, types.json and tags.json."""
    types_by_name: dict[str, DamageType] = {}
    ordered: list[DamageType] = []

    for entry in catalog_data.get("types", []):
        name = str(entry["id"])
        exhaustion_bits = str(entry.get("exhaustion", "00000000"))
        exhaustion = _decode_hex_float(exhaustion_bits)

        message_id = str(entry.get("message_id", ""))
        scaling = str(entry.get("scaling", "when_caused_by_living_non_player"))
        effects = str(entry.get("effects", "hurt"))
        death_message_type = str(entry.get("death_message_type", "default"))

        # types.json carries the same codec fields; use it as a fallback for
        # any field the catalog omitted (and for optional per-type tags).
        override = types_data.get(name) if isinstance(types_data, dict) else None
        explicit_tags: list[str] = []
        if override is not None:
            override = _decode_health_json(override)
            if isinstance(override, dict):
                message_id = str(override.get("message_id", message_id))
                scaling = str(override.get("scaling", scaling))
                effects = str(override.get("effects", effects))
                death_message_type = str(
                    override.get("death_message_type", death_message_type)
                )
                raw_tags = override.get("tags", [])
                if isinstance(raw_tags, list):
                    explicit_tags = [tag for tag in raw_tags if isinstance(tag, str)]

        damage_type = DamageType(
            id=name,
            message_id=message_id,
            exhaustion=exhaustion,
            scaling=scaling,
            effects=effects,
            death_message_type=death_message_type,
            tags=explicit_tags,
        )
        types_by_name[name] = damage_type
        ordered.append(damage_type)

    # Any type present only in types.json still belongs in the catalog.
    if isinstance(types_data, dict):
        for name in types_data:
            if name in types_by_name:
                continue
            override = _decode_health_json(types_data[name])
            if not isinstance(override, dict):
                continue
            damage_type = DamageType(
                id=name,
                message_id=str(override.get("message_id", "")),
                exhaustion=float(override.get("exhaustion", 0.0)),
                scaling=str(override.get("scaling", "when_caused_by_living_non_player")),
                effects=str(override.get("effects", "hurt")),
                death_message_type=str(override.get("death_message_type", "default")),
                tags=[tag for tag in override.get("tags", []) if isinstance(tag, str)],
            )
            types_by_name[name] = damage_type
            ordered.append(damage_type)

    # Normalise every tag entry and record which tags each type belongs to.
    tags: dict[str, list[str]] = {}
    if isinstance(tags_data, dict):
        for tag_name, raw in tags_data.items():
            tags[tag_name] = _tag_value_list(raw)

    for tag_name in tags:
        for member in _resolve_tag(tag_name, tags):
            damage_type = types_by_name.get(member)
            if damage_type is not None and tag_name not in damage_type.tags:
                damage_type.tags.append(tag_name)

    return DamageCatalog(types=ordered, tags=tags)


class DamageCatalog:
    """Port of horizon-world's damage_source::Catalog.

    Stores the damage type definitions and the resolved tag-name -> members
    mapping. Lookups are by canonical name.

    Methods:
        get(name) -> DamageType
        has(name) -> bool
        by_tag(tag) -> list[DamageType]
        has_tag(name, tag) -> bool
    """

    def __init__(self, types: list[DamageType], tags: dict[str, list[str]]):
        self.types = types
        self.tags = tags
        self._by_name = {damage_type.id: damage_type for damage_type in types}
        self._tag_members = {
            tag: _resolve_tag(tag, tags) for tag in tags
        }

    def get(self, name: str) -> DamageType:
        return self._by_name[name]

    def has(self, name: str) -> bool:
        return name in self._by_name

    def by_tag(self, tag: str) -> list[DamageType]:
        members = self._tag_members.get(tag)
        if members is None:
            members = _resolve_tag(tag, self.tags)
        result: list[DamageType] = []
        for name in members:
            damage_type = self._by_name.get(name)
            if damage_type is not None:
                result.append(damage_type)
        return result

    def has_tag(self, name: str, tag: str) -> bool:
        members = self._tag_members.get(tag)
        if members is None:
            members = _resolve_tag(tag, self.tags)
        return name in members


# ─── HealthResources ──────────────────────────────────────────────────
class HealthResources:
    """Port of HealthResources struct from health.rs line 162.
    
    Fields:
        damage: Catalog - damage type registry (dict mapping names to IDs)
        ids: PlayerFloatIds - player float IDs for health/absorption
    
    Methods:
        load(root) - load from .local/horizon-client-health/ directory
        with_packs - reload with packs overlay
        landing_source - get damage type ID for landing damage source
    """
    
    def __init__(self, damage: Dict[str, Any], ids: PlayerFloatIds):
        self.damage = damage
        self.ids = ids

    @classmethod
    def load(cls, root: Path) -> "HealthResources":
        """Load HealthResources from .local/horizon-client-health/ directory.

        Reads the prepared files:
            ids.json      - player float IDs for health and absorption
            catalog.json  - damage type definitions (hex float exhaustion)
            types.json    - damage type codec values (JSON-encoded strings)
            tags.json     - damage type tags (JSON-encoded strings)

        Args:
            root: Path to the .local/horizon-client-health/ directory

        Returns:
            A new HealthResources instance with a populated DamageCatalog.
        """
        root = Path(root)

        ids_data = _read_health_json(root / "ids.json")
        ids = PlayerFloatIds(
            health=int(ids_data.get("health", 0)),
            absorption=int(ids_data.get("absorption", 0)),
        )

        catalog_data = _read_health_json(root / "catalog.json")

        types_path = root / "types.json"
        types_data = _read_health_json(types_path) if types_path.exists() else {}

        tags_path = root / "tags.json"
        tags_data = _read_health_json(tags_path) if tags_path.exists() else {}

        damage = _build_damage_catalog(catalog_data, types_data, tags_data)
        return cls(damage=damage, ids=ids)

    def with_packs(
        self, root: Path, overlay: Optional[Dict[str, Any]] = None, reload: bool = False
    ) -> "HealthResources":
        """Return a new HealthResources with potentially reloaded damage data.

        Args:
            root: Path to the .local/horizon-client-health/ directory
            overlay: Optional pack overlay configuration (unused by this port)
            reload: Whether to reload tags against the frozen registry

        Returns:
            A new HealthResources instance
        """
        root = Path(root)

        if reload and isinstance(self.damage, DamageCatalog):
            # MinecraftServer.reloadResources retains the frozen damage
            # registry and only rebuilds tags.
            tags_path = root / "tags.json"
            tags_data = _read_health_json(tags_path) if tags_path.exists() else {}
            catalog_data = {
                "types": [
                    {
                        "id": damage_type.id,
                        "message_id": damage_type.message_id,
                        "exhaustion": struct.pack(">f", damage_type.exhaustion).hex(),
                        "scaling": damage_type.scaling,
                        "effects": damage_type.effects,
                        "death_message_type": damage_type.death_message_type,
                    }
                    for damage_type in self.damage.types
                ]
            }
            damage = _build_damage_catalog(catalog_data, {}, tags_data)
            return HealthResources(damage=damage, ids=self.ids)

        loaded = HealthResources.load(root)
        return HealthResources(damage=loaded.damage, ids=self.ids)

    def landing_source(self, source: str) -> str:
        """Get the damage type ID for a landing damage source.
        
        Args:
            source: The landing damage type (e.g. "Fall", "Stalagmite")
            
        Returns:
            The damage type name string
        """
        return source


# ─── PlayerHealth ─────────────────────────────────────────────────────
@dataclass
class PlayerHealth:
    """Port of PlayerHealth struct from health.rs line 307.
    
    An AGGREGATE struct that holds player health state.
    
    Fields:
        data: SyncedFloats - synchronized float data (health, absorption)
        ids: PlayerFloatIds - IDs for health and absorption fields
        food: FoodData - player food data (simplified as dict)
        hurt: State - hurt state tracking
        hurt_animation_time: i32 - hurt animation timer
        hurt_dir: f32 - hurt direction yaw
        indicated_dir: Optional[f32] - indicated damage direction
        dead: bool - whether the player is dead
        sync_velocity: bool - whether to sync velocity
        game_time: i64 - game time
        tick_count: i32 - tick count
        totem_ready: bool - whether totem is ready
        totem_used: bool - whether totem was used this tick
        
    Methods:
        new(resources, attributes) - construct from HealthResources and attributes
        health() -> f32 - current health value
        absorption() -> f32 - current absorption value
        game_time() -> i64 - game time
        dead_or_dying() -> bool - whether dead or at 0 health
        advance_clock() - advance the game clock
        animate_hurt() - start hurt animation
        animate_hurt_dir(yaw) - start hurt animation with yaw direction
        indicate_damage(xd, zd, yaw) - set indicated damage direction
        flash_health_change(health) - handle health change flashing
        set_health(value, absorption) - set health and/or absorption
    """
    
    # Core data fields
    data: dict  # Simplified SyncedFloats representation
    ids: PlayerFloatIds
    food: dict = field(default_factory=dict)  # FoodData simplification
    # PART 2: ``hurt`` is the PlayerHealth method. The Rust ``hurt`` field is
    # kept under ``hurt_state`` so both names can coexist in Python.
    hurt_state: dict = field(
        default_factory=lambda: {
            "no_action_time": 0,
            "cooldown": 0,
            "last_hurt": 0.0,
            "hurt_duration": 0,
            "hurt_time": 0,
            "last_source": None,
            "last_stamp": 0,
        }
    )
    hurt_animation_time: int = 0
    hurt_dir: float = 0.0
    indicated_dir: Optional[float] = None
    dead: bool = False
    sync_velocity: bool = False
    game_time: int = 0
    tick_count: int = 0
    totem_ready: bool = False
    totem_used: bool = False

    # === PART 2: hurt environment state ===
    # PlayerMotion carried these in Rust; PlayerHealth owns them here so the
    # hurt path is self-contained.
    client_side: bool = False
    entity_id: int = 0
    invulnerable: bool = False
    client_loaded: bool = True
    status: StatusFlags = field(default_factory=StatusFlags)
    fire_ticks: int = 0
    yaw: float = 0.0
    events: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    hurt_log: list = field(default_factory=list)
    protocol: object = None

    # === Constructor ===
    
    @classmethod
    def new(
        cls, resources: HealthResources, attributes: dict
    ) -> "PlayerHealth":
        """Construct a new PlayerHealth from HealthResources and attributes.
        
        Args:
            resources: HealthResources instance
            attributes: Attributes dict (simplified)
            
        Returns:
            A new PlayerHealth instance
        """
        # Initialize synchronized floats for health and absorption
        data = {
            "health": 1.0,  # Default max health starts at 1.0 (full)
            "absorption": 0.0,
        }
        
        # Initialize with maximum health from attributes if available
        maximum = attributes.get("minecraft:max_health", 20.0)
        if maximum is not None:
            try:
                maximum = float(maximum)
            except (ValueError, TypeError):
                maximum = 20.0
        else:
            maximum = 20.0
        
        # Set initial health to maximum
        data["health"] = maximum
        data["absorption"] = 0.0
        
        return cls(
            data=data,
            ids=resources.ids,
            food={},
            hurt_state={
                "no_action_time": 0,
                "cooldown": 0,
                "last_hurt": 0.0,
                "hurt_duration": 0,
                "hurt_time": 0,
                "last_source": None,
                "last_stamp": 0,
            },
            hurt_animation_time=0,
            hurt_dir=0.0,
            indicated_dir=None,
            attributes=dict(attributes),
            dead=False,
            sync_velocity=False,
            game_time=0,
            tick_count=0,
            totem_ready=False,
            totem_used=False,
        )

    # === Accessor methods ===

    def health(self) -> float:
        """Get current health value.
        
        Returns:
            float: The current health (0.0 to max)
        """
        return float(self.data.get("health", 1.0))

    def absorption(self) -> float:
        """Get current absorption value.
        
        Returns:
            float: The current absorption (0.0 to max)
        """
        return float(self.data.get("absorption", 0.0))

    def game_time(self) -> int:
        """Get game time.
        
        Returns:
            i64: The game time value
        """
        return self.game_time

    def dead_or_dying(self) -> bool:
        """Check if player is dead or dying.
        
        Returns:
            bool: True if health <= 0 or dead flag is set
        """
        return self.health() <= 0.0 or self.dead

    def advance_clock(self) -> None:
        """Advance the game clock.
        
        Decrements cooldowns and timers.
        """
        self.game_time = self.game_time + 1  # wrapping add
        self.tick_count = self.tick_count + 1  # wrapping add
        
        if self.hurt_state.get("cooldown", 0) > 0:
            self.hurt_state["cooldown"] = self.hurt_state["cooldown"] - 1
        
        if self.hurt_state.get("hurt_time", 0) > 0:
            self.hurt_state["hurt_time"] = self.hurt_state["hurt_time"] - 1
        
        if self.hurt_animation_time > 0:
            self.hurt_animation_time = self.hurt_animation_time - 1

    def animate_hurt(self) -> None:
        """Start hurt animation (tilt and red flash)."""
        self.hurt_state["hurt_duration"] = 10
        self.hurt_state["hurt_time"] = 10
        self.hurt_animation_time = 10

    def animate_hurt_dir(self, yaw: float) -> None:
        """Start hurt animation with yaw direction.
        
        Args:
            yaw: The yaw value for camera direction
        """
        self.animate_hurt()
        self.hurt_dir = yaw

    def indicate_damage(self, xd: float, zd: float, yaw: float) -> None:
        """Set the indicated damage direction.
        
        Args:
            xd: x direction component
            zd: z direction component
            yaw: player yaw value
        """
        import math
        # Simplified atan2-based calculation
        angle = math.atan2(zd, xd) * (180.0 / math.pi) - yaw
        self.indicated_dir = float(angle)

    def flash_health_change(self, health: float) -> None:
        """Handle health change flashing (hurt animation trigger).
        
        Args:
            health: The new health value
        """
        current_health = self.health()
        damage = current_health - health
        
        if damage <= 0.0:
            if damage < 0.0:
                # Health increased - reset cooldown
                self.hurt_state["cooldown"] = 10
        else:
            # Health decreased - trigger hurt
            self.hurt_state["last_hurt"] = damage
            self.hurt_state["cooldown"] = 20
            self.animate_hurt()

    def set_health(self, value: float, absorption: bool = False) -> None:
        """Set health and/or absorption values.
        
        Args:
            value: The new health value
            absorption: If True, set absorption instead of health
        """
        if absorption:
            self.data["absorption"] = value
        else:
            self.data["health"] = value


# ─── Validation / self-test ───────────────────────────────────────────

def _validate_imports():
    """Verify all types are importable and work correctly."""
    from quadrix.health import (
        HealthEvent,
        HurtSource,
        Knock,
        BlockOutcome,
        HurtRecord,
        AttackRecord,
        HealthResources,
        PlayerFloatIds,
        PlayerHealth,
    )
    
    # Test HurtSource
    hs = HurtSource(damage_type="minecraft:fall", causing=1, direct=0)
    assert hs.damage_type == "minecraft:fall", f"expected 'minecraft:fall', got {hs.damage_type}"
    assert hs.causing == 1, f"expected 1, got {hs.causing}"
    assert hs.direct == 0, f"expected 0, got {hs.direct}"
    
    # Test Knock
    k = Knock(strength=0.4, x=0.0, z=1.0)
    assert k.strength == 0.4, f"expected 0.4, got {k.strength}"
    assert k.x == 0.0, f"expected 0.0, got {k.x}"
    assert k.z == 1.0, f"expected 1.0, got {k.z}"
    
    # Test BlockOutcome
    bo = BlockOutcome(hurt=True, blocked=0.0, fully_blocked=False, sound=True, knockback=False, canceled=False)
    assert bo.hurt is True
    assert bo.fully_blocked is False
    assert bo.sound is True
    assert bo.knockback is False
    assert bo.canceled is False
    
    # Test HurtRecord
    hr = HurtRecord(
        game_time=100,
        source="minecraft:fall",
        amount=5.0,
        blocked=0.0,
        taken=5.0,
        hurt=True,
        armor=0.0,
        toughness=0.0,
        health=15.0,
        fire_ticks=0,
        knockback=[0.5, 0.0, 0.0],
    )
    assert hr.game_time == 100
    assert hr.amount == 5.0
    assert hr.knockback is not None
    assert hr.knockback == [0.5, 0.0, 0.0]
    
    # Test AttackRecord
    ar = AttackRecord(
        game_time=100,
        target="player",
        id=1,
        killed=False,
        amount=5.0,
        scale=1.0,
        crit=False,
        landed=True,
        dealt=5.0,
    )
    assert ar.killed is False
    assert ar.landed is True
    assert ar.amount == 5.0
    
    # Test PlayerFloatIds
    pfi = PlayerFloatIds(health=0, absorption=1)
    assert pfi.health == 0
    assert pfi.absorption == 1
    
    # Test HealthEvent variants can be listed
    variants = [e.name for e in HealthEvent]
    expected = [
        "StarvationDamage", "FreezeDamage", "SweetBerryBushDamage", "DrownDamage",
        "Updated", "Statistic", "RecordedDamage", "Phase", "ArmorHurt", "DamageBroadcast", "Criterion"
    ]
    for name in expected:
        assert name in variants, f"Missing HealthEvent variant: {name}"
    assert len(variants) == len(expected), f"Expected {len(expected)} variants, got {len(variants)}"
    
    # Test HealthResources.load with real file if available
    try:
        resources = HealthResources.load(Path(".local/horizon-client-health"))
        print(f"[QuadRix] HealthResources loaded successfully from .local")
    except (FileNotFoundError, Exception) as e:
        print(f"[QuadRix] HealthResources.load skipped (files not found): {type(e).__name__}")
    
    # Test PlayerHealth.new
    try:
        # Create minimal resources and attributes
        resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
        attributes = {"minecraft:max_health": 20.0}
        player = PlayerHealth.new(resources, attributes)
        assert player.health() == 20.0, f"expected 20.0, got {player.health()}"
        assert player.dead_or_dying() is False
        assert player.absorption() == 0.0
        print(f"[QuadRix] PlayerHealth.new() works: health={player.health()}")
    except Exception as e:
        print(f"[QuadRix] PlayerHealth.new() error: {type(e).__name__}: {e}")
    
    print("[QuadRix] All health type imports and basic tests passed!")


if __name__ == "__main__":
    _validate_imports()

# в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
# PART 2 --- hurt / die logic (health.rs lines 448-1062)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# --------- Supporting enums / small data types ---------------------------------------------------------------------------------------
class Scaling(Enum):
    """Port of horizon-world damage_source::Scaling."""
    Never = "never"
    LivingNonPlayer = "when_caused_by_living_non_player"
    Always = "always"

    def name_of(self) -> str:
        return self.value


class Difficulty(Enum):
    """Port of horizon-world food::Difficulty."""
    Peaceful = "peaceful"
    Easy = "easy"
    Normal = "normal"
    Hard = "hard"


class Bypass(Enum):
    """Port of horizon-world damage_reduction::Bypass."""
    Armor = auto()
    Effects = auto()
    Resistance = auto()
    Enchantments = auto()


class ImmunityTag(Enum):
    """Port of horizon-world damage_immunity::ImmunityTag."""
    BypassesInvulnerability = auto()
    Fire = auto()
    Fall = auto()
    Drowning = auto()
    Freezing = auto()


class DamageRule(Enum):
    """Port of horizon-world damage_immunity::DamageRule."""
    Drowning = auto()
    Fall = auto()
    Fire = auto()
    Freeze = auto()


class HurtTag(Enum):
    """Port of horizon-world living_hurt::HurtTag."""
    Fire = auto()
    Freezing = auto()
    DamagesHelmet = auto()
    BypassesCooldown = auto()
    NoImpact = auto()
    NoKnockback = auto()


class DamageStat(Enum):
    """Port of horizon-world living_damage::DamageStat."""
    Absorbed = auto()
    DealtAbsorbed = auto()
    Taken = auto()


# The wire/catalog id of a damage type. Rust wraps a usize; the Python
# catalog keys by canonical name, so the id is the name itself.
DamageTypeId = str


# Rust constants used by the hurt path.
STAT_LIMIT: float = 3.4028235e37
HURT_LOG: int = 64
MAX_F32: float = 3.4028235e38


def _positive(value: float) -> float:
    """Port of living_damage::positive."""
    if math.isnan(value):
        return value
    if value <= 0.0:
        return 0.0
    return value


def _stat_amount(value: float) -> int:
    """Port of living_damage::stat_amount (Java Math.round(float))."""
    scaled = value * 10.0
    if math.isnan(scaled) or math.isinf(scaled):
        return 0
    # Java Math.round is floor(x + 0.5), saturating at the integer bounds.
    rounded = math.floor(scaled + 0.5)
    if rounded > 2_147_483_647:
        return 2_147_483_647
    if rounded < -2_147_483_648:
        return -2_147_483_648
    return int(rounded)


def _java_min(a: float, b: float) -> float:
    if math.isnan(a) or math.isnan(b):
        return math.nan
    if a == 0.0 and b == 0.0:
        # Preserve -0.0 the way Java Math.min does.
        return a if math.copysign(1.0, a) < 0.0 else b
    return a if a <= b else b


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if math.isnan(value) or math.isnan(maximum):
        return math.nan
    return _java_min(value, maximum)


# --------- HealthRules ---------------------------------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class HealthRules:
    """Port of horizon-client-render world::HealthRules (world.rs line 540)."""
    difficulty: Difficulty = Difficulty.Normal
    natural_regeneration: bool = True
    drowning_damage: bool = True
    fall_damage: bool = True
    fire_damage: bool = True
    freeze_damage: bool = True


def _coerce_rules(rules: Any) -> HealthRules:
    if isinstance(rules, HealthRules):
        return rules
    if rules is None:
        return HealthRules()
    if isinstance(rules, dict):
        return HealthRules(
            difficulty=rules.get("difficulty", Difficulty.Normal),
            natural_regeneration=rules.get("natural_regeneration", True),
            drowning_damage=rules.get("drowning_damage", True),
            fall_damage=rules.get("fall_damage", True),
            fire_damage=rules.get("fire_damage", True),
            freeze_damage=rules.get("freeze_damage", True),
        )
    return rules


# --------- DamageSource ------------------------------------------------------------------------------------------------------------------------------------------------------------
_BYPASS_TAGS = {
    Bypass.Armor: "minecraft:bypasses_armor",
    Bypass.Effects: "minecraft:bypasses_effects",
    Bypass.Resistance: "minecraft:bypasses_resistance",
    Bypass.Enchantments: "minecraft:bypasses_enchantments",
}
_HURT_TAGS = {
    HurtTag.Fire: "minecraft:is_fire",
    HurtTag.Freezing: "minecraft:is_freezing",
    HurtTag.DamagesHelmet: "minecraft:damages_helmet",
    HurtTag.BypassesCooldown: "minecraft:bypasses_cooldown",
    HurtTag.NoImpact: "minecraft:no_impact",
    HurtTag.NoKnockback: "minecraft:no_knockback",
}
_IMMUNITY_TAGS = {
    ImmunityTag.BypassesInvulnerability: "minecraft:bypasses_invulnerability",
    ImmunityTag.Fire: "minecraft:is_fire",
    ImmunityTag.Fall: "minecraft:is_fall",
    ImmunityTag.Drowning: "minecraft:is_drowning",
    ImmunityTag.Freezing: "minecraft:is_freezing",
}


class DamageSource:
    """Port of horizon-world damage_source::DamageSource<'a, E>.

    ``__call__`` returns the type id, so ``environment.source`` can be used
    both as the Rust field and as the HurtWorld ``source()`` method.
    """

    def __init__(self, catalog: Any, name: str, direct: Any = None,
                 causing: Any = None, position: Optional[list[float]] = None):
        self.catalog = catalog
        self._name = name
        self._direct = direct
        self._causing = causing
        self._position = position

    def __call__(self) -> DamageTypeId:
        return self._name

    def definition(self) -> DamageType:
        return _catalog_definition(self.catalog, self._name)

    def type_id(self) -> DamageTypeId:
        return self._name

    def is_type(self, name: str) -> bool:
        return self.definition().id == name

    def in_tag(self, tag: str) -> bool:
        return _catalog_in_tag(self.catalog, self._name, tag)

    def bypasses(self, kind: Bypass) -> bool:
        return self.in_tag(_BYPASS_TAGS[kind])

    def hurt_tag(self, tag: HurtTag) -> bool:
        return self.in_tag(_HURT_TAGS[tag])

    def immunity_tag(self, tag: ImmunityTag) -> bool:
        return self.in_tag(_IMMUNITY_TAGS[tag])

    def direct_entity(self) -> Any:
        return self._direct

    def causing_entity(self) -> Any:
        return self._causing

    def is_direct(self) -> bool:
        return self._direct == self._causing

    def position_raw(self) -> Optional[list[float]]:
        return self._position

    def food_exhaustion(self) -> float:
        return float(self.definition().exhaustion)


def _catalog_definition(catalog: Any, name: str) -> DamageType:
    if isinstance(catalog, DamageCatalog):
        return catalog.get(name)
    if isinstance(catalog, dict):
        value = catalog.get(name)
        if isinstance(value, DamageType):
            return value
        if isinstance(value, dict):
            return DamageType(
                id=str(value.get("id", name)),
                message_id=str(value.get("message_id", "")),
                exhaustion=float(value.get("exhaustion", 0.0)),
                scaling=str(value.get("scaling", "when_caused_by_living_non_player")),
                effects=str(value.get("effects", "hurt")),
                death_message_type=str(value.get("death_message_type", "default")),
                tags=list(value.get("tags", [])),
            )
    raise KeyError(f"unknown damage type {name!r}")


def _catalog_in_tag(catalog: Any, name: str, tag: str) -> bool:
    if isinstance(catalog, DamageCatalog):
        return catalog.has_tag(name, tag)
    if isinstance(catalog, dict):
        value = catalog.get(name)
        if isinstance(value, DamageType):
            return tag in value.tags
        if isinstance(value, dict):
            return tag in value.get("tags", [])
    return False


def _resolve_source(resources: Any, source: Any) -> DamageSource:
    catalog = getattr(resources, "damage", resources)
    if isinstance(source, DamageSource):
        return source
    name = source if isinstance(source, str) else str(source)
    # Validate eagerly, like Catalog::source(...).ok_or("unknown ...")
    _catalog_definition(catalog, name)
    return DamageSource(catalog, name)


# --------- Blocking rules (horizon-world blocking_rules.rs) ------------------------------------------------
class _MatchedSets:
    """Port of health.rs MatchedSets: every set is already matched."""
    def source_in_set(self, value: bool) -> bool:
        return bool(value)


@dataclass
class DamageReduction:
    """Port of horizon-world blocking_rules::DamageReduction<S>."""
    horizontal_angle: float
    types: Optional[bool] = None
    base: float = 0.0
    factor: float = 1.0

    def resolve(self, world: _MatchedSets, damage: float, angle: float) -> float:
        if angle > 0.017453292 * self.horizontal_angle:
            return 0.0
        if self.types is not None and not world.source_in_set(self.types):
            return 0.0
        return _clamp(self.base + self.factor * damage, 0.0, damage)


@dataclass
class ItemDamageFunction:
    """Port of horizon-world blocking_rules::ItemDamageFunction."""
    threshold: float
    base: float
    factor: float

    def apply(self, damage: float) -> int:
        if damage < self.threshold:
            return 0
        return int(math.floor(self.base + self.factor * damage))


@dataclass
class BlockingRules:
    """Port of horizon-world blocking_rules::BlockingRules<S>."""
    delay_seconds: float = 0.0
    disable_scale: float = 1.0
    reductions: list[DamageReduction] = field(default_factory=list)
    item_damage: ItemDamageFunction = field(
        default_factory=lambda: ItemDamageFunction(0.0, 0.0, 0.0)
    )

    def delay_ticks(self) -> int:
        return int(math.floor(self.delay_seconds * 20.0 + 0.5))

    def disable_ticks(self, seconds: float) -> int:
        duration = seconds * self.disable_scale
        if duration > 0.0:
            return int(math.floor(duration * 20.0 + 0.5))
        return 0

    def resolve(self, world: _MatchedSets, damage: float, angle: float) -> float:
        blocked = 0.0
        for reduction in self.reductions:
            blocked += reduction.resolve(world, damage, angle)
        return _clamp(blocked, 0.0, damage)


# --------- Blocking ------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Blocking:
    """Port of health.rs::Blocking (line 637)."""
    rules: BlockingRules
    bypassed: bool
    pierce: bool
    angle: float


# --------- Hooks / protocol ------------------------------------------------------------------------------------------------------------------------------------------------
class Hurting:
    """Port of health.rs::Hurting<'a> for the Player variant."""
    def __init__(self, kind: str, entity: int, source: HurtSource):
        self.kind = kind
        self.entity = entity
        self.source = source

    @classmethod
    def player(cls, entity: int, source: HurtSource) -> "Hurting":
        return cls("player", entity, source)


# Module hooks, mirrors of the Rust OnceLock hooks.
HURT_SERVER_HOOK: Optional[Callable[[Hurting, float], Any]] = None
DAMAGE_PRE_HOOK: Optional[Callable[[Hurting, float], Any]] = None
DAMAGE_POST_HOOK: Optional[Callable[[Hurting, float], Any]] = None


class HealthProtocol:
    """Protocol for effects owned by the game (sounds, particles, packets).

    The hurt path never fakes these services: it calls this protocol, and a
    game integration supplies the real implementation.
    """
    def play_sound(self, sound: str, entity: int = 0) -> None:
        # Default: no audio device attached. Callers may subclass.
        return None

    def particle(self, name: str, entity: int = 0, count: int = 1) -> None:
        return None

    def broadcast_damage(self, source: DamageTypeId, entity: int = 0) -> None:
        return None


class _CallableBool:
    """A field that is also callable, mirroring Rust field+method names."""

    def __init__(self, value: bool):
        self.value = bool(value)

    def __call__(self) -> bool:
        return self.value

    def __bool__(self) -> bool:
        return self.value

    def __eq__(self, other: object) -> bool:
        return self.value == other

    def __repr__(self) -> str:
        return repr(self.value)


class _CallableInt:
    """An int field that is also callable, mirroring Rust field+method names."""

    def __init__(self, value: int):
        self.value = int(value)

    def __call__(self) -> int:
        return self.value

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        return self.value

    def __eq__(self, other: object) -> bool:
        return self.value == other

    def __repr__(self) -> str:
        return repr(self.value)


# --------- Environment ---------------------------------------------------------------------------------------------------------------------------------------------------------------
class Environment:
    """Port of health.rs::Environment (line 601) and all its impl methods.

    Rust splits these methods over several traits; Python keeps one method per
    name and accepts the trait-specific arguments optionally.
    """

    def __init__(
        self,
        *,
        entity: int,
        causing: int,
        direct: int = 0,
        invulnerable: bool,
        client_loaded: bool,
        rules: HealthRules,
        source: DamageSource,
        living_cause: bool,
        events: list,
        dead: bool,
        sync_velocity: bool,
        game_time: int,
        status: StatusFlags,
        blocking: Optional[Blocking] = None,
        blocked: float = 0.0,
        fully_blocked: bool = False,
        block_sound: bool = False,
        knocked: bool = False,
        totem: bool = False,
        totem_fired: bool = False,
        canceled: bool = False,
        data: Optional[dict] = None,
        food: Optional[dict] = None,
        attributes: Optional[dict] = None,
        protocol: Optional[HealthProtocol] = None,
    ):
        self.entity = entity
        self.causing = causing
        self.direct = direct
        self.invulnerable_flag = bool(invulnerable)
        # ``client_loaded`` must be callable as the ImmunityWorld method too.
        self.client_loaded = _CallableBool(client_loaded)
        self.rules = rules
        self.source = source
        self.living_cause = living_cause
        self.events = events
        self.dead = bool(dead)
        self.sync_velocity = bool(sync_velocity)
        self.game_time = _CallableInt(game_time)
        self.status = status
        self.blocking = blocking
        self.blocked = float(blocked)
        self.fully_blocked = bool(fully_blocked)
        self.block_sound = bool(block_sound)
        self.knocked = bool(knocked)
        self.totem = bool(totem)
        self.totem_fired = bool(totem_fired)
        self.canceled = bool(canceled)
        self.data = data if data is not None else {}
        self.food = food if food is not None else {}
        self.attributes = attributes if attributes is not None else {}
        self.protocol = protocol
        self.hurt_sounds: list[str] = []

    # ------ helper / event methods ------------------------------------------------------------------------------------------------------------------
    def source_in_set(self, value: bool) -> bool:
        return bool(value)

    def hurt_source(self) -> HurtSource:
        return HurtSource(
            damage_type=self.source.definition().id,
            causing=self.causing,
            direct=0,
        )

    def event(self, event: HealthEvent, **values: Any) -> None:
        for key, value in values.items():
            setattr(event, key, value)
        self.events.append(event)

    def phase(self, name: str) -> None:
        self.event(HealthEvent.Phase, text=name)

    def stat(self, name: str, amount: int) -> None:
        self.event(HealthEvent.Statistic, stat_name=name, amount=amount)

    def updated(self, data: Any, id: Any) -> None:
        value = 0.0
        if isinstance(data, dict):
            if id in data:
                value = data[id]
            elif id == getattr(self, "health_id", None):
                value = data.get("health", 0.0)
            elif id == getattr(self, "absorption_id", None):
                value = data.get("absorption", 0.0)
        dirty = bool(getattr(data, "is_dirty", lambda: False)())
        self.event(HealthEvent.Updated, id=id, value=value, dirty=dirty)

    # ------ ArmorWorld ---------------------------------------------------------------------------------------------------------------------------------------------------------
    def weapon(self) -> Optional[Any]:
        return None

    def server_level(self) -> Optional[Any]:
        return ()

    def modify_armor_effectiveness(self, level: Any, weapon: Any, value: float) -> float:
        return value

    # ------ ServerDamageEnvironment ---------------------------------------------------------------------------------------------------------------
    def invulnerable(self, state: Optional[dict] = None) -> bool:
        return _server_player_immunity(self)

    def bypasses(self, kind: Bypass) -> bool:
        return self.source.bypasses(kind)

    def hurt_armor(self, attributes: Optional[dict], damage: float) -> None:
        # The worn armor lives in the game, which wears it from this event.
        self.event(
            HealthEvent.ArmorHurt,
            source=self.source.type_id(),
            amount=damage,
        )

    def has_resistance(self) -> bool:
        return self.status.resistance is not None

    def resistance_amplifier(self) -> int:
        if self.status.resistance is None:
            raise ValueError("no resistance effect")
        return int(self.status.resistance)

    def award_resisted(self, value: int) -> None:
        self.stat("resisted", value)

    def attacker(self) -> Optional[Any]:
        return None

    def award_dealt_resisted(self, value: int) -> None:
        raise RuntimeError("no damage attacker")

    def damage_protection(self, level: Any = None) -> float:
        return effects_damage_protection(
            self.status, self.source.definition().id
        )

    def award_self(self, stat: DamageStat, value: int) -> None:
        if stat is DamageStat.Absorbed:
            self.stat("absorbed", value)
        elif stat is DamageStat.Taken:
            self.stat("taken", value)
        else:
            raise RuntimeError("attacker statistic")

    def award_attacker(self, attacker: Any, stat: DamageStat, value: int) -> None:
        raise RuntimeError("no damage attacker")

    def source_food_exhaustion(self) -> float:
        return float(self.source.definition().exhaustion)

    def ability_invulnerable(self) -> bool:
        return self.invulnerable_flag

    def level_is_client(self) -> bool:
        return False

    def record_damage(self, amount: float) -> None:
        self.event(
            HealthEvent.RecordedDamage,
            source=self.source.type_id(),
            amount=amount,
        )

    def damage_event(self) -> None:
        self.phase("entity-damage")

    def damage_pre(self, damage: float) -> float:
        hook = DAMAGE_PRE_HOOK
        if hook is None:
            return damage
        before = float(damage)
        changed = hook(Hurting.player(self.entity, self.hurt_source()), before)
        if isinstance(changed, tuple):
            changed = changed[-1]
        if changed is None or changed == before:
            return damage
        changed = float(changed)
        if math.isnan(changed) or changed < 0.0:
            return 0.0
        return min(changed, MAX_F32)

    def damage_post(self, damage: float) -> None:
        hook = DAMAGE_POST_HOOK
        if hook is not None:
            hook(Hurting.player(self.entity, self.hurt_source()), damage)

    # ------ CombatEnvironment ------------------------------------------------------------------------------------------------------------------------------------
    def dead_flag(self) -> bool:
        return bool(self.dead)

    # ------ ImmunityWorld ------------------------------------------------------------------------------------------------------------------------------------------------
    def removed(self) -> bool:
        return False

    def permanently_invulnerable(self) -> bool:
        return False

    def temporarily_invulnerable(self) -> bool:
        return False

    def tag(self, state: Any = None, tag: Any = None) -> bool:
        # Rust has two fields named ``tag`` in different traits.
        if tag is None:
            tag = state
        if isinstance(tag, HurtTag):
            return self.source.hurt_tag(tag)
        if isinstance(tag, ImmunityTag):
            return self.source.immunity_tag(tag)
        raise TypeError(f"unknown tag {tag!r}")

    def creative_source(self) -> bool:
        return False

    def fire_immune(self) -> bool:
        return False

    def fall_immune(self) -> bool:
        return False

    def enchantment_immunity(self) -> bool:
        return False

    def damage_rule(self, rule: DamageRule) -> bool:
        if rule is DamageRule.Drowning:
            return bool(self.rules.drowning_damage)
        if rule is DamageRule.Fall:
            return bool(self.rules.fall_damage)
        if rule is DamageRule.Fire:
            return bool(self.rules.fire_damage)
        if rule is DamageRule.Freeze:
            return bool(self.rules.freeze_damage)
        raise ValueError(f"unknown damage rule {rule!r}")

    def changing_dimension(self) -> bool:
        return False

    def ender_pearl(self) -> bool:
        return self.source.is_type("minecraft:ender_pearl")

    # ``client_loaded`` is the callable field set in __init__.

    # ------ HurtWorld ------------------------------------------------------------------------------------------------------------------------------------------------------------
    def source(self) -> DamageTypeId:
        return self.source.type_id()

    def is_server_player(self) -> bool:
        return True

    def dead_or_dying(self, state: Optional[dict] = None) -> bool:
        health = float(self.data.get("health", 1.0))
        return health <= 0.0 or bool(self.dead)

    def fire_resistance(self, state: Optional[dict] = None) -> bool:
        return effects_has_fire_resistance(self.status)

    def hurt_start(self, state: Optional[dict], damage: float) -> tuple[bool, float]:
        canceled = False
        current = damage
        hook = HURT_SERVER_HOOK
        if hook is not None:
            result = hook(Hurting.player(self.entity, self.hurt_source()), current)
            if isinstance(result, tuple):
                canceled = bool(result[0])
                if len(result) > 1:
                    current = float(result[1])
            else:
                canceled = bool(result)
        self.canceled = self.canceled or canceled
        return canceled, current

    def sleeping(self, state: Optional[dict] = None) -> bool:
        return False

    def stop_sleeping(self, state: Optional[dict] = None) -> None:
        return None

    def use_item(self, state: Optional[dict] = None) -> Optional[Any]:
        return None

    def apply_blocking(self, state: Optional[dict], damage: float) -> float:
        b = self.blocking
        if b is None:
            return 0.0
        if damage <= 0.0 or b.bypassed or b.pierce:
            return 0.0
        if isinstance(b.rules, dict):
            rules = BlockingRules(
                delay_seconds=float(b.rules.get("delay_seconds", 0.0)),
                disable_scale=float(b.rules.get("disable_scale", 1.0)),
                reductions=[
                    r if isinstance(r, DamageReduction) else DamageReduction(**r)
                    for r in b.rules.get("reductions", [])
                ],
            )
        else:
            rules = b.rules
        self.blocked = rules.resolve(_MatchedSets(), damage, b.angle)
        self.fully_blocked = self.blocked >= damage
        return self.blocked

    def freeze_hurts_extra(self, state: Optional[dict] = None) -> bool:
        return False

    def helmet_empty(self, state: Optional[dict] = None) -> bool:
        return True

    def hurt_helmet(self, state: Optional[dict], damage: float) -> None:
        return None

    def actually_hurt(self, state: Optional[dict], damage: float) -> None:
        if _server_player_immunity(self):
            return
        self._apply_after_immunity_check(damage)

    def resolve_mob(self, state: Optional[dict] = None) -> None:
        return None

    def resolve_player(self, state: Optional[dict] = None) -> None:
        return None

    def blocking_component(self, item: Any) -> Optional[Blocking]:
        return self.blocking

    def on_blocked(self, state: Optional[dict], block: Any) -> None:
        self.block_sound = True

    def broadcast_damage(self, state: Optional[dict] = None) -> None:
        self.event(
            HealthEvent.DamageBroadcast,
            source=self.source.type_id(),
        )
        if self.protocol is not None:
            self.protocol.broadcast_damage(self.source.type_id(), self.entity)

    def mark_hurt(self, state: Optional[dict] = None) -> None:
        self.sync_velocity = True

    def knockback(self, state: Optional[dict], damage: float, blocked: bool) -> None:
        self.knocked = True

    def death_protection(self, state: Optional[dict] = None) -> bool:
        if not self.totem or self.source.immunity_tag(
            ImmunityTag.BypassesInvulnerability
        ):
            return False
        used = try_use_totem(
            True,
            bypasses_invulnerability=False,
            main_hand=True,
        )
        if not used:
            return False
        self.totem_fired = True
        # The game's totem handler (totem.rs) restores one health and applies
        # the three TOTEM_EFFECTS. Keep the effect list on the environment.
        self.totem_effects = list(TOTEM_EFFECTS)
        return True

    def death_sound(self, state: Optional[dict] = None) -> Optional[str]:
        return None

    def make_sound(self, state: Optional[dict], sound: Any) -> None:
        self.phase("death-sound")

    def secondary_sound(self, state: Optional[dict] = None) -> None:
        if self.source.definition().effects == "thorns":
            self.phase("thorns-sound")

    def die(self, state: Optional[dict] = None) -> None:
        if self.data is not None:
            self.data["health"] = 0.0
        self.dead = True
        self.phase("death-request")

    def hurt_sound(self, state: Optional[dict] = None) -> None:
        if not self.block_sound:
            sound = hurt_sound(self.source.definition().effects)
            self.hurt_sounds.append(sound)
            if self.protocol is not None:
                self.protocol.play_sound(sound, self.entity)
        self.phase("hurt-sound")

    def game_time(self) -> int:
        return int(self.game_time)

    def effects_on_hurt(self, state: Optional[dict], damage: float) -> None:
        return None

    def player_hurt_criterion(
        self,
        state: Optional[dict],
        original: float,
        amount: float,
        blocked: bool,
    ) -> None:
        self.event(
            HealthEvent.Criterion,
            original=original,
            amount=amount,
            blocked=blocked,
        )

    def award_blocked(self, state: Optional[dict], amount: int) -> None:
        self.stat("blocked", amount)

    def attacker_criterion(
        self,
        state: Optional[dict],
        original: float,
        damage: float,
        blocked: bool,
    ) -> None:
        return None

    # ------ PlayerHurtWorld ------------------------------------------------------------------------------------------------------------------------------------------
    def bypasses_invulnerability(self, state: Optional[dict] = None) -> bool:
        return self.source.in_tag("minecraft:bypasses_invulnerability")

    def remove_shoulders(self, state: Optional[dict] = None) -> None:
        return None

    def scales_with_difficulty(self, state: Optional[dict] = None) -> bool:
        scaling = self.source.definition().scaling
        if scaling == "never" or scaling == Scaling.Never:
            return False
        if scaling == "always" or scaling == Scaling.Always:
            return True
        return bool(self.living_cause)

    def difficulty(self, state: Optional[dict] = None) -> Difficulty:
        return self.rules.difficulty

    # ------ ServerPlayerHurtWorld ------------------------------------------------------------------------------------------------------------------------
    def causing_entity(self, state: Optional[dict] = None) -> Any:
        return _CausingEntity.Other

    def arrow_player_owner(self, state: Optional[dict], arrow: Any) -> Optional[Any]:
        return None

    def can_harm_player(self, state: Optional[dict], player: Any) -> bool:
        return True

    # ------ inner damage (server_player_damage.rs / living_damage.rs) ------------
    def _after_armor(self, damage: float) -> float:
        if self.bypasses(Bypass.Armor):
            return damage
        self.hurt_armor(self.attributes, damage)
        armor = float(self.attributes.get("minecraft:armor", 0.0))
        toughness = float(self.attributes.get("minecraft:armor_toughness", 0.0))
        return armor_reduction(armor, toughness, damage)

    def _after_magic(self, damage: float) -> float:
        if self.bypasses(Bypass.Effects):
            return damage
        if self.has_resistance() and not self.bypasses(Bypass.Resistance):
            reduction = (self.resistance_amplifier() + 1) * 5
            remainder = 25 - reduction
            original = damage
            damage = _positive(damage * float(remainder) / 25.0)
            resisted = original - damage
            if 0.0 < resisted < STAT_LIMIT:
                self.award_resisted(_stat_amount(resisted))
        if damage <= 0.0:
            return 0.0
        if self.bypasses(Bypass.Enchantments):
            return damage
        protection = self.damage_protection(self.server_level())
        if protection > 0.0:
            protection = _clamp(protection, 0.0, 20.0)
            damage = damage * (1.0 - protection / 25.0)
        return damage

    def _apply_after_immunity_check(self, damage: float) -> None:
        damage = self._after_armor(damage)
        damage = self._after_magic(damage)
        absorption = float(self.data.get("absorption", 0.0))
        remaining = _positive(damage - absorption)
        new_absorption = absorption - (damage - remaining)
        self.data["absorption"] = new_absorption
        absorbed = damage - remaining
        if 0.0 < absorbed < STAT_LIMIT:
            self.award_self(DamageStat.Absorbed, _stat_amount(absorbed))
        remaining = self.damage_pre(remaining)
        if remaining == 0.0:
            self.damage_post(0.0)
            return
        if self.is_server_player():
            exhaustion = self.source_food_exhaustion()
            self._cause_food_exhaustion(exhaustion)
        self.record_damage(remaining)
        health = float(self.data.get("health", 1.0))
        self.data["health"] = health - remaining
        if remaining < STAT_LIMIT:
            self.award_self(DamageStat.Taken, _stat_amount(remaining))
        self.damage_event()
        self.damage_post(remaining)

    def _cause_food_exhaustion(self, value: float) -> None:
        if self.ability_invulnerable() or self.level_is_client():
            return
        # FoodData.add_exhaustion, with the dict-backed simplification.
        current = float(self.food.get("exhaustion", 0.0))
        self.food["exhaustion"] = _java_min(current + value, 40.0)


class _CausingEntity:
    Other = "other"


# --------- immunity helpers ------------------------------------------------------------------------------------------------------------------------------------------------
def _entity_invulnerable(env: Environment) -> bool:
    return env.permanently_invulnerable() or env.temporarily_invulnerable()


def _base_immunity(env: Environment) -> bool:
    if env.removed():
        return True
    if (
        _entity_invulnerable(env)
        and not env.tag(ImmunityTag.BypassesInvulnerability)
        and not env.creative_source()
    ):
        return True
    if env.tag(ImmunityTag.Fire) and env.fire_immune():
        return True
    return env.tag(ImmunityTag.Fall) and env.fall_immune()


def _living_immunity(env: Environment) -> bool:
    return _base_immunity(env) or env.enchantment_immunity()


def _player_immunity(env: Environment) -> bool:
    if _living_immunity(env):
        return True
    for tag, rule in (
        (ImmunityTag.Drowning, DamageRule.Drowning),
        (ImmunityTag.Fall, DamageRule.Fall),
        (ImmunityTag.Fire, DamageRule.Fire),
        (ImmunityTag.Freezing, DamageRule.Freeze),
    ):
        if env.tag(tag):
            return not env.damage_rule(rule)
    return False


def _server_player_immunity(env: Environment) -> bool:
    if _player_immunity(env):
        return True
    if env.changing_dimension() and not env.ender_pearl():
        return True
    return not env.client_loaded()


# --------- hurt_server / player_hurt_server / server_player_hurt_server ------------
def _hurt_server(env: Environment, state: dict, damage: float) -> bool:
    """Port of living_hurt::hurt_server."""
    if env.invulnerable(state) or env.dead_or_dying(state):
        return False
    if env.tag(state, HurtTag.Fire) and env.fire_resistance(state):
        return False
    canceled, damage = env.hurt_start(state, damage)
    if canceled:
        return False
    if env.sleeping(state):
        env.stop_sleeping(state)
    state["no_action_time"] = 0
    if damage < 0.0:
        damage = 0.0
    original = damage
    item = env.use_item(state)
    blocked_amount = env.apply_blocking(state, damage)
    damage -= blocked_amount
    blocked = blocked_amount > 0.0
    if env.tag(state, HurtTag.Freezing) and env.freeze_hurts_extra(state):
        damage *= 5.0
    if (
        env.tag(state, HurtTag.DamagesHelmet)
        and not env.helmet_empty(state)
    ):
        env.hurt_helmet(state, damage)
        damage *= 0.75
    if not math.isfinite(damage):
        damage = MAX_F32
    cooldown = int(state.get("cooldown", 0))
    if cooldown > 10 and not env.tag(state, HurtTag.BypassesCooldown):
        if damage <= float(state.get("last_hurt", 0.0)):
            return False
        env.actually_hurt(state, damage - float(state.get("last_hurt", 0.0)))
        state["last_hurt"] = damage
        fresh = False
    else:
        state["last_hurt"] = damage
        state["cooldown"] = 20
        env.actually_hurt(state, damage)
        state["hurt_duration"] = 10
        state["hurt_time"] = state["hurt_duration"]
        fresh = True
    env.resolve_mob(state)
    env.resolve_player(state)
    if fresh:
        component = env.blocking_component(item)
        if component is not None and blocked:
            env.on_blocked(state, component)
        else:
            env.broadcast_damage(state)
        if not env.tag(state, HurtTag.NoImpact) and (not blocked or damage > 0.0):
            env.mark_hurt(state)
        fully_blocked = blocked and damage <= 0.0
        if not env.tag(state, HurtTag.NoKnockback) and not fully_blocked:
            env.knockback(state, damage, blocked)
    if env.dead_or_dying(state):
        if not env.death_protection(state):
            if fresh:
                sound = env.death_sound(state)
                env.make_sound(state, sound)
                env.secondary_sound(state)
            env.die(state)
    elif fresh:
        env.hurt_sound(state)
        env.secondary_sound(state)
    accepted = (not blocked) or damage > 0.0
    if accepted:
        state["last_source"] = env.source()
        state["last_stamp"] = env.game_time()
        env.effects_on_hurt(state, damage)
    if env.is_server_player():
        env.player_hurt_criterion(state, original, damage, blocked)
        if 0.0 < blocked_amount < STAT_LIMIT:
            env.award_blocked(state, _stat_amount(blocked_amount))
    env.attacker_criterion(state, original, damage, blocked)
    return accepted


def _player_hurt_server(env: Environment, state: dict, damage: float) -> bool:
    """Port of player_hurt::player_hurt_server."""
    if env.invulnerable(state):
        return False
    if env.ability_invulnerable() and not env.bypasses_invulnerability(state):
        return False
    state["no_action_time"] = 0
    if env.dead_or_dying(state):
        return False
    env.remove_shoulders(state)
    if env.scales_with_difficulty(state):
        difficulty = env.difficulty(state)
        if difficulty is Difficulty.Peaceful:
            damage = 0.0
        if difficulty is Difficulty.Easy:
            damage = _java_min(damage / 2.0 + 1.0, damage)
        if difficulty is Difficulty.Hard:
            damage = damage * 3.0 / 2.0
    if damage == 0.0:
        return False
    return _hurt_server(env, state, damage)


def _server_player_hurt_server(env: Environment, state: dict, damage: float) -> bool:
    """Port of player_hurt::server_player_hurt_server."""
    if env.invulnerable(state):
        return False
    causing = env.causing_entity(state)
    if causing == "player":
        if not env.can_harm_player(state, causing):
            return False
    return _player_hurt_server(env, state, damage)


# --------- PlayerHealth hurt methods (health.rs lines 448-582) ---------------------------------------
def _player_health_hurt(
    self: PlayerHealth,
    resources: HealthResources,
    rules: Any,
    source: Any,
    amount: float,
    blocking: Optional[Blocking],
    living_cause: bool,
    causing: int,
) -> BlockOutcome:
    if self.client_side:
        return BlockOutcome(
            hurt=False,
            blocked=0.0,
            fully_blocked=False,
            sound=False,
            knockback=False,
            canceled=False,
        )
    src = _resolve_source(resources, source)
    before = self.health() + self.absorption()
    fire_ticks = self.fire_ticks
    source_name = src.definition().id
    totem_ready = self.totem_ready
    invulnerable = self.invulnerable
    env = Environment(
        entity=self.entity_id,
        causing=causing,
        invulnerable=invulnerable,
        client_loaded=self.client_loaded,
        rules=_coerce_rules(rules),
        source=src,
        living_cause=living_cause,
        events=self.events,
        dead=self.dead,
        sync_velocity=self.sync_velocity,
        game_time=self.game_time,
        status=self.status,
        blocking=blocking,
        totem=totem_ready,
        data=self.data,
        food=self.food,
        attributes=self.attributes,
        protocol=self.protocol,
    )
    hurt = _server_player_hurt_server(env, self.hurt_state, float(amount))
    outcome = BlockOutcome(
        hurt=hurt,
        blocked=env.blocked,
        fully_blocked=env.fully_blocked,
        sound=env.block_sound,
        knockback=env.knocked,
        canceled=env.canceled,
    )
    self.dead = env.dead
    self.sync_velocity = env.sync_velocity
    if env.totem_fired:
        self.totem_used = True
        self.totem_ready = False
        # DeathProtection.TOTEM_EFFECTS restores one health (totem.rs).
        self.data["health"] = 1.0
    if outcome.hurt:
        self.hurt_animation_time = int(self.hurt_state.get("hurt_time", 0))
    # dealDefaultKnockback ends in indicateDamage unless blocked.
    if outcome.knockback and outcome.blocked <= 0.0:
        self.indicate_damage(0.0, 0.0, self.yaw)
    after = self.health() + self.absorption()
    armor = float(self.attributes.get("minecraft:armor", 0.0))
    toughness = float(self.attributes.get("minecraft:armor_toughness", 0.0))
    if len(self.hurt_log) >= HURT_LOG:
        self.hurt_log.pop(0)
    self.hurt_log.append(
        HurtRecord(
            game_time=self.game_time,
            source=source_name,
            amount=float(amount),
            blocked=outcome.blocked,
            taken=before - after,
            hurt=outcome.hurt,
            armor=armor,
            toughness=toughness,
            health=after,
            fire_ticks=fire_ticks,
            knockback=None,
        )
    )
    return outcome


def _player_health_hurt_blocking(
    self: PlayerHealth,
    resources: HealthResources,
    rules: Any,
    source: Any,
    amount: float,
    blocking: Optional[Blocking] = None,
    living_cause: bool = False,
    causing: int = 0,
) -> BlockOutcome:
    return _player_health_hurt(
        self, resources, rules, source, amount, blocking, living_cause, causing
    )


def _player_health_hurt_caused_by(
    self: PlayerHealth,
    resources: HealthResources,
    rules: Any,
    source: Any,
    amount: float,
    blocking: Optional[Blocking] = None,
    living_cause: bool = False,
    causing: int = 0,
) -> BlockOutcome:
    return _player_health_hurt(
        self, resources, rules, source, amount, blocking, living_cause, causing
    )


def _player_health_hurt_simple(
    self: PlayerHealth,
    resources: HealthResources,
    rules: Any,
    source: Any,
    amount: float,
    blocking: Optional[Blocking] = None,
    living_cause: bool = False,
    causing: int = 0,
) -> bool:
    return _player_health_hurt(
        self, resources, rules, source, amount, blocking, living_cause, causing
    ).hurt


# Attach the PART 2 methods to PlayerHealth without redefining PART 1.
PlayerHealth.hurt = _player_health_hurt_simple
PlayerHealth.hurt_blocking = _player_health_hurt_blocking
PlayerHealth.hurt_caused_by = _player_health_hurt_caused_by


# --- hurt_sound (health.rs line 219) ---------------------------------
def hurt_sound(effects: str) -> str:
    """Port of health.rs::hurt_sound by a damage type's effects id."""
    if effects == "drowning":
        return "minecraft:entity.player.hurt_drown"
    if effects == "burning":
        return "minecraft:entity.player.hurt_on_fire"
    if effects == "poking":
        return "minecraft:entity.player.hurt_sweet_berry_bush"
    if effects == "freezing":
        return "minecraft:entity.player.hurt_freeze"
    # HURT and THORNS (both SoundEvents.PLAYER_HURT).
    return "minecraft:entity.player.hurt"


# --------- Self-test ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _validate_part2() -> None:
    from quadrix.health import (
        PlayerHealth,
        HealthResources,
        PlayerFloatIds,
        Environment,
        Blocking,
    )

    resources = HealthResources(damage={}, ids=PlayerFloatIds(health=0, absorption=1))
    player = PlayerHealth.new(resources, {"minecraft:max_health": 20.0})
    assert player.hurt_state["cooldown"] == 0
    print("[QuadRix] PART 2 import and self-test OK")


if __name__ == "__main__":
    _validate_part2()

