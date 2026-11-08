# Ported from horizon/crates/horizon-client/src/game/totem.rs
#
# Only the death-protection data path is ported here: whether a totem is held,
# consuming it, surviving at 1 health and applying the totem's three effects.
# The animation, particles, audio, gamepad rumble and item-render geometry in
# totem.rs are rendering concerns and are intentionally not ported.
#
# SKIP: rendering, not needed for hurt()

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ``totem.rs`` line 13.
TOTEM = "minecraft:totem_of_undying"

# ``EntityEvent.TOTEM_OF_UNDYING`` (totem.rs line 16).
TOTEM_EVENT = 35

# ``DeathProtection.TOTEM_EFFECTS`` (totem.rs lines 72-76).
# Ordered exactly as Rust applies them: regeneration, absorption, fire
# resistance. ``duration`` is in ticks, ``amplifier`` is 0-based.
TOTEM_EFFECTS: tuple["TotemEffect", ...] = ()


@dataclass(frozen=True)
class TotemEffect:
    """One entry of ``DeathProtection.TOTEM_EFFECTS``.

    The fields match the ``EffectInstance`` data that the Rust code constructs
    (id, ticks, amplifier). Potions are not implemented here; this is the
    minimal effect record the death-protection path needs.
    """

    id: str
    duration: int
    amplifier: int


TOTEM_EFFECTS = (
    TotemEffect("regeneration", 900, 1),
    TotemEffect("absorption", 100, 1),
    TotemEffect("fire_resistance", 800, 0),
)


@dataclass
class TotemUse:
    """What the server's half of a fired totem did.

    Mirrors the state changes in ``Game::apply_totem`` (totem.rs lines 31-82):
    the effect list is cleared first, health becomes 1.0, the totem is used up
    (main hand first, then offhand) and entity event 35 is emitted.
    """

    used: bool
    health: float
    effects: list[TotemEffect] = field(default_factory=list)
    event: int = TOTEM_EVENT
    hand: Optional[str] = None
    item: str = TOTEM


def use_totem(
    has_totem: bool,
    *,
    bypasses_invulnerability: bool = False,
    main_hand: bool = True,
) -> Optional[TotemUse]:
    """``LivingEntity.checkTotemDeathProtection`` for the player.

    Returns ``None`` when death protection does not fire, otherwise a
    ``TotemUse`` describing the consumed totem, the new health and the effects.

    The void and ``/kill`` carry ``BYPASSES_INVULNERABILITY`` and ignore a
    totem (mobs.rs line 3918 and health.rs lines 969-976).
    """
    if bypasses_invulnerability:
        return None
    if not has_totem:
        return None
    # ``getItemInHand``: the main hand is checked first, then the off hand
    # (totem.rs lines 47-55, mobs.rs lines 3924-3932).
    hand = "main_hand" if main_hand else "off_hand"
    # ``setHealth(1.0F)`` then ``DeathProtection.TOTEM_EFFECTS``; the existing
    # effects are cleared before the totem's are added (totem.rs lines 70-80).
    return TotemUse(
        used=True,
        health=1.0,
        effects=list(TOTEM_EFFECTS),
        event=TOTEM_EVENT,
        hand=hand,
    )


def try_use_totem(
    has_totem: bool,
    *,
    bypasses_invulnerability: bool = False,
    main_hand: bool = True,
) -> bool:
    """Boolean wrapper used by the hurt path.

    ``True`` means the hit was survived at 1 health, the totem was used up and
    the totem effects were applied; ``False`` means normal damage handling
    continues (no totem, or a source that bypasses invulnerability).
    """
    return use_totem(
        has_totem,
        bypasses_invulnerability=bypasses_invulnerability,
        main_hand=main_hand,
    ) is not None


def totem_effect_ids() -> tuple[str, ...]:
    """The effect ids a fired totem applies, in application order."""
    return tuple(effect.id for effect in TOTEM_EFFECTS)
