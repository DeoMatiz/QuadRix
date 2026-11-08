# Ported from horizon/crates/horizon-client-render/src/effects.rs
# Only the StatusFlags data type and its pure data helpers are ported here.
# The rest of effects.rs (EffectInstance, PlayerEffects ticking, potions) is
# gameplay bookkeeping and belongs to a later session.
#
# Rendering is deliberately out of scope:
# SKIP: rendering, not needed for hurt()

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StatusFlags:
    """Effect and equipment facts the movement and damage kernels query.

    Port of ``StatusFlags`` from effects.rs line 399. The Rust struct derives
    ``Clone``, ``Debug`` and ``Default``; the dataclass defaults below are that
    ``Default`` implementation.

    Fields line-for-line from Rust:
        jump_boost: Option<i32>
        slow_falling: bool
        levitation: Option<i32>
        resistance: Option<i32>       # amplifier, None = no resistance effect
        fire_resistance: bool
        dolphins_grace: bool
        weaving: bool                 # cobwebs hold half as much
        water_breathing: bool         # water_breathing or conduit_power
        breath_of_the_nautilus: bool
        protection: Vec<(String, f32)>

    Additional amplifier/amount fields required by the health hurt() path
    (PART 2) are appended with harmless defaults:
        speed, slowness, poison, wither, regeneration, absorption
    """

    jump_boost: Optional[int] = None
    slow_falling: bool = False
    levitation: Optional[int] = None
    resistance: Optional[int] = None
    fire_resistance: bool = False
    dolphins_grace: bool = False
    weaving: bool = False
    water_breathing: bool = False
    breath_of_the_nautilus: bool = False
    # EnchantmentHelper.getDamageProtection: per damage-type id.
    protection: list[tuple[str, float]] = field(default_factory=list)

    # Health hurt() amplifiers / amounts. Rust stores these in other types, so
    # they default to "no effect" here and never change existing behaviour.
    speed: Optional[int] = None
    slowness: Optional[int] = None
    poison: Optional[int] = None
    wither: Optional[int] = None
    regeneration: Optional[int] = None
    absorption: float = 0.0

    def protection_for(self, damage_type: str) -> float:
        """``StatusFlags::protection`` (effects.rs line 414).

        Returns the protection points registered for ``damage_type``, or 0.0
        when the damage type is absent.
        """
        for kind, points in self.protection:
            if kind == damage_type:
                return float(points)
        return 0.0

    # The Rust method is named ``protection``. A field and a method cannot share
    # a name in Python, so the dataclass field keeps the Rust name and the
    # lookup keeps the same behaviour under ``protection_for``; the module-level
    # ``damage_protection`` helper exposes the Rust call shape as well.
    def has_resistance(self) -> bool:
        """``ServerDamageEnvironment::has_resistance`` (health.rs line 769)."""
        return self.resistance is not None

    def resistance_amplifier(self) -> int:
        """``ServerDamageEnvironment::resistance_amplifier`` (health.rs line 772).

        Mirrors the Rust error path: asking without the effect raises.
        """
        if self.resistance is None:
            raise ValueError("no resistance effect")
        return int(self.resistance)

    def has_fire_resistance(self) -> bool:
        """Fire Resistance makes the player immune to fire damage."""
        return bool(self.fire_resistance)


def has_resistance(status: StatusFlags) -> bool:
    """Module-level form of ``StatusFlags::has_resistance``."""
    return status.has_resistance()


def resistance_amplifier(status: StatusFlags) -> int:
    """Module-level form of ``StatusFlags::resistance_amplifier``.

    Returns the Resistance amplifier (0 = level I, 1 = level II, ...).
    Raises ``ValueError`` when the status has no Resistance effect, exactly
    like the Rust ``ok_or_else(|| io::Error::other("no resistance effect"))``.
    """
    return status.resistance_amplifier()


def has_fire_resistance(status: StatusFlags) -> bool:
    """Module-level form of ``StatusFlags::has_fire_resistance``."""
    return status.has_fire_resistance()


def damage_protection(status: StatusFlags, damage_type: str) -> float:
    """``StatusFlags::protection`` lookup, with the Rust call shape."""
    return status.protection_for(damage_type)
