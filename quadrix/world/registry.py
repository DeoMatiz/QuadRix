#!/usr/bin/env python3
"""Runtime block-state IDs imported from a version-pinned registry data export.

Port of horizon/crates/horizon-world/src/registry.rs (Minecraft 26.3).
This module reads the block-registry.nbt file and provides lookup by state,
name, and properties.
"""

from __future__ import annotations

import io
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from quadrix.world.nbt import read_nbt, Tag, TagType


# ---------------------------------------------------------------------------
# BlockStateId – wrapper around a u32 index
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class BlockStateId:
    """Per-state identity, indexed by a hash of name + properties."""
    id: int  # u32


# ---------------------------------------------------------------------------
# BlockProperties – a dict of property-name -> value, shared‑string style
# ---------------------------------------------------------------------------

@dataclass
class BlockProperties:
    """A block state's properties, replacing BTreeMap<String, String> with
    shared strings (interned like the Rust SharedStrings).

    Invariants: keys and values are always plain Python str objects.
    """

    properties: dict = field(default_factory=dict)  # str -> str

    # --- public API ---

    def get(self, key: str) -> Optional[str]:
        """Return the property *value* for *key*, or ``None`` if the key is
        absent."""
        return self.properties.get(key)

    def contains_key(self, key: str) -> bool:
        """Return *True* if *key* exists in this property bag."""
        return key in self.properties

    def __contains__(self, key: str) -> bool:
        return key in self.properties

    def __getitem__(self, key: str) -> str:
        return self.properties[key]

    def __setitem__(self, key: str, value: str) -> None:
        self.properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.properties[key]

    def __len__(self) -> int:
        return len(self.properties)

    def __iter__(self):
        return iter(self.properties)

    def items(self):
        """Return a view of (key, value) pairs."""
        return self.properties.items()

    def keys(self):
        """Return a view of keys."""
        return self.properties.keys()

    def values(self):
        """Return a view of values."""
        return self.properties.values()

    # --- hashing / equality (used as dict key / BTreeMap replacement) ---

    def __hash__(self) -> int:
        # Deterministic hash matching the Rust state_key logic.
        h = hashlib.md5()
        h.update(str(sorted(self.properties.items())).encode("utf-8"))
        return int(h.hexdigest(), 16)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BlockProperties):
            return NotImplemented
        return self.properties == other.properties

    def __str__(self) -> str:
        return str(self.properties)

    def __repr__(self) -> str:
        return f"BlockProperties({self.properties!r})"


# ---------------------------------------------------------------------------
# BlockState – name + properties
# ---------------------------------------------------------------------------

@dataclass
class BlockState:
    """A per-block-state identity: name + properties."""

    name: str
    properties: BlockProperties = field(default_factory=BlockProperties)

    # --- NBT reading ---

    @classmethod
    def from_nbt(cls, tag: Tag) -> "BlockState":
        """Read a ``BlockState`` from an NBT ``Tag``.

        The NBT tag may be:
        * a plain ``Tag::String`` – just the state name (e.g. ``"minecraft:air"``),
        * a ``Tag::Compound`` with an ``id`` key (string) and an optional
          ``properties`` compound.
        """
        # Case 1: plain string tag (e.g. the list‑element format some NBTs use)
        if tag.is_string:
            name = tag.str_val if tag.str_val else ""
            return cls(name=name, properties=BlockProperties())

        # Case 2: compound tag with ``id`` and optional ``properties``
        if tag.is_compound:
            # Read the ``id`` field – required
            id_tag = tag.compound_val.get("id") if tag.compound_val else None
            if id_tag is None or not id_tag.is_string:
                raise ValueError("block state is missing id")

            name = id_tag.str_val if id_tag.str_val else ""
            properties_dict: dict = {}

            # Read optional ``properties`` compound
            props_tag = tag.compound_val.get("properties") if tag.compound_val else None
            if props_tag is not None and props_tag.is_compound:
                for prop_key, prop_val in props_tag.compound_val.items():
                    # Property values are stored as strings in NBT
                    prop_str = prop_val.str_val if prop_val.str_val else ""
                    properties_dict[prop_key] = prop_str

            props = BlockProperties(properties=properties_dict)
            return cls(name=name, properties=props)

        raise ValueError("unrecognised block state tag format")

    # --- human‑readable / NBT writing ---

    def to_nbt(self) -> Tag:
        """Return a minimal NBT compound ``{id: "name"}`` for this state."""
        return Tag(
            tag_type=TagType.String,
            str_val=self.name,
        )


# ---------------------------------------------------------------------------
# BlockRegistry – the main registry type
# ---------------------------------------------------------------------------

DATA_VERSION: int = 5023


def _state_key(state: BlockState) -> int:
    """Compute a hash key for a block state.

    Matches the Rust ``state_key``: hashes the state name and all property
    key/value pairs.
    """
    h = hashlib.md5()
    h.update(state.name.encode("utf-8"))
    for key, value in sorted(state.properties.items()):
        h.update(key.encode("utf-8"))
        h.update(value.encode("utf-8"))
    return int(h.hexdigest(), 16)


class BlockRegistry:
    """Runtime block-state IDs imported from a version-pinned registry data
    export.

    This is the Python equivalent of ``horizon-world::registry::BlockRegistry``.
    It reads the ``block-registry.nbt`` file and supports lookup by state,
    name, and property values.
    """

    def __init__(
        self,
        states: List[BlockState],
        ids: Dict[int, int],        # hash -> index in ``states``
        collided: Dict[int, BlockStateId],  # hash -> BlockStateId for collisions
        defaults: Dict[str, BlockStateId],  # name -> BlockStateId
    ) -> None:
        self.states = states
        self.ids = ids
        self.collided = collided
        self.defaults = defaults

    # --- construction from NBT ---

    @classmethod
    def from_nbt(cls, tag: Tag) -> "BlockRegistry":
        """Read a ``BlockRegistry`` from an NBT compound tag.

        The NBT must have the following shape (mirrors Rust's ``from_nbt``):

        * ``DataVersion`` – ``Tag::Int`` must equal ``DATA_VERSION``.
        * ``states`` – ``Tag::List`` of state compound tags; each state has
          an ``id`` key (string) and optional ``properties`` compound.
        * ``defaults`` – ``Tag::Compound`` mapping state *names* (strings) to
          state *IDs* (ints).
        """
        # --- DataVersion check ---
        if tag.compound_val is None:
            raise ValueError("tag has no compound_val")
        dv_tag = tag.compound_val.get("DataVersion")
        if dv_tag is None or not dv_tag.is_int:
            raise ValueError("missing registry DataVersion")
        if dv_tag.int_val != DATA_VERSION:
            raise ValueError(
                f"block registry DataVersion mismatch (expected {DATA_VERSION}, got {dv_tag.int_val})"
            )

        # --- Read states list ---
        states_tag = tag.compound_val.get("states")
        if states_tag is None or not states_tag.is_list:
            raise ValueError("missing registry states")

        states_list = states_tag.list_val
        states: List[BlockState] = []
        for st in states_list:
            state = BlockState.from_nbt(st)
            states.append(state)

        # --- Read defaults compound ---
        defaults_tag = tag.compound_val.get("defaults")
        if defaults_tag is None or not defaults_tag.is_compound:
            raise ValueError("missing registry defaults")

        defaults_map: Dict[str, BlockStateId] = {}
        for name_tag, id_tag in defaults_tag.compound_val.items():
            # name_tag is already a Python str (Java UTF-8 decoded)
            name = str(name_tag)

            if id_tag is None or not id_tag.is_int:
                raise ValueError("default state ID is not an int")
            id_val = id_tag.int_val
            defaults_map[name] = BlockStateId(id_val)

        # --- Build the index (``ids`` + ``collided``) ---
        ids_map: Dict[int, int] = {}        # hash -> first index
        collided_map: Dict[int, BlockStateId] = {}  # hash -> BlockStateId for later states

        for i, state in enumerate(states):
            key = _state_key(state)
            if key in ids_map:
                # Collision: this hash was already seen – store in collided map
                collided_map[key] = BlockStateId(i)
            else:
                ids_map[key] = i

        # --- Validate defaults against actual states ---
        for name, desired_id in defaults_map.items():
            if desired_id.id < 0 or desired_id.id >= len(states):
                raise ValueError(
                    f"invalid default block state ID {desired_id.id} for name '{name}'"
                )
            actual_state = states[desired_id.id]
            if actual_state.name != name:
                raise ValueError(
                    f"default state ID {desired_id.id} points to '{actual_state.name}', "
                    f"not '{name}'"
                )

        return cls(
            states=states,
            ids=ids_map,
            collided=collided_map,
            defaults=defaults_map,
        )

    # --- public API ---

    def len(self) -> int:
        """Return the number of states in the registry."""
        return len(self.states)

    def is_empty(self) -> bool:
        """Return *True* if the registry has no states."""
        return len(self.states) == 0

    def state(self, id: BlockStateId) -> Optional[BlockState]:
        """Return the ``BlockState`` for *id*, or ``None`` if out of range."""
        if id.id < 0 or id.id >= len(self.states):
            return None
        return self.states[id.id]

    def id(self, state: BlockState) -> Optional[BlockStateId]:
        """Return the ``BlockStateId`` for *state*, or ``None`` if not found.

        The lookup follows the same strategy as Rust:
        1. Hash *state* and look it up in the ``ids`` map.
        2. If the hash matches but the stored state differs, fall through
           to the ``collided`` map.
        3. If nothing matches, return ``None``.
        """
        key = _state_key(state)
        # Step 1: direct hash lookup
        maybe_id = self.ids.get(key)
        if maybe_id is not None and maybe_id < len(self.states):
            if self.states[maybe_id] == state:
                return BlockStateId(maybe_id)

        # Step 2: check collided map (same hash, different state)
        # The collided map is keyed by hash -> BlockStateId of the *first* state
        # that had that hash. We check if any collided entry's state matches.
        for bid in self.collided.values():
            if bid.id < len(self.states) and self.states[bid.id] == state:
                return bid

        # Step 3: nothing matched
        return None

    def default_state(self, name: str) -> Optional[BlockStateId]:
        """Return the ``BlockStateId`` for the default state called *name*,
        or ``None`` if the name is not a known default."""
        return self.defaults.get(name)

    def property_values(self, block: str, property: str) -> List[str]:
        """Return all distinct values that *property* takes on *block*, in the
        order they first appear in the state list.

        This mirrors vanilla's ``StateDefinition`` ordering.
        """
        values: List[str] = []
        seen: set = set()
        for state in self.states:
            if state.name == block:
                val = state.properties.get(property)
                if val is not None and val not in seen:
                    seen.add(val)
                    values.append(val)
        return values

    def resolve(self, descriptor: BlockState) -> BlockStateId:
        """Resolve a saved descriptor, supplying omitted default properties.

        ``descriptor`` must have ``name`` set; any missing properties default
        to the registry's default for that block name.

        Raises ``ValueError`` if the descriptor is invalid.
        """
        default = self.default_state(descriptor.name)
        if default is None:
            raise ValueError(f"unknown block name: {descriptor.name!r}")

        # Start from the default state for this block name
        state = self.state(default)
        if state is None:
            raise ValueError(f"default state unavailable for name: {descriptor.name!r}")

        # Overlay the descriptor's properties on top of the default state
        if descriptor.properties is not None and len(descriptor.properties.properties) > 0:
            # shallow merge: descriptor properties override defaults
            merged_props = dict(state.properties.properties)
            merged_props.update(descriptor.properties.properties)
            # Replace the state's properties with the merged version
            state = BlockState(
                name=state.name,
                properties=BlockProperties(properties=merged_props),
            )

        # Now look up the resulting state
        result = self.id(state)
        if result is None:
            raise ValueError("invalid block property value")
        return result


# ---------------------------------------------------------------------------
# Convenience helper: load from the .local/horizon-client-motion path
# ---------------------------------------------------------------------------

def load_registry(nbt_path: str | Path) -> BlockRegistry:
    """Load a ``BlockRegistry`` from an NBT file.

    The *nbt_path* is resolved relative to the QuadRix ``.local/`` layout,
    e.g. ``".local/horizon-client-motion/block-registry.nbt"``.
    """
    path = Path(nbt_path).resolve()
    raw = path.read_bytes()
    tag_dict = read_nbt(raw)  # returns Dict[str, Tag]
    # The root NBT compound contains DataVersion, states, defaults
    # wrap it so from_nbt can find the top‑level keys
    root_tag = Tag(
        tag_type=TagType.Compound,
        compound_val=tag_dict,
    )
    return BlockRegistry.from_nbt(root_tag)


# Backward‑compatible alias matching the Rust API pattern
BlockRegistry.load = staticmethod(load_registry)  # type: ignore[assignment]