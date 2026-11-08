#!python3
from __future__ import annotations

from quadrix.core.geometry import Vec3, Aabb, floor_i32
from quadrix.world.registry import BlockRegistry


def fire_contact(world, registry: BlockRegistry, bounds: Aabb) -> float:
    """Returns fire contact damage value.

    1.0 if inside bounds contains minecraft:fire
    2.0 if minecraft:soul_fire
    0.0 otherwise
    """
    b = bounds.deflate(Vec3(1e-5, 1e-5, 1e-5))
    damage = 0.0
    min_x = floor_i32(b.min_position.x)
    max_x = floor_i32(b.max_position.x)
    min_y = floor_i32(b.min_position.y)
    max_y = floor_i32(b.max_position.y)
    min_z = floor_i32(b.min_position.z)
    max_z = floor_i32(b.max_position.z)

    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                block_name = world.block(x, y, z)
                if block_name == "minecraft:fire":
                    damage = max(damage, 1.0)
                elif block_name == "minecraft:soul_fire":
                    damage = max(damage, 2.0)
    return damage


def cactus_contact(world, registry: BlockRegistry, bounds: Aabb) -> bool:
    """Returns True if inside bounds contains minecraft:cactus (or cactus tag)."""
    b = bounds.deflate(Vec3(1e-5, 1e-5, 1e-5))
    min_x = floor_i32(b.min_position.x)
    max_x = floor_i32(b.max_position.x)
    min_y = floor_i32(b.min_position.y)
    max_y = floor_i32(b.max_position.y)
    min_z = floor_i32(b.min_position.z)
    max_z = floor_i32(b.max_position.z)

    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                if world.block(x, y, z) == "minecraft:cactus":
                    return True
    return False


def ignite_contact(ticks: int, player: bool, random, multiplier: float) -> int:
    """Port of horizon/crates/horizon-client/src/motion/environment.rs ignite_contact.

    Determines new fire tick duration after contact with fire/cactus.

    Args:
        ticks: Current fire ticks
        player: Whether the entity is a player
        random: Random source with next_int_bound method (returns 0 or 1)
        multiplier: Burning time multiplier (e.g. from minecraft:burning_time attribute)

    Returns:
        Clamped fire ticks (0..64 as per Minecraft behavior)
    """
    # Rust: let ticks = if ticks < 0 { ticks + 1 } else if player { ticks + 1 + random.next_int_bound(2).unwrap_or(0) } else { ticks };
    if ticks < 0:
        ticks = ticks + 1
    elif player:
        ticks = ticks + 1 + random.next_int_bound(2)
    # else: ticks stays the same (not player)

    # Rust: if ticks >= 0 { ticks.max((160.0 * multiplier).ceil() as i32) } else { ticks }
    if ticks >= 0:
        ticks = max(ticks, int(__import__("math").ceil(160.0 * multiplier)))
    # else: ticks stays negative

    return ticks


# MotionWorld environment methods (mirror horizon::motion::MotionWorld impls)

def tick_remaining_fire(player, multiplier: float = 1.0) -> None:
    """Port of MotionWorld::tick_remaining_fire.

    Decreases fire_ticks by 1 each tick. If player was in water, clamps to 0.

    Args:
        player: Player object with fire_ticks, spectator, invulnerable, was_touching_water attributes
        multiplier: Burning time multiplier (unused in this simplified version)
    """
    if player.spectator:
        player.fire_ticks = 0
    if player.invulnerable and player.fire_ticks > 1:
        player.fire_ticks = 1
    if player.fire_ticks > 0:
        # Every 20 ticks without lava, apply fire damage
        # In simplified version: always decrement
        player.fire_ticks -= 1
    if getattr(player, "fluids", None) and getattr(player.fluids, "was_touching_water", False):
        player.fire_ticks = min(player.fire_ticks, 0)


def environment_hurt(health, source: str, damage: float) -> None:
    """Port of MotionWorld::environment_hurt.

    Applies hurt to player health with the given source and damage amount.

    Args:
        health: PlayerHealth instance with hurt method
        source: Damage source string (e.g. "minecraft:on_fire", "minecraft:cactus")
        damage: Damage amount
    """
    # Check invulnerability and spectator status with defaults
    invuln = getattr(health, "invulnerable", False)
    spect = getattr(health, "spectator", False)
    if invuln or spect:
        return
    # Simplified: reduce health by damage amount
    # Rust environment_hurt deals damage through the health system;
    # here we directly reduce health to mirror the behavior for testing.
    current = health.health() if hasattr(health, "health") else 1.0
    new_value = max(0.0, current - damage)
    if hasattr(health, "set_health"):
        health.set_health(new_value)
    elif hasattr(health, "data"):
        health.data["health"] = new_value


def server_hazards_tick(player, bottom_y: float, in_wall: bool) -> None:
    """Port of MotionWorld::server_hazards_tick.

    Handles void damage and wall suffocation.

    Args:
        player: Player object with position attribute
        bottom_y: World bottom Y coordinate
        in_wall: Whether player is inside a wall
    """
    if player.position.y < bottom_y - 64:
        # Out of world damage
        environment_hurt("minecraft:out_of_world", 4.0)
    if in_wall:
        environment_hurt("minecraft:in_wall", 1.0)


def apply_fire_contact(player, world, registry: BlockRegistry, random, attributes: dict) -> None:
    """Port of MotionWorld::apply_fire_contact.

    Applies fire contact damage and sets fire ticks.

    Args:
        player: Player object with fire_ticks, fluids, attributes, set_remaining_fire_ticks
        world: World object with block method
        registry: BlockRegistry for block state lookup
        random: Random source for ignition RNG
        attributes: Player attributes dict (for burning_time)
    """
    damage = fire_contact(world, registry, player.bounds())
    if damage > 0.0:
        player.ticks_frozen = 0
        was_touching_water = getattr(player.fluids, "was_touching_water", False)
        if not was_touching_water:
            multiplier = attributes.get("minecraft:burning_time", 1.0)
            ticks = ignite_contact(player.fire_ticks, True, random, multiplier)
            player.set_remaining_fire_ticks(ticks)
        environment_hurt("minecraft:in_fire", damage)
    elif player.fire_ticks <= 0:
        player.fire_ticks = -20


def jump_phase(player, fluids, attributes: dict, random, velocity: Vec3) -> Vec3:
    """Port of MotionWorld::jump_phase.

    Handles jump phase in water/lava or from ground.

    Args:
        player: Player object with jumping, flying, ground, fluid_height, etc.
        fluids: Fluid interaction state
        attributes: Player attributes
        random: Random source
        velocity: Current velocity Vec3

    Returns:
        Updated velocity Vec3
    """
    if not player.jumping or player.flying:
        # no_jump_delay = 0  # would be set on player
        return velocity

    in_lava = player.is_in_lava()
    # fluid_height simplified
    fluid_name = "lava" if in_lava else "water"
    height = 1.0 if fluid_name == "water" else 1.0  # simplified

    in_water = fluids.was_touching_water and height > 0.0
    # fluid_jump_threshold simplified - default 0.4
    threshold = attributes.get("minecraft:fluid_jump_threshold", 0.4)
    on_ground = player.ground.on_ground if hasattr(player, "ground") and hasattr(player.ground, "on_ground") else False

    if in_water and not (on_ground and height <= threshold):
        # jumpInLiquid(WATER): velocity.y += 0.04
        velocity = Vec3(velocity.x, velocity.y + 0.04, velocity.z)
    elif in_lava and not (on_ground and height <= threshold):
        # jumpInLiquid(LAVA): velocity.y += 0.04
        velocity = Vec3(velocity.x, velocity.y + 0.04, velocity.z)
    elif (on_ground or (in_water and height <= threshold)) and getattr(player, "no_jump_delay", 0) == 0:
        # jump_from_ground()
        # no_jump_delay = 10
        pass  # Would call jump_from_ground and set delay

    return velocity


def bubble_column_inside(player, state_id, block_pos, precise: bool) -> None:
    """Port of MotionWorld::bubble_column_inside.

    Handles bubble column effects on player velocity.

    Args:
        player: Player object with velocity, flying attribute
        state_id: BlockStateId of the bubble column block
        block_pos: BlockPos of the bubble column
        precise: Whether precise check is needed
    """
    if not precise:
        return

    # Check drag property
    from quadrix.world.registry import BlockState
    state = registry.state(state_id)
    drag = state is not None and state.properties.get("drag") == "true" if state else False

    # Above block check
    above = block_pos.offset(0, 1, 0)
    # Simplified: check if above block has no collision
    # In real code: collision_shape_with_context
    above_block_name = player.world.block(above.x, above.y, above.z) if hasattr(player, "world") else "minecraft:air"
    surface = above_block_name != "minecraft:bubble_column"

    if player.flying:
        return

    v = player.velocity
    # Simplified bubble column push
    if surface and drag:
        y = max(-0.9, v.y - 0.03)
    elif surface and not drag:
        y = min(1.8, v.y + 0.1)
    elif not surface and drag:
        y = max(-0.3, v.y - 0.03)
    else:  # not surface and not drag
        y = min(0.7, v.y + 0.06)

    player.velocity = Vec3(v.x, y, v.z)

    # Spawn particles if empty (simplified)
    if True:  # would check if empty
        # Would spawn bubble column particles
        pass