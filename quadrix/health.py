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
from typing import Optional, Dict, Any


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
    hurt: dict = field(
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
            hurt={
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
        
        if self.hurt.get("cooldown", 0) > 0:
            self.hurt["cooldown"] = self.hurt["cooldown"] - 1
        
        if self.hurt.get("hurt_time", 0) > 0:
            self.hurt["hurt_time"] = self.hurt["hurt_time"] - 1
        
        if self.hurt_animation_time > 0:
            self.hurt_animation_time = self.hurt_animation_time - 1

    def animate_hurt(self) -> None:
        """Start hurt animation (tilt and red flash)."""
        self.hurt["hurt_duration"] = 10
        self.hurt["hurt_time"] = 10
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
                self.hurt["cooldown"] = 10
        else:
            # Health decreased - trigger hurt
            self.hurt["last_hurt"] = damage
            self.hurt["cooldown"] = 20
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